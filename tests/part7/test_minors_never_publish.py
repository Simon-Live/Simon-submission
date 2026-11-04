"""Minors never publish (docs/specs/minors-never-publish.md AC-MN1 to AC-MN13; privacy audit PM-B1 to PM-B3, PM-R1 to
PM-R6, PM-R10, app-surface R5).

Real sessions through the sign-in routes, the real identity store, the real queue and the stub Part 6 catalog. An
account is marked 13 to 17 the way prod marks it (`identity.mark_minor`, called by `auth.attach_job`).
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import time
import types
from typing import Any

import pytest

from auth_support import authenv, get, post, sign_in  # noqa: F401  authenv is a fixture
from part7 import (auth, challenge_routes, consent_record, entry_access, identity, notes, prod_mode, quota, resume,
                   share_routes, teacher_routes, trainer_publish)
from part7.parts import p6_catalog
from support import Api
from test_notes import World
from test_private_default import MOVE, follow, owned_movement, user_of

pytestmark = pytest.mark.usefixtures("authenv")
GRACE = "grace.hopper@example.com"
CONSENT = {"version": consent_record.VERSION, "items": {k: True for k in consent_record.ITEMS}, "at": "2026-11-03T10:00:00Z"}


@pytest.fixture()
def prod(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prod switches (trainer_public off, consent required) for the calls after it; the server already runs."""
    monkeypatch.setenv("FIRM_ENV", "prod")
    for name in prod_mode.PROD_DEFAULTS:
        monkeypatch.delenv(f"SIMON7_POLICY_{name.upper()}", raising=False)


def mark(api: Api, sid: str) -> str:
    uid = user_of(api, sid)
    auth.identity(api.app).mark_minor(uid)
    return uid


def share(api: Api, sid: str, kind: str, ref: str, path: str = "api/shares") -> tuple[int, Any]:
    status, _, body = post(api, path, {"kind": kind, "item_ref": ref, "confirm": True, "days": 7}, cookie=sid)
    return status, body


# ----- AC-MN1 (PM-B1): no share link of any kind -----------------------------------------------------------------
def test_mn1_a_minor_account_makes_no_share_link_of_any_kind(api: Api) -> None:
    sid = sign_in(api)
    job = follow(api, MOVE, owner=user_of(api, sid))
    status, body = share(api, sid, "take_result", job)
    assert status == 201, body  # control: an adult's take is shared
    token = body["token"]
    assert get(api, f"api/shared/{token}")[0] == 200
    mark(api, sid)
    assert get(api, f"api/shared/{token}")[0] == 410, "marking the account ends its live links"
    for kind, ref in (("take_result", job), ("history_report", MOVE), ("progress_sheet", MOVE)):
        for path in ("api/shares", "api/shares/preview"):
            assert share(api, sid, kind, ref, path) == (403, {"ok": False, "error": share_routes.MSG_MINOR,
                                                              "message": share_routes.MSG_MINOR}), (kind, path)
    rows = auth.identity(api.app).fetch("SELECT revoked_utc FROM shares")
    assert len(rows) == 1 and rows[0]["revoked_utc"], "nothing new was stored"


def test_mn1_a_take_with_a_13_to_17_answer_is_never_shared(api: Api) -> None:
    sid = sign_in(api)
    job = follow(api, MOVE, consent={"age_band": "minor"})  # signed out: no account owns it yet
    auth.identity(api.app).attach(job, user_of(api, sid), "follow", MOVE, None, "submit")
    assert share(api, sid, "take_result", job)[0] == 403


# ----- AC-MN2 (PM-B2): no board and no name ----------------------------------------------------------------------
def board(api: Api, sid: str, name: str) -> tuple[int, Any]:
    status, _, body = post(api, "api/challenges", {"entry_id": MOVE, "kind": "friend", "title": "Raise off",
                                                   "creator_name": name}, cookie=sid)
    return status, body


