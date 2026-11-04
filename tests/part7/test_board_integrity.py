"""Board integrity (docs/specs/challenges.md "Integrity"): a deleted take, a deleted account, an under-18 mark and
a name that hides itself all leave nothing of the person on a board; a board others are on outlives its maker.
Real sign-in, the real identity store and the real delete and board routes."""

from __future__ import annotations

import json
from typing import Any

import pytest

from auth_support import authenv, post, sign_in  # noqa: F401  authenv is a fixture
from part7 import auth, challenges, delete_routes, takes_on
from support import Api
from test_challenges import _create, _job

ENTRY = "lateral-raise"


def _user(api: Api, sid: str) -> str:
    return auth.identity(api.app).session_user(sid)


def _owned_job(api: Api, sid: str, job_id: str) -> str:
    _job(api, job_id)
    auth.identity(api.app).attach(job_id, _user(api, sid), "follow", ENTRY, None, "submit")
    return job_id


def _join(api: Api, cid: str, job_id: str, name: str, sid: str | None = None) -> None:
    status, _, body = post(api, f"api/challenges/{cid}/entries", {"job_id": job_id, "name": name}, cookie=sid)
    assert status == 201, body


def _names(api: Api, cid: str) -> list[str]:
    doc = challenges.get(api.app.state, cid)
    return [e["name"] for e in doc["entries"]] if doc else []


# ----- row 4: a take gone after the 7-day sweep leaves no score -------------------------------------------
def test_deleting_an_expired_take_takes_its_score_off_the_board(api: Api) -> None:
    cid = _create(api)["id"]
    job = _job(api, "ccccccccccc1")
    _join(api, cid, job, "Sam")
    other = _job(api, "ccccccccccc2")
    _join(api, cid, other, "Kim")
    api.app.queue._jobs.pop(job)  # the 7-day sweep
    status, body = delete_routes.delete_take(api.app, job)
    assert status == 200 and "board" in body["removed"], body
    assert _names(api, cid) == ["Kim"]  # negative: the other score stays
    assert delete_routes.delete_take(api.app, job)[0] == 404  # and a take that was never there is still missing


def test_account_delete_after_the_sweep_removes_the_account_scores(api: Api, authenv: Any) -> None:
    sid = sign_in(api)
    cid = _create(api)["id"]
    job = _owned_job(api, sid, "ddddddddddd1")
    _join(api, cid, job, "Ada", sid)
    _join(api, cid, _job(api, "ddddddddddd2"), "Kim")
    api.app.queue._jobs.pop(job)
    assert delete_routes.remove_for_account(api.app, job) == "removed"
    assert _names(api, cid) == ["Kim"]


def test_a_stranger_cannot_delete_an_expired_take_an_account_owns(api: Api, authenv: Any) -> None:
    sid = sign_in(api)
    cid = _create(api)["id"]
    job = _owned_job(api, sid, "eeeeeeeeeee1")
    _join(api, cid, job, "Ada", sid)
    api.app.queue._jobs.pop(job)
    status, _, body = post(api, f"api/jobs/{job}/delete", {})
    assert status == 403, body
    assert _names(api, cid) == ["Ada"]
    assert post(api, f"api/jobs/{job}/delete", {}, cookie=sid)[0] == 200
    assert _names(api, cid) == []


# ----- row 11: the maker leaves, the board stays for the others ---------------------------------------------
def test_deleting_the_makers_data_keeps_a_board_others_are_on(api: Api, authenv: Any) -> None:
    sid = sign_in(api)
    uid = _user(api, sid)
    doc = challenges.create(api.app.state, entry_id=ENTRY, title="Raises", creator_name="Maker Name", kind="friend", owner=uid, visitor="v")
    _join(api, doc["id"], _job(api, "fffffffffff1"), "Someone else")
    challenges.remove_account(api.app.state, uid)
    kept = challenges.get(api.app.state, doc["id"])
    assert kept is not None and _names(api, doc["id"]) == ["Someone else"]
    assert kept["creator_name"] != "Maker Name" and "owner" not in kept and "visitor" not in kept
    assert "Maker Name" not in str(kept)


def test_an_empty_board_of_the_maker_is_removed(api: Api, authenv: Any) -> None:
    uid = _user(api, sign_in(api))
    doc = challenges.create(api.app.state, entry_id=ENTRY, title="T", creator_name="Maker", kind="friend", owner=uid)
    challenges.remove_account(api.app.state, uid)
    assert challenges.get(api.app.state, doc["id"]) is None


def test_the_makers_own_scores_leave_the_board_they_made(api: Api, authenv: Any) -> None:
    sid = sign_in(api)
    uid = _user(api, sid)
    doc = challenges.create(api.app.state, entry_id=ENTRY, title="T", creator_name="Maker", kind="friend", owner=uid)
    _join(api, doc["id"], _owned_job(api, sid, "abababababa1"), "Maker", sid)
    _join(api, doc["id"], _job(api, "abababababa2"), "Other")
    challenges.remove_account(api.app.state, uid)
    assert _names(api, doc["id"]) == ["Other"]


