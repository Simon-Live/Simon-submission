"""FBX, .blend and gltf-zip on Modal (docs/specs/model-convert.md "On Modal"): the jail's flags, the client's Volume rule and
the server's path to a checked model. Fakes only: no network and no Blender. The real run is recorded in the spec."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import time
from typing import Any
from unittest import mock

import pytest

from part7 import model_convert as mc, model_convert_modal as route, quota

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "deploy" / "serverless" / "convert_app.py"
CLIENT = ROOT / "deploy" / "serverless" / "convert_client.py"
MID = "a" * 32


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


# ---------------------------------------------------------------- the jail
def test_the_converter_class_has_no_network_no_secret_no_shared_volume_and_one_file_per_container() -> None:
    source = APP.read_text(encoding="utf-8")
    head = source[source.index("@app.cls("):source.index("class Convert")]
    assert "block_network=True" in head and "single_use_containers=True" in head
    assert "secrets" not in head and "volumes" not in head and "gpu" not in head


def test_blender_runs_without_auto_run_scripts_as_nobody_on_pinned_tarballs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "modal", mock.MagicMock())
    app = _load(APP, "convert_app_under_test")
    argv = app.blender_argv("4.5", Path("/w/input.fbx"), Path("/w/out/model.glb"))
    assert "-Y" in argv and "--factory-startup" in argv and "-y" not in argv
    assert "user=NOBODY, group=NOBODY, extra_groups=[]" in APP.read_text(encoding="utf-8")
    assert all(len(sha) == 64 for _, _, sha in app.BLENDERS) and [b[0] for b in app.BLENDERS] == ["4.5", "3.6"]
    assert "sha256sum -c" in app._fetch(*app.BLENDERS[0])


def _chain(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, runs: list[dict[str, Any]]) -> tuple[dict[str, Any], list[str], Path]:
    monkeypatch.setitem(sys.modules, "modal", mock.MagicMock())
    app = _load(APP, "convert_app_under_test")
    tried: list[str] = []
    work, target = tmp_path / "w", tmp_path / "io"
    (work / "out").mkdir(parents=True)
    target.mkdir()

    def fake(series: str, source: Path, folder: Path) -> dict[str, Any]:
        tried.append(series)
        run = runs[len(tried) - 1]
        if not run["reason"]:
            (folder / "out" / "model.glb").write_bytes(b"glTF")
        return {"reader": f"blender-{series}", **run}

    monkeypatch.setattr(app, "attempt", fake)
    return app.convert_file(work / "input.fbx", work, target), tried, target


def test_the_second_blender_reads_what_the_first_could_not(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    doc, tried, target = _chain(monkeypatch, tmp_path, [{"reason": "failed", "outcome": {"code": "unreadable"}}, {"reason": "", "outcome": {"ok": True}}])
    assert tried == ["4.5", "3.6"] and doc["reason"] == "" and (target / "out" / "model.glb").is_file()
    assert json.loads((target / "result.json").read_text())["reader"] == "blender-3.6"


def test_a_file_with_no_mesh_stops_the_chain_and_leaves_no_glb(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    doc, tried, target = _chain(monkeypatch, tmp_path, [{"reason": "failed", "outcome": {"code": "skeleton-only", "bones": 3}}])
    assert tried == ["4.5"] and doc["reason"] == "failed" and not (target / "out").exists()


def test_the_old_reader_runs_after_both_blenders(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setitem(sys.modules, "modal", mock.MagicMock())
    app = _load(APP, "convert_app_under_test")
    work, target = tmp_path / "w", tmp_path / "io"
    (work / "out").mkdir(parents=True)
    target.mkdir()
    monkeypatch.setattr(app, "attempt", lambda series, source, folder: {"reader": f"blender-{series}", "reason": "failed", "outcome": {"code": "unreadable"}})

    def old(source: Path, folder: Path) -> dict[str, Any]:
        (folder / "out" / "model.glb").write_bytes(b"glTF")
        return {"reader": "fbx2gltf", "reason": "", "outcome": {"mode": "rigged"}}

    monkeypatch.setattr(app, "attempt_fbx2gltf", old)
    doc = app.convert_file(work / "input.fbx", work, target)
    assert [a["reader"] for a in doc["attempts"]] == ["blender-4.5", "blender-3.6", "fbx2gltf"] and doc["reader"] == "fbx2gltf"
    assert (target / "out" / "model.glb").is_file()
    called: list[Path] = []
    monkeypatch.setattr(app, "attempt_fbx2gltf", lambda source, folder: called.append(source) or {"reader": "fbx2gltf", "reason": "failed", "outcome": {}})
    assert app.convert_file(work / "input.blend", work, target)["reader"] == "blender-3.6" and not called, "only an FBX"


def test_the_old_reader_is_pinned_and_keeps_the_sandbox(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "modal", mock.MagicMock())
    app = _load(APP, "convert_app_under_test")
    fetch = (ROOT / "tools" / "model-converter" / "fetch-fbx2gltf.sh").read_text(encoding="utf-8")
    assert app.FBX2GLTF_SHA in fetch and app.FBX2GLTF_SHA in app._fetch_fbx2gltf() and app.FBX2GLTF_PKG_SHA in app._fetch_fbx2gltf()
    source = APP.read_text(encoding="utf-8")
    assert source.count("subprocess.Popen(") == 1 and "user=NOBODY" in source and "block_network=True" in source


# ---------------------------------------------------------------- the client
class FakeVolume:
    def __init__(self, files: dict[str, bytes]) -> None:
        self.files, self.uploaded = files, []

    def batch_upload(self) -> Any:
        vol = self

        class Batch:
            def __enter__(self) -> Any:
                return self

            def __exit__(self, *exc: Any) -> None:
                return None

            def put_file(self, local: str, remote: str) -> None:
                vol.uploaded.append(remote)

        return Batch()

    def read_file(self, path: str) -> Any:
        if path not in self.files:
            raise FileNotFoundError(path)
        return iter([self.files[path]])


def _fake_modal(vol: FakeVolume, spawn_fails: bool = False) -> Any:
    modal = mock.MagicMock()
    modal.Volume.from_name.return_value = vol
    method = modal.Cls.from_name.return_value.with_options.return_value.return_value.convert
    method.spawn.side_effect = RuntimeError("no") if spawn_fails else None
    return modal


def test_each_file_gets_its_own_volume_no_pickle_and_the_volume_goes(tmp_path: Path) -> None:
    client, vol = _load(CLIENT, "convert_client_under_test"), FakeVolume({"result.json": b'{"reason": ""}', "out/model.glb": b"glTF", "log.txt": b"log"})
    modal, src = _fake_modal(vol), tmp_path / "m.fbx"
    src.write_bytes(b"x")
    assert client.convert(modal, client._p2(), src, "input.fbx", tmp_path / "out") == 0
    name = modal.Volume.from_name.call_args.args[0]
    assert name.startswith(client.VOLUME_PREFIX) and len(name) == len(client.VOLUME_PREFIX) + 32
    assert vol.uploaded == ["/in/input.fbx"]
    modal.Cls.from_name.return_value.with_options.assert_called_once_with(volumes={client.IO_MOUNT: vol})
    call = modal.Cls.from_name.return_value.with_options.return_value.return_value.convert.spawn.return_value
    call.get.assert_not_called()
    modal.Volume.objects.delete.assert_called_once_with(name, allow_missing=True)
    assert (tmp_path / "out" / "model.glb").read_bytes() == b"glTF"


def test_the_volume_goes_when_the_call_fails_and_when_the_wait_ends(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, src = _load(CLIENT, "convert_client_under_test"), tmp_path / "m.fbx"
    src.write_bytes(b"x")
    modal = _fake_modal(FakeVolume({}), spawn_fails=True)
    with pytest.raises(RuntimeError):
        client.convert(modal, client._p2(), src, "input.fbx", tmp_path / "o")
    modal.Volume.objects.delete.assert_called_once()
    modal = _fake_modal(FakeVolume({}))
    monkeypatch.setattr(client, "POLL_S", 0)
    assert client.convert(modal, client._p2(), src, "input.fbx", tmp_path / "o", wait_s=0.01) == client.TIMEOUT_EXIT
    modal.Volume.objects.delete.assert_called_once()
    assert not (tmp_path / "o" / "result.json").exists()


def test_an_oversized_result_or_glb_is_not_taken(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, src = _load(CLIENT, "convert_client_under_test"), tmp_path / "m.fbx"
    src.write_bytes(b"x")
    monkeypatch.setattr(client, "POLL_S", 0)
    big = FakeVolume({"result.json": b"x" * (client.MAX_RESULT_BYTES + 1)})
    assert client.convert(_fake_modal(big), client._p2(), src, "input.fbx", tmp_path / "o") == client.TIMEOUT_EXIT
    monkeypatch.setattr(client, "MAX_GLB_BYTES", 2)
    p2 = client._p2()
    with pytest.raises(p2.Refused):
        client.convert(_fake_modal(FakeVolume({"result.json": b"{}", "out/model.glb": b"glTF"})), p2, src, "input.fbx", tmp_path / "o")


def test_the_launcher_gives_the_child_no_token(monkeypatch: pytest.MonkeyPatch) -> None:
    p2 = _load(CLIENT, "convert_client_under_test")._p2()
    env = p2.server_env({"PATH": "/bin", "MODAL_TOKEN_ID": "ak-1", "MODAL_TOKEN_SECRET": "as-2", "OTHER": "x"}, Path("/tmp/h"))
    assert "MODAL_TOKEN_ID" not in env and "MODAL_TOKEN_SECRET" not in env and "OTHER" not in env


# ---------------------------------------------------------------- the server
@pytest.fixture
def state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "state"
    (root / "models" / MID / "in").mkdir(parents=True)
    (root / "models" / MID / "in" / "m.fbx").write_bytes(b"Kaydara FBX Binary  \x00")
    (root / "models" / MID / "status.json").write_text(json.dumps({"id": MID, "status": "queued", "owner": "u:1"}), encoding="utf-8")
    monkeypatch.setenv("SIMON7_STATE_DIR", str(root))
    monkeypatch.setenv("SIMON7_COMPUTE", "serverless")
    monkeypatch.delenv("SIMON7_MODEL_CONVERT", raising=False)
    mc.set_done_handler(None)
    mc._handlers.clear()
    mc._active.clear()
    return root


def _ready(state: Path, ok: bool = True) -> None:
    spool = mc.spool_dir(state)
    spool.mkdir(parents=True, exist_ok=True)
    (spool / route.READY_FILE).write_text(json.dumps({"ok": ok, "ts": time.time()}), encoding="utf-8")


def _fake_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, result: Any, glb: bytes | None = b"glTF", code: int = 0) -> None:
    script = tmp_path / "client.py"
    script.write_text(f"""
