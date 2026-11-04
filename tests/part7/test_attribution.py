"""Author lines, the entry.author_state migration and the payload fields (docs/specs/attribution.md, TICKET-232)."""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import types
from typing import Any

import pytest

from auth_support import EMAIL, authenv, get, post, sign_in  # noqa: F401
from part7 import attribution, auth, identity
from support import Api

pytestmark = pytest.mark.usefixtures("authenv")
ENTRY = "lateral-raise"
PROFILES: dict[str, dict[str, Any]] = {}


def fake_profile(users: dict[str, dict[str, Any]]) -> types.SimpleNamespace:
    def public_identity(db: Any, user_id: str) -> dict[str, Any]:
        row = users.get(user_id, {})
        return {"name": row.get("name"), "avatar": row.get("avatar"), "credit_as_trainer": bool(row.get("credit"))}
    return types.SimpleNamespace(public_identity=public_identity)


@pytest.fixture()
def profiles(monkeypatch: pytest.MonkeyPatch) -> dict[str, dict[str, Any]]:
    users: dict[str, dict[str, Any]] = {}
    monkeypatch.setattr(attribution, "_profile", fake_profile(users))
    return users


def entry(uid: str, state: str = "owned", only_me: bool = False) -> dict[str, Any]:
    return {"kind": "entry", "user_id": uid, "author_state": state, "only_me": only_me}


def take(uid: str, trainer: dict[str, Any] | None, state: str = "owned") -> dict[str, Any]:
    return {"kind": "take", "user_id": uid, "author_state": state, "trainer": trainer}


# ----- author_line (table-driven) ----------------------------------------------------------------------
@pytest.mark.parametrize("profile, subject, author, credit", [
    ({"name": "Ada", "credit": True}, entry("t"), "Ada", None),
    ({"name": "Ada", "credit": False}, entry("t"), None, None),  # a trainer who did not opt in is neutral
    ({"name": None, "credit": True}, entry("t"), None, None),  # no public name
    ({"name": "Ada", "credit": True}, entry("t", "unattributed"), "NOAUTHOR", None),  # unattributed: no author at all
    ({"name": "Ada", "credit": True}, take("f", None), "Ada", None),
    ({"name": "Ada", "credit": True}, take("", None, "unattributed"), "NOAUTHOR", None),
])
def test_author_line_table(profiles: dict, profile: dict, subject: dict, author: Any, credit: Any) -> None:
    profiles.update({"t": profile, "f": profile})
    line = attribution.author_line(object(), subject)
    if author == "NOAUTHOR":
        assert line["author"] is None
    elif author is None:
        assert line["author"] is not None and line["author"]["name"] is None
    else:
        assert line["author"]["name"] == author
    assert line["trainer_credit"] == credit


@pytest.mark.parametrize("trainer_profile, trainer, named", [
    ({"name": "Tia", "credit": True}, entry("t"), True),
    ({"name": "Tia", "credit": False}, entry("t"), False),  # opt-in respected
    ({"name": "Tia", "credit": True}, entry("t", "unattributed"), False),
    ({"name": "Tia", "credit": True}, entry("t", only_me=True), False),  # only_me credits nobody
    ({"name": None, "credit": True}, entry("t"), False),
    ({"name": "Tia", "credit": True}, None, False),
])
def test_trainer_credit_on_a_follower_result(profiles: dict, trainer_profile: dict, trainer: Any, named: bool) -> None:
    profiles["t"] = trainer_profile
    credit = attribution.author_line(object(), take("", trainer, "unattributed"))["trainer_credit"]
    assert (credit["name"] if credit else None) == ("Tia" if named else None)


def test_no_profile_module_means_everyone_is_unnamed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(attribution, "_profile", None)
    line = attribution.author_line(object(), take("f", entry("t")))
    assert line == {"author": {"name": None, "avatar": None}, "trainer_credit": None}


def test_a_profile_fault_is_unnamed_not_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(db: Any, uid: str) -> dict:
        raise RuntimeError("down")
    monkeypatch.setattr(attribution, "_profile", types.SimpleNamespace(public_identity=boom))
    assert attribution.author_line(object(), entry("t"))["author"] == {"name": None, "avatar": None}


# ----- migration ---------------------------------------------------------------------------------------
OLD_SCHEMA = """
CREATE TABLE users (user_id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE, created_at REAL NOT NULL,
  last_seen_at REAL NOT NULL, consent_version TEXT, consent_at REAL, retention_opt_in INTEGER NOT NULL DEFAULT 0);
CREATE TABLE entries (entry_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, trainer_job TEXT NOT NULL DEFAULT '',
  only_me INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL);
"""


