"""part2/jobs.py: one worker, the free memory check, timeout, cancel, progress, restart and cleanup
(docs/specs/run-app.md AC-A08, AC-A09, AC-A12; tracker-registry.md Budget).

The run is a fake: FAKE_RUN, a small Python script started exactly as `part2 run` would be (own process group,
stdout parsed for progress). No GPU, no model, no key: free memory and the lock are fakes or a temp lock file.
"""
import json
import os
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

from part2 import gpu_guard, jobs
from part2.joints import CANONICAL

FAST = dict(gpu_poll_s=0.05, poll_s=0.05, kill_grace_s=2.0, sweep_every_s=3600)

FAKE_RUN = textwrap.dedent(r'''
    import json, os, subprocess, sys, time
    behaviour, out = sys.argv[1], sys.argv[2]
    say = lambda line: print(line, flush=True)
    JOINTS = %(joints)s

    def write(n=3, ids=(0,), prov=None, tracks=False):
        os.makedirs(os.path.join(out, "frames"), exist_ok=True)
        recs = []
        for f in range(n):
            name = "%%06d.jpg" %% f
            with open(os.path.join(out, "frames", name), "wb") as fh:
                fh.write(b"\xff\xd8\xff\xe0frame" + str(f).encode())
            recs.append({"frame": f, "t_ms": f * 100.0, "file": name})
        json.dump({"source": "x", "frames": recs}, open(os.path.join(out, "frames", "frames.json"), "w"))
        joints = {j: {"x": 0.01 * k, "y": 0.1 * k, "z": 0.0, "conf": 1.0} for k, j in enumerate(JOINTS)}
        pose = {"frames": [{"frame": f, "t_ms": f * 100.0, "people": [{"id": i, "joints": joints} for i in ids]}
                           for f in range(n)]}
        if prov is not None:
            pose["provenance"] = prov
        eye = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
        json.dump(pose, open(os.path.join(out, "pose3d.json"), "w"))
        json.dump({"K": [[1000, 0, 640], [0, 1000, 360], [0, 0, 1]], "image_size": [1280, 720], "frames": [
            {"frame": f, "people": [{"id": i, "R": eye, "t": [0, 0, 3]} for i in ids]} for f in range(n)]},
            open(os.path.join(out, "camera.json"), "w"))
        if tracks:
            json.dump({"frames": [{"frame": f, "people": [{"id": i, "bbox": [0, 0, 1, 1], "confidence": 1.0}
                                                         for i in ids]} for f in range(n)]},
                      open(os.path.join(out, "tracks.json"), "w"))

    if behaviour == "ok":
        say("progress frames 3 3"); say("progress pose 2 3"); say("progress write 1 1")
        write(prov={"backend": "gpu", "tracker": None, "lifter": None})
    elif behaviour == "cpu":
        write(prov={"backend": "cpu", "tracker": None, "lifter": "fixed-bones"})
    elif behaviour == "class-fallback":
        write(ids=(0, 1, 2), tracks=True, prov={"backend": "gpu", "tracker": "local-open", "lifter": None,
              "fallback_from": "api-sam31", "fallback_reason": "budget"})
    elif behaviour == "legacy":
        say("30 frames -> /somewhere/frames"); time.sleep(0.3)
        say("camera-space 3D (gpu) -> /somewhere/body3d.json"); time.sleep(0.3)
        write()
        say("/somewhere/pose3d.json + /somewhere/camera.json")
    elif behaviour == "no-provenance":
        write()
    elif behaviour == "no-output":
        say("progress frames 1 1")
    elif behaviour == "noperson":
        sys.stderr.write("part2: no person found in 3 frames (/home/someone/job/out/frames)\n"); sys.exit(1)
    elif behaviour == "crash":
        sys.stderr.write("Traceback (most recent call last):\n  File \"/home/x/part2/cli.py\"\nKeyError: 'x'\n"); sys.exit(1)
    elif behaviour == "oom":
        sys.stderr.write("torch.OutOfMemoryError: CUDA out of memory.\n"); sys.exit(1)
    elif behaviour in ("sleep", "sleep-short"):
        log = os.environ.get("FAKE_LOG")
        if log:
            open(log, "a").write("start %%f\n" %% time.time())
        if behaviour == "sleep":
            kid = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
            open(os.path.join(os.path.dirname(out), "grandchild.pid"), "w").write(str(kid.pid))
        say("progress frames 1 10")
        time.sleep(120 if behaviour == "sleep" else 0.3)
        if log:
            open(log, "a").write("end %%f\n" %% time.time())
        write()
    elif behaviour == "env":
        os.makedirs(out, exist_ok=True)
        keys = ("MODEL_API_KEY", "HF_TOKEN", "PART2_TRACKER", "META_SPEND_LEDGER", "META_BUDGET_USD", "PART2_JOB_LEDGER",
                "PART2_JOB_BUDGET_USD", "PART2_PROGRESS", "PYTHONDONTWRITEBYTECODE")
        json.dump({k: os.environ.get(k) for k in keys}, open(os.path.join(out, "env.json"), "w"))
        write()
    elif behaviour == "lock":
        from part2 import gpu_guard, trackers
        try:
            with gpu_guard.gpu_lock(wait_s=0.3, poll_s=0.05):
                held_by_parent = False
        except trackers.GpuBusy:
            held_by_parent = True
        write()
        json.dump({"held_by_parent": held_by_parent}, open(os.path.join(out, "lock.json"), "w"))
''') % {"joints": json.dumps(CANONICAL)}