import json, pathlib, sys
out = pathlib.Path(sys.argv[sys.argv.index("--out") + 1])
if {result!r} is not None:
    (out / "result.json").write_text(json.dumps({result!r}))
if {glb!r} is not None:
    (out / "model.glb").write_bytes({glb!r})
sys.exit({code})
""", encoding="utf-8")
    monkeypatch.setattr(route, "_command", lambda *a: [sys.executable, "-I", str(script), *a])


def _run(state: Path) -> tuple[Path, list[tuple[bool, str]]]:
    folder, seen = state / "models" / MID, []
    mc.submit(folder, folder / "in" / "m.fbx", "fbx", on_done=lambda d, ok, msg: seen.append((ok, msg)), state=state)
    for _ in range(200):
        if seen:  # `_finish` writes the status before it calls back: the status alone races on a loaded host
            break
        time.sleep(0.05)
    return folder, seen


def _deployed(monkeypatch: pytest.MonkeyPatch, stamp: bytes | None) -> tuple[Any, Any, Any]:
    client = _load(CLIENT, "convert_client_under_test")
    p2 = _load(ROOT / "deploy" / "serverless" / "p2_client.py", "p2_client_under_convert_test")
    modal = mock.MagicMock()
    modal.exception.NotFoundError = type("NotFoundError", (Exception,), {})

    def read(_vol: Any, name: str, _cap: int) -> tuple[bytes, bool]:
        assert name == p2.CONVERTER_STAMP
        if stamp is None:
            raise FileNotFoundError(name)
        return stamp, False

    monkeypatch.setattr(p2, "read_head", read)
    return client, p2, modal


def test_the_client_check_is_the_stamp_not_only_a_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    client, p2, modal = _deployed(monkeypatch, None)
    assert client.check(modal, p2) == 81, "the app is there but carries no stamp"
    monkeypatch.setattr(p2, "read_head", lambda *_: (json.dumps({"version": "an-older-image"}).encode(), False))
    assert client.check(modal, p2) == 81
    monkeypatch.setattr(p2, "read_head", lambda *_: (json.dumps({"version": p2.converter_version()}).encode(), False))
    assert client.check(modal, p2) == 0
    modal.App.lookup.side_effect = modal.exception.NotFoundError("no app")
    assert client.check(modal, p2) == 81


def test_the_stale_converter_is_not_offered(state: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A stale app accepted a text FBX and failed for the person: `reads_text_fbx` now follows the stamp's check."""
    monkeypatch.setenv("SIMON7_COMPUTE", "serverless")
    spool = mc.spool_dir(state)
    spool.mkdir(parents=True, exist_ok=True)
    for code, offered in ((81, False), (0, True)):
        monkeypatch.setattr(route.subprocess, "run", lambda *_a, code=code, **_k: mock.Mock(returncode=code))
        route._checking = True
        route._check(spool)
        assert mc.available(state) is offered and mc.reads_text_fbx(state) is offered


