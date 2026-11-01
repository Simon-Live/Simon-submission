"""The hooks that join sign-in, the history store and the existing server (TICKET-175; docs/specs/history.md "Hooks").

Each hook is proved at the file that owns it: server, jobs, delete_routes, teacher_routes, keys and auth_routes. The
anonymous cases prove that with nobody signed in nothing changes."""

from __future__ import annotations

import json
import threading
import time
from typing import Any

import pytest

from auth_support import authenv, get, post, sign_in  # noqa: F401
from part7 import auth, auth_routes, delete_routes, history_store, identity, keys
from support import Api

pytestmark = pytest.mark.usefixtures("authenv")
ENTRY = "lateral-raise"


def until(test: Any, seconds: float = 10.0) -> bool:
    """Poll `test()` until it is true: the history copy runs on its own thread, a moment after the job is done."""
    end = time.time() + seconds
    while time.time() < end:
        if test():
            return True
        time.sleep(0.02)
    return bool(test())


def copies_running() -> bool:
    return any(t.name.startswith("history-copy-") and t.is_alive() for t in threading.enumerate())


def finished(api: Api, **fields: Any) -> str:
    def fn(ctx: Any) -> dict[str, Any]:
        (ctx.work / "follower").mkdir()
        (ctx.work / "follower" / "analysis.json").write_text(json.dumps({"score": {"value": 70, "grade": "C", "timeline": []}}))
        return {"result": {}}

    made = api.app.queue.submit("follow", fn, entry_id=ENTRY, **fields)
    assert api.app.queue.wait(made["id"], 10)["status"] == "done"
    return made["id"]


def test_every_answer_says_no_referrer(api: Api) -> None:
    for path in ("api/health", "api/auth/me", "api/no-such-route"):
        assert get(api, path)[1]["referrer-policy"] == "no-referrer"


def test_the_two_new_key_names_are_registered_for_redaction() -> None:
    assert "SIMON7_SMTP_URL" in keys.KEY_NAMES and "SIMON7_AUTH_PEPPER" in keys.KEY_NAMES


