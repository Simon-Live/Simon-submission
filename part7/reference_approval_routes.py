"""HTTP routes of "teacher approves a student's take as their reference" (docs/specs/my-reference.md, ADR-0019);
`server.py` calls `handle` with the route below `api/`.

    POST api/me/note-requests/<id>/approve-reference   the teacher: approve the take of this open note request
    POST api/me/reference/suggestion                   the student: {entry_id, action: "accept" | "decline"}

The teacher needs an open request the student sent them for an entry the teacher owns (the ask-the-trainer consent,
`notes.get_for_trainer`), so a job id is never guessed. Every refusal toward the teacher is the same 404 (a stranger, a
request of another teacher, a withdrawn or closed request, a private take, an entry marked "only me"); 401 when signed
out. The answer to the teacher carries no student id, name or job id. A POST passes the same CSRF guard as the other `me/` routes.
"""

from __future__ import annotations

import logging
from pathlib import Path
import time
from typing import Any

from part7 import applog, auth, history_store, jobs, labels, my_reference, notes, reference_approval
from part7.auth_routes import _fail, _post_body, _reply, _user_or_401
from part7.my_reference_routes import MSG_BAD_ENTRY, NO_STORE, _Refuse, _skeleton
from part7.notes_routes import _store

MSG_GROUP = "This take shows one person of a group video, so it cannot be this student's reference."
MSG_NOT_FOUND = "This request is not available."
MSG_RATE = "You approved many takes just now. Try again in a minute."
MSG_NO_SUGGESTION = "There is no waiting approval for this movement."
MSG_DECLINED = "The student has already said no to this rep."
MSG_ACTION = "Choose accept or decline."
LIMIT = (10, 60)  # approvals per teacher, seconds (each one runs Part 5's check)


def _limiter(app: Any) -> auth.Limiter:
    found = getattr(app, "_approve_limit", None)
    if found is None:
        found = app._approve_limit = auth.Limiter(*LIMIT)
    return found


def _owned_take(h: Any, teacher: str, row: Any) -> tuple[dict[str, Any], Path]:
    """The job and skeleton path of an open request's take once every rule holds; `_Refuse` otherwise (a refusal toward
    the teacher is a 404 whatever the reason, so nothing says why a take is out of reach)."""
    entry = _store(h).entry_author(row["entry_id"])
    if entry is None or entry["author_state"] != "owned" or entry["user_id"] != teacher or entry["only_me"]:
        raise _Refuse(404, MSG_NOT_FOUND)
    job_id = row["job_id"]
    job = h.app.queue.get(job_id) if jobs.JOB_ID_RE.match(job_id) else None
    if (not job or job.get("kind") != "follow" or job.get("status") != "done" or job.get("entry_id") != row["entry_id"]
            or history_store.is_private(job) or auth.job_owner(h.app, job_id) != row["follower_id"]):
        raise _Refuse(404, MSG_NOT_FOUND)
    if my_reference.is_group(h.app.queue, job):
        raise _Refuse(409, MSG_GROUP)
    return job, Path(h.app.queue.job_dir(job_id)) / "work" / "follower" / "follower.json"


def _approve(h: Any, teacher: str, request_id: str) -> None:
    if _post_body(h, fields=False) is None:
        return
    began = time.time()
    row = notes.get_for_trainer(_store(h), teacher, request_id)
    if row is None or row["state"] != "asked":  # only while the student's request is open: the take is then in the teacher's view
        return _fail(h, 404, MSG_NOT_FOUND)
    try:
        job, path = _owned_take(h, teacher, row)
        if reference_approval.was_declined(h.app.state, row["follower_id"], row["entry_id"], row["job_id"]):
            raise _Refuse(409, MSG_DECLINED)
        if not _limiter(h.app).hit(teacher):
            return _fail(h, 429, MSG_RATE)
        data = _skeleton(h, path)
    except _Refuse as exc:
        return _fail(h, exc.status, exc.message)
    def still_allowed() -> bool:  # runs under the history lock, after the seconds-long Part 5 check (ADR-0019)
        again = notes.get_for_trainer(_store(h), teacher, request_id)
        job_now = h.app.queue.get(row["job_id"])
        return bool(again is not None and again["state"] == "asked" and job_now and job_now.get("status") == "done")

    state = reference_approval.approve(h.app.state, row["follower_id"], row["entry_id"], row["job_id"],
                                       str(job.get("created_at") or "")[:10], data, teacher, since=began, still_allowed=still_allowed)
    if state is None:  # the request was withdrawn, the take or the account went meanwhile
        return _fail(h, 404, MSG_NOT_FOUND)
    applog.log(f"reference approval: {state}", level=logging.INFO)
    _reply(h, 200, {"state": state}, NO_STORE)


def _suggestion(h: Any, student: str) -> None:
    doc = _post_body(h)
    if doc is None:
        return
    entry, action = doc.get("entry_id"), doc.get("action")
    if not isinstance(entry, str) or not labels.ENTRY_ID_RE.match(entry):
        return _fail(h, 400, MSG_BAD_ENTRY)
    if action not in ("accept", "decline"):
        return _fail(h, 400, MSG_ACTION)
    if action == "accept":
        made = reference_approval.accept(h.app.state, student, entry)
        if made is None:
            return _fail(h, 404, MSG_NO_SUGGESTION)
        applog.log("reference approval: accepted", level=logging.INFO)
        return _reply(h, 200, {"entry_id": entry, "reference": my_reference.public(made)}, NO_STORE)
    if not reference_approval.decline(h.app.state, student, entry):
        return _fail(h, 404, MSG_NO_SUGGESTION)
    applog.log("reference approval: declined", level=logging.INFO)
    _reply(h, 200, {"entry_id": entry, "suggestion": None}, NO_STORE)


def handle(h: Any, method: str, route: str) -> bool:
    """Answer the two routes above; False for any other route."""
    parts = route.split("/")
    if method != "POST":
        return False
    if route == "me/reference/suggestion":
        action, arg = _suggestion, None
    elif len(parts) == 4 and parts[:2] == ["me", "note-requests"] and parts[3] == "approve-reference":
        action, arg = _approve, parts[2]
    else:
        return False
    if (user_id := _user_or_401(h)) is not None:
        action(h, user_id) if arg is None else action(h, user_id, arg)
    return True
