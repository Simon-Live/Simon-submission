"""Signed-in devices: the sessions of one account, listed and ended (docs/specs/devices.md; TICKET-235).

Two additive columns on `sessions` in identity.db: `public_id` (12 random hex, the handle the list uses, never derived
from the session id) and `device` (a coarse label such as "Firefox on Android" built from the User-Agent by a fixed word
list). The User-Agent and the address are never stored. `store` below is the `IdentityStore` (its connection, lock and
clock are used). Every query names the caller's user id, so another account's session is never listed or ended.
"""

from __future__ import annotations

from pathlib import Path
import re
import secrets
import sqlite3
from typing import Any

from part7 import identity as ident

UNKNOWN = "Unknown browser"
LABEL_MAX = 40
BACKUP_NAME = "identity.db.pre-devices"
ID_RE = re.compile(r"^[0-9a-f]{12}$")

# First match wins, so Edge and Opera (which also say Chrome) come before Chrome, and Chrome before Safari.
_BROWSERS = (("Edge", ("edg/", "edga/", "edgios/")), ("Opera", ("opr/",)), ("Firefox", ("firefox/", "fxios/")),
             ("Chrome", ("chrome/", "crios/")), ("Safari", ("safari/",)))
_SYSTEMS = (("Android", ("android",)), ("iPhone", ("iphone",)), ("iPad", ("ipad",)), ("Windows", ("windows",)),
            ("macOS", ("mac os x", "macintosh")), ("ChromeOS", ("cros",)), ("Linux", ("linux", "x11")))

_COLUMNS = (("public_id", "TEXT"), ("device", "TEXT"))


def device_label(user_agent: Any) -> str:
    """"Firefox on Android" from a User-Agent, from the word lists above only; `UNKNOWN` when nothing is recognised."""
    text = user_agent.lower() if isinstance(user_agent, str) else ""
    browser = next((name for name, keys in _BROWSERS if any(k in text for k in keys)), None)
    system = next((name for name, keys in _SYSTEMS if any(k in text for k in keys)), None)
    if browser and system:
        return f"{browser} on {system}"[:LABEL_MAX]
    if browser:
        return browser
    return f"{UNKNOWN} on {system}"[:LABEL_MAX] if system else UNKNOWN


def new_public_id() -> str:
    return secrets.token_hex(6)


def _backup(conn: sqlite3.Connection, path: Path) -> None:
    """Copy the database beside itself (sqlite backup, so WAL content is included); raise if that fails."""
    target = None
    backup = Path(path).with_name(BACKUP_NAME)
    try:
        target = sqlite3.connect(str(backup))
        conn.backup(target)
        target.close()
        backup.chmod(0o600)
    except (sqlite3.Error, OSError) as exc:
        if target is not None:
            target.close()
        backup.unlink(missing_ok=True)
        raise RuntimeError(f"devices migration refused: backup copy failed ({type(exc).__name__})") from exc


def migrate(conn: sqlite3.Connection, path: Path) -> None:
    """Add `public_id` and `device` to `sessions`, give old rows an id and "Unknown browser", index the id. Additive and
    idempotent; no other column is written. Before the first change on a database with accounts the file is copied
    beside it, and if the copy fails this raises and nothing changes."""
    have = {row[1] for row in conn.execute("PRAGMA table_info(sessions)")}
    missing = [(name, kind) for name, kind in _COLUMNS if name not in have]
    if missing:
        if conn.execute("SELECT 1 FROM users LIMIT 1").fetchone() and not Path(path).with_name(BACKUP_NAME).exists():
            _backup(conn, path)
        for name, kind in missing:
            conn.execute(f"ALTER TABLE sessions ADD COLUMN {name} {kind}")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS sessions_public_id ON sessions (public_id)")
    for row in conn.execute("SELECT rowid FROM sessions WHERE public_id IS NULL").fetchall():
        conn.execute("UPDATE sessions SET public_id = ? WHERE rowid = ?", (new_public_id(), row[0]))
    conn.execute("UPDATE sessions SET device = ? WHERE device IS NULL", (UNKNOWN,))


def _hour(ts: float) -> str:
    return ident._iso(ts - ts % 3600)


def _live(store: Any, user_id: str) -> list[sqlite3.Row]:
    now = store.clock()
    return store._q(
        "SELECT sid_hash, public_id, device, created_at, last_seen_at FROM sessions "
        "WHERE user_id = ? AND expires_at > ? AND last_seen_at + ? > ? ORDER BY created_at DESC, public_id",
        (user_id, now, ident.SESSION_IDLE_S, now))


def list_sessions(store: Any, user_id: str, current_sid: str | None) -> list[dict[str, Any]]:
    """The caller's live sessions, newest first. Times are rounded to the hour; `current` marks the asking browser."""
    mine = ident._sha(current_sid) if current_sid else None
    return [{"id": r["public_id"], "device": r["device"] or UNKNOWN, "signed_in": _hour(r["created_at"]),
             "last_active": _hour(r["last_seen_at"]), "current": r["sid_hash"] == mine} for r in _live(store, user_id)]


def end_one(store: Any, user_id: str, public_id: str, current_sid: str | None) -> bool | None:
    """End one session of `user_id`. None when there is no such live session of theirs (also for another account's);
    else True when it was the asking browser's own session."""
    if not isinstance(public_id, str) or not ID_RE.match(public_id):
        return None
    mine = ident._sha(current_sid) if current_sid else None
    with store._lock:
        row = next((r for r in _live(store, user_id) if r["public_id"] == public_id), None)
        if row is None:
            return None
        store._db.execute("DELETE FROM sessions WHERE sid_hash = ? AND user_id = ?", (row["sid_hash"], user_id))
        return row["sid_hash"] == mine


def end_others(store: Any, user_id: str, current_sid: str | None) -> int:
    """End every session of `user_id` except the asking browser's own; returns how many were ended."""
    mine = ident._sha(current_sid) if current_sid else ""
    with store._lock:
        return store._db.execute("DELETE FROM sessions WHERE user_id = ? AND sid_hash != ?", (user_id, mine)).rowcount


def export_rows(ctx: Any) -> list[dict[str, Any]]:
    """The person's live sessions for "Download my data": device and hour-rounded times; no session id, public id or hash."""
    return [{"device": r["device"] or UNKNOWN, "signed_in": _hour(r["created_at"]), "last_active": _hour(r["last_seen_at"])}
            for r in _live(ctx.store, ctx.user_id)]
