"""HTTP routes of "ask the trainer for a note" (docs/specs/notes.md; TICKET-237); `server.py` calls `handle` with the route
below `api/`. Owner only: 401 signed out, 404 for anyone but the follower (their take) or the trainer (their request).
A POST passes the same CSRF guard as `api/me/consent`. Logs carry no id, name or note text.

Someone under 18 sends no grant to a trainer, so no clip goes and no free text comes back (privacy PM-R1): for an
account marked 13 to 17, or a take with that answer, `can_ask` is false and a request is 403 `notes.MSG_MINOR`
(`trainer_publish.minor_refused`). A request already sent stays withdrawable.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import parse_qs, urlsplit

from part7 import (applog, auth, history_store, jobs, labels, model_only, notes, result_media, shown_score,
                   trainer_publish)
from part7.auth_routes import _fail, _post_body, _reply, _user_or_401

NO_STORE = {"Cache-Control": "no-store"}
FAULTS_MAX = 20
NOTICES_MAX = 20
MSG_UNAVAILABLE = "The take is no longer kept, so only the request is shown."


def _store(h: Any) -> Any:
    return auth.identity(h.app)


def _refuse(h: Any, exc: notes.NoteError) -> None:
    _fail(h, exc.status, str(exc))


# ----- reading the take, live and only as far as the follower allowed -----------------------------------
def _analysis(h: Any, row: Any) -> Any:
    found = history_store.read_json(h.app.queue.job_dir(row["job_id"]) / "work" / "follower" / history_store.ANALYSIS_NAME)
    if isinstance(found, dict):
        return found
    copy = next((t for t in history_store.takes(h.app.state, row["follower_id"], row["entry_id"]) if t["job_id"] == row["job_id"]), None)
    return history_store.read_json(copy["analysis"]) if copy else None


def _clip(h: Any, row: Any) -> Any:
    if model_only.view_only(h.app.queue.get(row["job_id"])):  # "Show only my 3D model": no clip of the person (model-default.md AC-MD12)
        return None
    path = result_media.clip_path(h, row["job_id"], None)
    if path is not None:
        return path
    copy = next((t for t in history_store.takes(h.app.state, row["follower_id"], row["entry_id"]) if t["job_id"] == row["job_id"]), None)
    return copy["clip"] if copy and not copy["private"] else None


def _num(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and value == value else None


def _score_doc(analysis: dict[str, Any], light: Any = None) -> dict[str, Any] | None:
    """The score the trainer sees: Part 5's value and grade, and the result headline's score (one-letter.md)."""
    score = analysis.get("score") if isinstance(analysis.get("score"), dict) else {}
    if _num(score.get("value")) is None:
        return None
    return {"value": score["value"], "grade": score.get("grade") if isinstance(score.get("grade"), str) else None,
            "shown": shown_score.of_analysis(analysis, light)}


def _faults(analysis: Any) -> list[dict[str, Any]]:
    """`[{text, at_s}]` as the result page words them; a fault with no time keeps `at_s` None."""
    out = []
    for f in (analysis.get("faults") if isinstance(analysis, dict) else None) or []:
        text = next((f[k] for k in ("text_timed", "text", "coaching") if isinstance(f, dict) and isinstance(f.get(k), str) and f[k]), None)
        if text:
            side = f.get("side") if isinstance(f.get("side"), str) and f["side"] else None
            name = f["measure"] if isinstance(f.get("measure"), str) and f["measure"] else None
            out.append({"text": text, "at_s": _num(f.get("at_s")), "name": f"{name} {side}" if name and side else name})
    return out[:FAULTS_MAX]


def _limit(h: Any, row: Any, analysis: Any, faults: list[dict[str, Any]]) -> float | None:
    """The latest time a note may point at: the take's length (a reported fault time also counts); None when it is not known."""
    try:
        length = history_store.duration_of(h.app.queue.get(row["job_id"]) or {}, h.app.queue.job_dir(row["job_id"]), analysis)[0]
    except Exception:  # an unreadable video leaves the length unknown, so the time is not bounded
        length = None
    return None if length is None else max([length, *[f["at_s"] for f in faults if f["at_s"] is not None]])


