"""A job cut off by a restart is queued again when it can be rebuilt (TICKET-290; processor.md "Restart")."""

from __future__ import annotations

import json
import logging
from pathlib import Path
import threading
from typing import Any

import pytest

from part7 import jobs
from part7.jobs import JobFailed, JobQueue


def _gate(outcome: str = "fail") -> tuple[threading.Event, threading.Event, Any]:
    """A job that writes into its work folder, says it started, waits, then fails (or finishes) like a cut run."""
    started, release = threading.Event(), threading.Event()

    def fn(ctx: Any) -> dict[str, Any]:
        (ctx.dir / "work").mkdir(parents=True, exist_ok=True)
        (ctx.dir / "work" / "partial.mp4").write_bytes(b"x")
        started.set()
        release.wait(30)
        if outcome == "fail":
            raise JobFailed("pose", "part2: the worker closed the connection before finishing")
        return {"result": {"ok": True}}

    return started, release, fn


def _disk(root: Path, job: str) -> dict[str, Any]:
    return json.loads((root / "jobs" / job / "job.json").read_text())


def test_a_cut_job_with_a_resume_spec_is_queued_again_and_the_cut_run_cannot_fail_it(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    q = JobQueue(tmp_path, workers=1)
    started, release, fn = _gate()
    job = q.submit("trainer", fn, _resume={"v": 2, "upload_id": "22428e47f4b643ad"})["id"]
    assert started.wait(10)
    assert q.drain(0.3, poll_s=0.1) == 1
    got = q.get(job)
    assert got["status"] == "queued" and got["note"] == jobs.CUT_REQUEUE_NOTE and got["reason"] is None
    assert f"ANOMALY drain_cut_off job={job}" in caplog.text and "requeued=true" in caplog.text
    release.set()  # the cut run ends with a failure after the drain, as the live one did
    q.close()
    on_disk = _disk(tmp_path, job)
    assert on_disk["status"] == "queued" and on_disk["cut_offs"] == 1 and on_disk["work_reset"] is True


def test_the_next_server_clears_the_old_work_folder_and_runs_the_cut_job(tmp_path: Path) -> None:
    q = JobQueue(tmp_path, workers=1)
    started, release, fn = _gate()
    job = q.submit("trainer", fn, _resume={"v": 1, "upload_id": "22428e47f4b643ad"})["id"]
    assert started.wait(10)
    q.drain(0.3, poll_s=0.1)
    release.set()
    q.close()
    again = JobQueue(tmp_path, workers=1)
    assert not (tmp_path / "jobs" / job / "work").exists(), "the cut run's partial files are gone"
    assert "work_reset" not in _disk(tmp_path, job)
    assert again.resume(lambda record: (lambda ctx: {"result": {"again": True}})) == 1
    done = again.wait(job, 10)
    assert done["status"] == "done" and done["result"] == {"again": True}
    again.close()


def test_a_job_cut_more_than_the_limit_fails_with_the_plain_reason(tmp_path: Path) -> None:
    q = JobQueue(tmp_path, workers=1)
    started, release, fn = _gate()
    job = q.submit("trainer", fn, _resume={"v": 1}, cut_offs=jobs.CUT_REQUEUE_MAX)["id"]
    assert started.wait(10)
    q.drain(0.3, poll_s=0.1)
    got = q.get(job)
    assert got["status"] == "failed" and got["reason"] == jobs.DRAIN_CUT_REASON
    release.set()
    q.close()


def test_a_job_without_a_resume_spec_still_fails_at_the_cut(tmp_path: Path) -> None:
    q = JobQueue(tmp_path, workers=1)
    started, release, fn = _gate()
    job = q.submit("people", fn)["id"]
    assert started.wait(10)
    q.drain(0.3, poll_s=0.1)
    assert q.get(job)["status"] == "failed"
    release.set()
    q.close()


def test_a_cut_run_that_still_finishes_counts_as_done(tmp_path: Path) -> None:
    q = JobQueue(tmp_path, workers=1)
    started, release, fn = _gate("done")
    job = q.submit("follow", fn, _resume={"v": 1})["id"]
    assert started.wait(10)
    q.drain(0.3, poll_s=0.1)
    release.set()
    deadline = threading.Event()
    for _ in range(100):
        if q.get(job)["status"] == "done":
            break
        deadline.wait(0.05)
    got = q.get(job)
    assert got["status"] == "done" and got["note"] is None and got["result"] == {"ok": True}
    assert _disk(tmp_path, job)["status"] == "done" and "work_reset" not in _disk(tmp_path, job)
    q.close()


@pytest.mark.parametrize("extra", [{"stage": "catalog"}, {"stage": "skeleton"}, {"video_kept": False}])
def test_a_job_past_the_point_of_no_return_is_not_run_again(tmp_path: Path, extra: dict[str, Any]) -> None:
    job: dict[str, Any] = {"id": "abcabcabcabc", "kind": "trainer", "status": "running", "stage": "pose",
                           "_resume": {"v": 1}, **extra}
    assert JobQueue._requeue_cut(job) is False
    assert job["status"] == "running"
    assert JobQueue._requeue_cut({**job, "stage": "pose", "video_kept": True, "kind": "follow"}) is True
