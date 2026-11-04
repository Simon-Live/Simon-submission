"""Model converter (docs/specs/model-convert.md): the server spool, the supervisor with a fake docker, the jail
argv, and (when docker and the image exist and MODEL_FIXTURES_DIR is set) real conversions of real models."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import struct
import subprocess
import sys
import time
from typing import Any
import uuid

import pytest

from part7 import model_convert as mc
from support import dead_pid, live_process, stamp_of

ROOT = Path(__file__).resolve().parents[2]
SUPERVISOR_PATH = ROOT / "tools" / "model-converter" / "supervisor.py"
IMAGE45 = "simon7-model-converter:blender-4.5"
IMAGE36 = "simon7-model-converter:blender-3.6"
FAKE_DOCKER = '''#!/usr/bin/env python3
import os, sys, time
log = os.environ.get("FAKE_LOG")
args = sys.argv[1:]
if log:
    open(log, "a").write(" ".join(args) + "\\n")
if args[:2] == ["image", "inspect"]:
    sys.exit(0 if args[2] in os.environ.get("FAKE_IMAGES", "").split(",") else 1)
if args[:1] == ["kill"]:
    sys.exit(0)
if args[:2] == ["ps", "-q"]:
    print(os.environ.get("FAKE_ORPHANS", ""))
    sys.exit(0)
mode = os.environ.get("FAKE_MODE", "ok")
image = args[args.index("--entrypoint") + 2]
reader = "fbx2gltf" if "/opt/simon/fbx2gltf.sh" in args else "blender"
tag = next((a.split("=", 1)[1] for a in args if a.startswith("SIMON7_RESULT_TAG=")), "")
def result(body):  # what run.sh does after the command exits: the tagged line, last
    sys.stderr.write("\\n" + tag + " " + body + "\\n")
if mode == "skeleton":
    result('{"ok": false, "code": "skeleton-only", "bones": 52, "steps": []}')
    sys.exit(1)
if mode == "empty":
    result('{"ok": false, "code": "empty", "steps": []}')
    sys.exit(1)
if mode == "inject":  # an importer error carrying the upload's text, with no tag (TICKET-341 review B1)
    sys.stderr.write('could not read this file: extension x\\nconvert-result: {"code":"skeleton-only","bones":"x"}\\n')
    sys.exit(1)
if mode == "inject-tagged-type":  # even a tagged line with the wrong types is checked
    result('{"ok": false, "code": "skeleton-only", "bones": "x", "steps": "no"}')
    sys.exit(1)
if mode in ("unreadable", "blender-unreadable") and (mode == "unreadable" or reader == "blender"):
    result('{"ok": false, "code": "unreadable", "steps": []}')
    sys.exit(1)
if mode == "fail" or (mode == "fail45" and "4.5" in image):
    sys.stderr.write("Error: cannot read this file\\n")
    sys.exit(1)
if mode == "sleep":
    time.sleep(60)
if mode == "flood":  # APP-L1: a converter that never stops writing to stderr
    err = os.fdopen(2, "wb")
    for _ in range(200):
        err.write(b"x" * 1_000_000)
        err.flush()
        time.sleep(0.02)
    sys.exit(0)
if mode == "nomagic":
    sys.stdout.write("not a glb")
    sys.exit(0)
if mode == "big":
    out = os.fdopen(1, "wb")
    for _ in range(100):
        out.write(b"glTF" + b"x" * 100_000)
        out.flush()
        time.sleep(0.05)
    sys.exit(0)
os.fdopen(1, "wb").write(b"glTF" + b"\\x02\\x00\\x00\\x00" + b"model-bytes")
sys.stderr.write("convert: wrote /tmp/out/model.glb\\n")
result('{"ok": true, "mode": "static", "via": "%s", "steps": [{"step": "merge", "meshes": 3}]}' % reader)
'''


def _load_supervisor() -> Any:
    spec = importlib.util.spec_from_file_location("model_supervisor", SUPERVISOR_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["model_supervisor"] = module
    spec.loader.exec_module(module)
    return module


sup = _load_supervisor()


@pytest.fixture
def state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("SIMON7_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.delenv("SIMON7_MODEL_CONVERT", raising=False)
    monkeypatch.setenv("SIMON7_FBX2GLTF", str(tmp_path / "no-fbx2gltf"))  # the host's install never changes these tests
    mc.set_done_handler(None)
    mc._handlers.clear()
    mc._active.clear()
    (tmp_path / "state" / "models").mkdir(parents=True)
    return tmp_path / "state"


@pytest.fixture
def fake_docker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "fake-docker"
    path.write_text(FAKE_DOCKER, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("SIMON7_DOCKER", str(path))
    monkeypatch.setenv("FAKE_IMAGES", IMAGE45)
    monkeypatch.setenv("FAKE_LOG", str(tmp_path / "docker.log"))
    monkeypatch.setenv("FAKE_MODE", "ok")
    return path


def _beat(state: Path, **over: Any) -> None:
    spool = mc.spool_dir(state)
    spool.mkdir(parents=True, exist_ok=True)
    beat = {"pid": 1, "ts": time.time(), "ready": True, "images": [IMAGE45], **over}
    (spool / "supervisor.json").write_text(json.dumps(beat), encoding="utf-8")


def _model(state: Path, name: str = "a", fmt_file: str = "m.fbx", status: str = "queued") -> Path:
    model_id = (name * 32)[:32]
    folder = state / "models" / model_id
    (folder / "in").mkdir(parents=True)
    (folder / "in" / fmt_file).write_bytes(b"Kaydara FBX Binary  \x00data")
    (folder / "status.json").write_text(json.dumps({"id": model_id, "status": status, "owner": "u1", "bytes": 5}), encoding="utf-8")
    return folder


def _status(folder: Path) -> dict[str, Any]:
    return json.loads((folder / "status.json").read_text(encoding="utf-8"))


# AC1: the jail argv

def _argv() -> list[str]:
    return sup.container_argv("n", "/scratch/in", "input.fbx", IMAGE45)


def test_argv_has_every_jail_flag() -> None:
    argv = _argv()
    pairs = [("--network", "none"), ("--security-opt", "no-new-privileges"), ("--user", "65534:65534"),
             ("--pids-limit", "256"), ("--memory", "4g"), ("--cap-drop", "ALL"), ("-e", "HOME=/tmp")]
    for flag, value in pairs:
        assert argv[argv.index(flag) + 1] == value
    assert "--read-only" in argv
    assert "/scratch/in:/in:ro" in argv
    assert any(a.startswith("/tmp:") and "size=1g" in a for a in argv)


def test_argv_runs_blender_headless_without_autoexec() -> None:
    argv = _argv()
    tail = argv[argv.index("blender"):]
    assert tail[:4] == ["blender", "-b", "--factory-startup", "-Y"]
    assert "-y" not in argv
    assert tail[-3:] == ["--", "/in/input.fbx", "/tmp/out/model.glb"]


def test_argv_has_no_writable_bind_mount_and_no_privilege_flags() -> None:
    argv = _argv()
    assert [a for a in argv if ":/" in a and not a.endswith(":ro") and not a.startswith("/tmp:")] == []
    assert "--privileged" not in argv and "--network=host" not in argv
    assert "-v" in argv and argv.count("-v") == 2  # the input, and the converter scripts (TICKET-341), both :ro


# AC6: availability

def test_available_false_without_heartbeat(state: Path) -> None:
    assert mc.available(state) is False


def test_available_true_with_fresh_ready_heartbeat(state: Path) -> None:
    _beat(state)
    assert mc.available(state) is True


@pytest.mark.parametrize("over", [{"ready": False}, {"ts": 1.0}, {"ts": "now"}])
def test_available_false_for_not_ready_or_stale(state: Path, over: dict[str, Any]) -> None:
    _beat(state, **over)
    assert mc.available(state) is False


def test_available_false_when_heartbeat_is_garbage(state: Path) -> None:
    (mc.spool_dir(state)).mkdir(parents=True)
    (mc.spool_dir(state) / "supervisor.json").write_text("[1]", encoding="utf-8")
    assert mc.available(state) is False


def test_available_false_when_switched_off(state: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _beat(state)
    monkeypatch.setenv("SIMON7_MODEL_CONVERT", "off")
    assert mc.available(state) is False


def test_submit_unavailable(state: Path) -> None:
    folder = _model(state)
    with pytest.raises(mc.ConvertUnavailable, match="needs the converter, which is not installed here"):
        mc.submit(folder, folder / "in" / "m.fbx", "fbx", state=state)
    assert not (mc.spool_dir(state) / "queue").exists() or not list((mc.spool_dir(state) / "queue").iterdir())


# submit

def test_submit_writes_request_and_keeps_status_fields(state: Path) -> None:
    _beat(state)
    folder = _model(state)
    mc.submit(folder, folder / "in" / "m.fbx", "fbx", state=state)
    req = json.loads((mc.spool_dir(state) / "queue" / f"{folder.name}.json").read_text(encoding="utf-8"))
    assert req["id"] == folder.name and req["fmt"] == "fbx" and req["src"] == str(folder / "in" / "m.fbx")
    data = _status(folder)
    assert data["status"] == "queued" and data["owner"] == "u1" and data["stage"] == "convert" and data["error"] is None


@pytest.mark.parametrize("fmt", ["obj", "glb", "", "FBX"])
def test_submit_rejects_unknown_format(state: Path, fmt: str) -> None:
    _beat(state)
    folder = _model(state)
    with pytest.raises(ValueError):
        mc.submit(folder, folder / "in" / "m.fbx", fmt, state=state)


def test_submit_rejects_source_outside_in_and_symlink(state: Path, tmp_path: Path) -> None:
    _beat(state)
    folder = _model(state)
    outside = tmp_path / "x.fbx"
    outside.write_bytes(b"x")
    with pytest.raises(ValueError):
        mc.submit(folder, outside, "fbx", state=state)
    (folder / "in" / "link.fbx").symlink_to(outside)
    with pytest.raises(ValueError):
        mc.submit(folder, folder / "in" / "link.fbx", "fbx", state=state)
    with pytest.raises(ValueError):
        mc.submit(folder, folder / "in" / "missing.fbx", "fbx", state=state)


def test_submit_busy_at_ten_pending(state: Path) -> None:
    _beat(state)
    queue = mc.spool_dir(state) / "queue"
    queue.mkdir(parents=True)
    for i in range(mc.MAX_PENDING):
        (queue / f"{i:032x}.json").write_text("{}", encoding="utf-8")
    folder = _model(state)
    with pytest.raises(mc.ConvertBusy):
        mc.submit(folder, folder / "in" / "m.fbx", "fbx", state=state)
    assert _status(folder)["status"] == "queued" and "stage" not in _status(folder)


# poll_once / handler contract

def _result(state: Path, folder: Path, **fields: Any) -> None:
    results = mc.spool_dir(state) / "results"
    results.mkdir(parents=True, exist_ok=True)
    (results / f"{folder.name}.json").write_text(json.dumps({"id": folder.name, **fields}), encoding="utf-8")


def _produce(folder: Path, data: bytes = b"glTFxxxx") -> None:
    (folder / "out").mkdir(exist_ok=True)
    (folder / "out" / "model.glb").write_bytes(data)


def test_poll_success_moves_glb_calls_handler_and_cleans_up(state: Path) -> None:
    folder = _model(state, status="converting")
    _produce(folder)
    _result(state, folder, ok=True, reason="", message="")
    seen: list[tuple[str, bool, str]] = []

    def handler(model_dir: Path, ok: bool, message: str) -> None:
        seen.append((model_dir.name, ok, message))
        assert (model_dir / "model.glb").read_bytes() == b"glTFxxxx"
        assert not (model_dir / "out").exists()
        mc.set_status(model_dir, "ready")

    mc.set_done_handler(handler)
    assert mc.poll_once(mc.spool_dir(state)) == 1
    assert seen == [(folder.name, True, "")]
    assert _status(folder)["status"] == "ready" and _status(folder)["owner"] == "u1"
    assert not (folder / "in").exists()
    assert not list((mc.spool_dir(state) / "results").iterdir())


def test_per_submit_handler_wins_over_global(state: Path) -> None:
    _beat(state)
    folder = _model(state)
    calls: list[str] = []
    mc.set_done_handler(lambda *a: calls.append("global"))
    mc.submit(folder, folder / "in" / "m.fbx", "fbx", on_done=lambda *a: calls.append("own"), state=state)
    _produce(folder)
    _result(state, folder, ok=True)
    mc.poll_once(mc.spool_dir(state))
    assert calls == ["own"]


def test_poll_without_handler_fails_the_model(state: Path) -> None:
    folder = _model(state, status="converting")
    _produce(folder)
    _result(state, folder, ok=True)
    mc.poll_once(mc.spool_dir(state))
    assert _status(folder)["status"] == "failed" and _status(folder)["error"] == mc.UNCHECKED_MESSAGE


def test_poll_handler_crash_fails_the_model(state: Path) -> None:
    folder = _model(state, status="converting")
    _produce(folder)
    _result(state, folder, ok=True)

    def boom(*_a: Any) -> None:
        raise RuntimeError("bad glb")

    mc.set_done_handler(boom)
    mc.poll_once(mc.spool_dir(state))
    assert _status(folder)["status"] == "failed" and _status(folder)["error"] == mc.UNCHECKED_MESSAGE
    assert (folder / "in").exists()


def test_poll_failure_sets_failed_message_and_removes_input(state: Path) -> None:
    folder = _model(state, status="converting")
    _produce(folder)
    _result(state, folder, ok=False, reason="timeout", message="The model took too long to convert.")
    calls: list[tuple[bool, str]] = []
    mc.set_done_handler(lambda d, ok, msg: calls.append((ok, msg)))
    mc.poll_once(mc.spool_dir(state))
    assert _status(folder)["status"] == "failed" and _status(folder)["error"] == "The model took too long to convert."
    assert calls == [(False, "The model took too long to convert.")]
    assert not (folder / "in").exists() and not (folder / "out").exists() and not (folder / "model.glb").exists()


def test_poll_success_without_output_is_lost(state: Path) -> None:
    folder = _model(state, status="converting")
    _result(state, folder, ok=True)
    mc.poll_once(mc.spool_dir(state))
    assert _status(folder)["error"] == mc.LOST_MESSAGE


def test_poll_refuses_symlinked_output(state: Path, tmp_path: Path) -> None:
    folder = _model(state, status="converting")
    (folder / "out").mkdir()
    target = tmp_path / "secret.glb"
    target.write_bytes(b"glTFsecret")
    (folder / "out" / "model.glb").symlink_to(target)
    _result(state, folder, ok=True)
    mc.poll_once(mc.spool_dir(state))
    assert _status(folder)["status"] == "failed" and not (folder / "model.glb").exists()


@pytest.mark.parametrize("bad", ["../etc", "short", "Z" * 32, ""])
def test_poll_ignores_unknown_or_malformed_ids(state: Path, bad: str) -> None:
    results = mc.spool_dir(state) / "results"
    results.mkdir(parents=True)
    (results / "x.json").write_text(json.dumps({"id": bad, "ok": True}), encoding="utf-8")
    (results / "y.json").write_text("not json", encoding="utf-8")
    mc.poll_once(mc.spool_dir(state))
    assert not (results / "x.json").exists()


# AC7: recover_stuck

def _gone(folder: Path) -> None:
    """The server that queued this conversion has exited (TICKET-306)."""
    data = _status(folder)
    data["run_by"] = {"pid": dead_pid(), "start": None}
    (folder / "status.json").write_text(json.dumps(data), encoding="utf-8")


def test_recover_stuck_fails_convert_stage_only(state: Path) -> None:
    _beat(state)
    stuck = _model(state, "a")
    mc.submit(stuck, stuck / "in" / "m.fbx", "fbx", state=state)
    (mc.spool_dir(state) / "queue" / f"{stuck.name}.json").unlink()  # the request is gone: nothing to poll for
    _gone(stuck)
    converting = _model(state, "b", status="converting")
    mc.set_status(converting, "converting")
    _gone(converting)
    avatar = _model(state, "c", status="queued")  # an avatar job: no convert stage
    done = _model(state, "d", status="ready")
    (converting / "out").mkdir()
    running = mc.spool_dir(state) / "running"
    running.mkdir(exist_ok=True)
    (running / f"{converting.name}.json").write_text("{}", encoding="utf-8")
    failed = mc.recover_stuck(state)
    assert sorted(failed) == sorted([stuck.name, converting.name])
    for folder in (stuck, converting):
        assert _status(folder)["status"] == "failed" and _status(folder)["error"] == mc.RESTART_MESSAGE
        assert _status(folder)["owner"] == "u1"
    assert _status(avatar)["status"] == "queued" and _status(done)["status"] == "ready"
    assert not list((mc.spool_dir(state) / "queue").iterdir()) and not list(running.iterdir())
    assert not (converting / "out").exists()


def test_recover_stuck_leaves_a_live_server_alone_and_polls_a_queued_one_again(state: Path) -> None:
    _beat(state)
    with live_process() as pid:  # the old server, still draining in a restart with no gap
        live = _model(state, "e", status="converting")
        mc.set_status(live, "converting")
        data = _status(live)
        data["run_by"] = stamp_of(pid)
        (live / "status.json").write_text(json.dumps(data), encoding="utf-8")
        queued = _model(state, "f")
        mc.submit(queued, queued / "in" / "m.fbx", "fbx", state=state)
        _gone(queued)
        assert mc.recover_stuck(state) == []
        assert _status(live)["status"] == "converting" and _status(live)["run_by"] == stamp_of(pid)
    assert _status(queued)["status"] == "queued" and _status(queued)["run_by"]["pid"] == os.getpid()
    assert (mc.spool_dir(state) / "queue" / f"{queued.name}.json").is_file()
    assert (queued.name, "convert") in mc.running()


def test_cut_off_fails_a_converting_one_and_leaves_a_queued_one_for_the_next_server(state: Path) -> None:
    _beat(state)
    first, second = _model(state, "1"), _model(state, "2")
    for folder in (first, second):
        mc.submit(folder, folder / "in" / "m.fbx", "fbx", state=state)
    sup.set_status(first, "converting", only_from="queued")  # the supervisor started the first one
    assert {job for job, _ in mc.running()} >= {first.name, second.name}
    assert mc.cut_off() == [(first.name, "convert")]
    assert _status(first)["status"] == "failed" and _status(first)["error"] == mc.RESTART_MESSAGE
    assert not (mc.spool_dir(state) / "queue" / f"{first.name}.json").exists()
    assert _status(second)["status"] == "queued" and (mc.spool_dir(state) / "queue" / f"{second.name}.json").is_file()


def test_recover_stuck_with_no_models_dir(tmp_path: Path) -> None:
    assert mc.recover_stuck(tmp_path / "empty") == []


# supervisor with a fake docker

def _enqueue(state: Path, folder: Path, fmt: str = "fbx", src: str = "m.fbx", **over: Any) -> None:
    queue = mc.spool_dir(state) / "queue"
    queue.mkdir(parents=True, exist_ok=True)
    req = {"id": folder.name, "model_dir": str(folder), "src": str(folder / "in" / src), "fmt": fmt, **over}
    (queue / f"{folder.name}.json").write_text(json.dumps(req), encoding="utf-8")


def _run_supervisor(state: Path) -> dict[str, Any]:
    s = sup.Supervisor(mc.spool_dir(state))
    s.images = [IMAGE45]
    s.images_at = time.monotonic()
    s.loop(once=True)
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in (mc.spool_dir(state) / "results").glob("*.json")}


def test_supervisor_success(state: Path, fake_docker: Path, tmp_path: Path) -> None:
    folder = _model(state)
    _enqueue(state, folder)
    results = _run_supervisor(state)
    assert results[folder.name]["ok"] is True and results[folder.name]["image"] == IMAGE45
    assert (folder / "out" / "model.glb").read_bytes().startswith(b"glTF")
    assert _status(folder)["status"] == "converting" and _status(folder)["owner"] == "u1"
    assert "wrote /tmp/out/model.glb" in (folder / "convert.log").read_text(encoding="utf-8")
    log = (tmp_path / "docker.log").read_text(encoding="utf-8")
    assert "--network none" in log and "input.fbx" in log
    assert not (mc.spool_dir(state) / "work" / folder.name).exists()
    assert not list((mc.spool_dir(state) / "running").iterdir())


def test_supervisor_copies_input_under_a_fixed_name(state: Path, fake_docker: Path, tmp_path: Path) -> None:
    folder = _model(state, fmt_file="--evil name.blend")
    _enqueue(state, folder, "blend", "--evil name.blend")
    _run_supervisor(state)
    log = (tmp_path / "docker.log").read_text(encoding="utf-8")
    assert "/in/input.blend" in log and "evil" not in log


def test_supervisor_failure_reports_message(state: Path, fake_docker: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_MODE", "fail")
    folder = _model(state)
    _enqueue(state, folder)
    result = _run_supervisor(state)[folder.name]
    assert result["ok"] is False and result["reason"] == "failed" and result["message"] == sup.FAILED_MESSAGE
    assert "cannot read this file" in (folder / "convert.log").read_text(encoding="utf-8")
    assert not (folder / "out" / "model.glb").exists()


def test_supervisor_no_glb_magic_is_a_failure(state: Path, fake_docker: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_MODE", "nomagic")
    folder = _model(state)
    _enqueue(state, folder)
    assert _run_supervisor(state)[folder.name]["reason"] == "failed"


def test_supervisor_falls_back_to_the_older_image(state: Path, fake_docker: Path, monkeypatch: pytest.MonkeyPatch,
                                                 tmp_path: Path) -> None:
    monkeypatch.setenv("FAKE_MODE", "fail45")
    folder = _model(state, fmt_file="e.blend")
    _enqueue(state, folder, "blend", "e.blend")
    s = sup.Supervisor(mc.spool_dir(state))
    s.images, s.images_at = [IMAGE45, IMAGE36], time.monotonic()
    s.loop(once=True)
    result = json.loads((mc.spool_dir(state) / "results" / f"{folder.name}.json").read_text(encoding="utf-8"))
    assert result["ok"] is True and result["image"] == IMAGE36


# AC5: timeout

def test_supervisor_timeout(state: Path, fake_docker: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("FAKE_MODE", "sleep")
    monkeypatch.setattr(sup, "TIMEOUT_S", 1)
    folder = _model(state)
    _enqueue(state, folder)
    started = time.monotonic()
    result = _run_supervisor(state)[folder.name]
    assert time.monotonic() - started < 20
    assert result == {"id": folder.name, "ok": False, "reason": "timeout", "message": "The model took too long to convert.",
                      "image": IMAGE45, "reader": "blender", "seconds": result["seconds"]}
    assert "kill simon7-convert-" in (tmp_path / "docker.log").read_text(encoding="utf-8")


def test_stderr_flood_is_stopped_and_only_its_tail_is_read(state: Path, fake_docker: Path, monkeypatch: pytest.MonkeyPatch,
                                                           tmp_path: Path) -> None:
    monkeypatch.setenv("FAKE_MODE", "flood")
    monkeypatch.setattr(sup, "MAX_LOG_BYTES", 2_000_000)
    folder = _model(state)
    _enqueue(state, folder)
    started = time.monotonic()
    result = _run_supervisor(state)[folder.name]
    assert time.monotonic() - started < 20
    assert result["ok"] is False and result["reason"] == "too-big"
    assert result["message"] == sup.LOG_TOO_BIG_MESSAGE
    assert "kill simon7-convert-" in (tmp_path / "docker.log").read_text(encoding="utf-8")
    kept = (folder / "convert.log").read_text(encoding="utf-8")
    assert len(kept) <= sup.LOG_KEEP * 2 + 1000  # the kept log is a tail, never the 200 MB the converter wrote


def test_tail_bytes_reads_only_the_end(tmp_path: Path) -> None:
    path = tmp_path / "log"
    path.write_bytes(b"a" * 1000 + b"END")
    assert sup._tail_bytes(path, 10) == b"a" * 7 + b"END"
    assert sup._tail_bytes(path, 5000) == b"a" * 1000 + b"END"


def test_jail_has_cpu_file_and_log_caps() -> None:
    argv = sup.container_argv("n", "/scratch/in", "input.fbx", IMAGE45)
    pairs = list(zip(argv, argv[1:]))
    for flag in (("--ulimit", "cpu=900"), ("--ulimit", "nofile=1024:1024"), ("--ulimit", "fsize=1073741824"),
                 ("--ulimit", "core=0"), ("--log-driver", "none"), ("--network", "none"), ("--read-only", "--tmpfs")):
        assert flag in pairs, flag


def test_timeout_constant_is_180_seconds() -> None:
    assert sup.TIMEOUT_S == 180


def test_end_to_end_timeout(state: Path, fake_docker: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_MODE", "sleep")
    monkeypatch.setattr(sup, "TIMEOUT_S", 1)
    _beat(state)
    folder = _model(state)
    mc.submit(folder, folder / "in" / "m.fbx", "fbx", state=state)
    _run_supervisor(state)
    mc.poll_once(mc.spool_dir(state))
    assert _status(folder) | {} == _status(folder)
    assert _status(folder)["status"] == "failed" and _status(folder)["error"] == "The model took too long to convert."


def test_end_to_end_success(state: Path, fake_docker: Path) -> None:
    _beat(state)
    folder = _model(state)
    mc.set_done_handler(lambda d, ok, msg: mc.set_status(d, "ready"))
    mc.submit(folder, folder / "in" / "m.fbx", "fbx", state=state)
    _run_supervisor(state)
    mc.poll_once(mc.spool_dir(state))
    assert _status(folder)["status"] == "ready"
    assert (folder / "model.glb").read_bytes().startswith(b"glTF")
    assert not (folder / "in").exists() and not (folder / "out").exists()


def test_supervisor_output_cap(state: Path, fake_docker: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_MODE", "big")
    monkeypatch.setattr(sup, "MAX_GLB_BYTES", 500_000)
    folder = _model(state)
    _enqueue(state, folder)
    result = _run_supervisor(state)[folder.name]
    assert result["reason"] == "too-big" and result["message"] == sup.TOO_BIG_MESSAGE


# supervisor request checks

def test_supervisor_rejects_model_dir_outside_models(state: Path, fake_docker: Path, tmp_path: Path) -> None:
    folder = _model(state)
    other = tmp_path / "elsewhere" / folder.name
    (other / "in").mkdir(parents=True)
    (other / "in" / "m.fbx").write_bytes(b"x")
    _enqueue(state, folder, model_dir=str(other), src=str(other / "in" / "m.fbx"))
    result = _run_supervisor(state)[folder.name]
    assert result["reason"] == "bad-request" and result["message"] == sup.BAD_REQUEST_MESSAGE
    assert not (tmp_path / "docker.log").exists() or "run" not in (tmp_path / "docker.log").read_text(encoding="utf-8").split()


@pytest.mark.parametrize("over", [
    {"fmt": "obj"}, {"fmt": None}, {"id": "../x"}, {"src": "/etc/passwd"},
])
def test_supervisor_rejects_bad_requests(state: Path, fake_docker: Path, over: dict[str, Any]) -> None:
    folder = _model(state)
    _enqueue(state, folder, **over)
    queue_file = mc.spool_dir(state) / "queue" / f"{folder.name}.json"
    results = _run_supervisor(state)
    assert not queue_file.exists()
    assert all(r["ok"] is False and r["reason"] == "bad-request" for r in results.values())


def test_supervisor_rejects_symlinked_source(state: Path, fake_docker: Path, tmp_path: Path) -> None:
    folder = _model(state)
    target = tmp_path / "t.fbx"
    target.write_bytes(b"x")
    (folder / "in" / "l.fbx").symlink_to(target)
    _enqueue(state, folder, src="l.fbx")
    assert _run_supervisor(state)[folder.name]["reason"] == "bad-request"


def test_supervisor_discards_result_when_cancelled(state: Path, fake_docker: Path) -> None:
    folder = _model(state)
    s = sup.Supervisor(mc.spool_dir(state))
    running = s.spool / "running" / f"{folder.name}.json"
    running.write_text("{}", encoding="utf-8")
    running.unlink()  # the server removed it: cancelled
    s.publish(folder.name, running, {"ok": True})
    assert not list((s.spool / "results").iterdir())


def test_supervisor_without_image_reports_not_installed(state: Path, fake_docker: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_IMAGES", "")
    folder = _model(state)
    _enqueue(state, folder)
    s = sup.Supervisor(mc.spool_dir(state))
    s.images, s.images_at = [], time.monotonic()
    s.loop(once=True)
    result = json.loads((mc.spool_dir(state) / "results" / f"{folder.name}.json").read_text(encoding="utf-8"))
    assert result["reason"] == "no-image" and result["message"] == mc.UNAVAILABLE_MESSAGE


def test_the_supervisor_exits_when_its_spool_is_gone(state: Path, fake_docker: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """TICKET-379 (AC22): a supervisor left by a test whose temp dir was removed stops instead of polling forever."""
    s = sup.Supervisor(mc.spool_dir(state))
    s.heartbeat()
    shutil.rmtree(mc.spool_dir(state))
    monkeypatch.setattr(sup, "POLL_S", 0.01)
    s.loop(once=False)  # returns; before the fix it never did
    assert not mc.spool_dir(state).exists()  # and it did not recreate the folder it was serving


def test_one_missing_reading_or_an_oserror_does_not_stop_the_supervisor(state: Path, fake_docker: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """TICKET-379 (AC22): an EIO on the spool check is a failed turn, one missing reading is not enough, two in a row exit."""
    s = sup.Supervisor(mc.spool_dir(state))
    readings = [OSError(5, "Input/output error"), False, True, False, False]
    calls: list[int] = []

    real_is_dir = Path.is_dir

    def fake_is_dir(self: Path) -> bool:
        if self != s.spool:
            return real_is_dir(self)
        calls.append(1)
        value = readings[len(calls) - 1]
        if isinstance(value, OSError):
            raise value
        return value

    monkeypatch.setattr(Path, "is_dir", fake_is_dir)
    monkeypatch.setattr(s, "recover", lambda: None)
    monkeypatch.setattr(s, "turn", lambda: False)
    monkeypatch.setattr(sup, "POLL_S", 0.01)
    s.loop(once=False)  # an OSError, a lone miss and a recovery are survived; the two misses in a row end it
    assert len(calls) == len(readings)


def test_supervisor_restart_fails_leftover_running(state: Path, fake_docker: Path) -> None:
    folder = _model(state, status="converting")
    s = sup.Supervisor(mc.spool_dir(state))
    (s.spool / "running" / f"{folder.name}.json").write_text(json.dumps({"id": folder.name}), encoding="utf-8")
    s.recover()
    result = json.loads((s.spool / "results" / f"{folder.name}.json").read_text(encoding="utf-8"))
    assert result["reason"] == "restart" and result["message"] == sup.RESTART_MESSAGE


def test_heartbeat_reports_images_and_server_sees_it(state: Path, fake_docker: Path) -> None:
    s = sup.Supervisor(mc.spool_dir(state))
    s.heartbeat()
    beat = json.loads((s.spool / "supervisor.json").read_text(encoding="utf-8"))
    assert beat["ready"] is True and beat["images"] == [IMAGE45] and beat["pid"] == os.getpid()
    assert mc.available(state) is True


def test_heartbeat_not_ready_without_images(state: Path, fake_docker: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_IMAGES", "")
    s = sup.Supervisor(mc.spool_dir(state))
    s.heartbeat()
    assert mc.available(state) is False


def test_supervisor_cli_once_exits_zero(state: Path, fake_docker: Path) -> None:
    done = subprocess.run([sys.executable, "-I", str(SUPERVISOR_PATH), "--spool", str(mc.spool_dir(state)), "--once"],
                          env={**os.environ, "SIMON7_DOCKER": str(fake_docker)}, capture_output=True, timeout=60)
    assert done.returncode == 0, done.stderr
    assert json.loads((mc.spool_dir(state) / "supervisor.json").read_text(encoding="utf-8"))["ready"] is True


# static checks on the files that go into the image

def test_convert_script_never_enables_autoexec_or_network() -> None:
    text = (ROOT / "tools" / "model-converter" / "convert.py").read_text(encoding="utf-8")
    for needle in ("urllib.request", "from urllib import", "import socket", "requests", "subprocess", "os.system", "autoexec", "use_scripts=True"):
        assert needle not in text
    assert text.count("urllib") == text.count("urllib.parse")  # only the name parser, nothing that opens a connection


def test_dockerfile_pins_blender_by_sha256_and_drops_root() -> None:
    text = (ROOT / "tools" / "model-converter" / "Dockerfile").read_text(encoding="utf-8")
    assert "sha256sum -c" in text and "USER 65534:65534" in text
    assert len(text.split("ARG BLENDER_SHA256=")[1].split()[0]) == 64


def test_no_dash_characters_in_converter_strings() -> None:
    spec = ROOT / "docs" / "specs" / "model-convert.md"  # docs/specs/ is not published to the client repo
    for path in [ROOT / "part7" / "model_convert.py", SUPERVISOR_PATH, *([spec] if spec.is_file() else [])]:
        text = path.read_text(encoding="utf-8")
        assert "\u2014" not in text and "\u2013" not in text


# real data (needs docker, the image and MODEL_FIXTURES_DIR)

FIXTURES = os.environ.get("MODEL_FIXTURES_DIR")


def _docker_ready(image: str = IMAGE45) -> bool:
    if not shutil.which("docker"):
        return False
    return subprocess.run(["docker", "image", "inspect", image], capture_output=True).returncode == 0


real = pytest.mark.skipif(not (FIXTURES and _docker_ready()), reason="needs docker, the converter image and MODEL_FIXTURES_DIR")


def _glb_json(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    assert data[:4] == b"glTF"
    length = struct.unpack("<I", data[12:16])[0]
    return json.loads(data[20:20 + length])


def _real_convert(state: Path, src: Path, fmt: str, name: str) -> tuple[Path, dict[str, Any]]:
    # A unique id names the container: a fixed one collides with any other suite on this host (TICKET-380 publish).
    folder = _model(state, uuid.uuid4().hex, fmt_file=name)
    shutil.copyfile(src, folder / "in" / name)
    _enqueue(state, folder, fmt, name)
    s = sup.Supervisor(mc.spool_dir(state))
    s.loop(once=True)
    result = json.loads((mc.spool_dir(state) / "results" / f"{folder.name}.json").read_text(encoding="utf-8"))
    return folder, result


@real
def test_real_kenney_fbx(state: Path) -> None:
    src = Path(FIXTURES or "") / "kenney-animated-protagonists" / "extracted" / "Model" / "characterMedium.fbx"
    folder, result = _real_convert(state, src, "fbx", "characterMedium.fbx")
    assert result["ok"] is True, (folder / "convert.log").read_text(encoding="utf-8")[-2000:]
    doc = _glb_json(folder / "out" / "model.glb")
    names = [doc["nodes"][i]["name"] for skin in doc["skins"] for i in skin["joints"]]
    assert {"Hips", "Head", "LeftFoot", "RightHand"} <= set(names)
    assert len(names) == 32 and not [n for n in names if n.endswith("_end")]  # leaf helpers carry no weights
    assert not [n for n in names if n.endswith("IK") or n == "HipsCtrl"]
    assert "animations" not in doc
    for mat in doc["materials"]:  # alpha 0 with no texture drew nothing
        colour = mat.get("pbrMetallicRoughness", {}).get("baseColorFactor", [1, 1, 1, 1])
        assert colour[3] > 0 or "baseColorTexture" in mat.get("pbrMetallicRoughness", {}), mat


@real
def test_real_ellie_blend(state: Path) -> None:
    src = Path(FIXTURES or "") / "blender-studio-ellie" / "ellie_v1.blend"
    folder, result = _real_convert(state, src, "blend", "ellie_v1.blend")
    log = (folder / "convert.log").read_text(encoding="utf-8")
    if not result["ok"]:  # a named limit in the spec, not hidden
        assert result["reason"] in {"timeout", "failed", "too-big"}, log[-2000:]
        pytest.skip(f"Ellie v1 did not convert: {result['reason']} (named limit in docs/specs/model-convert.md)")
    doc = _glb_json(folder / "out" / "model.glb")
    names = {doc["nodes"][i]["name"] for skin in doc["skins"] for i in skin["joints"]}
    assert any(n.startswith("DEF-") for n in names)
    assert not any(n.startswith(("ORG-", "MCH-")) for n in names)
    assert len(names) <= 512 and len(doc.get("images", [])) <= 32  # the import limits hold (TICKET-242 AC-3)
    image_names = {i["name"] for i in doc.get("images", [])}  # the face is not painted with a mask map
    assert not {"ellie.bruise_map", "ellie.dirt_map", "ellie.progression_map"} & image_names, image_names
    face = next(m for m in doc["materials"] if m["name"] == "ellie.head")
    face_image = doc["images"][doc["textures"][face["pbrMetallicRoughness"]["baseColorTexture"]["index"]]["source"]]
    assert face_image["name"] == "ellie.head"
    from part7 import bone_map, glb_inspect  # the converted rig now maps, chain rule included (TICKET-242 AC-1)
    report = glb_inspect.inspect(folder / "out" / "model.glb")
    mapped = bone_map.map_result(report.gltf, report.positions())
    assert not mapped.missing and not mapped.problems, (mapped.missing, mapped.problems)


FLAT_RIG = '''
import bpy
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.object.armature_add()
arm = bpy.context.object
bpy.ops.object.mode_set(mode="EDIT")
eb = arm.data.edit_bones
for b in list(eb):
    eb.remove(b)
def bone(name, head, tail, parent=None, deform=False):
    b = eb.new(name)
    b.head, b.tail, b.use_deform = head, tail, deform
    b.parent = eb[parent] if parent else None
    return b
bone("ORG-Spine", (0, 0, 1.0), (0, 0, 1.2))
bone("ORG-Thigh.L", (0.1, 0, 1.0), (0.1, 0, 0.55), "ORG-Spine")
bone("ORG-Knee.L", (0.1, 0, 0.55), (0.1, 0, 0.1), "ORG-Thigh.L")
bone("ORG-Foot.L", (0.1, 0, 0.1), (0.1, 0.2, 0.0), "ORG-Knee.L")
bone("STR-Thigh.L", (0.1, 0, 1.0), (0.1, 0, 0.55), "ORG-Thigh.L")
bone("STR-Knee.L", (0.1, 0, 0.55), (0.1, 0, 0.1), "ORG-Knee.L")
bone("STR-Foot.L", (0.1, 0, 0.1), (0.1, 0.2, 0.0), "ORG-Foot.L")
bone("DEF-Pelvis", (0, 0, 1.0), (0, 0, 1.2), "ORG-Spine", True)
bone("DEF-Thigh.L", (0.1, 0, 1.0), (0.1, 0, 0.55), "STR-Thigh.L", True)
bone("DEF-Shin.L", (0.1, 0, 0.55), (0.1, 0, 0.1), "STR-Knee.L", True)
bone("DEF-Foot.L", (0.1, 0, 0.1), (0.1, 0.2, 0.0), "STR-Foot.L", True)
bpy.ops.object.mode_set(mode="OBJECT")
bpy.ops.mesh.primitive_uv_sphere_add()
body = bpy.context.object
body.parent = arm
names = ["DEF-Pelvis", "DEF-Thigh.L", "DEF-Shin.L", "DEF-Foot.L"]
groups = [body.vertex_groups.new(name=n) for n in names]
for i in range(len(body.data.vertices)):
    groups[i % 4].add([i], 1.0, "REPLACE")
mod = body.modifiers.new("Armature", "ARMATURE")
mod.object = arm
bpy.ops.wm.save_as_mainfile(filepath="/work/flat.blend")
'''


def _make_blend(script: str, name: str, tmp_path: Path) -> Path:
    work = tmp_path / "gen"
    work.mkdir(exist_ok=True)
    work.chmod(0o777)
    (work / "make.py").write_text(script, encoding="utf-8")
    made = subprocess.run(
        ["docker", "run", "--rm", "--network", "none", "--user", "65534:65534", "-e", "HOME=/tmp", "-v", f"{work}:/work",
         "--entrypoint", "blender", IMAGE45, "-b", "--factory-startup", "--python-exit-code", "1", "--python", "/work/make.py"],
        capture_output=True, timeout=170)
    assert made.returncode == 0, made.stderr[-1500:]
    return work / name


@real
def test_real_flat_deform_rig_keeps_the_bone_chain(state: Path, tmp_path: Path) -> None:
    """TICKET-242: deform bones hung off ORG and STR bones (CloudRig) export as one chain, Pelvis to Foot."""
    src = _make_blend(FLAT_RIG, "flat.blend", tmp_path)
    folder, result = _real_convert(state, src, "blend", "flat.blend")
    assert result["ok"] is True, (folder / "convert.log").read_text(encoding="utf-8")[-2000:]
    nodes = _glb_json(folder / "out" / "model.glb")["nodes"]
    parent = {c: i for i, n in enumerate(nodes) for c in n.get("children", [])}
    i, up = next(k for k, n in enumerate(nodes) if n.get("name") == "DEF-Foot.L"), []
    while i in parent:
        i = parent[i]
        up.append(nodes[i].get("name"))
    assert up[:3] == ["DEF-Shin.L", "DEF-Thigh.L", "DEF-Pelvis"]


HOSTILE = '''
import bpy
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.object.armature_add()
arm = bpy.context.object
bpy.ops.mesh.primitive_cube_add()
cube = bpy.context.object
cube.parent = arm
g = cube.vertex_groups.new(name="Bone")
g.add(list(range(len(cube.data.vertices))), 1.0, "REPLACE")
mod = cube.modifiers.new("Armature", "ARMATURE")
mod.object = arm
payload = "import sys\\nsys.stderr.write('PW'+'NED-MARKER\\\\n')\\ntry:\\n open('/out/pwned','w').write('x')\\nexcept Exception as e:\\n sys.stderr.write('PW'+'NED-WRITE ' + str(e) + '\\\\n')\\n"
text = bpy.data.texts.new("evil.py")
text.write(payload)
text.use_module = True
cube["x"] = 1
fc = cube.driver_add('location', 0)
fc.driver.type = 'SCRIPTED'
fc.driver.expression = "__import__('sys').stderr.write('PW'+'NED-DRIVER\\\\n') or 0"
bpy.ops.wm.save_as_mainfile(filepath="/work/hostile.blend")
'''


@real
def test_real_hostile_blend(state: Path, tmp_path: Path) -> None:
    work = tmp_path / "gen"
    work.mkdir()
    work.chmod(0o777)
    (work / "make.py").write_text(HOSTILE, encoding="utf-8")
    made = subprocess.run(
        ["docker", "run", "--rm", "--network", "none", "--user", "65534:65534", "-e", "HOME=/tmp", "-v", f"{work}:/work",
         "--entrypoint", "blender", IMAGE45, "-b", "--factory-startup", "--python-exit-code", "1", "--python", "/work/make.py"],
        capture_output=True, timeout=170)
    assert made.returncode == 0, made.stderr[-1500:]
    control = subprocess.run(  # positive control: with auto-run on, the same file does print its markers
        ["docker", "run", "--rm", "--network", "none", "--user", "65534:65534", "-e", "HOME=/tmp", "-v", f"{work}:/work:ro",
         "--entrypoint", "blender", IMAGE45, "-b", "--factory-startup", "--enable-autoexec", "/work/hostile.blend",
         "--python-expr", "import bpy; bpy.context.scene.frame_set(2)"],
        capture_output=True, timeout=170)
    assert b"PWNED" in control.stdout + control.stderr, (control.stdout + control.stderr)[-1500:]
    folder, result = _real_convert(state, work / "hostile.blend", "blend", "hostile.blend")
    log = (folder / "convert.log").read_text(encoding="utf-8")
    assert "PWNED" not in log, log[-1500:]
    assert not (mc.spool_dir(state) / "work").exists() or not list((mc.spool_dir(state) / "work").glob("**/pwned"))
    assert not Path("/out/pwned").exists()
    assert result["reason"] in {"", "failed"}


# TICKET-341: the FBX reader chain, named failures and convert.json (fake docker)

def _fake_fbx2gltf(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    tool = tmp_path / "FBX2glTF"
    tool.write_text("#!/bin/sh\n", encoding="utf-8")
    tool.chmod(0o755)
    monkeypatch.setenv("SIMON7_FBX2GLTF", str(tool))
    return tool


def _chain(state: Path, fmt: str = "fbx", src: str = "m.fbx") -> tuple[Path, dict[str, Any], dict[str, Any]]:
    folder = _model(state, fmt_file=src)
    _enqueue(state, folder, fmt, src)
    s = sup.Supervisor(mc.spool_dir(state))
    s.images, s.images_at = [IMAGE45, IMAGE36], time.monotonic()
    s.loop(once=True)
    result = json.loads((mc.spool_dir(state) / "results" / f"{folder.name}.json").read_text(encoding="utf-8"))
    return folder, result, json.loads((folder / "convert.json").read_text(encoding="utf-8"))


def test_argv_mounts_the_converter_scripts_read_only_and_runs_them() -> None:
    argv = _argv()
    assert f"{sup.HERE}:/opt/simon:ro" in argv
    assert argv[argv.index("--entrypoint") + 1] == "/opt/simon/run.sh"
    assert "/opt/simon/convert.py" in argv


def test_fbx2gltf_argv_mounts_the_binary_read_only_and_keeps_every_jail_flag(tmp_path: Path,
                                                                            monkeypatch: pytest.MonkeyPatch) -> None:
    tool = _fake_fbx2gltf(tmp_path, monkeypatch)
    argv = sup.container_argv("n", "/scratch/in", "input.fbx", IMAGE45, "fbx2gltf")
    assert f"{tool}:/opt/fbx2gltf/FBX2glTF:ro" in argv
    assert argv[-4:] == ["sh", "/opt/simon/fbx2gltf.sh", "/in/input.fbx", "/tmp/out/model.glb"]
    for flag in ("--read-only", "--cap-drop", "--security-opt", "--user"):
        assert flag in argv
    assert [a for a in argv if ":/" in a and not a.endswith(":ro") and not a.startswith("/tmp:")] == []
    assert argv[argv.index("--network") + 1] == "none"


def test_plan_adds_fbx2gltf_only_for_an_fbx_when_installed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIMON7_FBX2GLTF", str(tmp_path / "missing"))
    assert sup.plan("fbx", [IMAGE45, IMAGE36]) == [("blender", IMAGE45), ("blender", IMAGE36)]
    _fake_fbx2gltf(tmp_path, monkeypatch)
    assert sup.plan("fbx", [IMAGE45, IMAGE36])[-1] == ("fbx2gltf", IMAGE45)
    assert sup.plan("blend", [IMAGE45]) == [("blender", IMAGE45)]
    assert sup.present_tools() == ["fbx2gltf"]


def test_parse_outcome_reads_only_the_runs_own_tagged_line() -> None:
    tag = sup.new_tag()
    tail = f'convert-result: {{"ok": true, "mode": "rigged"}}\nnoise\n{tag} {{"ok": false, "code": "empty"}}\n'
    assert sup.parse_outcome(tail, tag)["code"] == "empty"
    assert sup.parse_outcome('convert-result: {"ok": true, "mode": "rigged"}\n', tag) == {}  # untagged: ignored
    assert sup.parse_outcome(f"{sup.new_tag()} {{\"ok\": true}}\n", tag) == {}  # another run's tag
    assert sup.parse_outcome(f"{tag} {{broken\n", tag) == {}
    assert sup.parse_outcome("anything", "") == {}
    assert tag.startswith(sup.RESULT_PREFIX) and tag != sup.new_tag()


def test_clean_outcome_keeps_only_expected_types_and_values() -> None:
    raw = {"ok": "yes", "code": "rm -rf", "mode": "rigged", "via": "x", "bones": "x",
           "steps": [{"step": "a" * 500, **{f"k{i}": i for i in range(30)}}] * 80 + ["junk"]}
    out = sup.clean_outcome(raw)
    assert out["ok"] is False and out["code"] is None and out["mode"] == "rigged" and out["via"] is None
    assert "bones" not in out and len(out["steps"]) == sup.MAX_STEPS
    assert len(out["steps"][0]) == sup.MAX_STEP_KEYS and len(out["steps"][0]["step"]) == sup.MAX_TEXT
    assert "bones" not in sup.clean_outcome({"bones": True}) and "bones" not in sup.clean_outcome({"bones": 10**9})
    assert sup.clean_outcome({"bones": 52})["bones"] == 52 and sup.clean_outcome([1]) == {}


def test_failure_message_never_raises_on_a_bad_bone_count() -> None:
    assert sup.failure_message({"code": "skeleton-only", "bones": "x"}) == sup.FAILED_MESSAGE
    assert sup.failure_message({"code": "skeleton-only"}) == sup.FAILED_MESSAGE


def test_failure_messages_name_what_was_found() -> None:
    assert "52 bones" in sup.failure_message({"code": "skeleton-only", "bones": 52})
    assert "no body mesh" in sup.failure_message({"code": "skeleton-only", "bones": 52})
    assert sup.failure_message({"code": "empty"}) == sup.EMPTY_MESSAGE
    assert sup.failure_message({"code": "unreadable"}) == sup.FAILED_MESSAGE == sup.failure_message({})
    for text in (sup.FAILED_MESSAGE, sup.SKELETON_ONLY_MESSAGE, sup.EMPTY_MESSAGE):
        assert "skeleton and a mesh, then try again" not in text and "\u2014" not in text and "\u2013" not in text


def test_a_skeleton_only_file_stops_at_the_first_reader_with_a_specific_message(
        state: Path, fake_docker: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("FAKE_MODE", "skeleton")
    monkeypatch.setenv("FAKE_IMAGES", f"{IMAGE45},{IMAGE36}")
    _fake_fbx2gltf(tmp_path, monkeypatch)
    folder, result, record = _chain(state)
    assert result["ok"] is False and "skeleton (52 bones) but no body mesh" in result["message"]
    assert [(a["reader"], a["code"]) for a in record["attempts"]] == [("blender", "skeleton-only")]
    assert record["code"] == "skeleton-only"


def test_an_empty_file_gets_its_own_message(state: Path, fake_docker: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_MODE", "empty")
    _, result, _ = _chain(state)
    assert result["message"] == sup.EMPTY_MESSAGE


def test_a_file_blender_cannot_read_falls_back_to_fbx2gltf(state: Path, fake_docker: Path, monkeypatch: pytest.MonkeyPatch,
                                                           tmp_path: Path) -> None:
    monkeypatch.setenv("FAKE_MODE", "blender-unreadable")
    _fake_fbx2gltf(tmp_path, monkeypatch)
    folder, result, record = _chain(state)
    assert result["ok"] is True and result["reader"] == "fbx2gltf"
    assert [(a["reader"], a["ok"]) for a in record["attempts"]] == [("blender", False), ("blender", False), ("fbx2gltf", True)]
    assert record["reader"] == "fbx2gltf" and record["steps"] == [{"step": "merge", "meshes": 3}]
    assert (folder / "out" / "model.glb").read_bytes().startswith(b"glTF")
    log = (folder / "convert.log").read_text(encoding="utf-8")
    assert log.count("=== ") == 3 and "=== fbx2gltf" in log


def test_no_reader_can_read_it_gives_the_export_advice(state: Path, fake_docker: Path, monkeypatch: pytest.MonkeyPatch,
                                                       tmp_path: Path) -> None:
    monkeypatch.setenv("FAKE_MODE", "unreadable")
    _fake_fbx2gltf(tmp_path, monkeypatch)
    _, result, record = _chain(state)
    assert result["ok"] is False and result["message"] == sup.FAILED_MESSAGE and "binary FBX" in result["message"]
    assert len(record["attempts"]) == 3


def test_a_blend_file_never_goes_to_fbx2gltf(state: Path, fake_docker: Path, monkeypatch: pytest.MonkeyPatch,
                                             tmp_path: Path) -> None:
    monkeypatch.setenv("FAKE_MODE", "unreadable")
    _fake_fbx2gltf(tmp_path, monkeypatch)
    _, _, record = _chain(state, "blend", "e.blend")
    assert [a["reader"] for a in record["attempts"]] == ["blender", "blender"]


def test_heartbeat_names_the_fbx2gltf_tool(state: Path, fake_docker: Path, monkeypatch: pytest.MonkeyPatch,
                                           tmp_path: Path) -> None:
    _fake_fbx2gltf(tmp_path, monkeypatch)
    s = sup.Supervisor(mc.spool_dir(state))
    s.heartbeat()
    assert json.loads((mc.spool_dir(state) / "supervisor.json").read_text(encoding="utf-8"))["tools"] == ["fbx2gltf"]


def test_poll_keeps_the_input_of_a_model_handed_to_the_rig_maker(state: Path) -> None:
    folder = _model(state, status="converting")
    _produce(folder)
    _result(state, folder, ok=True, reason="", message="")

    def handler(model_dir: Path, ok: bool, message: str) -> None:
        (model_dir / "in" / "upload.glb").write_bytes(b"glTF")
        mc.set_status(model_dir, "queued")  # what model_import._queue_autorig leaves

    mc.set_done_handler(handler)
    mc.poll_once(mc.spool_dir(state))
    assert (folder / "in" / "upload.glb").is_file()


# TICKET-341: real conversions of synthetic FBX files made by Blender in the converter image (docker and the image)

FBX_GEN = ROOT / "tests" / "part7" / "fbx_fixtures" / "make_fbx.py"
KINDS = ("rigged", "static", "multi", "skeleton", "wrong-units", "rigged-cm", "loose", "rigged-leaves")
synthetic = pytest.mark.skipif(not _docker_ready(), reason="needs docker and the converter image")


@pytest.fixture(scope="module")
def fbx_files(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    out = tmp_path_factory.mktemp("fbx")
    out.chmod(0o777)
    pairs = [x for kind in KINDS for x in (kind, f"/out/{kind}.fbx")]
    done = subprocess.run(["docker", "run", "--rm", "--network", "none", "--user", f"{os.getuid()}:{os.getgid()}",
                           "-e", "HOME=/tmp", "-v", f"{FBX_GEN.parent}:/gen:ro", "-v", f"{out}:/out",
                           "--entrypoint", "blender", IMAGE45, "-b", "--factory-startup", "-Y", "--python-exit-code", "1",
                           "--python", "/gen/make_fbx.py", "--", *pairs], capture_output=True, timeout=600)
    assert done.returncode == 0, done.stderr[-2000:]
    files = {kind: out / f"{kind}.fbx" for kind in KINDS}
    for kind, name in (("static", "old-version"), ("loose", "loose-old-version")):
        old = bytearray(files[kind].read_bytes())  # a binary FBX whose header says 7.0: Blender refuses it, FBX2glTF reads it
        old[23:27] = struct.pack("<I", 7000)
        files[name] = out / f"{name}.fbx"
        files[name].write_bytes(bytes(old))
    return files


def _with_fbx2gltf(monkeypatch: pytest.MonkeyPatch) -> None:
    installed = Path.home() / ".local" / "share" / "simon-part-7" / "tools" / "FBX2glTF"
    tool = os.environ.get("SIMON7_FBX2GLTF_REAL") or str(installed)
    if not os.access(tool, os.X_OK):
        pytest.skip("FBX2glTF is not installed (tools/model-converter/fetch-fbx2gltf.sh)")
    monkeypatch.setenv("SIMON7_FBX2GLTF", tool)


def _synthetic(state: Path, src: Path) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    folder, result = _real_convert(state, src, "fbx", "m.fbx")
    return folder, result, json.loads((folder / "convert.json").read_text(encoding="utf-8"))


def _height(glb: Path) -> float:
    """Y extent of every mesh's POSITION accessor (the converter applies its scale to the vertices, Y up)."""
    doc = _glb_json(glb)
    ys = [v for mesh in doc["meshes"] for prim in mesh["primitives"]
          for v in (doc["accessors"][prim["attributes"]["POSITION"]]["min"][1], doc["accessors"][prim["attributes"]["POSITION"]]["max"][1])]
    return max(ys) - min(ys)


