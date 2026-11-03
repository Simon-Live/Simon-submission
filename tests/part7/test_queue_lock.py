"""One server runs the jobs of a state folder: the queue lock and the standby queue (TICKET-240; staging.md "Restart
with no gap", app.md "Jobs")."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import threading
import time
from typing import Any, Callable

from part7 import jobs
from part7.jobs import JobQueue
from part7.queue_lock import QueueLock, start_time


def _until(cond: Callable[[], bool], timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return True
        time.sleep(0.02)
    return cond()


class Ledger:
    """Which queue ran which job, across queues (the double-run check)."""

    def __init__(self) -> None:
        self.runs: list[tuple[str, str]] = []
        self._lock = threading.Lock()

    def fn(self, who: str, tag: str, gate: threading.Event | None = None) -> Callable[[Any], dict[str, Any]]:
        def run(ctx: Any) -> dict[str, Any]:
            with self._lock:
                self.runs.append((who, tag))
            if gate is not None:
                gate.wait(30)
            return {}
        return run

    def tags(self) -> list[str]:
        with self._lock:
            return [tag for _, tag in self.runs]


def test_a_second_queue_on_the_same_folder_is_a_standby_and_runs_nothing(tmp_path: Path) -> None:
    ledger = Ledger()
    first = JobQueue(tmp_path, workers=1)
    second = JobQueue(tmp_path, workers=1)
    try:
        assert first.owner and not second.owner
        job = second.submit("follow", ledger.fn("second", "c"))["id"]
        time.sleep(1.5)  # three lock polls
        assert ledger.tags() == [] and second.get(job)["status"] == "queued"
    finally:
        second.close()
        first.close()


def test_the_standby_takes_jobs_only_after_the_owner_releases_the_lock(tmp_path: Path) -> None:
    ledger = Ledger()
    first = JobQueue(tmp_path, workers=1)
    second = JobQueue(tmp_path, workers=1)
    try:
        job = second.submit("follow", ledger.fn("second", "c"))["id"]
        time.sleep(1.0)
        assert ledger.tags() == []
        released = time.monotonic()
        first.close()
        assert _until(lambda: second.owner)
        assert second.wait(job, 10)["status"] == "done"
        assert ledger.runs == [("second", "c")]
        assert time.monotonic() - released < 30  # a few lock polls; loose for a loaded host
    finally:
        second.close()


def test_two_queues_never_run_the_same_job_across_a_drain_and_takeover(tmp_path: Path) -> None:
    """The old server finishes its running job, its queued resumable job runs once on the new one, the new one's own
    job runs once, and the new one never marks the old one's running job failed."""
    ledger = Ledger()
    gate = threading.Event()
    old = JobQueue(tmp_path, workers=1)
    running = old.submit("follow", ledger.fn("old", "a", gate))["id"]
    assert _until(lambda: ledger.tags() == ["a"])
    resumable = old.submit("follow", ledger.fn("old", "b"), _resume={"kind": "follow"})["id"]
    new = JobQueue(tmp_path, workers=2)
    new.resume(lambda record: ledger.fn("new", "b") if record["id"] == resumable else None)
    own = new.submit("trainer", ledger.fn("new", "c"))["id"]
    try:
        assert not new.owner
        assert json.loads((tmp_path / "jobs" / running / "job.json").read_text())["status"] == "running"
        assert new.get(running)["status"] == "running", "the standby reads the old server's record from disk"
        drained = threading.Thread(target=old.drain, args=(20,), kwargs={"poll_s": 0.05})
        drained.start()
        time.sleep(0.5)
        gate.set()
        drained.join(10)
        assert new.get(running)["status"] == "done", "the standby sees the old server finish it"
        assert not new.owner, "the old server still holds the lock until it closes"
        old.close()
        assert _until(lambda: new.owner)
        assert new.wait(resumable, 10)["status"] == "done"
        assert new.wait(own, 10)["status"] == "done"
        assert new.get(running)["status"] == "done", "the takeover never marks a finished job failed"
        assert sorted(ledger.runs) == [("new", "b"), ("new", "c"), ("old", "a")]
    finally:
        gate.set()
        new.close()
        old.close()


