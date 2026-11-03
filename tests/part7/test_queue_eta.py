"""The rough wait estimate (app.md "Wait estimate", TICKET-288): estimator, queue fields and the job API."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import threading
import time
import uuid

from part7 import queue_eta
from part7.jobs import JobQueue
from support import Api

NOW = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc).timestamp()


def _stamp(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _seed(root: Path, n: int, kind: str, seconds: list[float] | float, ago: float = 3600.0, status: str = "done",
          now: float | None = None) -> None:
    """`n` finished job records of `kind` under `root`, each run for `seconds`, finished `ago` seconds before now."""
    now = time.time() if now is None else now
    for i in range(n):
        run = seconds[i] if isinstance(seconds, list) else seconds
        finished = now - ago - i
        job_id = uuid.uuid4().hex[:12]
        folder = root / job_id
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "job.json").write_text(json.dumps({
            "id": job_id, "kind": kind, "status": status,
            "started_at": _stamp(finished - run), "finished_at": _stamp(finished),
        }), encoding="utf-8")


def _cache(root: Path) -> queue_eta.EtaCache:
    cache = queue_eta.EtaCache(root, clock=lambda: NOW)
    cache.refresh()
    return cache


# ----- estimator ---------------------------------------------------------------------------------
def test_fewer_than_three_samples_gives_no_estimate(tmp_path: Path) -> None:
    _seed(tmp_path, 2, "follow", 400, now=NOW)
    cache = _cache(tmp_path)
    assert cache.median("follow") is None
    assert queue_eta.for_queued("follow", [], [], 2, cache.median) is None
    assert queue_eta.for_running("follow", 10, cache.median) is None


def test_the_median_of_the_last_ten_done_jobs_of_the_kind(tmp_path: Path) -> None:
    _seed(tmp_path, 3, "follow", [300, 500, 400], now=NOW)
    _seed(tmp_path, 3, "trainer", 900, now=NOW)
    _seed(tmp_path, 4, "follow", 5000, status="failed", ago=7200, now=NOW)  # failed jobs are not samples
    assert _cache(tmp_path).median("follow") == (400, 3)
    _seed(tmp_path, 12, "group", [100] * 10 + [9000, 9000], ago=60, now=NOW)  # the two oldest fall outside the last ten
    assert _cache(tmp_path).median("group") == (100, 10)


def test_stale_samples_are_ignored(tmp_path: Path) -> None:
    _seed(tmp_path, 3, "follow", 400, ago=8 * 86400, now=NOW)
    _seed(tmp_path, 2, "follow", 600, now=NOW)
    assert _cache(tmp_path).median("follow") is None  # two recent ones: not enough
    _seed(tmp_path, 1, "follow", 800, ago=10, now=NOW)
    assert _cache(tmp_path).median("follow") == (600, 3)


def test_jobs_ahead_and_running_ones_are_shared_by_the_workers() -> None:
    med = {"follow": (400.0, 5), "trainer": (600.0, 4)}.get
    eta, basis = queue_eta.for_queued("follow", ["trainer", "follow"], [("follow", 100.0), ("trainer", 0.0)], 2, med)
    # ahead 600 + 400, running left 300 + 600, over two workers, then its own 400
    assert eta == round((600 + 400 + 300 + 600) / 2 + 400)
    assert basis == {"kind": "follow", "samples": 5, "median_s": 400, "ahead": 2, "running": 2, "workers": 2, "late": False}
    assert queue_eta.for_queued("follow", ["group"], [], 2, med) is None  # a kind ahead without samples: no number


def test_a_running_job_counts_its_elapsed_time_and_never_goes_negative() -> None:
    med = {"follow": (400.0, 5)}.get
    eta, basis = queue_eta.for_running("follow", 150.0, med)
    assert (eta, basis["late"], basis["elapsed_s"]) == (250, False, 150)
    eta, basis = queue_eta.for_running("follow", 900.0, med)
    assert eta == queue_eta.MIN_LEFT_S and eta > 0 and basis["late"] is True


def test_bad_records_are_skipped(tmp_path: Path) -> None:
    (tmp_path / "abcdefabcdef").mkdir()
    (tmp_path / "abcdefabcdef" / "job.json").write_text("{not json", encoding="utf-8")
    _seed(tmp_path, 3, "follow", 400, now=NOW)
    assert queue_eta.sample_of({"status": "done", "kind": "follow", "started_at": None, "finished_at": _stamp(NOW)}) is None
    assert _cache(tmp_path).median("follow") == (400, 3)


# ----- the queue and the job API -----------------------------------------------------------------
def _wait_running(q: JobQueue, ids: list[str], n: int) -> None:
    deadline = time.monotonic() + 5
    while sum(q.get(i)["status"] == "running" for i in ids) < n and time.monotonic() < deadline:
        time.sleep(0.01)


def test_queue_view_has_eta_only_with_samples_and_refreshes_on_completion(tmp_path: Path) -> None:
    q, gate = JobQueue(tmp_path, workers=1), threading.Event()
    ids = [q.submit("follow", lambda ctx: gate.wait(20))["id"] for _ in range(2)]
    _wait_running(q, ids, 1)
    assert "eta_s" not in q.get(ids[0]) and "eta_s" not in q.get(ids[1])  # no samples yet: the old answer exactly
    _seed(tmp_path / "jobs", 3, "follow", 400)
    q._eta.refresh()
    running, queued = q.get(ids[0]), q.get(ids[1])
    assert 0 < running["eta_s"] <= 400 and running["eta_basis"]["samples"] == 3
    assert queued["queue_position"] == 1 and 400 < queued["eta_s"] <= 800
    gate.set()
    assert q.wait(ids[1], 20)["status"] == "done"
    assert "eta_s" not in q.get(ids[1])  # a finished job has no estimate
    q.close()


def test_job_api_queued_job_carries_eta_s(api: Api) -> None:
    q, gate = api.app.queue, threading.Event()
    _seed(q.root, 3, "trainer", 600)
    q._eta.refresh()
    ids = [q.submit("trainer", lambda ctx: gate.wait(20))["id"] for _ in range(q.workers + 1)]
    try:
        _wait_running(q, ids, q.workers)
        status, doc = api.json("GET", f"api/jobs/{ids[-1]}")
        assert status == 200 and doc["status"] == "queued" and doc["queue_position"] == 1
        assert doc["eta_basis"]["samples"] == 3 and doc["eta_basis"]["workers"] == q.workers
        assert 600 < doc["eta_s"] <= 1200  # the running ones' remainder shared by the workers, plus its own run
        status, doc = api.json("GET", f"api/jobs/{ids[0]}")
        assert doc["status"] == "running" and 0 < doc["eta_s"] <= 600
    finally:
        gate.set()
        for i in ids:
            q.wait(i, 20)