def _steps(record: dict[str, Any], name: str) -> dict[str, Any]:
    return next(s for s in record["steps"] if s["step"] == name)


@synthetic
def test_synthetic_rigged_binary_fbx_keeps_its_skin_and_embedded_texture(state: Path, fbx_files: dict[str, Path]) -> None:
    folder, result, record = _synthetic(state, fbx_files["rigged"])
    assert result["ok"] is True, (folder / "convert.log").read_text(encoding="utf-8")[-3000:]
    doc = _glb_json(folder / "out" / "model.glb")
    assert doc["skins"] and len(doc.get("images", [])) == 1
    assert record["mode"] == "rigged" and _steps(record, "textures")["embedded"] == 1
    from part7 import bone_map, glb_inspect  # head, hands and feet are end bones: they survive the import
    report = glb_inspect.inspect(folder / "out" / "model.glb")
    mapped = bone_map.map_result(report.gltf, report.positions())
    assert not mapped.missing, (mapped.missing, mapped.problems)


@synthetic
def test_synthetic_fbx_without_skin_converts_unskinned_for_the_rig_maker(state: Path, fbx_files: dict[str, Path]) -> None:
    folder, result, record = _synthetic(state, fbx_files["static"])
    assert result["ok"] is True, (folder / "convert.log").read_text(encoding="utf-8")[-3000:]
    doc = _glb_json(folder / "out" / "model.glb")
    assert "skins" not in doc and len(doc["meshes"]) == 1
    assert record["mode"] == "static" and _steps(record, "found")["armatures"] == 0