def fake_command(script: Path, behaviour=None):
    """A command builder for JobQueue: the behaviour is job.input unless one is given (a str or a callable)."""
    def build(job):
        b = behaviour(job) if callable(behaviour) else behaviour or job.input
        return [sys.executable, str(script), b, str(job.dir / "out")]
    return build


@pytest.fixture
def script(tmp_path):
    path = tmp_path / "fake_run.py"
    path.write_text(FAKE_RUN)
    return path


@pytest.fixture(autouse=True)
def lock_in_tmp(tmp_path, monkeypatch):
    monkeypatch.setenv("PART2_GPU_LOCK", str(tmp_path / "gpu.lock"))
    monkeypatch.setenv("PYTHONPATH", str(Path(jobs.ROOT)))


@pytest.fixture
def make_queue(tmp_path, script):
    made = []

    def make(free=20.0, start=True, behaviour=None, **settings):
        free_fn = free if callable(free) else (lambda: free)
        q = jobs.JobQueue(tmp_path / "jobs", jobs.Settings(**{**FAST, **settings}),
                          command=fake_command(script, behaviour), free_gib=free_fn)
        made.append(q)
        return q.start() if start else q
    yield make
    for q in made:
        q.stop()


def submit(q, behaviour="ok", mode="single", backend="gpu", tracker=None, kind="sample"):
    return q.submit(q.new_job(mode=mode, kind=kind, input=behaviour, backend=backend, tracker=tracker))


