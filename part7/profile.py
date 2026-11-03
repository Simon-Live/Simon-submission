"""A signed-in person's profile: public name, built-in avatar, modes, goals and two privacy switches (docs/specs/profile.md).

Rows live in the `profiles` table of identity.db. `db` below is the `IdentityStore` (its connection and lock are used).
Privacy fails closed: a new profile shows no name and credits nobody. The email is never read into any answer here.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
from typing import Any
import unicodedata

from part7 import modes as modes_mod

NAME_MAX = 40
AVATARS: tuple[str, ...] = ("fern", "ember", "tide", "moss", "dusk", "sun", "stone", "wave")  # built in, no upload
GOALS: dict[str, str] = {
    "learn_the_moves": "Learn the moves",
    "match_trainer_timing": "Match the trainer's timing",
    "steady_practice": "Keep a steady practice",
}
FIELDS = ("public_name", "avatar", "modes", "goals", "show_name", "credit_me_as_trainer", "default_model_id",
          "model_only_view")
BACKUP_NAME = "identity.db.pre-profiles"
MODEL_BACKUP_NAME = "identity.db.pre-default-model"
VIEW_BACKUP_NAME = "identity.db.pre-model-only-view"
# The picker's choice id for "You" (web/skin/picker.js): person, skeleton, lib:<library id> or up:<upload id>.
MODEL_CHOICE_RE = re.compile(r"^(?:person|skeleton|(?:lib|up):[A-Za-z0-9][A-Za-z0-9_.-]{0,63})$")

MSG_NAME = "Use 1 to 40 characters for your name. Leave out @ and your email."
MSG_AVATAR = "Pick one of the avatars shown."
MSG_MODES = "Pick dance, rehab or fitness."
MSG_GOALS = "Pick goals from the list shown."
MSG_SWITCH = "Each privacy choice is on or off."
MSG_UNKNOWN = "Only the profile fields can be changed."
MSG_MODEL = "Pick a model from the list shown."

_SCHEMA = """
CREATE TABLE IF NOT EXISTS profiles (
  user_id TEXT PRIMARY KEY, public_name TEXT, avatar_key TEXT, modes TEXT NOT NULL DEFAULT '[]',
  goals TEXT NOT NULL DEFAULT '[]', show_name INTEGER NOT NULL DEFAULT 0, credit_me_as_trainer INTEGER NOT NULL DEFAULT 0,
  created_utc TEXT, updated_utc TEXT);
"""


class ProfileError(ValueError):
    """A field is not acceptable; the message is plain words for the person."""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _backup(conn: sqlite3.Connection, path: Path, name: str, what: str) -> None:
    """Copy the database to `name` beside it once, when it holds accounts (sqlite backup, so WAL content is included).
    If the copy fails this raises, the partial copy is removed and the caller changes nothing."""
    backup = Path(path).with_name(name)
    if backup.exists() or not conn.execute("SELECT 1 FROM users LIMIT 1").fetchone():
        return
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
        raise RuntimeError(f"{what} migration refused: backup copy failed ({type(exc).__name__})") from exc


def migrate(conn: sqlite3.Connection, path: Path) -> None:
    """Add the `profiles` table. Additive and idempotent. Before the first run on an existing database the file is
    copied beside it (sqlite backup, so WAL content is included); if the copy fails this raises and nothing changes."""
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='profiles'").fetchone():
        return
    _backup(conn, path, BACKUP_NAME, "profiles")
    conn.executescript(_SCHEMA)


def migrate_default_model(conn: sqlite3.Connection, path: Path) -> bool:
    """Add `profiles.default_model_id TEXT NULL` once (the default model for "You"); True when it ran. Additive and
    idempotent; runs after `migrate` and the other identity migrations. The database is copied to
    `identity.db.pre-default-model` first when it holds accounts, and a failed copy raises with nothing changed."""
    if any(r[1] == "default_model_id" for r in conn.execute("PRAGMA table_info(profiles)")):
        return False
    _backup(conn, path, MODEL_BACKUP_NAME, "default model")
    conn.execute("ALTER TABLE profiles ADD COLUMN default_model_id TEXT")
    return True


def migrate_model_only_view(conn: sqlite3.Connection, path: Path) -> bool:
    """Add `profiles.model_only_view INTEGER NOT NULL DEFAULT 0` once ("Show only my 3D model", model-default.md
    AC-MD10); True when it ran. Additive and idempotent, after `migrate_default_model`. Old rows read off. The database
    is copied to `identity.db.pre-model-only-view` first when it holds accounts, and a failed copy raises with nothing changed."""
    if any(r[1] == "model_only_view" for r in conn.execute("PRAGMA table_info(profiles)")):
        return False
    _backup(conn, path, VIEW_BACKUP_NAME, "model only view")
    conn.execute("ALTER TABLE profiles ADD COLUMN model_only_view INTEGER NOT NULL DEFAULT 0")
    return True


def clean_name(raw: Any, email: str | None = None) -> str | None:
    """None for no name, else the cleaned name; `ProfileError` when it is not acceptable (never the email)."""
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ProfileError(MSG_NAME)
    text = unicodedata.normalize("NFKC", raw).strip()
    if not 0 < len(text) <= NAME_MAX or "@" in text or any(unicodedata.category(c).startswith("C") for c in text):
        raise ProfileError(MSG_NAME)
    if email and text.casefold() in (email.casefold(), email.split("@")[0].casefold()):
        raise ProfileError(MSG_NAME)
    return text


def _pick(raw: Any, allowed: tuple[str, ...], message: str) -> list[str]:
    if not isinstance(raw, list) or any(not isinstance(v, str) or v not in allowed for v in raw):
        raise ProfileError(message)
    return [v for v in allowed if v in raw]  # fixed order, no duplicates


def _switch(raw: Any) -> int:
    if not isinstance(raw, bool):
        raise ProfileError(MSG_SWITCH)
    return int(raw)


def clean_model(raw: Any) -> str | None:
    """None (no default) or a picker choice id; `ProfileError` for anything else."""
    if raw is None:
        return None
    if not isinstance(raw, str) or not MODEL_CHOICE_RE.match(raw):
        raise ProfileError(MSG_MODEL)
    return raw


def defaults() -> dict[str, Any]:
    return {"public_name": None, "avatar": None, "modes": [], "goals": [], "show_name": False,
            "credit_me_as_trainer": False, "default_model_id": None, "model_only_view": False,
            "created_utc": None, "updated_utc": None}


def _row_doc(row: sqlite3.Row) -> dict[str, Any]:
    return {"public_name": row["public_name"], "avatar": row["avatar_key"], "modes": json.loads(row["modes"] or "[]"),
            "goals": json.loads(row["goals"] or "[]"), "show_name": bool(row["show_name"]),
            "credit_me_as_trainer": bool(row["credit_me_as_trainer"]), "default_model_id": row["default_model_id"],
            "model_only_view": bool(row["model_only_view"]),
            "created_utc": row["created_utc"], "updated_utc": row["updated_utc"]}


def get_profile(db: Any, user_id: str) -> dict[str, Any] | None:
    """The stored profile of `user_id`, or None when none was saved. Reads only that user's row."""
    row = db._one("SELECT * FROM profiles WHERE user_id = ?", (user_id,))
    return _row_doc(row) if row else None


