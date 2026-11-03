"""Ask the trainer for a note over a real server (docs/specs/notes.md AC-N1 to AC-N10; TICKET-237)."""

from __future__ import annotations

import json
import sqlite3
import time
from types import SimpleNamespace
from typing import Any

import pytest

from auth_support import authenv, get, origin, post, sign_in  # noqa: F401
from part7 import auth, history_store, identity, notes
from support import Api

pytestmark = pytest.mark.usefixtures("authenv")
ENTRY = "lateral-raise"
TRAINER, FOLLOWER, THIRD = "tina@example.com", "fred@example.com", "theo@example.com"
FAULTS = [{"measure": "elbow", "side": "left", "text_timed": "Your arm drifts forward at 2.4 s", "at_s": 2.4},
          {"measure": "tempo", "text": "A little fast near the end", "at_s": 7.1}]
ANALYSIS = {"score": {"value": 81, "grade": "B", "timeline": []}, "faults": FAULTS}
CLIP_BYTES = b"not a real mp4 but served as one"


def store(api: Api) -> identity.IdentityStore:
    return auth.identity(api.app)


def make_job(api: Api, *, clip: bool = True, private: bool = False, entry: str = ENTRY, **extra: Any) -> str:
    def fn(ctx: Any) -> dict[str, Any]:
        (ctx.work / "follower").mkdir()
        (ctx.work / "follower" / "analysis.json").write_text(json.dumps(ANALYSIS))
        if clip:
            (ctx.work / "video.mp4").write_bytes(CLIP_BYTES)
        return {"result": {}}

    made = api.app.queue.submit("follow", fn, entry_id=entry, **({"private": True} if private else {}), **extra)
    assert api.app.queue.wait(made["id"], 10)["status"] == "done"
    return made["id"]


def claimed(api: Api, sid: str, **more: Any) -> str:
    job = make_job(api, **more)
    assert post(api, "api/me/claims", {"job_id": job}, cookie=sid)[0] == 200
    return job


def send(api: Api, path: str, doc: Any, sid: str | None, method: str = "POST") -> tuple[int, Any]:
    hdr = {"Content-Type": "application/json", "Origin": origin(api)}
    if sid:
        hdr["Cookie"] = f"{auth.COOKIE}={sid}"
    status, _, data = api.request(method, path, json.dumps(doc).encode(), hdr)
    return status, (json.loads(data) if data else None)


class World:
    """A trainer who owns the movement, a follower with one kept take, and a third account."""

    def __init__(self, api: Api) -> None:
        self.api = api
        self.trainer, self.follower, self.third = (sign_in(api, e) for e in (TRAINER, FOLLOWER, THIRD))
        self.store = store(api)
        self.tid, self.fid, self.xid = (self.store.session_user(s) for s in (self.trainer, self.follower, self.third))
        self.store.attach_entry(ENTRY, self.tid)
        self.job = claimed(api, self.follower)

    def ask(self, include: Any = "default", job: str | None = None, sid: str | None = None) -> tuple[int, Any]:
        body: dict[str, Any] = {"confirm": True}
        if include != "default":
            body["include"] = include
        return send(self.api, f"api/me/takes/{job or self.job}/ask-trainer", body, sid or self.follower)

    def request_id(self) -> str:
        [row] = get(self.api, "api/me/note-requests", cookie=self.trainer)[2]["requests"]
        return row["id"]

    def answer(self, note: str = "Keep the elbow soft.", at_s: Any = None, sid: str | None = None, rid: str | None = None) -> tuple[int, Any]:
        doc: dict[str, Any] = {"note": note}
        if at_s is not None:
            doc["at_s"] = at_s
        return send(self.api, f"api/me/note-requests/{rid or self.request_id()}/answer", doc, sid or self.trainer)

    def view(self, job: str | None = None) -> tuple[int, Any]:
        status, _, doc = get(self.api, f"api/me/takes/{job or self.job}/ask-trainer", cookie=self.follower)
        return status, doc

    def rows(self) -> list[sqlite3.Row]:
        return self.store.fetch("SELECT * FROM note_requests")


@pytest.fixture()
def world(api: Api) -> World:
    return World(api)


# ----- AC-N1 data and migration ------------------------------------------------------------------------
def legacy(tmp_path: Any) -> tuple[Any, sqlite3.Connection]:
    path = identity.db_path(tmp_path)
    path.parent.mkdir()
    db = sqlite3.connect(str(path), isolation_level=None)
    db.executescript(identity._SCHEMA)
    db.execute("INSERT INTO users (user_id, email, created_at, last_seen_at) VALUES ('u-1', 'a@example.com', 1, 1)")
    return path, db


