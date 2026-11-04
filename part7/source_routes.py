"""HTTP routes of the source and licence credit (docs/specs/source-credit.md; TICKET-322); `server.py` calls `handle`
with the route below `api/`.

`GET source/<entry|take>/<id>` answers `{source, mine, licences}`; `source` is null when none was written, and also for
a viewer who is not the owner when the take is private or its movement "only me" (the answer is the same, so nothing
says that a credit exists). A movement the caller may not view (`auth.may_view_entry`) and another account's take
(`take_access.refusal`) answer 404, as their own routes do (app-surface R1). `POST me/source/<entry|take>/<id>` is the owner's edit: 401 signed out, 403
for anyone else, 404 for an unknown subject, 400 with one sentence for a bad field; all-empty fields clear the source.
Logs carry no field text.
"""

from __future__ import annotations

from typing import Any

from part7 import auth, history_store, identity, labels, share, source_credit, take_access
from part7.auth_routes import _fail, _post_body, _reply, _user_or_401

NO_STORE = {"Cache-Control": "no-store"}
MSG_NOT_YOURS = "Only the person who made this can change its source."
MSG_NONE = "There is nothing here to give a source to."


def _owner(store: Any, kind: str, subject_id: str) -> tuple[str | None, bool]:
    """(owner user id or None, hidden from other viewers) for an entry or a take."""
    if kind == "entry":
        found = store.entry_owner(subject_id)
        return (found[0], found[1]) if found else (None, False)
    return store.owner_of(subject_id), False


def _hidden_take(h: Any, store: Any, job_id: str) -> bool:
    """A take is hidden from others when it ran in private mode or its movement is marked "only me"."""
    job = history_store.read_json(h.app.queue.job_dir(job_id) / "job.json")
    if isinstance(job, dict) and history_store.is_private(job):
        return True
    row = store.fetch("SELECT e.only_me FROM takes t JOIN entries e ON e.entry_id = t.entry_id WHERE t.job_id = ?", (job_id,))
    return bool(row and row[0]["only_me"])


def _well_formed(kind: str, subject_id: str) -> bool:
    """A movement id by the catalog's rule (a shipped sample such as `squat` is short), any other id by the credit's."""
    return bool((labels.ENTRY_ID_RE if kind == "entry" else source_credit.ID_RE).match(subject_id))


def _refused(h: Any, kind: str, subject_id: str) -> tuple[int, str] | None:
    """app-surface R1: the credit of a movement the caller may not view (unpublished, "only me", a minor's) and of
    another account's take answer as a missing one, as the movement's and the take's own routes do."""
    if kind == "entry":
        return None if auth.may_view_entry(h, subject_id) else (404, MSG_NONE)
    return take_access.refusal(h, subject_id)


def _read(h: Any, kind: str, subject_id: str) -> None:
    # a malformed id answers as an unknown one, so the answer never tells a valid id from an invalid one (R4, the team on #61)
    if not _well_formed(kind, subject_id):
        return _fail(h, 404, MSG_NONE)
    if refused := _refused(h, kind, subject_id):
        return _fail(h, *refused)
    viewer = auth.current_user(h)
    if not identity.db_path(h.app.state).is_file():
        return _reply(h, 200, {"source": None, "mine": False, "licences": list(source_credit.LICENCES)}, NO_STORE)
    store = auth.identity(h.app)
    owner, hidden = _owner(store, kind, subject_id)
    mine = bool(viewer and owner == viewer)
    if kind == "take" and owner and not mine:
        hidden = _hidden_take(h, store, subject_id)
    shown = None if (hidden and not mine) else source_credit.get(store, kind, subject_id)
    _reply(h, 200, {"source": shown, "mine": mine, "licences": list(source_credit.LICENCES)}, NO_STORE)


def _write(h: Any, kind: str, subject_id: str) -> None:
    doc = _post_body(h)
    if doc is None or (user_id := _user_or_401(h)) is None:
        return
    store = auth.identity(h.app)
    owner = _owner(store, kind, subject_id)[0] if _well_formed(kind, subject_id) else None
    if owner is None:
        return _fail(h, 404, MSG_NONE)
    if owner != user_id:  # a hidden subject answers as an unknown one, so existence does not leak (R4)
        hidden = _owner(store, kind, subject_id)[1] or (kind == "take" and _hidden_take(h, store, subject_id))
        return _fail(h, 404, MSG_NONE) if hidden else _fail(h, 403, MSG_NOT_YOURS)
    try:
        fields = source_credit.clean(doc)
    except source_credit.SourceError as exc:
        return _fail(h, 400, str(exc))
    _reply(h, 200, {"source": source_credit.put(store, kind, subject_id, user_id, fields), "mine": True}, NO_STORE)


def for_share(h: Any, store: Any, token: str) -> dict[str, str] | None:
    """The take's source for a live share link of kind `take_result`, as a stranger sees it (hidden like any other viewer's);
    None for any other kind or when there is none. The caller has already resolved the token, so the link is live."""
    rows = store.fetch("SELECT kind, item_ref FROM shares WHERE token_hash = ?", (share.token_hash(token),))
    if not rows or rows[0]["kind"] != "take_result" or not source_credit.ID_RE.match(str(rows[0]["item_ref"])):
        return None
    job_id = rows[0]["item_ref"]
    return None if _hidden_take(h, store, job_id) else source_credit.get(store, "take", job_id)


def handle(h: Any, method: str, route: str) -> bool:
    """Answer the source routes (below `api/`); False for any other route."""
    parts = route.split("/")
    if parts[0] == "source" and len(parts) == 3 and parts[1] in source_credit.KINDS and method in ("GET", "HEAD"):
        _read(h, parts[1], parts[2])
        return True
    if parts[:2] == ["me", "source"] and len(parts) == 4 and parts[2] in source_credit.KINDS and method == "POST":
        _write(h, parts[2], parts[3])
        return True
    return False
