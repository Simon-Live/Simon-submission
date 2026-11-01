"""Graceful drain and resume of queued jobs on a restart (TICKET-115; staging.md "Restart", processor.md "Restart")."""

from __future__ import annotations

import json
import logging
from pathlib import Path
import threading
import time
from typing import Any, Iterator

import pytest

from part7 import chain, config, jobs, server
from part7.jobs import JobQueue
from support import Api, FakeChild, make_lock
from test_server import _fake_trainer, _upload


def _gate() -> tuple[threading.Event, threading.Event, Any]:
    """A job function that says it started, then waits to be released."""
    started, release = threading.Event(), threading.Event()

    def fn(ctx: Any) -> dict[str, Any]:
        started.set()
        release.wait(30)
        return {}

    return started, release, fn


def test_drain_waits_for_a_running_job_and_logs_it(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    q = JobQueue(tmp_path, workers=1)
    started, release, fn = _gate()
    job = q.submit("follow", fn)["id"]
    assert started.wait(10)
    threading.Timer(0.5, release.set).start()
    t0 = time.monotonic()
    assert q.drain(20, poll_s=0.1) == 0
    assert time.monotonic() - t0 >= 0.4
    assert q.get(job)["status"] == "done"
    assert "drain: waiting for 1 running job(s)" in caplog.text
    q.close()


def test_drain_refuses_new_jobs_and_does_not_start_queued_ones(tmp_path: Path) -> None:
    q = JobQueue(tmp_path, workers=1)
    started, release, fn = _gate()
    q.submit("follow", fn)
    assert started.wait(10)
    waiting = q.submit("follow", lambda ctx: {})["id"]
    done = threading.Thread(target=q.drain, args=(20,), kwargs={"poll_s": 0.1})
    done.start()
    deadline = time.monotonic() + 5
    while not q.draining and time.monotonic() < deadline:
        time.sleep(0.01)
    with pytest.raises(jobs.DrainingError):
        q.submit("follow", lambda ctx: {})
    release.set()
    done.join(10)
    time.sleep(0.2)
    assert q.get(waiting)["status"] == "queued"  # not started during the drain
    q.close()


def test_a_job_running_past_the_max_is_failed_with_a_reason_and_an_anomaly(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    q = JobQueue(tmp_path, workers=1)
    started, release, fn = _gate()
    job = q.submit("follow", fn)["id"]
    assert started.wait(10)
    assert q.drain(0.3, poll_s=0.1) == 1
    got = q.get(job)
    assert got["status"] == "failed" and got["reason"] == jobs.DRAIN_CUT_REASON
    assert f"ANOMALY drain_cut_off job={job}" in caplog.text
    on_disk = json.loads((tmp_path / "jobs" / job / "job.json").read_text())
    assert on_disk["status"] == "failed"
    release.set()
    q.close()


def test_a_queued_job_with_a_resume_spec_stays_queued_and_runs_after_the_restart(tmp_path: Path) -> None:
    first = JobQueue(tmp_path, start=False)
    job = first.submit("follow", lambda ctx: {}, _resume={"v": 1})["id"]
    plain = first.submit("follow", lambda ctx: {})["id"]
    first.close()
    again = JobQueue(tmp_path, workers=1)
    assert again.get(job)["status"] == "queued"
    assert again.get(plain)["status"] == "failed" and again.get(plain)["reason"] == "the server restarted"
    ran = threading.Event()
    assert again.resume(lambda record: (lambda ctx: ran.set() or {})) == 1
    assert again.wait(job, 10)["status"] == "done" and ran.is_set()
    assert "_resume" not in again.get(job)  # the spec is not public
    again.close()


def test_a_queued_job_that_cannot_be_rebuilt_is_failed(tmp_path: Path) -> None:
    first = JobQueue(tmp_path, start=False)
    job = first.submit("follow", lambda ctx: {}, _resume={"v": 1})["id"]
    first.close()
    again = JobQueue(tmp_path, start=False)
    assert again.resume(lambda record: None) == 0
    assert again.get(job)["status"] == "failed" and again.get(job)["reason"] == "the server restarted"


def test_a_running_job_cut_off_by_a_stop_is_still_failed_on_start(tmp_path: Path) -> None:
    q = JobQueue(tmp_path, workers=1)
    started, release, fn = _gate()
    job = q.submit("follow", fn, _resume={"v": 1})["id"]
    assert started.wait(10)
    again = JobQueue(tmp_path, start=False)  # the record on disk says running
    assert again.get(job)["status"] == "failed"
    release.set()
    q.close()


def test_the_drain_limit_comes_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SIMON7_DRAIN_MAX_S", raising=False)
    assert config.drain_max_s() == 600
    monkeypatch.setenv("SIMON7_DRAIN_MAX_S", "45")
    assert config.drain_max_s() == 45
    monkeypatch.setenv("SIMON7_DRAIN_MAX_S", "x")
    assert config.drain_max_s() == 600


def test_new_job_routes_answer_503_with_retry_after_while_draining(api: Api, tiny_mp4: Path) -> None:
    api.app.queue.drain(0)
    status, headers, body = api.request("POST", "api/uploads", tiny_mp4.read_bytes(), {"Content-Type": "video/mp4"})
    assert status == 503 and headers["retry-after"] == "60"
    assert json.loads(body)["message"] == "Restarting shortly, try again in a minute."
    status, headers, _ = api.request("POST", "api/follow", b"{}", {"Content-Type": "application/json"})
    assert status == 503 and "retry-after" in headers
    status, doc = api.json("GET", "api/health")
    assert status == 200 and doc["draining"] is True  # reads, and job polling, keep working
    assert api.request("POST", "api/client-log", b"{}", {"Content-Type": "application/json"})[0] != 503


@pytest.fixture()
def two_apps(tmp_path: Path, state_dir: Path) -> Iterator[Any]:
    created: list[Any] = []

    def make(start: bool) -> Api:
        child = FakeChild(tmp_path / "catalog")
        app = server.build_app(state_dir, "/simon-part-7/", child=child, lock=make_lock(), phrasing="template",
                               start_queue=start)
        http = server.make_server(app)
        threading.Thread(target=http.serve_forever, daemon=True).start()
        created.append((app, http, child))
        return Api(app, http)

    yield make
    for app, http, child in created:
        http.shutdown()
        http.server_close()
        app.queue.close()
        child.close()


def test_a_trainer_job_queued_at_a_stop_runs_after_the_restart(
    two_apps: Any, tiny_mp4: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(chain, "trainer", _fake_trainer("squat"))
    before = two_apps(False)  # nothing runs: the job stays queued, as at a stop
    upload_id = _upload(before, tiny_mp4)
    status, queued = before.json("POST", "api/trainer", {"upload_id": upload_id, "name": "A", "category": "dance"})
    assert status == 202
    before.app.queue.close()
    after = two_apps(True)
    got = after.app.queue.wait(queued["job"], 60)
    assert got["status"] == "done", got
    assert got["entry_id"] == "squat"
