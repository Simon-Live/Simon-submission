"""`GET api/me/export` and `GET api/me/export.zip`: download my data (docs/specs/export-data.md, TICKET-236, LEG-M3).

Owner only: 401 signed out (the sign-in text of the other `me/` routes); with sign-in off `auth_routes` already
answers 404 first. The JSON file is built in memory,
served as an attachment with `no-store` and never written to disk. The ZIP (the JSON plus the person's video and
per-take files) is written to a private file in `<state>/tmp`, streamed, and removed when the answer ends, whatever
happens; one left by a crash goes with the next download after an hour. No model call and no ledger line. An error
answers no file.
"""

from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import secrets
from typing import Any

from part7 import applog, auth, export_data, quota
from part7.auth_routes import _fail, _user_or_401

CHUNK = 256 * 1024
MSG_FAILED = "Your data could not be put together. Nothing was downloaded. Try again in a moment."
ROUTES = ("me/export", "me/export.zip")


def tmp_dir(app: Any) -> Path:
    return Path(app.state) / "tmp"


def _send_zip(h: Any, ctx: export_data.Ctx, user_id: str, now: datetime) -> None:
    from part7 import delete_routes  # every movement the person recorded, also after its take is gone

    folder = tmp_dir(h.app)
    low = quota.disk_refusal(h.app.state)  # security audit R7: no ZIP is written past the free-disk floor
    if low:
        return _fail(h, 503, low)
    folder.mkdir(parents=True, exist_ok=True)
    export_data.sweep_zips(folder)
    target = folder / f"{export_data.ZIP_PREFIX}{secrets.token_hex(8)}.zip"
    try:
        try:
            size = export_data.write_zip(ctx, target, now, delete_routes.account_entries(h.app, user_id))
        except export_data.ExportError as exc:
            applog.log(f"export: zip failed for {user_id}: {exc}")
            return _fail(h, 500, MSG_FAILED)
        h.send_response(200)
        for key, value in (("Content-Type", "application/zip"), ("Content-Length", str(size)), ("Cache-Control", "no-store"),
                           ("Content-Disposition", f'attachment; filename="{export_data.filename(now, "zip")}"'),
                           ("Referrer-Policy", "no-referrer")):
            h.send_header(key, value)
        h.end_headers()
        if h.command == "HEAD":
            return
        with target.open("rb") as src:
            while block := src.read(CHUNK):
                h.wfile.write(block)
    except (BrokenPipeError, ConnectionResetError):
        pass  # the browser left mid-download
    finally:
        try:
            os.unlink(target)
        except FileNotFoundError:
            pass


def _get(h: Any, route: str) -> None:
    if (user_id := _user_or_401(h)) is None:
        return
    now = datetime.fromtimestamp(auth.CLOCK(), timezone.utc)
    ctx = export_data.Ctx(state=h.app.state, store=auth.identity(h.app), user_id=user_id, child=getattr(h.app, "child", None))
    if route == "me/export.zip":
        return _send_zip(h, ctx, user_id, now)
    try:
        data = export_data.build(ctx, now)
    except export_data.ExportError as exc:
        applog.log(f"export: failed for {user_id}: {exc}")
        return _fail(h, 500, MSG_FAILED)
    name = export_data.filename(now)
    h._send(200, data, "application/json; charset=utf-8",
            {"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"})


def handle(h: Any, method: str, route: str) -> bool:
    """Answer `me/export` and `me/export.zip`; False for any other route."""
    if route not in ROUTES or method not in ("GET", "HEAD"):
        return False
    _get(h, route)
    return True