def test_the_client_waits_past_the_app_and_the_server_past_the_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "modal", mock.MagicMock())
    app = _load(APP, "convert_app_timeouts_under_test")
    client = _load(CLIENT, "convert_client_under_test")
    assert client.WAIT_S > app.ATTEMPT_S * (len(app.BLENDERS) + 2) + 60
    assert route.CALL_TIMEOUT_S > client.WAIT_S


def test_available_follows_the_deployed_check_and_the_stop_file(state: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(route, "refresh", lambda spool: None)
    assert mc.available(state) is False, "not asked yet: refused plainly, not accepted and failed later"
    _ready(state, ok=False)
    assert mc.available(state) is False
    _ready(state)
    assert mc.available(state) is True
    (state / quota.STOP_FILE).write_text("")
    assert mc.available(state) is False
    (state / quota.STOP_FILE).unlink()
    monkeypatch.setenv("SIMON7_MODEL_CONVERT", "off")
    assert mc.available(state) is False


def test_a_stale_answer_is_used_and_asked_again(state: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    asked: list[Path] = []
    monkeypatch.setattr(route, "refresh", asked.append)
    spool = mc.spool_dir(state)
    spool.mkdir(parents=True)
    (spool / route.READY_FILE).write_text(json.dumps({"ok": True, "ts": time.time() - route.RECHECK_S - 5}), encoding="utf-8")
    assert mc.available(state) is True and asked == [spool]


def test_a_converted_file_reaches_the_one_door_with_its_record(state: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _ready(state)
    steps = [{"step": "import", "blender": "4.5.15"}]
    _fake_client(tmp_path, monkeypatch, {"reason": "", "reader": "blender-4.5", "outcome": {"ok": True, "mode": "rigged", "steps": steps},
                                         "attempts": [{"reader": "blender-4.5", "reason": ""}]})
    folder, seen = _run(state)
    assert seen == [(True, "")] and (folder / "model.glb").read_bytes() == b"glTF" and not (folder / "out").exists()
    record = json.loads((folder / "convert.json").read_text())
    assert record["ok"] is True and record["reader"] == "blender" and record["mode"] == "rigged" and record["steps"] == steps
    assert record["attempts"][0]["image"] == "blender-4.5" and mc.running() == []


@pytest.mark.parametrize(("result", "glb", "code", "words"), [
    ({"reason": "failed", "outcome": {"code": "skeleton-only", "bones": 3}}, None, 0, "skeleton (3 bones)"),
    ({"reason": "failed", "outcome": {"code": "empty"}}, None, 0, "no mesh and no skeleton"),
    ({"reason": "failed", "outcome": "not a dict"}, None, 0, "could not read this file"),
    ({"reason": "too-big", "outcome": {}}, None, 0, "too large"),
    ({"reason": "timeout", "outcome": {}}, None, 0, "too long"),
    ({"reason": ""}, None, 0, "could not read this file"),  # says it worked and brought nothing
    (None, None, route.TIMEOUT_EXIT, "too long"),
    (None, None, 80, "cannot convert files right now"),
])
def test_every_failure_ends_failed_with_a_plain_line(state: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, result: Any, glb: Any, code: int, words: str) -> None:
    _ready(state)
    _fake_client(tmp_path, monkeypatch, result, glb, code)
    folder, seen = _run(state)
    status = json.loads((folder / "status.json").read_text())
    assert status["status"] == "failed" and words in status["error"] and seen[0][0] is False
    assert not (folder / "model.glb").exists() and not (folder / "in").exists()


def test_a_forged_outcome_keeps_nothing_unexpected(state: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _ready(state)
    _fake_client(tmp_path, monkeypatch, {"reason": "", "reader": "../../x", "outcome": {"ok": True, "mode": "evil", "code": "evil", "extra": "x" * 9000},
                                         "attempts": "nope"})
    folder, _ = _run(state)
    record = json.loads((folder / "convert.json").read_text())
    assert record["mode"] is None and record["code"] is None and record["attempts"] == [] and "extra" not in record


def test_a_conversion_the_drain_settled_is_left_as_it_is(state: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _ready(state)
    folder = state / "models" / MID

    def call(job_id: str, argv: list[str]) -> int:
        assert mc.cut_off() == [(MID, "convert")]
        return 0

    monkeypatch.setattr(route, "_call", call)
    mc.submit(folder, folder / "in" / "m.fbx", "fbx", state=state)
    for _ in range(100):
        if mc._status_of(folder) == "failed":
            break
        time.sleep(0.05)
    time.sleep(0.2)
    status = json.loads((folder / "status.json").read_text())
    assert status["status"] == "failed" and status["error"] == mc.RESTART_MESSAGE and not (folder / "model.glb").exists()


def test_the_converter_stamp_changes_with_the_reader_baked_into_its_image(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-M11: convert.py is in the image, so a change to it alone must not pass the check against a stale app."""
    p2 = _load(CLIENT, "convert_client_under_test")._p2()
    (tmp_path / "deploy/serverless").mkdir(parents=True)
    (tmp_path / "tools/model-converter").mkdir(parents=True)
    (tmp_path / "deploy/serverless/convert_app.py").write_text("app")
    reader = tmp_path / "tools/model-converter/convert.py"
    reader.write_text("one")
    monkeypatch.setattr(p2, "__file__", str(tmp_path / "deploy/serverless/p2_client.py"))
    first = p2.converter_version()
    reader.write_text("two")
    assert p2.converter_version() != first
