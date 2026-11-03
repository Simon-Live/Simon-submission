"""Download my data (docs/specs/export-data.md AC-ED-1 to AC-ED-10; TICKET-236). Seeded accounts, no model call."""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from typing import Any

import pytest

from auth_support import authenv, get, post, sign_in  # noqa: F401
from export_seed import ENTRY, seed_report, seed_takes
from part7 import auth, export_data, export_data_routes, history_store, profile
from part7.identity import IdentityStore
from support import Api

ADA, GRACE = "Ada.Lovelace@Example.com", "grace@example.com"


def fetch(api: Api, sid: str | None = None) -> tuple[int, dict[str, str], Any]:
    return get(api, "api/me/export", sid)


def two_accounts(api: Api, ada_takes: int = 3, private: set[int] | None = None) -> dict[str, Any]:
    ada, grace = sign_in(api, ADA), sign_in(api, GRACE)
    store, state = auth.identity(api.app), api.app.state
    uid_a, uid_g = store.session_user(ada), store.session_user(grace)
    a_jobs = seed_takes(state, store, uid_a, "ada", ada_takes, private)
    g_jobs = seed_takes(state, store, uid_g, "grace", 2, entry="side-lunge-0a1b2c3d")
    seed_report(state, uid_a, ENTRY, a_jobs)
    profile.update(store, uid_a, {"public_name": "Ada L", "modes": ["dance"]})
    profile.update(store, uid_g, {"public_name": "Grace Secret"})
    return {"ada": ada, "grace": grace, "uid_a": uid_a, "uid_g": uid_g, "a_jobs": a_jobs, "g_jobs": g_jobs}


@pytest.mark.usefixtures("authenv")
def test_signed_out_is_401_with_the_sign_in_text(api: Api) -> None:  # AC-ED-1
    status, head, body = fetch(api)
    assert status == 401 and body["message"] == "Sign in to see this."
    assert "content-disposition" not in head and "set-cookie" not in head


@pytest.mark.usefixtures("authenv")
def test_owner_gets_one_attachment_with_every_section(api: Api) -> None:  # AC-ED-1, 2
    w = two_accounts(api)
    status, head, doc = fetch(api, w["ada"])
    assert status == 200
    assert head["content-disposition"].startswith('attachment; filename="simon-my-data-') and head["content-disposition"].endswith('.json"')
    assert head["cache-control"] == "no-store" and head["content-type"].startswith("application/json")
    assert doc["format"] == "simon.export.v1"
    for section in ("account", "profile", "sessions", "takes", "entries", "history", "shares", "notes"):
        assert section in doc, section
    assert doc["account"]["email"] == ADA.lower()
    assert set(doc["account"]["consent"]) == {"retention", "video"}
    assert doc["profile"]["public_name"] == "Ada L" and doc["profile"]["modes"] == ["dance"]
    assert {t["job_id"] for t in doc["takes"]} == set(w["a_jobs"])
    assert doc["takes"][0]["kind"] == "follow" and doc["takes"][0]["grade"] == "A" and doc["takes"][0]["private"] is False
    assert [e["entry_id"] for e in doc["entries"]] == [ENTRY]
    assert doc["shares"] == doc["notes"] == []
    movement = doc["history"][0]
    assert len(movement["takes"]) == 3 and movement["reports"][0]["summary"]["text"] == "Seeded summary."
    kept = movement["takes"][0]
    assert kept["meta"]["job_id"] == kept["job_id"] and kept["analysis"]["score"] and kept["clip"]["duration_s"] == 4.5
    assert "not in this file" in kept["clip"]["note"]


@pytest.mark.usefixtures("authenv")
def test_empty_account_still_has_every_section(api: Api) -> None:  # AC-ED-2
    sid = sign_in(api, ADA)
    status, _, doc = fetch(api, sid)
    assert status == 200
    assert doc["takes"] == doc["entries"] == doc["history"] == doc["shares"] == doc["notes"] == []
    assert doc["profile"]["public_name"] is None and doc["account"]["consent"]["retention"]["opted_in"] is False


@pytest.mark.usefixtures("authenv")
def test_nothing_of_another_account_or_a_secret(api: Api) -> None:  # AC-ED-3 negative assertions
    w = two_accounts(api)
    raw = api.request("GET", "api/me/export", None, {"Cookie": f"{auth.COOKIE}={w['ada']}"})[2].decode()
    for other in (w["uid_g"], GRACE, "Grace Secret", "side-lunge", *w["g_jobs"]):
        assert other not in raw, other
    pepper = auth._pepper(api.app.state).hex()
    for secret in (w["ada"], pepper, "sid_hash", "token_hash", "seeded clip bytes", w["uid_a"]):
        assert secret not in raw, secret


@pytest.mark.usefixtures("authenv")
def test_private_take_is_listed_by_date_only(api: Api) -> None:  # AC-ED-3
    w = two_accounts(api, 3, private={1})
    _, _, doc = fetch(api, w["ada"])
    private = next(t for t in doc["history"][0]["takes"] if t["private"])
    assert set(private) == {"job_id", "date", "private", "note"} and private["job_id"] == w["a_jobs"][1]
    assert next(t for t in doc["takes"] if t["job_id"] == w["a_jobs"][1])["private"] is True
    assert sum(1 for t in doc["history"][0]["takes"] if "analysis" in t) == 2