def test_a_standby_that_is_stopped_never_takes_the_lock(tmp_path: Path) -> None:
    first = JobQueue(tmp_path, workers=1)
    second = JobQueue(tmp_path, workers=1)
    try:
        assert second.drain(5, poll_s=0.05) == 0
        first.close()
        time.sleep(1.5)
        assert not second.owner
        third = JobQueue(tmp_path, workers=1)
        assert third.owner
        third.close()
    finally:
        second.close()
        first.close()


def test_when_owner_hooks_run_now_on_an_owner_and_at_takeover_on_a_standby(tmp_path: Path) -> None:
    calls: list[str] = []
    first = JobQueue(tmp_path, workers=1)
    first.when_owner(lambda: calls.append("first"))
    second = JobQueue(tmp_path, workers=1)
    second.when_owner(lambda: calls.append("second"))
    try:
        assert calls == ["first"]
        first.close()
        assert _until(lambda: calls == ["first", "second"])
    finally:
        second.close()
        first.close()


def test_the_standby_waits_for_the_named_old_process_even_without_a_lock(tmp_path: Path) -> None:
    """An old build that predates the lock: the new queue waits for its pid to exit."""
    old = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        q = JobQueue(tmp_path, workers=1, after_pid=old.pid)
        try:
            time.sleep(1.0)
            assert not q.owner
            old.kill()
            old.wait(5)
            assert _until(lambda: q.owner)
        finally:
            q.close()
    finally:
        old.kill()


def test_the_lock_follows_a_crashed_holder_in_another_process(tmp_path: Path) -> None:
    holder = subprocess.Popen(
        [sys.executable, "-c", "import sys, time; from part7.queue_lock import QueueLock\n"
         "assert QueueLock(sys.argv[1]).try_take(); print('held', flush=True); time.sleep(30)", str(tmp_path)],
        stdout=subprocess.PIPE, text=True, cwd=Path(jobs.__file__).resolve().parents[1],
    )
    try:
        assert holder.stdout is not None and holder.stdout.readline().strip() == "held"
        q = JobQueue(tmp_path, workers=1)
        try:
            assert not q.owner
            holder.kill()
            holder.wait(5)
            assert _until(lambda: q.owner)
        finally:
            q.close()
    finally:
        holder.kill()


def test_queue_lock_ignores_a_reused_pid_and_releases_on_close(tmp_path: Path) -> None:
    me = QueueLock(tmp_path, after_pid=999_999_999)  # no such process: nothing to wait for
    assert not me.waits_for_pid() and me.try_take() and me.held
    other = QueueLock(tmp_path)
    assert not other.try_take()
    me.release()
    me.release()  # idempotent
    assert other.try_take()
    other.release()
    assert start_time(999_999_999) is None


def test_queues_without_a_lock_behave_as_before(tmp_path: Path) -> None:
    """`start=False` (tests, tools) takes no lock: a second queue still loads and marks records as a restart does."""
    first = JobQueue(tmp_path, start=False)
    second = JobQueue(tmp_path, start=False)
    assert first.owner and second.owner
    first.close()
    second.close()


def test_jobs_after_pid_reads_only_a_positive_pid(monkeypatch: Any) -> None:
    from part7 import config
    for value, want in (("4242", 4242), ("", None), ("0", None), ("-3", None), ("abc", None)):
        monkeypatch.setenv("SIMON7_JOBS_AFTER_PID", value)
        assert config.jobs_after_pid() == want
    assert 'SIMON7_JOBS_AFTER_PID="$after" setsid nohup python3 -m part7 serve' in (
        Path(jobs.__file__).resolve().parents[1] / "staging" / "server-lib.sh").read_text()
