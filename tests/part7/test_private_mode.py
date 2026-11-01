"""Tests for part7/private_mode.py (docs/specs/private-mode.md, TICKET-147)."""

from __future__ import annotations

from pathlib import Path

import pytest

from part7 import private_mode as pm


def ready(model: str) -> None:
    return None


@pytest.fixture(autouse=True)
def _gpu_has_room(monkeypatch: pytest.MonkeyPatch) -> None:
    """No test reads the host's real GPU memory; the floor tests pass their own memory_fn."""
    monkeypatch.setattr(pm.gpu_lock, "free_gpu_memory_mib", lambda: 30000)


def test_ac001_switch_values() -> None:
    for v in ("1", "true", "YES", " On "):
        assert pm.enabled({"SIMON7_PRIVATE": v})
    for v in ("", "0", "no", "maybe"):
        assert not pm.enabled({"SIMON7_PRIVATE": v})
    assert not pm.enabled({})


def test_ac001_job_flag_wins() -> None:
    assert pm.enabled({}, job_flag=True)
    assert not pm.enabled({"SIMON7_PRIVATE": "1"}, job_flag=False)


def test_ac002_env_and_argv() -> None:
    p = pm.plan({"SIMON7_PRIVATE": "1", "PATH": "/bin"}, status_fn=ready)
    assert p.active and p.argv == ["--phrasing", "local-llm"]
    assert p.env["PART5_OLLAMA_MODEL"] == "muse-glimmer:30b"
    assert p.env["PART5_PHRASING_BUDGET_S"] == pm.BUDGET_S
    assert p.env["PART5_LOCAL_LLM_TIMEOUT_S"] == "90" and p.env["PART5_LOCAL_LLM_THINK"] == "0"
    assert float(p.env["PART5_LOCAL_LLM_TIMEOUT_S"]) < float(p.env["PART5_PHRASING_BUDGET_S"])
    assert ".local/bin" in p.env["PATH"] and p.env["PATH"].endswith("/bin")
    assert "--live" not in p.argv and p.note is None


def test_ac002_model_override() -> None:
    p = pm.plan({"SIMON7_PRIVATE": "1", "SIMON7_PRIVATE_MODEL": "muse-glimmer:30b-nvfp4"}, status_fn=ready)
    assert p.env["PART5_OLLAMA_MODEL"] == "muse-glimmer:30b-nvfp4"


@pytest.mark.parametrize("reason", ["ollama not found", "ollama is not answering", "model x is not pulled"])
def test_ac003_unavailable_falls_back_with_note(reason: str) -> None:
    p = pm.plan({"SIMON7_PRIVATE": "1"}, status_fn=lambda m: reason)
    assert not p.active and p.argv == ["--phrasing", "template"] and p.env == {}
    assert p.note == f"private mode: {reason}, template wording used"


def test_ac003_status_reasons() -> None:
    tags = {"models": [{"name": "gemma3:27b"}]}
    assert pm.local_status("muse-glimmer:30b", fetch=lambda h: tags, has_binary=lambda: False) == "ollama not found"
    assert pm.local_status("muse-glimmer:30b", fetch=lambda h: tags, has_binary=lambda: True) == \
        "model muse-glimmer:30b is not pulled"

    def down(host: str) -> dict:
        raise OSError("refused")

    assert pm.local_status("m:1", fetch=down, has_binary=lambda: True) == "ollama is not answering"
    ok = {"models": [{"name": "muse-glimmer:30b"}]}
    assert pm.local_status("muse-glimmer:30b", fetch=lambda h: ok, has_binary=lambda: True) is None
    latest = {"models": [{"name": "muse-glimmer:latest"}]}
    assert pm.local_status("muse-glimmer", fetch=lambda h: latest, has_binary=lambda: True) is None


def test_ac004_off_changes_nothing() -> None:
    p = pm.plan({}, status_fn=lambda m: pytest.fail("must not probe when off"))
    assert p == pm.Plan(active=False) and p.note is None


