"""The default model for "You" on the profile (docs/specs/profile.md AC-PR-12 to AC-PR-15): the additive
`profiles.default_model_id` column, its migration and the `default_model_id` field of `api/me/profile`."""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from typing import Any

import pytest

from auth_support import authenv, get, post, sign_in  # noqa: F401
from part7 import auth, profile
from part7.identity import IdentityStore
from support import Api
from test_profile import PEPPER, make_user, old_db, send

GOOD = ["person", "skeleton", "lib:ual1-mannequin", "lib:rigged_figure.v2", "up:" + "a" * 32, "lib:" + "x" * 64]
BAD = ["", "lib:", "up:", "LIB:x", "lib:-x", "lib:a/b", "up:../etc", "lib:a b", "me", "lib:" + "x" * 65, 5, True,
       ["lib:x"], {"id": "lib:x"}]


def columns(db: sqlite3.Connection) -> set[str]:
    return {r[1] for r in db.execute("PRAGMA table_info(profiles)")}


def profiles_without_column(tmp_path: Path) -> Path:
    """A database from before this change: accounts and a `profiles` table with no `default_model_id`."""
    old_db(tmp_path)
    path = tmp_path / "identity" / "identity.db"
    db = sqlite3.connect(str(path))
    profile.migrate(db, path)
    db.execute("INSERT INTO profiles (user_id, public_name) VALUES ('u-1', 'Ada L')")
    db.commit()
    db.close()
    return path


# ----- migration ------------------------------------------------------------------------------------
def test_migration_backs_up_then_adds_column_and_is_idempotent(tmp_path: Path) -> None:  # AC-PR-12
    path = profiles_without_column(tmp_path)
    store = IdentityStore(tmp_path, PEPPER)
    backup = path.with_name(profile.MODEL_BACKUP_NAME)
    assert backup.is_file() and (backup.stat().st_mode & 0o777) == 0o600
    copy = sqlite3.connect(str(backup))
    assert "default_model_id" not in columns(copy) and copy.execute("SELECT public_name FROM profiles").fetchone()[0] == "Ada L"
    copy.close()
    assert "default_model_id" in columns(store._db)
    kept = profile.get_profile(store, "u-1")
    assert kept["public_name"] == "Ada L" and kept["default_model_id"] is None  # old rows keep their values, no default
    assert profile.migrate_default_model(store._db, path) is False
    before = backup.stat().st_mtime_ns
    store._db.close()
    again = IdentityStore(tmp_path, PEPPER)
    assert "default_model_id" in columns(again._db) and backup.stat().st_mtime_ns == before
    assert profile.get_profile(again, "u-1")["public_name"] == "Ada L"


def test_migration_refuses_when_backup_fails(tmp_path: Path) -> None:  # AC-PR-12
    path = profiles_without_column(tmp_path)

    def boom(self: Any, target: Any, **kw: Any) -> None:
        raise sqlite3.OperationalError("disk full")

    class Conn(sqlite3.Connection):
        backup = boom  # type: ignore[assignment]

    db = sqlite3.connect(str(path), factory=Conn)
    with pytest.raises(RuntimeError, match="default model migration refused"):
        profile.migrate_default_model(db, path)
    assert "default_model_id" not in columns(db)
    assert not path.with_name(profile.MODEL_BACKUP_NAME).exists()


def test_new_database_gets_the_column_without_a_backup(tmp_path: Path) -> None:  # AC-PR-12
    store = IdentityStore(tmp_path, PEPPER)
    assert "default_model_id" in columns(store._db)
    assert not (tmp_path / "identity" / profile.MODEL_BACKUP_NAME).exists()  # nothing to keep: no accounts yet


# ----- store ----------------------------------------------------------------------------------------
@pytest.fixture()
def store(tmp_path: Path) -> IdentityStore:
    return IdentityStore(tmp_path, PEPPER)


@pytest.mark.parametrize("good", GOOD)
def test_choice_ids_accepted(store: IdentityStore, good: str) -> None:  # AC-PR-13
    uid = make_user(store, "ada@example.com")
    assert profile.update(store, uid, {"default_model_id": good})["default_model_id"] == good


