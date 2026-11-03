"""Signed, revocable share links (docs/specs/share.md, TICKET-233).

A share is a grant on one snapshot, never a job id. The token is `base64url(share_id) "." base64url(HMAC-SHA256(key,
share_id))`; only `sha256(token)` is stored. `key` is derived from the auth pepper (HKDF-style, extract then expand,
info `simon7-share-v1`), so a pepper leak is the only way to forge a token and the pepper is never printed. The snapshot
is taken when the share is made and is the only thing a viewer ever gets: later edits, other takes and other users
never reach it. `db` is the `identity.IdentityStore`; the `shares` table is additive and made once, after a copy of
the database file (a failed copy refuses the migration).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
from typing import Any

from part7 import identity as ident

KINDS = ("take_result", "progress_card", "history_report", "progress_sheet")
OFFERED_KINDS = ("take_result", "history_report", "progress_sheet")  # progress_card waits for TICKET-227, which is not merged
DELETED_ON_REVOKE = ("progress_sheet",)  # TICKET-283: ending a progress-sheet link deletes its stored copy too
DAYS = (1, 7, 30)
MAX_ACTIVE = 20
MAX_PER_HOUR = 10
INFO = b"simon7-share-v1"
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}\.[A-Za-z0-9_-]{43}$")
HASH_RE = re.compile(r"^[0-9a-f]{64}$")

MSG_KIND = "That kind of share is not available yet."
MSG_DAYS = "Choose 1, 7 or 30 days."
MSG_LIMIT_ACTIVE = "You have 20 active share links. Revoke one to make another."
MSG_LIMIT_HOUR = "You made 10 share links in the last hour. Try again later."
MSG_MIGRATION = "Sharing is not available right now."

_COLUMNS = "token_hash, owner_id, kind, item_ref, snapshot, show_name, show_clip, created_utc, expires_utc, revoked_utc"
_TABLE = """
CREATE TABLE {name} (
  token_hash TEXT PRIMARY KEY, owner_id TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('take_result', 'progress_card', 'history_report', 'progress_sheet')),
  item_ref TEXT NOT NULL, snapshot TEXT NOT NULL, show_name INTEGER NOT NULL DEFAULT 0, show_clip INTEGER NOT NULL DEFAULT 0,
  created_utc TEXT NOT NULL, expires_utc TEXT NOT NULL, revoked_utc TEXT);
"""
_INDEXES = """
CREATE INDEX IF NOT EXISTS shares_owner ON shares (owner_id, created_utc);
CREATE INDEX IF NOT EXISTS shares_item ON shares (item_ref);
"""
# TICKET-283: SQLite cannot widen a CHECK in place, so a table made before `progress_sheet` is rebuilt in one transaction.
_REBUILD = ("BEGIN IMMEDIATE;" + _TABLE.format(name="shares_v2") + f"INSERT INTO shares_v2 ({_COLUMNS}) SELECT {_COLUMNS} FROM shares;"
            "DROP TABLE shares; ALTER TABLE shares_v2 RENAME TO shares;" + _INDEXES + "COMMIT;")


class ShareError(ValueError):
    """A refusal with a sentence a person can read; `status` is the HTTP answer (400, 429 or 503)."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def signing_key(pepper: bytes) -> bytes:
    """HKDF (RFC 5869) with SHA-256: extract with a fixed salt, expand one block with `INFO`."""
    prk = hmac.new(b"simon7-share-salt", pepper, hashlib.sha256).digest()
    return hmac.new(prk, INFO + b"\x01", hashlib.sha256).digest()


def _sign(db: ident.IdentityStore, share_id: str) -> str:
    return _b64(hmac.new(signing_key(db.pepper), share_id.encode("ascii"), hashlib.sha256).digest())


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _takes_sheets(db: ident.IdentityStore) -> bool:
    rows = db.fetch("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'shares'")
    return bool(rows) and "progress_sheet" in str(rows[0]["sql"])


def ensure_schema(db: ident.IdentityStore) -> None:
    """Make the table once, and widen a table made before `progress_sheet` (TICKET-283) once. Before either migration
    the database file is copied (`identity.db.pre-shares`, `identity.db.pre-progress-sheet`); when that copy fails the
    migration does not run. A second call changes nothing."""
    exists = db.has_table("shares")
    if exists and _takes_sheets(db):
        return
    target = ident.db_path(db.state).with_name("identity.db.pre-progress-sheet" if exists else "identity.db.pre-shares")
    try:
        db.backup_to(target)
    except Exception as exc:
        raise ShareError(MSG_MIGRATION, 503) from exc
    if exists:
        db.write_script(_REBUILD)
        return
    db.write(_TABLE.format(name="IF NOT EXISTS shares").strip())
    for statement in filter(None, (s.strip() for s in _INDEXES.split(";"))):
        db.write(statement)


def _iso(ts: float) -> str:
    return ident._iso(ts)


