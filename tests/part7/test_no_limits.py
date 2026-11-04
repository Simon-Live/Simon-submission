"""Operator, verbatim: "no limits anywhere ever". No usage cap refuses, none can be set, and no copy promises one back."""

from __future__ import annotations

import math
from pathlib import Path
import re

import pytest

from part7 import challenges, config, jobs, model_store, muse_prod, quota

ROOT = Path(__file__).resolve().parents[2]


def test_no_window_or_cap_setting_is_left_in_the_prod_config() -> None:
    conf = (ROOT / "prod/compute.conf").read_text(encoding="utf-8")
    up = (ROOT / "prod/up.sh").read_text(encoding="utf-8")
    for name in ("SIMON7_LIMITS_OFF_UNTIL", "SIMON7_SERVERLESS_DAILY_JOBS", "SIMON7_SERVERLESS_USER_DAILY_JOBS",
                 "SIMON7_MUSE_SITE_DAILY_USD", "SIMON7_MUSE_USER_DAILY_USD"):
        assert name not in conf and name not in up
    assert not (ROOT / "part7/limits_window.py").exists()
    assert re.search(r"^SIMON7_SERVERLESS_MAX_CONCURRENT=12$", conf, re.M)


def test_a_person_past_every_old_job_count_is_still_admitted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIMON7_COMPUTE", "serverless")
    q = quota.Quota(tmp_path)
    for _ in range(200):
        q.reserve("trainer", "account:u1")
    assert q.gpu_jobs_today() == 200


def test_a_damaged_day_file_refuses_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIMON7_COMPUTE", "serverless")
    q = quota.Quota(tmp_path)
    q._path().write_text("{not json", encoding="utf-8")
    q.reserve("follow", "account:u1")
    assert q.gpu_jobs_today() == 1


def test_sign_in_and_the_stop_file_still_refuse(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIMON7_COMPUTE", "serverless")
    q = quota.Quota(tmp_path)
    with pytest.raises(quota.SignInRequired):
        q.reserve("follow", None)
    (tmp_path / quota.STOP_FILE).touch()
    with pytest.raises(quota.ComputeStopped):
        q.reserve("follow", "account:u1")


def test_the_free_disk_floor_still_refuses(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIMON7_COMPUTE", "serverless")
    assert quota.disk_refusal(tmp_path, 10, free=lambda _p: 0) == quota.DISK_MESSAGE
    assert quota.disk_refusal(tmp_path, 10, free=lambda _p: 10**15) is None


def test_on_modal_a_take_past_the_workers_waits_in_the_queue(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIMON7_COMPUTE", "serverless")
    monkeypatch.setenv("SIMON7_SERVERLESS_MAX_CONCURRENT", "12")
    assert config.queue_limit() == math.inf
    queue = jobs.JobQueue(tmp_path, start=False)
    made = [queue.submit("follow", lambda *a, **k: None) for _ in range(40)]
    assert len(made) == 40 and queue.has_room() and all(job["status"] == "queued" for job in made)


def test_the_host_gpu_keeps_its_queue_bound(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SIMON7_COMPUTE", raising=False)
    assert config.queue_limit() == config.QUEUE_LIMIT


def test_muse_counts_its_estimate_and_refuses_on_no_amount(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(muse_prod.quota, "visitor_key", lambda v: v)
    for _ in range(1000):
        muse_prod._count("part1", "u1", tmp_path)
    assert not hasattr(muse_prod, "SITE_ENV") and not hasattr(muse_prod, "MSG_SITE")
    assert '"site": 250.0' in muse_prod._day_file(tmp_path).read_text(encoding="utf-8")
    assert muse_prod.PART5_CAP_UNLIMITED_USD >= 1_000_000


def test_no_store_or_board_count_constant_is_left() -> None:
    assert not hasattr(model_store, "MAX_MODELS") and not hasattr(model_store, "MAX_BYTES")
    assert not hasattr(challenges, "MAX_ENTRIES") and not hasattr(challenges, "MAX_BOARDS")
    assert not hasattr(challenges, "BOARDS_PER_VISITOR_DAY")


@pytest.mark.parametrize("folder", ["web", "part7"])
def test_no_screen_promises_a_limit_or_a_return_tomorrow(folder: str) -> None:
    said = re.compile(r"(?i)try again tomorrow|sent tomorrow|today's (limit|analyses|questions|comparisons|readings|AI)|left today|limit for today")
    found = [str(p) for p in (ROOT / folder).rglob("*") if p.suffix in (".py", ".js", ".html") and "vendor" not in p.parts
             and said.search(p.read_text(encoding="utf-8", errors="ignore"))]
    assert found == []