def test_ac005_gpu_turn_loads_then_unloads_inside_lock(tmp_path: Path) -> None:
    calls: list[tuple[str, object]] = []
    p = pm.plan({"SIMON7_PRIVATE": "1"}, status_fn=ready)
    with pm.gpu_turn(p, lock_path=tmp_path / "gpu.lock", post=lambda h, b: calls.append(("post", b["keep_alive"]))):
        calls.append(("body", None))
    assert calls == [("post", pm.KEEP_ALIVE), ("body", None), ("post", 0)]


def test_ac005_load_failure_does_not_raise_and_still_unloads(tmp_path: Path) -> None:
    seen: list[object] = []

    def post(host: str, body: dict) -> None:
        seen.append(body["keep_alive"])
        raise OSError("down")

    p = pm.plan({"SIMON7_PRIVATE": "1"}, status_fn=ready)
    with pm.gpu_turn(p, lock_path=tmp_path / "gpu.lock", post=post):
        pass
    assert seen == [pm.KEEP_ALIVE, 0]


def test_ac005_unload_on_body_error(tmp_path: Path) -> None:
    seen: list[object] = []
    p = pm.plan({"SIMON7_PRIVATE": "1"}, status_fn=ready)
    with pytest.raises(RuntimeError):
        with pm.gpu_turn(p, lock_path=tmp_path / "gpu.lock", post=lambda h, b: seen.append(b["keep_alive"])):
            raise RuntimeError("boom")
    assert seen == [pm.KEEP_ALIVE, 0]


def test_ac005_inactive_plan_is_noop(tmp_path: Path) -> None:
    def no_call(h: str, b: dict) -> None:
        pytest.fail("no call")

    with pm.gpu_turn(pm.Plan(active=False), lock_path=tmp_path / "x", post=no_call):
        pass


def test_ac008_floor_met_loads_model(tmp_path: Path) -> None:
    calls: list[object] = []
    p = pm.plan({"SIMON7_PRIVATE": "1"}, status_fn=ready)
    with pm.gpu_turn(p, lock_path=tmp_path / "g.lock", memory_fn=lambda: pm.DEFAULT_FLOOR_MIB,
                     post=lambda h, b: calls.append(b["keep_alive"])) as used:
        assert used is p and used.active
    assert calls == [pm.KEEP_ALIVE, 0]
    assert pm.DEFAULT_FLOOR_MIB == 20480


