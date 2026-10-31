"""Quota, queue and replay validation (app.md "Quotas and spend", "Jobs"; AC-A8, AC-A11, AC-R4)."""

from __future__ import annotations

import json
import os
from pathlib import Path
import threading
import time
from typing import Any

import pytest

from part7 import config, jobs, keys, modules, quota, replay
from part7.jobs import JobFailed, JobQueue, QueueFullError, sanitize_reason


# ----- quota ------------------------------------------------------------------------------------
def test_visitor_trainer_limit_is_three_and_gpu_limit_ten(tmp_path: Path) -> None:
    q = quota.Quota(tmp_path)
    for _ in range(3):
        q.reserve("trainer", "1.2.3.4")
    with pytest.raises(quota.VisitorQuotaError, match="Try again tomorrow"):
        q.reserve("trainer", "1.2.3.4")
    for _ in range(7):
        q.reserve("follow", "1.2.3.4")
    with pytest.raises(quota.VisitorQuotaError):
        q.reserve("follow", "1.2.3.4")
    q.reserve("follow", "5.6.7.8")


def test_no_visitor_skips_the_visitor_quota_but_not_the_daily_caps(tmp_path: Path) -> None:
    q = quota.Quota(tmp_path, daily_gpu=15, daily_trainer=2)
    for _ in range(2):
        q.reserve("trainer", None)
    with pytest.raises(quota.DailyCapError, match="today's limit"):
        q.reserve("trainer", None)
    for _ in range(13):
        q.reserve("follow", None)
    with pytest.raises(quota.DailyCapError):
        q.reserve("follow", None)
    assert q.gpu_jobs_today() == 15


def test_default_daily_caps_are_forty_gpu_and_ten_trainer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SIMON7_DAILY_GPU", raising=False)
    q = quota.Quota(tmp_path)
    assert (q.daily_gpu, q.daily_trainer) == (40, 10)


def test_counters_persist_reset_by_day_and_release(tmp_path: Path) -> None:
    day = ["2026-10-30"]
    q = quota.Quota(tmp_path, today=lambda: day[0])
    q.reserve("trainer", "9.9.9.9")
    assert quota.Quota(tmp_path, today=lambda: day[0]).gpu_jobs_today() == 1
    q.release("trainer", "9.9.9.9")
    assert q.gpu_jobs_today() == 0
    q.reserve("follow", "9.9.9.9")
    day[0] = "2026-10-31"
    assert q.gpu_jobs_today() == 0
    assert (tmp_path / "quota" / "2026-10-30.json").is_file()


def test_visitor_addresses_are_not_stored(tmp_path: Path) -> None:
    quota.Quota(tmp_path).reserve("follow", "198.51.100.77")
    assert "198.51.100.77" not in "".join(p.read_text() for p in (tmp_path / "quota").iterdir())


# ----- queue ------------------------------------------------------------------------------------
def test_job_runs_and_records_result_on_disk(tmp_path: Path) -> None:
    q = JobQueue(tmp_path)

    def fn(ctx: jobs.JobContext) -> dict[str, Any]:
        ctx.set_stage("pose")
        ctx.add_note("a")
        ctx.add_note("b")
        return {"entry_id": "e1", "result": {"x": 1}}

    job = q.submit("trainer", fn)
    done = q.wait(job["id"], 10)
    assert (done["status"], done["entry_id"], done["result"], done["note"]) == ("done", "e1", {"x": 1}, "a; b")
    on_disk = json.loads((tmp_path / "jobs" / job["id"] / "job.json").read_text())
    assert on_disk["status"] == "done" and on_disk["stages"] == ["pose"]
    q.close()


