"""The identity store (docs/specs/identity.md AC-ID-1 to AC-ID-10; TICKET-171)."""

from __future__ import annotations

import hashlib
import hmac
import os
from pathlib import Path
import re
import sqlite3
import stat
import threading

import pytest

from part7 import history_store, identity
from part7.identity import IdentityStore, normalise_email

PEPPER = b"p" * 32
EMAIL = "ada@example.com"


class Clock:
    def __init__(self) -> None:
        self.now = 1_800_000_000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture()
def clock() -> Clock:
    return Clock()


@pytest.fixture()
def store(tmp_path: Path, clock: Clock) -> IdentityStore:
    return IdentityStore(tmp_path, PEPPER, clock)


def sign_up(store: IdentityStore, email: str = EMAIL) -> str:
    token, _ = store.start_challenge(email, "ip")  # type: ignore[misc]
    user = store.consume_token(token)
    assert user
    return user


def test_schema_and_modes(tmp_path: Path, store: IdentityStore) -> None:  # AC-ID-1
    db = tmp_path / "identity" / "identity.db"
    assert stat.S_IMODE(os.stat(db.parent).st_mode) == 0o700 and stat.S_IMODE(os.stat(db).st_mode) == 0o600
    con = sqlite3.connect(db)
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"users", "challenges", "sessions", "takes", "entries"} <= tables
    assert con.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    cols = {r[1] for r in con.execute("PRAGMA table_info(challenges)")}
    assert {"id", "email", "token_hash", "code_mac", "created_at", "expires_at", "attempts", "used_at", "ip_key"} <= cols
    cols = {r[1] for r in con.execute("PRAGMA table_info(users)")}
    assert {"user_id", "email", "created_at", "last_seen_at", "consent_version", "consent_at", "retention_opt_in"} <= cols
    con.close()


def test_user_id_is_random_stable_and_not_from_the_email(store: IdentityStore) -> None:  # AC-ID-2
    first = sign_up(store)
    assert re.fullmatch(r"u-[0-9a-f]{24}", first)
    assert "ada" not in first and hashlib.sha256(EMAIL.encode()).hexdigest()[:24] not in first
    assert sign_up(store) == first  # same address, same account
    assert sign_up(store, "grace@example.com") != first


def test_only_hashes_are_stored(tmp_path: Path, store: IdentityStore) -> None:  # AC-ID-3
    token, code = store.start_challenge(EMAIL, "ip")  # type: ignore[misc]
    user = store.consume_token(token)
    sid = store.new_session(user)  # type: ignore[arg-type]
    con = sqlite3.connect(tmp_path / "identity" / "identity.db")
    values = [str(v) for table in ("challenges", "sessions", "users", "takes") for row in con.execute(f"SELECT * FROM {table}") for v in row]
    assert code not in values and token not in "".join(values) and sid not in "".join(values)
    row = con.execute("SELECT id, token_hash, code_mac FROM challenges").fetchone()
    assert row[1] == hashlib.sha256(token.encode()).hexdigest()
    assert row[2] == hmac.new(PEPPER, f"{row[0]}:{code}".encode(), hashlib.sha256).hexdigest()
    assert con.execute("SELECT sid_hash FROM sessions").fetchone()[0] == hashlib.sha256(sid.encode()).hexdigest()
    con.close()
    raw = b"".join(p.read_bytes() for p in (tmp_path / "identity").iterdir())
    assert token.encode() not in raw and sid.encode() not in raw


@pytest.mark.parametrize("raw,want", [
    ("  Ada@Example.COM ", "ada@example.com"),
    ("ada+tag@gmail.com", "ada+tag@gmail.com"),  # no provider aliasing
    ("a.d.a@gmail.com", "a.d.a@gmail.com"),
    ("ｕｓｅｒ@example.com", "user@example.com"),  # NFKC
    ("me@bücher.example", "me@xn--bcher-kva.example"),
    ("a@b", None), ("a@@b.com", None), ("nobody", None), ("@b.com", None), ("a b@c.com", None),
    ("a@.com", None), ("a@b..com", None), (None, None), (42, None),
    ("x" * 65 + "@example.com", None), ("x" * 64 + "@example.com", "x" * 64 + "@example.com"),
    ("a@" + "d" * 63 + "." + "d" * 63 + "." + "d" * 63 + "." + "d" * 63 + ".com", None),  # over 254
])
def test_normalise(raw: object, want: str | None) -> None:  # AC-ID-4
    assert normalise_email(raw) == want


