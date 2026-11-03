"""TICKET-289: GPU waits are visible on the job record and in api/health (docs/specs/app.md "GPU wait on the job").

Admission sets `wait` with a reason class and clears it; a lease sets `worker: "warm"`; a dead or busy worker sets
`worker: "cold"` with its reason; api/health carries `gpu: {busy, holder}` with no pid or path.
"""

from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from typing import Any, Iterator

import pytest

from part7 import gpu_lock, job_gpu, jobs, p2_worker
from part7.parts import p2_pose
from support import Api

HOLD = ("import fcntl, os, sys, time\n"
        "fd = os.open(sys.argv[1], os.O_CREAT | os.O_RDWR, 0o666)\n"
        "fcntl.flock(fd, fcntl.LOCK_EX)\n"
        "print('held', flush=True)\n"
        "time.sleep(float(sys.argv[2]))\n")


@contextlib.contextmanager
def held_by_child(lock: Path, seconds: float) -> Iterator[subprocess.Popen[str]]:
    """A child process of this test holds the flock on `lock` for `seconds`; it is killed by its own handle at the end."""
    lock.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen([sys.executable, "-c", HOLD, str(lock), str(seconds)], stdout=subprocess.PIPE, text=True)
    try:
        assert proc.stdout is not None and proc.stdout.readline().strip() == "held"
        yield proc
    finally:
        proc.kill()
        proc.wait(5)


@pytest.fixture
def fast_note(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gpu_lock, "NOTE_AFTER_S", 0.1)
    monkeypatch.setattr(gpu_lock, "NOTE_POLL_S", 0.05)


@pytest.fixture
def job(tmp_path: Path) -> Iterator[tuple[Path, list[dict[str, Any]]]]:
    """A tracked job folder and the field updates sent to it."""
    root = tmp_path / "jobs" / "abcdefabcdef"
    (root / "work").mkdir(parents=True)
    seen: list[dict[str, Any]] = []
    job_gpu.track(root, lambda **f: seen.append(f))
    yield root, seen
    job_gpu.untrack(root)


def _waits(seen: list[dict[str, Any]]) -> list[Any]:
    return [f["wait"] for f in seen if "wait" in f]


def _admit_while_held(lock: Path, work: Path, hold_s: float = 1.0) -> None:
    with held_by_child(lock, hold_s):
        with gpu_lock.acquire(lock_path=lock, min_free_mib=0, poll_s=0.05, timeout_s=10.0, job_dir=work,
                              concurrent=True, hold_flock=False, settle_s=0.0):
            pass


