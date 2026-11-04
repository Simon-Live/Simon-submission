"""Ask the trainer for a note on a take: rules and store (docs/specs/notes.md; TICKET-237).

A request is a grant from a follower to the trainer of the movement for ONE take, scoped by `include`, revocable
(`withdraw`). Rows live in the `note_requests` table of identity.db; `store` below is the `IdentityStore`. The trainer is
never given a job id, a user id or an email: names come only from `attribution.author_line`. The note is human text and is
never sent to a model here; `notes_for` is the hook a long-pack lane reads (quoted JSON data only).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
from pathlib import Path
import re
import secrets
import sqlite3
from typing import Any
import unicodedata

from part7 import attribution
from part7 import identity as ident

INCLUDES = ("score", "faults", "clip")
DEFAULT_INCLUDE = ["score", "faults"]  # the clip is off until ticked
STATES = ("asked", "answered", "withdrawn", "declined")
NOTE_MAX = 600
CLIP_URL_S = 60
BACKUP_NAME = "identity.db.pre-notes"
ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,32}$")
INFO = b"simon7-notes-v1"
_LINK_RE = re.compile(r"(https?:|ftp:|mailto:|www\.|\]\(|[<>])", re.IGNORECASE)

MSG_NOT_FOUND = "This take cannot be sent to a trainer."
MSG_GONE = "This request is not available."
MSG_CLOSED = "This request has already been closed."
MSG_ALREADY = "This take already has a request."
MSG_INCLUDE = "Choose from the score, what Simon noticed and the clip."
MSG_NO_CLIP = "This take has no clip to send."
MSG_CONFIRM = "Confirm what the trainer will see."
MSG_MINOR = "Notes from a trainer are off for anyone under 18."  # privacy PM-R1 (notes_routes)
MSG_NOTE = "Write 1 to 600 characters of plain text, with no links."
MSG_AT = "Use a time inside the take, or leave it empty."

_SCHEMA = """
CREATE TABLE IF NOT EXISTS note_requests (
  id TEXT PRIMARY KEY, job_id TEXT NOT NULL, entry_id TEXT NOT NULL, follower_id TEXT NOT NULL, trainer_id TEXT NOT NULL,
  include TEXT NOT NULL DEFAULT '["score","faults"]',
  state TEXT NOT NULL CHECK (state IN ('asked', 'answered', 'withdrawn', 'declined')),
  asked_utc TEXT NOT NULL, answered_utc TEXT, note TEXT, note_at_s REAL, seen INTEGER NOT NULL DEFAULT 0, matched_fault TEXT);
CREATE INDEX IF NOT EXISTS note_requests_trainer ON note_requests (trainer_id, state, asked_utc);
CREATE INDEX IF NOT EXISTS note_requests_follower ON note_requests (follower_id, state);
CREATE INDEX IF NOT EXISTS note_requests_job ON note_requests (job_id);
CREATE UNIQUE INDEX IF NOT EXISTS note_requests_one_open ON note_requests (job_id) WHERE state = 'asked';
"""


class NoteError(ValueError):
    """A refusal with a sentence a person can read; `status` is the HTTP answer."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


# ----- migration -----------------------------------------------------------------------------------
def migrate(conn: sqlite3.Connection, path: Path | str) -> bool:
    """Add the `note_requests` table once; True when it ran. Additive and idempotent. Before the first run on a database
    with accounts the file is copied beside it (SQLite backup, so WAL content is included); if the copy fails this
    raises and nothing changes."""
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'note_requests'").fetchone():
        if not any(r[1] == "matched_fault" for r in conn.execute("PRAGMA table_info(note_requests)")):  # one more additive column
            conn.execute("ALTER TABLE note_requests ADD COLUMN matched_fault TEXT")
        return False
    backup = Path(path).with_name(BACKUP_NAME)
    if conn.execute("SELECT 1 FROM users LIMIT 1").fetchone() and not backup.exists():
        target = None
        try:
            target = sqlite3.connect(str(backup))
            conn.backup(target)
            target.close()
            backup.chmod(0o600)
        except (sqlite3.Error, OSError) as exc:
            if target is not None:
                target.close()
            backup.unlink(missing_ok=True)
            raise RuntimeError(f"notes migration refused: backup copy failed ({type(exc).__name__})") from exc
    conn.executescript(_SCHEMA)
    return True