def _movement(h: Any, row: Any) -> str:
    return labels.entry_name(h.app.child, row["entry_id"])


def _answer_doc(row: Any) -> dict[str, Any] | None:
    if row["state"] != "answered":
        return None
    return {"note": row["note"], "at_s": row["note_at_s"], "matched_fault": row["matched_fault"], "answered_utc": row["answered_utc"]}


# ----- follower ----------------------------------------------------------------------------------------
def _eligible(h: Any, follower: str, job_id: str) -> dict[str, str]:
    """The entry and trainer of a take that may be sent; `NoteError` 404 for everything else."""
    if not jobs.JOB_ID_RE.match(job_id):
        raise notes.NoteError(notes.MSG_NOT_FOUND, 404)
    found = notes.eligibility(_store(h), follower, job_id)
    job = h.app.queue.get(job_id)
    if not job or job.get("kind") != "follow" or job.get("status") != "done" or history_store.is_private(job):
        raise notes.NoteError(notes.MSG_NOT_FOUND, 404)
    return found


def _request_doc(h: Any, row: Any) -> dict[str, Any]:
    """The follower's view of their request: state, dates, the trainer's author line and, once answered, the note."""
    store = _store(h)
    return {"state": row["state"], "asked_utc": row["asked_utc"], "answered_utc": row["answered_utc"], "include": notes.include_of(row),
            "from": {"name": notes.trainer_name(store, row)}, "answer": _answer_doc(row)}


def _follower_view(h: Any, follower: str, job_id: str) -> None:
    try:
        found = _eligible(h, follower, job_id)
    except notes.NoteError as exc:
        return _refuse(h, exc)
    store = _store(h)
    row = notes.latest_for_job(store, follower, job_id)
    probe = {"job_id": job_id, "entry_id": found["entry_id"], "follower_id": follower}
    minor = trainer_publish.minor_refused(h, follower, h.app.queue.get(job_id))  # PM-R1
    can_ask = not minor and (row is None or row["state"] == "declined")
    _reply(h, 200, {"can_ask": can_ask, "has_clip": _clip(h, probe) is not None,
                    "shown_as": notes.follower_name(store, probe), "include_default": notes.DEFAULT_INCLUDE,
                    "trainer": {"name": notes.trainer_name(store, probe)},
                    "request": _request_doc(h, row) if row is not None else None}, NO_STORE)


def _ask(h: Any, follower: str, job_id: str) -> None:
    doc = _post_body(h)
    if doc is None:
        return
    try:
        found = _eligible(h, follower, job_id)
        if trainer_publish.minor_refused(h, follower, h.app.queue.get(job_id)):  # PM-R1: no grant, no clip, no note
            raise notes.NoteError(notes.MSG_MINOR, 403)
        if doc.get("confirm") is not True:
            raise notes.NoteError(notes.MSG_CONFIRM)
        include = notes.clean_include(doc.get("include"))
        probe = {"job_id": job_id, "entry_id": found["entry_id"], "follower_id": follower}
        if "clip" in include and _clip(h, probe) is None:
            raise notes.NoteError(notes.MSG_NO_CLIP)
        row = notes.create(_store(h), follower, job_id, found, include)
    except notes.NoteError as exc:
        return _refuse(h, exc)
    applog.log("notes: asked", level=logging.INFO)
    _reply(h, 201, {"request": _request_doc(h, row)}, NO_STORE)


def _withdraw(h: Any, follower: str, job_id: str) -> None:
    if _post_body(h, fields=False) is None:
        return
    if not jobs.JOB_ID_RE.match(job_id) or not notes.withdraw(_store(h), follower, job_id):
        return _fail(h, 404, notes.MSG_GONE)
    applog.log("notes: withdrawn", level=logging.INFO)
    _reply(h, 200, {"withdrawn": True}, NO_STORE)


