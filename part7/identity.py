"""Opt-in identity store: users, sign-in challenges, sessions and ownership in stdlib SQLite (docs/specs/identity.md).

One file, `<state>/identity/identity.db` (WAL, folder 0700, file 0600). A secret is never stored in clear: the link
token and the session id as `sha256`, the 6-digit code as `HMAC-SHA256(pepper, challenge_id + ":" + code)`.
Nothing here touches `job.json`; ownership lives only in the `takes` table. Every method takes the store lock, so
`ThreadingHTTPServer` threads share one connection. `owner_of_job` and `retention_opt_in` are read-only readers that
need no pepper.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
import os
from pathlib import Path
import re
import secrets
import sqlite3
import threading
import time
from typing import Any, Callable
import unicodedata

CHALLENGE_TTL_S = 15 * 60
CODE_TRIES = 5
EMAIL_FAILS_PER_HOUR = 10
EMAIL_STARTS_PER_HOUR = 5
EMAIL_STARTS_PER_DAY = 20
GLOBAL_MAILS_PER_HOUR = 200
SESSION_ABSOLUTE_S = 30 * 86400
SESSION_IDLE_S = 14 * 86400
SESSION_TOUCH_S = 60
ACCOUNT_IDLE_S = 180 * 86400
KINDS = ("follow", "trainer")  # group takes are not owned (identity.md)
VIAS = ("submit", "claim")
_CODE_RE = re.compile(r"^[0-9]{6}$")
_HOUR, _DAY = 3600, 86400

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  user_id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE, created_at REAL NOT NULL, last_seen_at REAL NOT NULL,
  consent_version TEXT, consent_at REAL, retention_opt_in INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS challenges (
  id TEXT PRIMARY KEY, email TEXT NOT NULL, token_hash TEXT NOT NULL UNIQUE, code_mac TEXT NOT NULL,
  created_at REAL NOT NULL, expires_at REAL NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, used_at REAL,
  ip_key TEXT);
CREATE INDEX IF NOT EXISTS challenges_email ON challenges (email, created_at);
CREATE TABLE IF NOT EXISTS sessions (
  sid_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL, created_at REAL NOT NULL, last_seen_at REAL NOT NULL,
  expires_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS sessions_user ON sessions (user_id);
CREATE TABLE IF NOT EXISTS takes (
  job_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, kind TEXT NOT NULL, entry_id TEXT, people_job TEXT,
  via TEXT NOT NULL, created_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS takes_user ON takes (user_id, created_at);
CREATE TABLE IF NOT EXISTS entries (
  entry_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, trainer_job TEXT NOT NULL DEFAULT '',
  only_me INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS entries_user ON entries (user_id, created_at);
"""


def normalise_email(raw: Any) -> str | None:
    """Trim, NFKC, one `@`, lowercase, IDNA domain, at most 254 characters and 64 in the local part; else None.

    No provider aliasing: two spellings are two accounts.
    """
    if not isinstance(raw, str):
        return None
    text = unicodedata.normalize("NFKC", raw.strip()).lower()
    if text.count("@") != 1 or len(text) > 254 or any(c.isspace() or ord(c) < 32 for c in text):
        return None
    local, domain = text.split("@")
    if not local or len(local) > 64 or not domain or domain.startswith(".") or domain.endswith("."):
        return None
    try:
        domain = domain.encode("idna").decode("ascii")
    except UnicodeError:
        return None
    if "." not in domain or len(domain) > 253 or any(not part or len(part) > 63 for part in domain.split(".")):
        return None
    if not re.match(r"^[a-z0-9.-]+$", domain) or domain.startswith("-") or ".." in domain:
        return None
    email = f"{local}@{domain}"
    return email if len(email) <= 254 else None


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def retention_days() -> int:
    """Days an opted-in owner's history copies are kept: the one setting `SIMON7_HISTORY_DAYS`, default 90."""
    from part7 import history_store
    return history_store.days()


def db_path(state: Path | str) -> Path:
    return Path(state) / "identity" / "identity.db"


AUTHOR_STATES = ("owned", "unattributed")
BACKUP_SUFFIX = ".pre-attribution"