def test_a_finished_job_is_offered_to_the_history_store_and_a_fault_does_not_fail_it(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []
    monkeypatch.setattr(history_store, "record_take", lambda state, job, job_dir: seen.append(job["id"]))
    first = finished(api)
    assert until(lambda: seen == [first])

    def boom(state: Any, job: Any, job_dir: Any) -> None:
        raise RuntimeError("disk full")

    monkeypatch.setattr(history_store, "record_take", boom)
    second = finished(api)
    assert until(lambda: not copies_running()) and api.app.queue.get(second)["status"] == "done"  # the warning is logged, the job stays done


def test_an_anonymous_finished_take_is_not_copied(api: Api) -> None:
    job_id = finished(api)
    assert not (api.app.state / "history").exists() or not list((api.app.state / "history").glob("*/*/takes/*"))
    assert api.app.queue.get(job_id)["status"] == "done"


def test_the_job_sweep_runs_the_history_sweep(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[Any] = []
    monkeypatch.setattr(history_store, "sweep", lambda state, now=None: calls.append(state) or 0)
    api.app.queue.cleanup()
    assert calls == [api.app.state]

    def boom(state: Any, now: Any = None) -> int:
        raise OSError("gone")

    monkeypatch.setattr(history_store, "sweep", boom)
    api.app.queue.cleanup()  # a history fault does not stop the sweep


def test_delete_take_drops_the_history_copy_and_the_ownership_row(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    dropped: list[str] = []
    monkeypatch.setattr(history_store, "drop_take", lambda state, job_id: dropped.append(job_id) or 0)
    sid = sign_in(api)
    job_id = finished(api)
    assert post(api, "api/me/claims", {"job_id": job_id}, cookie=sid)[0] == 200
    assert [t["job_id"] for t in get(api, "api/me/takes", cookie=sid)[2]["takes"]] == [job_id]
    assert api.json("POST", f"api/jobs/{job_id}/delete", {})[0] == 200
    assert dropped == [job_id]
    assert get(api, "api/me/takes", cookie=sid)[2] == {"takes": []}
    assert identity.owner_of_job(api.app.state, job_id) is None


def test_an_anonymous_delete_by_job_id_still_works(api: Api) -> None:
    job_id = finished(api)
    status, body = api.json("POST", f"api/jobs/{job_id}/delete", {})
    assert status == 200 and body["deleted"] is True and api.app.queue.get(job_id) is None


def test_account_delete_removes_the_real_takes(api: Api) -> None:
    assert auth_routes.TAKE_REMOVER is delete_routes.remove_for_account
    sid = sign_in(api)
    job_id = finished(api)
    post(api, "api/me/claims", {"job_id": job_id}, cookie=sid)
    status, _, body = post(api, "api/me/delete", {"confirm": "delete"}, cookie=sid)
    assert status == 200 and body["deleted"] is True and body["takes_removed"] == 1
    assert api.app.queue.get(job_id) is None


def test_the_remover_answers_removed_busy_or_gone(api: Api) -> None:
    done = finished(api)
    assert delete_routes.remove_for_account(api.app, done) == "removed"
    assert delete_routes.remove_for_account(api.app, done) == "gone"
    assert delete_routes.remove_for_account(api.app, "ffffffffffff") == "gone"


def test_withdrawing_retention_calls_the_history_store_and_keeping_does_not(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    withdrawn: list[str] = []
    monkeypatch.setattr(history_store, "withdraw_retention", lambda state, user: withdrawn.append(user) or 0)
    sid = sign_in(api)
    uid = get(api, "api/auth/me", cookie=sid)[2]["user_id"]
    assert post(api, "api/me/consent", {"retention": True, "version": "v1"}, cookie=sid)[0] == 200
    assert withdrawn == []
    assert post(api, "api/me/consent", {"retention": False, "version": "v1"}, cookie=sid)[0] == 200
    assert withdrawn == [uid]


def test_a_claim_copies_into_history_through_the_store(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    claimed: list[tuple[str, str]] = []
    monkeypatch.setattr(history_store, "claim", lambda state, user, job: claimed.append((user, job)) or True)
    sid = sign_in(api)
    job_id = finished(api)
    assert post(api, "api/me/claims", {"job_id": job_id}, cookie=sid)[0] == 200
    assert claimed == [(get(api, "api/auth/me", cookie=sid)[2]["user_id"], job_id)]


def test_the_teacher_page_hides_an_only_me_entry_from_others_and_not_from_anonymous_entries(api: Api) -> None:
    assert get(api, f"api/teacher/{ENTRY}")[0] == 200  # nobody owns it: unchanged
    ada, grace = sign_in(api), sign_in(api, "grace@example.com")
    owner = get(api, "api/auth/me", cookie=ada)[2]["user_id"]
    auth.identity(api.app).attach_entry(ENTRY, owner, "")
    assert get(api, f"api/teacher/{ENTRY}")[0] == 200  # owned but not marked only me
    post(api, f"api/me/entries/{ENTRY}", {"only_me": True}, cookie=ada)
    assert get(api, f"api/teacher/{ENTRY}")[0] == 404
    assert get(api, f"api/teacher/{ENTRY}", cookie=grace)[0] == 404
    assert get(api, f"api/teacher/{ENTRY}", cookie=ada)[0] == 200


def test_the_versions_the_pages_send_pass_the_server_checks() -> None:
    """The web sends a consent version string; the fake servers of the web tests accepted any value."""
    import re
    from pathlib import Path

    web = Path(__file__).resolve().parents[2] / "web" / "model"
    for name in ("history.js", "me.js"):
        found = re.search(r'CONSENT_VERSION = "([^"]*)"', (web / name).read_text(encoding="utf-8"))
        assert found and history_store.VERSION_RE.match(found.group(1)) and 0 < len(found.group(1)) <= auth_routes.VERSION_MAX, name


def test_the_sweep_prunes_expired_sign_in_state_and_an_idle_account_goes_whole(api: Api) -> None:  # B3

    sid = sign_in(api)
    uid = get(api, "api/auth/me", cookie=sid)[2]["user_id"]
    store = auth.identity(api.app)
    copy = history_store.take_dir(api.app.state, uid, ENTRY, "aaaaaaaaaaaa")
    copy.mkdir(parents=True)
    (copy / "meta.json").write_text(json.dumps({"kept_ts": time.time() + 400 * 86400}))  # young: only the account delete removes it
    assert list((api.app.state / "outbox").glob("*.eml"))  # the sign-in mail
    api.app.queue.cleanup()  # nothing is old yet
    assert store.user(uid) is not None and copy.is_dir() and get(api, "api/me/takes", cookie=sid)[0] == 200
    store.clock = lambda: time.time() + 31 * 86400  # past the sessions' 30 days, the challenges' 2 days
    api.app.queue.cleanup()
    assert get(api, "api/me/takes", cookie=sid)[0] == 401 and store.user(uid) is not None  # the session is pruned
    store.clock = lambda: time.time() + 200 * 86400  # idle past 180 days
    api.app.queue.cleanup()
    assert store.user(uid) is None  # the account
    assert not copy.exists() and not (api.app.state / "history" / uid).exists()  # its history copies
    assert not list((api.app.state / "outbox").glob("*.eml"))  # and its mail


def test_only_me_fails_closed_when_the_store_errors(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:  # R10
    sign_in(api)  # the identity file exists
    assert get(api, f"api/teacher/{ENTRY}")[0] == 200

    def broken(app: Any) -> Any:
        raise RuntimeError("database is locked")

    monkeypatch.setattr(auth, "identity", broken)
    assert get(api, f"api/teacher/{ENTRY}")[0] == 404  # hidden, not shown


def test_an_anonymous_delete_survives_a_fault_in_the_opt_in_stores(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:  # R4
    def boom(*args: Any) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(history_store, "drop_take", boom)
    monkeypatch.setattr(auth, "forget_job", boom)
    job_id = finished(api)
    status, body = api.json("POST", f"api/jobs/{job_id}/delete", {})
    assert status == 200 and body["deleted"] is True and api.app.queue.get(job_id) is None


def test_the_worker_returns_before_the_history_transcode_finishes(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:  # R5
    started, release, done = threading.Event(), threading.Event(), threading.Event()

    def slow_copy(state: Any, job: Any, job_dir: Any) -> bool:
        started.set()
        release.wait(20)
        done.set()
        return True

    monkeypatch.setattr(history_store, "record_take", slow_copy)
    job_id = finished(api)  # waits for the job to be done: this returns while the copy is still blocked
    assert started.wait(10) and not done.is_set() and api.app.queue.get(job_id)["status"] == "done"
    second = finished(api)  # the same worker takes the next job although the first copy has not finished
    assert api.app.queue.get(second)["status"] == "done" and not done.is_set()
    release.set()
    assert until(done.is_set)


def test_both_pages_title_an_entry_through_one_lookup(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:  # R14
    from part7 import labels

    api.app.child.entries[ENTRY]["name"] = "Lateral raise"
    assert labels.entry_name(api.app.child, ENTRY) == "Lateral raise"
    assert labels.entry_name(api.app.child, "unknown-entry") == "unknown-entry"
    sid = sign_in(api)
    owner = get(api, "api/auth/me", cookie=sid)[2]["user_id"]
    auth.identity(api.app).attach_entry(ENTRY, owner, "")
    assert get(api, "api/me/entries", cookie=sid)[2]["entries"][0]["name"] == "Lateral raise"