def wait_for(q, job, states=jobs.FINISHED, timeout=20.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if job.state in states:
            return q.public(job.id)
        time.sleep(0.02)
    raise AssertionError(f"job stayed {job.state}")


def alive(pid: int) -> bool:
    try:
        return Path(f"/proc/{pid}/stat").read_text().split()[2] != "Z"
    except OSError:
        return False


def gone(pid: int, timeout=5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not alive(pid):
            return True
        time.sleep(0.05)
    return False


# ---- a run end to end (AC-A04 shape, AC-A09) -----------------------------------------------------------------

def test_a_job_runs_to_done_and_names_what_ran(make_queue):
    q = make_queue()
    job = submit(q)
    assert len(job.id) == 12 and jobs.JOB_ID.fullmatch(job.id)
    pub = wait_for(q, job)
    assert pub["state"] == "done" and pub["error"] is None and pub["position"] is None
    assert pub["backend"] == "gpu" and pub["tracker"] is None and pub["lifter"] is None
    assert pub["files"] == ["pose3d.json", "camera.json"] and pub["frames"] == 3
    assert pub["progress"] == {"stage": "write", "done": 1, "total": 1}
    assert pub["fallback"] is None and pub["notice"] is None and pub["approximate"] is False
    assert pub["started"] >= pub["created"] and pub["ended"] >= pub["started"]
    assert (job.dir / "out" / "pose3d.json").is_file() and (job.dir / "run.out").read_text().startswith("progress")
    assert str(job.dir) not in json.dumps(pub) and "/" not in json.dumps({k: pub[k] for k in ("backend", "error")})


def test_progress_is_reported_while_the_run_works(make_queue):
    q = make_queue()
    job = submit(q, "sleep-short")
    seen = wait_for(q, job, {"running"})
    deadline = time.monotonic() + 5
    while q.public(job.id)["progress"]["stage"] is None and time.monotonic() < deadline:
        time.sleep(0.02)
    assert q.public(job.id)["progress"] == {"stage": "frames", "done": 1, "total": 10}
    assert seen["position"] == 0
    wait_for(q, job)


def test_the_cpu_backend_is_labelled_approximate_and_names_its_lifter(make_queue):
    q = make_queue(free=lambda: pytest.fail("a CPU one-person job must not check GPU memory"))
    job = submit(q, "cpu", backend="cpu")
    pub = wait_for(q, job)
    assert pub["state"] == "done" and pub["backend"] == "cpu" and pub["lifter"] == "fixed-bones"
    assert pub["approximate"] is (not jobs.CPU_3D_BAR_PASSED)


def test_a_fallback_is_named_with_the_plain_notice(make_queue):
    q = make_queue()
    job = submit(q, "class-fallback", mode="class")
    pub = wait_for(q, job)
    assert pub["tracker"] == "local-open" and pub["fallback"] == {"from": "api-sam31", "reason": "budget"}
    assert pub["notice"] == "SAM 3.1 spend cap reached; tracked with local-open"
    assert pub["files"] == ["pose3d.json", "tracks.json", "camera.json"]


def test_a_class_job_shows_automatic_until_it_has_run(make_queue):
    q = make_queue(start=False)
    job = submit(q, "ok", mode="class")
    assert q.public(job.id)["tracker"] == "automatic"
    named = submit(q, "ok", mode="class", tracker="bytetrack")
    assert q.public(named.id)["tracker"] == "bytetrack"
    assert q.public(submit(q).id)["tracker"] is None


def test_a_run_without_provenance_falls_back_to_the_requested_backend(make_queue):
    q = make_queue()
    pub = wait_for(q, submit(q, "no-provenance", backend="gpu"))
    assert pub["state"] == "done" and pub["backend"] == "gpu" and pub["tracker"] is None


@pytest.mark.parametrize("behaviour,message", [
    ("noperson", "No person was found in this file."),
    ("crash", "The run stopped with an error. Try another file, or try again later."),
    ("oom", "The GPU ran out of memory on this file. Try a shorter clip or the CPU backend."),
    ("no-output", "The run stopped with an error. Try another file, or try again later."),
])
def test_failed_runs_carry_a_plain_message(make_queue, behaviour, message):
    q = make_queue()
    pub = wait_for(q, submit(q, behaviour))
    assert pub["state"] == "failed" and pub["error"] == message
    text = json.dumps(pub)
    assert "Traceback" not in text and "/home" not in text and "Error" not in text


def test_a_run_that_cannot_start_fails_plainly(make_queue, tmp_path):
    q = make_queue(start=False)
    q.command = lambda job: [str(tmp_path / "no-such-python"), "-m", "part2"]
    q.start()
    pub = wait_for(q, submit(q))
    assert pub["state"] == "failed" and pub["error"] == "The job could not be started on this server."


def test_the_worker_survives_a_broken_command_builder(make_queue, capsys):
    q = make_queue(start=False)
    q.command = lambda job: (_ for _ in ()).throw(KeyError("/home/secret/path"))
    q.start()
    pub = wait_for(q, submit(q))
    assert pub["state"] == "failed" and pub["error"] == jobs.MESSAGES["failed"]
    assert "/home/secret" not in capsys.readouterr().err
    q.command = lambda job: [sys.executable, "-c", "pass"]
    assert wait_for(q, submit(q))["state"] == "failed"              # ran (no pose3d.json), so the worker is alive


# ---- one worker, memory check, timeout, cancel (AC-A08) ------------------------------------------------------

def test_two_jobs_never_run_at_once(make_queue, tmp_path, monkeypatch):
    log = tmp_path / "times.log"
    monkeypatch.setenv("FAKE_LOG", str(log))
    q = make_queue()
    batch = [submit(q, "sleep-short") for _ in range(3)]
    for j in batch:
        assert wait_for(q, j)["state"] == "done"
    marks = [line.split() for line in log.read_text().splitlines()]
    assert [m[0] for m in marks] == ["start", "end"] * 3
    times = [float(m[1]) for m in marks]
    assert times == sorted(times)


def test_queue_positions_count_the_jobs_ahead(make_queue):
    q = make_queue(start=False)
    a, b, c = submit(q), submit(q), submit(q)
    assert [q.public(j.id)["position"] for j in (a, b, c)] == [0, 1, 2]
    listing = q.listing()
    assert [r["position"] for r in listing] == [0, 1, 2] and all(set(r) == {"ref", "state", "position", "mode", "created"}
                                                                 for r in listing)
    assert all(len(r["ref"]) == 4 and r["ref"] == j.id[:4] for r, j in zip(listing, (a, b, c)))
    assert all(j.id not in json.dumps(listing) for j in (a, b, c))      # ids are capabilities: never listed


def test_a_job_waits_for_gpu_memory_and_fails_after_the_wait_limit(make_queue):
    q = make_queue(free=4.0, gpu_wait_s=0.5)
    job = submit(q)
    assert wait_for(q, job, {"waiting-gpu"})["position"] == 0
    t0 = time.monotonic()
    pub = wait_for(q, job)
    assert pub["state"] == "failed" and pub["error"] == "The GPU is busy with other work; try again later."
    assert time.monotonic() - t0 < 5 and not (job.dir / "run.out").exists()       # the run never started


def test_a_waiting_job_starts_once_memory_frees(make_queue):
    readings = iter([4.0, 8.0, 11.9, 12.0])
    q = make_queue(free=lambda: next(readings, 20.0), gpu_wait_s=10)
    pub = wait_for(q, submit(q))
    assert pub["state"] == "done"


def test_a_held_gpu_lock_also_keeps_a_job_waiting(make_queue):
    held = gpu_guard.try_lock()
    try:
        q = make_queue(gpu_wait_s=0.4)
        pub = wait_for(q, submit(q))
        assert pub["error"] == jobs.MESSAGES["gpu_busy"]
    finally:
        gpu_guard.release(held)


def test_without_nvidia_smi_a_gpu_job_waits_and_a_cpu_class_job_runs(make_queue):
    q = make_queue(free=lambda: None, gpu_wait_s=0.3)
    assert wait_for(q, submit(q, backend="gpu"))["state"] == "failed"
    assert wait_for(q, submit(q, mode="class", backend="cpu"))["state"] == "done"


def test_which_jobs_need_the_gpu(make_queue):
    q = make_queue(start=False)
    job = lambda **kw: jobs.Job(id="0" * 12, dir=Path("/x"), **{"mode": "single", "kind": "video", **kw})
    assert q.needs_gpu(job(backend="gpu"))
    assert not q.needs_gpu(job(backend="cpu"))
    assert q.needs_gpu(job(backend="cpu", mode="class", tracker=None))          # Automatic runs a SAM tracker
    assert q.needs_gpu(job(backend="cpu", mode="class", tracker="local-open"))
    assert not q.needs_gpu(job(backend="cpu", mode="class", tracker="bytetrack"))


def held_by_parent(job) -> bool:
    return json.loads((job.dir / "out" / "lock.json").read_text())["held_by_parent"]


def test_the_worker_holds_the_gpu_lock_through_a_run_that_never_takes_it(make_queue):
    q = make_queue()
    single = submit(q, "lock", backend="gpu")
    bytetrack = submit(q, "lock", mode="class", backend="gpu", tracker="bytetrack")
    assert wait_for(q, single)["state"] == wait_for(q, bytetrack)["state"] == "done"
    assert held_by_parent(single) and held_by_parent(bytetrack)
    probe = gpu_guard.try_lock()
    assert probe is not None                          # and released it afterwards
    gpu_guard.release(probe)


def test_a_class_run_with_a_sam_tracker_takes_the_lock_itself(make_queue):
    q = make_queue()
    auto = submit(q, "lock", mode="class", backend="gpu")
    named = submit(q, "lock", mode="class", backend="cpu", tracker="local-open")
    assert wait_for(q, auto)["state"] == wait_for(q, named)["state"] == "done"
    assert not held_by_parent(auto) and not held_by_parent(named)     # trackers.gpu_lock never waits on its parent
    assert q.run_takes_lock(auto) and not q.run_takes_lock(jobs.Job(id="0" * 12, dir=Path("/x"), mode="single",
                                                                     kind="video"))


def test_a_job_past_the_timeout_is_killed_with_its_process_group(make_queue):
    q = make_queue(timeout_s=1.0)
    job = submit(q, "sleep")
    pub = wait_for(q, job, timeout=30)
    assert pub["state"] == "failed" and pub["error"] == "The job took longer than 20 minutes and was stopped."
    assert gone(int((job.dir / "grandchild.pid").read_text()))


def test_cancel_while_running_kills_the_process_group(make_queue):
    q = make_queue()
    job = submit(q, "sleep")
    wait_for(q, job, {"running"})
    pid_file = job.dir / "grandchild.pid"
    deadline = time.monotonic() + 10
    while not pid_file.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert q.cancel(job.id) == "cancelled"
    assert q.public(job.id)["state"] == "cancelled"
    assert gone(int(pid_file.read_text()))
    time.sleep(0.3)
    assert q.public(job.id)["state"] == "cancelled" and not q.busy()
    with pytest.raises(jobs.AlreadyFinished):
        q.cancel(job.id)
    assert wait_for(q, submit(q))["state"] == "done"          # the worker carries on


def test_cancel_a_queued_or_waiting_job(make_queue):
    q = make_queue(free=4.0, gpu_wait_s=30)
    waiting, queued = submit(q), submit(q)
    wait_for(q, waiting, {"waiting-gpu"})
    assert q.cancel(queued.id) == "cancelled"
    assert q.cancel(waiting.id) == "cancelled"
    time.sleep(0.3)
    assert queued.state == waiting.state == "cancelled" and not (queued.dir / "run.out").exists()
    with pytest.raises(KeyError):
        q.cancel("0123456789ab")
    with pytest.raises(KeyError):
        q.cancel("../../etc")


def test_the_sixth_unfinished_job_is_refused(make_queue):
    q = make_queue(start=False)
    for _ in range(5):
        submit(q)
    assert q.pending() == 5
    with pytest.raises(jobs.QueueFull):
        submit(q)
    q.cancel(next(iter(q._jobs)))
    submit(q)                                                 # a finished job frees its place


def test_stop_kills_the_running_job(make_queue):
    q = make_queue()
    job = submit(q, "sleep")
    wait_for(q, job, {"running"})
    time.sleep(0.3)
    q.stop()
    assert job.state == "failed" and job.error == "The server restarted."


# ---- the run's command and environment -------------------------------------------------------------------------

def test_the_run_environment_holds_no_key_and_the_staging_caps(make_queue, monkeypatch, tmp_path):
    monkeypatch.setenv("MODEL_API_KEY", "FAKE-KEY-DO-NOT-PRINT-123")
    monkeypatch.setenv("HF_TOKEN", "FAKE-TOKEN-DO-NOT-PRINT")
    monkeypatch.setenv("PART2_TRACKER", "api-sam31")
    q = make_queue(free=lambda: pytest.fail("no GPU check for a CPU one-person job"),
                   staging_ledger=str(tmp_path / "staging.jsonl"))
    job = submit(q, "env", backend="cpu")
    assert wait_for(q, job)["state"] == "done"
    env = json.loads((job.dir / "out" / "env.json").read_text())
    assert env["MODEL_API_KEY"] is None and env["HF_TOKEN"] is None and env["PART2_TRACKER"] is None
    assert env["META_SPEND_LEDGER"] == str(tmp_path / "staging.jsonl") and env["META_BUDGET_USD"] == "10"
    assert env["PART2_JOB_LEDGER"] == str(job.dir / "meta_spend_job.jsonl") and env["PART2_JOB_BUDGET_USD"] == "0.5"
    assert env["PART2_PROGRESS"] == "1" and env["PYTHONDONTWRITEBYTECODE"] == "1"
    assert "FAKE-KEY" not in (job.dir / "job.json").read_text()


def test_the_default_staging_ledger_and_caps():
    s = jobs.Settings()
    assert s.staging_ledger == "~/.simon/meta_spend_staging.jsonl" and s.total_budget_usd == 10 and s.job_budget_usd == 0.5
    assert (s.max_pending, s.min_free_gib, s.gpu_wait_s, s.gpu_poll_s, s.timeout_s, s.retention_s) == (
        5, 12.0, 600.0, 15.0, 1200.0, 86400.0)


def test_default_command_for_each_kind_of_job(tmp_path):
    job = lambda **kw: jobs.Job(id="a" * 12, dir=tmp_path, **kw)
    video = jobs.default_command(job(mode="single", kind="video", input="/j/input.mp4", backend="gpu"), "py")
    assert video == ["py", "-m", "part2", "run", "--mode", "single", "--input", "/j/input.mp4",
                     "--out", str(tmp_path / "out"), "--backend", "gpu", "--fps", "10"]
    auto = jobs.default_command(job(mode="class", kind="sample", input="/f", backend="cpu"), "py")
    assert auto[auto.index("--mode") + 1] == "multi" and "--tracker" not in auto and "--fps" not in auto
    named = jobs.default_command(job(mode="class", kind="photo", input="/p", backend="gpu", tracker="bytetrack"), "py")
    assert named[-4:] == ["--fps", "10", "--tracker", "bytetrack"]


def test_job_python_prefers_the_override_then_the_gpu_venv(tmp_path, monkeypatch):
    monkeypatch.setenv("PART2_JOB_PYTHON", "/opt/py")
    assert jobs.job_python() == "/opt/py"
    monkeypatch.delenv("PART2_JOB_PYTHON")
    venv = tmp_path / "python"
    monkeypatch.setattr(jobs, "GPU_PYTHON", str(venv))
    assert jobs.job_python() == sys.executable
    venv.write_text("")
    assert jobs.job_python() == str(venv)


def test_default_jobs_dir_is_per_port_unless_given(monkeypatch, tmp_path):
    monkeypatch.delenv("PART2_JOBS_DIR", raising=False)
    assert jobs.default_jobs_dir(7122) == Path("~/.local/state/simon-part-2/jobs/7122").expanduser()
    monkeypatch.setenv("PART2_JOBS_DIR", str(tmp_path))
    assert jobs.default_jobs_dir(7122) == tmp_path


# ---- progress parsing (AC-A09) -----------------------------------------------------------------------------------

def test_progress_lines_are_parsed():
    p = jobs.Progress("single")
    assert p.value == {"stage": "frames", "done": 0, "total": 0}
    assert p.feed("progress pose 4 30\n") and p.value == {"stage": "pose", "done": 4, "total": 30}
    assert p.feed("progress write 9 1") and p.value == {"stage": "write", "done": 1, "total": 1}
    assert not p.feed("30 frames -> /x")                     # once explicit lines arrive, summaries are ignored
    for line in ("progress jump 1 2", "progress pose x 2", "progresspose 1 2", "", "Traceback"):
        assert not jobs.Progress("single").feed(line)


def test_summary_lines_move_the_stage_on_for_a_run_without_progress_lines():
    single, multi = jobs.Progress("single"), jobs.Progress("class")
    assert single.feed("30 frames -> /j/out/frames") and single.value == {"stage": "pose", "done": 0, "total": 30}
    assert single.feed("camera-space 3D (gpu) -> /j/out/body3d.json") and single.value["stage"] == "write"
    assert single.feed("/j/out/pose3d.json + /j/out/camera.json") and single.value == {"stage": "write", "done": 1, "total": 1}
    assert multi.feed("12 frames -> /j/out/frames") and multi.value == {"stage": "track", "done": 0, "total": 12}
    assert multi.feed("7 tracked people -> /j/out/tracks.json (tracker local-sam31)")
    assert multi.value == {"stage": "pose", "done": 0, "total": 12}
    assert multi.feed("pose3d for people [0, 1] -> /j/out/pose3d.json (+ pose3d_person_<id>.json each)")
    assert multi.value["done"] == 1


def test_legacy_lines_reach_the_job_record(make_queue):
    q = make_queue()
    job = submit(q, "legacy")
    seen = set()
    while job.state not in jobs.FINISHED:
        seen.add(json.dumps(q.public(job.id)["progress"], sort_keys=True))
        time.sleep(0.02)
    assert json.dumps({"stage": "pose", "done": 0, "total": 30}, sort_keys=True) in seen


def test_classify_maps_errors_to_plain_messages():
    assert jobs.classify("part2: no person found to track") == jobs.MESSAGES["no_person"]
    assert jobs.classify("part2: another GPU job is running") == jobs.MESSAGES["gpu_busy"]
    assert jobs.classify("RuntimeError: CUDA out of memory") == jobs.MESSAGES["out_of_memory"]
    assert jobs.classify("anything else at /home/x") == jobs.MESSAGES["failed"]
    assert all("/" not in m and "Error" not in m for m in jobs.MESSAGES.values())


def test_tail_reads_the_end_of_a_file(tmp_path):
    f = tmp_path / "err"
    f.write_bytes(b"a" * 20000 + b"part2: no person found")
    assert jobs.tail(f).endswith("no person found") and len(jobs.tail(f)) == 8192
    assert jobs.tail(tmp_path / "absent") == ""


# ---- restart and cleanup (AC-A12, edge "Server restart with jobs running") ---------------------------------------

def write_record(d: Path, **rec):
    d.mkdir(parents=True)
    base = {"id": d.name, "mode": "single", "kind": "video", "state": "done", "created": time.time()}
    (d / "job.json").write_text(json.dumps({**base, **rec}))


def test_a_restart_fails_unfinished_jobs_and_keeps_finished_ones(tmp_path, script):
    root = tmp_path / "jobs"
    write_record(root / "aaaaaaaaaaaa", state="running")
    write_record(root / "bbbbbbbbbbbb", state="queued")
    write_record(root / "cccccccccccc", state="done", ended=time.time(), files=["pose3d.json"])
    (root / "dddddddddddd").mkdir()                                   # an upload cut off by a crash
    q = jobs.JobQueue(root, jobs.Settings(**FAST), command=fake_command(script)).start()
    try:
        for jid in ("aaaaaaaaaaaa", "bbbbbbbbbbbb"):
            pub = q.public(jid)
            assert pub["state"] == "failed" and pub["error"] == "The server restarted." and pub["ended"]
            assert json.loads((root / jid / "job.json").read_text())["state"] == "failed"
        assert q.public("cccccccccccc")["state"] == "done"
        assert not (root / "dddddddddddd").exists()
        assert q.pending() == 0 and not q.busy()
    finally:
        q.stop()


def test_old_job_dirs_are_removed_at_start_and_others_are_left_alone(tmp_path, script):
    root = tmp_path / "jobs"
    old = time.time() - 25 * 3600
    write_record(root / "aaaaaaaaaaaa", state="done", ended=old, created=old)
    write_record(root / "bbbbbbbbbbbb", state="running", created=old)        # marked failed now, ends now: kept
    write_record(root / "cccccccccccc", state="done", ended=time.time() - 3600)
    (root / "not-a-job").mkdir()
    (root / "not-a-job" / "keep.txt").write_text("x")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("x")
    (root / "eeeeeeeeeeee").symlink_to(outside)
    q = jobs.JobQueue(root, jobs.Settings(**FAST), command=fake_command(script)).start()
    try:
        assert not (root / "aaaaaaaaaaaa").exists() and q.get("aaaaaaaaaaaa") is None
        assert (root / "bbbbbbbbbbbb").exists() and (root / "cccccccccccc").exists()
        assert (root / "not-a-job" / "keep.txt").exists() and (outside / "keep.txt").exists()
    finally:
        q.stop()


def test_the_sweeper_removes_jobs_24_hours_after_they_end(tmp_path, script):
    now = [time.time()]
    q = jobs.JobQueue(tmp_path / "jobs", jobs.Settings(**FAST), command=fake_command(script), clock=lambda: now[0],
                      free_gib=lambda: 20.0).start()
    try:
        job = submit(q)
        wait_for(q, job)
        stray = tmp_path / "jobs" / "ffffffffffff"
        stray.mkdir()
        os.utime(stray, (now[0] - 90000, now[0] - 90000))
        q.sweep()
        assert job.dir.exists() and q.get(job.id) is not None
        now[0] += 24 * 3600 + 1
        q.sweep()
        assert not job.dir.exists() and q.get(job.id) is None and not stray.exists()
    finally:
        q.stop()


def test_unknown_or_malformed_ids_are_not_found(make_queue):
    q = make_queue(start=False)
    for jid in ("", "x", "../aaaaaaaaaa", "AAAAAAAAAAAA", "aaaaaaaaaaaaa", None):
        assert q.get(jid) is None and q.public(jid) is None


def test_job_records_round_trip_and_reject_junk(tmp_path):
    job = jobs.Job(id="abcdefabcdef", dir=tmp_path, mode="class", kind="video", tracker="bytetrack")
    again = jobs.Job.from_record(json.loads(json.dumps(job.record())), tmp_path)
    assert again.record() == job.record()
    with pytest.raises(ValueError):
        jobs.Job.from_record({**job.record(), "state": "exploded"}, tmp_path)
    with pytest.raises(ValueError):
        jobs.Job.from_record({**job.record(), "id": "../x"}, tmp_path)


def test_new_job_dirs_are_private_and_outside_the_tree(make_queue):
    q = make_queue(start=False)
    job = q.new_job(mode="single", kind="video")
    assert job.dir.is_dir() and (job.dir.stat().st_mode & 0o777) == 0o700
    assert jobs.ROOT not in job.dir.parents
    q.discard(job)
    assert not job.dir.exists()


def test_concurrent_submits_respect_the_cap(make_queue):
    q = make_queue(start=False)
    results = []

    def go():
        try:
            submit(q)
            results.append("ok")
        except jobs.QueueFull:
            results.append("full")
    threads = [threading.Thread(target=go) for _ in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count("ok") == 5 and results.count("full") == 7


def test_kill_group_never_signals_a_finished_process():
    proc = subprocess.Popen([sys.executable, "-c", "pass"], start_new_session=True)
    proc.wait()
    jobs.kill_group(proc, grace_s=0.1)                 # no error, no other group touched
