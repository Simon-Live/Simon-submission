"""HTTP route of "Takes on this movement" (docs/specs/takes-on-movement.md, TICKET-327); `server.py` calls `handle`.

`GET api/takes-on/<entry>[?jobs=<id>,<id>]` answers `{entry_id, signed_in, mine, shared, followers}` (rows in
`part7/takes_on.py`). Signed out is not refused: the browser's own takes and the public boards still answer. A movement
its owner marked "only me" is 404 for everyone else (`auth.may_view_entry`, as the teacher page). One client may ask
`PER_CLIENT` times a window (429 after). `no-store` and `no-referrer`: the answer is per caller.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import parse_qs, urlsplit

from part7 import attribution, auth, challenges, takes_on

MSG_NO_ENTRY = "This movement is not in the catalog."
MSG_METHOD = "Method not allowed."
MSG_RATE = "Too many requests. Wait a little, then try again."
HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}
PER_CLIENT = (60, 60)  # requests, seconds
_LIMIT: dict[int, auth.Limiter] = {}


def _reply(h: Any, status: int, doc: dict[str, Any], extra: dict[str, str] | None = None) -> None:
    h._send(status, json.dumps(doc).encode("utf-8"), "application/json; charset=utf-8", {**HEADERS, **(extra or {})})


def _refuse(h: Any, status: int, message: str, extra: dict[str, str] | None = None) -> None:
    _reply(h, status, {"ok": False, "error": message, "message": message}, extra)


def handle(h: Any, method: str, route: str) -> bool:
    """Answer `route` (below `api/`) when it is `takes-on/<entry>`; False when it is not."""
    parts = route.split("/")
    if parts[0] != "takes-on" or len(parts) != 2:
        return False
    if method not in ("GET", "HEAD"):
        _refuse(h, 405, MSG_METHOD)
        return True
    if not _LIMIT.setdefault(id(h.app), auth.Limiter(*PER_CLIENT)).hit(auth.client_key(h)):
        _refuse(h, 429, MSG_RATE, {"Retry-After": str(PER_CLIENT[1])})
        return True
    entry_id = parts[1]
    if not challenges.ENTRY_ID_RE.match(entry_id) or h.app.child.get_entry(entry_id) is None or not auth.may_view_entry(h, entry_id):
        _refuse(h, 404, MSG_NO_ENTRY)
        return True
    user = auth.current_user(h)
    device = takes_on.device_ids((parse_qs(urlsplit(h.path).query).get("jobs") or [""])[0])
    _reply(h, 200, {
        "entry_id": entry_id, "signed_in": user is not None,
        "mine": takes_on.mine(h, entry_id, user, device),
        "shared": takes_on.shared(h, entry_id, user, device),
        "followers": user is not None and attribution.for_entry(h, entry_id).get("mine") is True,  # the class table's own rule
    })
    return True
