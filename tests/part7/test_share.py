"""Signed, revocable share links over a real server (docs/specs/share.md, TICKET-233)."""

from __future__ import annotations

import json
import sqlite3
import sys
import types
from typing import Any

import pytest

from auth_support import authenv, get, post, sign_in  # noqa: F401
from history_support import ENTRY as H_ENTRY, FIRST, SECOND, job_record, seed_job
from part7 import auth, history_report, history_store, identity, share
from support import Api

pytestmark = pytest.mark.usefixtures("authenv")
ENTRY = "lateral-raise"
ANALYSIS = {"score": {"value": 81, "grade": "B", "timeline": []}, "faults": [{"text": "leaning forward more than the example"}]}
GRACE = "grace@example.com"


def make_job(api: Api, score: int = 81) -> str:
    def fn(ctx: Any) -> dict[str, Any]:
        (ctx.work / "follower").mkdir()
        (ctx.work / "follower" / "analysis.json").write_text(json.dumps({**ANALYSIS, "score": {**ANALYSIS["score"], "value": score}}))
        return {"result": {}}

    made = api.app.queue.submit("follow", fn, entry_id=ENTRY)
    assert api.app.queue.wait(made["id"], 10)["status"] == "done"
    return made["id"]


def owned_job(api: Api, sid: str, score: int = 81) -> str:
    job = make_job(api, score)
    assert post(api, "api/me/claims", {"job_id": job}, cookie=sid)[0] == 200
    return job


def share_body(job: str, **more: Any) -> dict[str, Any]:
    return {"kind": "take_result", "item_ref": job, "confirm": True, "days": 7, **more}


def make_share(api: Api, sid: str, job: str, **more: Any) -> str:
    status, _, doc = post(api, "api/shares", share_body(job, **more), cookie=sid)
    assert status == 201, doc
    return doc["token"]


def store(api: Api) -> identity.IdentityStore:
    return auth.identity(api.app)


def test_the_viewer_shows_only_the_snapshot_and_no_account_detail(api: Api) -> None:
    sid = sign_in(api)
    job = owned_job(api, sid)
    token = make_share(api, sid, job)
    status, head, doc = get(api, f"api/shared/{token}")  # no cookie: nobody needs to sign in
    assert status == 200
    assert (doc["title"], doc["score"], doc["grade"], doc["kind"]) == (ENTRY, 81, "B", "take_result")
    assert doc["faults"] == ["leaning forward more than the example"] and doc["author"] is None and doc["clip"] is None
    assert head["cache-control"] == "no-store" and head["referrer-policy"] == "no-referrer" and head["x-robots-tag"] == "noindex"
    text = json.dumps(doc).lower()
    user_id = identity.owner_of_job(api.app.state, job)
    assert "example.com" not in text and job not in text and user_id not in text and "u-" not in text


def test_defaults_name_off_and_clip_off_and_an_opt_in_name(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    profile = types.ModuleType("part7.profile")
    profile.public_identity = lambda db, user: {"name": "Ada", "avatar": None, "credit_as_trainer": False}  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "part7.profile", profile)
    sid = sign_in(api)
    job = owned_job(api, sid)
    assert get(api, f"api/shared/{make_share(api, sid, job)}")[2]["author"] is None  # name is off unless ticked
    assert get(api, f"api/shared/{make_share(api, sid, job, show_name=True)}")[2]["author"] == "Ada"
    rows = share.list_for_owner(store(api), identity.owner_of_job(api.app.state, job))
    assert sorted(r["show_name"] for r in rows) == [False, True] and not any(r["show_clip"] for r in rows)


def test_a_name_without_a_profile_is_left_out(api: Api) -> None:
    sid = sign_in(api)
    token = make_share(api, sid, owned_job(api, sid), show_name=True)
    assert get(api, f"api/shared/{token}")[2]["author"] is None


def test_tampered_malformed_and_unknown_tokens_get_one_generic_404(api: Api) -> None:
    sid = sign_in(api)
    token = make_share(api, sid, owned_job(api, sid))
    share_id, mac = token.split(".")
    flipped = mac[:-1] + ("A" if mac[-1] != "A" else "B")
    forged = f"{share.secrets.token_urlsafe(12)}.{mac}"
    bodies = set()
    for bad in (f"{share_id}.{flipped}", forged, share_id, f"{token}x", "a.b", "....", "x" * 200):
        status, head, doc = get(api, f"api/shared/{bad}")
        assert status == 404 and head["x-robots-tag"] == "noindex"
        bodies.add(json.dumps(doc))
    assert len(bodies) == 1
    assert get(api, f"api/shared/{token}")[0] == 200  # the real one still opens


