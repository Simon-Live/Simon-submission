"""Profile routes: `api/me/profile` (GET, PUT, DELETE) and `api/avatars` (docs/specs/profile.md).

Owner only: 401 signed out, and the profile read is always the session's own user. `server.py` calls `handle` with the
route below `api/`. A PUT or DELETE passes the same CSRF guard as the other writes. No answer carries an email.
"""

from __future__ import annotations

from typing import Any

from part7 import auth, labels, modes, profile, profile_summary, share
from part7.auth_routes import MSG_OFF, _fail, _post_body, _reply, _user_or_401


def options() -> dict[str, Any]:
    # #415: rehab is off in prod (modes.offered, practice-and-modes.md)
    return {"avatars": list(profile.AVATARS), "modes": list(modes.offered()),
            "goals": [{"key": k, "label": v} for k, v in profile.GOALS.items()], "name_max": profile.NAME_MAX}


def _own(h: Any, user_id: str) -> dict[str, Any]:
    return profile.get_profile(auth.identity(h.app), user_id) or profile.defaults()


def _read(h: Any, user_id: str) -> dict[str, Any]:
    """The profile plus the owner's lists (TICKET-231 AC-5, AC-6). Owner only: every list is read for the session's own user."""
    name_of = lambda entry: labels.entry_name(h.app.child, entry)  # noqa: E731
    owned = auth.identity(h.app).entries_of(user_id)
    entries = profile_summary.entries(h.app.queue.root, owned, name_of)
    return {**_own(h, user_id), "entries": entries, "movements": profile_summary.movements(h.app.state, user_id, name_of),
            "summary": profile_summary.summary(h.app.state, user_id, profile_summary.capped(entries))}


def _put(h: Any) -> None:
    doc = _post_body(h)
    if doc is None or (user_id := _user_or_401(h)) is None:
        return
    try:
        new = profile.update(auth.identity(h.app), user_id, doc)
    except profile.ProfileError as exc:
        return _fail(h, 400, str(exc))
    _reply(h, 200, new, {"Cache-Control": "no-store"})


def _delete(h: Any) -> None:
    if _post_body(h, fields=False) is None or (user_id := _user_or_401(h)) is None:
        return
    store = auth.identity(h.app)
    profile.delete(store, user_id)
    share.revoke_all(store, user_id)  # the page promises it: deleting profile details ends every share link
    _reply(h, 200, {"deleted": True, **profile.defaults()}, {"Cache-Control": "no-store"})


def handle(h: Any, method: str, route: str) -> bool:
    """Answer `me/profile` and `avatars`; False for any other route."""
    if route not in ("me/profile", "avatars"):
        return False
    if not auth.state(h.app).available:  # sign-in off: the feature leaves no trace
        _fail(h, 404, MSG_OFF)
        return True
    get = method in ("GET", "HEAD")
    if route == "avatars" and get:
        if _user_or_401(h) is not None:
            _reply(h, 200, options())
    elif route == "me/profile" and get:
        if (user_id := _user_or_401(h)) is not None:
            _reply(h, 200, _read(h, user_id), {"Cache-Control": "no-store"})
    elif route == "me/profile" and method == "PUT":
        _put(h)
    elif route == "me/profile" and method == "DELETE":
        _delete(h)
    else:
        return False
    return True