def test_mn2_a_minor_account_cannot_make_a_board(api: Api) -> None:
    adult, teen = sign_in(api), sign_in(api, GRACE)
    assert board(api, adult, "Ada")[0] == 201  # control
    mark(api, teen)
    status, body = board(api, teen, "Grace Hopper")
    assert (status, body["error"]) == (403, challenge_routes.MSG_MINOR_BOARD)
    listed = json.dumps(get(api, "api/challenges")[2])
    assert "Grace Hopper" not in listed and "Ada" in listed


# ----- AC-MN9 (PM-R4): the board entry reads the account mark ------------------------------------------------------
def test_mn9_a_take_of_a_marked_account_stays_off_a_board(api: Api) -> None:
    adult, teen = sign_in(api), sign_in(api, GRACE)
    challenge = board(api, adult, "Ada")[1]["id"]
    job = follow(api, MOVE, owner=user_of(api, teen))  # its job record carries no 13 to 17 answer
    mark(api, teen)
    status, _, body = post(api, f"api/challenges/{challenge}/entries", {"job_id": job, "name": "G"}, cookie=teen)
    assert (status, body["error"]) == (409, challenge_routes.MSG_MINOR)
    other = follow(api, MOVE, owner=user_of(api, adult))
    assert post(api, f"api/challenges/{challenge}/entries", {"job_id": other, "name": "A"}, cookie=adult)[0] == 201


# ----- AC-MN6 (PM-R1): no note request, no teacher share --------------------------------------------------------
def test_mn6_a_minor_follower_cannot_ask_a_trainer_for_a_note(api: Api) -> None:
    world = World(api)
    assert world.view()[1]["can_ask"] is True  # control
    auth.identity(api.app).mark_minor(world.fid)
    assert world.view()[1]["can_ask"] is False
    status, body = world.ask(["score", "clip"])
    assert (status, body["error"]) == (403, notes.MSG_MINOR)
    assert world.rows() == [], "no grant was stored"


def test_mn6_a_minor_cannot_share_a_take_on_the_teacher_page(api: Api) -> None:
    sid = sign_in(api)
    job = follow(api, MOVE, owner=user_of(api, sid))
    url = f"api/teacher/{MOVE}/shares"
    assert post(api, url, {"job_id": job, "shared": True}, cookie=sid)[0] == 200  # control
    mark(api, sid)
    status, _, body = post(api, url, {"job_id": job, "shared": True}, cookie=sid)
    assert (status, body["error"]) == (403, teacher_routes.MSG_MINOR)
    assert post(api, url, {"job_id": job, "shared": False}, cookie=sid)[0] == 200, "unsharing is never refused"


# ----- AC-MN7 (PM-R2): the mark applies backwards ---------------------------------------------------------------
def test_mn7_marking_an_account_unpublishes_its_movements_and_visible_reads_the_mark(api: Api) -> None:
    sid = sign_in(api)
    uid = user_of(api, sid)
    owned_movement(api, sid, "adult-move-1a2b", "adult")
    owned_movement(api, sid, "adult-move-2c3d", "adult")
    assert entry_access.get(api.app.state, "adult-move-1a2b")["published"] is True  # outside prod: public
    assert get(api, "catalog/api/entries/adult-move-1a2b")[0] == 200
    auth.identity(api.app).write("UPDATE users SET age_band = 'minor' WHERE user_id = ?", (uid,))  # the mark alone
    assert get(api, "catalog/api/entries/adult-move-1a2b")[0] == 404, "visible reads the account mark"
    assert entry_access.visible(api.app.state, "adult-move-1a2b", uid, None), "its owner still sees it"
    auth.identity(api.app).write("UPDATE users SET age_band = NULL WHERE user_id = ?", (uid,))  # review R5: the
    auth.identity(api.app).mark_minor(uid)  # rows are made private when mark_minor changes the mark
    assert [entry_access.get(api.app.state, e)["published"] for e in ("adult-move-1a2b", "adult-move-2c3d")] == [False, False]
    assert identity.account_minor(api.app.state, uid) and not identity.account_minor(api.app.state, "u-nobody")


