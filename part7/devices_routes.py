"""Device routes below `api/me/sessions` (docs/specs/devices.md; TICKET-235). `server.py` calls `handle` with the route
below `api/`. Owner only: 401 signed out; a session of another account answers 404, never 403. A POST passes the same
CSRF guard as `api/me/consent`. Logs carry the public id at most, never a session id, an address or a User-Agent."""

from __future__ import annotations

import logging
from typing import Any

from part7 import applog, auth, devices
from part7.auth_routes import MSG_OFF, _fail, _post_body, _reply, _user_or_401

MSG_NOT_FOUND = "That device is not signed in any more."
NO_STORE = {"Cache-Control": "no-store"}


def _list(h: Any) -> None:
    if (user_id := _user_or_401(h)) is not None:
        _reply(h, 200, devices.list_sessions(auth.identity(h.app), user_id, auth.sid_from(h)), NO_STORE)


def _end_one(h: Any, public_id: str) -> None:
    if _post_body(h, fields=False) is None or (user_id := _user_or_401(h)) is None:
        return
    was_current = devices.end_one(auth.identity(h.app), user_id, public_id, auth.sid_from(h))
    if was_current is None:
        return _fail(h, 404, MSG_NOT_FOUND)
    applog.log(f"auth: device ended {public_id}", level=logging.INFO)
    headers = {**NO_STORE, **({"Set-Cookie": auth.cookie_header(h, None)} if was_current else {})}
    _reply(h, 200, {"ended": True, "current": was_current}, headers)


def _end_others(h: Any) -> None:
    if _post_body(h, fields=False) is None or (user_id := _user_or_401(h)) is None:
        return
    count = devices.end_others(auth.identity(h.app), user_id, auth.sid_from(h))
    applog.log(f"auth: other devices ended ({count})", level=logging.INFO)
    _reply(h, 200, {"ended": count}, NO_STORE)


def handle(h: Any, method: str, route: str) -> bool:
    """Answer `me/sessions...`; False for any other route."""
    parts = route.split("/")
    if parts[:2] != ["me", "sessions"]:
        return False
    if not auth.state(h.app).available:  # sign-in off: the feature leaves no trace
        _fail(h, 404, MSG_OFF)
        return True
    if len(parts) == 2 and method in ("GET", "HEAD"):
        _list(h)
    elif parts == ["me", "sessions", "end-others"] and method == "POST":
        _end_others(h)
    elif len(parts) == 4 and parts[3] == "end" and method == "POST":
        _end_one(h, parts[2])
    else:
        return False
    return True
