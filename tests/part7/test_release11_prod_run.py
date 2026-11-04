"""Release 11, from the release 9 prod run: a press of "You, doing it right" always ends in a line (muse-fix-ui.md),
"Kept" only when it is (web-signin.md), a reel says the page's score, and invited boards and group takes keep to their people."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from auth_support import authenv, claim_doc, get, post, sign_in  # noqa: F401  authenv is a fixture
from history_support import World, world  # noqa: F401
from part7 import auth, challenges, history_reel, history_store, muse_fix, muse_fix_routes as routes, muse_prod, takes_on, upload_owner
from support import Api
from test_challenges import _create, _job
from test_history_reel import _facts
from test_muse_fix import Fake, build_job, drawing_on  # noqa: F401  drawing_on is an autouse fixture: the shipped switch is off (R14)
from test_muse_fix_routes import Env, consent, fake_run
from test_release11_fixes import _store
from test_takes_on import URL, board, make_job

SPINE = {"joint": "spine", "follower_frames": [0, 1], "magnitude_deg": 40.0}
ELBOW = {"joint": "left_elbow", "follower_frames": [0, 1], "magnitude_deg": 10.0}


def _analysis(job: Path, *faults: dict[str, Any]) -> None:
    (job / "work" / "follower").mkdir(parents=True, exist_ok=True)
    (job / "work" / "follower" / "analysis.json").write_text(json.dumps({"faults": list(faults)}))


# ----- H1: You, doing it right ------------------------------------------------------------------------------
def test_a_take_with_no_fault_to_draw_offers_nothing_and_touches_no_limit(api: Api, world: World, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    env = Env(api, world)
    consent(api)
    monkeypatch.setattr(muse_fix, "run", fake_run(env))
    admitted: list[Any] = []
    real = muse_prod.admit
    monkeypatch.setattr(muse_prod, "admit", lambda *a, **k: (admitted.append(a), real(*a, **k))[1])
    _analysis(env.dir, SPINE, {"joint": "hip", "side": "both", "follower_frames": [0]}, {"joint": "left_ankle", "follower_frames": [0]})
    assert env.get()[1]["can_draw"] is False
    status, doc = env.post("image")
    assert status == 409 and doc["code"] == "no_fault_to_draw"
    assert "Nothing was sent" in doc["message"]
    assert env.runs == [] and admitted == []  # negative: no run, and nothing counted against the person


def test_a_take_with_a_fault_to_draw_is_offered(api: Api, world: World, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    monkeypatch.setattr(muse_fix, "DRAW_ENABLED", True)  # shipped off (release 14; off behaviour: test_muse_fix_r14.py)
    monkeypatch.setattr("part7.muse_fix_measure.available", lambda: True)
    monkeypatch.setattr("part7.muse_fix_measure.reachable", lambda: True)
    env = Env(api, world)
    consent(api)
    monkeypatch.setattr(muse_fix, "run", fake_run(env))
    _analysis(env.dir, SPINE, ELBOW)
    assert env.get()[1]["can_draw"] is True
    assert env.post("image")[0] == 202
    env.settle()
    assert len(env.runs) == 1


def test_a_press_that_found_no_moment_leaves_a_line_on_the_card(tmp_path: Path) -> None:
    job, fake = build_job(tmp_path / "jobs"), Fake()
    _analysis(job, {"joint": "left_elbow", "follower_frames": [], "magnitude_deg": 9.0})
    assert muse_fix.run(job, consent=True, transport=fake, state=tmp_path / "s")["status"] == "not_available"
    shown = muse_fix.latest_card(job)
    assert shown == {"status": "not_available", "message": muse_fix.NOTHING_SENT} and fake.edits == []
    assert muse_fix.report(job.parent)["scored"] == 0  # negative: a press that made no call is no miss of the model


def test_the_biggest_fault_with_a_moment_is_the_one_drawn(tmp_path: Path) -> None:
    job = build_job(tmp_path / "jobs")
    doc = json.loads((job / "work" / "follower" / "analysis.json").read_text())
    timed = doc["faults"][0]
    _analysis(job, {**timed, "follower_frames": [], "magnitude_deg": 99.0}, {**timed, "magnitude_deg": 1.0})
    replay = json.loads((job / "work" / "follower" / "replay.json").read_text())
    index, moment = muse_fix._first_moment(json.loads((job / "work" / "follower" / "analysis.json").read_text()), replay)
    assert index == 1 and moment is not None


def test_a_worker_fault_leaves_a_failed_line_on_the_card(api: Api, world: World, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    monkeypatch.setattr(muse_fix, "DRAW_ENABLED", True)  # shipped off (release 14; off behaviour: test_muse_fix_r14.py)
    monkeypatch.setattr("part7.muse_fix_measure.available", lambda: True)
    monkeypatch.setattr("part7.muse_fix_measure.reachable", lambda: True)
    env = Env(api, world)
    consent(api)

    def boom(*_a: Any, **_k: Any) -> None:
        raise RuntimeError("no GPU")

    monkeypatch.setattr(muse_fix, "run", boom)
    assert env.post("image")[0] == 202
    env.settle()
    assert env.get()[1]["card"] == {"status": "failed", "message": muse_fix.NOT_DRAWN}
    assert routes.active(env.id) is False


# ----- M2: Kept -----------------------------------------------------------------------------------------------
def _follow(api: Api) -> str:
    def fn(ctx: Any) -> dict[str, Any]:
        (ctx.work / "follower").mkdir()
        (ctx.work / "follower" / "analysis.json").write_text(json.dumps({"score": {"value": 81, "grade": "B"}}))
        return {"result": {}}

    made = api.app.queue.submit("follow", fn, entry_id="lateral-raise")
    assert api.app.queue.wait(made["id"], 10)["status"] == "done"
    return made["id"]


def test_a_take_is_kept_only_when_its_history_copy_exists(api: Api) -> None:
    sid, mine = sign_in(api), _follow(api)
    status, _, body = post(api, "api/me/claims", claim_doc(api, mine), cookie=sid)
    assert status == 200 and body["claimed"] is True and body["kept"] is False  # no retention consent: on the account, no copy
    assert get(api, "api/me/takes", cookie=sid)[2]["takes"][0]["kept"] is False
    uid = get(api, "api/auth/me", cookie=sid)[2]["user_id"]
    auth.identity(api.app).set_consent(uid, "v1", True)
    status, _, body = post(api, "api/me/claims", claim_doc(api, mine), cookie=sid)
    assert status == 200 and body["kept"] is True and history_store.has_copy(api.app.state, uid, "lateral-raise", mine)
    assert get(api, "api/me/takes", cookie=sid)[2]["takes"][0]["kept"] is True


# ----- the reel says what the page says -----------------------------------------------------------------------
PAGE = {"letter": "A", "figures": "9,570", "caption": "of 10,000", "unit": "points", "capped": False}


def test_a_reel_is_sent_only_the_page_score() -> None:
    assert history_reel._page_score_only({"score": 78, "grade": "C", "shown": PAGE}) == {"score": None, "grade": None, "shown": PAGE}
    assert history_reel._page_score_only({"score": 78, "grade": "C"})["score"] == 78  # an old take has nothing else to say


@pytest.mark.parametrize("text, kept", [
    ("Take 2 at 0.9 s, score 78.", False),
    ("The grade C shows at 0.9 s.", False),
    ("Take 2 at 0.9 s, score 9,570.", True),
    ("The trunk leans forward at 0.9 s in Take 2.", True),
])
def test_a_caption_never_names_a_score_off_the_page(text: str, kept: bool) -> None:
    facts = _facts()
    facts["takes"][1].update(shown=PAGE, score=78, grade="C")
    got, rejected = history_reel.guard_moments({"moments": [{"take": 2, "at_s": 0.9, "role": "early", "text": text}]}, facts, [2])
    assert bool(got) is kept and (kept or rejected[0]["item"] == "moments[0]")


# ----- review B3, B4: group takes and invited boards -----------------------------------------------------------
@pytest.mark.parametrize("made, caller, keyed", [("", None, True), ("u-a", None, False), ("u-a", "u-b", False), ("u-a", "u-a", True),
                                                 (upload_owner.UNKNOWN, "u-a", False), (None, None, True)])
def test_a_named_group_take_answers_only_to_its_maker(api: Api, monkeypatch: pytest.MonkeyPatch, made: Any, caller: str | None, keyed: bool) -> None:
    monkeypatch.setattr(takes_on, "owner", lambda app, job_id: None)
    monkeypatch.setattr(upload_owner, "people_owner", lambda queue, job_id, kinds=(): made)
    assert takes_on.keyed_by_id(api.app, "ddddddddddd2", caller) is keyed


def test_naming_another_accounts_group_take_removes_nothing(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    stranger = sign_in(api, "dev@example.com")
    cid, job = _create(api)["id"], _job(api, "ddddddddddd3")
    assert post(api, f"api/challenges/{cid}/entries", {"job_id": job, "name": "Ada"})[0] == 201
    monkeypatch.setattr(upload_owner, "people_owner", lambda queue, job_id, kinds=(): "u-ada")
    for cookie in (stranger, None):
        status, _, body = post(api, f"api/challenges/{cid}/remove-my-score", {"jobs": [job]}, cookie=cookie)
        assert status in (200, 401) and (body or {}).get("removed", 0) == 0
    assert len(challenges.get(api.app.state, cid)["entries"]) == 1


def test_an_invited_board_stays_out_of_takes_on(api: Api) -> None:
    grace = sign_in(api, "grace@example.com")
    made = board(api, ("Grace Secret", make_job(api, score=80), 80))
    assert [r["name"] for r in get(api, URL)[2]["shared"]] == ["Grace Secret"]  # public: listed
    _store(api, {**challenges.get(api.app.state, made), "visibility": "invited", "invites": [{"email": "bob@example.com"}]})
    assert get(api, URL)[2]["shared"] == []  # negative: signed out
    assert get(api, URL, cookie=grace)[2]["shared"] == []  # negative: another account
    assert [r["name"] for r in get(api, URL, cookie=sign_in(api, "bob@example.com"))[2]["shared"]] == ["Grace Secret"]  # one on the list still sees it


def test_a_named_group_take_gives_a_board_rank_only_to_its_maker(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    job, stranger = _job(api, "ddddddddddd5"), sign_in(api, "dev@example.com")
    entry = api.app.queue.get(job)["entry_id"]
    rows = [{"name": "Ada", "score": 80, "grade": "B", "job_id": job, "pid": None, "strongest_section": None}]
    challenges.create(api.app.state, entry_id=entry, title="Beat me", creator_name="Ada", kind="friend", entries=rows)
    rank = lambda cookie=None: get(api, f"api/movements/{entry}/boards?jobs={job}", cookie=cookie)[2]["boards"][0]["viewer_rank"]  # noqa: E731
    monkeypatch.setattr(upload_owner, "people_owner", lambda queue, job_id, kinds=(): "")
    assert rank() == 1  # made signed out: the browser that holds the id
    monkeypatch.setattr(upload_owner, "people_owner", lambda queue, job_id, kinds=(): "u-ada")
    assert rank() is None and rank(stranger) is None  # negative


def test_a_passing_draw_fault_keeps_the_try_again(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(muse_fix, "DRAW_ENABLED", True)  # shipped off (release 14; off behaviour: test_muse_fix_r14.py)
    monkeypatch.setattr("part7.muse_fix_measure.available", lambda: True)
    monkeypatch.setattr("part7.muse_fix_measure.reachable", lambda: True)
    job, fake = build_job(tmp_path / "jobs"), Fake()

    def busy(*_a: Any, **_k: Any) -> None:
        raise muse_fix.render.RenderBusy("the frame could not be drawn on")

    monkeypatch.setattr(muse_fix.render, "guide_points", busy)
    assert muse_fix.run(job, consent=True, transport=fake, state=tmp_path / "s")["status"] == "failed"
    assert muse_fix.latest_card(job) == {"status": "failed", "message": muse_fix.NOT_DRAWN} and fake.edits == []


def test_the_account_that_holds_a_take_copies_it_from_another_browser(api: Api) -> None:
    sid, mine = sign_in(api), _follow(api)
    uid = get(api, "api/auth/me", cookie=sid)[2]["user_id"]
    assert post(api, "api/me/claims", {"job_id": mine, "creator_token": "wrong"}, cookie=sid)[0] == 403  # not theirs yet, no token
    auth.identity(api.app).attach(mine, uid, "follow", "lateral-raise", None, "submit")
    auth.identity(api.app).set_consent(uid, "v1", True)
    status, _, body = post(api, "api/me/claims", {"job_id": mine, "creator_token": "wrong"}, cookie=sid)
    assert status == 200 and body["kept"] is True
    other = sign_in(api, "dev@example.com")
    assert post(api, "api/me/claims", {"job_id": mine, "creator_token": "wrong"}, cookie=other)[0] == 403  # negative: another account


@pytest.mark.parametrize("text, off", [("Your score at 0.9 s shows the lean.", False), ("78 points at 0.9 s.", True), ("A C grade here.", True), ("An A grade here.", False)])
def test_the_reel_guard_reads_a_score_in_other_words(text: str, off: bool) -> None:
    assert history_reel._off_the_page(text, {"score": 78, "shown": PAGE}) is off


@pytest.mark.parametrize("text, off", [("Reached 76.1% overall.", False), ("Held at 76 seconds.", False), ("At 1 second, 76 second.", False),
                                       ("The take got 76.", True), ("It got 76 points.", True)])
def test_the_reel_guard_counts_a_raw_score_only_as_the_score(text: str, off: bool) -> None:
    """R4: a figure that only starts with the raw score, or is a time in seconds, does not name it; a closing full stop still does."""
    shown = {"letter": "A", "figures": "9,570", "caption": "of 10,000", "unit": "points", "capped": False}
    assert history_reel._off_the_page(text, {"score": 76, "shown": shown}) is off