def test_only_one_job_runs_at_a_time(tmp_path: Path) -> None:
    q, live, peak = JobQueue(tmp_path, workers=1), [0], [0]

    def fn(ctx: jobs.JobContext) -> None:
        live[0] += 1
        peak[0] = max(peak[0], live[0])
        time.sleep(0.05)
        live[0] -= 1

    ids = [q.submit("follow", fn)["id"] for _ in range(4)]
    assert all(q.wait(i, 20)["status"] == "done" for i in ids) and peak[0] == 1
    q.close()


def test_queue_limit_and_positions(tmp_path: Path) -> None:
    q, gate = JobQueue(tmp_path, limit=3, workers=1), threading.Event()
    ids = [q.submit("follow", lambda ctx: gate.wait(20))["id"] for _ in range(3)]
    with pytest.raises(QueueFullError, match="busy"):
        q.submit("follow", lambda ctx: None)
    deadline = time.monotonic() + 5
    while q.get(ids[0])["status"] != "running" and time.monotonic() < deadline:
        time.sleep(0.01)
    assert [q.get(i)["queue_position"] for i in ids] == [None, 1, 2]
    assert q.counts() == {"running": 1, "waiting": 2}
    gate.set()
    assert q.wait(ids[2], 20)["status"] == "done"
    q.close()


def test_default_queue_limit_is_eight(tmp_path: Path) -> None:
    assert JobQueue(tmp_path, start=False).limit == 8


def test_failure_reason_has_no_path_host_or_key(tmp_path: Path) -> None:
    secret = tmp_path / "keys"
    secret.mkdir()
    (secret / "MODEL_API_KEY").write_text("sk-live-abcdef123456")
    os.environ["SIMON7_KEYS_DIR"] = str(secret)
    try:
        keys.read_key("MODEL_API_KEY")
        q = JobQueue(tmp_path / "s")

        def fn(ctx: jobs.JobContext) -> None:
            raise JobFailed("pose", "failed in /home/user/.local/state/x.log on api.example.com with sk-live-abcdef123456")

        done = q.wait(q.submit("trainer", fn)["id"], 10)
        assert done["status"] == "failed" and done["stage"] == "pose"
        for text in (done["reason"], done["error"]):
            assert "/" not in text.replace("failed:pose:", "") and "example.com" not in text and "sk-live" not in text
        q.close()
    finally:
        os.environ.pop("SIMON7_KEYS_DIR")


def test_unexpected_exception_gives_a_plain_reason_and_logs_the_traceback(tmp_path: Path) -> None:
    q = JobQueue(tmp_path)

    def fn(ctx: jobs.JobContext) -> None:
        ctx.set_stage("skeleton")
        raise KeyError("/secret/path/file")

    job = q.submit("follow", fn)
    done = q.wait(job["id"], 10)
    assert done["error"] == f"failed:skeleton: {jobs.FALLBACK_REASON}"
    assert "KeyError" in (tmp_path / "jobs" / job["id"] / "steps" / "error.log").read_text()
    q.close()


@pytest.mark.parametrize("raw,expected", [
    ("", jobs.FALLBACK_REASON),
    ("/a/b/c", jobs.FALLBACK_REASON),
    ("the 3D step took too long", "the 3D step took too long"),
    ("open /tmp/x.json failed: missing", "open failed: missing"),
    ("call to https://example.com/v1 failed", "call to failed"),
])
def test_sanitize_reason(raw: str, expected: str) -> None:
    assert sanitize_reason(raw) == expected


def test_restart_fails_unfinished_jobs_and_cleanup_removes_week_old_jobs(tmp_path: Path) -> None:
    q = JobQueue(tmp_path, start=False)
    first = q.submit("follow", lambda ctx: None)["id"]
    q.close()
    again = JobQueue(tmp_path, start=False)
    got = again.get(first)
    assert got["status"] == "failed" and got["reason"] == "the server restarted"
    record = tmp_path / "jobs" / first / "job.json"
    old = time.time() - (config.RETENTION_DAYS * 86400 + 60)
    os.utime(record, (old, old))
    assert again.cleanup() == 1 and not (tmp_path / "jobs" / first).exists()