@pytest.mark.usefixtures("authenv")
def test_a_deleted_take_is_absent(api: Api) -> None:  # AC-ED-5
    w = two_accounts(api)
    gone = w["a_jobs"][0]
    assert gone in json.dumps(fetch(api, w["ada"])[2])
    history_store.drop_take(api.app.state, gone)
    auth.identity(api.app).forget_job(gone)
    after = fetch(api, w["ada"])[2]
    assert gone not in json.dumps(after)
    assert w["a_jobs"][1] in json.dumps(after)
    assert after["history"][0]["reports"] == []  # the report citing it went with it


@pytest.mark.usefixtures("authenv")
def test_after_account_delete_the_old_session_gets_401(api: Api) -> None:
    w = two_accounts(api)
    assert fetch(api, w["ada"])[0] == 200
    assert post(api, "api/me/delete", {"confirm": "delete"}, cookie=w["ada"])[0] == 200
    assert fetch(api, w["ada"])[0] == 401


@pytest.mark.usefixtures("authenv")
def test_sixth_export_in_an_hour_is_429_and_a_later_one_works(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:  # AC-ED-6
    w = two_accounts(api)
    clock = [auth.CLOCK()]
    monkeypatch.setattr(auth, "CLOCK", lambda: clock[0])
    assert [fetch(api, w["ada"])[0] for _ in range(5)] == [200] * 5
    status, _, body = fetch(api, w["ada"])
    assert status == 429 and body["message"] == export_data_routes.MSG_RATE
    assert fetch(api, w["grace"])[0] == 200  # the limit is per person
    clock[0] += 3601
    assert fetch(api, w["ada"])[0] == 200


@pytest.mark.usefixtures("authenv")
def test_export_writes_no_file(api: Api) -> None:  # AC-ED-6 no ledger line, never on disk
    w = two_accounts(api)
    state = api.app.state

    def listing() -> list[str]:
        return sorted(str(p.relative_to(state)) for p in state.rglob("*") if p.is_file() and not p.name.startswith("identity.db"))

    before = listing()
    assert fetch(api, w["ada"])[0] == 200
    assert listing() == before


@pytest.mark.usefixtures("authenv")
def test_sign_in_off_leaves_no_trace(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIMON7_MAIL_TRANSPORT", "off")
    assert fetch(api)[0] == 404


@pytest.mark.usefixtures("authenv")
def test_a_leak_or_a_fault_ends_in_no_file(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:  # AC-ED-3 guard
    w = two_accounts(api)
    monkeypatch.setitem(export_data.EXPORTERS, "oops", lambda ctx: {"owner": w["uid_g"]})
    status, head, body = fetch(api, w["ada"])
    assert status == 500 and body["message"] == export_data_routes.MSG_FAILED and "content-disposition" not in head
    monkeypatch.setitem(export_data.EXPORTERS, "oops", lambda ctx: {"mail": GRACE})
    assert fetch(api, w["ada"])[0] == 500
    monkeypatch.setitem(export_data.EXPORTERS, "oops", lambda ctx: 1 / 0)
    assert fetch(api, w["ada"])[0] == 500


@pytest.mark.usefixtures("authenv")
def test_registry_takes_a_new_store_with_one_line_and_scrubs_secrets(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    w = two_accounts(api)
    monkeypatch.setitem(export_data.EXPORTERS, "shares", lambda ctx: [{"kind": "take_result", "token": "abc", "token_hash": "def", "state": "live"}])
    assert fetch(api, w["ada"])[2]["shares"] == [{"kind": "take_result", "state": "live"}]


def test_every_identity_table_is_exported_or_left_out_on_purpose(tmp_path: Path) -> None:  # the "known stores" test
    IdentityStore(tmp_path, b"p" * 32)
    names = [r[0] for r in sqlite3.connect(str(tmp_path / "identity" / "identity.db")).execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    unknown = [n for n in names if n not in export_data.COVERED_TABLES]
    assert not unknown, f"a new per-user table must join the export (export_data.register) or be listed as left out: {unknown}"
    for section in {s for s in export_data.COVERED_TABLES.values() if s}:
        assert section in export_data.EXPORTERS


@pytest.mark.usefixtures("authenv")
def test_long_seed_size_is_recorded_and_small(api: Api, capsys: pytest.CaptureFixture[str]) -> None:  # AC-ED-4
    sid = sign_in(api, ADA)
    store = auth.identity(api.app)
    uid = store.session_user(sid)
    jobs = seed_takes(api.app.state, store, uid, "long", 300)
    seed_report(api.app.state, uid, ENTRY, jobs)
    raw = api.request("GET", "api/me/export", None, {"Cookie": f"{auth.COOKIE}={sid}"})[2]
    with capsys.disabled():
        print(f"\nexport size with 300 seeded takes: {len(raw)} bytes")
    doc = json.loads(raw)
    assert len(doc["takes"]) == 300 and len(doc["history"][0]["takes"]) == 300
    assert len(raw) < export_data.MAX_BYTES // 4


def test_too_large_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = IdentityStore(tmp_path, b"p" * 32)
    uid = store._user_for("ada@example.com", store.clock())
    monkeypatch.setattr(export_data, "MAX_BYTES", 200)
    with pytest.raises(export_data.ExportError):
        export_data.build(export_data.Ctx(tmp_path, store, uid))