def old_db(folder: Path) -> Path:
    path = identity.db_path(folder)
    path.parent.mkdir(parents=True)
    db = sqlite3.connect(path)
    db.executescript(OLD_SCHEMA)
    db.execute("INSERT INTO users VALUES ('u-1', 'a@example.com', 1, 1, NULL, NULL, 0)")
    db.executemany("INSERT INTO entries VALUES (?, ?, ?, ?, ?)", [
        ("owned-1", "u-1", "job1", 0, 10.0), ("orphan", "u-gone", "job2", 0, 11.0),
        ("blank", "", "", 0, 12.0), ("private", "u-1", "job3", 1, 13.0)])
    db.commit()
    db.close()
    return path


def rows(path: Path) -> list[tuple]:
    db = sqlite3.connect(path)
    try:
        return db.execute("SELECT entry_id, user_id, trainer_job, only_me, created_at FROM entries ORDER BY entry_id").fetchall()
    finally:
        db.close()


def test_migration_marks_owned_and_unattributed_and_changes_nothing_else(tmp_path: Path) -> None:
    path = old_db(tmp_path)
    before = rows(path)
    store = identity.IdentityStore(tmp_path, b"p" * 32)
    states = {e: store.entry_author(e)["author_state"] for e in ("owned-1", "orphan", "blank", "private")}
    assert states == {"owned-1": "owned", "orphan": "unattributed", "blank": "unattributed", "private": "owned"}
    assert rows(path) == before  # every other column byte for byte
    backup = Path(str(path) + identity.BACKUP_SUFFIX)
    assert backup.is_file() and rows(backup) == before and (backup.stat().st_mode & 0o777) == 0o600
    assert not any(r[1] == "author_state" for r in sqlite3.connect(backup).execute("PRAGMA table_info(entries)"))


def test_migration_is_idempotent(tmp_path: Path) -> None:
    path = old_db(tmp_path)
    identity.IdentityStore(tmp_path, b"p" * 32)
    backup = Path(str(path) + identity.BACKUP_SUFFIX)
    first = backup.stat().st_mtime_ns
    db = sqlite3.connect(path)
    db.execute("UPDATE entries SET author_state = 'unattributed' WHERE entry_id = 'owned-1'")  # a later decision
    db.commit()
    db.close()
    store = identity.IdentityStore(tmp_path, b"p" * 32)
    assert store.entry_author("owned-1")["author_state"] == "unattributed"  # not re-derived
    assert backup.stat().st_mtime_ns == first  # no second copy
    db = sqlite3.connect(path)
    assert identity.migrate_attribution(db, path) is False
    db.close()


def test_migration_refuses_when_the_copy_fails_and_leaves_the_database_alone(tmp_path: Path) -> None:
    path = old_db(tmp_path)
    Path(str(path) + identity.BACKUP_SUFFIX).mkdir()  # the copy cannot be written
    with pytest.raises(RuntimeError, match="refused"):
        identity.IdentityStore(tmp_path, b"p" * 32)
    db = sqlite3.connect(path)
    assert not any(r[1] == "author_state" for r in db.execute("PRAGMA table_info(entries)"))
    db.close()


def test_new_entries_are_owned_and_a_fresh_store_has_the_column(tmp_path: Path) -> None:
    store = identity.IdentityStore(tmp_path, b"p" * 32)
    store.attach_entry("e1", "u-9", "")
    assert store.entry_author("e1") == {"user_id": "u-9", "author_state": "owned", "only_me": False}
    assert store.entry_author("missing") is None


# ----- payload fields over a real server ---------------------------------------------------------------
def make_job(api: Api, **fields: Any) -> str:
    made = api.app.queue.submit("follow", lambda ctx: {"result": {}}, entry_id=ENTRY, **fields)
    assert api.app.queue.wait(made["id"], 10)["status"] == "done"
    return made["id"]


def uid_of(api: Api, sid: str) -> str:
    return get(api, "api/auth/me", cookie=sid)[2]["user_id"]


def test_teacher_entry_payload_names_an_opted_in_trainer_only(api: Api, profiles: dict) -> None:
    sid = sign_in(api)
    owner = uid_of(api, sid)
    auth.identity(api.app).attach_entry(ENTRY, owner, "")
    profiles[owner] = {"name": "Tia", "credit": True, "avatar": "owl"}
    doc = get(api, f"api/teacher/{ENTRY}")[2]["attribution"]
    assert doc["kind"] == "entry" and doc["author"] == {"name": "Tia", "avatar": "owl"} and doc["mine"] is False
    assert get(api, f"api/teacher/{ENTRY}", cookie=sid)[2]["attribution"]["mine"] is True
    profiles[owner]["credit"] = False  # read at request time: the next request is neutral
    assert get(api, f"api/teacher/{ENTRY}")[2]["attribution"]["author"] == {"name": None, "avatar": None}


