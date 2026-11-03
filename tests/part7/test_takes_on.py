"""`GET api/takes-on/<entry>` over a real server (docs/specs/takes-on-movement.md, TICKET-327 AC-T1 to AC-T9)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from auth_support import authenv, get, sign_in  # noqa: F401
from part7 import auth, challenges, my_reference, takes_on
from support import Api

pytestmark = pytest.mark.usefixtures("authenv")
ENTRY, OTHER_ENTRY = "lateral-raise", "reverse-lunge"
URL = f"api/takes-on/{ENTRY}"


def make_job(api: Api, entry: str = ENTRY, score: float | None = 81, grade: str = "B", at: str | None = None, **fields: Any) -> str:
    made = api.app.queue.submit("follow", lambda ctx: {"result": {}}, entry_id=entry, **fields)
    assert api.app.queue.wait(made["id"], 10)["status"] == "done"
    if at is not None:
        api.app.queue.update(made["id"], finished_at=at)
    if score is not None:
        folder = api.app.queue.job_dir(made["id"]) / "work" / "follower"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "analysis.json").write_text(json.dumps({"score": {"value": score, "grade": grade}}), encoding="utf-8")
    return made["id"]


def own(api: Api, job: str, sid: str, entry: str = ENTRY) -> str:
    uid = get(api, "api/auth/me", cookie=sid)[2]["user_id"]
    auth.identity(api.app).attach(job, uid, "follow", entry, None, "submit")
    return uid


def board(api: Api, *posts: tuple[str, str, float]) -> str:
    """A friend board on ENTRY with `(name, job_id, score)` posts."""
    rows = [{"name": n, "score": s, "grade": "B", "job_id": j, "pid": None, "strongest_section": None} for n, j, s in posts]
    return challenges.create(api.app.state, entry_id=ENTRY, title="Beat me", creator_name=posts[0][0], kind="friend", entries=rows)["id"]


def test_signed_in_lists_my_takes_of_this_movement_newest_first(api: Api) -> None:  # AC-T1
    ada = sign_in(api)
    first, second = make_job(api, score=62, grade="D", at="2026-11-01T10:00:00Z"), make_job(api, score=88, grade="B", at="2026-11-02T10:00:00Z")
    elsewhere = make_job(api, entry=OTHER_ENTRY)
    for job in (first, second):
        own(api, job, ada)
    own(api, elsewhere, ada, OTHER_ENTRY)
    status, head, doc = get(api, URL, cookie=ada)
    assert status == 200 and head["cache-control"] == "no-store" and doc["signed_in"] is True
    rows = doc["mine"]
    assert [r["job_id"] for r in rows] == [second, first]  # newest first; the other movement's take is not here
    assert (rows[0]["score"], rows[0]["grade"], rows[0]["open"], rows[0]["status"]) == (88, "B", "result", "done")
    assert elsewhere not in json.dumps(doc)


def test_signed_out_sees_the_takes_this_browser_names_and_nothing_else(api: Api) -> None:  # AC-T2, AC-T5
    mine, stranger = make_job(api, score=29, grade="F"), make_job(api)
    status, _, doc = get(api, f"{URL}?jobs={mine},not-a-job,{'f' * 12}")
    assert status == 200 and doc["signed_in"] is False
    assert [(r["job_id"], r["score"], r["grade"]) for r in doc["mine"]] == [(mine, 29, "F")]
    assert stranger not in json.dumps(doc) and doc["followers"] is False


def test_another_users_job_named_by_this_browser_is_never_mine(api: Api) -> None:  # AC-T5 negative: the job-owner check
    grace = sign_in(api, "grace@example.com")
    theirs = make_job(api)
    own(api, theirs, grace)
    assert get(api, f"{URL}?jobs={theirs}")[2]["mine"] == []  # signed out
    ada = sign_in(api)
    assert get(api, f"{URL}?jobs={theirs}", cookie=ada)[2]["mine"] == []  # another account
    assert [r["job_id"] for r in get(api, f"{URL}?jobs={theirs}", cookie=grace)[2]["mine"]] == [theirs]  # the owner


def test_a_job_of_another_movement_is_not_listed(api: Api) -> None:
    other = make_job(api, entry=OTHER_ENTRY)
    assert get(api, f"{URL}?jobs={other}")[2]["mine"] == []


def test_shared_lists_board_posts_without_job_ids(api: Api) -> None:  # AC-T3
    posted = make_job(api, score=70, grade="C")
    made = board(api, ("Sam", posted, 70))
    status, _, doc = get(api, URL)
    assert status == 200
    assert [(r["name"], r["score"], r["board"], r["title"]) for r in doc["shared"]] == [("Sam", 70, made, "Beat me")]
    assert posted not in json.dumps(doc["shared"])  # a job id is the poster's private key, never shown


def test_shared_never_lists_a_private_take_or_an_own_reference(api: Api) -> None:  # AC-T4 negatives
    grace = sign_in(api, "grace@example.com")
    private = make_job(api, private=True)
    own_ref = make_job(api, reference={"used": my_reference.OWN, "date": "2026-11-01"})
    kept_ref = make_job(api)
    uid = own(api, kept_ref, grace)
    my_reference.set_reference(api.app.state, uid, ENTRY, kept_ref, "2026-11-01", b"{}", False)
    public = make_job(api)
    board(api, ("Priv", private, 90), ("Ref", own_ref, 91), ("Kept", kept_ref, 92), ("Pub", public, 50))
    names = [r["name"] for r in get(api, URL)[2]["shared"]]
    assert names == ["Pub"]


def test_my_own_board_post_is_mine_not_shared(api: Api) -> None:  # AC-T3
    ada = sign_in(api)
    mine = make_job(api)
    own(api, mine, ada)
    device = make_job(api)
    board(api, ("Ada", mine, 80), ("Me too", device, 60))
    doc = get(api, f"{URL}?jobs={device}", cookie=ada)[2]
    assert doc["shared"] == [] and {r["job_id"] for r in doc["mine"]} == {mine, device}


def test_only_me_movement_is_404_for_everyone_but_its_owner(api: Api) -> None:  # AC-T6
    owner = sign_in(api)
    uid = get(api, "api/auth/me", cookie=owner)[2]["user_id"]
    store = auth.identity(api.app)
    store.attach_entry(ENTRY, uid, "")
    assert store.set_only_me(ENTRY, uid, True)
    other = sign_in(api, "grace@example.com")
    assert get(api, URL)[0] == 404 and get(api, URL, cookie=other)[0] == 404
    status, _, doc = get(api, URL, cookie=owner)
    assert status == 200 and doc["followers"] is True  # AC-T7: the owner's link to the class table


def test_followers_link_is_the_owners_alone(api: Api) -> None:  # AC-T7
    owner = sign_in(api)
    uid = get(api, "api/auth/me", cookie=owner)[2]["user_id"]
    auth.identity(api.app).attach_entry(ENTRY, uid, "")
    assert get(api, URL, cookie=owner)[2]["followers"] is True
    assert get(api, URL, cookie=sign_in(api, "grace@example.com"))[2]["followers"] is False
    assert get(api, URL)[2]["followers"] is False


def test_expired_take_keeps_its_row_without_a_link(api: Api) -> None:
    ada = sign_in(api)
    uid = get(api, "api/auth/me", cookie=ada)[2]["user_id"]
    auth.identity(api.app).attach("abcdefabcdef", uid, "follow", ENTRY, None, "submit")  # its job folder is gone
    rows = get(api, URL, cookie=ada)[2]["mine"]
    assert [(r["job_id"], r["status"], r["open"], r["score"]) for r in rows] == [("abcdefabcdef", "expired", "none", None)]


def test_unknown_or_malformed_movement_and_methods(api: Api) -> None:  # AC-T8
    assert get(api, "api/takes-on/not-in-catalog")[0] == 404
    assert get(api, "api/takes-on/Bad_Entry")[0] == 404
    assert api.request("POST", URL, b"{}", {"Content-Type": "application/json"})[0] == 405


def test_device_ids_are_capped_and_cleaned() -> None:  # AC-T9
    ids = ",".join(f"{i:012x}" for i in range(40))
    assert len(takes_on.device_ids(ids)) == takes_on.DEVICE_MAX
    assert takes_on.device_ids("abc,../../x,ABCDEFABCDEF,aaaaaaaaaaaa,aaaaaaaaaaaa") == ["aaaaaaaaaaaa"]
    assert takes_on.device_ids(None) == []


# ----- review fixes (B2, R1, R2) ------------------------------------------------------------------------------
def _expire(api: Api, job: str) -> None:
    """The job folder is gone (7-day retention); the board keeps its copy of the post."""
    import shutil
    shutil.rmtree(api.app.queue.job_dir(job))
    api.app.queue._jobs.pop(job, None)


def _post_board(api: Api, job: str) -> tuple[int, Any]:
    from test_challenges import VISITOR
    body = {"entry_id": ENTRY, "title": "Beat me", "creator_name": "Sam", "kind": "friend", "job_id": job}
    return api.json("POST", "api/challenges", body, VISITOR)


def _scored_job(api: Api, **fields: Any) -> str:
    from test_challenges import _analysis
    job = make_job(api, **fields)
    folder = api.app.queue.job_dir(job) / "work" / "follower"
    (folder / "analysis.json").write_text(json.dumps(_analysis()), encoding="utf-8")
    return job


def test_posting_a_private_or_own_reference_take_to_a_board_is_refused(api: Api) -> None:  # B2
    before = len(challenges.list_all(api.app.state))
    for job in (_scored_job(api, private=True), _scored_job(api, reference={"used": my_reference.OWN})):
        status, doc = _post_board(api, job)
        assert (status, doc["message"]) == (409, "This take is private to you, so it cannot go on a board.")
    grace = sign_in(api, "grace@example.com")
    kept = _scored_job(api)
    uid = own(api, kept, grace)
    my_reference.set_reference(api.app.state, uid, ENTRY, kept, "2026-11-01", b"{}", False)
    assert _post_board(api, kept)[0] == 409  # the take kept as someone's own reference
    assert len(challenges.list_all(api.app.state)) == before  # negative: no board and no count holds them
    status, doc = _post_board(api, _scored_job(api))
    assert status == 201 and challenges.get(api.app.state, doc["id"])["entries"][0]["private"] is False
    assert "private" not in json.dumps(api.json("GET", f"api/challenges/{doc['id']}")[1])  # the flags stay on disk


def test_an_expired_private_post_never_shows_and_a_checked_public_one_still_does(api: Api) -> None:  # B2
    flagged, legacy, public = make_job(api), make_job(api), make_job(api)
    rows = [{"name": "Priv", "score": 90, "grade": "A", "job_id": flagged, "pid": None, "private": True, "own_reference": False},
            {"name": "Ref", "score": 91, "grade": "A", "job_id": legacy, "pid": None},  # posted before the flags existed
            {"name": "Pub", "score": 50, "grade": "F", "job_id": public, "pid": None, "private": False, "own_reference": False}]
    challenges.create(api.app.state, entry_id=ENTRY, title="T", creator_name="S", kind="friend", entries=rows)
    for job in (flagged, legacy, public):
        _expire(api, job)
    assert [r["name"] for r in get(api, URL)[2]["shared"]] == ["Pub"]


def test_a_failed_owner_lookup_drops_the_browser_take(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:  # R2: fails closed
    sign_in(api)  # the identity store exists
    job = make_job(api)
    assert [r["job_id"] for r in get(api, f"{URL}?jobs={job}")[2]["mine"]] == [job]

    def broken(self: Any, job_id: str) -> Any:
        raise RuntimeError("store fault")
    monkeypatch.setattr(type(auth.identity(api.app)), "owner_of", broken)
    assert get(api, f"{URL}?jobs={job}")[2]["mine"] == []


def test_one_client_is_rate_limited(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:  # R1
    from part7 import takes_on_routes
    monkeypatch.setattr(takes_on_routes, "PER_CLIENT", (2, 60))
    monkeypatch.setattr(takes_on_routes, "_LIMIT", {})
    assert [get(api, URL)[0] for _ in range(2)] == [200, 200]
    status, head, doc = get(api, URL)
    assert (status, head["retry-after"], doc["message"]) == (429, "60", takes_on_routes.MSG_RATE)


def test_shared_stops_at_its_cap(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:  # R1/R4: the cap is applied inside the scan
    monkeypatch.setattr(takes_on, "SHARED_MAX", 2)
    board(api, *[(f"P{i}", make_job(api), 50 + i) for i in range(4)])
    made = []
    real = challenges.public_entry
    monkeypatch.setattr(challenges, "public_entry", lambda e: made.append(e) or real(e))
    assert len(get(api, URL)[2]["shared"]) == 2
    assert len(made) == 2  # a row is built for the shown posts only (the slice after a full scan built all 4)


def test_posts_examined_are_capped_whatever_is_shown(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:  # R3
    monkeypatch.setattr(takes_on, "POSTS_MAX", 3)
    private = [make_job(api, private=True) for _ in range(6)]
    board(api, *[(f"P{i}", job, 50 + i) for i, job in enumerate(private)])
    looked = []
    real = takes_on._listable
    monkeypatch.setattr(takes_on, "_listable", lambda *a: looked.append(a) or real(*a))
    assert get(api, URL)[2]["shared"] == [] and len(looked) == 3


# ----- the board's own views apply the same rule (ADR-0019) ---------------------------------------------------
def test_a_post_later_kept_as_my_reference_leaves_the_board_view_and_its_summary(api: Api) -> None:  # R1
    grace = sign_in(api, "grace@example.com")
    job = _scored_job(api)
    uid = own(api, job, grace)
    status, doc = _post_board(api, job)
    assert status == 201
    cid = doc["id"]
    listed = lambda: next(c for c in api.json("GET", f"api/challenges?entry_id={ENTRY}")[1]["challenges"] if c["id"] == cid)  # noqa: E731
    assert len(api.json("GET", f"api/challenges/{cid}")[1]["entries"]) == 1 and listed()["entry_count"] == 1
    my_reference.set_reference(api.app.state, uid, ENTRY, job, "2026-11-01", b"{}", False)  # kept as her reference after posting
    assert api.json("GET", f"api/challenges/{cid}")[1]["entries"] == []
    assert (listed()["entry_count"], listed()["leader"]) == (0, None)


def test_legacy_private_and_own_reference_posts_leave_both_views_while_the_job_is_there(api: Api) -> None:  # R2
    private, own_ref, public = make_job(api, private=True), make_job(api, reference={"used": my_reference.OWN}), make_job(api)
    cid = board(api, ("Priv", private, 99), ("Ref", own_ref, 98), ("Pub", public, 50))  # rows with no flags: posted before them
    assert [e["name"] for e in api.json("GET", f"api/challenges/{cid}")[1]["entries"]] == ["Pub"]
    row = next(c for c in api.json("GET", f"api/challenges?entry_id={ENTRY}")[1]["challenges"] if c["id"] == cid)
    assert row["entry_count"] == 1 and row["leader"]["name"] == "Pub"


def test_a_store_fault_on_board_post_is_503_not_a_privacy_refusal(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:  # R7
    sign_in(api)
    job = _scored_job(api)

    def broken(self: Any, job_id: str) -> Any:
        raise RuntimeError("store fault")
    monkeypatch.setattr(type(auth.identity(api.app)), "owner_of", broken)
    status, doc = _post_board(api, job)
    assert (status, doc["message"]) == (503, "Boards are not available right now. Try again in a minute.")