# ----- field rules ---------------------------------------------------------------------------------
def clean_include(raw: Any) -> list[str]:
    """The include set in fixed order. Missing means the default (score and faults); anything else must be a list of
    distinct names from `INCLUDES` (an empty list is allowed: the trainer then sees only the movement and the date)."""
    if raw is None:
        return list(DEFAULT_INCLUDE)
    if not isinstance(raw, list) or any(not isinstance(v, str) or v not in INCLUDES for v in raw) or len(set(raw)) != len(raw):
        raise NoteError(MSG_INCLUDE)
    return [v for v in INCLUDES if v in raw]


def clean_note(raw: Any) -> str:
    """NFKC, whitespace runs to one space, trimmed; 1 to 600 characters, no control character, no link markup."""
    if not isinstance(raw, str):
        raise NoteError(MSG_NOTE)
    text = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", raw)).strip()
    if not 0 < len(text) <= NOTE_MAX or any(unicodedata.category(c).startswith("C") for c in text) or _LINK_RE.search(text):
        raise NoteError(MSG_NOTE)
    return text


def clean_at(raw: Any, limit: float | None) -> float | None:
    """None when absent; else a finite time from 0 to `limit` seconds (the take's length; None when it is not known)."""
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(raw) or raw < 0 or (limit is not None and raw > limit):
        raise NoteError(MSG_AT)
    return float(raw)


def match_fault(at_s: float | None, faults: list[dict[str, Any]]) -> str | None:
    """The name of the reported fault whose time equals `at_s` (within half a millisecond), else None: the trainer
    confirmed what Simon reported, or spotted something it did not."""
    if at_s is None:
        return None
    return next((f["name"] for f in faults if f.get("at_s") is not None and f.get("name") and abs(f["at_s"] - at_s) < 0.0005), None)


# ----- names (only through attribution; never an email or an id) --------------------------------------
def follower_name(store: Any, row: Any) -> str | None:
    """The follower's public name, or None (shown as "A Simon user")."""
    author = attribution.author_line(store, attribution.take_subject(store, row["job_id"], row["entry_id"], row["follower_id"]))["author"]
    return author["name"] if author else None


def trainer_name(store: Any, row: Any) -> str | None:
    """The trainer's credited name, or None (shown as "A Simon trainer")."""
    author = attribution.author_line(store, attribution.entry_subject(store, row["entry_id"]))["author"]
    return author["name"] if author else None


# ----- rules and writes ------------------------------------------------------------------------------
def _now(store: Any) -> str:
    return ident._iso(store.clock())


def eligibility(store: Any, follower_id: str, job_id: str) -> dict[str, str]:
    """`{entry_id, trainer_id}` when the follower owns this follow take and its entry has an owned trainer who is not
    them and has not marked it "only me"; else `NoteError` 404. The caller adds the job checks (done, not private)."""
    rows = store.fetch("SELECT user_id, kind, entry_id FROM takes WHERE job_id = ?", (job_id,))
    if not rows or rows[0]["user_id"] != follower_id or rows[0]["kind"] != "follow" or not rows[0]["entry_id"]:
        raise NoteError(MSG_NOT_FOUND, 404)
    entry = store.entry_author(rows[0]["entry_id"])
    if entry is None or entry["author_state"] != "owned" or not entry["user_id"] or entry["user_id"] == follower_id or entry["only_me"]:
        raise NoteError(MSG_NOT_FOUND, 404)
    return {"entry_id": rows[0]["entry_id"], "trainer_id": entry["user_id"]}


def latest_for_job(store: Any, follower_id: str, job_id: str) -> Any | None:
    """The follower's newest request for this take that is not withdrawn."""
    rows = store.fetch("SELECT * FROM note_requests WHERE job_id = ? AND follower_id = ? AND state != 'withdrawn' "
                       "ORDER BY asked_utc DESC, rowid DESC LIMIT 1", (job_id, follower_id))
    return rows[0] if rows else None