def _received(h: Any, user_id: str) -> None:
    """The follower's notes for one movement: `?entry=<id>`; each with its take number when the copy is kept."""
    entry = parse_qs(urlsplit(h.path).query).get("entry", [""])[0]
    if not labels.ENTRY_ID_RE.match(entry):
        return _fail(h, 404, notes.MSG_GONE)
    kept = {t["job_id"]: t for t in history_store.takes(h.app.state, user_id, entry)}
    store, out = _store(h), []
    for n in notes.notes_for(h.app.state, user_id, entry):
        row = {"job_id": n["job_id"], "entry_id": entry, "follower_id": user_id}
        out.append({"note": n["note"], "at_s": n["at_s"], "matched_fault": n["matched_fault"], "answered_utc": n["answered_utc"], "take": kept.get(n["job_id"], {}).get("take"),
                    "from": {"name": notes.trainer_name(store, row)}})
    _reply(h, 200, {"notes": out}, NO_STORE)


# ----- trainer ------------------------------------------------------------------------------------------
def _list(h: Any, trainer: str) -> None:
    store = _store(h)
    rows = [{"id": r["id"], "movement": _movement(h, r), "asked_utc": r["asked_utc"], "state": r["state"],
             "from": {"name": notes.follower_name(store, r)}} for r in notes.list_for_trainer(store, trainer)]
    _reply(h, 200, {"requests": rows}, NO_STORE)


def _detail_doc(h: Any, row: Any) -> dict[str, Any]:
    """Only what the follower included, and only while the request is open: no job id, user id or email."""
    store = _store(h)
    shown = notes.include_of(row)
    doc: dict[str, Any] = {"id": row["id"], "state": row["state"], "asked_utc": row["asked_utc"], "movement": _movement(h, row),
                           "from": {"name": notes.follower_name(store, row)}, "include": shown, "note_max": notes.NOTE_MAX,
                           "answer": _answer_doc(row), "score": None, "faults": None, "clip": None, "available": True,
                           "can_approve_reference": False}
    if row["state"] != "asked":
        return doc
    analysis = _analysis(h, row)
    if analysis is None:
        doc["available"] = False
        return doc
    doc["can_approve_reference"] = True  # an open request is the consent that lets the trainer approve this take (ADR-0019)
    if "score" in shown:
        doc["score"] = _score_doc(analysis, history_store.light_of(h.app.queue.get(row["job_id"]) or {}))
    if "faults" in shown:
        doc["faults"] = [{"text": f["text"], "at_s": f["at_s"]} for f in _faults(analysis)]
    if "clip" in shown and _clip(h, row) is not None:
        exp, sig = notes.sign_clip(store, row["id"])
        doc["clip"] = f"api/me/note-requests/{row['id']}/clip.mp4?exp={exp}&sig={sig}"
    return doc


def _detail(h: Any, trainer: str, request_id: str) -> None:
    row = notes.get_for_trainer(_store(h), trainer, request_id)
    if row is None:
        return _fail(h, 404, notes.MSG_GONE)
    _reply(h, 200, _detail_doc(h, row), NO_STORE)


def _answer(h: Any, trainer: str, request_id: str) -> None:
    doc = _post_body(h)
    if doc is None:
        return
    store = _store(h)
    row = notes.get_for_trainer(store, trainer, request_id)
    if row is None:
        return _fail(h, 404, notes.MSG_GONE)
    try:
        if row["state"] != "asked":
            raise notes.NoteError(notes.MSG_CLOSED, 409)
        text = notes.clean_note(doc.get("note"))
        analysis = _analysis(h, row)
        faults = _faults(analysis)
        at_s = notes.clean_at(doc.get("at_s"), _limit(h, row, analysis, faults))
        notes.close(store, row, "answered", text, at_s, notes.match_fault(at_s, faults))
    except notes.NoteError as exc:
        return _refuse(h, exc)
    applog.log("notes: answered", level=logging.INFO)
    _reply(h, 200, {"state": "answered"}, NO_STORE)


