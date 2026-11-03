"""Signed-in devices: label, migration, list, end one, end others, delete and prune (docs/specs/devices.md AC-DV-1 to 10; TICKET-235)."""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from typing import Any

import pytest

from auth_support import authenv, get, post, sign_in  # noqa: F401
from part7 import applog, auth, devices, identity
from part7.identity import IdentityStore
from support import Api

pytestmark = pytest.mark.usefixtures("authenv")
PEPPER = b"d" * 32
UA_FIREFOX = "Mozilla/5.0 (Android 14; Mobile; rv:126.0) Gecko/126.0 Firefox/126.0"
UA_CHROME = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
UA_SAFARI = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
ANN, BOB = "ann@example.com", "bob@example.com"


def ua(text: str) -> dict[str, str]:
    return {"User-Agent": text}


def listing(api: Api, sid: str) -> list[dict[str, Any]]:
    status, _, body = get(api, "api/me/sessions", cookie=sid)
    assert status == 200
    return body


def end_url(public_id: str) -> str:
    return f"api/me/sessions/{public_id}/end"


# ----- the label ---------------------------------------------------------------------------------------
@pytest.mark.parametrize("agent, label", [
    (UA_FIREFOX, "Firefox on Android"),
    (UA_CHROME, "Chrome on Windows"),
    (UA_SAFARI, "Safari on iPhone"),
    ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36 Edg/126.0", "Edge on Linux"),
    ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Gecko/20100101 Firefox/126.0", "Firefox on macOS"),
    ("curl/8.5.0", "Unknown browser"),
    ("Mozilla/5.0 (X11; Linux x86_64)", "Unknown browser on Linux"),
    ("Firefox/126.0", "Firefox"),
    ("", "Unknown browser"),
    (None, "Unknown browser"),
])
def test_device_label_comes_from_the_word_lists(agent: Any, label: str) -> None:  # AC-DV-1
    assert devices.device_label(agent) == label


def test_device_label_is_short_and_never_the_raw_agent() -> None:  # AC-DV-1
    agent = "Evil/1.0 " * 200 + "Firefox/9 Android"
    out = devices.device_label(agent)
    assert len(out) <= devices.LABEL_MAX and "Evil" not in out and out == "Firefox on Android"


# ----- migration ------------------------------------------------------------------------------------------
def legacy_db(tmp_path: Path) -> Path:
    """A database built by the previous schema: sessions without the two columns, two accounts, three sessions."""
    folder = tmp_path / "identity"
    folder.mkdir()
    path = identity.db_path(tmp_path)
    old_sessions = ("CREATE TABLE IF NOT EXISTS sessions (\n  sid_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL, created_at REAL NOT NULL, "
                    "last_seen_at REAL NOT NULL,\n  expires_at REAL NOT NULL);")
    schema = identity._SCHEMA.replace(identity._SCHEMA[identity._SCHEMA.index("CREATE TABLE IF NOT EXISTS sessions"):
                                                       identity._SCHEMA.index("CREATE INDEX IF NOT EXISTS sessions_user")], old_sessions + "\n")
    db = sqlite3.connect(str(path))
    db.executescript(schema)
    db.execute("INSERT INTO users (user_id, email, created_at, last_seen_at) VALUES ('u-1', 'a@example.com', 1, 1)")
    db.execute("INSERT INTO users (user_id, email, created_at, last_seen_at) VALUES ('u-2', 'b@example.com', 1, 1)")
    for i, user in enumerate(("u-1", "u-1", "u-2")):
        db.execute("INSERT INTO sessions VALUES (?, ?, ?, ?, ?)", (f"hash{i}", user, 100.0 + i, 200.0 + i, 9e12))
    db.commit()
    db.close()
    return path


def rows(path: Path) -> list[tuple]:
    db = sqlite3.connect(str(path))
    try:
        return db.execute("SELECT sid_hash, user_id, created_at, last_seen_at, expires_at, public_id, device FROM sessions ORDER BY sid_hash").fetchall()
    finally:
        db.close()


