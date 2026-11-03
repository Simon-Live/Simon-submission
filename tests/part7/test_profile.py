"""Profile store and routes (docs/specs/profile.md AC-PR-1 to AC-PR-10; TICKET-231 server side)."""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from typing import Any

import pytest

from auth_support import EMAIL, authenv, get, origin, post, sign_in  # noqa: F401
from part7 import auth, identity, profile
from part7.identity import IdentityStore
from support import Api

PEPPER = b"p" * 32


@pytest.fixture()
def store(tmp_path: Path) -> IdentityStore:
    return IdentityStore(tmp_path, PEPPER)


def make_user(store: IdentityStore, email: str) -> str:
    return store._user_for(email, store.clock())


def send(api: Api, method: str, path: str, doc: Any = None, cookie: str | None = None) -> tuple[int, dict, Any]:
    hdr = {"Content-Type": "application/json", "Origin": origin(api)}
    if cookie:
        hdr["Cookie"] = f"{auth.COOKIE}={cookie}"
    status, head, data = api.request(method, path, json.dumps(doc or {}).encode(), hdr)
    return status, head, (json.loads(data) if data else None)


# ----- store ----------------------------------------------------------------------------------------
def test_fresh_account_has_closed_defaults(store: IdentityStore) -> None:  # AC-PR-3
    uid = make_user(store, "ada@example.com")
    assert profile.get_profile(store, uid) is None
    assert profile.public_identity(store, uid) == {"name": None, "avatar": None, "credit_as_trainer": False}
    saved = profile.update(store, uid, {})
    assert (saved["show_name"], saved["credit_me_as_trainer"], saved["public_name"], saved["avatar"]) == (False, False, None, None)
    assert saved["modes"] == [] and saved["goals"] == []


def test_public_identity_shows_name_only_when_chosen(store: IdentityStore) -> None:  # AC-PR-4
    uid = make_user(store, "ada@example.com")
    profile.update(store, uid, {"public_name": "Ada L", "avatar": "fern", "credit_me_as_trainer": True})
    assert profile.public_identity(store, uid) == {"name": None, "avatar": "fern", "credit_as_trainer": True}
    profile.update(store, uid, {"show_name": True})
    assert profile.public_identity(store, uid)["name"] == "Ada L"
    profile.update(store, uid, {"public_name": None})
    assert profile.public_identity(store, uid)["name"] is None
    assert profile.public_identity(store, None)["name"] is None
    assert "ada@example.com" not in json.dumps(profile.public_identity(store, uid))


@pytest.mark.parametrize("bad", ["", "   ", "x" * 41, "a@b", "Ada\x00", "Ada\n", "ada","ADA@EXAMPLE.COM", 5, ["a"]])
def test_bad_names_refused(store: IdentityStore, bad: Any) -> None:  # AC-PR-5
    uid = make_user(store, "ada@example.com")
    with pytest.raises(profile.ProfileError):
        profile.update(store, uid, {"public_name": bad})
    assert profile.get_profile(store, uid) is None


def test_name_is_nfkc_trimmed_and_capped(store: IdentityStore) -> None:
    uid = make_user(store, "bob@example.com")
    assert profile.update(store, uid, {"public_name": "  Ａda  "})["public_name"] == "Ada"
    assert profile.update(store, uid, {"public_name": "y" * 40})["public_name"] == "y" * 40


def test_lists_and_switches_validated(store: IdentityStore) -> None:  # AC-PR-6
    uid = make_user(store, "ada@example.com")
    for patch in ({"avatar": "../x"}, {"avatar": 3}, {"modes": ["yoga"]}, {"modes": "dance"}, {"goals": ["win"]},
                  {"show_name": 1}, {"credit_me_as_trainer": "yes"}, {"email": "a@b.c"}, {"user_id": "u-x"}):
        with pytest.raises(profile.ProfileError):
            profile.update(store, uid, patch)
    out = profile.update(store, uid, {"modes": ["fitness", "dance", "dance"], "goals": ["steady_practice", "learn_the_moves"]})
    assert out["modes"] == ["dance", "fitness"] and out["goals"] == ["learn_the_moves", "steady_practice"]
    assert profile.update(store, uid, {"avatar": profile.AVATARS[0]})["avatar"] == profile.AVATARS[0]
    assert profile.update(store, uid, {"avatar": None})["avatar"] is None


def test_update_is_idempotent_and_partial(store: IdentityStore) -> None:
    uid = make_user(store, "ada@example.com")
    first = profile.update(store, uid, {"public_name": "Ada L", "modes": ["dance"]})
    again = profile.update(store, uid, {"public_name": "Ada L", "modes": ["dance"]})
    assert {k: v for k, v in first.items() if k != "updated_utc"} == {k: v for k, v in again.items() if k != "updated_utc"}
    assert profile.update(store, uid, {"goals": ["steady_practice"]})["public_name"] == "Ada L"