def test_ac008_floor_not_met_never_loads_and_yields_template(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lines: list[str] = []
    monkeypatch.setattr(pm.applog, "log", lambda msg, job=None, job_dir=None, level=0: lines.append(msg))

    def no_call(h: str, b: dict) -> None:
        pytest.fail("the model must not load below the floor")

    p = pm.plan({"SIMON7_PRIVATE": "1"}, status_fn=ready)
    env = {"SIMON7_PRIVATE_WAIT_S": "0.2"}
    with pm.gpu_turn(p, lock_path=tmp_path / "g.lock", memory_fn=lambda: pm.DEFAULT_FLOOR_MIB - 1, post=no_call,
                     env=env) as used:
        assert not used.active and used.argv == ["--phrasing", "template"] and used.env == {}
        assert "20480 MiB needed" in used.note and "template wording used" in used.note
    assert any("template wording used" in m for m in lines)


def test_ac008_floor_and_wait_from_env(tmp_path: Path) -> None:
    p = pm.plan({"SIMON7_PRIVATE": "1"}, status_fn=ready)
    seen: list[object] = []
    env = {"SIMON7_PRIVATE_MIN_FREE_MIB": "1000", "SIMON7_PRIVATE_WAIT_S": "bad"}
    with pm.gpu_turn(p, lock_path=tmp_path / "g.lock", memory_fn=lambda: 1000, env=env,
                     post=lambda h, b: seen.append(b["keep_alive"])) as used:
        assert used.active  # 1000 MiB meets the overridden floor; a bad wait keeps the default
    assert seen == [pm.KEEP_ALIVE, 0]


def test_ac007_old_pin_is_inert_and_notes_once() -> None:
    probed: list[str] = []
    p = pm.plan({"SIMON7_PRIVATE": "1"}, status_fn=lambda m: probed.append(m), part5_clone="/clone",
                supports_fn=lambda c: False)
    assert not p.active and p.env == {} and p.argv == ["--phrasing", "template"]
    assert p.note == "Private wording needs a newer Part 5; this take used the standard wording."
    assert probed == []  # Ollama is not even probed


def test_ac007_new_pin_runs_normally() -> None:
    p = pm.plan({"SIMON7_PRIVATE": "1"}, status_fn=ready, part5_clone="/clone", supports_fn=lambda c: True)
    assert p.active and p.argv == ["--phrasing", "local-llm"]


def test_ac007_off_does_not_check_the_pin() -> None:
    p = pm.plan({}, part5_clone="/clone", supports_fn=lambda c: pytest.fail("not asked"))
    assert p == pm.Plan(active=False)


def test_ac007_inert_plan_makes_gpu_turn_a_noop(tmp_path: Path) -> None:
    p = pm.plan({"SIMON7_PRIVATE": "1"}, part5_clone="/c", supports_fn=lambda c: False)
    with pm.gpu_turn(p, lock_path=tmp_path / "g.lock", post=lambda h, b: pytest.fail("no load")) as used:
        assert used is p


def test_ac007_part5_has_fix_reads_the_documented_setting(tmp_path: Path) -> None:
    guide = tmp_path / pm.PART5_FIX_DOC
    assert not pm.part5_has_fix(tmp_path)  # no guide: an old or missing clone stays inert
    assert not pm.part5_has_fix(tmp_path / "missing")
    guide.parent.mkdir(parents=True)
    guide.write_text("| `PART5_LOCAL_LLM_TIMEOUT_S` | ... |\n", encoding="utf-8")
    assert not pm.part5_has_fix(tmp_path)  # the timeout setting alone is not the full fix
    guide.write_text("| `PART5_LOCAL_LLM_MAX_TOKENS` | 2048 | ... |\n", encoding="utf-8")
    assert pm.part5_has_fix(tmp_path)


def test_ac007_published_part5_d6700e8_has_the_fix() -> None:
    clone = Path.home() / "simon-part-5"
    import subprocess
    try:
        text = subprocess.run(["git", "-C", str(clone), "show", "d6700e8:docs/dev/DEVELOPING.md"],
                              capture_output=True, text=True, check=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        pytest.skip("Part 5 clone with d6700e8 not on this host")
    assert pm.PART5_FIX_MARKER in text  # the published Part 5 that Part 7 pins in release 13


def test_ac006_recorded_backend() -> None:
    local = {"phrasing": {"faults": [{"backend": "template", "model": None},
                                     {"backend": "local-llm", "model": "muse-glimmer:30b"}]}}
    assert pm.recorded_backend(local) == ("local-llm", "muse-glimmer:30b")
    tmpl = {"phrasing": {"faults": [{"backend": "template", "model": None}]}}
    assert pm.recorded_backend(tmpl) == ("template", None)
    assert pm.recorded_backend({}) == ("template", None)


def test_r11_load_and_unload_failures_are_logged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lines: list[str] = []
    monkeypatch.setattr(pm.applog, "log", lambda msg, job=None, job_dir=None, level=0: lines.append(msg))

    def post(host: str, body: dict) -> None:
        raise OSError("down")

    p = pm.plan({"SIMON7_PRIVATE": "1"}, status_fn=ready)
    with pm.gpu_turn(p, lock_path=tmp_path / "gpu.lock", post=post):
        pass
    assert any("model load failed (OSError)" in m for m in lines)
    assert any("model unload failed (OSError)" in m for m in lines)
