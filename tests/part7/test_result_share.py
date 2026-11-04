"""The result page's "Share this result" link, end to end on the server (docs/specs/share.md "Result share", TICKET-394).

The link a person copies is a signed `#/shared/<token>` link that opens signed out; the result's own address never is. The
server enforces the length the person chose, says plainly when a link ended, and a shared view outlives the 7 days a result
is kept because it is a separate copy of the movement name, score, grade and fixes (no video, no biometrics)."""

from __future__ import annotations

import json
import time
from typing import Any

import pytest

from auth_support import authenv, get, post, sign_in  # noqa: F401
from part7 import auth, identity, share
from support import Api
from test_share import GRACE, make_share, owned_job, share_body, store

pytestmark = pytest.mark.usefixtures("authenv")
NOW = 1_800_000_000.0


def clock(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    now = [NOW]
    monkeypatch.setattr(auth, "CLOCK", lambda: now[0])
    return now


def delete(api: Api, path: str, sid: str) -> tuple[int, Any]:
    status, _, data = api.request("DELETE", path, None, {"Origin": f"http://127.0.0.1:{api.port}", "Content-Type": "application/json", "Cookie": f"{auth.COOKIE}={sid}"})
    return status, (json.loads(data) if data else None)


def test_minting_returns_a_signed_shared_link_and_never_the_result_address(api: Api) -> None:
    sid = sign_in(api)
    job = owned_job(api, sid)
    status, _, doc = post(api, "api/shares", share_body(job), cookie=sid)
    assert status == 201 and doc["path"] == f"#/shared/{doc['token']}" and job not in json.dumps(doc)
    status, _, view = get(api, f"api/shared/{doc['token']}")  # signed out: no cookie
    assert status == 200 and (view["title"], view["score"], view["grade"]) == ("lateral-raise", 81, "B")
    assert get(api, f"api/jobs/{job}")[0] in (401, 404), "the result's own address stays closed to anyone but the owner"


@pytest.mark.parametrize("days", [1, 7, 30])
def test_each_duration_sets_the_expiry_to_the_day(api: Api, monkeypatch: pytest.MonkeyPatch, days: int) -> None:
    now = clock(monkeypatch)
    sid = sign_in(api)
    doc = post(api, "api/shares", share_body(owned_job(api, sid), days=days), cookie=sid)[2]
    assert doc["expires_utc"] == identity._iso(NOW + days * 86400)
    now[0] += days * 86400 - 1
    assert get(api, f"api/shared/{doc['token']}")[0] == 200
    now[0] += 2
    assert get(api, f"api/shared/{doc['token']}")[0] == 410


def test_cancel_makes_nothing_so_no_request_is_the_whole_of_cancel(api: Api) -> None:
    sid = sign_in(api)
    owned_job(api, sid)
    assert get(api, "api/me/shares", cookie=sid)[2] == {"shares": []}  # the prompt sends nothing until a duration is chosen
    assert post(api, "api/shares", share_body("abcdefabcdef", confirm=False), cookie=sid)[0] in (400, 404)
    assert get(api, "api/me/shares", cookie=sid)[2] == {"shares": []}


def test_an_expired_link_says_so_in_a_plain_line_not_not_found(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    now = clock(monkeypatch)
    sid = sign_in(api)
    token = make_share(api, sid, owned_job(api, sid), days=1)
    now[0] += 86400 + 5
    status, head, doc = get(api, f"api/shared/{token}")
    assert status == 410 and doc["message"] == "This link has expired." and doc["ended"] == "expired"
    assert "found" not in json.dumps(doc).lower() and head["x-robots-tag"] == "noindex"
    status, _, doc = get(api, f"api/shared/{token[:-1]}A")  # tampered: still the generic 404, so a guess learns nothing
    assert status == 404 and doc["message"] == "This link is not available."


def test_the_owner_stops_a_link_early_and_it_ends_on_the_next_request(api: Api) -> None:
    sid = sign_in(api)
    job = owned_job(api, sid)
    token = make_share(api, sid, job)
    row = get(api, "api/me/shares", cookie=sid)[2]["shares"][0]
    assert (row["item_ref"], row["state"], row["kind"]) == (job, "active", "take_result") and row["expires_utc"]
    assert delete(api, f"api/me/shares/{row['id']}", sid) == (200, {"revoked": True})
    status, _, doc = get(api, f"api/shared/{token}")
    assert status == 410 and doc["ended"] == "revoked" and "stopped" in doc["message"]
    assert get(api, "api/me/shares", cookie=sid)[2]["shares"][0]["state"] == "revoked"


def test_a_non_owner_cannot_mint_stop_or_see_anothers_link(api: Api) -> None:
    ada, grace = sign_in(api), sign_in(api, GRACE)
    job = owned_job(api, ada)
    token = make_share(api, ada, job)
    status, _, doc = post(api, "api/shares", share_body(job, days=30), cookie=grace)
    assert status == 404 and doc["message"] == "There is nothing here to share."
    assert len(store(api).fetch("SELECT 1 FROM shares")) == 1, "nothing was made for the non-owner"
    mine = get(api, "api/me/shares", cookie=ada)[2]["shares"][0]["id"]
    assert delete(api, f"api/me/shares/{mine}", grace)[0] == 404 and get(api, f"api/shared/{token}")[0] == 200
    assert get(api, "api/me/shares", cookie=grace)[2] == {"shares": []}


def test_minting_needs_a_session_and_a_same_origin_post(api: Api) -> None:
    sid = sign_in(api)
    job = owned_job(api, sid)
    assert post(api, "api/shares", share_body(job))[0] == 401
    assert post(api, "api/shares", share_body(job), cookie=sid, guard=False)[0] in (400, 403)
    assert not store(api).has_table("shares") or store(api).fetch("SELECT 1 FROM shares") == []


def test_minting_has_no_count_limit(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    clock(monkeypatch)
    sid = sign_in(api)
    job = owned_job(api, sid)
    for _ in range(30):  # past the old 10 an hour and 20 active
        make_share(api, sid, job)
    status, _, _doc = post(api, "api/shares", share_body(job), cookie=sid)
    assert status in (200, 201)


def test_a_deleted_take_and_deleted_data_end_the_link(api: Api) -> None:
    ada, grace = sign_in(api), sign_in(api, GRACE)
    job_a, job_b = owned_job(api, ada), owned_job(api, ada)
    taken, other, kept = make_share(api, ada, job_a), make_share(api, ada, job_b), make_share(api, grace, owned_job(api, grace))
    store(api).forget_job(job_a)  # the take is deleted
    assert get(api, f"api/shared/{taken}")[0] == 410 and get(api, f"api/shared/{other}")[0] == 200
    uid = store(api).session_user(ada)
    store(api).delete_user(uid)  # "Delete my data"
    assert get(api, f"api/shared/{other}")[0] == 404 and get(api, f"api/shared/{kept}")[0] == 200
    assert store(api).fetch("SELECT COUNT(*) FROM shares WHERE owner_id = ?", (uid,))[0][0] == 0


def test_the_shared_view_outlives_the_seven_day_result_sweep_and_ends_with_its_own_sweep(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    now = clock(monkeypatch)
    sid = sign_in(api)
    job = owned_job(api, sid)
    token = make_share(api, sid, job, days=30)
    api.app.queue.cleanup(now=time.time() + 8 * 86400)  # the real retention sweep of jobs: the result's folder is removed
    assert not api.app.queue.job_dir(job).exists()
    now[0] += 20 * 86400
    status, head, view = get(api, f"api/shared/{token}")
    assert status == 200 and view["score"] == 81 and view["faults"] and view["clip"] is None
    assert job not in json.dumps(view) and head["x-robots-tag"] == "noindex"
    now[0] += 11 * 86400 + 5  # past the 30 days, plus a day for the sweep
    assert get(api, f"api/shared/{token}")[0] == 410
    assert share.sweep(store(api)) == 1 and get(api, f"api/shared/{token}")[0] == 404