def create(store: Any, follower_id: str, job_id: str, found: dict[str, str], include: list[str]) -> Any:
    """One new request. 409 when the take already has an open or answered one."""
    now = store.clock()
    request_id = secrets.token_urlsafe(12)
    with store._lock:
        store._db.execute("BEGIN IMMEDIATE")
        try:
            if store._db.execute("SELECT 1 FROM note_requests WHERE job_id = ? AND state IN ('asked', 'answered')", (job_id,)).fetchone():
                raise NoteError(MSG_ALREADY, 409)
            store._db.execute(
                "INSERT INTO note_requests (id, job_id, entry_id, follower_id, trainer_id, include, state, asked_utc) "
                "VALUES (?, ?, ?, ?, ?, ?, 'asked', ?)",
                (request_id, job_id, found["entry_id"], follower_id, found["trainer_id"], json.dumps(include), ident._iso(now)))
            store._db.execute("COMMIT")
        except BaseException:
            store._db.execute("ROLLBACK")
            raise
    return store.fetch("SELECT * FROM note_requests WHERE id = ?", (request_id,))[0]


def withdraw(store: Any, follower_id: str, job_id: str) -> bool:
    """End the follower's open request for this take; False when none is open."""
    return store.write("UPDATE note_requests SET state = 'withdrawn' WHERE job_id = ? AND follower_id = ? AND state = 'asked'",
                       (job_id, follower_id)) == 1


def list_for_trainer(store: Any, trainer_id: str) -> list[Any]:
    """Requests addressed to the caller, newest first; a withdrawn one is gone."""
    return store.fetch("SELECT * FROM note_requests WHERE trainer_id = ? AND state != 'withdrawn' ORDER BY asked_utc DESC, rowid DESC",
                       (trainer_id,))


def get_for_trainer(store: Any, trainer_id: str, request_id: str) -> Any | None:
    """One request addressed to the caller, or None (unknown, another trainer's, withdrawn)."""
    if not isinstance(request_id, str) or not ID_RE.match(request_id):
        return None
    rows = store.fetch("SELECT * FROM note_requests WHERE id = ? AND trainer_id = ? AND state != 'withdrawn'", (request_id, trainer_id))
    return rows[0] if rows else None


def close(store: Any, row: Any, state: str, note: str | None = None, at_s: float | None = None, matched: str | None = None) -> None:
    """Answer or decline an open request once; 409 when it was closed meanwhile (also by a withdraw)."""
    changed = store.write("UPDATE note_requests SET state = ?, answered_utc = ?, note = ?, note_at_s = ?, matched_fault = ? WHERE id = ? AND state = 'asked'",
                          (state, _now(store), note, at_s, matched, row["id"]))
    if changed != 1:
        raise NoteError(MSG_CLOSED, 409)


def include_of(row: Any) -> list[str]:
    try:
        found = json.loads(row["include"])
    except (TypeError, ValueError):
        return []
    return [v for v in INCLUDES if isinstance(found, list) and v in found]


# ----- the long-context hook (AC-N8) ------------------------------------------------------------------
def _read(state: Path | str, sql: str, args: tuple) -> list[sqlite3.Row]:
    path = ident.db_path(state)
    if not path.is_file():
        return []
    try:
        db = sqlite3.connect(str(path), timeout=10)
        try:
            db.row_factory = sqlite3.Row
            return db.execute(sql, args).fetchall()
        finally:
            db.close()
    except sqlite3.Error:
        return []


def notes_for(state: Path | str, user_id: str, entry_id: str) -> list[dict[str, Any]]:
    """The follower's received notes for one movement, oldest first: `[{note, at_s, matched_fault, job_id, answered_utc}]`.

    Human text. A caller that sends it to a model must pass it as quoted JSON data only (TICKET-207 constraint 11) and
    count it in the receipt."""
    rows = _read(state, "SELECT note, note_at_s, matched_fault, job_id, answered_utc FROM note_requests WHERE follower_id = ? AND entry_id = ? "
                        "AND state = 'answered' ORDER BY answered_utc, rowid", (user_id, entry_id))
    return [{"note": r["note"], "at_s": r["note_at_s"], "matched_fault": r["matched_fault"], "job_id": r["job_id"], "answered_utc": r["answered_utc"]} for r in rows]


