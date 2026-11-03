""""Show only my 3D model" on the server (docs/specs/model-default.md AC-MD12): the owner's choice is stamped on the
follow job at submit, and no route serves the person's camera clip of a stamped job, to anyone. Unstamped is unchanged."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from auth_support import authenv, get, post, sign_in  # noqa: F401
from part7 import auth, chain, model_only, profile
from history_support import FIRST, SECOND, USER, job_record, seed_job, world  # noqa: F401
from support import Api
from test_people import class_mp4  # noqa: F401
from test_server import _fake_follower, _upload


def signed_follow(api: Api, tiny_mp4: Path, monkeypatch: pytest.MonkeyPatch, sid: str) -> str:
    """A follow sent by the signed-in `sid`, with the fake chain; returns the finished job id."""
    monkeypatch.setattr(chain, "follower", _fake_follower())
    api.app.child.files["animation.json"] = json.dumps({"format": "simon.animation.v1", "fps": 10, "frame_count": 2, "duration_s": 0.2,
                                                        "frames": [{"index": i, "t": i / 10, "joints": {"nose": [0, 0, 0]}} for i in range(2)]}).encode()
    upload = _upload(api, tiny_mp4)
    status, _, doc = post(api, "api/follow", {"upload_id": upload, "entry_id": "lateral-raise"}, cookie=sid)
    assert status == 202, doc
    api.app.queue.wait(doc["job"], 60)
    return doc["job"]


def turn_on(api: Api, sid: str, model: Any = "skeleton") -> None:
    store = auth.identity(api.app)
    profile.update(store, store.session_user(sid), {"default_model_id": model, "model_only_view": True})


def clip_status(api: Api, job: str, sid: str | None) -> tuple[int, Any]:
    status, _, data = api.request("GET", f"api/results/{job}/video.mp4", None,
                                  {"Cookie": f"{auth.COOKIE}={sid}"} if sid else {})
    try:
        return status, json.loads(data)
    except ValueError:
        return status, None


@pytest.mark.usefixtures("authenv")
def test_a_stamped_take_serves_no_camera_clip_to_the_owner_or_anyone(api: Api, tiny_mp4: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ada, grace = sign_in(api), sign_in(api, "grace@example.com")
    turn_on(api, ada)
    job = signed_follow(api, tiny_mp4, monkeypatch, ada)
    record = api.app.queue.get(job)
    assert record["model_only_view"] is True and record.get("video_kept") is not False  # stamped, the video is still kept
    assert (api.app.queue.job_dir(job) / "work" / "video.mp4").is_file()  # the raw take stays for Part 2
    for who in (ada, grace, None):
        status, body = clip_status(api, job, who)
        assert status == 404 and body["error"] == model_only.MSG_VIEW_ONLY, who
    status, doc = api.json("POST", f"api/jobs/{job}/export", {})
    assert status == 404 and doc["error"] == model_only.MSG_VIEW_ONLY  # no export clip either
    served = api.json("GET", f"api/jobs/{job}")[1]
    assert served["model_only_view"] is True  # the result page reads the stamp, for every viewer


@pytest.mark.usefixtures("authenv")
def test_an_unstamped_take_is_unchanged(api: Api, tiny_mp4: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ada = sign_in(api)
    job = signed_follow(api, tiny_mp4, monkeypatch, ada)
    assert "model_only_view" not in api.app.queue.get(job)
    assert clip_status(api, job, ada)[0] in (200, 206)
    assert clip_status(api, job, None)[0] in (200, 206)


@pytest.mark.usefixtures("authenv")
def test_on_without_a_default_model_does_not_stamp(api: Api, tiny_mp4: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ada = sign_in(api)
    turn_on(api, ada, model=None)
    job = signed_follow(api, tiny_mp4, monkeypatch, ada)
    assert "model_only_view" not in api.app.queue.get(job)
    assert clip_status(api, job, ada)[0] in (200, 206)


def test_view_only_reads_only_the_exact_stamp() -> None:
    assert model_only.view_only({"model_only_view": True})
    for record in ({}, None, {"model_only_view": 1}, {"model_only_view": "true"}, {"model_only_view": False}):
        assert not model_only.view_only(record)


# ----- every other route that could carry the person's clip (review delta B1 to B3) ---------------------------------
def stamped_kept_take(api: Api, sid: str) -> str:
    """A finished follow take with its camera clip on disk, stamped by its owner, claimed into the owner's history."""
    from test_notes import make_job
    job = make_job(api, model_only_view=True)
    assert post(api, "api/me/claims", {"job_id": job}, cookie=sid)[0] == 200
    return job


