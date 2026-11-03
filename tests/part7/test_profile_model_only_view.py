""""Show only my 3D model" on the profile (docs/specs/model-default.md AC-MD10, AC-MD13): the additive
`profiles.model_only_view` column, the `model_only_view` field of `api/me/profile`, Download my data and delete."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest

from auth_support import authenv, get, post, sign_in  # noqa: F401
from part7 import auth, profile
from part7.identity import IdentityStore
from support import Api
from test_profile import PEPPER, make_user, old_db, send


def columns(db: sqlite3.Connection) -> set[str]:
    return {r[1] for r in db.execute("PRAGMA table_info(profiles)")}


@pytest.fixture()
def store(tmp_path: Path) -> IdentityStore:
    return IdentityStore(tmp_path, PEPPER)


def test_migration_backs_up_adds_the_column_and_old_rows_read_off(tmp_path: Path) -> None:  # AC-MD13
    old_db(tmp_path)
    path = tmp_path / "identity" / "identity.db"
    db = sqlite3.connect(str(path))
    profile.migrate(db, path)
    profile.migrate_default_model(db, path)
    db.execute("INSERT INTO profiles (user_id, public_name) VALUES ('u-1', 'Ada L')")
    db.commit()
    db.close()
    store = IdentityStore(tmp_path, PEPPER)
    assert "model_only_view" in columns(store._db)
    assert path.with_name(profile.VIEW_BACKUP_NAME).is_file()
    assert profile.get_profile(store, "u-1")["model_only_view"] is False  # negative: nobody is turned on by the migration
    assert profile.migrate_model_only_view(store._db, path) is False  # idempotent


def test_default_is_off_and_a_switch_round_trips(store: IdentityStore) -> None:  # AC-MD10, AC-MD13
    uid = make_user(store, "ada@example.com")
    assert profile.defaults()["model_only_view"] is False
    assert profile.update(store, uid, {"default_model_id": "skeleton"})["model_only_view"] is False
    assert profile.update(store, uid, {"model_only_view": True})["model_only_view"] is True
    form = {"public_name": "Ada L", "avatar": "fern", "modes": ["dance"], "goals": [], "show_name": True,
            "credit_me_as_trainer": False}  # the profile form's six keys keep it
    kept = profile.update(store, uid, form)
    assert kept["model_only_view"] is True and kept["default_model_id"] == "skeleton"
    assert profile.update(store, uid, {"model_only_view": False})["model_only_view"] is False


@pytest.mark.parametrize("bad", [1, 0, "true", None, [True]])
def test_only_a_boolean_is_accepted(store: IdentityStore, bad: Any) -> None:  # AC-MD13
    uid = make_user(store, "ada@example.com")
    with pytest.raises(profile.ProfileError):
        profile.update(store, uid, {"model_only_view": bad})
    assert profile.get_profile(store, uid) is None


def test_profile_delete_and_account_delete_remove_it(store: IdentityStore) -> None:  # AC-MD13
    ada, bob = make_user(store, "ada@example.com"), make_user(store, "bob@example.com")
    profile.update(store, ada, {"model_only_view": True})
    profile.update(store, bob, {"model_only_view": True})
    profile.delete(store, ada)
    assert (profile.get_profile(store, ada) or profile.defaults())["model_only_view"] is False
    assert profile.get_profile(store, bob)["model_only_view"] is True  # another account is untouched
    profile.update(store, ada, {"model_only_view": True})
    store.delete_user(ada)
    assert profile.get_profile(store, ada) is None


@pytest.mark.usefixtures("authenv")
def test_route_round_trip_export_and_delete_my_data(api: Api) -> None:  # AC-MD10, AC-MD13
    ada, grace = sign_in(api), sign_in(api, "grace@example.com")
    assert get(api, "api/me/profile", ada)[2]["model_only_view"] is False
    status, _, body = send(api, "PUT", "api/me/profile", {"default_model_id": "skeleton", "model_only_view": True}, ada)
    assert status == 200 and body["model_only_view"] is True
    assert get(api, "api/me/profile", grace)[2]["model_only_view"] is False  # negative: another account never has it
    assert send(api, "PUT", "api/me/profile", {"model_only_view": "yes"}, ada)[0] == 400
    exported = get(api, "api/me/export", ada)[2]
    assert exported["profile"]["model_only_view"] is True
    assert get(api, "api/me/export", grace)[2]["profile"]["model_only_view"] is False
    store = auth.identity(api.app)
    uid = store.session_user(ada)
    assert post(api, "api/me/delete", {"confirm": "delete"}, cookie=ada)[0] == 200
    assert profile.get_profile(store, uid) is None


@pytest.mark.usefixtures("authenv")
def test_signed_out_cannot_set_it(api: Api) -> None:  # AC-MD13
    assert send(api, "PUT", "api/me/profile", {"model_only_view": True})[0] == 401
