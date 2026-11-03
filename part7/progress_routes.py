"""HTTP routes of the measure-only home programme and its progress sheet (docs/specs/progress-sheet.md, TICKET-283).

- `GET api/me/progress/<entry>`: the signed-in person's sheet (401 signed out, 404 with no tracked take of theirs).
- `GET api/programmes`: the joint angles a programme can follow. `GET api/programmes/<entry>`: the declared one (public, 404 none).
- `PUT` (or `POST`) `api/programmes/<entry> {primary_measure}` and `DELETE api/programmes/<entry>`: the entry's owner only (401
  signed out, 404 for anyone else, 403 without a same-origin JSON request, 400 for a measure not listed).
Sharing the sheet is `POST api/shares {kind: "progress_sheet", item_ref: <entry>}`; deleting it is
`DELETE api/me/shares/<id>` (share_routes.py). `server.py` calls `handle(h, method, route)` with `route` below `api/`.
"""

from __future__ import annotations

from typing import Any

from part7 import auth, labels, programme, progress_sheet
from part7.auth_routes import MSG_CSRF, MSG_SIGN_IN, _fail, _post_body, _reply

MSG_NONE = "There is nothing here."
MSG_METHOD = "Method not allowed."


def _sheet(h: Any, entry: str) -> None:
    owner = auth.current_user(h)
    if owner is None:
        return _fail(h, 401, MSG_SIGN_IN)
    sheet = progress_sheet.build(h.app.state, owner, entry, labels.entry_name(h.app.child, entry, h.app.state))
    if sheet is None:
        return _fail(h, 404, MSG_NONE)
    _reply(h, 200, sheet)


def _owns_entry(h: Any, user: str, entry: str) -> bool:
    found = auth.identity(h.app).entry_owner(entry)
    return bool(found and found[0] == user)


def _change(h: Any, method: str, entry: str) -> None:
    user = auth.current_user(h)
    if user is None:
        return _fail(h, 401, MSG_SIGN_IN)
    if method == "DELETE" and not auth.origin_ok(h):
        return _fail(h, 403, MSG_CSRF)
    doc = _post_body(h) if method in ("POST", "PUT") else {}
    if doc is None:
        return None
    if not _owns_entry(h, user, entry):
        return _fail(h, 404, MSG_NONE)
    if method == "DELETE":
        return _reply(h, 200, {"removed": programme.remove(h.app.state, entry)})
    try:
        _reply(h, 200, programme.save(h.app.state, entry, doc.get("primary_measure")))
    except ValueError as exc:
        _fail(h, 400, str(exc))


def _programmes(h: Any, method: str, parts: list[str]) -> None:
    if len(parts) == 1:
        if method not in ("GET", "HEAD"):
            return _fail(h, 405, MSG_METHOD)
        return _reply(h, 200, {"measures": [{"name": k, "label": v} for k, v in programme.LABELS.items()]})
    entry = parts[1]
    if not labels.ENTRY_ID_RE.match(entry):
        return _fail(h, 404, MSG_NONE)
    if method in ("GET", "HEAD"):
        found = programme.get(h.app.state, entry)
        return _reply(h, 200, found) if found else _fail(h, 404, MSG_NONE)
    if method in ("POST", "PUT", "DELETE"):  # PUT is the trainer form's verb (TICKET-283); POST stays for older callers
        return _change(h, method, entry)
    _fail(h, 405, MSG_METHOD)


def handle(h: Any, method: str, route: str) -> bool:
    """Answer `route` (below `api/`) when it is a programme or progress-sheet route; False when it is not."""
    parts = route.split("/")
    if parts[0] == "programmes" and len(parts) in (1, 2):
        _programmes(h, method, parts)
        return True
    if parts[:2] == ["me", "progress"] and len(parts) == 3:
        if method not in ("GET", "HEAD"):
            _fail(h, 405, MSG_METHOD)
        elif not labels.ENTRY_ID_RE.match(parts[2]):
            _fail(h, 404, MSG_NONE)
        else:
            _sheet(h, parts[2])
        return True
    return False