def test_a_token_signed_with_another_pepper_is_refused(api: Api) -> None:
    sid = sign_in(api)
    token = make_share(api, sid, owned_job(api, sid))
    assert share.signing_key(b"a") != share.signing_key(b"b") and share.signing_key(b"a") == share.signing_key(b"a")
    other = identity.IdentityStore(api.app.state, b"another pepper", clock=store(api).clock)
    assert share.resolve(other, token) is None and share.resolve(store(api), token) is not None


def test_only_the_hash_of_the_token_is_stored(api: Api) -> None:
    sid = sign_in(api)
    token = make_share(api, sid, owned_job(api, sid))
    dump = "\n".join(sqlite3.connect(identity.db_path(api.app.state)).iterdump())
    assert token not in dump and token.split(".")[1] not in dump and share.token_hash(token) in dump


@pytest.mark.parametrize("days,alive_after,gone_after", [(1, 86000, 86500), (7, 6 * 86400, 7 * 86400 + 5), (30, 29 * 86400, 30 * 86400 + 5)])
def test_expiry_in_one_seven_or_thirty_days(api: Api, monkeypatch: pytest.MonkeyPatch, days: int, alive_after: int, gone_after: int) -> None:
    now = [1_800_000_000.0]
    monkeypatch.setattr(auth, "CLOCK", lambda: now[0])
    sid = sign_in(api)
    token = make_share(api, sid, owned_job(api, sid), days=days)
    now[0] += alive_after
    assert get(api, f"api/shared/{token}")[0] == 200
    now[0] += gone_after - alive_after
    assert get(api, f"api/shared/{token}")[0] == 404
    owner = store(api).fetch("SELECT owner_id FROM shares")[0][0]
    assert share.list_for_owner(store(api), owner)[0]["state"] == "expired"


def test_days_outside_one_seven_thirty_are_refused(api: Api) -> None:
    sid = sign_in(api)
    job = owned_job(api, sid)
    for days in (0, 2, 31, 365, "7", True, None):
        status, _, doc = post(api, "api/shares", share_body(job, days=days), cookie=sid)
        assert status == 400 and doc["message"] == share.MSG_DAYS


def test_revoke_works_on_the_next_request_and_only_for_the_owner(api: Api) -> None:
    ada, grace = sign_in(api), sign_in(api, GRACE)
    token = make_share(api, ada, owned_job(api, ada))
    assert get(api, f"api/shared/{token}")[0] == 200
    listed = get(api, "api/me/shares", cookie=ada)[2]["shares"]
    assert len(listed) == 1 and listed[0]["state"] == "active" and "token" not in listed[0] and token not in json.dumps(listed)
    mine = listed[0]["id"]
    assert get(api, "api/me/shares", cookie=grace)[2] == {"shares": []}  # another person's list shows nothing of mine
    status, _, _ = api.request("DELETE", f"api/me/shares/{mine}", None, {"Origin": f"http://127.0.0.1:{api.port}", "Content-Type": "application/json", "Cookie": f"{auth.COOKIE}={grace}"})
    assert status == 404 and get(api, f"api/shared/{token}")[0] == 200
    status, _, doc = api.request("DELETE", f"api/me/shares/{mine}", None, {"Origin": f"http://127.0.0.1:{api.port}", "Content-Type": "application/json", "Cookie": f"{auth.COOKIE}={ada}"})
    assert status == 200 and json.loads(doc) == {"revoked": True}
    assert get(api, f"api/shared/{token}")[0] == 404
    assert get(api, "api/me/shares", cookie=ada)[2]["shares"][0]["state"] == "revoked"


def test_owner_routes_need_a_session_and_a_same_origin_delete(api: Api) -> None:
    assert get(api, "api/me/shares")[0] == 401
    assert post(api, "api/shares", share_body("aaaaaaaaaaaa"))[0] == 401
    sid = sign_in(api)
    assert api.request("DELETE", f"api/me/shares/{'0' * 64}", None, {"Cookie": f"{auth.COOKIE}={sid}"})[0] == 403
    assert api.request("DELETE", f"api/me/shares/{'0' * 64}", None, {"Origin": f"http://127.0.0.1:{api.port}", "Content-Type": "application/json", "Cookie": f"{auth.COOKIE}={sid}"})[0] == 404
    assert post(api, "api/shares", share_body("aaaaaaaaaaaa"), cookie=sid, guard=False)[0] == 403


