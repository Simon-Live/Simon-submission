"""The signed-in person's routes, the hooks and the anonymous regression (docs/specs/identity.md AC-AU-9, 10, 12; TICKET-172)."""

from __future__ import annotations

import json
import sys
import threading
import types
from typing import Any

import pytest

from auth_support import EMAIL, authenv, get, outbox, post, sign_in  # noqa: F401
from part7 import auth, auth_routes, challenge_routes, identity
from support import Api

pytestmark = pytest.mark.usefixtures("authenv")
ENTRY = "lateral-raise"
SCORE = {"value": 81, "grade": "B", "timeline": []}


def job(api: Api, kind: str = "follow", score: bool = True, result: dict | None = None, **fields: Any) -> str:
    def fn(ctx: Any) -> dict[str, Any]:
        if score:
            (ctx.work / "follower").mkdir()
            (ctx.work / "follower" / "analysis.json").write_text(json.dumps({"score": SCORE}))
        return {"result": result or {}}

    made = api.app.queue.submit(kind, fn, entry_id=fields.pop("entry_id", ENTRY), **fields)
    assert api.app.queue.wait(made["id"], 10)["status"] == "done"
    return made["id"]


def running_job(api: Api) -> tuple[str, threading.Event]:
    hold = threading.Event()
    made = api.app.queue.submit("follow", lambda ctx: (hold.wait(10), {"result": {}})[1], entry_id=ENTRY)
    return made["id"], hold


def test_signed_out_routes_answer_401_with_the_text(api: Api) -> None:
    for path in ("api/me/takes", "api/me/entries"):
        status, _, body = get(api, path)
        assert status == 401 and body["message"] == "Sign in to see this."
    for path, doc in (("api/me/claims", {"job_id": "aaaaaaaaaaaa"}), ("api/me/consent", {"retention": True, "version": "v1"}),
                      ("api/me/delete", {"confirm": "delete"}), ("api/me/entries/x", {"only_me": True})):
        assert post(api, path, doc)[0] == 401


def test_claims_first_wins_409_and_404(api: Api) -> None:  # AC-AU-9
    ada, grace = sign_in(api), sign_in(api, "grace@example.com")
    mine = job(api)
    status, _, body = post(api, "api/me/claims", {"job_id": mine}, cookie=ada)
    assert (status, body) == (200, {"claimed": True, "kind": "follow"})
    assert post(api, "api/me/claims", {"job_id": mine}, cookie=ada)[0] == 200  # a repeat by the owner
    status, _, body = post(api, "api/me/claims", {"job_id": mine}, cookie=grace)
    assert status == 409 and body["message"] == "This take is kept by another account."
    for missing in ("ffffffffffff", "short", 5, None):
        status, _, body = post(api, "api/me/claims", {"job_id": missing}, cookie=ada)
        assert status == 404 and body["message"] == challenge_routes.MSG_NO_JOB
    assert post(api, "api/me/claims", {"job_id": job(api, "people")}, cookie=ada)[0] == 404  # not a claimable kind
    assert identity.owner_of_job(api.app.state, mine) == auth.identity(api.app).owner_of(mine)


def test_a_group_take_is_not_owned_and_a_trainer_entry_is(api: Api) -> None:  # AC-AU-9, R3
    sid = sign_in(api)
    group = job(api, "group", people_job="cccccccccccc")
    one_person = job(api, people_job="cccccccccccc", person_id="0")  # a follow cut from one person of a people job
    trainer = job(api, "trainer", result={"entry_id": "my-move"}, entry_id=None)
    assert post(api, "api/me/claims", {"job_id": group}, cookie=sid)[0] == 404  # out of scope: no owner, no history
    assert post(api, "api/me/claims", {"job_id": one_person}, cookie=sid)[2]["kind"] == "follow"  # an ordinary follow take
    assert post(api, "api/me/claims", {"job_id": trainer}, cookie=sid)[2]["kind"] == "trainer"
    entries = get(api, "api/me/entries", cookie=sid)[2]["entries"]
    assert [(e["entry_id"], e["only_me"]) for e in entries] == [("my-move", False)]
    assert group not in {t["job_id"] for t in auth.identity(api.app).takes_of(get(api, "api/auth/me", cookie=sid)[2]["user_id"])}


