"""HTTP routes of "my reference" (docs/specs/my-reference.md, ADR-0019); `server.py` calls `handle` with the route below `api/`.

    GET  api/me/reference?entry=<id>   the caller's reference for a movement, or null
    POST api/me/reference              {job_id}: make one of the caller's finished takes the reference (replaces)
    POST api/me/reference/remove       {entry_id}: remove it; later takes use the teacher's clip again

Owner only: 401 signed out; a take that is not the caller's answers the same 404 as a take that does not exist.
POST passes the same CSRF guard as the other `me/` routes. Nothing here reads another person's reference.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from part7 import applog, auth, history_store, jobs, labels, my_reference, notes, reference_approval
from part7.auth_routes import _fail, _post_body, _reply, _user_or_401
from part7.parts import p5_analyse

NO_STORE = {"Cache-Control": "no-store"}
MSG_NOT_FOUND = "This take was not found."
MSG_NOT_FINISHED = "Mark a take as your reference when it has finished."
MSG_PRIVATE = "A private take cannot be your reference, because Simon keeps no movement data for it."
MSG_UNUSABLE = "This take cannot be your reference, because Simon cannot compare other takes with it."
MSG_GROUP = "A take of one person in a group video cannot be your reference."
MSG_BAD_ENTRY = "Pick a movement."
MSG_GONE = "You have no reference for this movement."


def accepts(app: Any, data: bytes) -> bool:
    """Part 5's doctor decides whether the take's skeleton can be an expected clip (the check a skeleton-only entry gets)."""
    return p5_analyse.accepts_expected(data, app.state / "tmp", app.lock)


def _eligible_job(h: Any, user_id: str, job_id: Any) -> tuple[dict[str, Any], Path]:
    """The job record and the path of the take's `follower.json`; a refusal is raised as `_Refuse(status, message)`."""
    if not isinstance(job_id, str) or not jobs.JOB_ID_RE.match(job_id):
        raise _Refuse(404, MSG_NOT_FOUND)
    job = h.app.queue.get(job_id)
    if auth.job_owner(h.app, job_id) != user_id or not job or job.get("kind") != "follow" or not labels.ENTRY_ID_RE.match(str(job.get("entry_id") or "")):
        raise _Refuse(404, MSG_NOT_FOUND)
    if job.get("status") != "done":
        raise _Refuse(409, MSG_NOT_FINISHED)
    if history_store.is_private(job):
        raise _Refuse(409, MSG_PRIVATE)
    if my_reference.is_group(h.app.queue, job):  # one person of a group video is not the signed-in student
        raise _Refuse(409, MSG_GROUP)
    return job, Path(h.app.queue.job_dir(job_id)) / "work" / "follower" / "follower.json"


def _skeleton(h: Any, path: Path) -> bytes:
    """The bytes of the take's skeleton once Part 5 accepts them; `_Refuse` 422 otherwise."""
    try:
        data = path.read_bytes() if history_store.read_json(path) is not None else b""
    except OSError:
        data = b""
    if not data or not accepts(h.app, data):
        raise _Refuse(422, MSG_UNUSABLE)
    return data


class _Refuse(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status, self.message = status, message


def _teacher_answered(h: Any, user_id: str, job_id: str) -> bool:
    """True when the teacher answered a note request about this take (the teacher loop link, when it exists)."""
    try:
        row = notes.latest_for_job(auth.identity(h.app), user_id, job_id)
        return bool(row is not None and row["state"] == "answered")
    except Exception as exc:  # the link is optional: a store fault records "no"
        applog.log(f"my reference: teacher link unavailable ({type(exc).__name__})", level=logging.WARNING)
        return False


def _get(h: Any, user_id: str) -> None:
    entry = parse_qs(urlsplit(h.path).query).get("entry", [""])[0]
    if not labels.ENTRY_ID_RE.match(entry):
        return _fail(h, 400, MSG_BAD_ENTRY)
    found = my_reference.meta(h.app.state, user_id, entry)
    _reply(h, 200, {"entry_id": entry, "reference": my_reference.public(found),
                    "fell_back": bool(found and found["state"] == "deleted"),
                    "suggestion": reference_approval.public_suggestion(reference_approval.suggestion(h.app.state, user_id, entry))}, NO_STORE)


def _set(h: Any, user_id: str) -> None:
    doc = _post_body(h)
    if doc is None:
        return
    try:
        job, path = _eligible_job(h, user_id, doc.get("job_id"))
        entry = job["entry_id"]
        same = my_reference.meta(h.app.state, user_id, entry)
        if same and same["state"] == "ok" and same["job_id"] == job["id"]:  # nothing changes: no check, no rewrite
            return _reply(h, 200, {"entry_id": entry, "reference": my_reference.public(same)}, NO_STORE)
        data = _skeleton(h, path)
    except _Refuse as exc:
        return _fail(h, exc.status, exc.message)
    made = my_reference.set_reference(h.app.state, user_id, entry, job["id"], str(job.get("created_at") or "")[:10], data,
                                      _teacher_answered(h, user_id, job["id"]))
    applog.log("my reference: set", level=logging.INFO)
    _reply(h, 200, {"entry_id": entry, "reference": my_reference.public(made)}, NO_STORE)


def _remove(h: Any, user_id: str) -> None:
    doc = _post_body(h)
    if doc is None:
        return
    entry = doc.get("entry_id")
    if not isinstance(entry, str) or not labels.ENTRY_ID_RE.match(entry):
        return _fail(h, 400, MSG_BAD_ENTRY)
    had = my_reference.meta(h.app.state, user_id, entry)
    if had and had["state"] == "ok" and had.get("approved_by"):  # the student's removal wins: that take is not approved again
        reference_approval.note_declined(h.app.state, user_id, entry, had["job_id"])
    if not my_reference.remove(h.app.state, user_id, entry):
        return _fail(h, 404, MSG_GONE)
    applog.log("my reference: removed", level=logging.INFO)
    _reply(h, 200, {"entry_id": entry, "reference": None}, NO_STORE)


def handle(h: Any, method: str, route: str) -> bool:
    """Answer the three routes above; False for any other route."""
    table = {("GET", "me/reference"): _get, ("HEAD", "me/reference"): _get, ("POST", "me/reference"): _set,
             ("POST", "me/reference/remove"): _remove}
    if not route.startswith("me/reference"):
        return False
    action = table.get((method, route))
    if action is None:
        return False
    if (user_id := _user_or_401(h)) is not None:
        action(h, user_id)
    return True