def test_delete_removes_row_and_user_delete_cascades(store: IdentityStore) -> None:  # AC-PR-8
    ada, bob = make_user(store, "ada@example.com"), make_user(store, "bob@example.com")
    profile.update(store, ada, {"public_name": "Ada L"})
    profile.update(store, bob, {"public_name": "Bob K"})
    assert profile.delete(store, ada) is True and profile.delete(store, ada) is False
    assert profile.get_profile(store, ada) is None and profile.get_profile(store, bob)["public_name"] == "Bob K"
    profile.update(store, ada, {"public_name": "Ada L"})
    store.delete_user(ada)
    assert profile.get_profile(store, ada) is None and profile.get_profile(store, bob) is not None


def test_prune_of_idle_account_removes_profile(tmp_path: Path) -> None:  # AC-PR-8
    clock = [1_800_000_000.0]
    store = IdentityStore(tmp_path, PEPPER, lambda: clock[0])
    uid = make_user(store, "ada@example.com")
    profile.update(store, uid, {"public_name": "Ada L"})
    clock[0] += identity.ACCOUNT_IDLE_S + 10
    store.prune(tmp_path)
    assert profile.get_profile(store, uid) is None


# ----- migration ------------------------------------------------------------------------------------
OLD_SCHEMA = [s for s in identity._SCHEMA.split(";") if s.strip()]


def old_db(path: Path) -> None:
    (path / "identity").mkdir(parents=True)
    db = sqlite3.connect(str(path / "identity" / "identity.db"))
    for stmt in OLD_SCHEMA:
        db.execute(stmt)
    db.execute("INSERT INTO users (user_id, email, created_at, last_seen_at) VALUES ('u-1', 'a@b.co', 1, 1)")
    db.commit()
    db.close()


def test_migration_backs_up_then_adds_table_and_is_idempotent(tmp_path: Path) -> None:  # AC-PR-9
    old_db(tmp_path)
    store = IdentityStore(tmp_path, PEPPER)
    backup = tmp_path / "identity" / profile.BACKUP_NAME
    assert backup.is_file() and (backup.stat().st_mode & 0o777) == 0o600
    copy = sqlite3.connect(str(backup))
    assert copy.execute("SELECT email FROM users").fetchone()[0] == "a@b.co"
    assert not copy.execute("SELECT name FROM sqlite_master WHERE name='profiles'").fetchall()
    copy.close()
    assert store.user("u-1")["email"] == "a@b.co"
    before = store._q("SELECT sql FROM sqlite_master WHERE name='profiles'")[0][0]
    store._db.close()
    again = IdentityStore(tmp_path, PEPPER)
    assert again._q("SELECT sql FROM sqlite_master WHERE name='profiles'")[0][0] == before
    assert again.user("u-1")["email"] == "a@b.co"


def test_migration_refuses_when_backup_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # AC-PR-9
    old_db(tmp_path)

    def boom(self: Any, target: Any, **kw: Any) -> None:
        raise sqlite3.OperationalError("disk full")

    class Conn(sqlite3.Connection):
        backup = boom  # type: ignore[assignment]

    db = sqlite3.connect(str(tmp_path / "identity" / "identity.db"), factory=Conn)
    with pytest.raises(RuntimeError, match="refused"):
        profile.migrate(db, tmp_path / "identity" / "identity.db")
    assert not db.execute("SELECT name FROM sqlite_master WHERE name='profiles'").fetchall()
    assert not (tmp_path / "identity" / profile.BACKUP_NAME).exists()


# ----- routes ---------------------------------------------------------------------------------------
@pytest.mark.usefixtures("authenv")
def test_signed_out_is_401(api: Api) -> None:  # AC-PR-1
    assert get(api, "api/me/profile")[0] == 401
    assert get(api, "api/avatars")[0] == 401
    assert send(api, "PUT", "api/me/profile", {"public_name": "Ada L"})[0] == 401
    assert send(api, "DELETE", "api/me/profile")[0] == 401


def without_lists(body: dict) -> dict:
    """The profile fields alone: GET also answers the owner's entries, movements and summary (profile_summary.py, tests in test_as_fixes.py)."""
    return {k: v for k, v in body.items() if k not in ("entries", "movements", "summary")}


@pytest.mark.usefixtures("authenv")
def test_owner_round_trip_and_defaults(api: Api) -> None:  # AC-PR-2, 3
    sid = sign_in(api)
    status, _, body = get(api, "api/me/profile", sid)
    assert status == 200 and body["show_name"] is False and body["credit_me_as_trainer"] is False
    assert body["public_name"] is None and body["modes"] == []
    status, _, body = send(api, "PUT", "api/me/profile", {"public_name": "Ada L", "avatar": "tide", "modes": ["dance"],
                                                          "goals": ["steady_practice"], "show_name": True}, sid)
    assert status == 200 and body["public_name"] == "Ada L" and body["show_name"] is True
    assert without_lists(get(api, "api/me/profile", sid)[2]) == body
    status, _, body = send(api, "DELETE", "api/me/profile", None, sid)
    assert status == 200 and body["deleted"] is True
    again = get(api, "api/me/profile", sid)[2]
    assert again["public_name"] is None and again["show_name"] is False