def test_migration_adds_columns_keeps_the_rest_and_is_idempotent(tmp_path: Path) -> None:  # AC-DV-1
    path = legacy_db(tmp_path)
    store = IdentityStore(tmp_path, PEPPER)
    first = rows(path)
    assert [r[:5] for r in first] == [("hash0", "u-1", 100.0, 200.0, 9e12), ("hash1", "u-1", 101.0, 201.0, 9e12), ("hash2", "u-2", 102.0, 202.0, 9e12)]
    ids = [r[5] for r in first]
    assert len(set(ids)) == 3 and all(devices.ID_RE.match(i) for i in ids)
    assert {r[6] for r in first} == {"Unknown browser"}
    assert path.with_name(devices.BACKUP_NAME).is_file()
    store._db.close()
    again = IdentityStore(tmp_path, PEPPER)  # a second open changes nothing
    assert rows(path) == first
    again._db.close()


def test_migration_backup_holds_the_old_schema(tmp_path: Path) -> None:  # AC-DV-1
    path = legacy_db(tmp_path)
    IdentityStore(tmp_path, PEPPER)._db.close()
    copy = sqlite3.connect(str(path.with_name(devices.BACKUP_NAME)))
    cols = [r[1] for r in copy.execute("PRAGMA table_info(sessions)")]
    assert "public_id" not in cols and copy.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 3
    copy.close()


def test_migration_refuses_when_the_copy_fails(tmp_path: Path) -> None:  # AC-DV-1
    path = legacy_db(tmp_path)
    path.with_name(devices.BACKUP_NAME).symlink_to(tmp_path / "nowhere" / "copy.db")  # the copy cannot be written
    with pytest.raises((RuntimeError, sqlite3.Error)):
        IdentityStore(tmp_path, PEPPER)
    db = sqlite3.connect(str(path))
    assert "public_id" not in [r[1] for r in db.execute("PRAGMA table_info(sessions)")]  # nothing changed
    db.close()


def test_a_fresh_database_needs_no_copy(tmp_path: Path) -> None:  # AC-DV-1
    IdentityStore(tmp_path, PEPPER)._db.close()
    assert not identity.db_path(tmp_path).with_name(devices.BACKUP_NAME).exists()


# ----- list ------------------------------------------------------------------------------------------------
def test_signed_out_list_is_401_with_the_usual_text(api: Api) -> None:  # AC-DV-2
    status, head, body = get(api, "api/me/sessions")
    assert (status, body["message"]) == (401, "Sign in to see this.")
    assert not (api.app.state / "identity").exists()  # no cookie: the store is not opened