def test_one_challenge_token_kills_code_and_reverse(store: IdentityStore, clock: Clock) -> None:  # AC-ID-5
    token, code = store.start_challenge(EMAIL, "ip")  # type: ignore[misc]
    assert store.consume_token(token)
    assert store.consume_code(EMAIL, code) is None and store.consume_token(token) is None
    token, code = store.start_challenge(EMAIL, "ip")  # type: ignore[misc]
    assert store.consume_code(EMAIL, code)
    assert store.consume_token(token) is None and store.consume_code(EMAIL, code) is None


def test_one_challenge_expires_after_15_minutes(store: IdentityStore, clock: Clock) -> None:  # AC-ID-5
    token, code = store.start_challenge(EMAIL, "ip")  # type: ignore[misc]
    clock.now += 15 * 60
    assert store.consume_token(token) is None and store.consume_code(EMAIL, code) is None
    token, code = store.start_challenge(EMAIL, "ip")  # type: ignore[misc]
    clock.now += 15 * 60 - 1
    assert store.consume_code(EMAIL, code)


def test_one_challenge_new_start_supersedes_the_old(store: IdentityStore) -> None:  # AC-ID-5
    old_token, old_code = store.start_challenge(EMAIL, "ip")  # type: ignore[misc]
    new_token, new_code = store.start_challenge(EMAIL, "ip")  # type: ignore[misc]
    assert store.consume_token(old_token) is None and store.consume_code(EMAIL, old_code) is None
    assert store.consume_code(EMAIL, new_code) and store.consume_token(new_token) is None


def test_code_input_shapes(store: IdentityStore) -> None:  # AC-ID-5
    _, code = store.start_challenge(EMAIL, "ip")  # type: ignore[misc]
    assert store.consume_code(EMAIL, "12345") is None and store.consume_code(EMAIL, "abcdef") is None
    assert store.consume_code("not an address", code) is None and store.consume_code(EMAIL, None) is None  # type: ignore[arg-type]
    assert store.consume_code("ADA@example.com", f"{code[:3]} {code[3:]}")  # a pasted "123 456"


def test_limits_five_wrong_codes_kill_the_challenge(store: IdentityStore) -> None:  # AC-ID-6
    _, code = store.start_challenge(EMAIL, "ip")  # type: ignore[misc]
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(5):
        assert store.consume_code(EMAIL, wrong) is None
    assert store.consume_code(EMAIL, code) is None  # dead, even with the right code


def test_limits_ten_failed_codes_an_hour_per_address(store: IdentityStore, clock: Clock) -> None:  # AC-ID-6
    for _ in range(2):
        _, code = store.start_challenge(EMAIL, "ip")  # type: ignore[misc]
        wrong = "000000" if code != "000000" else "111111"
        for _ in range(5):
            store.consume_code(EMAIL, wrong)
    _, code = store.start_challenge(EMAIL, "ip")  # type: ignore[misc]
    assert store.consume_code(EMAIL, code) is None  # 10 failures this hour: even the right code waits
    clock.now += 3601
    _, code = store.start_challenge(EMAIL, "ip")  # type: ignore[misc]
    assert store.consume_code(EMAIL, code)


def test_limits_per_address_hour_day_and_global(store: IdentityStore, clock: Clock, monkeypatch: pytest.MonkeyPatch) -> None:  # AC-ID-6
    assert all(store.start_challenge(EMAIL, "ip") for _ in range(5))
    assert store.start_challenge(EMAIL, "ip") is None  # the 6th in an hour
    assert store.start_challenge("grace@example.com", "ip")  # another address is not limited
    for _ in range(3):  # 4 hours on: 5 more an hour, up to the day's 20
        clock.now += 3601
        for _ in range(5):
            assert store.start_challenge(EMAIL, "ip")
    clock.now += 3601
    assert store.start_challenge(EMAIL, "ip") is None  # 20 in the last day
    clock.now += 86400
    assert store.start_challenge(EMAIL, "ip")
    monkeypatch.setattr(identity, "GLOBAL_MAILS_PER_HOUR", 3)
    assert store.start_challenge("a1@example.com", "ip") and store.start_challenge("a2@example.com", "ip")
    assert store.start_challenge("a3@example.com", "ip") is None  # the global cap, same silent answer