def test_an_entry_made_signed_out_is_unattributed_and_shows_no_name(api: Api, profiles: dict) -> None:
    doc = get(api, f"api/teacher/{ENTRY}")[2]["attribution"]
    assert doc["author"] is None and doc["trainer_credit"] is None


def test_follower_result_credits_the_trainer_only_on_opt_in(api: Api, profiles: dict) -> None:
    trainer, follower = sign_in(api), sign_in(api, "grace@example.com")
    tid, fid = uid_of(api, trainer), uid_of(api, follower)
    auth.identity(api.app).attach_entry(ENTRY, tid, "")
    job = make_job(api)
    auth.identity(api.app).attach(job, fid, "follow", ENTRY, None, "submit")
    profiles[tid] = {"name": "Tia", "credit": True}
    profiles[fid] = {"name": None}  # Grace kept show_name off: public_identity gives no name
    doc = get(api, f"api/jobs/{job}", cookie=follower)[2]["attribution"]  # B2: an owned take answers its owner only
    assert doc["trainer_credit"]["name"] == "Tia" and doc["author"] == {"name": None, "avatar": None}  # follower hid the name
    profiles[tid]["credit"] = False
    assert get(api, f"api/jobs/{job}", cookie=follower)[2]["attribution"]["trainer_credit"] is None
    anon = make_job(api)  # an anonymous follower: no follower name is invented
    profiles[tid]["credit"] = True
    doc = get(api, f"api/jobs/{anon}")[2]["attribution"]
    assert doc["author"] is None and doc["trainer_credit"]["name"] == "Tia"
    mine = get(api, "api/me/takes", cookie=follower)[2]["takes"][0]["attribution"]
    assert mine["mine"] is True


def test_deleting_profile_details_makes_every_surface_neutral(api: Api, profiles: dict) -> None:
    sid = sign_in(api)
    uid = uid_of(api, sid)
    auth.identity(api.app).attach_entry(ENTRY, uid, "")
    job = make_job(api)
    auth.identity(api.app).attach(job, uid, "follow", ENTRY, None, "submit")
    profiles[uid] = {"name": "Tia", "credit": True, "avatar": "owl"}
    surfaces = [lambda: get(api, f"api/teacher/{ENTRY}")[2], lambda: get(api, f"api/jobs/{job}", cookie=sid)[2],
                lambda: get(api, "api/me/entries", cookie=sid)[2]["entries"][0], lambda: get(api, "api/me/takes", cookie=sid)[2]["takes"][0]]
    assert "Tia" in json.dumps([s() for s in surfaces])
    profiles.clear()
    assert "Tia" not in json.dumps([s() for s in surfaces])


def test_no_payload_ever_carries_an_email(api: Api, profiles: dict) -> None:
    sid = sign_in(api)
    uid = uid_of(api, sid)
    auth.identity(api.app).attach_entry(ENTRY, uid, "")
    job = make_job(api)
    auth.identity(api.app).attach(job, uid, "follow", ENTRY, None, "submit")
    profiles[uid] = {"name": "Tia", "credit": True}
    bodies = [get(api, f"api/teacher/{ENTRY}")[2], get(api, f"api/jobs/{job}", cookie=sid)[2], get(api, "api/me/entries", cookie=sid)[2],
              get(api, "api/me/takes", cookie=sid)[2]]
    text = json.dumps(bodies)
    assert EMAIL.lower() not in text.lower() and "@" not in json.dumps([b.get("attribution", b) for b in bodies[:2]])


def test_result_answer_says_whether_the_viewer_owns_it_and_whether_there_is_narration(api: Api, profiles: dict) -> None:
    """The result page asks for owner-only data (ask-trainer, since-last-time) only when `attribution.mine`, and for the
    narration only when `narration` (staging intake check: a non-owner's result drew three 404s)."""
    owner, other = sign_in(api), sign_in(api, "grace@example.com")
    job = make_job(api)
    auth.identity(api.app).attach(job, uid_of(api, owner), "follow", ENTRY, None, "submit")
    assert get(api, f"api/jobs/{job}", cookie=owner)[2]["attribution"]["mine"] is True
    assert get(api, f"api/jobs/{job}", cookie=other)[0] == 404  # negative: another account (B2: not even the record)
    assert get(api, f"api/jobs/{job}")[0] == 404  # negative: signed out
    anon = make_job(api)  # an anonymous take answers whoever holds its id, and is nobody's
    assert get(api, f"api/jobs/{anon}", cookie=other)[2]["attribution"]["mine"] is False
    assert get(api, f"api/jobs/{job}", cookie=owner)[2]["narration"] is False
    folder = api.app.child.catalog_dir / ENTRY
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "narration.json").write_text(json.dumps({"cues": []}))
    assert get(api, f"api/jobs/{job}", cookie=owner)[2]["narration"] is True
