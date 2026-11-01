"""Idempotency-Key on uploads, follow, trainer and group (offline takes; app.md "Idempotency-Key")."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import time

import pytest

from part7 import chain, config, idempotency, quota, server
from support import Api
from test_server import _fake_follower, _fake_trainer, _upload

KEY = "3f2b8c1e-9d4a-4e7b-8a61-0c5d2e9f7a10"
OTHER = "aa2b8c1e-9d4a-4e7b-8a61-0c5d2e9f7a11"


def _hdr(key: str = KEY, **more: str) -> dict[str, str]:
    return {"Idempotency-Key": key, **more}


def test_the_same_key_returns_the_same_upload_and_stores_one_file(api: Api, tiny_mp4: Path) -> None:
    first = api.upload(tiny_mp4, headers=_hdr())
    again = api.upload(tiny_mp4, headers=_hdr())
    assert first[0] == 201 and again == first
    assert len(list(api.app.uploads.iterdir())) == 1
    other = api.upload(tiny_mp4, headers=_hdr(OTHER))
    assert other[0] == 201 and other[1]["upload_id"] != first[1]["upload_id"]


def test_an_upload_whose_file_is_gone_is_uploaded_again_under_the_same_key(api: Api, tiny_mp4: Path) -> None:
    first = api.upload(tiny_mp4, headers=_hdr())[1]
    shutil.rmtree(api.app.uploads / first["upload_id"])
    second = api.upload(tiny_mp4, headers=_hdr())
    assert second[0] == 201 and second[1]["upload_id"] != first["upload_id"]
    assert api.app.upload_file(second[1]["upload_id"]) is not None
    assert api.upload(tiny_mp4, headers=_hdr()) == second  # and that answer is the one remembered now


def test_the_same_key_gives_one_job_and_charges_no_second_quota(api: Api, tiny_mp4: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chain, "trainer", _fake_trainer())
    upload_id = _upload(api, tiny_mp4)
    body = {"upload_id": upload_id, "name": "A", "category": "dance"}
    hdr = _hdr(**{"Cf-Connecting-Ip": "203.0.113.9"})
    status, first = api.json("POST", "api/trainer", body, hdr)
    assert status == 202
    api.app.queue.wait(first["job"], 60)
    used = api.app.quota.gpu_jobs_today()
    for _ in range(config.VISITOR_TRAINER_PER_DAY + 2):  # more repeats than the visitor's daily allowance
        status, again = api.json("POST", "api/trainer", body, hdr)
        assert (status, again["job"]) == (202, first["job"])
    assert api.app.quota.gpu_jobs_today() == used


def test_follow_repeats_return_the_original_job(api: Api, tiny_mp4: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chain, "follower", _fake_follower())
    body = {"upload_id": _upload(api, tiny_mp4), "entry_id": "lateral-raise"}
    status, first = api.json("POST", "api/follow", body, _hdr())
    assert status == 202, first
    api.app.queue.wait(first["job"], 60)
    assert api.json("POST", "api/follow", body, _hdr())[1]["job"] == first["job"]
    assert api.json("POST", "api/follow", body, _hdr(OTHER))[1]["job"] != first["job"]


def test_a_refusal_is_not_remembered_so_the_retry_can_succeed(api: Api, tiny_mp4: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chain, "trainer", _fake_trainer())
    body = {"upload_id": _upload(api, tiny_mp4), "name": "A", "category": "dance"}
    api.app.quota.daily_gpu = 0
    assert api.json("POST", "api/trainer", body, _hdr())[0] == 503
    api.app.quota.daily_gpu = 100
    status, doc = api.json("POST", "api/trainer", body, _hdr())
    assert status == 202 and doc["job"]


@pytest.mark.parametrize("bad", ["", "not-a-uuid", "3f2b8c1e-9d4a-4e7b-8a61-0c5d2e9f7a1", "x" * 200, "3f2b8c1e9d4a4e7b8a610c5d2e9f7a10"])
def test_a_bad_key_is_ignored_like_no_key(api: Api, tiny_mp4: Path, bad: str) -> None:
    one = api.upload(tiny_mp4, headers={"Idempotency-Key": bad})
    two = api.upload(tiny_mp4, headers={"Idempotency-Key": bad})
    assert one[0] == two[0] == 201 and one[1]["upload_id"] != two[1]["upload_id"]
    assert list(api.app.idempotency.dir.iterdir()) == []


def test_requests_without_a_key_behave_as_before(api: Api, tiny_mp4: Path) -> None:
    assert api.upload(tiny_mp4)[1]["upload_id"] != api.upload(tiny_mp4)[1]["upload_id"]


def test_a_key_on_another_route_is_ignored(api: Api) -> None:
    status, _, _ = api.request("GET", "api/health", headers=_hdr())
    assert status == 200
    status, _ = api.json("POST", "api/client-log", {"level": "info", "event": "x", "detail": {}}, _hdr())
    assert list(api.app.idempotency.dir.iterdir()) == []


def test_the_same_key_on_two_routes_is_two_records(api: Api, tiny_mp4: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The browser uses the take id on the upload and on the job: they must not collide."""
    monkeypatch.setattr(chain, "trainer", _fake_trainer())
    up = api.upload(tiny_mp4, headers=_hdr())[1]
    status, job = api.json("POST", "api/trainer", {"upload_id": up["upload_id"], "name": "A", "category": "dance"}, _hdr())
    assert status == 202 and job["job"]
    assert api.upload(tiny_mp4, headers=_hdr())[1] == up


def test_records_are_pruned_after_seven_days(tmp_path: Path) -> None:
    store = idempotency.Store(tmp_path)
    store.put("uploads", KEY, 201, {"upload_id": "a"})
    store.put("follow", OTHER, 202, {"job": "j"})
    old = time.time() - (config.RETENTION_DAYS + 1) * 86400
    os.utime(store.dir / f"uploads-{KEY}.json", (old, old))
    assert store.prune(config.RETENTION_DAYS) == 1
    assert store.get("uploads", KEY) is None and store.get("follow", OTHER) == (202, {"job": "j"})


def test_start_prunes_old_records(tmp_path: Path, state_dir: Path) -> None:
    from support import FakeChild, make_lock

    store = idempotency.Store(state_dir)
    store.put("uploads", KEY, 201, {"upload_id": "a"})
    old = time.time() - (config.RETENTION_DAYS + 1) * 86400
    os.utime(store.dir / f"uploads-{KEY}.json", (old, old))
    child = FakeChild(tmp_path / "catalog")
    try:
        app = server.build_app(state_dir, "/", child=child, lock=make_lock(), web_dir=tmp_path, phrasing="template")
        app.queue.close()
    finally:
        child.close()
    assert not list(store.dir.glob("uploads-*.json"))


def test_only_accepted_answers_are_replayable() -> None:
    assert idempotency.REPLAYABLE == (201, 202)
    assert idempotency.valid_key(KEY.upper()) == KEY and idempotency.valid_key(None) is None
    assert quota.VISITOR_MESSAGE  # the 429 text is the one the browser classifies as "try again tomorrow"