def test_list_shows_only_my_sessions_newest_first(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:  # AC-DV-2
    clock = [1_800_000_000.0]
    monkeypatch.setattr(auth, "CLOCK", lambda: clock[0])
    a1 = sign_in(api, ANN, headers=ua(UA_FIREFOX))
    clock[0] += 5000
    a2 = sign_in(api, ANN, headers=ua(UA_CHROME))
    clock[0] += 100
    b1 = sign_in(api, BOB, headers=ua(UA_SAFARI))
    mine = listing(api, a1)
    assert [d["device"] for d in mine] == ["Chrome on Windows", "Firefox on Android"]
    assert [d["current"] for d in mine] == [False, True]
    assert listing(api, a2)[0]["current"] is True
    theirs = listing(api, b1)
    assert [d["device"] for d in theirs] == ["Safari on iPhone"] and theirs[0]["current"] is True
    assert not {d["id"] for d in mine} & {d["id"] for d in theirs}  # negative: no session of the other account
    assert set(mine[0]) == {"id", "device", "signed_in", "last_active", "current"}
    assert all(devices.ID_RE.match(d["id"]) for d in mine + theirs)


def test_times_are_rounded_to_the_hour(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:  # AC-DV-2
    monkeypatch.setattr(auth, "CLOCK", lambda: 1_800_000_000.0 + 1234)
    sid = sign_in(api, ANN)
    row = listing(api, sid)[0]
    assert row["signed_in"].endswith(":00:00Z") and row["last_active"].endswith(":00:00Z")


def test_list_leaves_out_expired_sessions(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:  # AC-DV-2, AC-DV-9
    clock = [1_800_000_000.0]
    monkeypatch.setattr(auth, "CLOCK", lambda: clock[0])
    old = sign_in(api, ANN)
    clock[0] += identity.SESSION_IDLE_S - 100
    fresh = sign_in(api, ANN)
    clock[0] += 200  # the first session is now idle for 14 days
    assert [d["current"] for d in listing(api, fresh)] == [True]
    assert get(api, "api/me/sessions", cookie=old)[0] == 401


def test_the_list_never_carries_a_session_id_or_its_hash(api: Api) -> None:  # AC-DV-2, AC-DV-8
    sid = sign_in(api, ANN)
    text = json.dumps(listing(api, sid))
    assert sid not in text and identity._sha(sid) not in text and "@" not in text


def test_nothing_raw_is_stored(api: Api) -> None:  # AC-DV-1
    sign_in(api, ANN, headers={"User-Agent": UA_FIREFOX, "X-Forwarded-For": "203.0.113.9"})
    db = sqlite3.connect(str(identity.db_path(api.app.state)))
    dump = "\n".join(db.iterdump())
    db.close()
    assert "Gecko" not in dump and "Mozilla" not in dump and "203.0.113.9" not in dump and "Firefox on Android" in dump


# ----- end one ------------------------------------------------------------------------------------------------
def test_end_one_ends_that_session_on_its_next_request(api: Api) -> None:  # AC-DV-3, AC-DV-4
    a, b = sign_in(api, ANN, headers=ua(UA_FIREFOX)), sign_in(api, ANN, headers=ua(UA_CHROME))
    target = next(d for d in listing(api, a) if not d["current"])
    status, head, body = post(api, end_url(target["id"]), cookie=a)
    assert (status, body) == (200, {"ended": True, "current": False}) and "set-cookie" not in head
    assert get(api, "api/me/sessions", cookie=b)[0] == 401  # negative: the ended session is signed out at once
    assert get(api, "api/auth/me", cookie=b)[2]["signed_in"] is False
    assert [d["current"] for d in listing(api, a)] == [True]
    assert post(api, end_url(target["id"]), cookie=a)[0] == 404  # already gone


def test_ending_my_own_session_clears_the_cookie(api: Api) -> None:  # AC-DV-3
    a = sign_in(api, ANN)
    mine = listing(api, a)[0]["id"]
    status, head, body = post(api, end_url(mine), cookie=a)
    assert (status, body) == (200, {"ended": True, "current": True}) and "Max-Age=0" in head["set-cookie"]
    assert get(api, "api/me/sessions", cookie=a)[0] == 401


def test_another_accounts_session_answers_404_not_403(api: Api) -> None:  # AC-DV-3
    a, b = sign_in(api, ANN), sign_in(api, BOB)
    theirs = listing(api, b)[0]["id"]
    status, _, body = post(api, end_url(theirs), cookie=a)
    assert status == 404 and body["message"] == "That device is not signed in any more."
    assert listing(api, b)[0]["id"] == theirs  # negative: untouched
    for bad in ("zzzzzzzzzzzz", "abc", "0" * 12, "A" * 12):
        assert post(api, end_url(bad), cookie=a)[0] == 404, bad


def test_end_requires_sign_in_and_the_origin_check(api: Api) -> None:  # AC-DV-3
    a = sign_in(api, ANN)
    mine = listing(api, a)[0]["id"]
    assert post(api, end_url(mine))[0] == 401
    assert post(api, end_url(mine), cookie=a, guard=False)[0] == 403
    assert post(api, "api/me/sessions/end-others", cookie=a, guard=False)[0] == 403
    assert post(api, "api/me/sessions/end-others")[0] == 401
    assert get(api, end_url(mine), cookie=a)[0] == 404  # a GET is not an end
    assert listing(api, a)[0]["id"] == mine


# ----- end others ------------------------------------------------------------------------------------------------
def test_end_others_keeps_only_this_session(api: Api) -> None:  # AC-DV-4
    a, b, c = (sign_in(api, ANN) for _ in range(3))
    other = sign_in(api, BOB)
    status, _, body = post(api, "api/me/sessions/end-others", cookie=b)
    assert (status, body) == (200, {"ended": 2})
    assert [d["current"] for d in listing(api, b)] == [True]
    assert get(api, "api/me/sessions", cookie=a)[0] == 401 and get(api, "api/me/sessions", cookie=c)[0] == 401  # no cache
    assert len(listing(api, other)) == 1  # negative: the other account keeps its session
    assert post(api, "api/me/sessions/end-others", cookie=b)[2] == {"ended": 0}


# ----- delete, prune, expiry -------------------------------------------------------------------------------------------
def test_delete_my_data_removes_the_session_rows(api: Api) -> None:  # AC-DV-5
    a, b, other = sign_in(api, ANN), sign_in(api, ANN), sign_in(api, BOB)
    assert post(api, "api/me/delete", {"confirm": "delete"}, cookie=a)[0] == 200
    db = sqlite3.connect(str(identity.db_path(api.app.state)))
    left = db.execute("SELECT u.email FROM sessions s JOIN users u USING (user_id)").fetchall()
    ids = db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    db.close()
    assert left == [(BOB,)] and ids == 1
    assert get(api, "api/me/sessions", cookie=b)[0] == 401 and len(listing(api, other)) == 1


def test_prune_and_expiry_rules_are_unchanged(tmp_path: Path) -> None:  # AC-DV-5
    now = [1_800_000_000.0]
    store = IdentityStore(tmp_path, PEPPER, clock=lambda: now[0])
    uid = store._user_for("c@example.com", now[0])
    sid = store.new_session(uid, "Firefox on Android")
    assert store.session_user(sid) == uid
    now[0] += identity.SESSION_IDLE_S + 1
    assert store.session_user(sid) is None  # 14 days idle
    sid = store.new_session(uid)
    for _ in range(31):  # kept active, still gone after 30 days absolute
        now[0] += 86400
        store.session_user(sid)
    assert store.session_user(sid) is None
    store.new_session(uid)
    now[0] += identity.ACCOUNT_IDLE_S + 1
    store.prune(tmp_path)  # 180 days idle: the account goes whole
    assert store._q("SELECT COUNT(*) AS n FROM sessions")[0]["n"] == 0 and store.user(uid) is None


def test_public_ids_are_unique_random_and_not_the_hash(tmp_path: Path) -> None:  # AC-DV-1
    store = IdentityStore(tmp_path, PEPPER)
    uid = store._user_for("d@example.com", store.clock())
    sids = [store.new_session(uid) for _ in range(50)]
    got = [r["public_id"] for r in store._q("SELECT public_id FROM sessions")]
    assert len(set(got)) == 50 and not any(identity._sha(s).startswith(g) or g in s for s in sids for g in got)
    with pytest.raises(sqlite3.IntegrityError):
        store._db.execute("UPDATE sessions SET public_id = ?", (got[0],))  # the unique index holds


# ----- logs and anonymous flows -------------------------------------------------------------------------------------------
def test_logs_carry_the_public_id_only(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:  # AC-DV-8
    lines: list[str] = []
    monkeypatch.setattr(applog, "log", lambda msg, *a, **k: lines.append(str(msg)))
    a, b = sign_in(api, ANN, headers=ua(UA_FIREFOX)), sign_in(api, ANN, headers=ua(UA_CHROME))
    target = next(d for d in listing(api, a) if not d["current"])
    post(api, end_url(target["id"]), cookie=a)
    post(api, "api/me/sessions/end-others", cookie=a)
    text = "\n".join(lines)
    assert f"device ended {target['id']}" in text and "other devices ended" in text
    assert a not in text and b not in text and identity._sha(a) not in text and "Mozilla" not in text and ANN not in text


def test_sign_in_off_leaves_no_trace_and_anonymous_flows_are_unchanged(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:  # AC-DV-6
    monkeypatch.setenv("SIMON7_MAIL_TRANSPORT", "off")
    assert get(api, "api/me/sessions")[0] == 404 and post(api, "api/me/sessions/end-others")[0] == 404
    assert post(api, end_url("0" * 12))[0] == 404
    for path in ("api/health", "api/version", "api/config", "catalog/video.mp4"):
        status, head, _ = api.request("GET", path)
        assert status == 200 and "set-cookie" not in head, path
    assert not (api.app.state / "identity").exists()