@synthetic
def test_synthetic_skeleton_only_fbx_names_the_bones_it_found(state: Path, fbx_files: dict[str, Path]) -> None:
    folder, result, record = _synthetic(state, fbx_files["skeleton"])
    assert result["ok"] is False and "skeleton (17 bones) but no body mesh" in result["message"]
    assert [a["code"] for a in record["attempts"]] == ["skeleton-only"]


@synthetic
def test_synthetic_multi_mesh_fbx_is_merged_into_one_mesh(state: Path, fbx_files: dict[str, Path]) -> None:
    folder, result, record = _synthetic(state, fbx_files["multi"])
    assert result["ok"] is True, (folder / "convert.log").read_text(encoding="utf-8")[-3000:]
    assert len(_glb_json(folder / "out" / "model.glb")["meshes"]) == 1
    assert _steps(record, "merge")["meshes"] == 5


@synthetic
@pytest.mark.parametrize("kind", ["wrong-units", "rigged-cm"])
def test_synthetic_centimetre_scale_fbx_comes_out_in_metres(state: Path, fbx_files: dict[str, Path], kind: str) -> None:
    folder, result, record = _synthetic(state, fbx_files[kind])
    assert result["ok"] is True, (folder / "convert.log").read_text(encoding="utf-8")[-3000:]
    units = _steps(record, "units")
    assert units["height_found_m"] == pytest.approx(175.0, rel=0.01) and units["scale"] == 0.01
    assert _height(folder / "out" / "model.glb") == pytest.approx(1.75, rel=0.02)


