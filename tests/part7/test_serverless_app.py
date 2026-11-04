"""serverless-compute.md AC-SC3 to AC-SC6, AC-SC19: what deploy/serverless/part2_app.py declares, read from its source. Importing
it needs Modal's client and Part 2's checkout, and a real deploy is the runbook's job (docs/prod/serverless-real-take.md)."""

from __future__ import annotations

import ast
from pathlib import Path
import re
import sys
import types
from unittest.mock import MagicMock

import pytest

from part7 import config, licence_gates, serverless_route

ROOT = Path(__file__).resolve().parents[2]
APP = (ROOT / "deploy/serverless/part2_app.py").read_text(encoding="utf-8")
CLIENT = (ROOT / "deploy/serverless/p2_client.py").read_text(encoding="utf-8")


def _constant(source: str, name: str) -> object:
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    return ast.literal_eval(node.value)
                if isinstance(target, ast.Tuple) and isinstance(node.value, ast.Tuple):
                    for t, v in zip(target.elts, node.value.elts, strict=True):
                        if isinstance(t, ast.Name) and t.id == name:
                            return ast.literal_eval(v)
    raise AssertionError(name)


def _constant_default(env: str) -> str:
    found = re.search(rf'os\.environ\.get\("{env}", "([^"]+)"\)', APP)
    assert found, env
    return found.group(1)


@pytest.mark.parametrize("word", ["simon-meta", "simon-hf", "api-sam31", "sam31_warm", "HF_TOKEN", "META_API"])
def test_nothing_in_the_app_can_send_frames_to_meta(word: str) -> None:
    assert word not in APP.replace("api-sam31 is", "")


def test_the_warm_tracker_script_is_gone() -> None:
    assert not (ROOT / "deploy/serverless/sam31_warm.py").exists()


def test_the_container_runs_local_open_and_refuses_another() -> None:
    assert 'PART2_TRACKER' in APP and "local-open" in APP and "_tracker_refused" in APP
    assert licence_gates.PROD_TRACKERS == ("local-open",)
    assert _constant(CLIENT, "ONLY_TRACKER") == "local-open"


def test_scale_settings() -> None:
    assert _constant_default("SIMON_MODAL_GPU") == "L40S" and APP.count("gpu=GPU") == 2
    assert re.search(r"scaledown_window=\w+", APP) and re.search(r"max_containers=\w+", APP)
    assert "memory=MEMORY_MIB," in APP and int(re.search(r"^MEMORY_MIB = (\d+)$", APP, re.M).group(1)) >= 32768  # 10 fps peaked at 21,527 MiB
    assert "SIMON7_SERVERLESS_MAX_CONCURRENT" in APP and "SIMON_MODAL_REGION" in APP
    assert 'version=2' in APP


def test_the_store_route_takes_a_key_and_no_media() -> None:
    tree = ast.parse(APP)
    found = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "run_part2_store"]
    assert len(found) == 1
    assert [a.arg for a in found[0].args.args] == ["self", "key", "argv", "names", "expected_sha"]
    assert "bytes" not in ast.dump(found[0].args)


def test_the_client_never_asks_for_a_pickled_result_on_this_route() -> None:
    for name in ("run_server", "transcribe_server", "check_deploy", "delete_listed"):
        body = next(n for n in ast.walk(ast.parse(CLIENT)) if isinstance(n, ast.FunctionDef) and n.name == name)
        text = ast.get_source_segment(CLIENT, body) or ""
        assert ".get(" not in text.replace("doc.get(", "").replace('.get("version")', ""), name
        assert "remote_gen" not in text


def test_a_cron_removes_what_a_crash_left_behind_and_keeps_the_stamp() -> None:
    assert "sweep_store" in APP and "modal.Period" in APP
    assert "deploy.json" not in APP or "IO_KEY_RE" in APP
    assert _constant(CLIENT, "DEPLOY_STAMP") == "deploy.json"


def test_constants_shared_across_the_three_files_agree() -> None:
    assert _constant(CLIENT, "BUSY_EXIT") == serverless_route.BUSY_EXIT == 79
    assert _constant(CLIENT, "STOPPED_EXIT") == serverless_route.STOPPED_EXIT == 80
    assert _constant(CLIENT, "STORE_VOLUME") == _constant(APP, "STORE_VOLUME_NAME")
    assert _constant(CLIENT, "APP_NAME") == _constant(APP, "APP_NAME")
    assert config.serverless_queue_wait_s() == _constant(CLIENT, "QUEUE_WAIT_S")


def test_the_container_measures_what_the_runbook_asks_for() -> None:
    for name in _constant(CLIENT, "MEASURES"):  # type: ignore[union-attr]
        assert f'"{name}"' in APP, name


def test_first_real_build_fixes_stay() -> None:
    """Found by the first real deploy (docs/prod/serverless-real-take.md): the caption image's undeclared import, a false
    `+dirty` stamp from the files left out of the image, and a peak RAM read from a field Modal's kernel does not give."""
    assert '"av==15.1.0"' in APP  # unpinned, av 19 made every captions call fail with a TypeError
    assert "requests==" in APP and "huggingface_hub==" in APP and ".pip_install(*ASR_PACKAGES)" in APP
    assert "--skip-worktree" in APP
    assert "VmRSS" in APP and "max(gpu_peak.ram, _peak_ram_mib(" in APP


def test_a_finished_call_writes_its_result_whole_and_last() -> None:
    """A background commit must never show an empty result.json (first real take), and what it announces is visible first."""
    assert 'result.json").write_text' not in APP and 'metrics.json").write_text' not in APP
    assert "os.replace(tmp, path)" in APP
    body = APP[APP.index("def run_part2_store"):APP.index("def _run(self")]
    assert body.index('"metrics.json"') < body.index("STORE_VOLUME.commit()  # everything") < body.index('"result.json"')


def test_part2_app_imports_given_a_container_whose_image_sets_no_part2_sha(monkeypatch: pytest.MonkeyPatch) -> None:  # AC-SC15
    """`Transcribe` runs on `asr_image`, which sets no PART2_SHA. Prod: KeyError at import, Modal crash-looped the class,
    no call ever wrote `result.json`, and every trainer take waited out the captions budget and lost its sound."""
    head = APP[:APP.index("# Supply audit R7")]
    fake = types.ModuleType("modal")
    fake.is_local = lambda: False  # type: ignore[attr-defined]
    fake.__getattr__ = lambda name: MagicMock()  # type: ignore[attr-defined,method-assign]
    monkeypatch.setitem(sys.modules, "modal", fake)
    monkeypatch.delenv("PART2_SHA", raising=False)
    found: dict[str, object] = {"__name__": "part2_app", "__file__": str(ROOT / "deploy/serverless/part2_app.py")}
    exec(compile(head, "part2_app.py", "exec"), found)
    assert found["PART2_SHA"] == ""


def test_part2_app_reads_the_sha_given_the_worker_image_sets_it(monkeypatch: pytest.MonkeyPatch) -> None:  # negative
    head = APP[:APP.index("# Supply audit R7")]
    fake = types.ModuleType("modal")
    fake.is_local = lambda: False  # type: ignore[attr-defined]
    fake.__getattr__ = lambda name: MagicMock()  # type: ignore[attr-defined,method-assign]
    monkeypatch.setitem(sys.modules, "modal", fake)
    monkeypatch.setenv("PART2_SHA", "a" * 40)
    found: dict[str, object] = {"__name__": "part2_app", "__file__": str(ROOT / "deploy/serverless/part2_app.py")}
    exec(compile(head, "part2_app.py", "exec"), found)
    assert found["PART2_SHA"] == "a" * 40