def public_identity(db: Any, user_id: str | None) -> dict[str, Any]:
    """What anyone else may see: the name only when the owner turned it on and set one; never an email."""
    profile = get_profile(db, user_id) if user_id else None
    if profile is None:
        return {"name": None, "avatar": None, "credit_as_trainer": False}
    name = profile["public_name"] if profile["show_name"] and profile["public_name"] else None
    return {"name": name, "avatar": profile["avatar"], "credit_as_trainer": bool(profile["credit_me_as_trainer"])}


def update(db: Any, user_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    """Apply `patch` (only the keys sent change) and return the profile. `ProfileError` on any bad key or value."""
    if not isinstance(patch, dict) or any(k not in FIELDS for k in patch):
        raise ProfileError(MSG_UNKNOWN)
    user = db.user(user_id)
    values: dict[str, Any] = {}
    if "public_name" in patch:
        values["public_name"] = clean_name(patch["public_name"], (user or {}).get("email"))
    if "avatar" in patch:
        if patch["avatar"] is not None and (not isinstance(patch["avatar"], str) or patch["avatar"] not in AVATARS):
            raise ProfileError(MSG_AVATAR)
        values["avatar_key"] = patch["avatar"]
    if "modes" in patch:
        values["modes"] = json.dumps(_pick(patch["modes"], modes_mod.MODES, MSG_MODES))
    if "goals" in patch:
        values["goals"] = json.dumps(_pick(patch["goals"], tuple(GOALS), MSG_GOALS))
    for key in ("show_name", "credit_me_as_trainer", "model_only_view"):
        if key in patch:
            values[key] = _switch(patch[key])
    if "default_model_id" in patch:
        values["default_model_id"] = clean_model(patch["default_model_id"])
    now = _now()
    with db._lock:
        db._db.execute("INSERT OR IGNORE INTO profiles (user_id, created_utc, updated_utc) VALUES (?, ?, ?)",
                       (user_id, now, now))
        if values:
            cols = ", ".join(f"{k} = ?" for k in values)
            db._db.execute(f"UPDATE profiles SET {cols}, updated_utc = ? WHERE user_id = ?",
                           (*values.values(), now, user_id))
    return get_profile(db, user_id) or defaults()


def delete(db: Any, user_id: str) -> bool:
    """Remove the profile row (name, avatar, modes, goals, switches, default model, model only view). Takes are not touched."""
    with db._lock:
        return db._db.execute("DELETE FROM profiles WHERE user_id = ?", (user_id,)).rowcount > 0


def clear_default_model(db: Any, user_id: str, choice: str) -> bool:
    """Set `default_model_id` to none when it is `choice` (a model that was deleted), so the profile never names it."""
    with db._lock:
        return db._db.execute("UPDATE profiles SET default_model_id = NULL WHERE user_id = ? AND default_model_id = ?",
                              (user_id, choice)).rowcount > 0