def test_limits_malformed_address_is_none(store: IdentityStore) -> None:
    assert store.start_challenge("nope", "ip") is None


def test_comparisons_use_compare_digest(store: IdentityStore, monkeypatch: pytest.MonkeyPatch) -> None:  # constant time
    calls: list[tuple[str, str]] = []
    real = hmac.compare_digest

    def spy(a: str, b: str) -> bool:
        calls.append((a, b))
        return real(a, b)

    monkeypatch.setattr(identity.hmac, "compare_digest", spy)
    _, code = store.start_challenge(EMAIL, "ip")  # type: ignore[misc]
    store.consume_code(EMAIL, "000000" if code != "000000" else "111111")
    assert len(calls) == 1
    store.consume_code("nobody-here@example.com", code)  # no challenge: the same work is done
    assert len(calls) == 2


def test_claim_race_first_owner_wins_across_threads(store: IdentityStore) -> None:  # AC-ID-7
    users = [sign_up(store, f"u{n}@example.com") for n in range(12)]
    results: list[bool] = []
    barrier = threading.Barrier(len(users))

    def go(user: str) -> None:
        barrier.wait()
        results.append(store.attach("aaaaaaaaaaaa", user, "follow", "lateral-raise", None, "claim"))

    threads = [threading.Thread(target=go, args=(u,)) for u in users]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert results.count(True) == 1 and results.count(False) == len(users) - 1
    owner = store.owner_of("aaaaaaaaaaaa")
    assert owner in users and store.attach("aaaaaaaaaaaa", owner, "follow", None, None, "claim")  # a repeat by the owner is True


def test_attach_rejects_unknown_kind(store: IdentityStore) -> None:
    with pytest.raises(ValueError):
        store.attach("aaaaaaaaaaaa", "u-" + "0" * 24, "people", None, None, "submit")


def test_takes_entries_and_only_me(store: IdentityStore, clock: Clock) -> None:
    ada, grace = sign_up(store), sign_up(store, "grace@example.com")
    store.attach("aaaaaaaaaaaa", ada, "follow", "lateral-raise", None, "submit")
    clock.now += 10
    store.attach("bbbbbbbbbbbb", ada, "trainer", "lateral-raise", None, "claim")
    with pytest.raises(ValueError):
        store.attach("eeeeeeeeeeee", ada, "group", "lateral-raise", "cccccccccccc", "claim")  # a group take is not owned
    assert [t["job_id"] for t in store.takes_of(ada)] == ["bbbbbbbbbbbb", "aaaaaaaaaaaa"]  # newest first
    assert store.takes_of(grace) == []
    store.attach_entry("lateral-raise", ada, "")
    store.attach_entry("lateral-raise", grace, "dddddddddddd")  # first owner wins
    store.attach_entry("lateral-raise", ada, "dddddddddddd")  # the owner fills in the trainer job
    assert store.entry_owner("lateral-raise") == (ada, False) and store.entry_owner("nope") is None
    assert store.entries_of(ada)[0]["trainer_job"] == "dddddddddddd" and store.entries_of(grace) == []
    assert store.set_only_me("lateral-raise", grace, True) is False and store.entry_owner("lateral-raise") == (ada, False)
    assert store.set_only_me("lateral-raise", ada, True) and store.entry_owner("lateral-raise") == (ada, True)


def test_delete_user_removes_everything_of_the_user(store: IdentityStore) -> None:  # AC-ID-8
    ada, grace = sign_up(store), sign_up(store, "grace@example.com")
    sid, gsid = store.new_session(ada), store.new_session(grace)
    store.attach("aaaaaaaaaaaa", ada, "follow", None, None, "submit")
    store.attach("bbbbbbbbbbbb", grace, "follow", None, None, "submit")
    store.attach_entry("lateral-raise", ada, "dddddddddddd")
    store.start_challenge(EMAIL, "ip")  # an open challenge
    store.delete_user(ada)
    assert store.user(ada) is None and store.session_user(sid) is None
    assert store.takes_of(ada) == [] and store.entries_of(ada) == [] and store.owner_of("aaaaaaaaaaaa") is None
    assert store.consume_code(EMAIL, "123456") is None
    assert store.session_user(gsid) == grace and store.owner_of("bbbbbbbbbbbb") == grace  # others untouched


