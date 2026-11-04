"""The board lists over a real server (docs/specs/board-discovery.md, TICKET-394 AC-S1 to AC-S9)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from auth_support import EMAIL, authenv, get, sign_in  # noqa: F401
from part7 import auth, board_discovery, challenges
from support import Api, published

pytestmark = pytest.mark.usefixtures("authenv")
ENTRY, OTHER = "lateral-raise", "reverse-lunge"
JOB_A, JOB_B, JOB_C = "a" * 12, "b" * 12, "c" * 12
CARD_KEYS = {"id", "title", "kind", "visibility", "ends_at", "ended", "entries", "viewer_rank", "top", "url", "creator", "mine"}


def row(name: str, score: float, job: str, shown: Any = None) -> dict[str, Any]:
    return {"name": name, "score": score, "grade": "B", "job_id": job, "pid": None, "strongest_section": None,
            **({"shown": shown} if shown else {})}


def make(api: Api, *posts: dict[str, Any], entry: str = ENTRY, title: str = "Beat me", **over: Any) -> dict[str, Any]:
    visibility = over.pop("visibility", None)
    doc = challenges.create(api.app.state, entry_id=entry, title=title, creator_name="Maker", kind="friend", entries=list(posts), **over)
    if visibility:  # the visibility lane's field; written as the model will store it
        doc = {**challenges.get(api.app.state, doc["id"]), "visibility": visibility}
        challenges._write(api.app.state, doc)
    return doc


def boards(api: Api, path: str, cookie: str | None = None) -> list[dict[str, Any]]:
    status, _, doc = get(api, path, cookie=cookie)
    assert status == 200, doc
    return doc["boards"]


def test_a_movement_lists_its_boards_with_the_card_shape_and_nothing_private(api: Api) -> None:  # AC-S1, AC-S2
    shown = {"letter": "B", "figures": "9,249", "caption": "of 12,160", "unit": "points", "capped": False}
    made = make(api, row("Mo", 84, JOB_A, shown), row("Cat", 70, JOB_B), owner="u-owner@example.com")
    make(api, row("Elsewhere", 50, JOB_C), entry=OTHER, title="Other movement")
    cards = boards(api, f"api/movements/{ENTRY}/boards")
    assert [c["id"] for c in cards] == [made["id"]]
    card = cards[0]
    assert set(card) == CARD_KEYS
    assert (card["entries"], card["kind"], card["visibility"], card["ended"], card["viewer_rank"]) == (2, "friend", "public", False, None)
    assert card["top"][0] == {"name": "Mo", "score_label": "9,249 points of 12,160"}
    assert card["top"][1] == {"name": "Cat", "score_label": "70"}
    assert card["url"] == f"#/challenge/{made['id']}"
    raw = json.dumps(cards)
    for secret in (JOB_A, JOB_B, "job_id", "pid", "owner", "visitor", "@"):
        assert secret not in raw, secret  # negative: no email, no job id, no owner


def test_a_private_board_never_appears_on_any_list_or_for_anyone_but_its_maker(api: Api) -> None:  # AC-S3
    ada = sign_in(api)
    uid = get(api, "api/auth/me", cookie=ada)[2]["user_id"]
    other = sign_in(api, "grace@example.com")
    hidden = make(api, row("Quiet", 60, JOB_A), title="Private one", visibility="invited", owner=uid)
    shown = make(api, row("Loud", 61, JOB_B), title="Public one")
    for path in (f"api/movements/{ENTRY}/boards", "api/boards", "api/me/boards"):
        for cookie in (None, other):
            ids = [c["id"] for c in boards(api, f"{path}?jobs={JOB_A}", cookie)]
            assert hidden["id"] not in ids, (path, cookie)  # negative: not signed out, not another account, not even with its job named
    assert {c["id"] for c in boards(api, f"api/movements/{ENTRY}/boards", ada)} == {hidden["id"], shown["id"]}  # the maker still finds it


def test_a_private_movement_answers_as_a_missing_one(api: Api) -> None:  # AC-S3
    owner = sign_in(api)
    uid = get(api, "api/auth/me", cookie=owner)[2]["user_id"]
    store = auth.identity(api.app)
    store.attach_entry(ENTRY, uid, "")
    assert store.set_only_me(ENTRY, uid, True)
    make(api, row("Mo", 80, JOB_A))
    other = sign_in(api, "grace@example.com")
    assert get(api, f"api/movements/{ENTRY}/boards")[0] == 404
    assert get(api, f"api/movements/{ENTRY}/boards", cookie=other)[0] == 404
    assert get(api, "api/movements/no-such-movement/boards")[0] == 404
    assert boards(api, "api/boards") == [] and boards(api, "api/boards", other) == []  # home leaves it out too
    assert len(boards(api, f"api/movements/{ENTRY}/boards", owner)) == 1


def test_ended_boards_are_listed_after_open_ones(api: Api) -> None:  # AC-S4
    old = make(api, row("Zed", 66, JOB_A), title="Old news")
    challenges.close(api.app.state, old["id"])
    busy = make(api, row("A", 70, JOB_B), row("B", 71, JOB_C), title="Busy")
    quiet = make(api, row("C", 40, "d" * 12), title="Quiet")
    cards = boards(api, f"api/movements/{ENTRY}/boards")
    assert [c["id"] for c in cards] == [busy["id"], quiet["id"], old["id"]]
    assert [c["ended"] for c in cards] == [False, False, True]


def test_the_viewers_rank_comes_from_their_account_or_the_jobs_their_browser_names(api: Api) -> None:  # AC-S5
    ada = sign_in(api)
    uid = get(api, "api/auth/me", cookie=ada)[2]["user_id"]
    auth.identity(api.app).attach(JOB_B, uid, "follow", ENTRY, None, "submit")
    made = make(api, row("Top", 90, JOB_A), row("Me", 70, JOB_B), row("Low", 40, JOB_C))
    assert boards(api, f"api/movements/{ENTRY}/boards", ada)[0]["viewer_rank"] == 2
    assert boards(api, f"api/movements/{ENTRY}/boards")[0]["viewer_rank"] is None  # signed out, nothing named
    assert boards(api, f"api/movements/{ENTRY}/boards?jobs={JOB_C}")[0]["viewer_rank"] == 3  # an unowned take this browser sent
    stranger = boards(api, f"api/movements/{ENTRY}/boards?jobs={JOB_B}")[0]  # negative: a job another account owns is not a browser's word
    assert stranger["viewer_rank"] is None and stranger["id"] == made["id"]


def test_my_boards_holds_only_boards_the_caller_made_or_is_on(api: Api) -> None:  # AC-S6
    ada = sign_in(api)
    uid = get(api, "api/auth/me", cookie=ada)[2]["user_id"]
    mine = make(api, row("Me", 70, JOB_A), title="Made by me", owner=uid)
    on = make(api, row("Cat", 80, JOB_B), row("Me too", 70, JOB_C), title="I am on it")
    make(api, row("Other", 50, "d" * 12), title="Not mine")
    assert get(api, "api/me/boards")[2]["boards"] == []  # signed out and no jobs named
    got = {c["id"]: c["viewer_rank"] for c in boards(api, f"api/me/boards?jobs={JOB_C}")}
    assert got == {on["id"]: 2}
    assert {c["id"] for c in boards(api, "api/me/boards", ada)} == {mine["id"]}


def test_a_capped_take_never_heads_a_card_and_a_sponsored_board_stays_off_while_prize_boards_are_off(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:  # AC-S7
    capped = {"letter": "F", "figures": "37", "caption": "score out of 100", "unit": "score", "capped": True}
    made = make(api, row("Capped", 99, JOB_A, capped), row("Fair", 60, JOB_B))
    assert [t["name"] for t in boards(api, f"api/movements/{ENTRY}/boards")[0]["top"]] == ["Fair"]
    assert made["id"]
    challenges.create(api.app.state, entry_id=ENTRY, title="Sponsor", creator_name="S", kind="sponsored", allow_sponsored=True,
                      sponsor={"name": "N", "tagline": "t", "url": "https://example.com", "prize": "p", "rules_url": "https://example.com/rules"}, ends_at="2999-12-01T00:00:00Z")
    assert {c["kind"] for c in boards(api, f"api/movements/{ENTRY}/boards")} == {"friend", "sponsored"}  # on outside prod
    monkeypatch.setenv("FIRM_ENV", "prod")
    monkeypatch.setenv("SIMON7_POLICY_PRIZE_BOARDS", "off")  # prod has prize boards on from release 7 (AC-CH-P1); the switch turns them off
    assert all(c["kind"] != "sponsored" for c in boards(api, f"api/movements/{ENTRY}/boards"))


def test_the_judge_view_leaves_test_boards_out(api: Api) -> None:  # AC-S8
    published(api.app.state, "verify-2026-10-31t06-23-06z-317d3534")
    make(api, row("Real", 70, JOB_A))
    make(api, row("Test", 70, JOB_B), entry="verify-2026-10-31t06-23-06z-317d3534", title="Verify")
    assert {c["title"] for c in boards(api, "api/boards")} == {"Beat me", "Verify"}
    assert [c["title"] for c in boards(api, "api/boards?view=judge")] == ["Beat me"]


def test_viewable_is_the_one_access_check(api: Api) -> None:  # AC-S3: the visibility lane replaces this one function
    class Viewer:
        app = api.app
        headers: dict[str, str] = {}

    doc = make(api, row("Mo", 80, JOB_A))
    assert board_discovery._viewable(challenges.get(api.app.state, doc["id"]), Viewer()) is True
    assert board_discovery._viewable({**doc, "visibility": "invited", "owner": "someone"}, Viewer()) is False


@pytest.mark.parametrize("method", ["POST", "DELETE"])
def test_the_lists_are_read_only(api: Api, method: str) -> None:  # AC-S9
    status, _ = api.json(method, f"api/movements/{ENTRY}/boards", {}, {"Cf-Connecting-Ip": "198.51.100.7"})
    assert status == 405


# ----- the person's own controls (TICKET-431 rows 13, 16, 19) ---------------------------------------------------------
def post(api: Api, path: str, doc: Any = None, cookie: str | None = None) -> tuple[int, Any]:
    from auth_support import post as signed_post

    status, _, body = signed_post(api, path, doc if doc is not None else {}, cookie=cookie)
    return status, body


def test_the_board_marks_you_and_names_its_maker_controls(api: Api) -> None:  # AC-S10
    ada = sign_in(api)
    uid = get(api, "api/auth/me", cookie=ada)[2]["user_id"]
    made = make(api, {**row("Ada", 70, JOB_A), "owner": uid}, row("Other", 90, JOB_B), owner=uid)
    mine = get(api, f"api/challenges/{made['id']}", cookie=ada)[2]
    assert [(e["name"], e["you"]) for e in mine["entries"]] == [("Other", False), ("Ada", True)] and mine["can_manage"] is True
    out = get(api, f"api/challenges/{made['id']}")[2]
    assert [e["you"] for e in out["entries"]] == [False, False] and out["can_manage"] is False  # negative: signed out
    named = get(api, f"api/challenges/{made['id']}?jobs={JOB_B}")[2]
    assert [e["you"] for e in named["entries"]] == [True, False]  # an unowned take this browser names
    assert JOB_A not in json.dumps(mine) and "\"owner\":" not in json.dumps(mine)  # the role word "owner" is fine; the key is not
    card = boards(api, f"api/movements/{ENTRY}/boards", ada)[0]
    assert (card["mine"], card["creator"], card["viewer_rank"]) == (True, "Maker", 2)


def test_remove_my_score_takes_only_the_callers_rows(api: Api) -> None:  # AC-S11
    ada = sign_in(api)
    uid = get(api, "api/auth/me", cookie=ada)[2]["user_id"]
    other = sign_in(api, "grace@example.com")
    made = make(api, {**row("Ada", 70, JOB_A), "owner": uid}, row("Other", 90, JOB_B), row("Dev", 50, JOB_C))
    assert post(api, f"api/challenges/{made['id']}/remove-my-score", cookie=other) == (200, {"removed": 0})  # negative: not theirs
    assert post(api, f"api/challenges/{made['id']}/remove-my-score", {"jobs": [JOB_C]}) == (200, {"removed": 1})  # an unowned take this browser names
    assert post(api, f"api/challenges/{made['id']}/remove-my-score", cookie=ada) == (200, {"removed": 1})
    left = get(api, f"api/challenges/{made['id']}")[2]["entries"]
    assert [e["name"] for e in left] == ["Other"]
    assert post(api, "api/challenges/nosuchboard1/remove-my-score")[0] == 404


def test_only_the_maker_closes_or_deletes_a_board(api: Api) -> None:  # AC-S12
    ada = sign_in(api)
    uid = get(api, "api/auth/me", cookie=ada)[2]["user_id"]
    other = sign_in(api, "grace@example.com")
    made = make(api, row("Ada", 70, JOB_A), owner=uid)
    for action in ("close", "delete"):
        assert post(api, f"api/challenges/{made['id']}/{action}", cookie=other)[0] == 403  # negative: another account
        assert post(api, f"api/challenges/{made['id']}/{action}")[0] == 403  # negative: signed out
    assert post(api, f"api/challenges/{made['id']}/close", cookie=ada) == (200, {"closed": True})
    assert get(api, f"api/challenges/{made['id']}")[2]["ended"] is True
    assert [c["ended"] for c in boards(api, f"api/movements/{ENTRY}/boards")] == [True]  # still listed, apart
    assert post(api, f"api/challenges/{made['id']}/delete", cookie=ada) == (200, {"deleted": True})
    assert get(api, f"api/challenges/{made['id']}")[0] == 404 and boards(api, f"api/movements/{ENTRY}/boards") == []


def test_an_end_date_from_the_web_says_why(api: Api) -> None:  # AC-S13
    status, doc = api.json("POST", "api/challenges", {"entry_id": ENTRY, "title": "T", "creator_name": "S", "kind": "friend", "ends_at": "2030-01-01T00:00:00Z"},
                           {"Cf-Connecting-Ip": "198.51.100.7"})
    assert status == 400 and "closes it" in doc["message"] and "operator" not in doc["message"]


# ----- the link preview (TICKET-431 row 22) -----------------------------------------------------------------------------
def preview(api: Api, board_id: str) -> tuple[int, str]:
    status, _, body = api.request("GET", f"c/{board_id}")
    return status, body.decode()


def test_a_public_board_link_carries_its_preview_and_still_opens_the_app(api: Api) -> None:  # AC-P1, AC-P2
    made = make(api, row("Mo", 84, JOB_A, {"letter": "B", "figures": "9,249", "caption": "of 12,160", "unit": "points", "capped": False}),
                row("Cat", 70, JOB_B), title="Beat my <Squat> & co")
    status, page = preview(api, made["id"])
    assert status == 200
    assert 'property="og:title" content="Beat my &lt;Squat&gt; &amp; co"' in page  # escaped
    assert "2 people are on this leaderboard. Top score 9,249 points of 12,160. Can you beat it?" in page
    assert f'content="http://127.0.0.1:{api.port}{api.app.base}icons/og-image.png"' in page  # absolute image
    assert f'url={api.app.base}#/challenge/{made["id"]}' in page and "Open the leaderboard in Simon" in page  # on to the app
    assert "Cat" not in page  # no entrant names in the tags
    for secret in (JOB_A, JOB_B, "Maker"):
        assert secret not in page


def test_a_private_missing_or_hidden_board_gets_the_same_generic_preview(api: Api) -> None:  # AC-P3
    ada = sign_in(api)
    uid = get(api, "api/auth/me", cookie=ada)[2]["user_id"]
    hidden = make(api, row("Quiet", 60, JOB_A), title="Secret club", visibility="invited", owner=uid)
    for board_id in (hidden["id"], "nosuchboard"):
        status, page = preview(api, board_id)
        assert status == 200
        assert 'og:title" content="Simon"' in page and "Secret club" not in page and "leaderboard." not in page.split("<title>")[1].split("</title>")[0]
        assert "people are on this leaderboard" not in page and "Quiet" not in page
        assert f"#/challenge/{board_id}" in page  # the link still goes to the app, which asks who they are
    assert preview(api, hidden["id"])[1].replace(hidden["id"], "X") == preview(api, "nosuchboard")[1].replace("nosuchboard", "X")


def test_a_board_on_a_private_movement_gets_the_generic_preview(api: Api) -> None:  # AC-P3
    owner = sign_in(api)
    uid = get(api, "api/auth/me", cookie=owner)[2]["user_id"]
    store = auth.identity(api.app)
    store.attach_entry(ENTRY, uid, "")
    assert store.set_only_me(ENTRY, uid, True)
    made = make(api, row("Mo", 80, JOB_A), title="Hidden movement board")
    page = preview(api, made["id"])[1]
    assert "Hidden movement board" not in page and 'og:title" content="Simon"' in page


def test_only_c_slash_an_id_is_a_preview(api: Api) -> None:  # AC-P4
    assert api.request("GET", "c/short")[0] == 404
    assert api.request("POST", "c/abcdefghijk")[0] == 405


def test_a_stored_address_stays_masked_on_a_card() -> None:
    """Review of release 10: the card read raw names where `challenges.view` masks an old board's stored address."""
    doc = {"id": "abcdefgh1", "title": "ann@example.com board", "kind": "friend", "creator_name": "ann@example.com",
           "entries": [{"name": "bob@example.com", "score": 50, "grade": "C", "job_id": "cccccccccccc", "created_at": "2026-11-01T00:00:00Z"}]}
    card = board_discovery._card(doc, lambda _e: True, set())
    assert "@" not in json.dumps(card)
    assert card["title"] == "Challenge" and card["creator"] == "Hidden name" and card["top"][0]["name"] == "Hidden name"