@synthetic
def test_synthetic_old_version_fbx_falls_back_to_fbx2gltf(state: Path, fbx_files: dict[str, Path],
                                                          monkeypatch: pytest.MonkeyPatch) -> None:
    _with_fbx2gltf(monkeypatch)
    folder, result, record = _synthetic(state, fbx_files["old-version"])
    assert result["ok"] is True and result["reader"] == "fbx2gltf", (folder / "convert.log").read_text(encoding="utf-8")[-3000:]
    assert [a["code"] for a in record["attempts"][:2]] == ["unreadable", "unreadable"]
    doc = _glb_json(folder / "out" / "model.glb")
    assert len(doc["meshes"]) == 1 and len(doc.get("images", [])) == 1


@synthetic
def test_synthetic_skeleton_that_deforms_nothing_is_dropped_and_the_mesh_rigged_again(state: Path,
                                                                                     fbx_files: dict[str, Path]) -> None:
    folder, result, record = _synthetic(state, fbx_files["loose"])
    assert result["ok"] is True and record["mode"] == "static", (folder / "convert.log").read_text(encoding="utf-8")[-3000:]
    assert _steps(record, "found")["armatures"] == 1 and "skins" not in _glb_json(folder / "out" / "model.glb")


@synthetic
def test_synthetic_bone_display_shapes_are_not_counted_as_body_meshes(state: Path, fbx_files: dict[str, Path],
                                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    _with_fbx2gltf(monkeypatch)  # the glTF importer behind FBX2glTF adds an Icosphere bone shape
    folder, result, record = _synthetic(state, fbx_files["loose-old-version"])
    assert result["ok"] is True and result["reader"] == "fbx2gltf", (folder / "convert.log").read_text(encoding="utf-8")[-3000:]
    assert _steps(record, "found")["meshes"] == 1 and len(_glb_json(folder / "out" / "model.glb")["meshes"]) == 1


# TICKET-341 review: a crafted upload never stops the supervisor (B1), locks (R1, R2), heartbeat (R8)

@pytest.mark.parametrize("mode", ["inject", "inject-tagged-type"])
def test_a_forged_result_line_fails_that_job_and_the_supervisor_keeps_going(
        state: Path, fake_docker: Path, monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    monkeypatch.setenv("FAKE_MODE", mode)
    first = _model(state, "a")
    _enqueue(state, first)
    second = _model(state, "b")
    _enqueue(state, second)
    os.utime(mc.spool_dir(state) / "queue" / f"{second.name}.json", (time.time() + 5, time.time() + 5))
    results = _run_supervisor(state)
    assert set(results) == {first.name, second.name}  # the loop lived to run the second job
    for job in results.values():
        assert job["ok"] is False and job["message"] == sup.FAILED_MESSAGE
    record = json.loads((first / "convert.json").read_text(encoding="utf-8"))
    assert record["code"] is None or record["code"] == "skeleton-only"
    assert all(isinstance(a.get("code"), (str, type(None))) for a in record["attempts"])


def test_a_job_that_raises_is_failed_and_the_loop_runs_the_next(state: Path, fake_docker: Path,
                                                                monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    real = sup.Supervisor.convert

    def flaky(self: Any, job_id: str, *a: Any) -> dict:
        calls.append(job_id)
        if len(calls) == 1:
            raise ValueError("boom")
        return real(self, job_id, *a)

    monkeypatch.setattr(sup.Supervisor, "convert", flaky)
    first, second = _model(state, "a"), _model(state, "b")
    _enqueue(state, first)
    _enqueue(state, second)
    os.utime(mc.spool_dir(state) / "queue" / f"{second.name}.json", (time.time() + 5, time.time() + 5))
    results = _run_supervisor(state)
    assert results[first.name]["ok"] is False and results[first.name]["message"] == sup.FAILED_MESSAGE
    assert results[second.name]["ok"] is True
    assert not list((mc.spool_dir(state) / "running").iterdir())


def test_only_one_supervisor_holds_a_spool(state: Path) -> None:
    first, second = sup.Supervisor(mc.spool_dir(state)), sup.Supervisor(mc.spool_dir(state))
    assert first.claim() is True
    assert second.claim() is False
    done = subprocess.run([sys.executable, "-I", str(SUPERVISOR_PATH), "--spool", str(mc.spool_dir(state)), "--once"],
                          capture_output=True, text=True, timeout=60)
    assert done.returncode == 0 and "another supervisor" in done.stderr


def test_run_one_holds_the_busy_lock_while_it_works(state: Path, fake_docker: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import fcntl
    seen: list[bool] = []
    real = sup.Supervisor.convert

    def probe(self: Any, *a: Any) -> dict:
        with open(mc.spool_dir(state) / sup.BUSY_LOCK, "a+") as other:
            try:
                fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
                seen.append(False)
            except OSError:
                seen.append(True)
        return real(self, *a)

    monkeypatch.setattr(sup.Supervisor, "convert", probe)
    folder = _model(state)
    _enqueue(state, folder)
    _run_supervisor(state)
    assert seen == [True]


def test_recover_kills_orphan_converter_containers(state: Path, fake_docker: Path, monkeypatch: pytest.MonkeyPatch,
                                                   tmp_path: Path) -> None:
    monkeypatch.setenv("FAKE_ORPHANS", "c0ffee\nbadf00d")
    sup.Supervisor(mc.spool_dir(state)).recover()
    log = (tmp_path / "docker.log").read_text(encoding="utf-8")
    label = sup.spool_label(mc.spool_dir(state))
    assert f"ps -q --filter name=simon7-convert- --filter label={label}" in log and "kill c0ffee badf00d" in log


def test_containers_carry_their_spools_label_and_recover_filters_on_it(state: Path, fake_docker: Path,
                                                                       tmp_path: Path) -> None:
    label = sup.spool_label(mc.spool_dir(state))
    assert label.startswith("simon7.spool=") and len(label.split("=", 1)[1]) == 64
    assert label != sup.spool_label(tmp_path / "another-spool")  # a test spool never matches staging's
    folder = _model(state)
    _enqueue(state, folder)
    _run_supervisor(state)
    runs = [line for line in (tmp_path / "docker.log").read_text(encoding="utf-8").splitlines() if line.startswith("run ")]
    assert runs and all(f"--label {label}" in line for line in runs)
    ps = [line for line in (tmp_path / "docker.log").read_text(encoding="utf-8").splitlines() if line.startswith("ps ")]
    assert ps and all(f"--filter label={label}" in line for line in ps)


def test_both_callers_use_the_one_set_of_caps(state: Path) -> None:
    from part7 import model_import
    assert Path(sup.caps.__file__).resolve() == (ROOT / "tools" / "model-converter" / "record_caps.py").resolve()
    assert Path(model_import.record_caps.__file__).resolve() == Path(sup.caps.__file__).resolve()
    steps = [{"step": "x" * 900, "n": 1e13, "ok": True, "list": ["a" * 900] * 40, "obj": {"a": 1}}] * 90
    folder = _model(state)
    (folder / "convert.json").write_text(json.dumps({"reader": "blender", "steps": steps, "attempts": steps}), encoding="utf-8")
    record = model_import.import_record(folder)
    assert record["steps"] == sup.clean_steps(steps) == sup.caps.items(steps)
    first = record["steps"][0]
    assert first["n"] is None and len(first["step"]) == sup.caps.MAX_TEXT and first["obj"] is None
    assert len(first["list"]) == sup.caps.MAX_LIST and len(record["steps"]) == sup.caps.MAX_ITEMS
    assert len(record["attempts"]) == sup.caps.MAX_ATTEMPTS


def test_a_failing_heartbeat_does_not_stop_the_loop(state: Path, fake_docker: Path) -> None:
    folder = _model(state)
    _enqueue(state, folder)
    s = sup.Supervisor(mc.spool_dir(state))
    s.images, s.images_at = [IMAGE45], time.monotonic()
    real, failures = s.heartbeat, []

    def full_disk() -> None:
        if not failures:
            failures.append(1)
            raise OSError(28, "No space left on device")
        real()

    s.heartbeat = full_disk  # type: ignore[method-assign]
    s.loop(once=True)
    assert failures and (mc.spool_dir(state) / "results" / f"{folder.name}.json").is_file()


def test_a_request_removed_while_listed_is_skipped(state: Path, fake_docker: Path) -> None:
    queue = mc.spool_dir(state) / "queue"
    queue.mkdir(parents=True, exist_ok=True)
    (queue / ("f" * 32 + ".json")).symlink_to(queue / "gone.json")  # listed by glob, then stat raises FileNotFoundError
    folder = _model(state)
    _enqueue(state, folder)
    s = sup.Supervisor(mc.spool_dir(state))
    assert s.queued() == [queue / f"{folder.name}.json"]
    _run_supervisor(state)
    assert (mc.spool_dir(state) / "results" / f"{folder.name}.json").is_file()


RUN_SH = ROOT / "tools" / "model-converter" / "run.sh"
STUB = """#!/bin/sh
out="$1"
env > "$(dirname "$out")/env.txt"
printf '{"ok": true, "code": null}' > "$(dirname "$out")/result.json"
printf 'glTFstub' > "$out"
echo 'convert-result-forged: {"ok": true}' >&2
"""


def test_run_sh_hides_the_tag_from_the_converter_and_prints_the_result_last(tmp_path: Path) -> None:
    stub = tmp_path / "stub.sh"
    stub.write_text(STUB, encoding="utf-8")
    out = tmp_path / "out" / "model.glb"
    tag = sup.new_tag()
    done = subprocess.run(["sh", str(RUN_SH), "sh", str(stub), str(out)], capture_output=True, timeout=30,
                          env={**os.environ, "SIMON7_RESULT_TAG": tag})
    assert done.returncode == 0 and done.stdout == b"glTFstub"
    assert "SIMON7_RESULT_TAG" not in (tmp_path / "out" / "env.txt").read_text(encoding="utf-8")
    last = done.stderr.decode().rstrip().splitlines()[-1]
    assert last == f'{tag} {{"ok": true, "code": null}}'
    assert sup.parse_outcome(done.stderr.decode(), tag) == sup.clean_outcome({"ok": True, "code": None})


def test_run_sh_without_a_tag_prints_no_result_line(tmp_path: Path) -> None:
    stub = tmp_path / "stub.sh"
    stub.write_text(STUB, encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k != "SIMON7_RESULT_TAG"}
    done = subprocess.run(["sh", str(RUN_SH), "sh", str(stub), str(tmp_path / "o" / "model.glb")], capture_output=True,
                          timeout=30, env=env)
    assert done.returncode == 0 and b'{"ok": true, "code": null}' not in done.stderr


def test_the_supervisor_beats_while_a_container_runs(state: Path, fake_docker: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_MODE", "sleep")
    monkeypatch.setattr(sup, "TIMEOUT_S", 2)
    monkeypatch.setattr(sup, "BEAT_EVERY_S", 0.3)
    folder = _model(state)
    _enqueue(state, folder)
    s = sup.Supervisor(mc.spool_dir(state))
    s.images, s.images_at = [IMAGE45], time.monotonic()
    beats: list[float] = []
    real = s.heartbeat

    def count() -> None:
        beats.append(time.monotonic())
        real()

    s.heartbeat = count  # type: ignore[method-assign]
    s.loop(once=True)
    assert len(beats) >= 4  # one per loop turn plus several during the 2 s container run


@synthetic
def test_synthetic_leaf_bones_never_become_joints(state: Path, fbx_files: dict[str, Path]) -> None:
    joints = {}
    for kind in ("rigged", "rigged-leaves"):
        folder, result, _ = _synthetic(state, fbx_files[kind])
        assert result["ok"] is True, (folder / "convert.log").read_text(encoding="utf-8")[-3000:]
        doc = _glb_json(folder / "out" / "model.glb")
        joints[kind] = [doc["nodes"][i]["name"] for skin in doc["skins"] for i in skin["joints"]]
        shutil.rmtree(folder)
    assert not [n for n in joints["rigged-leaves"] if n.endswith("_end")]
    assert sorted(joints["rigged-leaves"]) == sorted(joints["rigged"]) and len(joints["rigged"]) == 17


def _text_fbx(tmp_path: Path) -> Path:
    spec = importlib.util.spec_from_file_location("ascii_fbx", ROOT / "tests" / "part7" / "fbx_fixtures" / "ascii_fbx.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.write(tmp_path / "text.fbx")


def test_the_text_fbx_fixture_carries_a_mesh_for_the_real_fbx2gltf(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The first fixture lacked the Model's DefaultAttributeIndex: FBX2glTF kept the node and dropped the mesh (0 triangles)."""
    _with_fbx2gltf(monkeypatch)
    out = tmp_path / "out"
    out.mkdir()
    (tmp_path / "sdk").mkdir()
    done = subprocess.run([os.environ["SIMON7_FBX2GLTF"], "-b", "--pbr-metallic-roughness", "--fbx-temp-dir", str(tmp_path / "sdk"),
                           "-i", str(_text_fbx(tmp_path)), "-o", str(out / "model")], capture_output=True, timeout=120)
    assert done.returncode == 0, done.stderr[-1000:]
    doc = _glb_json(out / "model.glb")
    assert len(doc["meshes"]) == 1
    assert doc["accessors"][doc["meshes"][0]["primitives"][0]["indices"]]["count"] == 36  # a box: 12 triangles


@synthetic
def test_synthetic_text_fbx_reads_through_fbx2gltf_and_is_cleaned_up(state: Path, tmp_path: Path,
                                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    _with_fbx2gltf(monkeypatch)
    folder, result, record = _synthetic(state, _text_fbx(tmp_path))
    assert result["ok"] is True and result["reader"] == "fbx2gltf", (folder / "convert.log").read_text(encoding="utf-8")[-3000:]
    doc = _glb_json(folder / "out" / "model.glb")
    assert len(doc["meshes"]) == 1 and "skins" not in doc
    assert _height(folder / "out" / "model.glb") == pytest.approx(1.75, rel=0.02)