@pytest.mark.parametrize("bad", BAD)
def test_other_values_refused(store: IdentityStore, bad: Any) -> None:  # AC-PR-13
    uid = make_user(store, "ada@example.com")
    with pytest.raises(profile.ProfileError, match="Pick a model"):
        profile.update(store, uid, {"default_model_id": bad})
    assert profile.get_profile(store, uid) is None  # a refusal writes nothing


def test_partial_updates_keep_it_and_null_clears_it(store: IdentityStore) -> None:  # AC-PR-13
    uid = make_user(store, "ada@example.com")
    assert profile.defaults()["default_model_id"] is None
    profile.update(store, uid, {"default_model_id": "lib:ual1-mannequin"})
    form = {"public_name": "Ada L", "avatar": "fern", "modes": ["dance"], "goals": [], "show_name": True,
            "credit_me_as_trainer": False}  # the profile form's six keys
    assert profile.update(store, uid, form)["default_model_id"] == "lib:ual1-mannequin"
    cleared = profile.update(store, uid, {"default_model_id": None})
    assert cleared["default_model_id"] is None and cleared["public_name"] == "Ada L"


def test_delete_and_account_delete_clear_it(store: IdentityStore) -> None:  # AC-PR-14
    ada, bob = make_user(store, "ada@example.com"), make_user(store, "bob@example.com")
    profile.update(store, ada, {"default_model_id": "skeleton"})
    profile.update(store, bob, {"default_model_id": "person"})
    profile.delete(store, ada)
    assert (profile.get_profile(store, ada) or profile.defaults())["default_model_id"] is None
    assert profile.get_profile(store, bob)["default_model_id"] == "person"
    profile.update(store, ada, {"default_model_id": "skeleton"})
    store.delete_user(ada)
    assert profile.get_profile(store, ada) is None


# ----- routes ---------------------------------------------------------------------------------------
@pytest.mark.usefixtures("authenv")
def test_signed_out_is_401(api: Api) -> None:  # AC-PR-15
    assert send(api, "PUT", "api/me/profile", {"default_model_id": "skeleton"})[0] == 401


@pytest.mark.usefixtures("authenv")
def test_round_trip_owner_only(api: Api) -> None:  # AC-PR-13, AC-PR-15
    ada, grace = sign_in(api), sign_in(api, "grace@example.com")
    assert get(api, "api/me/profile", ada)[2]["default_model_id"] is None
    status, _, body = send(api, "PUT", "api/me/profile", {"default_model_id": "lib:ual1-mannequin"}, ada)
    assert status == 200 and body["default_model_id"] == "lib:ual1-mannequin"
    assert get(api, "api/me/profile", ada)[2]["default_model_id"] == "lib:ual1-mannequin"
    assert get(api, "api/me/profile", grace)[2]["default_model_id"] is None  # another account never sees it
    assert send(api, "PUT", "api/me/profile", {"default_model_id": None}, ada)[2]["default_model_id"] is None


@pytest.mark.usefixtures("authenv")
def test_bad_values_400(api: Api) -> None:  # AC-PR-13
    sid = sign_in(api)
    send(api, "PUT", "api/me/profile", {"default_model_id": "skeleton"}, sid)
    for bad in BAD:
        status, _, body = send(api, "PUT", "api/me/profile", {"default_model_id": bad}, sid)
        assert status == 400 and body["ok"] is False and "@" not in json.dumps(body), bad
    assert get(api, "api/me/profile", sid)[2]["default_model_id"] == "skeleton"


@pytest.mark.usefixtures("authenv")
def test_profile_delete_and_delete_my_data_clear_it(api: Api) -> None:  # AC-PR-14
    sid = sign_in(api)
    send(api, "PUT", "api/me/profile", {"default_model_id": "skeleton"}, sid)
    status, _, body = send(api, "DELETE", "api/me/profile", None, sid)
    assert status == 200 and body["default_model_id"] is None
    assert get(api, "api/me/profile", sid)[2]["default_model_id"] is None
    send(api, "PUT", "api/me/profile", {"default_model_id": "skeleton"}, sid)
    store = auth.identity(api.app)
    uid = store.session_user(sid)
    assert post(api, "api/me/delete", {"confirm": "delete"}, cookie=sid)[0] == 200
    assert profile.get_profile(store, uid) is None
