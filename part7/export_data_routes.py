"""`GET api/me/export`: download my data (docs/specs/export-data.md, TICKET-236).

Owner only: 401 signed out (the sign-in text of the other `me/` routes); with sign-in off `auth_routes` already
answers 404 first. Five files per person per hour (429). The file is built in memory, served as an attachment with
`no-store` and never written to disk. No model call and no ledger line. An error answers no file.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from part7 import applog, auth, export_data
from part7.auth_routes import _fail, _user_or_401

LIMIT = (5, 3600)  # exports per person, seconds
MSG_RATE = "You have downloaded your data five times in the last hour. Try again later."
MSG_FAILED = "Your data could not be put together. Nothing was downloaded. Try again in a moment."


def _limiter(app: Any) -> auth.Limiter:
    found = getattr(app, "_export_limit", None)
    if found is None:
        found = app._export_limit = auth.Limiter(*LIMIT)
    return found


def _get(h: Any) -> None:
    if (user_id := _user_or_401(h)) is None:
        return
    if not _limiter(h.app).hit(user_id):
        return _fail(h, 429, MSG_RATE)
    now = datetime.fromtimestamp(auth.CLOCK(), timezone.utc)
    ctx = export_data.Ctx(state=h.app.state, store=auth.identity(h.app), user_id=user_id, child=getattr(h.app, "child", None))
    try:
        data = export_data.build(ctx, now)
    except export_data.ExportError as exc:
        applog.log(f"export: failed for {user_id}: {exc}")
        return _fail(h, 500, MSG_FAILED)
    name = export_data.filename(now)
    h._send(200, data, "application/json; charset=utf-8",
            {"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"})


def handle(h: Any, method: str, route: str) -> bool:
    """Answer `me/export`; False for any other route."""
    if route != "me/export" or method not in ("GET", "HEAD"):
        return False
    _get(h)
    return True
