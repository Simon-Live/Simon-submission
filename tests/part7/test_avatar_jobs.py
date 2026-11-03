"""Avatar job queue (docs/specs/avatar-jobs.md). Part 2 is a stand-in command in a real subprocess."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import threading
import time

import pytest

from part7 import avatar_jobs as aj, model_store
from support import dead_pid, live_process, stamp_of

STUB = r'''
import json, os, sys, time
from pathlib import Path
args = sys.argv[1:]
assert args[:1] == ["-m"] and args[1] == "part2", args
sub, rest = args[2], args[3:]
out = Path(rest[rest.index("--out") + 1])
files = [a for a in rest if a != "--out" and a != str(out)]
mode = os.environ.get("FAKE_MODE", "ok")
log = Path(os.environ["FAKE_LOG"])
with log.open("a") as fh:
    fh.write(json.dumps({"sub": sub, "files": files, "cwd": os.getcwd(), "pp": os.environ.get("PYTHONPATH"),
                         "secret": os.environ.get("SIMON7_FAKE_API_KEY")}) + "\n")
calls = len(log.read_text().splitlines())
if mode == "exit2":
    if os.environ.get("FAKE_STDERR", "") != "":
        sys.stderr.write(os.environ["FAKE_STDERR"] + "\n")
    sys.exit(2)
if mode == "exit3":
    sys.exit(3)
if mode == "exit4" or (mode == "busy_then_ok" and calls < 3):
    sys.exit(4)
if mode == "exit9":
    sys.exit(9)
if mode == "hang":
    time.sleep(60)
if mode == "slow":
    time.sleep(float(os.environ.get("FAKE_SLOW", "0.5")))
out.mkdir(parents=True)
if mode == "nothing":
    sys.exit(0)
(out / "model.glb").write_bytes(Path(os.environ["FAKE_GLB"]).read_bytes() if mode != "empty" else b"")
kind = "image" if sub == "avatar" else "autorig"
doc = {"schema": "simon.avatar.v1", "kind": kind if mode != "wrongkind" else "other", "inputs": len(files),
       "height_m": 1.7, "joints": 127, "mapped": {}, "part2_commit": "abc"}
if mode == "licence":
    doc["licence"] = "SAM License - MHR \u2014 notice"
(out / "avatar.json").write_text(json.dumps(doc) if mode != "badjson" else "{")
'''

SCRATCH = Path("/tmp/claude-1000/-home-gingy-claude-template/8ef63116-b407-46dd-9af6-851dd3cf56a7/scratchpad/models")
RIGGED = SCRATCH / "khronos-riggedfigure" / "RiggedFigure.glb"
TAKE = Path("/tmp/simon-demo-r17/state/jobs/4a946eb885b3/work/video.mp4")


@pytest.fixture
def env(tmp_path, monkeypatch):
    modules = tmp_path / "modules"
    (modules / "part-2").mkdir(parents=True)
    venv = tmp_path / "venv"
    (venv / "bin").mkdir(parents=True)
    stub = tmp_path / "stub_part2.py"
    stub.write_text(STUB)
    py = venv / "bin" / "python"
    py.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{stub}" "$@"\n')
    py.chmod(py.stat().st_mode | stat.S_IEXEC)
    glb = tmp_path / "fake.glb"
    glb.write_bytes(b"glTF" + bytes(range(64)))
    monkeypatch.setenv("SIMON7_MODULES_DIR", str(modules))
    monkeypatch.setenv("SIMON7_PART2_GPU_VENV", str(venv))
    monkeypatch.setenv("SIMON7_GPU_LOCK_PATH", str(tmp_path / "gpu.lock"))
    monkeypatch.setenv("FAKE_LOG", str(tmp_path / "calls.log"))
    monkeypatch.setenv("FAKE_GLB", str(glb))
    monkeypatch.setenv("SIMON7_FAKE_API_KEY", "must-not-leak")
    monkeypatch.setattr(aj, "MIN_FREE_MIB", 0)
    monkeypatch.setattr(aj, "MIN_FREE_MIB_IMAGE3D", 0)
    monkeypatch.setattr(aj, "RETRY_WAIT_S", 0.0)
    monkeypatch.setattr(aj, "CHECK_HOLD_S", 0.0)
    done = []

    def finalize(model_dir, glb_path, extra):
        done.append({"dir": Path(model_dir), "bytes": Path(glb_path).read_bytes(), "extra": extra,
                     "existed": Path(glb_path).is_file()})
        (Path(model_dir) / "model.glb").write_bytes(Path(glb_path).read_bytes())
        (Path(model_dir) / "character.json").write_text("{}")
        return {"schema": "simon.character.v1"}

    monkeypatch.setattr(aj, "_finalize_fn", lambda: finalize)
    aj.wait_idle(5)
    yield type("Env", (), {"tmp": tmp_path, "done": done, "glb": glb, "modules": modules,
                           "calls": lambda self: [json.loads(x) for x in (tmp_path / "calls.log").read_text().splitlines()]
                           if (tmp_path / "calls.log").exists() else []})()
    aj.wait_idle(10)


def make_model(env, name="a" * 32, n=1, owner="visitor-1", suffix=".jpg"):
    d = env.tmp / "models" / name
    (d / "in").mkdir(parents=True)
    files = []
    for i in range(n):
        f = d / "in" / f"p{i}{suffix}"
        f.write_bytes(b"x" * 10)
        files.append(f)
    (d / "status.json").write_text(json.dumps({"id": name, "status": "queued", "error": None, "missing": None,
                                               "owner": owner, "created_at": "2026-11-01T00:00:00Z", "bytes": 10}))
    return d, files


def status(d):
    return json.loads((d / "status.json").read_text())


def run_images(env, mode, n=1, **kw):
    os.environ["FAKE_MODE"] = mode
    d, files = make_model(env, n=n)
    aj.submit_images(d, files, "visitor-1")
    assert aj.wait_idle(30)
    return d


@pytest.fixture(autouse=True)
def _mode_reset():
    yield
    os.environ.pop("FAKE_MODE", None)
    os.environ.pop("FAKE_STDERR", None)


# AC-1
def test_submit_images_queues_and_returns_at_once(env):
    os.environ["FAKE_MODE"] = "slow"
    os.environ["FAKE_SLOW"] = "1"
    d, files = make_model(env, n=2)
    t = time.monotonic()
    aj.submit_images(d, files, "visitor-1")
    assert time.monotonic() - t < 0.5
    assert json.loads((d / "avatar-job.json").read_text())["kind"] == "image"
    assert status(d)["status"] in ("queued", "converting")
    assert aj.wait_idle(30)
    assert status(d)["status"] == "ready"
    del os.environ["FAKE_SLOW"]


@pytest.mark.parametrize("count", [0, 5])
def test_submit_images_count_bounds(env, count):
    d, files = make_model(env, n=max(count, 1))
    with pytest.raises(aj.AvatarError):
        aj.submit_images(d, files[:0] if count == 0 else files + [files[0]] * (count - len(files)), "o")
    assert not (d / "avatar-job.json").exists()
    assert status(d)["status"] == "queued"
    assert env.calls() == []


def test_submit_rejects_bad_files(env, tmp_path):
    d, files = make_model(env)
    with pytest.raises(aj.AvatarError):
        aj.submit_images(d, [d / "in" / "missing.jpg"], "o")
    with pytest.raises(aj.AvatarError):
        aj.submit_images(d, [d / "in"], "o")
    link = d / "in" / "link.jpg"
    link.symlink_to(files[0])
    with pytest.raises(aj.AvatarError):
        aj.submit_images(d, [link], "o")
    outside = tmp_path / "outside.jpg"
    outside.write_bytes(b"x")
    with pytest.raises(aj.AvatarError):
        aj.submit_images(d, [outside], "o")
    assert not (d / "avatar-job.json").exists()


# AC-2
def test_submit_autorig_takes_exactly_one(env):
    os.environ["FAKE_MODE"] = "ok"
    d, files = make_model(env, n=2, suffix=".glb")
    with pytest.raises(aj.AvatarError):
        aj.submit_autorig(d, files[0].parent, "o")
    aj.submit_autorig(d, files[0], "visitor-1")
    assert aj.wait_idle(30)
    call = env.calls()[0]
    assert call["sub"] == "autorig" and call["files"] == [str(files[0])]
    assert env.done[0]["extra"]["source_kind"] == "autorig"


# AC-3, AC-5, AC-4, AC-10
def test_success_runs_part2_finalizes_and_cleans(env):
    d = run_images(env, "ok", n=3)
    call = env.calls()[0]
    assert call["sub"] == "avatar" and len(call["files"]) == 3
    assert call["cwd"] == str(env.modules / "part-2") and call["pp"] == str(env.modules / "part-2")
    assert call["secret"] is None  # secrets are not handed to Part 2
    assert len(env.done) == 1
    done = env.done[0]
    assert done["bytes"] == env.glb.read_bytes() and done["existed"]
    assert done["extra"]["kind"] == "generated" and done["extra"]["preset"] == "simon-avatar"
    assert done["extra"]["licence"] == {"id": "own-work", "attribution": aj.DEFAULT_ATTRIBUTION, "shareable": False}
    st = status(d)
    assert st["status"] == "ready" and st["error"] is None
    assert st["owner"] == "visitor-1" and st["id"] == "a" * 32 and st["created_at"] == "2026-11-01T00:00:00Z"
    assert not (d / "in").exists() and not (d / "out").exists()
    assert (d / "model.glb").is_file() and (d / "character.json").is_file()


def test_licence_text_from_avatar_json_is_cleaned(env):
    run_images(env, "licence")
    att = env.done[0]["extra"]["licence"]["attribution"]
    assert att.startswith("SAM License") and "\u2014" not in att and " - " not in att


def test_jobs_run_one_at_a_time_in_order(env, monkeypatch):
    os.environ["FAKE_MODE"] = "slow"
    os.environ["FAKE_SLOW"] = "0.3"
    active, peak = [0], [0]
    real = aj.gpu_lock.acquire

    import contextlib

    @contextlib.contextmanager
    def counting(**kw):
        assert kw["hold_flock"] is False and kw["min_free_mib"] == 0
        with real(**kw):
            active[0] += 1
            peak[0] = max(peak[0], active[0])
            yield
            active[0] -= 1

    monkeypatch.setattr(aj.gpu_lock, "acquire", counting)
    dirs = []
    for i in range(3):
        d, files = make_model(env, name=f"{i:032x}")
        aj.submit_images(d, files, "o")
        dirs.append(d)
    assert aj.wait_idle(60)
    assert peak[0] == 1
    assert [x["dir"].name for x in env.done] == [d.name for d in dirs]
    del os.environ["FAKE_SLOW"]


# AC-6
def test_exit2_uses_first_clean_stderr_line(env):
    os.environ["FAKE_STDERR"] = "image 1 is not a photo \u2014 too small\x07"
    d = run_images(env, "exit2")
    st = status(d)
    assert st["status"] == "failed" and st["error"] == "image 1 is not a photo, too small"
    assert not (d / "in").exists() and env.done == []


def test_exit2_without_stderr_has_default(env):
    assert status(run_images(env, "exit2"))["error"] == aj.MSG_BAD_IMAGES


def test_exit2_stderr_is_bounded(env):
    os.environ["FAKE_STDERR"] = "x" * 900
    assert len(status(run_images(env, "exit2"))["error"]) == aj.MESSAGE_MAX


def test_exit3_no_person(env):
    assert status(run_images(env, "exit3"))["error"] == "We could not find a person in the picture."


def test_exit3_autorig_wording(env):
    os.environ["FAKE_MODE"] = "exit3"
    d, files = make_model(env, suffix=".obj")
    aj.submit_autorig(d, files[0], "o")
    aj.wait_idle(30)
    assert status(d)["error"] == "We could not find a body in the mesh."


def test_exit4_retries_then_fails(env):
    d = run_images(env, "exit4")
    assert len(env.calls()) == aj.BUSY_RETRIES + 1
    assert status(d)["error"] == aj.MSG_GPU_BUSY


def test_exit4_twice_then_ok(env):
    d = run_images(env, "busy_then_ok")
    assert len(env.calls()) == 3 and status(d)["status"] == "ready"


def test_other_exit_is_generic(env):
    assert status(run_images(env, "exit9"))["error"] == aj.MSG_FAILED


# AC-7
@pytest.mark.parametrize("mode", ["nothing", "empty", "badjson", "wrongkind"])
def test_unusable_output(env, mode):
    d = run_images(env, mode)
    assert status(d)["status"] == "failed" and status(d)["error"] == aj.MSG_UNUSABLE
    assert env.done == []


# AC-8
def test_finalize_error_message_and_missing(env, monkeypatch):
    class Refused(Exception):
        message = "The model has no left hand."
        missing = ["leftHand"]

    def boom(*a):
        raise Refused()

    monkeypatch.setattr(aj, "_finalize_fn", lambda: boom)
    st = status(run_images(env, "ok"))
    assert st["status"] == "failed" and st["error"] == "The model has no left hand." and st["missing"] == ["leftHand"]


def test_finalize_unknown_error_is_generic(env, monkeypatch):
    def boom(*a):
        raise RuntimeError("secret internals")

    monkeypatch.setattr(aj, "_finalize_fn", lambda: boom)
    st = status(run_images(env, "ok"))
    assert st["error"] == aj.MSG_UNCHECKED and "secret" not in json.dumps(st)


# AC-9
def test_timeout_kills_the_group_it_started(env, monkeypatch):
    monkeypatch.setitem(aj.TIMEOUT_S, "image", 0.5)
    t = time.monotonic()
    d = run_images(env, "hang")
    assert time.monotonic() - t < 20
    assert status(d)["error"] == aj.MSG_TIMEOUT and not (d / "in").exists()


# AC-11
def test_folder_deleted_while_queued_is_skipped(env):
    os.environ["FAKE_MODE"] = "slow"
    os.environ["FAKE_SLOW"] = "0.8"
    first, f1 = make_model(env, name="1" * 32)
    second, f2 = make_model(env, name="2" * 32)
    aj.submit_images(first, f1, "o")
    aj.submit_images(second, f2, "o")
    shutil.rmtree(second)
    assert aj.wait_idle(30)
    assert not second.exists()
    assert len(env.calls()) == 1
    del os.environ["FAKE_SLOW"]


def test_folder_deleted_while_running_is_not_recreated(env):
    os.environ["FAKE_MODE"] = "slow"
    os.environ["FAKE_SLOW"] = "0.8"
    d, files = make_model(env)
    aj.submit_images(d, files, "o")
    deadline = time.monotonic() + 10
    while status(d)["status"] != "converting" and time.monotonic() < deadline:
        time.sleep(0.02)
    shutil.rmtree(d)
    assert aj.wait_idle(30)
    assert not d.exists() and env.done == []
    del os.environ["FAKE_SLOW"]


# AC-12
def test_not_set_up_fails_before_the_gpu_lock(env, monkeypatch):
    def no_lock(**kw):
        raise AssertionError("the GPU lock must not be taken")

    monkeypatch.setattr(aj.gpu_lock, "acquire", no_lock)
    monkeypatch.setenv("SIMON7_PART2_GPU_VENV", str(env.tmp / "no-venv"))
    d = run_images(env, "ok")
    assert status(d)["error"] == aj.MSG_NOT_SET_UP and not (d / "in").exists()
    shutil.rmtree(env.modules / "part-2")
    monkeypatch.setenv("SIMON7_PART2_GPU_VENV", str(env.tmp / "venv"))
    d2, f2 = make_model(env, name="3" * 32)
    aj.submit_images(d2, f2, "o")
    aj.wait_idle(10)
    assert status(d2)["error"] == aj.MSG_NOT_SET_UP


# AC-13
def test_queue_full(env):
    os.environ["FAKE_MODE"] = "slow"
    os.environ["FAKE_SLOW"] = "1.5"
    dirs = []
    for i in range(aj.MAX_QUEUE):
        d, files = make_model(env, name=f"{i:032x}")
        aj.submit_images(d, files, "o")
        dirs.append(d)
    d, files = make_model(env, name="f" * 32)
    with pytest.raises(aj.QueueFull) as exc:
        aj.submit_images(d, files, "o")
    assert exc.value.message == aj.MSG_QUEUE_FULL
    assert not (d / "avatar-job.json").exists()
    assert aj.wait_idle(60)
    del os.environ["FAKE_SLOW"]


# AC-14
def test_fail_stuck_touches_only_avatar_jobs_in_flight(env):
    root = env.tmp / "models"
    ids = {}
    for name, st, job in [("q", "queued", True), ("c", "converting", True), ("r", "ready", True),
                          ("f", "failed", True), ("conv", "converting", False)]:
        d, _ = make_model(env, name=name * 32)
        s = status(d)
        s["status"] = st
        (d / "status.json").write_text(json.dumps(s))
        if job:
            (d / "avatar-job.json").write_text("{}")
        ids[name] = d
    assert aj.fail_stuck(root) == ["c" * 32, "q" * 32]
    assert status(ids["q"])["error"] == aj.STUCK_MESSAGE and not (ids["q"] / "in").exists()
    assert status(ids["r"])["status"] == "ready" and status(ids["f"])["status"] == "failed"
    assert status(ids["conv"])["status"] == "converting" and (ids["conv"] / "in").exists()
    assert aj.fail_stuck(env.tmp / "nowhere") == []


# TICKET-306: a restart settles only the jobs of a server process that is gone
def _left(d, files, state, run_by, kind="image"):
    """A job another server left in `state`, owned by the process `run_by` names."""
    s = status(d)
    s.update({"status": state, "run_by": run_by})
    (d / "status.json").write_text(json.dumps(s))
    (d / "avatar-job.json").write_text(json.dumps({"kind": kind, "inputs": [f.name for f in files], "owner": "visitor-1"}))


def test_fail_stuck_leaves_a_converting_model_of_a_live_server_alone(env):
    with live_process() as pid:  # the old server, still draining in a restart with no gap
        d, files = make_model(env, name="l" * 32)
        _left(d, files, "converting", stamp_of(pid))
        assert aj.fail_stuck(env.tmp / "models") == []
        assert status(d)["status"] == "converting" and status(d)["error"] is None
        assert (d / "in").exists()


def test_fail_stuck_fails_a_converting_model_whose_server_is_gone(env):
    d, files = make_model(env, name="d" * 32)
    _left(d, files, "converting", {"pid": dead_pid(), "start": "1"})
    assert aj.fail_stuck(env.tmp / "models") == [d.name]
    assert status(d)["status"] == "failed" and status(d)["error"] == aj.STUCK_MESSAGE
    assert not (d / "in").exists()


def test_a_reused_pid_with_another_start_stamp_counts_as_gone(env):
    mine = model_store.owner_stamp()
    assert model_store.owner_alive({"run_by": mine})
    reused = {"pid": mine["pid"], "start": "not-this-process"}  # the pid now belongs to a later process
    assert not model_store.owner_alive({"run_by": reused})
    assert not model_store.owner_alive({}) and not model_store.owner_alive({"run_by": {"pid": True}})
    d, files = make_model(env, name="u" * 32)
    _left(d, files, "converting", reused)
    assert aj.fail_stuck(env.tmp / "models") == [d.name]


def test_a_queued_model_whose_server_is_gone_runs_again_here(env):
    os.environ["FAKE_MODE"] = "ok"
    d, files = make_model(env, name="e" * 32)
    _left(d, files, "queued", {"pid": dead_pid(), "start": None})
    assert aj.fail_stuck(env.tmp / "models") == []
    assert status(d)["run_by"] == model_store.owner_stamp()  # this server owns it now
    assert aj.wait_idle(30)
    assert status(d)["status"] == "ready" and [x["dir"] for x in env.done] == [d]


def test_a_queued_model_whose_inputs_are_gone_fails(env):
    d, files = make_model(env, name="g" * 32)
    _left(d, files, "queued", {"pid": dead_pid(), "start": None})
    shutil.rmtree(d / "in")
    assert aj.fail_stuck(env.tmp / "models") == [d.name]
    assert status(d)["error"] == aj.STUCK_MESSAGE and env.calls() == []


# AC-15
def test_module_strings_have_no_banned_dashes():
    text = Path(aj.__file__).read_text(encoding="utf-8")
    strings = [v for k, v in vars(aj).items() if k.startswith("MSG_") and isinstance(v, str)]
    strings += list(aj.MSG_NO_PERSON.values()) + [aj.STUCK_MESSAGE, aj.DEFAULT_ATTRIBUTION]
    for s in strings:
        assert "\u2014" not in s and "\u2013" not in s and " - " not in s
    assert "\u2014" not in text and "\u2013" not in text  # the cleaner writes them as escapes only


def test_worker_survives_a_crashing_job(env, monkeypatch):
    d, files = make_model(env, name="9" * 32)
    monkeypatch.setattr(aj, "_attempt", lambda *a: (_ for _ in ()).throw(RuntimeError("x")))
    aj.submit_images(d, files, "o")
    assert aj.wait_idle(10)
    assert status(d)["error"] == aj.MSG_FAILED
    monkeypatch.undo()
    assert aj._thread is None


def test_submit_from_many_threads_runs_every_job(env):
    os.environ["FAKE_MODE"] = "ok"
    made = [make_model(env, name=f"{i:032x}") for i in range(4)]
    ts = [threading.Thread(target=aj.submit_images, args=(d, f, "o")) for d, f in made]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert aj.wait_idle(60)
    assert all(status(d)["status"] == "ready" for d, _ in made)


# AC-16 real data
@pytest.mark.skipif(not (RIGGED.is_file() and TAKE.is_file() and shutil.which("ffmpeg")),
                    reason="local real-data files are not present")
def test_real_take_frame_and_real_rigged_glb(env, monkeypatch):
    monkeypatch.setenv("FAKE_GLB", str(RIGGED))
    os.environ["FAKE_MODE"] = "ok"
    d, _ = make_model(env, name="e" * 32)
    frame = d / "in" / "frame.jpg"
    subprocess.run(["ffmpeg", "-v", "error", "-ss", "2", "-i", str(TAKE), "-frames:v", "1", str(frame)], check=True)
    assert frame.stat().st_size > 1000
    aj.submit_images(d, [frame], "visitor-1")
    assert aj.wait_idle(60)
    assert status(d)["status"] == "ready"
    assert hashlib.sha256(env.done[0]["bytes"]).hexdigest() == hashlib.sha256(RIGGED.read_bytes()).hexdigest()
    assert env.done[0]["bytes"][:4] == b"glTF"
    assert not frame.exists()


def test_a_refusal_by_the_importer_stays_failed(env, monkeypatch):
    def refuse(model_dir, glb_path, extra):
        aj._set_status(Path(model_dir), "failed", "Simon could not find these bones: leftFoot.", ["leftFoot"])
        return None

    monkeypatch.setattr(aj, "_finalize_fn", lambda: refuse)
    d = run_images(env, "ok")
    st = status(d)
    assert st["status"] == "failed" and "leftFoot" in st["error"] and not (d / "in").exists()


def test_available_needs_the_part2_command_and_the_venv(env, monkeypatch):
    assert aj.available("image") is False  # the fake Part 2 has no avatar.py yet
    (env.modules / "part-2" / "part2").mkdir(parents=True, exist_ok=True)
    (env.modules / "part-2" / "part2" / "avatar.py").write_text("")
    assert aj.available("image") is True and aj.available("autorig") is False and aj.available("other") is False


# ms-intake-fix: a queued model says why it waits, and turns to converting only when Part 2 starts
def test_waits_for_the_card_with_a_plain_reason_then_converts(env, monkeypatch):
    os.environ["FAKE_MODE"] = "ok"
    free = {"mib": 2000}
    monkeypatch.setattr(aj, "MIN_FREE_MIB", 11264)
    monkeypatch.setattr(aj, "CARD_POLL_S", 0.05)
    monkeypatch.setattr(aj.gpu_lock, "free_gpu_memory_mib", lambda: free["mib"])
    monkeypatch.setattr(aj.gpu_lock, "lock_holder", lambda _p: "pid 1 owner=staging cwd=/x")
    released = []
    monkeypatch.setattr(aj.p2_worker, "release_idle_workers", lambda: released.append(1) or [])
    d, files = make_model(env)
    aj.submit_images(d, files, "visitor-1")
    deadline = time.monotonic() + 5
    while not (status(d).get("waiting") or "").startswith("Waiting for the graphics") and time.monotonic() < deadline:
        time.sleep(0.02)
    got = status(d)
    assert got["status"] == "queued"
    assert got["waiting"] == "Waiting for the graphics card: a take is being analysed. Your model is next."
    assert got["position"] == 1 and released == [1]
    free["mib"] = 20000
    assert aj.wait_idle(30)
    final = status(d)
    assert final["status"] == "ready" and "waiting" not in final and "position" not in final


# staging 2026-11-02: an image3d job waiting while staging freed its own idle warm workers said "another job is using it"
@pytest.mark.parametrize("holder, own, released, want", [
    (None, False, ["p2_worker"], "Freeing the graphics card for your model. Your model is next."),
    ("pid 4242 owner=part7-other cwd=/x", True, ["p2_worker"], "Freeing the graphics card for your model. Your model is next."),
    ("pid 4242 owner=part2 cwd=/y", False, ["p2_worker"], "Waiting for the graphics card: another job is using it. Your model is next."),
    ("pid 4242 owner=part2 cwd=/y", False, [], "Waiting for the graphics card: another job is using it. Your model is next."),
    (None, False, [], "Waiting for the graphics card: other programs are using its memory. Your model is next."),
])
def test_waiting_says_freeing_for_own_workers_and_another_job_only_for_its_lock(env, monkeypatch, holder, own, released, want):
    os.environ["FAKE_MODE"] = "ok"
    free = {"mib": 2000}
    monkeypatch.setattr(aj, "MIN_FREE_MIB", 11264)
    monkeypatch.setattr(aj, "CARD_POLL_S", 0.05)
    monkeypatch.setattr(aj.gpu_lock, "free_gpu_memory_mib", lambda: free["mib"])
    monkeypatch.setattr(aj.gpu_lock, "lock_holder", lambda _p: holder)
    monkeypatch.setattr(aj.p2_worker, "own_warm_worker", lambda pid: own and pid == 4242)
    monkeypatch.setattr(aj.p2_worker, "release_idle_workers", lambda: list(released))
    monkeypatch.setattr(aj.p2_worker, "state", lambda: "off")
    monkeypatch.setattr(aj.p2_worker, "track_state", lambda: "off")
    d, files = make_model(env)
    aj.submit_images(d, files, "visitor-1")
    deadline = time.monotonic() + 5
    while not (status(d).get("waiting") or "").startswith(("Freeing", "Waiting for the graphics")) and time.monotonic() < deadline:
        time.sleep(0.02)
    assert status(d)["waiting"] == want
    free["mib"] = 20000
    assert aj.wait_idle(30)
    assert status(d)["status"] == "ready"


def test_own_warm_worker_is_a_child_worker_of_this_server_only(monkeypatch):
    from part7 import p2_worker

    class Pool:
        def _ours(self, pid):
            return pid in (500, 600)

    me = os.getpid()
    parents = {500: me, 501: 500, 600: 999, 700: me}  # 500 our worker, 501 its child, 600 a worker of another server
    monkeypatch.setattr(p2_worker.gpu_lock, "_read_ppid_and_age", lambda pid: (parents.get(pid), 1.0))
    monkeypatch.setattr(p2_worker, "_POOL", Pool())
    monkeypatch.setattr(p2_worker, "_TRACK_POOL", None)
    assert p2_worker.own_warm_worker(500) and p2_worker.own_warm_worker(501)
    assert not p2_worker.own_warm_worker(600), "negative: another server's worker is another job"
    assert not p2_worker.own_warm_worker(700), "negative: a child of this server that is not a warm worker (a take)"
    assert not p2_worker.own_warm_worker(None)


def test_a_second_model_learns_its_place_in_line(env, monkeypatch):
    os.environ["FAKE_MODE"] = "slow"
    os.environ["FAKE_SLOW"] = "1"
    first, f1 = make_model(env, name="a" * 32)
    second, f2 = make_model(env, name="b" * 32)
    aj.submit_images(first, f1, "visitor-1")
    time.sleep(0.2)
    aj.submit_images(second, f2, "visitor-1")
    got = status(second)
    assert got["status"] == "queued" and got["position"] == 2
    assert "number 2 in line" in got["waiting"]
    assert aj.wait_idle(30)


def test_an_idle_warm_worker_is_released_and_a_leased_one_is_not(monkeypatch):
    from part7 import p2_worker

    class Pool:
        label = "p2_tracker"

        def __init__(self, st):
            self.st, self.released = st, 0

        def state(self):
            return self.st

        def release_all(self, wait_s):
            self.released += 1
            return True

    idle, busy = Pool("idle"), Pool("busy")
    monkeypatch.setattr(p2_worker, "_POOL", busy)
    monkeypatch.setattr(p2_worker, "_TRACK_POOL", idle)
    assert p2_worker.release_idle_workers() == ["p2_tracker"]
    assert (idle.released, busy.released) == (1, 0)


def test_the_floor_is_the_measured_peak_with_a_small_margin():
    peak_mib = 10.32 * 1024
    assert peak_mib < aj.MIN_FREE_MIB <= peak_mib + 1024


def test_status_carries_the_step_from_waiting_to_checking(env, monkeypatch):
    seen = {}
    real_run = aj._run_part2

    def spy(argv, cwd, envv, model_dir, timeout_s):
        seen["while_running"] = {k: status(model_dir).get(k) for k in ("status", "step", "step_index", "step_count")}
        return real_run(argv, cwd, envv, model_dir, timeout_s)

    monkeypatch.setattr(aj, "_run_part2", spy)
    real_mark = aj._mark_step
    monkeypatch.setattr(aj, "_mark_step", lambda d, s: (real_mark(d, s), seen.setdefault("after_part2", status(d).get("step"))))
    os.environ["FAKE_MODE"] = "ok"
    d, files = make_model(env)
    aj.submit_images(d, files, "visitor-1")
    queued = status(d)
    assert (queued["step"], queued["step_index"], queued["step_count"]) in {("waiting", 2, 5), ("making", 3, 5)}
    assert aj.wait_idle(30)
    assert seen["while_running"] == {"status": "converting", "step": "making", "step_index": 3, "step_count": 5}
    assert seen["after_part2"] == "checking"
    final = status(d)
    assert final["status"] == "ready" and not {"step", "step_index", "step_count"} & set(final)


def test_a_mesh_job_shows_the_skeleton_step(env, monkeypatch):
    seen = {}
    real_run = aj._run_part2

    def spy(argv, cwd, envv, model_dir, timeout_s):
        seen["step"] = status(model_dir).get("step")
        return real_run(argv, cwd, envv, model_dir, timeout_s)

    monkeypatch.setattr(aj, "_run_part2", spy)
    os.environ["FAKE_MODE"] = "ok"
    d, files = make_model(env, suffix=".glb")
    aj.submit_autorig(d, files[0], "visitor-1")
    assert aj.wait_idle(30)
    assert seen["step"] == "skeleton"


# intake fix 2: the "checking" step is reported before ready and stays long enough for a poll to see it
def test_checking_step_is_reported_and_held_before_ready(env, monkeypatch):
    monkeypatch.setattr(aj, "CHECK_HOLD_S", 0.4)
    seen = []
    inner = aj._finalize_fn()

    def finalize(model_dir, glb_path, extra):
        seen.append((dict(status(Path(model_dir))), time.monotonic()))
        return inner(model_dir, glb_path, extra)

    monkeypatch.setattr(aj, "_finalize_fn", lambda: finalize)
    marks = []
    real = aj._mark_step
    monkeypatch.setattr(aj, "_mark_step", lambda d, s: (marks.append((s, time.monotonic())), real(d, s))[1])
    d = run_images(env, "ok")
    (rec, t_final), (step, t_mark) = seen[0], marks[0]
    assert step == "checking" and rec["step"] == "checking" and rec["step_index"] == 4 and rec["step_count"] == 5
    assert t_final - t_mark >= 0.4, "negative: the step is not gone before a poll can see it"
    assert status(d)["status"] == "ready" and "step" not in status(d)