@pytest.mark.usefixtures("authenv")
def test_name_equal_to_email_local_part_refused(api: Api) -> None:  # AC-PR-5
    sid = sign_in(api)  # Ada.Lovelace@Example.com
    assert send(api, "PUT", "api/me/profile", {"public_name": "ada.lovelace"}, sid)[0] == 400
    assert send(api, "PUT", "api/me/profile", {"public_name": "Ada L"}, sid)[0] == 200


@pytest.mark.usefixtures("authenv")
def test_other_user_never_sees_it_and_email_never_returned(api: Api) -> None:  # AC-PR-7
    ada, grace = sign_in(api), sign_in(api, "grace@example.com")
    texts = [json.dumps(send(api, "PUT", "api/me/profile", {"public_name": "Ada Secret", "avatar": "sun"}, ada)[2])]
    texts.append(json.dumps(get(api, "api/me/profile", ada)[2]))
    other = get(api, "api/me/profile", grace)[2]
    texts += [json.dumps(other), json.dumps(get(api, "api/avatars", grace)[2]),
              json.dumps(send(api, "DELETE", "api/me/profile", None, grace)[2])]
    assert other["public_name"] is None and other["avatar"] is None
    for text in texts:
        assert "example.com" not in text.lower() and "lovelace" not in text.lower() and "@" not in text
    assert get(api, "api/me/profile", ada)[2]["public_name"] == "Ada Secret"  # grace's delete left it


@pytest.mark.usefixtures("authenv")
def test_bad_input_400_and_csrf_403(api: Api) -> None:  # AC-PR-5, 6
    sid = sign_in(api)
    for doc in ({"public_name": "me@x.co"}, {"avatar": "nope"}, {"modes": ["x"]},
                {"goals": ["x"]}, {"show_name": "true"}, {"role": "admin"}):
        status, _, body = send(api, "PUT", "api/me/profile", doc, sid)
        assert status == 400 and body["ok"] is False, doc
    assert get(api, "api/me/profile", sid)[2]["public_name"] is None
    hdr = {"Cookie": f"{auth.COOKIE}={sid}", "Content-Type": "application/json"}
    assert api.request("PUT", "api/me/profile", b"{}", hdr)[0] == 403  # no Origin
    assert api.request("DELETE", "api/me/profile", b"{}", hdr)[0] == 403


@pytest.mark.usefixtures("authenv")
def test_avatars_and_options(api: Api) -> None:  # AC-PR-6
    sid = sign_in(api)
    status, _, body = get(api, "api/avatars", sid)
    assert status == 200 and tuple(body["avatars"]) == profile.AVATARS and body["modes"] == ["dance", "rehab", "fitness"]
    assert {g["key"] for g in body["goals"]} == set(profile.GOALS)


@pytest.mark.usefixtures("authenv")
def test_account_delete_removes_profile_row(api: Api) -> None:  # AC-PR-8
    sid = sign_in(api)
    send(api, "PUT", "api/me/profile", {"public_name": "Ada L"}, sid)
    store = auth.identity(api.app)
    uid = store.session_user(sid)
    assert profile.get_profile(store, uid) is not None
    assert post(api, "api/me/delete", {"confirm": "delete"}, cookie=sid)[0] == 200
    assert profile.get_profile(store, uid) is None


@pytest.mark.usefixtures("authenv")
def test_sign_in_off_leaves_no_trace(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:  # AC-PR-10
    monkeypatch.setenv("SIMON7_MAIL_TRANSPORT", "off")
    assert get(api, "api/me/profile")[0] == 404 and get(api, "api/avatars")[0] == 404


@pytest.mark.usefixtures("authenv")
def test_web_to_wire_body_is_accepted_and_options_match(api: Api) -> None:  # web toWire x api/avatars
    """The exact PUT body `toWire` makes for a full draft, with option ids taken from `GET api/avatars`."""
    sid = sign_in(api)
    opts = get(api, "api/avatars", sid)[2]
    body = {"public_name": "Sam", "avatar": opts["avatars"][2], "modes": [opts["modes"][0]],
            "goals": [opts["goals"][0]["key"]], "show_name": True, "credit_me_as_trainer": False}
    status, _, saved = send(api, "PUT", "api/me/profile", body, sid)
    assert status == 200
    assert {k: saved[k] for k in body} == body
    assert without_lists(get(api, "api/me/profile", sid)[2]) == saved