@pytest.mark.usefixtures("authenv")
def test_clip_path_gives_none_for_a_stamped_take(api: Api) -> None:
    from part7 import result_media
    from test_notes import make_job
    job, plain = make_job(api, model_only_view=True), make_job(api)
    assert (api.app.queue.job_dir(job) / "work" / "video.mp4").is_file()  # the file is kept
    h = type("H", (), {"app": api.app})()
    assert result_media.clip_path(h, job, None) is None
    assert result_media.clip_path(h, plain, None) is not None  # witness: an unstamped take still has its clip


def test_a_stamped_take_has_no_history_clip(tmp_path: Path, world: Any) -> None:
    from part7 import history_store
    world.opted_in.add(USER)
    for job, fields in ((FIRST, {}), (SECOND, {"model_only_view": True})):
        folder = seed_job(tmp_path, job, **fields)
        world.owners[job] = USER
        assert history_store.record_take(tmp_path, job_record(tmp_path, job), folder)
    by_job = {r["job_id"]: r for r in history_store.takes(tmp_path, USER, "body-squat-19b06562")}
    assert by_job[SECOND]["clip"] is None
    assert by_job[FIRST]["clip"] is not None  # witness: the unstamped take keeps its clip


@pytest.mark.usefixtures("authenv")
def test_a_note_request_never_offers_or_serves_a_stamped_clip(api: Api) -> None:
    from test_notes import World
    world = World(api)
    assert world.view()[1]["has_clip"] is True  # witness: the unstamped take
    assert world.ask(["score", "clip"])[0] == 201
    rid = world.request_id()
    url = get(api, f"api/me/note-requests/{rid}", cookie=world.trainer)[2]["clip"]
    serve = lambda: api.request("GET", url, None, {"Cookie": f"{auth.COOKIE}={world.trainer}"})[0]  # noqa: E731
    assert serve() == 200
    api.app.queue.update(world.job, model_only_view=True)  # the same take, stamped
    assert serve() == 404
    assert world.view()[1]["has_clip"] is False
    stamped = stamped_kept_take(api, world.follower)
    assert world.view(stamped)[1]["has_clip"] is False
    status, doc = world.ask(["clip"], stamped)
    assert status == 400 and "no clip" in doc["message"]


@pytest.mark.usefixtures("authenv")
def test_a_share_of_a_stamped_take_carries_no_clip(api: Api) -> None:
    from test_share import share_body
    sid = sign_in(api)
    job = stamped_kept_take(api, sid)
    status, _, doc = post(api, "api/shares", share_body(job, show_clip=True), cookie=sid)
    assert status == 201, doc
    status, _, shared = get(api, f"api/shared/{doc['token']}")
    assert status == 200 and shared["clip"] is None
    assert get(api, f"api/shared/{doc['token']}/clip.mp4")[0] == 404


def test_a_group_take_carries_the_people_job_stamp_and_serves_no_person_video(api: Api, class_mp4: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from test_people import VISITOR, Fakes, _group_body, _people_job
    Fakes(monkeypatch, {0: 20, 1: 20, 2: 20, 3: 20})
    people = _people_job(api, class_mp4)
    api.app.queue.update(people["id"], model_only_view=True)  # as POST api/people stamps it for an owner with the choice on
    body = _group_body(api, people["id"])
    status, doc = api.json("POST", "api/group", body, VISITOR)
    assert status == 202, doc
    group = api.app.queue.wait(doc["job"], 90)
    assert group["model_only_view"] is True
    for pid in body["follower_ids"]:
        status, _, data = api.request("GET", f"api/results/{group['id']}/{pid}/video.mp4")
        assert status == 404 and json.loads(data)["error"] == model_only.MSG_VIEW_ONLY, pid


def test_an_unstamped_group_take_is_not_stamped(api: Api, class_mp4: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from test_people import VISITOR, Fakes, _group_body, _people_job
    Fakes(monkeypatch, {0: 20, 1: 20, 2: 20, 3: 20})
    people = _people_job(api, class_mp4)
    status, doc = api.json("POST", "api/group", _group_body(api, people["id"]), VISITOR)
    assert status == 202, doc
    assert "model_only_view" not in api.app.queue.wait(doc["job"], 90)


def test_a_profile_read_error_never_fails_the_take(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(_store: Any, _uid: Any) -> bool:
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(model_only, "owner_view", boom)
    monkeypatch.setattr(auth, "current_user", lambda _h: "u-1")
    monkeypatch.setattr(auth, "identity", lambda _app: object())
    record: dict[str, Any] = {}
    model_only.stamp(type("H", (), {"app": None})(), record)
    assert record == {}