# ----- notices for the Me page (no mail, no push) ------------------------------------------------------
def waiting_count(store: Any, trainer_id: str) -> int:
    return store.fetch("SELECT COUNT(*) AS n FROM note_requests WHERE trainer_id = ? AND state = 'asked'", (trainer_id,))[0]["n"]


def unseen_notes(store: Any, user_id: str) -> list[Any]:
    return store.fetch("SELECT * FROM note_requests WHERE follower_id = ? AND state = 'answered' AND seen = 0 "
                       "ORDER BY answered_utc DESC, rowid DESC LIMIT 20", (user_id,))


def mark_seen(store: Any, user_id: str) -> int:
    return store.write("UPDATE note_requests SET seen = 1 WHERE follower_id = ? AND state IN ('answered', 'declined') AND seen = 0", (user_id,))


# ----- the signed clip URL (60 s) ----------------------------------------------------------------------
def _clip_key(store: Any) -> bytes:
    prk = hmac.new(b"simon7-notes-salt", store.pepper, hashlib.sha256).digest()
    return hmac.new(prk, INFO + b"\x01", hashlib.sha256).digest()


def sign_clip(store: Any, request_id: str) -> tuple[int, str]:
    """`(expiry, signature)` for the clip of one request, valid for `CLIP_URL_S` seconds."""
    exp = int(store.clock()) + CLIP_URL_S
    return exp, hmac.new(_clip_key(store), f"{request_id}:{exp}".encode("ascii"), hashlib.sha256).hexdigest()


def clip_signature_ok(store: Any, request_id: str, exp: Any, sig: Any) -> bool:
    if not isinstance(exp, str) or not (exp.isascii() and exp.isdigit()) or len(exp) > 20 or not isinstance(sig, str) or int(exp) < store.clock():
        return False
    want = hmac.new(_clip_key(store), f"{request_id}:{exp}".encode("ascii"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(want, sig)


# ----- cascades (AC-N9): identity.db opened directly, so history_store and the delete routes need no store object ----
def _delete(state: Path | str, sql: str, args: tuple) -> int:
    path = ident.db_path(state)
    if not path.is_file():
        return 0
    db = sqlite3.connect(str(path), timeout=30)
    try:
        with db:
            return db.execute(sql, args).rowcount
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc):
            return 0
        raise
    finally:
        db.close()


def drop_jobs(state: Path | str, job_ids: set[str]) -> int:
    """Remove the requests (and notes) about these takes."""
    ids = sorted(job_ids)
    if not ids:
        return 0
    return _delete(state, f"DELETE FROM note_requests WHERE job_id IN ({','.join('?' * len(ids))})", tuple(ids))


def drop_follower(state: Path | str, user_id: str) -> int:
    """Remove every request the person asked (retention withdrawn, Delete my data)."""
    return _delete(state, "DELETE FROM note_requests WHERE follower_id = ?", (user_id,))


def drop_follower_entry(state: Path | str, user_id: str, entry_id: str) -> int:
    """Remove the person's requests about one movement ("forget this movement")."""
    return _delete(state, "DELETE FROM note_requests WHERE follower_id = ? AND entry_id = ?", (user_id, entry_id))


# ----- download my data ----------------------------------------------------------------------------------
def export_rows(ctx: Any) -> list[dict[str, Any]]:
    """The person's notes for "Download my data", both roles. The other side is named only by its public author line
    ("A Simon user" or "A Simon trainer" when it has no shown name); never an id or an email. A trainer's row holds the
    trainer's own note and state, not the follower's take."""
    store, me, out = ctx.store, ctx.user_id, []
    for row in store.fetch("SELECT * FROM note_requests WHERE (follower_id = ? OR trainer_id = ?) AND state != 'withdrawn' "
                           "ORDER BY asked_utc, rowid", (me, me)):
        asked = row["follower_id"] == me
        out.append({"role": "follower" if asked else "trainer", "movement": ctx.movement(row["entry_id"]),
                    "with": (trainer_name(store, row) or "A Simon trainer") if asked else (follower_name(store, row) or "A Simon user"),
                    "asked": row["asked_utc"], "state": row["state"], "shown": include_of(row) if asked else None,
                    "answered": row["answered_utc"], "note": row["note"], "at_s": row["note_at_s"], "matched_fault": row["matched_fault"]})
    return out