def migrate_attribution(db: sqlite3.Connection, path: Path | str) -> bool:
    """Add `entries.author_state` once (docs/specs/attribution.md); True when it ran, False when already done.

    Additive and fail closed: the database is copied to `<db>.pre-attribution` first and the migration refuses
    (raises) when the copy fails. It writes only the new column: `owned` where the row names an existing user,
    `unattributed` for every other row, so nobody is named by guess.
    """
    if any(r[1] == "author_state" for r in db.execute("PRAGMA table_info(entries)")):
        return False
    backup = Path(str(path) + BACKUP_SUFFIX)
    try:
        copy = sqlite3.connect(str(backup))
        try:
            db.backup(copy)
        finally:
            copy.close()
        os.chmod(backup, 0o600)
    except (OSError, sqlite3.Error) as exc:
        raise RuntimeError(f"attribution migration refused: the database could not be copied ({type(exc).__name__})") from exc
    db.execute("BEGIN IMMEDIATE")
    try:
        db.execute("ALTER TABLE entries ADD COLUMN author_state TEXT NOT NULL DEFAULT 'unattributed'")
        db.execute("UPDATE entries SET author_state = 'owned' WHERE user_id <> '' "
                   "AND EXISTS (SELECT 1 FROM users WHERE users.user_id = entries.user_id)")
        db.execute("COMMIT")
    except BaseException:
        db.execute("ROLLBACK")
        raise
    return True