def create_share(db: ident.IdentityStore, owner_id: str, kind: str, item_ref: str, show_name: bool, show_clip: bool,
                 days: int, *, snapshot: dict[str, Any]) -> str:
    """Make one share and return its token (shown once, never stored). `snapshot` is the item as it is now."""
    if kind not in OFFERED_KINDS:
        raise ShareError(MSG_KIND)
    if isinstance(days, bool) or days not in DAYS:
        raise ShareError(MSG_DAYS)
    ensure_schema(db)
    now = db.clock()
    active = db.fetch("SELECT COUNT(*) AS n FROM shares WHERE owner_id = ? AND revoked_utc IS NULL AND expires_utc > ?",
                      (owner_id, _iso(now)))[0]["n"]
    recent = db.fetch("SELECT COUNT(*) AS n FROM shares WHERE owner_id = ? AND created_utc > ?", (owner_id, _iso(now - 3600)))[0]["n"]
    if active >= MAX_ACTIVE:
        raise ShareError(MSG_LIMIT_ACTIVE, 429)
    if recent >= MAX_PER_HOUR:
        raise ShareError(MSG_LIMIT_HOUR, 429)
    share_id = secrets.token_urlsafe(12)
    token = f"{share_id}.{_sign(db, share_id)}"
    db.write(
        "INSERT INTO shares (token_hash, owner_id, kind, item_ref, snapshot, show_name, show_clip, created_utc, expires_utc) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (token_hash(token), owner_id, kind, item_ref, json.dumps(snapshot, separators=(",", ":")), int(bool(show_name)),
         int(bool(show_clip)), _iso(now), _iso(now + days * 86400)))
    return token


def _row(db: ident.IdentityStore, token: Any) -> Any | None:
    """The live row for a token, or None: tampered, unknown, expired and revoked all look the same."""
    if not isinstance(token, str) or not TOKEN_RE.match(token) or not db.has_table("shares"):
        return None
    share_id, mac = token.split(".")
    if not hmac.compare_digest(_sign(db, share_id), mac):
        return None
    rows = db.fetch("SELECT * FROM shares WHERE token_hash = ?", (token_hash(token),))
    if not rows or rows[0]["revoked_utc"] is not None or rows[0]["expires_utc"] <= _iso(db.clock()):
        return None
    return rows[0]


def resolve(db: ident.IdentityStore, token: Any) -> dict[str, Any] | None:
    """The snapshot a viewer may see, or None. Nothing is cached, so a revoke ends the link on the next request."""
    row = _row(db, token)
    if row is None:
        return None
    snap = json.loads(row["snapshot"])
    return {**snap, "kind": row["kind"], "expires_utc": row["expires_utc"]}


def clip_grant(db: ident.IdentityStore, token: Any) -> tuple[str, str] | None:
    """`(owner_id, job_id)` when the token is live, is a take result and its owner ticked the clip; else None."""
    row = _row(db, token)
    if row is None or row["kind"] != "take_result" or not row["show_clip"]:
        return None
    return row["owner_id"], row["item_ref"]


def revoke(db: ident.IdentityStore, owner_id: str, hash_: str) -> bool:
    """Mark the owner's share revoked; False when it is not theirs (the route answers 404)."""
    if not isinstance(hash_, str) or not HASH_RE.match(hash_) or not db.has_table("shares"):
        return False
    rows = db.fetch("SELECT kind FROM shares WHERE token_hash = ? AND owner_id = ?", (hash_, owner_id))
    if not rows:
        return False
    if rows[0]["kind"] in DELETED_ON_REVOKE:  # the row is the sheet's only copy: it goes, so the link answers 404 at once
        db.write("DELETE FROM shares WHERE token_hash = ? AND owner_id = ?", (hash_, owner_id))
        return True
    db.write("UPDATE shares SET revoked_utc = ? WHERE token_hash = ? AND owner_id = ? AND revoked_utc IS NULL",
             (_iso(db.clock()), hash_, owner_id))
    return True


def revoke_all(db: ident.IdentityStore, owner_id: str) -> int:
    """End every live share of one owner (deleting profile details ends every share link); returns how many."""
    if not db.has_table("shares"):
        return 0
    gone = db.write("DELETE FROM shares WHERE owner_id = ? AND kind = 'progress_sheet'", (owner_id,))  # DELETED_ON_REVOKE
    return gone + db.write("UPDATE shares SET revoked_utc = ? WHERE owner_id = ? AND revoked_utc IS NULL", (_iso(db.clock()), owner_id))


def list_for_owner(db: ident.IdentityStore, owner_id: str) -> list[dict[str, Any]]:
    """The owner's shares, newest first. Never the token."""
    if not db.has_table("shares"):
        return []
    now, out = _iso(db.clock()), []
    for row in db.fetch("SELECT * FROM shares WHERE owner_id = ? ORDER BY created_utc DESC, token_hash", (owner_id,)):
        state = "revoked" if row["revoked_utc"] else "expired" if row["expires_utc"] <= now else "active"
        out.append({"id": row["token_hash"], "kind": row["kind"], "title": json.loads(row["snapshot"]).get("title"),
                    "show_name": bool(row["show_name"]), "show_clip": bool(row["show_clip"]), "created_utc": row["created_utc"],
                    "expires_utc": row["expires_utc"], "state": state})
    return out


def sweep(db: ident.IdentityStore) -> int:
    """Delete share rows that expired or were revoked over a day ago."""
    if not db.has_table("shares"):
        return 0
    cutoff = _iso(db.clock() - 86400)
    return db.write("DELETE FROM shares WHERE expires_utc <= ? OR revoked_utc <= ?", (cutoff, cutoff))


def export_rows(ctx: Any) -> list[dict[str, Any]]:
    """The owner's shares for "Download my data": kind, target, what is shown, dates and state. Never a token or its hash."""
    db = ctx.store
    if not db.has_table("shares"):
        return []
    now, out = _iso(db.clock()), []
    for row in db.fetch("SELECT * FROM shares WHERE owner_id = ? ORDER BY created_utc DESC, token_hash", (ctx.user_id,)):
        state = "revoked" if row["revoked_utc"] else "expired" if row["expires_utc"] <= now else "active"
        shown = [name for name, on in (("name", row["show_name"]), ("clip", row["show_clip"])) if on]
        out.append({"kind": row["kind"], "target": row["item_ref"], "includes": shown, "created": row["created_utc"],
                    "expires": row["expires_utc"], "revoked": row["revoked_utc"], "state": state})
    return out