def test_migration_copies_first_is_idempotent_and_additive(tmp_path: Any) -> None:  # AC-N1
    path, db = legacy(tmp_path)
    before = db.execute("SELECT * FROM users").fetchall()
    assert notes.migrate(db, path) is True
    backup = path.with_name(notes.BACKUP_NAME)
    assert backup.is_file() and oct(backup.stat().st_mode & 0o777) == "0o600"
    copy = sqlite3.connect(str(backup))
    assert copy.execute("SELECT name FROM sqlite_master WHERE name = 'note_requests'").fetchone() is None  # the copy is the old shape
    assert copy.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1
    assert notes.migrate(db, path) is False  # second run does nothing
    assert db.execute("SELECT * FROM users").fetchall() == before  # no other table is touched
    cols = [r[1] for r in db.execute("PRAGMA table_info(note_requests)")]
    assert cols[:11] == ["id", "job_id", "entry_id", "follower_id", "trainer_id", "include", "state", "asked_utc", "answered_utc", "note", "note_at_s"]


def test_migration_refuses_when_the_copy_fails_and_changes_nothing(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:  # AC-N1
    path, db = legacy(tmp_path)

    def broken(*_: Any, **__: Any) -> None:
        raise sqlite3.OperationalError("disk full")

    monkeypatch.setattr(notes, "sqlite3", SimpleNamespace(connect=broken, Error=sqlite3.Error))
    with pytest.raises(RuntimeError, match="refused"):
        notes.migrate(db, path)
    assert db.execute("SELECT name FROM sqlite_master WHERE name = 'note_requests'").fetchone() is None
    assert not path.with_name(notes.BACKUP_NAME).exists()


def test_a_fresh_database_needs_no_copy(tmp_path: Any) -> None:  # AC-N1
    path = identity.db_path(tmp_path)
    path.parent.mkdir()
    db = sqlite3.connect(str(path), isolation_level=None)
    db.executescript(identity._SCHEMA)
    assert notes.migrate(db, path) is True and not path.with_name(notes.BACKUP_NAME).exists()


def test_one_open_request_per_take(world: World) -> None:  # AC-N1
    assert world.ask()[0] == 201
    status, doc = world.ask()
    assert status == 409 and "already has a request" in doc["message"]
    with pytest.raises(sqlite3.IntegrityError):  # the index backs the rule even for a direct write
        world.store.write("INSERT INTO note_requests (id, job_id, entry_id, follower_id, trainer_id, state, asked_utc) "
                          "VALUES ('x1', ?, ?, 'a', 'b', 'asked', 't')", (world.job, ENTRY))
    assert len(world.rows()) == 1


# ----- AC-N2 who may ask ------------------------------------------------------------------------------------
def test_who_may_ask_the_owner_of_a_finished_take_of_a_trainers_movement(world: World) -> None:  # AC-N2
    status, doc = world.view()
    assert status == 200 and doc["can_ask"] is True and doc["request"] is None and doc["has_clip"] is True
    assert doc["include_default"] == ["score", "faults"]
    assert world.ask()[0] == 201


def test_ask_refused_for_everything_else_with_404_and_no_row(world: World) -> None:  # AC-N2
    api = world.api
    stranger = claimed(api, world.third)  # another account's take
    anonymous = make_job(api)  # nobody owns it: the job id alone is not consent
    private = claimed(api, world.follower, private=True)
    unattributed = claimed(api, world.follower, entry="empty")  # an entry with no owner row
    own = claimed(api, world.trainer)  # the trainer's own take of their own movement
    hidden = claimed(api, world.follower)
    world.store.set_only_me(ENTRY, world.tid, True)
    cases = [(world.follower, stranger), (world.follower, anonymous), (world.follower, private), (world.follower, unattributed),
             (world.trainer, own), (world.follower, hidden), (world.follower, "0" * 12), (world.follower, "not-a-job")]
    for sid, job in cases:
        assert send(api, f"api/me/takes/{job}/ask-trainer", {"confirm": True}, sid)[0] == 404, job
        assert get(api, f"api/me/takes/{job}/ask-trainer", cookie=sid)[0] == 404, job
    assert world.rows() == []
    assert send(api, f"api/me/takes/{world.job}/ask-trainer", {"confirm": True}, None)[0] == 401  # signed out
    assert get(api, f"api/me/takes/{world.job}/ask-trainer")[0] == 401


def test_a_take_of_an_entry_made_signed_out_cannot_be_sent(world: World) -> None:  # AC-N2
    world.store.write("UPDATE entries SET author_state = 'unattributed' WHERE entry_id = ?", (ENTRY,))
    assert world.view()[0] == 404 and world.ask()[0] == 404


# ----- AC-N3 include and the name line ---------------------------------------------------------------------------
def test_include_defaults_to_score_and_faults_and_clip_is_off(world: World) -> None:
    status, doc = world.ask()
    assert status == 201 and doc["request"]["include"] == ["score", "faults"]
    assert doc["request"]["state"] == "asked" and doc["request"]["from"] == {"name": None}


def test_include_is_a_subset_in_fixed_order_and_bad_values_are_refused(world: World) -> None:  # AC-N3
    for bad in (["pain"], "score", ["score", "score"], [1], {"score": True}):
        assert world.ask(bad)[0] == 400, bad
    assert world.rows() == []
    status, doc = world.ask(["clip", "score"])
    assert status == 201 and doc["request"]["include"] == ["score", "clip"]


def test_a_clip_cannot_be_included_when_the_take_has_none(world: World) -> None:  # AC-N3
    job = claimed(world.api, world.follower, clip=False)
    assert world.view(job)[1]["has_clip"] is False
    status, doc = world.ask(["clip"], job)
    assert status == 400 and "no clip" in doc["message"]
    assert world.ask(["score"], job)[0] == 201


def test_ask_needs_confirm_and_the_same_origin_guard(world: World) -> None:  # AC-N3
    path = f"api/me/takes/{world.job}/ask-trainer"
    assert send(world.api, path, {"include": ["score"]}, world.follower)[0] == 400
    assert send(world.api, path, {"confirm": "yes"}, world.follower)[0] == 400
    assert post(world.api, path, {"confirm": True}, cookie=world.follower, guard=False)[0] == 403
    assert world.rows() == []


def test_shown_as_is_the_public_name_only_when_the_profile_shows_it(world: World) -> None:  # AC-N3
    assert world.view()[1]["shown_as"] is None
    send(world.api, "api/me/profile", {"public_name": "Fred F", "show_name": False}, world.follower, "PUT")
    assert world.view()[1]["shown_as"] is None  # a name that is not shown stays hidden
    send(world.api, "api/me/profile", {"show_name": True}, world.follower, "PUT")
    assert world.view()[1]["shown_as"] == "Fred F"
    world.ask()
    [row] = get(world.api, "api/me/note-requests", cookie=world.trainer)[2]["requests"]
    assert row["from"] == {"name": "Fred F"}


# ----- AC-N4 trainer side ----------------------------------------------------------------------------------------
def test_trainer_sees_only_the_included_parts_of_that_one_take(world: World) -> None:  # AC-N4
    other = claimed(world.api, world.follower)  # a second take that was not sent
    world.ask(["score"])
    status, _, listing = get(world.api, "api/me/note-requests", cookie=world.trainer)
    [row] = listing["requests"]
    assert status == 200 and set(row) == {"id", "movement", "asked_utc", "state", "from"} and row["state"] == "asked"
    status, _, doc = get(world.api, f"api/me/note-requests/{row['id']}", cookie=world.trainer)
    assert status == 200 and {k: v for k, v in doc["score"].items() if k != "shown"} == {"value": 81, "grade": "B"}
    assert (doc["score"]["shown"]["letter"], doc["score"]["shown"]["figures"]) == ("B", "81")  # one-letter.md
    assert doc["faults"] is None and doc["clip"] is None  # negative: not ticked, not sent
    text = json.dumps([listing, doc])
    for secret in (world.job, other, world.fid, world.tid, FOLLOWER, TRAINER, "example.com"):
        assert secret not in text, secret


def test_trainer_sees_faults_with_their_times_and_a_signed_clip_when_included(world: World) -> None:  # AC-N4
    world.ask(["score", "faults", "clip"])
    doc = get(world.api, f"api/me/note-requests/{world.request_id()}", cookie=world.trainer)[2]
    assert doc["faults"] == [{"text": "Your arm drifts forward at 2.4 s", "at_s": 2.4}, {"text": "A little fast near the end", "at_s": 7.1}]
    assert doc["clip"].startswith(f"api/me/note-requests/{doc['id']}/clip.mp4?exp=")
    status, head, body = world.api.request("GET", doc["clip"], None, {"Cookie": f"{auth.COOKIE}={world.trainer}"})
    assert status == 200 and body == CLIP_BYTES and head["content-type"] == "video/mp4"


def test_the_clip_url_needs_a_fresh_signature_and_the_trainers_session(world: World) -> None:  # AC-N4
    world.ask(["clip"])
    rid = world.request_id()
    url = get(world.api, f"api/me/note-requests/{rid}", cookie=world.trainer)[2]["clip"]
    cookie = lambda sid: {"Cookie": f"{auth.COOKIE}={sid}"}  # noqa: E731
    get_clip = lambda u, sid: world.api.request("GET", u, None, cookie(sid) if sid else {})[0]  # noqa: E731
    assert get_clip(url, world.trainer) == 200
    assert get_clip(url, world.follower) == 404 and get_clip(url, world.third) == 404 and get_clip(url, None) == 401  # a copied URL is useless
    assert get_clip(url.replace("sig=", "sig=0"), world.trainer) == 404
    assert get_clip(url.split("?")[0], world.trainer) == 404  # no signature
    real = auth.CLOCK
    try:
        auth.CLOCK = lambda: time.time() + 61  # the URL lives 60 seconds
        assert get_clip(url, world.trainer) == 404
    finally:
        auth.CLOCK = real


def test_no_clip_url_and_no_clip_route_when_the_clip_was_not_included(world: World) -> None:  # AC-N4
    world.ask(["score", "faults"])
    rid = world.request_id()
    assert get(world.api, f"api/me/note-requests/{rid}", cookie=world.trainer)[2]["clip"] is None
    exp, sig = notes.sign_clip(world.store, rid)  # even a correctly signed URL gives nothing
    assert world.api.request("GET", f"api/me/note-requests/{rid}/clip.mp4?exp={exp}&sig={sig}", None,
                             {"Cookie": f"{auth.COOKIE}={world.trainer}"})[0] == 404


def test_a_third_account_and_signed_out_see_nothing_of_the_request(world: World) -> None:  # AC-N4
    world.ask(["score", "faults", "clip"])
    rid = world.request_id()
    assert get(world.api, f"api/me/note-requests/{rid}", cookie=world.third)[0] == 404
    assert get(world.api, f"api/me/note-requests/{rid}", cookie=world.follower)[0] == 404  # not even the asker
    assert get(world.api, "api/me/note-requests", cookie=world.third)[2] == {"requests": []}
    assert get(world.api, f"api/me/note-requests/{rid}")[0] == 401
    assert send(world.api, f"api/me/note-requests/{rid}/answer", {"note": "Hi"}, world.third)[0] == 404
    assert send(world.api, f"api/me/note-requests/{rid}/decline", {}, world.third)[0] == 404
    assert send(world.api, f"api/me/note-requests/{rid}/answer", {"note": "Hi"}, None)[0] == 401
    assert get(world.api, "api/me/note-requests/nope")[0] == 401 and get(world.api, "api/me/note-requests/x", cookie=world.trainer)[0] == 404


def test_once_closed_the_trainer_keeps_the_note_but_not_the_take(world: World) -> None:  # AC-N4
    world.ask(["score", "faults", "clip"])
    assert world.answer("Looks good.")[0] == 200
    doc = get(world.api, f"api/me/note-requests/{world.request_id()}", cookie=world.trainer)[2]
    assert doc["state"] == "answered" and doc["answer"]["note"] == "Looks good."
    assert doc["score"] is None and doc["faults"] is None and doc["clip"] is None


def test_a_take_that_is_no_longer_kept_shows_the_request_without_content(world: World) -> None:  # AC-N4
    world.ask()
    (world.api.app.queue.job_dir(world.job) / "work" / "follower" / "analysis.json").unlink()
    doc = get(world.api, f"api/me/note-requests/{world.request_id()}", cookie=world.trainer)[2]
    assert doc["available"] is False and doc["score"] is None


# ----- AC-N5 answer and decline --------------------------------------------------------------------------------------
def test_answer_with_a_moment_and_the_follower_reads_it(world: World) -> None:  # AC-N5 AC-N6
    world.ask()
    assert world.answer("  Soften the\n elbow here.  ", at_s=2.4)[0] == 200
    request = world.view()[1]["request"]
    assert request["state"] == "answered" and request["answer"]["note"] == "Soften the elbow here."
    assert request["answer"]["at_s"] == 2.4 and request["from"] == {"name": None}
    assert world.view()[1]["can_ask"] is False


@pytest.mark.parametrize("note", ["", "   ", "x" * 601, "see https://example.org", "go to www.example.org", "[a](b)", "<b>hi</b>",
                                  "bell\x07", "ｈｔｔｐｓ：／／ｅｘａｍｐｌｅ．ｏｒｇ", 5, None])
def test_answer_text_rules(world: World, note: Any) -> None:  # AC-N5
    world.ask()
    status, doc = send(world.api, f"api/me/note-requests/{world.request_id()}/answer", {"note": note}, world.trainer)
    assert status == 400 and "1 to 600" in doc["message"]
    assert world.rows()[0]["state"] == "asked"


def test_answer_accepts_exactly_600_characters_after_normalising(world: World) -> None:  # AC-N5
    world.ask()
    assert world.answer("é" * 600)[0] == 200


def test_at_s_may_be_any_time_in_the_take_and_a_match_records_the_fault(world: World) -> None:  # AC-N5
    job = claimed(world.api, world.follower, clip=False, duration_ms=10000)  # a take of 10 seconds
    world.ask(job=job)
    assert world.answer("Matched.", at_s=7.1)[0] == 200
    assert world.rows()[0]["matched_fault"] == "tempo" and world.rows()[0]["note_at_s"] == 7.1
    other = claimed(world.api, world.follower, clip=False, duration_ms=10000)
    world.ask(job=other)
    rid = [r["id"] for r in get(world.api, "api/me/note-requests", cookie=world.trainer)[2]["requests"] if r["state"] == "asked"][0]
    assert world.answer("Missed by Simon.", at_s=4.2, rid=rid)[0] == 200  # a time Simon did not report
    row = [r for r in world.rows() if r["job_id"] == other][0]
    assert row["note_at_s"] == 4.2 and row["matched_fault"] is None
    mine = get(world.api, f"api/me/notes?entry={ENTRY}", cookie=world.follower)[2]["notes"]
    assert {(n["at_s"], n["matched_fault"]) for n in mine} == {(7.1, "tempo"), (4.2, None)}


def test_a_matched_fault_with_a_side_is_named_with_it(world: World) -> None:  # AC-N5
    world.ask()
    assert world.answer("Left elbow.", at_s=2.4)[0] == 200
    assert world.rows()[0]["matched_fault"] == "elbow left"


def test_at_s_out_of_range_or_negative_is_a_400(world: World) -> None:  # AC-N5
    job = claimed(world.api, world.follower, clip=False, duration_ms=10000)
    world.ask(job=job)
    for bad in (10.5, 1e9, -0.1, -1, "2.4", True, float("nan"), float("inf")):
        status, doc = world.answer("Fine.", at_s=bad)
        assert status == 400 and "inside the take" in doc["message"], bad
    assert world.rows()[0]["state"] == "asked"
    assert world.answer("Fine.", at_s=10)[0] == 200  # the end of the take is inside it


def test_at_s_without_the_faults_shown_is_still_free_within_the_take(world: World) -> None:  # AC-N5
    world.ask(["score"])
    assert world.answer("Fine.", at_s=3.3)[0] == 200


def test_a_request_is_answered_once(world: World) -> None:  # AC-N5
    world.ask()
    rid = world.request_id()
    assert world.answer("One.")[0] == 200
    assert world.answer("Two.", rid=rid)[0] == 409
    assert send(world.api, f"api/me/note-requests/{rid}/decline", {}, world.trainer)[0] == 409
    assert world.rows()[0]["note"] == "One."


def test_decline_closes_the_request_and_the_follower_may_ask_again(world: World) -> None:  # AC-N5 AC-N6
    world.ask()
    assert send(world.api, f"api/me/note-requests/{world.request_id()}/decline", {}, world.trainer)[0] == 200
    view = world.view()[1]
    assert view["request"]["state"] == "declined" and view["request"]["answer"] is None and view["can_ask"] is True
    assert world.ask()[0] == 201


def test_answer_needs_the_same_origin_guard(world: World) -> None:  # AC-N5
    world.ask()
    status = post(world.api, f"api/me/note-requests/{world.request_id()}/answer", {"note": "Hi"}, cookie=world.trainer, guard=False)[0]
    assert status == 403


# ----- AC-N6 follower side ---------------------------------------------------------------------------------------------
def test_withdraw_ends_the_trainers_access_on_the_next_request(world: World) -> None:  # AC-N6
    world.ask(["score", "faults", "clip"])
    rid = world.request_id()
    assert get(world.api, f"api/me/note-requests/{rid}", cookie=world.trainer)[0] == 200
    assert send(world.api, f"api/me/takes/{world.job}/ask-trainer/withdraw", {}, world.follower)[0] == 200
    assert get(world.api, f"api/me/note-requests/{rid}", cookie=world.trainer)[0] == 404
    assert get(world.api, "api/me/note-requests", cookie=world.trainer)[2] == {"requests": []}
    assert send(world.api, f"api/me/note-requests/{rid}/answer", {"note": "Late."}, world.trainer)[0] == 404
    assert world.view()[1]["request"] is None and world.view()[1]["can_ask"] is True
    assert world.ask()[0] == 201  # a new request is allowed


def test_withdraw_needs_an_open_request_of_your_own(world: World) -> None:  # AC-N6
    path = f"api/me/takes/{world.job}/ask-trainer/withdraw"
    assert send(world.api, path, {}, world.follower)[0] == 404  # nothing open
    world.ask()
    assert send(world.api, path, {}, world.third)[0] == 404
    assert send(world.api, path, {}, world.trainer)[0] == 404
    assert send(world.api, path, {}, None)[0] == 401
    assert post(world.api, path, {}, cookie=world.follower, guard=False)[0] == 403
    assert world.rows()[0]["state"] == "asked"
    world.answer("Done.")
    assert send(world.api, path, {}, world.follower)[0] == 404  # an answered request is not open


def test_the_follower_view_never_carries_the_trainers_ids(world: World) -> None:  # AC-N6
    world.ask()
    world.answer("Nice.")
    text = json.dumps(world.view()[1])
    for secret in (world.tid, world.fid, TRAINER, "example.com"):
        assert secret not in text


def test_received_notes_by_movement_for_the_history_page(world: World) -> None:  # AC-N6
    world.ask()
    world.answer("Elbow.", at_s=7.1)
    status, _, doc = get(world.api, f"api/me/notes?entry={ENTRY}", cookie=world.follower)
    assert status == 200 and [(n["note"], n["at_s"], n["from"]) for n in doc["notes"]] == [("Elbow.", 7.1, {"name": None})]
    assert get(world.api, f"api/me/notes?entry={ENTRY}", cookie=world.third)[2] == {"notes": []}  # negative
    assert get(world.api, f"api/me/notes?entry={ENTRY}")[0] == 401 and get(world.api, "api/me/notes?entry=..%2F", cookie=world.follower)[0] == 404


def test_the_trainer_is_named_only_when_they_opted_in(world: World) -> None:  # AC-N6
    send(world.api, "api/me/profile", {"public_name": "Tina T", "show_name": True}, world.trainer, "PUT")
    world.ask()
    world.answer("Hello.")
    assert world.view()[1]["request"]["from"] == {"name": None}  # a public name alone does not credit them as a trainer
    send(world.api, "api/me/profile", {"credit_me_as_trainer": True}, world.trainer, "PUT")
    assert world.view()[1]["request"]["from"] == {"name": "Tina T"}


# ----- AC-N7 notices, no mail ----------------------------------------------------------------------------------------------
def test_notices_count_waiting_requests_and_new_notes_and_send_no_mail(world: World) -> None:  # AC-N7
    mails = len(list((world.api.app.state / "outbox").glob("*.eml")))
    assert get(world.api, "api/me/note-notices", cookie=world.trainer)[2] == {"waiting": 0, "received": []}
    world.ask()
    assert get(world.api, "api/me/note-notices", cookie=world.trainer)[2]["waiting"] == 1
    assert get(world.api, "api/me/note-notices", cookie=world.follower)[2] == {"waiting": 0, "received": []}
    world.answer("Nice.")
    assert get(world.api, "api/me/note-notices", cookie=world.trainer)[2]["waiting"] == 0
    notice = get(world.api, "api/me/note-notices", cookie=world.follower)[2]
    assert [n["entry_id"] for n in notice["received"]] == [ENTRY] and notice["waiting"] == 0
    assert get(world.api, "api/me/note-notices", cookie=world.third)[2] == {"waiting": 0, "received": []}
    assert send(world.api, "api/me/note-notices/seen", {}, world.third)[0] == 200  # another account's seen changes nothing of mine
    assert len(get(world.api, "api/me/note-notices", cookie=world.follower)[2]["received"]) == 1
    assert send(world.api, "api/me/note-notices/seen", {}, world.follower)[0] == 200
    assert get(world.api, "api/me/note-notices", cookie=world.follower)[2]["received"] == []  # since the last visit
    assert get(world.api, "api/me/note-notices")[0] == 401
    assert len(list((world.api.app.state / "outbox").glob("*.eml"))) == mails  # no mail, no push


# ----- AC-N8 long-context hook ------------------------------------------------------------------------------------------------
def test_notes_for_returns_the_followers_answered_notes_for_one_movement(world: World) -> None:  # AC-N8
    second = claimed(world.api, world.follower)
    third_take = claimed(world.api, world.follower)
    world.ask(job=world.job)
    world.ask(job=second)
    world.ask(job=third_take)
    [first_id, second_id] = [r["id"] for r in reversed(get(world.api, "api/me/note-requests", cookie=world.trainer)[2]["requests"])][:2]
    assert world.answer("First.", rid=first_id, at_s=2.4)[0] == 200
    assert world.answer("Second.", rid=second_id)[0] == 200  # the third stays asked: no note yet
    state = world.api.app.state
    got = notes.notes_for(state, world.fid, ENTRY)
    assert [(n["note"], n["at_s"]) for n in got] == [("First.", 2.4), ("Second.", None)]
    assert set(got[0]) == {"note", "at_s", "matched_fault", "job_id", "answered_utc"} and got[0]["job_id"] == world.job
    assert notes.notes_for(state, world.fid, "other-entry") == [] and notes.notes_for(state, world.xid, ENTRY) == []  # negative
    assert notes.notes_for(state, world.tid, ENTRY) == []  # the trainer receives none
    assert notes.notes_for(state / "nowhere", world.fid, ENTRY) == []


# ----- AC-N9 cascade -------------------------------------------------------------------------------------------------------------
def answered(world: World) -> None:
    world.ask()
    assert world.answer("Keep it.")[0] == 200
    assert len(world.rows()) == 1


def nothing_left(world: World) -> None:
    assert world.rows() == []
    follower = world.view()
    assert follower[0] == 404 or follower[1]["request"] is None  # no tombstone on the follower's side


def test_cascade_deleting_the_take(world: World) -> None:
    answered(world)
    other = claimed(world.api, world.follower)
    world.ask(job=other)
    assert world.api.request("POST", f"api/jobs/{world.job}/delete", b"", {})[0] == 200
    assert [r["job_id"] for r in world.rows()] == [other]  # only the deleted take's request goes
    assert get(world.api, "api/me/notes?entry=" + ENTRY, cookie=world.follower)[2] == {"notes": []}


def test_cascade_withdrawing_retention(world: World) -> None:
    answered(world)
    assert send(world.api, "api/me/consent", {"retention": False, "version": "retention-90-v2"}, world.follower)[0] == 200
    nothing_left(world)
    assert get(world.api, "api/me/note-requests", cookie=world.trainer)[2] == {"requests": []}


def test_cascade_the_followers_delete_my_data(world: World) -> None:
    answered(world)
    assert send(world.api, "api/me/delete", {"confirm": "delete"}, world.follower)[0] == 200
    assert world.rows() == [] and get(world.api, "api/me/note-requests", cookie=world.trainer)[2] == {"requests": []}


def test_cascade_the_trainers_delete_my_data_leaves_the_follower_nothing_to_see(world: World) -> None:
    answered(world)
    assert send(world.api, "api/me/delete", {"confirm": "delete"}, world.trainer)[0] == 200
    assert world.rows() == []
    status, doc = world.view()
    assert status == 404 or doc["request"] is None  # the entry is gone with its owner: nothing to send, nothing shown
    assert get(world.api, f"api/me/notes?entry={ENTRY}", cookie=world.follower)[2] == {"notes": []}


def test_cascade_the_idle_account_prune(world: World) -> None:
    answered(world)
    other = claimed(world.api, world.third)
    store_ = world.store
    store_.write("UPDATE users SET last_seen_at = ? WHERE user_id = ?", (time.time() - 181 * 86400, world.fid))
    store_.prune(world.api.app.state)
    assert world.rows() == [] and store_.user(world.fid) is None
    assert store_.user(world.tid) is not None and other


def test_cascade_dropping_a_history_copy_and_forgetting_a_movement(world: World) -> None:
    answered(world)
    state = world.api.app.state
    assert history_store.drop_take(state, world.job) == 0  # no copy was kept, the request still goes with the take
    assert world.rows() == []
    world.ask()
    other = claimed(world.api, world.follower)
    world.ask(job=other)
    assert history_store.forget(state, world.fid, ENTRY) == 0
    assert world.rows() == []


def test_cascade_the_retention_sweep_removes_the_note_with_the_aged_copy(world: World) -> None:
    from export_seed import seed_takes

    [kept] = seed_takes(world.api.app.state, world.store, world.fid, "sweep", 1, entry=ENTRY)
    [fresh] = seed_takes(world.api.app.state, world.store, world.fid, "fresh", 1, entry=ENTRY)
    for job in (kept, fresh):
        world.store.write("INSERT INTO note_requests (id, job_id, entry_id, follower_id, trainer_id, state, asked_utc, note) "
                          "VALUES (?, ?, ?, ?, ?, 'answered', 't', 'n')", (f"id-{job}", job, ENTRY, world.fid, world.tid))
    meta = history_store.take_dir(world.api.app.state, world.fid, ENTRY, fresh) / history_store.META_NAME
    doc = json.loads(meta.read_text())
    meta.write_text(json.dumps({**doc, "kept_ts": time.time()}))
    assert history_store.sweep(world.api.app.state) == 1  # only the aged copy goes (its kept_ts is 1.0)
    assert [r["job_id"] for r in world.rows()] == [fresh]


def test_cascade_leaves_other_peoples_requests(world: World) -> None:
    answered(world)
    stranger = claimed(world.api, world.third)
    assert send(world.api, f"api/me/takes/{stranger}/ask-trainer", {"confirm": True}, world.third)[0] == 201
    history_store.forget(world.api.app.state, world.fid)
    assert [r["follower_id"] for r in world.rows()] == [world.xid]


def test_cascade_deleting_the_trainers_own_take_removes_requests_to_that_entry(api: Api) -> None:
    trainer = sign_in(api, TRAINER)
    follower = sign_in(api, FOLLOWER)
    made = api.app.queue.submit("trainer", lambda ctx: {"result": {"entry_id": "made-entry-1"}}, entry_id=None)
    api.app.queue.wait(made["id"], 10)
    assert post(api, "api/me/claims", {"job_id": made["id"]}, cookie=trainer)[0] == 200
    job = claimed(api, follower, entry="made-entry-1")
    assert send(api, f"api/me/takes/{job}/ask-trainer", {"confirm": True}, follower)[0] == 201
    assert api.request("POST", f"api/jobs/{made['id']}/delete", b"", {})[0] == 200
    assert store(api).fetch("SELECT * FROM note_requests") == []


# ----- AC-N10 limits ------------------------------------------------------------------------------------------------------------------
def test_limit_ten_open_requests_per_follower(world: World) -> None:
    jobs = [world.job] + [claimed(world.api, world.follower) for _ in range(10)]
    for job in jobs[:10]:
        assert world.ask(job=job)[0] == 201
    status, doc = world.ask(job=jobs[10])
    assert status == 429 and "10 requests waiting" in doc["message"]
    assert send(world.api, f"api/me/takes/{jobs[0]}/ask-trainer/withdraw", {}, world.follower)[0] == 200
    assert world.ask(job=jobs[10])[0] == 201  # room again


def test_limit_fifty_new_requests_per_trainer_per_day(world: World) -> None:
    now = world.store.clock()
    for n in range(49):
        world.store.write("INSERT INTO note_requests (id, job_id, entry_id, follower_id, trainer_id, state, asked_utc) "
                          "VALUES (?, ?, ?, ?, ?, 'answered', ?)", (f"seed{n:04d}xx", f"{n:012x}", ENTRY, f"u-other{n}", world.tid, identity._iso(now - 60)))
    assert world.ask()[0] == 201  # the 50th
    other = claimed(world.api, world.follower)
    status, doc = world.ask(job=other)
    assert status == 429 and "Try again tomorrow" in doc["message"]
    world.store.write("UPDATE note_requests SET asked_utc = ?", (identity._iso(now - 86400 - 5),))  # a day later
    assert world.ask(job=other)[0] == 201


# ----- anonymous flows and sign-in off -------------------------------------------------------------------------------------------------
def test_anonymous_flows_are_unchanged(api: Api) -> None:
    job = make_job(api)
    status, _, doc = get(api, f"api/jobs/{job}")
    assert status == 200 and "note" not in json.dumps(doc).lower().replace("\"note\": null", "")  # the job answer is as before
    assert get(api, f"api/me/takes/{job}/ask-trainer")[0] == 401
    assert get(api, "api/me/note-requests")[0] == 401 and get(api, "api/me/note-notices")[0] == 401
    assert not identity.db_path(api.app.state).is_file()  # asking about notes signed out does not even open the store


def test_sign_in_off_leaves_no_trace(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIMON7_MAIL_TRANSPORT", "off")
    status = get(api, "api/me/note-requests")[0]
    assert status in (401, 404)


# ----- download my data ---------------------------------------------------------------------------------------------------------------------
def test_export_carries_both_roles_and_nothing_of_the_other_account(world: World) -> None:
    send(world.api, "api/me/profile", {"public_name": "Fred F", "show_name": True}, world.follower, "PUT")
    world.ask(["score", "faults"])
    world.answer("Soft elbow.", at_s=2.4)
    mine = get(world.api, "api/me/export", cookie=world.follower)[2]["notes"]
    theirs = get(world.api, "api/me/export", cookie=world.trainer)[2]["notes"]
    [row] = mine
    assert row["role"] == "follower" and row["note"] == "Soft elbow." and row["at_s"] == 2.4 and row["matched_fault"] == "elbow left" and row["with"] == "A Simon trainer"
    assert row["shown"] == ["score", "faults"] and row["state"] == "answered"
    [row2] = theirs
    assert row2["role"] == "trainer" and row2["note"] == "Soft elbow." and row2["with"] == "Fred F" and row2["shown"] is None
    for doc in (mine, theirs):
        text = json.dumps(doc)
        for secret in (world.job, world.fid, world.tid, FOLLOWER, TRAINER):
            assert secret not in text
    assert get(world.api, "api/me/export", cookie=world.third)[2]["notes"] == []  # negative


def test_export_leaves_out_a_withdrawn_request(world: World) -> None:
    world.ask()
    send(world.api, f"api/me/takes/{world.job}/ask-trainer/withdraw", {}, world.follower)
    assert get(world.api, "api/me/export", cookie=world.follower)[2]["notes"] == []


def test_logs_carry_no_note_text_or_ids(world: World) -> None:
    from part7 import applog

    seen: list[str] = []
    real = applog.log
    applog.log = lambda message, *a, **k: (seen.append(str(message)), real(message, *a, **k))[1]  # type: ignore[assignment]
    try:
        world.ask()
        world.answer("A secret sentence.")
    finally:
        applog.log = real
    text = " ".join(seen)
    assert "secret sentence" not in text and world.job not in text and world.fid not in text