class IdentityStore:
    """Users, challenges, sessions, takes and entries behind one lock."""

    def __init__(self, state: Path, pepper: bytes, clock: Callable[[], float] = time.time) -> None:
        self.pepper, self.clock, self.state = pepper, clock, Path(state)
        self._lock = threading.RLock()
        folder = Path(state) / "identity"
        folder.mkdir(parents=True, exist_ok=True)
        os.chmod(folder, 0o700)
        path = db_path(state)
        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
        os.close(fd)
        os.chmod(path, 0o600)
        self._db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None, timeout=30)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(_SCHEMA)
        from part7 import profile  # additive `profiles` table, with a backup copy first (profile.md)
        profile.migrate(self._db, path)
        from part7 import devices  # additive `public_id` and `device` columns on `sessions`, with a backup copy first (devices.md)
        devices.migrate(self._db, path)
        migrate_attribution(self._db, path)
        from part7 import notes  # additive `note_requests` table, with a backup copy first (notes.md)
        notes.migrate(self._db, path)
        from part7 import source_credit  # additive `source_credits` table (source-credit.md)
        source_credit.migrate(self._db)
        profile.migrate_default_model(self._db, path)  # additive `profiles.default_model_id`, backup copy first (profile.md)
        profile.migrate_model_only_view(self._db, path)  # additive `profiles.model_only_view`, backup copy first (model-default.md)
        for suffix in ("-wal", "-shm"):  # SQLite creates these with the umask; keep them private too
            side = Path(str(path) + suffix)
            if side.exists():
                os.chmod(side, 0o600)

    # ----- helpers --------------------------------------------------------------------------
    # Public seam for part7/share.py (its table lives in this file but is its own).
    def fetch(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        return self._q(sql, args)

    def write(self, sql: str, args: tuple = ()) -> int:
        """Run one write under the store lock; returns the rows changed."""
        with self._lock:
            return self._db.execute(sql, args).rowcount

    def has_table(self, name: str) -> bool:
        return bool(self._q("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)))

    def write_if_table(self, name: str, sql: str, args: tuple = ()) -> None:
        with self._lock:
            if self.has_table(name):
                self._db.execute(sql, args)

    def write_script(self, script: str) -> None:
        """Run a script under the store lock; the script holds its own BEGIN and COMMIT (share.py's table rebuild)."""
        with self._lock:
            try:
                self._db.executescript(script)
            except BaseException:
                if self._db.in_transaction:
                    self._db.execute("ROLLBACK")
                raise

    def backup_to(self, target: Path) -> None:
        """A consistent copy of the database file (WAL included) at `target`; raises on any failure."""
        with self._lock:
            out = sqlite3.connect(str(target))
            try:
                self._db.backup(out)
            finally:
                out.close()
        os.chmod(target, 0o600)

    def _q(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._db.execute(sql, args).fetchall()

    def _one(self, sql: str, args: tuple = ()) -> sqlite3.Row | None:
        rows = self._q(sql, args)
        return rows[0] if rows else None

    def _mac(self, challenge_id: str, code: str) -> str:
        return hmac.new(self.pepper, f"{challenge_id}:{code}".encode("utf-8"), hashlib.sha256).hexdigest()

    def email_key(self, email: str) -> str:
        """A short keyed hash for logs: an address is never logged."""
        return hmac.new(self.pepper, email.encode("utf-8"), hashlib.sha256).hexdigest()[:12]

    # ----- sign-in challenges ---------------------------------------------------------------
    def start_challenge(self, email: str, ip_key: str) -> tuple[str, str] | None:
        """One challenge holding a link token and a 6-digit code; None when limited (5 an hour, 20 a day, 200 mails an hour)."""
        norm = normalise_email(email)
        if norm is None:
            return None
        now = self.clock()
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                def count(since: float, where: str = "email = ?") -> int:
                    args = (norm, since) if where else (since,)
                    return self._db.execute(
                        f"SELECT COUNT(*) FROM challenges WHERE {where + ' AND ' if where else ''}created_at > ?", args
                    ).fetchone()[0]

                if (count(now - _HOUR) >= EMAIL_STARTS_PER_HOUR or count(now - _DAY) >= EMAIL_STARTS_PER_DAY
                        or count(now - _HOUR, "") >= GLOBAL_MAILS_PER_HOUR):
                    self._db.execute("COMMIT")
                    return None
                cid, token = secrets.token_hex(8), secrets.token_urlsafe(32)
                code = f"{secrets.randbelow(10 ** 6):06d}"
                self._db.execute("UPDATE challenges SET used_at = ? WHERE email = ? AND used_at IS NULL", (now, norm))
                self._db.execute(
                    "INSERT INTO challenges (id, email, token_hash, code_mac, created_at, expires_at, ip_key) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (cid, norm, _sha(token), self._mac(cid, code), now, now + CHALLENGE_TTL_S, ip_key),
                )
                self._db.execute("COMMIT")
            except BaseException:
                self._db.execute("ROLLBACK")
                raise
        return token, code

    def _user_for(self, email: str, now: float) -> str:
        row = self._one("SELECT user_id FROM users WHERE email = ?", (email,))
        if row is not None:
            self._db.execute("UPDATE users SET last_seen_at = ? WHERE user_id = ?", (now, row["user_id"]))
            return row["user_id"]
        user_id = "u-" + secrets.token_hex(12)
        self._db.execute(
            "INSERT INTO users (user_id, email, created_at, last_seen_at) VALUES (?, ?, ?, ?)", (user_id, email, now, now)
        )
        return user_id

    def consume_token(self, token: str) -> str | None:
        """Use the link token once; returns the user id (creating the user) or None."""
        if not isinstance(token, str) or not 0 < len(token) <= 200:
            return None
        now = self.clock()
        with self._lock:
            row = self._one("SELECT id, email FROM challenges WHERE token_hash = ?", (_sha(token),))
            if row is None:
                return None
            used = self._db.execute(
                "UPDATE challenges SET used_at = ? WHERE id = ? AND used_at IS NULL AND expires_at > ?", (now, row["id"], now)
            ).rowcount
            return self._user_for(row["email"], now) if used == 1 else None

    def consume_code(self, email: str, code: str) -> str | None:
        """Check the code of the newest open challenge for `email`; every wrong try counts, the 5th kills it."""
        norm = normalise_email(email)
        text = code.replace(" ", "") if isinstance(code, str) else ""
        now = self.clock()
        with self._lock:
            row = None
            if norm is not None:
                row = self._one(
                    "SELECT id, code_mac, attempts FROM challenges WHERE email = ? AND used_at IS NULL AND expires_at > ? "
                    "ORDER BY created_at DESC LIMIT 1", (norm, now))
                failed = self._one("SELECT COALESCE(SUM(attempts), 0) AS n FROM challenges WHERE email = ? AND created_at > ?",
                                   (norm, now - _HOUR))["n"]
                if failed >= EMAIL_FAILS_PER_HOUR:
                    row = None
            expected = row["code_mac"] if row is not None else self._mac("none", "000000")
            shape_ok = bool(_CODE_RE.match(text))
            given = self._mac(row["id"] if row is not None else "none", text if shape_ok else "000000")
            match = hmac.compare_digest(expected, given) and row is not None and shape_ok
            if row is None:
                return None
            if not match:
                tries = row["attempts"] + 1
                self._db.execute("UPDATE challenges SET attempts = ?, used_at = CASE WHEN ? >= ? THEN ? ELSE used_at END "
                                 "WHERE id = ?", (tries, tries, CODE_TRIES, now, row["id"]))
                return None
            used = self._db.execute("UPDATE challenges SET used_at = ? WHERE id = ? AND used_at IS NULL", (now, row["id"])).rowcount
            return self._user_for(norm, now) if used == 1 else None

    # ----- sessions -------------------------------------------------------------------------
    def new_session(self, user_id: str, device: str | None = None) -> str:
        from part7 import devices  # `device` is the coarse label of `devices.device_label`, never a raw User-Agent
        sid, now = secrets.token_urlsafe(32), self.clock()
        self._q("INSERT INTO sessions (sid_hash, user_id, created_at, last_seen_at, expires_at, public_id, device) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (_sha(sid), user_id, now, now, now + SESSION_ABSOLUTE_S, devices.new_public_id(), device or devices.UNKNOWN))
        return sid

    def session_user(self, sid: str) -> str | None:
        """The user of a live session; an absolute (30 days) or idle (14 days) expiry deletes the row."""
        if not isinstance(sid, str) or not 0 < len(sid) <= 200:
            return None
        now, key = self.clock(), _sha(sid)
        with self._lock:
            row = self._one("SELECT user_id, last_seen_at, expires_at FROM sessions WHERE sid_hash = ?", (key,))
            if row is None:
                return None
            if row["expires_at"] <= now or row["last_seen_at"] + SESSION_IDLE_S <= now:
                self._db.execute("DELETE FROM sessions WHERE sid_hash = ?", (key,))
                return None
            if self._one("SELECT 1 FROM users WHERE user_id = ?", (row["user_id"],)) is None:
                return None
            if now - row["last_seen_at"] >= SESSION_TOUCH_S:  # at most one write a minute
                self._db.execute("UPDATE sessions SET last_seen_at = ? WHERE sid_hash = ?", (now, key))
                self._db.execute("UPDATE users SET last_seen_at = ? WHERE user_id = ?", (now, row["user_id"]))
            return row["user_id"]

    def end_session(self, sid: str) -> None:
        if isinstance(sid, str) and sid:
            self._q("DELETE FROM sessions WHERE sid_hash = ?", (_sha(sid),))

    # ----- users ----------------------------------------------------------------------------
    def user(self, user_id: str) -> dict | None:
        row = self._one("SELECT * FROM users WHERE user_id = ?", (user_id,))
        if row is None:
            return None
        opted = bool(row["retention_opt_in"])
        return {
            "user_id": row["user_id"], "email": row["email"], "created_at": _iso(row["created_at"]),
            "retention_opt_in": opted,
            "retention": {"opted_in": opted, "days": retention_days(), "consent_version": row["consent_version"]},
        }

    def set_consent(self, user_id: str, version: str, retention: bool) -> None:
        self._q("UPDATE users SET consent_version = ?, consent_at = ?, retention_opt_in = ? WHERE user_id = ?",
                (version, self.clock(), 1 if retention else 0, user_id))

    # ----- ownership ------------------------------------------------------------------------
    def attach(self, job_id: str, user_id: str, kind: str, entry_id: str | None, people_job: str | None, via: str) -> bool:
        """First owner wins (unique `job_id`); True for the owner, also on a repeat, False for anyone else."""
        if kind not in KINDS or via not in VIAS:
            raise ValueError("unknown kind or via")
        with self._lock:
            self._db.execute(
                "INSERT OR IGNORE INTO takes (job_id, user_id, kind, entry_id, people_job, via, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)", (job_id, user_id, kind, entry_id, people_job, via, self.clock()))
            return self.owner_of(job_id) == user_id

    def attach_entry(self, entry_id: str, user_id: str, trainer_job: str = "") -> None:
        """Record the owner of a catalog entry (first wins); a later call fills in the trainer job of the same owner."""
        with self._lock:
            self._db.execute("INSERT OR IGNORE INTO entries (entry_id, user_id, trainer_job, created_at, author_state) "
                             "VALUES (?, ?, ?, ?, 'owned')", (entry_id, user_id, trainer_job, self.clock()))
            if trainer_job:
                self._db.execute("UPDATE entries SET trainer_job = ? WHERE entry_id = ? AND user_id = ? AND trainer_job = ''",
                                 (trainer_job, entry_id, user_id))

    def owner_of(self, job_id: str) -> str | None:
        row = self._one("SELECT user_id FROM takes WHERE job_id = ?", (job_id,))
        return row["user_id"] if row else None

    def entry_owner(self, entry_id: str) -> tuple[str, bool] | None:
        row = self._one("SELECT user_id, only_me FROM entries WHERE entry_id = ?", (entry_id,))
        return (row["user_id"], bool(row["only_me"])) if row else None

    def entry_author(self, entry_id: str) -> dict | None:
        """The attribution facts of an entry: `user_id`, `author_state`, `only_me`; None when no row exists."""
        row = self._one("SELECT user_id, author_state, only_me FROM entries WHERE entry_id = ?", (entry_id,))
        if row is None:
            return None
        return {"user_id": row["user_id"], "author_state": row["author_state"], "only_me": bool(row["only_me"])}

    def takes_of(self, user_id: str) -> list[dict]:
        """The user's takes, newest first: job_id, kind, entry_id, people_job, via, created_at (UTC text), created_ts."""
        rows = self._q("SELECT * FROM takes WHERE user_id = ? ORDER BY created_at DESC, job_id", (user_id,))
        return [{"job_id": r["job_id"], "kind": r["kind"], "entry_id": r["entry_id"], "people_job": r["people_job"],
                 "via": r["via"], "created_at": _iso(r["created_at"]), "created_ts": r["created_at"]} for r in rows]

    def entries_of(self, user_id: str) -> list[dict]:
        rows = self._q("SELECT * FROM entries WHERE user_id = ? ORDER BY created_at DESC, entry_id", (user_id,))
        return [{"entry_id": r["entry_id"], "trainer_job": r["trainer_job"], "only_me": bool(r["only_me"]),
                 "author_state": r["author_state"], "created_at": _iso(r["created_at"])} for r in rows]

    def set_only_me(self, entry_id: str, user_id: str, value: bool) -> bool:
        with self._lock:
            return self._db.execute("UPDATE entries SET only_me = ? WHERE entry_id = ? AND user_id = ?",
                                    (1 if value else 0, entry_id, user_id)).rowcount == 1

    def forget_job(self, job_id: str) -> None:
        """Drop the ownership of a deleted take (and the entry row its trainer job made)."""
        with self._lock:
            self.write_if_table("note_requests", "DELETE FROM note_requests WHERE job_id = ? OR entry_id IN "
                                "(SELECT entry_id FROM entries WHERE trainer_job = ?)", (job_id, job_id))  # TICKET-237: no note outlives its take
            self.write_if_table("shares", "DELETE FROM shares WHERE kind = 'progress_sheet' AND (owner_id, item_ref) IN "
                                "(SELECT user_id, entry_id FROM takes WHERE job_id = ?)", (job_id,))  # TICKET-283: the sheet read this take
            self.write_if_table("source_credits", "DELETE FROM source_credits WHERE (kind = 'take' AND subject_id = ?) OR (kind = 'entry' AND subject_id IN "
                                "(SELECT entry_id FROM entries WHERE trainer_job = ?))", (job_id, job_id))  # TICKET-322: a credit goes with its subject
            self._db.execute("DELETE FROM takes WHERE job_id = ?", (job_id,))
            self._db.execute("DELETE FROM entries WHERE trainer_job = ?", (job_id,))
            self.write_if_table("shares", "UPDATE shares SET revoked_utc = ? WHERE item_ref = ? AND revoked_utc IS NULL",
                                (_iso(self.clock()), job_id))  # TICKET-233: a deleted take takes its share links with it

    def delete_user(self, user_id: str) -> None:
        """Remove the user, sessions, open challenges and ownership rows."""
        with self._lock:
            row = self._one("SELECT email FROM users WHERE user_id = ?", (user_id,))
            self._db.execute("BEGIN IMMEDIATE")
            try:
                for table in ("sessions", "takes", "entries", "profiles"):
                    self._db.execute(f"DELETE FROM {table} WHERE user_id = ?", (user_id,))
                if self.has_table("shares"):  # TICKET-233: deleting my data ends every share link
                    self._db.execute("DELETE FROM shares WHERE owner_id = ?", (user_id,))
                if self.has_table("source_credits"):  # TICKET-322: the person's credits go with their data
                    self._db.execute("DELETE FROM source_credits WHERE owner_id = ?", (user_id,))
                if self.has_table("note_requests"):  # TICKET-237: both sides' requests and notes go; the other side sees nothing
                    self._db.execute("DELETE FROM note_requests WHERE follower_id = ? OR trainer_id = ?", (user_id, user_id))
                if row is not None:
                    self._db.execute("DELETE FROM challenges WHERE email = ?", (row["email"],))
                self._db.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
                self._db.execute("COMMIT")
            except BaseException:
                self._db.execute("ROLLBACK")
                raise

    def prune(self, state: Path | str | None = None) -> None:
        """Drop expired sessions, challenges older than two days and accounts idle for 180 days.

        An idle account goes whole, as "Delete my data" does: its history copies and reports (`history_store.forget`),
        its outbox mail, then the account. `state` is the server's state folder; the store's own folder is the default."""
        from part7 import history_store, mail
        state = Path(state) if state is not None else self.state
        now = self.clock()
        with self._lock:
            self._db.execute("DELETE FROM sessions WHERE expires_at <= ? OR last_seen_at <= ?", (now, now - SESSION_IDLE_S))
            self._db.execute("DELETE FROM challenges WHERE created_at < ?", (now - 2 * _DAY,))
            idle = [r["user_id"] for r in self._db.execute("SELECT user_id FROM users WHERE last_seen_at <= ?",
                                                           (now - ACCOUNT_IDLE_S,)).fetchall()]
        for user_id in idle:
            email = (self.user(user_id) or {}).get("email")
            history_store.forget(state, user_id)
            if email:
                mail.purge_outbox(state, email)
            self.delete_user(user_id)


# ----- read-only readers for other lanes (no pepper, never create the file) -------------------------
def _read_one(state: Path | str, sql: str, args: tuple) -> sqlite3.Row | None:
    path = db_path(state)
    if not path.is_file():
        return None
    try:
        db = sqlite3.connect(str(path), timeout=10)
        try:
            db.row_factory = sqlite3.Row
            return db.execute(sql, args).fetchone()
        finally:
            db.close()
    except sqlite3.Error:
        return None


def owner_of_job(state: Path, job_id: str) -> str | None:
    """The user who owns `job_id`, or None (anonymous, unknown, or no identity store yet)."""
    row = _read_one(state, "SELECT user_id FROM takes WHERE job_id = ?", (job_id,))
    return row["user_id"] if row else None


def follow_owners(state: Path, entry_id: str) -> dict[str, str]:
    """`{job_id: user_id}` of the signed-in follow takes of one entry (empty with no store); for the class table only."""
    path = db_path(state)
    if not path.is_file():
        return {}
    try:
        db = sqlite3.connect(str(path), timeout=10)
        try:
            rows = db.execute("SELECT job_id, user_id FROM takes WHERE entry_id = ? AND kind = 'follow'", (entry_id,)).fetchall()
        finally:
            db.close()
    except sqlite3.Error:
        return {}
    return {str(job): str(user) for job, user in rows}


def retention_opt_in(state: Path, user_id: str) -> bool:
    """True when the user chose to keep their history copies longer."""
    row = _read_one(state, "SELECT retention_opt_in FROM users WHERE user_id = ?", (user_id,))
    return bool(row and row["retention_opt_in"])