# ----- row 5: an under-18 mark after posting ---------------------------------------------------------------
def test_the_minor_mark_takes_the_scores_and_the_name_off_every_board(api: Api, authenv: Any) -> None:
    sid = sign_in(api)
    uid = _user(api, sid)
    mine = challenges.create(api.app.state, entry_id=ENTRY, title="Mine", creator_name="Teen Maker", kind="friend", owner=uid)
    _join(api, mine["id"], _job(api, "cdcdcdcdcdc1"), "Other")
    theirs = _create(api)["id"]
    _join(api, theirs, _owned_job(api, sid, "cdcdcdcdcdc2"), "Teen", sid)
    _join(api, theirs, _job(api, "cdcdcdcdcdc3"), "Adult")
    auth.identity(api.app).mark_minor(uid)
    assert _names(api, theirs) == ["Adult"]
    assert _names(api, mine["id"]) == ["Other"]
    assert "Teen Maker" not in str(challenges.get(api.app.state, mine["id"]))


def test_board_keep_hides_a_post_of_a_minor_account_even_before_any_sweep(api: Api, authenv: Any) -> None:
    sid = sign_in(api)
    cid = _create(api)["id"]
    job = _owned_job(api, sid, "efefefefefe1")
    _join(api, cid, job, "Teen", sid)
    keep = takes_on.board_keep(api.app, ENTRY)
    stored = challenges.get(api.app.state, cid)["entries"][0]
    assert keep(stored) is True  # control: an adult's post shows
    store = auth.identity(api.app)
    store.write("UPDATE users SET age_band = 'minor' WHERE user_id = ?", (_user(api, sid),))  # the mark, without the sweep
    assert takes_on.board_keep(api.app, ENTRY)(stored) is False
    status, body = api.json("GET", f"api/challenges/{cid}")[0:2]
    assert status == 200 and body["entries"] == []


def test_board_keep_hides_a_post_whose_take_says_13_to_17(api: Api) -> None:
    cid = _create(api)["id"]
    job = _job(api, "1212121212a1", consent={"age_band": "minor"})
    (api.app.queue.job_dir(job) / "job.json").write_text(json.dumps(api.app.queue._jobs[job]), encoding="utf-8")  # what a board view reads
    stored = {"job_id": job, "name": "Teen", "score": 80}
    assert takes_on.board_keep(api.app, ENTRY)(stored) is False
    assert cid  # the board exists; the check is the rule


# ----- row 12: Download my data lists every board with a score of mine -----------------------------------------
def test_download_my_data_lists_boards_with_my_score_and_only_my_entries(api: Api, authenv: Any) -> None:
    from part7 import export_data

    sid = sign_in(api)
    uid = _user(api, sid)
    other = challenges.create(api.app.state, entry_id=ENTRY, title="Theirs", creator_name="Other Maker", kind="friend", owner="u" + "0" * 31)
    _join(api, other["id"], _owned_job(api, sid, "a0a0a0a0a0a1"), "Ada", sid)
    _join(api, other["id"], _job(api, "a0a0a0a0a0a2"), "Somebody")
    stranger = challenges.create(api.app.state, entry_id=ENTRY, title="Not mine", creator_name="Third", kind="friend")
    _join(api, stranger["id"], _job(api, "a0a0a0a0a0a3"), "Somebody")
    raw = export_data.build(export_data.Ctx(api.app.state, auth.identity(api.app), uid)).decode("utf-8")
    boards = json.loads(raw)["boards"]
    assert [b["title"] for b in boards] == ["Theirs"]  # negative: the board with no entry of mine is not there
    assert boards[0]["made_by_me"] is False and "creator_name" not in boards[0]
    assert [e["name"] for e in boards[0]["my_entries"]] == ["Ada"] and boards[0]["entry_count"] == 2
    shown = json.dumps(boards)
    assert "Somebody" not in shown and "Other Maker" not in shown and "job_id" not in shown and "owner" not in shown


# ----- row 3: names -------------------------------------------------------------------------------------------
@pytest.mark.parametrize("raw", ["​", "‮gnp.evil", "⠀", "­", "A​B", "ab﻿", "‏x", "Simon", "simon official", "SIMON  Official", "Simon Support", "Simon Staff", "Official Simon", "Moderator", "Admin", "Staff"])
def test_clean_name_refuses_format_characters_and_reserved_names(raw: str) -> None:
    with pytest.raises(challenges.ChallengeError):
        challenges.clean_name(raw)


@pytest.mark.parametrize("raw", ["Sam", "Simone", "Simon Cowell", "Amélie", "李雷"])
def test_clean_name_keeps_ordinary_names(raw: str) -> None:
    assert challenges.clean_name(raw) == raw
