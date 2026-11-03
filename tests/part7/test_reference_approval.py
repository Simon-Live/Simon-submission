"""A teacher approves a student's take as their reference (docs/specs/my-reference.md AC-MR-20 to AC-MR-29; ADR-0019).
Fake chain, no GPU, no real clip. The consent is the open ask-the-trainer request (notes.md)."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

import pytest

from auth_support import authenv, get, post, sign_in  # noqa: F401
from part7 import auth, history_store, my_reference, my_reference_routes, reference_approval
from support import Api
from test_my_reference import ENTRY, follow, mark, mine, record_of, seen  # noqa: F401
from test_notes import send

TINA, ADA, THEO = "tina@example.com", "ada@example.com", "theo@example.com"
pytestmark = pytest.mark.usefixtures("authenv")


class Room:
    """Tina owns the movement, Ada follows it, Theo is a stranger teacher with his own movement."""

    def __init__(self, api: Api, mp4: Path) -> None:
        self.api, self.mp4 = api, mp4
        self.tina, self.ada, self.theo = (sign_in(api, e) for e in (TINA, ADA, THEO))
        self.store = auth.identity(api.app)
        self.tid, self.aid, self.xid = (self.store.session_user(s) for s in (self.tina, self.ada, self.theo))
        self.store.attach_entry(ENTRY, self.tid)

    def take(self) -> str:
        return follow(self.api, self.mp4, self.ada)["id"]

    def ask(self, job: str) -> str:
        assert send(self.api, f"api/me/takes/{job}/ask-trainer", {"confirm": True}, self.ada)[0] == 201
        rows = get(self.api, "api/me/note-requests", cookie=self.tina)[2]["requests"]
        return next(r["id"] for r in rows if r["state"] == "asked")

    def approve(self, rid: str, sid: Any = "tina") -> tuple[int, Any]:
        return send(self.api, f"api/me/note-requests/{rid}/approve-reference", {}, self.tina if sid == "tina" else sid)

    def suggestion(self, action: str, sid: Any = "ada") -> tuple[int, Any]:
        return send(self.api, "api/me/reference/suggestion", {"entry_id": ENTRY, "action": action}, self.ada if sid == "ada" else sid)

    def reference(self) -> Any:
        return mine(self.api, self.ada)


@pytest.fixture()
def room(api: Api, tiny_mp4: Path, seen: list[bytes]) -> Room:  # noqa: F811
    return Room(api, tiny_mp4)


def test_a_stranger_teacher_and_a_signed_out_caller_cannot_approve(room: Room) -> None:  # AC-MR-20
    rid = room.ask(room.take())
    assert room.approve(rid, room.theo)[0] == 404 and room.approve(rid, room.ada)[0] == 404
    assert room.approve(rid, None)[0] == 401
    assert room.approve("not-an-id")[0] == 404 and room.approve("a" * 16)[0] == 404  # a guessed id is just as unknown
    assert room.reference()["reference"] is None and list((room.api.app.state / "myref").glob("*/*")) == []


def test_a_teacher_who_does_not_own_the_entry_gets_404(room: Room) -> None:  # AC-MR-20
    rid = room.ask(room.take())
    room.store.write("UPDATE entries SET user_id = ? WHERE entry_id = ?", (room.xid, ENTRY))
    assert room.approve(rid)[0] == 404
    assert room.reference()["reference"] is None


def test_a_closed_request_a_private_take_and_an_only_me_entry_are_404(room: Room, monkeypatch: pytest.MonkeyPatch) -> None:  # AC-MR-20
    first = room.ask(room.take())
    assert send(room.api, f"api/me/note-requests/{first}/decline", {}, room.tina)[0] == 200
    assert room.approve(first)[0] == 404  # the take is no longer in the teacher's view
    second = room.ask(room.take())
    monkeypatch.setattr(history_store, "is_private", lambda job: True)
    assert room.approve(second)[0] == 404
    monkeypatch.undo()
    room.store.write("UPDATE entries SET only_me = 1 WHERE entry_id = ?", (ENTRY,))
    assert room.approve(second)[0] == 404
    assert room.reference()["reference"] is None


def test_the_answer_to_the_teacher_names_no_student_and_no_job(room: Room) -> None:  # AC-MR-20
    job = room.take()
    status, doc = room.approve(room.ask(job))
    text = json.dumps(doc)
    assert status == 200 and doc == {"state": "accepted"} and job not in text and room.aid not in text


def test_an_approved_take_is_the_students_reference_for_later_takes(room: Room, seen: list[bytes]) -> None:  # AC-MR-21
    job = room.take()
    assert room.approve(room.ask(job))[1] == {"state": "accepted"}
    shown = room.reference()["reference"]
    assert shown["job_id"] == job and shown["approved"] and "approved_by" not in shown and room.tid not in json.dumps(shown)
    later = follow(room.api, room.mp4, room.ada)
    assert later["reference"]["used"] == "own" and later["reference"]["job_id"] == job and later["reference"]["approved_by"] == my_reference.approver_marker(room.tid)
    assert later["reference"]["approved"] == shown["approved"]
    mine_ = record_of(room.api, later["id"], room.ada)  # the owner reads the date, never the teacher's id
    assert mine_["approved"] == shown["approved"] and "approved_by" not in mine_
    for viewer in (room.theo, None):
        assert record_of(room.api, later["id"], viewer) == {"used": "own", "date": mine_["date"], "approved": shown["approved"]}
    assert seen[-1] != seen[0]  # Part 5 got the approved clip, not the teacher's


def test_approving_again_changes_nothing(room: Room) -> None:  # AC-MR-21
    rid = room.ask(room.take())
    assert room.approve(rid)[1] == {"state": "accepted"}
    before = room.reference()
    assert room.approve(rid)[1] == {"state": "accepted"} and room.reference() == before


def test_the_students_removal_wins(room: Room) -> None:  # AC-MR-22
    job = room.take()
    rid = room.ask(job)
    room.approve(rid)
    assert post(room.api, "api/me/reference/remove", {"entry_id": ENTRY}, cookie=room.ada)[0] == 200
    assert follow(room.api, room.mp4, room.ada)["reference"] == {"used": "teacher"}
    assert room.approve(rid)[0] == 409  # the same rep is not approved over a "no"
    assert room.reference()["reference"] is None
    other = room.take()  # another rep, approved later, waits for the student instead of replacing silently
    assert room.approve(room.ask(other))[1] == {"state": "suggested"}
    assert room.reference()["reference"] is None and follow(room.api, room.mp4, room.ada)["reference"] == {"used": "teacher"}


def test_a_pending_suggestion_changes_no_scoring_until_accepted(room: Room, seen: list[bytes]) -> None:  # AC-MR-23
    own = room.take()
    assert mark(room.api, room.ada, own)[0] == 200
    taken = room.take()
    assert room.approve(room.ask(taken))[1] == {"state": "suggested"}
    now = room.reference()
    assert now["reference"]["job_id"] == own and "approved" not in now["reference"]
    assert now["suggestion"]["job_id"] == taken and room.tid not in json.dumps(now)
    waiting = follow(room.api, room.mp4, room.ada)
    assert waiting["reference"]["job_id"] == own and "approved_by" not in waiting["reference"]
    status, doc = room.suggestion("accept")
    assert status == 200 and doc["reference"]["job_id"] == taken and doc["reference"]["approved"]
    after = follow(room.api, room.mp4, room.ada)
    assert after["reference"]["job_id"] == taken and after["reference"]["approved_by"] == my_reference.approver_marker(room.tid)
    assert room.reference()["suggestion"] is None and room.suggestion("accept")[0] == 404


def test_declining_keeps_the_reference_and_the_same_rep_is_not_suggested_again(room: Room) -> None:  # AC-MR-23
    own = room.take()
    mark(room.api, room.ada, own)
    taken = room.take()
    rid = room.ask(taken)
    room.approve(rid)
    assert room.suggestion("decline")[0] == 200
    assert room.reference()["suggestion"] is None and room.reference()["reference"]["job_id"] == own
    assert room.approve(rid)[0] == 409 and room.suggestion("decline")[0] == 404


def test_the_student_routes_are_owner_only_and_checked(room: Room) -> None:  # AC-MR-24
    mark(room.api, room.ada, room.take())
    room.approve(room.ask(room.take()))
    assert room.suggestion("accept", room.theo)[0] == 404  # Theo has none
    assert room.suggestion("accept", room.tina)[0] == 404  # the teacher cannot accept for the student
    assert send(room.api, "api/me/reference/suggestion", {"entry_id": ENTRY, "action": "x"}, room.ada)[0] == 400
    assert send(room.api, "api/me/reference/suggestion", {"entry_id": "../x", "action": "accept"}, room.ada)[0] == 400
    assert send(room.api, "api/me/reference/suggestion", {"entry_id": ENTRY, "action": "accept"}, None)[0] == 401
    assert get(room.api, f"api/me/reference?entry={ENTRY}", room.theo)[2]["suggestion"] is None


def test_a_waiting_suggestion_expires(room: Room, monkeypatch: pytest.MonkeyPatch) -> None:  # AC-MR-25
    mark(room.api, room.ada, room.take())
    room.approve(room.ask(room.take()))
    assert room.reference()["suggestion"] is not None
    monkeypatch.setattr(reference_approval, "SUGGESTION_DAYS", -1)
    assert room.reference()["suggestion"] is None and room.suggestion("accept")[0] == 404
    assert not (reference_approval.folder(room.api.app.state, room.aid, ENTRY) / reference_approval.COPY).exists()


def test_deleting_the_approved_take_drops_the_waiting_suggestion(room: Room) -> None:  # AC-MR-25
    mark(room.api, room.ada, room.take())
    taken = room.take()
    room.approve(room.ask(taken))
    assert post(room.api, f"api/jobs/{taken}/delete", cookie=room.ada)[0] == 200  # the owner (TICKET-373)
    assert room.reference()["suggestion"] is None


def test_the_rate_limit_and_an_unusable_skeleton(room: Room, monkeypatch: pytest.MonkeyPatch) -> None:  # AC-MR-26
    rid = room.ask(room.take())
    monkeypatch.setattr(my_reference_routes, "accepts", lambda app, data: False)
    assert room.approve(rid)[0] == 422 and room.reference()["reference"] is None
    monkeypatch.setattr(my_reference_routes, "accepts", lambda app, data: True)
    room.api.app._approve_limit = auth.Limiter(1, 60)
    assert room.approve(rid)[0] == 200 and room.approve(rid)[0] == 429


def test_download_my_data_holds_the_approval_in_both_accounts(room: Room) -> None:  # AC-MR-27
    job = room.take()
    room.approve(room.ask(job))
    student = get(room.api, "api/me/export", room.ada)[2]["reference_approvals"]
    teacher = get(room.api, "api/me/export", room.tina)[2]["reference_approvals"]
    assert [(r["role"], r["state"]) for r in student] == [("student", "accepted")] and [(r["role"], r["state"]) for r in teacher] == [("teacher", "accepted")]
    assert teacher[0]["approved"] and teacher[0]["take_date"] == student[0]["take_date"]
    for rows, other in ((student, room.tid), (teacher, room.aid)):
        text = json.dumps(rows)
        assert job not in text and other not in text and "skeleton" not in text and "format" not in text  # no movement data, no other account
    assert get(room.api, "api/me/export", room.theo)[2]["reference_approvals"] == []
    mark(room.api, room.ada, room.take())  # the student's own mark replaces the approved reference; the record goes with it
    assert get(room.api, "api/me/export", room.tina)[2]["reference_approvals"] == []
    room.approve(room.ask(room.take()))  # a waiting suggestion is listed too
    assert [r["state"] for r in get(room.api, "api/me/export", room.tina)[2]["reference_approvals"]] == ["suggested"]


def test_deleting_the_students_account_removes_the_record_from_both(room: Room) -> None:  # AC-MR-28
    mark(room.api, room.ada, room.take())
    room.approve(room.ask(room.take()))
    assert send(room.api, "api/me/delete", {"confirm": "delete"}, room.ada)[0] == 200
    assert get(room.api, "api/me/export", room.tina)[2]["reference_approvals"] == []
    assert list((room.api.app.state / "myref").glob("*/*")) == [] and [p for p in (room.api.app.state / "myref_suggest").glob("*/*") if p.parent.name != ".forgot"] == []


def test_deleting_the_teachers_account_takes_the_approval_off_and_drops_waiting_ones(room: Room) -> None:  # AC-MR-28
    job = room.take()
    room.approve(room.ask(job))  # accepted
    extra = room.take()
    room.approve(room.ask(extra))  # waits, the student already has a reference
    assert send(room.api, "api/me/delete", {"confirm": "delete"}, room.tina)[0] == 200
    now = room.reference()
    assert now["suggestion"] is None and now["reference"]["job_id"] == job and "approved" not in now["reference"]
    assert get(room.api, "api/me/export", room.ada)[2]["reference_approvals"] == []
    assert follow(room.api, room.mp4, room.ada)["reference"].get("approved_by") is None
    assert not reference_approval.was_declined(room.api.app.state, room.aid, ENTRY)


def test_forgetting_a_movement_removes_its_suggestion_and_nos(room: Room) -> None:  # AC-MR-28
    mark(room.api, room.ada, room.take())
    rid = room.ask(room.take())
    room.approve(rid)
    room.suggestion("decline")
    assert reference_approval.was_declined(room.api.app.state, room.aid, ENTRY)
    history_store.forget(room.api.app.state, room.aid, ENTRY)
    assert not reference_approval.was_declined(room.api.app.state, room.aid, ENTRY)
    assert history_store.forget(room.api.app.state, "bad id/..", ENTRY) == 0
    assert reference_approval.forget(room.api.app.state, "bad id/..") == 0


# ----- review fixes (B2, R1, R2, R3, R5, R6) ------------------------------------------------------------------------
def detail(room: Room, rid: str) -> Any:
    return get(room.api, f"api/me/note-requests/{rid}", cookie=room.tina)[2]


def test_the_trainer_page_offers_the_approval_only_while_the_request_is_open(room: Room) -> None:  # AC-MR-29 (B2)
    first, second = room.ask(room.take()), None
    assert detail(room, first)["can_approve_reference"] is True
    assert send(room.api, f"api/me/note-requests/{first}/decline", {}, room.tina)[0] == 200
    assert detail(room, first)["can_approve_reference"] is False
    second = room.ask(room.take())
    assert detail(room, second)["can_approve_reference"] is True
    assert send(room.api, f"api/me/note-requests/{second}/answer", {"note": "Soft elbow."}, room.tina)[0] == 200
    assert detail(room, second)["can_approve_reference"] is False


def leftovers(room: Room) -> list[Path]:
    """Every reference file or copy on disk, apart from the marks that refuse a late approval."""
    state = room.api.app.state
    return [p for root in ("myref", "myref_suggest") for p in (state / root).glob("*/*") if p.parent.name != ".forgot"]


def test_a_request_withdrawn_during_the_part5_check_is_refused_and_leaves_no_copy(room: Room, monkeypatch: pytest.MonkeyPatch) -> None:  # AC-MR-20 (R1)
    job = room.take()
    rid = room.ask(job)

    def doctor(app: Any, data: bytes) -> bool:
        assert send(room.api, f"api/me/takes/{job}/ask-trainer/withdraw", {}, room.ada)[0] == 200
        return True

    monkeypatch.setattr(my_reference_routes, "accepts", doctor)
    assert room.approve(rid)[0] == 404
    assert leftovers(room) == [] and room.reference()["reference"] is None


def test_a_take_deleted_during_the_part5_check_is_refused_and_leaves_no_copy(room: Room, monkeypatch: pytest.MonkeyPatch) -> None:  # AC-MR-20 (R1)
    job = room.take()
    rid = room.ask(job)

    def doctor(app: Any, data: bytes) -> bool:
        assert post(room.api, f"api/jobs/{job}/delete", cookie=room.ada)[0] == 200  # the owner (TICKET-373)
        return True

    monkeypatch.setattr(my_reference_routes, "accepts", doctor)
    assert room.approve(rid)[0] == 404
    assert leftovers(room) == [] and room.reference()["reference"] is None


def test_an_account_deleted_during_the_part5_check_is_refused_and_leaves_no_copy(room: Room, monkeypatch: pytest.MonkeyPatch) -> None:  # AC-MR-28 (R1)
    rid = room.ask(room.take())

    def doctor(app: Any, data: bytes) -> bool:
        assert send(room.api, "api/me/delete", {"confirm": "delete"}, room.ada)[0] == 200
        return True

    monkeypatch.setattr(my_reference_routes, "accepts", doctor)
    assert room.approve(rid)[0] == 404
    assert leftovers(room) == []


def test_data_forgotten_after_the_checks_began_refuses_the_write(room: Room) -> None:  # AC-MR-28 (R1)
    state, began = room.api.app.state, 0.0
    reference_approval.forget(state, room.aid, ENTRY)
    assert reference_approval.approve(state, room.aid, ENTRY, "a" * 12, "2026-10-01", b"{}", room.tid, since=began) is None
    assert reference_approval.approve(state, room.aid, ENTRY, "a" * 12, "2026-10-01", b"{}", room.tid, since=9e12) == "accepted"
    assert reference_approval.approve(state, room.aid, ENTRY, "b" * 12, "2026-10-01", b"{}", room.tid, still_allowed=lambda: False) is None


def test_a_reference_the_student_sets_during_the_approval_is_not_overwritten(room: Room, monkeypatch: pytest.MonkeyPatch) -> None:  # AC-MR-23 (R2)
    own, job = room.take(), room.take()
    state, ran = room.api.app.state, []
    real = reference_approval.was_declined

    def student_acts_meanwhile(*args: Any, **kw: Any) -> bool:  # called inside approve, between its read and its write
        worker = threading.Thread(target=lambda: ran.append(my_reference.set_reference(state, room.aid, ENTRY, own, "2026-10-01", b"{}", False)))
        worker.start()
        worker.join(0.5)
        ran.append("waiting" if worker.is_alive() else "interleaved")  # one lock: the student's write must wait for the approval
        return real(*args, **kw)

    monkeypatch.setattr(reference_approval, "was_declined", student_acts_meanwhile)
    assert reference_approval.approve(state, room.aid, ENTRY, job, "2026-10-01", b"{}", room.tid) == "accepted"
    monkeypatch.undo()
    assert ran[0] == "waiting"
    after = room.reference()["reference"]
    assert after["job_id"] == own and "approved" not in after  # the student's write came after the approval and won


def test_the_job_record_keeps_a_marker_not_the_teachers_account(room: Room) -> None:  # AC-MR-28 (R3)
    job = room.take()
    room.approve(room.ask(job))
    later = follow(room.api, room.mp4, room.ada)
    raw = json.dumps(room.api.app.queue.get(later["id"]))
    assert room.tid not in raw and later["reference"]["approved_by"] == my_reference.approver_marker(room.tid)
    assert send(room.api, "api/me/delete", {"confirm": "delete"}, room.tina)[0] == 200
    assert room.tid not in json.dumps(room.api.app.queue.get(later["id"])) and room.tid not in json.dumps(list((room.api.app.state / "myref").rglob("meta.json")) and
        [json.loads(p.read_text()) for p in (room.api.app.state / "myref").rglob("meta.json")])


def test_a_take_that_is_not_finished_or_not_the_requests_is_404(room: Room, monkeypatch: pytest.MonkeyPatch) -> None:  # AC-MR-20 (R5)
    job = room.take()
    rid = room.ask(job)
    queue, real = room.api.app.queue, room.api.app.queue.get
    monkeypatch.setattr(queue, "get", lambda j: {**real(j), "status": "running"} if j == job else real(j))
    assert room.approve(rid)[0] == 404  # not done
    monkeypatch.setattr(queue, "get", lambda j: {**real(j), "entry_id": "other-move"} if j == job else real(j))
    assert room.approve(rid)[0] == 404  # entry mismatch
    monkeypatch.setattr(queue, "get", real)
    monkeypatch.setattr(auth, "job_owner", lambda app, j: room.xid)
    assert room.approve(rid)[0] == 404  # the take is not the request's follower's
    monkeypatch.undo()
    assert leftovers(room) == []


def test_one_person_of_a_group_video_cannot_be_approved_and_the_teacher_is_told_so(room: Room, monkeypatch: pytest.MonkeyPatch) -> None:  # AC-MR-20 (R5, R6)
    rid = room.ask(room.take())
    monkeypatch.setattr(my_reference, "is_group", lambda queue, job: True)
    status, doc = room.approve(rid)
    assert status == 409 and "your" not in json.dumps(doc) and "group video" in json.dumps(doc)
    assert leftovers(room) == []