def test_claim_calls_the_history_store_when_it_exists(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:  # AC-AU-9
    seen: list[tuple[Any, ...]] = []
    fake = types.SimpleNamespace(claim=lambda *a: seen.append(("claim", *a)), forget=lambda *a: seen.append(("forget", *a)))
    monkeypatch.setitem(sys.modules, "part7.history_store", fake)
    sid = sign_in(api)
    mine = job(api)
    post(api, "api/me/claims", {"job_id": mine}, cookie=sid)
    user = get(api, "api/auth/me", cookie=sid)[2]["user_id"]
    post(api, "api/me/delete", {"confirm": "delete"}, cookie=sid)
    assert seen == [("claim", api.app.state, user, mine), ("forget", api.app.state, user)]


def test_takes_newest_first_with_score_from_the_analysis(api: Api) -> None:
    sid = sign_in(api)
    first, second, unscored = job(api), job(api), job(api, score=False)
    for j in (first, second, unscored):
        post(api, "api/me/claims", {"job_id": j}, cookie=sid)
    takes = get(api, "api/me/takes", cookie=sid)[2]["takes"]
    assert {t["job_id"] for t in takes} == {first, second, unscored}
    by_id = {t["job_id"]: t for t in takes}
    assert by_id[first]["score"] == 81 and by_id[first]["grade"] == "B" and by_id[first]["status"] == "done"
    assert by_id[unscored]["score"] is None and by_id[unscored]["grade"] is None
    assert set(by_id[first]) == {"job_id", "kind", "entry_id", "created_at", "status", "score", "grade", "shown", "video_kept", "attribution"}
    assert by_id[first]["shown"]["letter"] == "B" and by_id[unscored]["shown"] is None  # one-letter.md
    assert [t["created_at"] for t in takes] == sorted((t["created_at"] for t in takes), reverse=True)
    assert get(api, "api/me/takes", cookie=sign_in(api, "grace@example.com"))[2] == {"takes": []}  # not someone else's


def test_a_take_whose_folder_expired_is_listed_as_expired(api: Api) -> None:
    sid = sign_in(api)
    owner = get(api, "api/auth/me", cookie=sid)[2]["user_id"]
    auth.identity(api.app).attach("eeeeeeeeeeee", owner, "follow", ENTRY, None, "claim")
    take = get(api, "api/me/takes", cookie=sid)[2]["takes"][0]
    assert take["status"] == "expired" and take["score"] is None


def test_only_me_switch_owner_only_and_visibility(api: Api) -> None:
    ada, grace = sign_in(api), sign_in(api, "grace@example.com")
    owner = get(api, "api/auth/me", cookie=ada)[2]["user_id"]
    auth.identity(api.app).attach_entry(ENTRY, owner, "")
    assert post(api, f"api/me/entries/{ENTRY}", {"only_me": True}, cookie=grace)[0] == 404  # not the owner
    assert post(api, f"api/me/entries/{ENTRY}", {"only_me": "yes"}, cookie=ada)[0] == 400
    assert post(api, "api/me/entries/unknown", {"only_me": True}, cookie=ada)[0] == 404
    assert post(api, f"api/me/entries/{ENTRY}", {"only_me": True}, cookie=ada)[2] == {"entry_id": ENTRY, "only_me": True}

    class H:
        app = api.app
        headers: dict[str, str] = {}

    h = H()
    assert auth.may_view_entry(h, ENTRY) is False  # anonymous
    h.headers = {"Cookie": f"s7_sid={grace}"}
    assert auth.may_view_entry(h, ENTRY) is False
    h.headers = {"Cookie": f"s7_sid={ada}"}
    assert auth.may_view_entry(h, ENTRY) is True and auth.may_view_entry(h, "other-entry") is True
    post(api, f"api/me/entries/{ENTRY}", {"only_me": False}, cookie=ada)
    h.headers = {}
    assert auth.may_view_entry(h, ENTRY) is True
    assert get(api, "api/me/entries", cookie=ada)[2]["entries"][0]["name"] == ENTRY  # the catalog stub names none: the id


def test_consent_records_version_and_choice(api: Api) -> None:
    sid = sign_in(api)
    status, _, body = post(api, "api/me/consent", {"retention": True, "version": "2026-11"}, cookie=sid)
    assert status == 200 and body["retention"] == {"opted_in": True, "days": 90, "consent_version": "2026-11"}
    assert get(api, "api/auth/me", cookie=sid)[2]["retention"]["opted_in"] is True
    uid = get(api, "api/auth/me", cookie=sid)[2]["user_id"]
    assert identity.retention_opt_in(api.app.state, uid) is True
    assert post(api, "api/me/consent", {"retention": False, "version": "2026-11"}, cookie=sid)[2]["retention"]["opted_in"] is False
    for bad in ({"retention": "yes", "version": "v"}, {"retention": True}, {"retention": True, "version": ""},
                {"retention": True, "version": "v" * 41}):
        assert post(api, "api/me/consent", bad, cookie=sid)[0] == 400


def test_delete_my_data_busy_keeps_the_account(api: Api) -> None:  # AC-AU-10
    sid = sign_in(api)
    owner = get(api, "api/auth/me", cookie=sid)[2]["user_id"]
    done, (busy, hold) = job(api), running_job(api)
    post(api, "api/me/claims", {"job_id": done}, cookie=sid)
    auth.identity(api.app).attach(busy, owner, "follow", ENTRY, None, "submit")
    status, _, body = post(api, "api/me/delete", {"confirm": "delete"}, cookie=sid)
    assert status == 409 and body["busy"] == [busy] and body["message"] == "Try again when these finish."
    assert get(api, "api/auth/me", cookie=sid)[2]["signed_in"] is True
    assert len(auth.identity(api.app).takes_of(owner)) == 2  # nothing removed
    hold.set()
    api.app.queue.wait(busy, 10)


def test_delete_my_data_removes_the_account_cookie_and_mail(api: Api) -> None:  # AC-AU-10
    removed: list[str] = []

    def remover(app: Any, job_id: str) -> str:
        removed.append(job_id)
        return "removed"

    auth_routes.TAKE_REMOVER = remover
    try:
        sid, other = sign_in(api), sign_in(api, "grace@example.com")
        mine = job(api)
        theirs = job(api)
        post(api, "api/me/claims", {"job_id": mine}, cookie=sid)
        post(api, "api/me/claims", {"job_id": theirs}, cookie=other)
        owner = get(api, "api/auth/me", cookie=sid)[2]["user_id"]
        auth.identity(api.app).attach_entry("my-move", owner, mine)
        assert len(outbox(api)) == 2
        assert post(api, "api/me/delete", {"confirm": "nope"}, cookie=sid)[0] == 400
        status, head, body = post(api, "api/me/delete", {"confirm": "delete"}, cookie=sid)
    finally:
        auth_routes.TAKE_REMOVER = None
    assert status == 200 and body == {"deleted": True, "takes_removed": 1, "entries_unlinked": 1}
    assert removed == [mine] and "Max-Age=0" in head["set-cookie"]
    assert get(api, "api/auth/me", cookie=sid)[2]["signed_in"] is False and get(api, "api/me/takes", cookie=sid)[0] == 401
    assert len(outbox(api)) == 1 and "grace" in outbox(api)[0].read_text()  # only the deleted address's mail went
    assert get(api, "api/me/takes", cookie=other)[2]["takes"][0]["job_id"] == theirs  # the other account is untouched
    assert api.app.queue.get(mine) is not None  # without a remover the folder is left to the 7-day sweep


def test_delete_my_data_reports_busy_from_the_remover(api: Api) -> None:  # AC-AU-10
    auth_routes.TAKE_REMOVER = lambda app, job_id: "busy"
    try:
        sid = sign_in(api)
        mine = job(api)
        post(api, "api/me/claims", {"job_id": mine}, cookie=sid)
        status, _, body = post(api, "api/me/delete", {"confirm": "delete"}, cookie=sid)
    finally:
        auth_routes.TAKE_REMOVER = None
    assert status == 409 and body["busy"] == [mine] and get(api, "api/auth/me", cookie=sid)[2]["signed_in"] is True


def test_attach_job_and_on_entry_hooks_record_owners_only_when_signed_in(api: Api) -> None:  # contract B
    sid = sign_in(api)
    uid = get(api, "api/auth/me", cookie=sid)[2]["user_id"]

    class H:
        app = api.app
        headers = {"Cookie": f"s7_sid={sid}"}

    anon = types.SimpleNamespace(app=api.app, headers={})
    solo, group, trainer = job(api), job(api, "group", people_job="cccccccccccc"), job(api, "trainer")
    for jid in (solo, group, trainer):
        auth.attach_job(H(), api.app.queue.get(jid))
    auth.attach_job(anon, api.app.queue.get(job(api)))  # anonymous: nothing recorded
    auth.attach_job(H(), {"id": "aaaaaaaaaaaa", "kind": "people"})  # not an ownable kind
    kinds = {t["job_id"]: (t["kind"], t["via"]) for t in auth.identity(api.app).takes_of(uid)}
    assert kinds == {solo: ("follow", "submit"), trainer: ("trainer", "submit")}  # the group take is not recorded
    assert api.app.queue.get(solo).get("user_id") is None  # nothing in the job record  # type: ignore[union-attr]

    inner_calls: list[str] = []
    assert auth.on_entry(anon, None) is None
    marker = lambda entry_id: inner_calls.append(entry_id)  # noqa: E731
    assert auth.on_entry(anon, marker) is marker  # anonymous: the callback is untouched
    wrapped = auth.on_entry(H(), marker)
    wrapped("new-move")  # type: ignore[misc]
    assert inner_calls == ["new-move"] and auth.identity(api.app).entry_owner("new-move") == (uid, False)
    auth.on_entry(H(), None)("bare-move")  # type: ignore[misc]
    assert auth.identity(api.app).entry_owner("bare-move") == (uid, False)


def test_forget_job_hook_drops_ownership(api: Api) -> None:
    sid = sign_in(api)
    mine = job(api)
    post(api, "api/me/claims", {"job_id": mine}, cookie=sid)
    auth.forget_job(api.app, mine)
    assert auth.identity(api.app).owner_of(mine) is None


def test_current_user_survives_garbage_and_store_faults(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    for cookie in ("", "s7_sid=", "s7_sid=nope", "s7_sid=" + "x" * 5000, "\x00;;=", "other=1"):
        h = types.SimpleNamespace(app=api.app, headers={"Cookie": cookie})
        assert auth.current_user(h) is None
    sid = sign_in(api)
    monkeypatch.setattr(identity.IdentityStore, "session_user", lambda self, s: (_ for _ in ()).throw(RuntimeError("db gone")))
    assert auth.current_user(types.SimpleNamespace(app=api.app, headers={"Cookie": f"s7_sid={sid}"})) is None


@pytest.mark.parametrize("transport", ["file", "off"])
def test_anonymous_unchanged(api: Api, monkeypatch: pytest.MonkeyPatch, transport: str) -> None:  # AC-AU-12
    monkeypatch.setenv("SIMON7_MAIL_TRANSPORT", transport)
    done = job(api)
    for path in ("api/health", "api/version", "api/config", f"api/jobs/{done}", "api/teacher/lateral-raise", "catalog/video.mp4"):
        status, head, body = api.request("GET", path)
        assert status == 200, path
        assert "set-cookie" not in head and b"user_id" not in body, path
    assert api.request("GET", "api/jobs/ffffffffffff")[0] == 404
    status, head, _ = api.request("POST", "api/follow", b"{}", {"Content-Type": "application/json"})
    assert status == 400 and "set-cookie" not in head  # same refusal an anonymous caller always got
    assert not (api.app.state / "identity").exists() and not outbox(api)  # no cookie, so the store is never opened


def test_a_signed_in_visitor_sees_the_same_job_record(api: Api) -> None:  # AC-AU-12
    done = job(api)
    before = api.request("GET", f"api/jobs/{done}")[2]
    sid = sign_in(api)
    post(api, "api/me/claims", {"job_id": done}, cookie=sid)
    after = api.request("GET", f"api/jobs/{done}", None, {"Cookie": f"s7_sid={sid}"})[2]
    seen, own = json.loads(before), json.loads(after)
    assert own.pop("attribution")["mine"] is True and seen.pop("attribution")["mine"] is False  # the one field the viewer changes
    assert seen == own and b"user_id" not in after  # ownership never reaches job.json
    assert "user_id" not in (api.app.queue.job_dir(done) / "job.json").read_text()


def test_a_forged_host_gets_no_mail_and_a_pinned_origin_names_the_link(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:  # R1
    from auth_support import plain_text, outbox as box

    forged = {"Host": "evil.example", "Origin": "http://evil.example"}
    status, _, body = post(api, "api/auth/start", {"email": EMAIL}, forged)
    assert status == 403 and body["message"] == auth_routes.MSG_ORIGIN
    assert box(api) == []  # no challenge, no mail
    assert post(api, "api/auth/start", {"email": EMAIL})[0] == 202  # the real local host still works
    assert "http://127.0.0.1:" in plain_text(box(api)[-1])
    monkeypatch.setenv("SIMON7_PUBLIC_ORIGIN", "https://simon.example.org")
    assert post(api, "api/auth/start", {"email": "grace@example.com"}, forged)[0] == 202  # pinned: Host no longer matters
    text = plain_text(box(api)[-1])
    assert "https://simon.example.org" in text and "evil.example" not in text


def test_staging_trusts_a_host_only_when_it_came_through_the_gateway(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:  # R1
    monkeypatch.setenv("STAGING_BASE_PATH", "/simon-part-7/")
    monkeypatch.setattr(auth.mail, "is_local", lambda: False)
    def req(peer: str, **headers: str) -> Any:
        return types.SimpleNamespace(headers={"Host": "tunnel.example", **headers}, client_address=(peer, 1))

    assert auth.public_origin(req("127.0.0.1")) is None  # a direct request with a made-up Host
    assert auth.public_origin(req("203.0.113.9", **{"Cf-Connecting-Ip": "1.2.3.4"})) is None  # not the gateway hop
    assert auth.public_origin(req("127.0.0.1", **{"Cf-Connecting-Ip": "1.2.3.4"})) == "https://tunnel.example"


def test_labels_of_an_only_me_entry_are_its_owners_alone(api: Api) -> None:
    """GET api/labels and api/labels/<id> never show an only-me entry's labels or floor-work mark to anyone else."""
    from part7 import labels

    ada, grace = sign_in(api), sign_in(api, "grace@example.com")
    owner = get(api, "api/auth/me", cookie=ada)[2]["user_id"]
    auth.identity(api.app).attach_entry(ENTRY, owner, "")
    labels.save(api.app.state, ENTRY, labels.validate({"tags": ["knee"], "notes": "private"}))
    labels.set_floor_work(api.app.state, ENTRY, True)
    labels.save(api.app.state, "public-move", labels.validate({"tags": ["arm"], "notes": ""}))
    assert post(api, f"api/me/entries/{ENTRY}", {"only_me": True}, cookie=ada)[0] == 200
    for cookie in (None, grace):  # signed out, then a second account
        listed = get(api, "api/labels", cookie=cookie)[2]
        assert ENTRY not in listed and "public-move" in listed
        assert get(api, f"api/labels/{ENTRY}", cookie=cookie)[0] == 404
    mine = get(api, "api/labels", cookie=ada)[2]
    assert mine[ENTRY]["floor_work"] is True and mine[ENTRY]["tags"] == ["knee"]
    assert get(api, f"api/labels/{ENTRY}", cookie=ada)[0] == 200