# ----- AC-MN3, AC-MN4, AC-MN8 (PM-B3, PM-R3): the statement and an unknown band ---------------------------------
def test_mn3_opt_in_needs_public_and_the_statement_as_booleans(api: Api) -> None:
    adult = {"consent": CONSENT, "age_band": "adult"}
    assert trainer_publish.opt_in({**adult, "public": True, "nobody_under_18": True}) is True
    for doc in ({**adult, "public": True}, {**adult, "nobody_under_18": True},
                {**adult, "public": True, "nobody_under_18": "true"},
                {"consent": CONSENT, "age_band": "minor", "public": True, "nobody_under_18": True}):
        assert trainer_publish.opt_in(doc) is False, doc
    spec = resume.trainer_spec({**adult, "public": True, "nobody_under_18": True}, "n", "exercise", None)
    assert spec["public"] is True and spec["nobody_under_18"] is True
    assert "public" not in resume.trainer_spec({**adult, "public": True}, "n", "exercise", None)


def _job(state: Path, job_id: str, band: str) -> None:
    folder = Path(state) / "jobs" / job_id
    folder.mkdir(parents=True)
    (folder / "job.json").write_text(json.dumps({"id": job_id, "consent": {"age_band": band}}), encoding="utf-8")


def test_mn3_a_row_publishes_with_the_switch_off_only_with_the_statement(api: Api, prod: None) -> None:
    state = api.app.state
    _job(state, "job-adult-1", "adult")
    link = entry_access.Link(state, "u-1", published=True)  # True with the switch off: opt_in saw the statement
    link.job("job-adult-1")
    link.saved("stated-move-1a2b")
    row = entry_access.get(state, "stated-move-1a2b")
    assert (row["published"], row["nobody_under_18"]) == (True, True)
    entry_access.record(state, "bare-move-1a2b", trainer_job="job-adult-1", published=True, age_band="adult")
    assert entry_access.get(state, "bare-move-1a2b")["published"] is False, "no statement, no publish"
    assert entry_access.release(state, "bare-move-1a2b", "") is False
    _job(state, "job-adult-2", "adult")
    private = entry_access.Link(state, "u-1", published=False)
    private.job("job-adult-2")
    private.saved("plain-move-1a2b")
    assert entry_access.get(state, "plain-move-1a2b")["nobody_under_18"] is False


def test_mn8_an_unknown_band_is_never_published_where_consent_is_required(api: Api, prod: None) -> None:
    state = api.app.state
    entry_access.record(state, "nobody-knows-1a2b", published=True, nobody_under_18=True)
    assert entry_access.get(state, "nobody-knows-1a2b")["published"] is False
    assert entry_access.release(state, "nobody-knows-1a2b", "") is False
    entry_access.record(state, "adult-known-1a2b", published=True, nobody_under_18=True, age_band="adult")
    assert entry_access.get(state, "adult-known-1a2b")["published"] is True  # control