# ----- replay -----------------------------------------------------------------------------------
FIXTURE = config.REPO_ROOT / "fixtures" / "input" / "replay.json"


def test_fixture_replay_is_valid() -> None:
    assert replay.validate(json.loads(FIXTURE.read_text())) == []


@pytest.mark.parametrize("mutate,needle", [
    (lambda d: d.pop("exp_to_fol"), "exp_to_fol: is required"),
    (lambda d: d.update(format="other"), "replay.format"),
    (lambda d: d.update(fps="30"), "replay.fps"),
    (lambda d: d["expected_t"].pop(), "expected_t"),
    (lambda d: d["exp_to_fol"].__setitem__(0, 5000), "points past"),
])
def test_broken_replay_is_rejected(mutate: Any, needle: str, monkeypatch: Any) -> None:
    doc = json.loads(FIXTURE.read_text())
    mutate(doc)
    assert needle in " ".join(replay.validate(doc))


def test_schema_comes_from_the_part_5_module(tmp_path: Path) -> None:
    from support import lock_with_schema

    lk, state = lock_with_schema(tmp_path, {"type": "object", "required": ["only"]})
    assert replay.validate({}, lk, state) == ["replay.only: is required"]
    assert replay.validate({"only": 1}, lk, state) == []


def test_read_valid_rejects_non_json(tmp_path: Path) -> None:
    path = tmp_path / "r.json"
    path.write_text("not json")
    assert replay.read_valid(path)[0] is None


def test_two_workers_run_two_jobs_together_and_keep_the_limit(tmp_path: Path) -> None:
    q, gate, live, peak = JobQueue(tmp_path, limit=3, workers=2), threading.Event(), [0], [0]
    mu = threading.Lock()

    def fn(ctx: jobs.JobContext) -> None:
        with mu:
            live[0] += 1
            peak[0] = max(peak[0], live[0])
        gate.wait(20)
        with mu:
            live[0] -= 1

    ids = [q.submit("follow", fn)["id"] for _ in range(3)]
    with pytest.raises(QueueFullError):
        q.submit("follow", fn)
    deadline = time.monotonic() + 5
    # wait for the whole state, not only "running": the third job is counted as waiting a moment later
    while q.counts() != {"running": 2, "waiting": 1} and time.monotonic() < deadline:
        time.sleep(0.01)
    assert q.counts() == {"running": 2, "waiting": 1}
    # "running" is recorded a moment before the job function starts: wait until both are inside it
    while live[0] < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    gate.set()
    assert all(q.wait(i, 20)["status"] == "done" for i in ids) and peak[0] == 2
    q.close()


def test_worker_count_comes_from_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SIMON7_GPU_WORKERS", raising=False)
    assert JobQueue(tmp_path, start=False).workers == 2
    monkeypatch.setenv("SIMON7_GPU_WORKERS", "3")
    assert JobQueue(tmp_path, start=False).workers == 3
    monkeypatch.setenv("SIMON7_GPU_WORKERS", "nope")
    assert JobQueue(tmp_path, start=False).workers == 2


def test_limits_off_counts_but_never_refuses(tmp_path, monkeypatch) -> None:
    """Operator 2026-10-30: no limits during heavy testing (SIMON7_LIMITS off is the default)."""
    from part7 import quota

    monkeypatch.delenv("SIMON7_LIMITS", raising=False)
    q = quota.Quota(tmp_path, daily_gpu=1, daily_trainer=1, visitor_gpu=1, visitor_trainer=1)
    for _ in range(5):
        q.reserve("trainer", "203.0.113.9")
    assert q.gpu_jobs_today() == 5


def test_missing_schema_fails_closed(tmp_path: Path) -> None:
    lk = modules.Modules(root=tmp_path, shas={"5": "5" * 40})
    assert "missing" in " ".join(replay.validate(json.loads(FIXTURE.read_text()), lk))