def test_a_later_edit_does_not_reach_an_existing_share(api: Api) -> None:
    sid = sign_in(api)
    job = owned_job(api, sid, score=81)
    token = make_share(api, sid, job)
    (api.app.queue.job_dir(job) / "work" / "follower" / "analysis.json").write_text(json.dumps({"score": {"value": 12, "grade": "F"}, "faults": []}))
    again = make_share(api, sid, job)  # a new share sees the new state; the old one keeps what was shared
    assert get(api, f"api/shared/{token}")[2]["score"] == 81 and get(api, f"api/shared/{again}")[2]["score"] == 12


def test_another_users_take_and_bad_requests_are_404_or_400(api: Api) -> None:
    ada, grace = sign_in(api), sign_in(api, GRACE)
    mine = owned_job(api, ada)
    for item in (mine, "ffffffffffff", "short", 5, None):
        status, _, doc = post(api, "api/shares", share_body(item), cookie=grace)
        assert status == 404 and doc["message"] == "There is nothing here to share."
    assert post(api, "api/shares", {k: v for k, v in share_body(mine).items() if k != "confirm"}, cookie=ada)[0] == 400
    assert post(api, "api/shares", share_body(mine, confirm="yes"), cookie=ada)[0] == 400
    status, _, doc = post(api, "api/shares", share_body(mine, kind="progress_card"), cookie=ada)
    assert status == 400 and doc["message"] == share.MSG_KIND  # offered once TICKET-227 is merged
    assert post(api, "api/shares", share_body(mine, kind="nonsense"), cookie=ada)[0] == 400
    assert share.list_for_owner(store(api), identity.owner_of_job(api.app.state, mine)) == []
    assert get(api, "api/me/shares", cookie=grace)[2] == {"shares": []}


def test_a_clip_needs_a_kept_clip_and_the_take_is_not_shared_with_one_by_default(api: Api) -> None:
    sid = sign_in(api)
    status, _, doc = post(api, "api/shares", share_body(owned_job(api, sid), show_clip=True), cookie=sid)
    assert status == 400 and doc["message"] == "This take has no kept clip to share."