def test_admission_behind_an_outside_holder_sets_other_gpu_work_then_clears(
    fast_note: None, job: tuple[Path, list[dict[str, Any]]], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, seen = job
    monkeypatch.setattr(gpu_lock, "_from_here", lambda pid, depth=8: False)  # as if an eval run outside held it
    _admit_while_held(tmp_path / "gpu.lock", root / "work")
    waits = _waits(seen)
    assert waits[0]["reason"] == job_gpu.OTHER_WORK and waits[0]["since"].endswith("Z")
    assert waits[-1] is None  # admission ended: cleared
    assert not any(isinstance(w, dict) and ("pid" in json.dumps(w) or "/" in w["reason"]) for w in waits)


def test_admission_behind_a_holder_this_server_started_is_another_take(
    fast_note: None, job: tuple[Path, list[dict[str, Any]]], tmp_path: Path
) -> None:
    root, seen = job
    _admit_while_held(tmp_path / "gpu.lock", root / "work")  # the holder is our child, as a take's Part 2 is
    waits = _waits(seen)
    assert waits[0]["reason"] == job_gpu.ANOTHER_TAKE and waits[-1] is None


def test_a_short_admission_and_an_untracked_folder_write_nothing(
    job: tuple[Path, list[dict[str, Any]]], tmp_path: Path
) -> None:
    root, seen = job
    with gpu_lock.acquire(lock_path=tmp_path / "gpu.lock", min_free_mib=0, poll_s=0.05, timeout_s=2.0, job_dir=root):
        pass
    assert seen == []  # no wait at all: the record is untouched (the negative)
    other = tmp_path / "elsewhere"
    other.mkdir()
    assert not job_gpu.tracked(other)


def test_a_timed_out_admission_clears_the_wait(
    fast_note: None, job: tuple[Path, list[dict[str, Any]]], tmp_path: Path
) -> None:
    root, seen = job
    lock = tmp_path / "gpu.lock"
    with held_by_child(lock, 5.0), pytest.raises(TimeoutError):
        with gpu_lock.acquire(lock_path=lock, min_free_mib=0, poll_s=0.05, timeout_s=0.6, job_dir=root):
            pass
    waits = _waits(seen)
    assert waits and waits[0]["reason"] == job_gpu.ANOTHER_TAKE and waits[-1] is None


def test_the_job_queue_shows_the_wait_on_the_record_and_clears_it(fast_note: None, tmp_path: Path) -> None:
    queue = jobs.JobQueue(tmp_path / "state", workers=1)
    lock = tmp_path / "gpu.lock"
    seen_running: list[Any] = []

    def fn(ctx: jobs.JobContext) -> dict[str, Any]:
        with held_by_child(lock, 1.0):
            def peek() -> None:
                time.sleep(0.6)
                seen_running.append((queue.get(ctx.id) or {}).get("wait"))
            t = threading.Thread(target=peek)
            t.start()
            with gpu_lock.acquire(lock_path=lock, min_free_mib=0, poll_s=0.05, timeout_s=10.0, job_dir=ctx.work):
                pass
            t.join()
        return {}

    try:
        view = queue.submit("follow", fn)
        done = queue.wait(view["id"], timeout=15)
    finally:
        queue.close()
    assert seen_running[0]["reason"] == job_gpu.ANOTHER_TAKE  # the API view carries it while waiting
    assert done is not None and done["status"] == "done" and done["wait"] is None
    record = json.loads((tmp_path / "state" / "jobs" / view["id"] / "job.json").read_text())
    assert record["wait"] is None


def test_from_here_follows_parent_pids() -> None:
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(5)"])
    try:
        assert gpu_lock._from_here(proc.pid) and gpu_lock._from_here(os.getpid())
        assert not gpu_lock._from_here(1)
    finally:
        proc.kill()
        proc.wait(5)


# ----- the warm worker -------------------------------------------------------------------------------------------
def _p2(monkeypatch: pytest.MonkeyPatch, sock: Path | None, state: str, drop: bool = False) -> list[list[str]]:
    """Fakes for `p2_pose._execute`: the pin has `--worker`, the lease gives `sock`, the pool reads `state`."""
    ran: list[list[str]] = []

    @contextlib.contextmanager
    def fake_lease() -> Iterator[Path | None]:
        yield sock

    def fake_launch(sub: list[str], s: Path | None, work_p: Path, log_name: str, *a: Any) -> dict[str, Any]:
        ran.append([*sub, *(["--worker", str(s)] if s is not None else [])])
        if s is not None and drop:
            (work_p / "steps").mkdir(parents=True, exist_ok=True)
            (work_p / "steps" / log_name).write_text("the worker closed the connection", encoding="utf-8")
            return {"exit": 1}
        return {"exit": 0}

    monkeypatch.setattr(p2_pose, "has_worker", lambda *a, **k: True)
    monkeypatch.setattr(p2_pose.p2_worker, "lease", fake_lease)
    monkeypatch.setattr(p2_pose.p2_worker, "state", lambda: state)
    monkeypatch.setattr(p2_pose, "_launch", fake_launch)
    return ran


def _execute(root: Path) -> dict[str, Any]:
    return p2_pose._execute(["run", "--video", "v.mp4"], "gpu", root / "work", "p2.log", None, Path("."), False, None)  # type: ignore[arg-type]


def test_a_lease_sets_worker_warm(job: tuple[Path, list[dict[str, Any]]], tmp_path: Path,
                                  monkeypatch: pytest.MonkeyPatch) -> None:
    root, seen = job
    ran = _p2(monkeypatch, tmp_path / "w0.sock", "busy")
    _execute(root)
    assert seen == [{"worker": "warm", "worker_reason": None}] and "--worker" in ran[0]


def test_a_dead_worker_fallback_sets_cold_restarting(job: tuple[Path, list[dict[str, Any]]],
                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    root, seen = job
    _p2(monkeypatch, None, "starting")  # the killed worker failed its health check and restarts
    _execute(root)
    assert seen == [{"worker": "cold", "worker_reason": job_gpu.COLD_RESTARTING}]


def test_a_busy_worker_sets_cold_busy_and_a_dropped_call_sets_cold_failed(
    job: tuple[Path, list[dict[str, Any]]], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, seen = job
    _p2(monkeypatch, None, "busy")
    _execute(root)
    assert seen[-1] == {"worker": "cold", "worker_reason": job_gpu.COLD_BUSY}
    seen.clear()
    ran = _p2(monkeypatch, tmp_path / "w0.sock", "idle", drop=True)
    _execute(root)
    assert [f["worker"] for f in seen] == ["warm", "cold"] and seen[-1]["worker_reason"] == job_gpu.COLD_FAILED
    assert "--worker" in ran[0] and "--worker" not in ran[1]


def test_no_pool_reports_no_worker(job: tuple[Path, list[dict[str, Any]]], monkeypatch: pytest.MonkeyPatch) -> None:
    root, seen = job
    _p2(monkeypatch, None, "off")  # dev: no warm worker at all is not a fallback
    _execute(root)
    assert seen == []
    assert p2_worker.state() == "off"


# ----- api/health ----------------------------------------------------------------------------------------------
def test_health_gpu_block_names_an_outside_holder_as_other(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    lock = Path(os.environ["SIMON7_GPU_LOCK_PATH"])
    monkeypatch.setattr(gpu_lock, "_from_here", lambda pid, depth=8: False)
    with held_by_child(lock, 10.0) as proc:
        status, doc = api.json("GET", "api/health")
    assert status == 200 and doc["gpu"] == {"busy": True, "holder": "other"}
    assert doc["queue"]["running"] == 0  # an idle queue, yet the GPU is not free
    assert str(proc.pid) not in json.dumps(doc["gpu"]) and str(lock) not in json.dumps(doc)


def test_health_gpu_block_names_this_servers_holder_as_part7(api: Api) -> None:
    with held_by_child(Path(os.environ["SIMON7_GPU_LOCK_PATH"]), 10.0):
        assert api.json("GET", "api/health")[1]["gpu"] == {"busy": True, "holder": "part7"}
    with gpu_lock.acquire(min_free_mib=0, timeout_s=2.0):  # a call of this process past admission
        assert api.json("GET", "api/health")[1]["gpu"] == {"busy": True, "holder": "part7"}


def test_health_gpu_block_with_no_holder_is_not_busy(api: Api) -> None:
    status, doc = api.json("GET", "api/health")
    assert status == 200 and doc["gpu"] == {"busy": False, "holder": None}


def test_holder_class_names_the_class_without_pid_or_path(tmp_path: Path) -> None:
    """TICKET-305: the finding text uses this: no holder is `other GPU work`; a child of the test is a class, never a pid."""
    lock = tmp_path / "gpu.lock"
    assert gpu_lock.holder_class(lock) == job_gpu.OTHER_WORK
    with held_by_child(lock, 20) as proc:
        text = gpu_lock.holder_class(lock)
    assert str(proc.pid) not in text and str(tmp_path) not in text and "pid" not in text


def test_gpu_waits_lists_only_jobs_in_admission(tmp_path: Path) -> None:
    """TICKET-305: the heartbeat reads the waits from the queue; a finished or unwaiting job is not listed."""
    queue = jobs.JobQueue(tmp_path / "state", workers=1)
    release, inside = threading.Event(), threading.Event()

    def fn(ctx: jobs.JobContext) -> dict[str, Any]:
        queue.update(ctx.id, wait={"since": "2026-11-02T10:00:00Z", "reason": job_gpu.OTHER_WORK})
        inside.set()
        release.wait(10)
        queue.update(ctx.id, wait=None)
        return {}

    try:
        view = queue.submit("follow", fn)
        assert inside.wait(10)
        [(jid, since, reason)] = queue.gpu_waits()
        assert jid == view["id"] and reason == job_gpu.OTHER_WORK and since == 1793613600.0
        release.set()
        assert queue.wait(view["id"], timeout=15) is not None
        assert queue.gpu_waits() == []
    finally:
        release.set()
        queue.close()