def test_prune_sessions_and_idle_accounts(store: IdentityStore, clock: Clock) -> None:  # AC-ID-9
    ada, grace = sign_up(store), sign_up(store, "grace@example.com")
    old, kept = store.new_session(ada), store.new_session(grace)
    day = 86400
    clock.now += 13 * day
    assert store.session_user(kept) == grace  # used on day 13: idle clock restarts
    clock.now += 2 * day  # day 15: `old` idle 15 days, `kept` idle 2
    store.prune()
    assert store.session_user(old) is None and store.session_user(kept) == grace
    clock.now += 16 * day  # day 31: `kept` is past the absolute 30 days even though recently used
    store.prune()
    assert store.session_user(kept) is None
    clock.now += 170 * day  # more than 180 days since either signed in (grace last on day 13)
    store.prune()
    assert store.user(ada) is None and store.user(grace) is None


def test_session_idle_and_absolute_expiry(store: IdentityStore, clock: Clock) -> None:
    user = sign_up(store)
    sid = store.new_session(user)
    clock.now += 14 * 86400 - 1
    assert store.session_user(sid) == user
    clock.now += 14 * 86400 - 1
    assert store.session_user(sid) == user  # 28 days: still inside both
    clock.now += 3 * 86400
    assert store.session_user(sid) is None  # past 30 days
    assert store.session_user("") is None and store.session_user("x" * 300) is None


def test_end_session_makes_a_copied_sid_fail(store: IdentityStore) -> None:
    user = sign_up(store)
    sid = store.new_session(user)
    copy = str(sid)
    store.end_session(sid)
    assert store.session_user(copy) is None
    store.end_session("never-existed")  # no error


def test_consent_is_stored_and_withdrawn(store: IdentityStore, clock: Clock) -> None:
    ada = sign_up(store)
    store.set_consent(ada, "v1", True)
    user = store.user(ada)
    assert user and user["retention"] == {"opted_in": True, "days": 90, "consent_version": "v1"}
    store.set_consent(ada, "v1", False)
    assert store.user(ada)["retention"]["opted_in"] is False


def test_forget_job_drops_ownership_and_its_entry(store: IdentityStore) -> None:
    ada = sign_up(store)
    store.attach("aaaaaaaaaaaa", ada, "trainer", None, None, "claim")
    store.attach_entry("lateral-raise", ada, "aaaaaaaaaaaa")
    store.forget_job("aaaaaaaaaaaa")
    assert store.owner_of("aaaaaaaaaaaa") is None and store.entry_owner("lateral-raise") is None


def test_readers_need_no_pepper_and_never_create_the_file(tmp_path: Path, clock: Clock) -> None:  # AC-ID-10
    assert identity.owner_of_job(tmp_path, "aaaaaaaaaaaa") is None and identity.retention_opt_in(tmp_path, "u-" + "0" * 24) is False
    assert not (tmp_path / "identity").exists()
    store = IdentityStore(tmp_path, PEPPER, clock)
    ada = sign_up(store)
    store.attach("aaaaaaaaaaaa", ada, "follow", None, None, "submit")
    assert identity.owner_of_job(tmp_path, "aaaaaaaaaaaa") == ada and identity.owner_of_job(tmp_path, "bbbbbbbbbbbb") is None
    assert identity.retention_opt_in(tmp_path, ada) is False
    store.set_consent(ada, "v1", True)
    assert identity.retention_opt_in(tmp_path, ada) is True


def test_email_key_is_short_keyed_and_not_the_address(store: IdentityStore) -> None:
    key = store.email_key(EMAIL)
    assert len(key) == 12 and EMAIL not in key and key == store.email_key(EMAIL)


def test_retention_days_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIMON7_HISTORY_DAYS", "30")
    assert identity.retention_days() == 30 == history_store.days()  # one setting for both
    monkeypatch.setenv("SIMON7_HISTORY_DAYS", "many")
    assert identity.retention_days() == 90 == history_store.days()