def test_the_migration_copies_the_database_first_and_is_idempotent(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    db = store(api)
    sign_in(api)
    assert not db.has_table("shares")
    monkeypatch.setattr(identity.IdentityStore, "backup_to", lambda self, target: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(share.ShareError) as refused:
        share.ensure_schema(db)
    assert refused.value.status == 503 and not db.has_table("shares")  # no copy, no migration
    monkeypatch.undo()
    share.ensure_schema(db)
    backup = identity.db_path(api.app.state).with_name("identity.db.pre-shares")
    assert backup.is_file() and (backup.stat().st_mode & 0o777) == 0o600
    assert "shares" not in {r[0] for r in sqlite3.connect(backup).execute("SELECT name FROM sqlite_master")}  # taken before
    assert db.has_table("shares")
    share.ensure_schema(db)  # again: nothing changes
    assert db.fetch("SELECT COUNT(*) FROM users")[0][0] == 1


def test_deleting_a_take_or_the_account_ends_the_links(api: Api) -> None:
    ada, grace = sign_in(api), sign_in(api, GRACE)
    job = owned_job(api, ada)
    gone, kept = make_share(api, ada, job), make_share(api, grace, owned_job(api, grace))
    store(api).forget_job(job)
    assert get(api, f"api/shared/{gone}")[0] == 404 and get(api, f"api/shared/{kept}")[0] == 200
    own = make_share(api, ada, owned_job(api, ada))
    store(api).delete_user(store(api).session_user(ada))
    assert get(api, f"api/shared/{own}")[0] == 404 and get(api, f"api/shared/{kept}")[0] == 200


def test_limits_ten_an_hour_and_twenty_active(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    now = [1_800_000_000.0]
    monkeypatch.setattr(auth, "CLOCK", lambda: now[0])
    sid = sign_in(api)
    job = owned_job(api, sid)
    for _ in range(share.MAX_PER_HOUR):
        make_share(api, sid, job)
    status, _, doc = post(api, "api/shares", share_body(job), cookie=sid)
    assert status == 429 and doc["message"] == share.MSG_LIMIT_HOUR
    now[0] += 7200
    for _ in range(share.MAX_PER_HOUR):
        make_share(api, sid, job)
    status, _, doc = post(api, "api/shares", share_body(job), cookie=sid)
    assert status == 429 and doc["message"] == share.MSG_LIMIT_ACTIVE


def test_the_viewer_is_rate_limited_per_address(api: Api) -> None:
    from part7 import share_routes

    for _ in range(share_routes.VIEW_PER_IP[0]):
        assert get(api, "api/shared/nothing")[0] == 404
    assert get(api, "api/shared/nothing")[0] == 429


def test_the_sweep_removes_old_ended_rows_only(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    now = [1_800_000_000.0]
    monkeypatch.setattr(auth, "CLOCK", lambda: now[0])
    sid = sign_in(api)
    job = owned_job(api, sid)
    short, long_ = make_share(api, sid, job, days=1), make_share(api, sid, job, days=30)
    now[0] += 3 * 86400
    assert share.sweep(store(api)) == 1
    assert get(api, f"api/shared/{long_}")[0] == 200 and get(api, f"api/shared/{short}")[0] == 404
    assert share.sweep(store(api)) == 0


def test_the_token_never_reaches_the_server_log(api: Api, capsys: pytest.CaptureFixture[str]) -> None:
    sid = sign_in(api)
    token = make_share(api, sid, owned_job(api, sid))
    get(api, f"api/shared/{token}")
    get(api, f"api/shared/{token}x")
    err = capsys.readouterr().err
    assert "/api/shared/<token>" in err and token not in err and token.split(".")[0] not in err


def test_a_report_share_carries_the_report_and_no_ids(api: Api) -> None:
    sid = sign_in(api)
    db, state = store(api), api.app.state
    user = db.session_user(sid)
    db.set_consent(user, "v1", True)
    for job in (FIRST, SECOND):
        folder = seed_job(state, job)
        assert db.attach(job, user, "follow", H_ENTRY, None, "claim")
        assert history_store.record_take(state, job_record(state, job), folder)
    body = {"kind": "history_report", "item_ref": H_ENTRY, "confirm": True, "days": 7}
    status, _, doc = post(api, "api/shares", body, cookie=sid)
    assert status == 404 and doc["message"] == share_routes_msg()  # no comparison yet
    runner = history_report.runner_for(state, api.app.child.catalog_dir)
    _, key, _ = runner.plan(user, H_ENTRY)
    report = {"format": history_report.FORMAT, "summary": {"text": "Take 2 scored 77."}, "trends": [{"text": "Your chest stays up."}],
              "takes": [{"take": 1, "job_id": FIRST, "at": "2026-10-20T10:00:00Z", "score": 100, "grade": "A", "clip": True}],
              "observations": [{"text": "private cue"}]}
    path = history_report.report_path(state, user, H_ENTRY, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report))
    token = post(api, "api/shares", body, cookie=sid)[2]["token"]
    doc = get(api, f"api/shared/{token}")[2]
    assert doc["summary"] == "Take 2 scored 77." and doc["trends"] == ["Your chest stays up."] and doc["kind"] == "history_report"
    assert doc["takes"] == [{"take": 1, "on": "2026-10-20", "score": 100, "grade": "A"}]
    assert FIRST not in json.dumps(doc) and "private cue" not in json.dumps(doc) and user not in json.dumps(doc)
    other = sign_in(api, GRACE)
    assert post(api, "api/shares", body, cookie=other)[0] == 404  # another person's movement history


@pytest.mark.parametrize("ticks", [{}, {"include_faults": False}, {"include_score": False}, {"show_name": True}])
def test_the_owner_preview_has_the_viewers_title_score_and_faults(api: Api, ticks: dict[str, bool]) -> None:
    """QA share-link-take-create (release 20): the dialog showed a placeholder title and no faults while the viewer had both."""
    sid = sign_in(api)
    job = owned_job(api, sid)
    status, _, preview = post(api, "api/shares/preview", share_body(job, **ticks), cookie=sid)
    assert status == 200
    viewer = get(api, f"api/shared/{make_share(api, sid, job, **ticks)}")[2]
    for key in ("title", "score", "grade", "result", "faults", "on", "author", "attribution", "include", "kind"):
        assert preview.get(key) == viewer.get(key), key
    assert ("result" in viewer) is ticks.get("include_score", True), "an unticked score drops the result block too"
    assert preview["title"] == ENTRY and preview["title"] != "Your result"  # negative: never the old placeholder
    if ticks.get("include_faults", True):
        assert preview["faults"] == ["leaning forward more than the example"]


def share_routes_msg() -> str:
    from part7 import share_routes

    return share_routes.MSG_NO_REPORT


FIXTURES = __import__("pathlib").Path(__file__).resolve().parents[2] / "fixtures" / "input"


def capped_analysis() -> dict[str, Any]:
    """The low-match hero (59 F, capped by low_match, 100 A before the cap) with analysis-credit.json's credit block:
    a warning cap beside a credit that ignores it, the shape of staging take f530a6875dfb."""
    hero = json.loads((FIXTURES / "analysis-low-match-hero.json").read_text())
    credit = json.loads((FIXTURES / "analysis-credit.json").read_text())["score"]["credit"]
    return {**hero, "score": {**hero["score"], "credit": credit}}


def job_with(api: Api, sid: str, analysis: dict[str, Any], result: dict[str, Any] | None = None) -> str:
    def fn(ctx: Any) -> dict[str, Any]:
        (ctx.work / "follower").mkdir()
        (ctx.work / "follower" / "analysis.json").write_text(json.dumps(analysis))
        return {"result": result or {}}

    made = api.app.queue.submit("follow", fn, entry_id=ENTRY)
    assert api.app.queue.wait(made["id"], 10)["status"] == "done"
    assert post(api, "api/me/claims", {"job_id": made["id"]}, cookie=sid)[0] == 200
    return made["id"]


def test_a_capped_take_shares_its_cap_warning_and_credit_for_the_result_code(api: Api) -> None:
    """Staging 333aefca5: the share showed "0 F" with no warning. The snapshot now carries what the result draws from."""
    sid = sign_in(api)
    analysis = capped_analysis()
    job = job_with(api, sid, analysis, {"light": {"level": "ok", "median_y": 120.0, "dark_share": 0.0}})
    status, _, preview = post(api, "api/shares/preview", share_body(job), cookie=sid)
    doc = get(api, f"api/shared/{make_share(api, sid, job)}")[2]
    assert status == 200 and preview["result"] == doc["result"]
    block = doc["result"]
    assert (doc["score"], doc["grade"]) == (59, "F")  # the old fields stay for pages that read them
    assert block["score"]["value"] == 59 and block["score"]["grade"] == "F"
    assert block["score"]["capped_by"] == ["low_match"] and block["score"]["uncapped"] == {"value": 100, "grade": "A"}
    assert block["warnings"] == [{"code": "low_match", "text": analysis["warnings"][0]["text"]}]
    assert block["match"] == {"quality": "low"} and block["light"] == {"level": "ok"}
    credit = block["score"]["credit"]
    assert (credit["points"], credit["max_points"], credit["grade"]) == (9087, 12160, "C")
    # nothing the result code does not read: no per-window detail, no timeline, no job id
    assert "per_window" not in credit and "levels" not in credit and "timeline" not in block["score"]
    assert job not in json.dumps(doc)


def test_an_uncapped_take_shares_its_score_as_before(api: Api) -> None:
    sid = sign_in(api)
    doc = get(api, f"api/shared/{make_share(api, sid, owned_job(api, sid))}")[2]
    assert (doc["score"], doc["grade"]) == (81, "B")
    assert doc["result"] == {"score": {"value": 81, "grade": "B"}, "warnings": [], "mode": None}


def test_a_snapshot_stored_before_the_result_block_is_served_unchanged(api: Api) -> None:
    sid = sign_in(api)
    token = make_share(api, sid, owned_job(api, sid))
    old = {"title": ENTRY, "score": 0, "grade": "F", "faults": [], "on": "2026-11-02", "include": {"score": True, "faults": True},
           "author": None, "attribution": None, "clip": False}
    assert store(api).write("UPDATE shares SET snapshot = ? WHERE token_hash = ?", (json.dumps(old), share.token_hash(token))) == 1
    doc = get(api, f"api/shared/{token}")[2]
    assert (doc["score"], doc["grade"]) == (0, "F") and "result" not in doc


def test_the_owners_points_or_percent_choice_is_kept_and_odd_values_are_dropped(api: Api) -> None:
    sid = sign_in(api)
    job = job_with(api, sid, capped_analysis())
    keep = {"score_display": {"mode": "percent", "level": "hard"}}
    doc = get(api, f"api/shared/{make_share(api, sid, job, **keep)}")[2]
    assert doc["result"]["display"] == {"mode": "percent", "level": "hard"}
    preview = post(api, "api/shares/preview", share_body(job, **keep), cookie=sid)[2]
    assert preview["result"] == doc["result"]
    odd = get(api, f"api/shared/{make_share(api, sid, job, score_display={'mode': 'big', 'level': 1})}")[2]
    assert "display" not in odd["result"]
    assert "result" not in get(api, f"api/shared/{make_share(api, sid, job, include_score=False, **keep)}")[2]