def test_mn4_the_owner_switch_needs_the_statement_once(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    sid = sign_in(api)
    owned_movement(api, sid, "own-move-1a2b", "adult")
    entry_access.set_published(api.app.state, "own-move-1a2b", False)
    monkeypatch.setenv("FIRM_ENV", "prod")  # the switch is read per call: the publish rules of prod from here on
    for name in prod_mode.PROD_DEFAULTS:
        monkeypatch.delenv(f"SIMON7_POLICY_{name.upper()}", raising=False)
    url = "api/me/entries/own-move-1a2b"
    status, _, body = post(api, url, {"published": True}, cookie=sid)
    assert (status, body["error"]) == (403, trainer_publish.MSG_STATEMENT)
    assert entry_access.get(api.app.state, "own-move-1a2b")["published"] is False
    assert post(api, url, {"published": True, "nobody_under_18": True}, cookie=sid)[0] == 200
    assert entry_access.get(api.app.state, "own-move-1a2b")["nobody_under_18"] is True
    assert post(api, url, {"published": False}, cookie=sid)[0] == 200, "making it private is never refused"
    assert post(api, url, {"published": True}, cookie=sid)[0] == 200, "the row keeps the statement"


# ----- AC-MN10 (PM-R5): the account keeps an under 13 answer ------------------------------------------------------
def test_mn10_an_under_13_answer_stays_on_the_account(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    sid = sign_in(api)
    uid = user_of(api, sid)
    h = types.SimpleNamespace(app=api.app)
    monkeypatch.setattr(auth, "current_user", lambda handler: uid if handler is h else None)
    adult = {"consent": {**CONSENT, "account": uid}, "age_band": "adult"}  # the answer is stamped for the account (muse-consent B2)
    assert consent_record.refusal(adult, h) is None  # control
    assert consent_record.refusal({**adult, "age_band": "under13"}, h) == (403, consent_record.MSG_UNDER13)
    assert consent_record.refusal(adult, h) == (403, consent_record.MSG_UNDER13), "a clean browser answers adult"
    store = auth.identity(api.app)
    store.mark_minor(uid)
    assert store.is_under13(uid) and store.is_minor(uid), "a 13 to 17 mark never lowers an under 13 one"
    other = types.SimpleNamespace(app=api.app)
    signed_out = {"consent": CONSENT, "age_band": "adult"}
    assert consent_record.refusal(signed_out, other) is None, "signed out: only the request is read"
    assert consent_record.refusal(adult) is None


def test_mn10_a_store_fault_refuses(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    h = types.SimpleNamespace(app=api.app)
    monkeypatch.setattr(auth, "current_user", lambda handler: "u-1")

    def broken(app: Any) -> Any:
        raise RuntimeError("store down")

    monkeypatch.setattr(auth, "identity", broken)
    assert consent_record.refusal({"consent": CONSENT, "age_band": "adult"}, h) == (503, consent_record.MSG_STORE)
    assert trainer_publish.minor_refused(h, "u-1") is True, "the minor check fails closed too"


def test_mn10_the_job_routes_read_the_kept_under_13_answer(api: Api) -> None:
    """Wiring: `server._consent` passes its handler, so a clean adult answer from a marked account is refused."""
    sid = sign_in(api)
    adult = {"consent": CONSENT, "age_band": "adult"}
    status, _, body = post(api, "api/trainer", adult, cookie=sid)
    assert status != 403, body  # control: the adult answer passes the consent step (the request fails later)
    auth.identity(api.app).mark_under13(user_of(api, sid))
    status, _, body = post(api, "api/trainer", adult, cookie=sid)
    assert (status, body.get("error")) == (403, consent_record.MSG_UNDER13), body


# ----- AC-MN11 (PM-R6): a keyed visitor hash ----------------------------------------------------------------------
def test_mn11_the_visitor_key_is_keyed_by_the_pepper(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in (("a", "11" * 32), ("b", "22" * 32)):
        (tmp_path / name).mkdir()
        (tmp_path / name / "SIMON7_AUTH_PEPPER").write_text(value + "\n", encoding="utf-8")
    keys: dict[str, str | None] = {}
    for name in ("a", "a", "b"):
        monkeypatch.setenv("SIMON7_KEYS_DIR", str(tmp_path / name))
        monkeypatch.setattr(quota, "_VISITOR_KEYS", {})  # a fresh process
        keys.setdefault(name, quota.visitor_key("203.0.113.7"))
        assert keys[name] == quota.visitor_key("203.0.113.7"), "the same key after a restart with the same pepper"
    assert keys["a"] != keys["b"]
    assert keys["a"] != hashlib.sha256(b"203.0.113.7").hexdigest()[:16], "not the plain hash of the address"
    assert quota.visitor_key("2001:db8::1") == quota.visitor_key("2001:db8::2"), "an IPv6 /64 is still one client"


def test_mn11_no_pepper_yet_is_not_cached_and_the_next_call_reads_it(tmp_path: Path,
                                                                     monkeypatch: pytest.MonkeyPatch) -> None:  # R7
    monkeypatch.setenv("SIMON7_KEYS_DIR", str(tmp_path))
    monkeypatch.setattr(quota, "_VISITOR_KEYS", {})
    monkeypatch.setattr(quota, "_made_pepper", lambda _folder: None)  # a folder that cannot be written
    before = quota.visitor_key("203.0.113.7")
    assert quota._VISITOR_KEYS == {}, "the stand-in key is never kept as the folder's key"
    (tmp_path / "SIMON7_AUTH_PEPPER").write_text("33" * 32 + "\n", encoding="utf-8")  # sign-in made the pepper
    after = quota.visitor_key("203.0.113.7")
    assert after != before and list(quota._VISITOR_KEYS) == [str(tmp_path)]
    monkeypatch.setattr(quota, "_VISITOR_KEYS", {})  # a restart with the same pepper: the same key
    assert quota.visitor_key("203.0.113.7") == after


def test_the_first_call_makes_the_pepper_so_a_count_never_changes_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """the team on moalborati/simon#61: the first request counts under the pepper it made; it is 0600 and read back after a restart."""
    monkeypatch.setenv("SIMON7_KEYS_DIR", str(tmp_path))
    monkeypatch.setattr(quota, "_VISITOR_KEYS", {})
    first = quota.visitor_key("203.0.113.7")
    made = tmp_path / "SIMON7_AUTH_PEPPER"
    assert made.is_file() and made.stat().st_mode & 0o777 == 0o600
    monkeypatch.setattr(quota, "_VISITOR_KEYS", {})
    assert quota.visitor_key("203.0.113.7") == first


# ----- review R5: one identity read per owner, the mark applied once ---------------------------------------------
def test_r5_a_listing_reads_the_account_mark_once_per_owner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for n in range(4):
        entry_access.record(tmp_path, f"list-move-{n}a2b", owner="u-1" if n < 3 else "u-2", published=True,
                            age_band="adult")
    reads: list[str] = []
    real = identity.account_minor
    monkeypatch.setattr(identity, "account_minor", lambda state, uid: reads.append(uid) or real(state, uid))
    minors: dict[str, bool] = {}
    assert all(entry_access.visible(tmp_path, f"list-move-{n}a2b", None, None, minors=minors) for n in range(4))
    assert sorted(reads) == ["u-1", "u-2"]
    reads.clear()
    assert entry_access.visible(tmp_path, "list-move-0a2b", None, None) and reads == ["u-1"]  # no cache: one read


def test_r5_the_catalog_listing_passes_one_cache_for_the_request(monkeypatch: pytest.MonkeyPatch) -> None:
    from part7 import proxy

    seen: list[Any] = []
    monkeypatch.setattr(auth, "may_view_entry", lambda h, entry_id, minors=None: seen.append(minors) or True)
    visible = proxy._default_visible(types.SimpleNamespace(app=object()))
    visible("a-move-1a2b")
    visible("b-move-1a2b")
    assert isinstance(seen[0], dict) and seen[0] is seen[1]
    proxy._default_visible(types.SimpleNamespace(app=object()))("c-move-1a2b")
    assert seen[2] is not seen[0], "a new request starts a new cache"


def test_r5_mark_minor_unpublishes_only_when_the_mark_changes(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    sid = sign_in(api)
    uid = user_of(api, sid)
    calls: list[str] = []
    real = entry_access.unpublish_owner
    monkeypatch.setattr(entry_access, "unpublish_owner", lambda state, user: calls.append(user) or real(state, user))
    store = auth.identity(api.app)
    store.mark_minor(uid)
    store.mark_minor(uid)
    store.mark_minor(uid)
    assert calls == [uid] and store.is_minor(uid)
    store.mark_under13(uid)
    store.mark_under13(uid)
    store.mark_minor(uid)
    assert calls == [uid, uid] and store.is_under13(uid), "the under 13 mark changes once, never lowered"


# ----- review R6: reinstate applies the publish rule of `release` ------------------------------------------------
def test_r6_reinstate_puts_back_public_only_by_the_release_rule(api: Api, prod: None) -> None:
    state = api.app.state
    entry_access.record(state, "stated-back-1a2b", published=True, nobody_under_18=True, age_band="adult")
    entry_access.record(state, "bare-back-1a2b", published=False, age_band="adult")
    entry_access.set_published(state, "bare-back-1a2b", True)  # public once, without the statement
    entry_access.record(state, "marked-back-1a2b", owner="u-minor", published=True, nobody_under_18=True,
                        age_band="adult")
    for entry in ("stated-back-1a2b", "bare-back-1a2b", "marked-back-1a2b"):
        assert entry_access.get(state, entry)["published"] is True, entry
        entry_access.evict(state, entry, "a notice")
    entry_access.record(state, "own-minor-1a2b", owner="u-minor", published=False, age_band="minor")  # the owner is a minor
    assert entry_access.reinstate(state, "stated-back-1a2b", "counter notice")["published"] is True  # control
    assert entry_access.reinstate(state, "bare-back-1a2b", "counter notice")["published"] is False, "no statement"
    assert entry_access.reinstate(state, "marked-back-1a2b", "counter notice")["published"] is False, "a minor owner"


# ----- AC-MN12 (PM-R10): catalog folders without a row --------------------------------------------------------------
def _old(folder: Path, now: float, seconds: float = 7200) -> None:
    os.utime(folder, (now - seconds, now - seconds))


def _undone_save(state: Path, entry_id: str) -> None:
    """A reserved row whose save was undone: `Link.reserve`'s undo leaves the mark `orphans` needs."""
    entry_access.Link(state, "", False).reserve(entry_id)()


def test_mn12_orphans_lists_only_old_folders_of_an_undone_save(tmp_path: Path) -> None:
    state, catalog = tmp_path / "state", tmp_path / "catalog"
    now = time.time()
    for name in ("undone-move-1a2b", "kept-move-1a2b", "fixture-move-1a2b", "young-move-1a2b", "bad-row-move-1a2b"):
        (catalog / name).mkdir(parents=True)
    (catalog / "fixture-move-1a2b" / "manifest.json").write_text(json.dumps({"files_source": "fixture"}))
    for name in ("undone-move-1a2b", "fixture-move-1a2b", "young-move-1a2b"):
        _undone_save(state, name)
    entry_access.record(state, "kept-move-1a2b", published=False)
    (state / entry_access.FOLDER / "bad-row-move-1a2b.json").write_text("not json", encoding="utf-8")
    (catalog / "link-move-1a2b").symlink_to(catalog / "undone-move-1a2b")
    _undone_save(state, "link-move-1a2b")
    for name in ("undone-move-1a2b", "kept-move-1a2b", "fixture-move-1a2b", "bad-row-move-1a2b"):
        _old(catalog / name, now)
    assert entry_access.orphans(state, catalog, now, 3600) == ["undone-move-1a2b"]
    assert entry_access.orphans(state, catalog, now, 9000) == []


def test_mn12_a_folder_with_no_row_and_no_undone_save_is_never_an_orphan(tmp_path: Path) -> None:
    """A movement made before the access rows existed lost 116 staging entries on 4 November: no row proves nothing."""
    state, catalog = tmp_path / "state", tmp_path / "catalog"
    now = time.time()
    (catalog / "older-move-1a2b").mkdir(parents=True)
    _old(catalog / "older-move-1a2b", now, 90 * 86400)
    assert entry_access.orphans(state, catalog, now, 3600) == []


def test_mn12_a_new_row_clears_the_undone_mark(tmp_path: Path) -> None:
    state, catalog = tmp_path / "state", tmp_path / "catalog"
    now = time.time()
    (catalog / "again-move-1a2b").mkdir(parents=True)
    _old(catalog / "again-move-1a2b", now)
    _undone_save(state, "again-move-1a2b")
    entry_access.record(state, "again-move-1a2b", published=False)
    entry_access.drop(state, "again-move-1a2b")
    assert entry_access.orphans(state, catalog, now, 3600) == [], "a later save of the id is not the undone one"


def test_mn12_the_retention_sweep_keeps_older_movements_and_removes_an_undone_save(api: Api) -> None:
    """Wiring: `delete_routes.sweep_entries` removes only an undone save past `config.TIMEOUTS["6"]`, then forgets it."""
    from part7 import config, delete_routes

    catalog = Path(api.app.child.catalog_dir)
    now = time.time()
    for name in ("undone-move-1a2b", "young-move-1a2b", "older-move-1a2b"):
        (catalog / name).mkdir(parents=True)
        (catalog / name / "animation.json").write_text("{}", encoding="utf-8")
    for name in ("undone-move-1a2b", "young-move-1a2b"):
        _undone_save(api.app.state, name)
    old = now - config.TIMEOUTS["6"] - 5
    os.utime(catalog / "undone-move-1a2b", (old, old))
    os.utime(catalog / "older-move-1a2b", (now - 90 * 86400, now - 90 * 86400))
    assert delete_routes.sweep_entries(api.app, now=now) == 1
    assert not (catalog / "undone-move-1a2b").exists(), "an undone save past the save window stays on disk"
    assert (catalog / "young-move-1a2b").is_dir(), "a folder still inside the save window went"
    assert (catalog / "older-move-1a2b").is_dir(), "a movement made before the access rows existed went"
    assert not list(Path(api.app.state, entry_access.FOLDER).glob("undone-move-1a2b*")), "the mark outlived the movement"
    (catalog / "undone-move-1a2b").mkdir()
    os.utime(catalog / "undone-move-1a2b", (old, old))
    assert delete_routes.sweep_entries(api.app, now=now) == 0, "the mark was used twice"


def test_mn12_a_mark_with_no_folder_goes_past_the_window(tmp_path: Path) -> None:
    state, catalog = tmp_path / "state", tmp_path / "catalog"
    catalog.mkdir()
    now = time.time()
    _undone_save(state, "never-saved-1a2b")
    assert entry_access.orphans(state, catalog, now, 3600) == []
    assert list((state / entry_access.FOLDER).glob("*.undone")), "young: the late save may still come"
    assert entry_access.orphans(state, catalog, now + 7200, 3600) == []
    assert not list((state / entry_access.FOLDER).glob("*.undone"))


# ----- AC-MN13 (app-surface R5): ids and rows of another movement --------------------------------------------------
def test_mn13_new_id_skips_an_id_whose_row_exists(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state, catalog = tmp_path / "state", tmp_path / "catalog"
    catalog.mkdir()
    entry_access.record(state, "squat-aaaa1111", trainer_job="job-other", owner="u-2", published=False)

    def draws() -> Any:
        values = iter(["aaaa1111", "bbbb2222"] * 2)
        return lambda n: next(values)

    monkeypatch.setattr(p6_catalog.secrets, "token_hex", draws())
    assert p6_catalog.new_id(catalog, "Squat", state) == "squat-bbbb2222"
    monkeypatch.setattr(p6_catalog.secrets, "token_hex", draws())
    assert p6_catalog.new_id(catalog, "Squat") == "squat-aaaa1111", "control: without the state only folders count"


def test_mn13_reserve_refuses_another_movements_row(tmp_path: Path) -> None:
    state = tmp_path / "state"
    entry_access.record(state, "squat-aaaa1111", trainer_job="job-other", owner="u-2", published=True)
    before = entry_access.get(state, "squat-aaaa1111")
    link = entry_access.Link(state, "u-1", published=False)
    link.job("job-mine")
    with pytest.raises(OSError):
        link.reserve("squat-aaaa1111")
    assert entry_access.get(state, "squat-aaaa1111") == before
    undo = link.reserve("squat-cccc3333")  # control: a free id is reserved, and undone
    assert entry_access.get(state, "squat-cccc3333")["trainer_job"] == "job-mine"
    undo()
    assert entry_access.get(state, "squat-cccc3333") is None