def _decline(h: Any, trainer: str, request_id: str) -> None:
    if _post_body(h, fields=False) is None:
        return
    store = _store(h)
    row = notes.get_for_trainer(store, trainer, request_id)
    if row is None:
        return _fail(h, 404, notes.MSG_GONE)
    try:
        if row["state"] != "asked":
            raise notes.NoteError(notes.MSG_CLOSED, 409)
        notes.close(store, row, "declined")
    except notes.NoteError as exc:
        return _refuse(h, exc)
    applog.log("notes: declined", level=logging.INFO)
    _reply(h, 200, {"state": "declined"}, NO_STORE)


def _clip_file(h: Any, trainer: str, request_id: str) -> None:
    """The clip of an open request, for the trainer's session and a signature under 60 s old (else one generic 404)."""
    store = _store(h)
    query = parse_qs(urlsplit(h.path).query)
    row = notes.get_for_trainer(store, trainer, request_id)
    path = None
    if (row is not None and row["state"] == "asked" and "clip" in notes.include_of(row)
            and notes.clip_signature_ok(store, request_id, query.get("exp", [None])[0], query.get("sig", [None])[0])):
        path = _clip(h, row)
    if path is None:
        return _fail(h, 404, notes.MSG_GONE)
    result_media.serve_file(h, path)


# ----- notices on the Me page ------------------------------------------------------------------------------
def _notices(h: Any, user_id: str) -> None:
    store = _store(h)
    received = [{"entry_id": r["entry_id"], "movement": _movement(h, r), "answered_utc": r["answered_utc"]}
                for r in notes.unseen_notes(store, user_id)[:NOTICES_MAX]]
    _reply(h, 200, {"waiting": notes.waiting_count(store, user_id), "received": received}, NO_STORE)


def _seen(h: Any, user_id: str) -> None:
    if _post_body(h, fields=False) is None:
        return
    _reply(h, 200, {"seen": notes.mark_seen(_store(h), user_id)}, NO_STORE)


# ----- dispatch -----------------------------------------------------------------------------------------------
def _pick(parts: list[str], method: str) -> Any:
    """`(handler, argument)` for a notes route, or None. Handlers take `(h, user_id)` or `(h, user_id, argument)`."""
    get, post, n = method in ("GET", "HEAD"), method == "POST", len(parts)
    if parts[1] == "takes" and n in (4, 5) and parts[3] == "ask-trainer":
        if n == 4 and (get or post):
            return (_follower_view if get else _ask), parts[2]
        return (_withdraw, parts[2]) if n == 5 and post and parts[4] == "withdraw" else None
    if parts[1] == "note-requests":
        if n == 2 and get:
            return _list, None
        if n == 3 and get:
            return _detail, parts[2]
        if n == 4 and post and parts[3] in ("answer", "decline"):
            return (_answer if parts[3] == "answer" else _decline), parts[2]
        return (_clip_file, parts[2]) if n == 4 and get and parts[3] == "clip.mp4" else None
    if parts[1] == "note-notices":
        return (_notices, None) if n == 2 and get else (_seen, None) if n == 3 and post and parts[2] == "seen" else None
    return (_received, None) if parts[1] == "notes" and n == 2 and get else None


def handle(h: Any, method: str, route: str) -> bool:
    """Answer the notes routes (below `api/`); False for any other route."""
    parts = route.split("/")
    picked = _pick(parts, method) if parts[0] == "me" and len(parts) >= 2 else None
    if picked is None:
        return False
    handler, arg = picked
    if (user_id := _user_or_401(h)) is not None:
        args = (h, user_id) if arg is None else (h, user_id, arg)
        handler(*args)
    return True
