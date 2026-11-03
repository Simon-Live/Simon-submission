"""Profile and share links together over a real server (TICKET-231 + TICKET-233; attribution joins here)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from auth_support import authenv, get, origin, sign_in  # noqa: F401
from part7 import auth, identity, share
from support import Api
from test_share import make_share, owned_job

pytestmark = pytest.mark.usefixtures("authenv")
ADA, GRACE = "ada@example.com", "grace@example.com"


def send(api: Api, method: str, path: str, doc: Any, sid: str) -> tuple[int, Any]:
    hdr = {"Content-Type": "application/json", "Origin": origin(api), "Cookie": f"{auth.COOKIE}={sid}"}
    status, _, data = api.request(method, path, json.dumps(doc).encode(), hdr)
    return status, (json.loads(data) if data else None)


def set_profile(api: Api, sid: str, **doc: Any) -> None:
    assert send(api, "PUT", "api/me/profile", doc, sid)[0] == 200


def owner_shares(api: Api, sid: str) -> list[dict[str, Any]]:
    return get(api, "api/me/shares", cookie=sid)[2]["shares"]


def test_the_shared_page_shows_the_name_only_when_chosen_and_allowed_and_never_an_email(api: Api) -> None:
    sid = sign_in(api, ADA)
    job = owned_job(api, sid)
    set_profile(api, sid, public_name="Ada L", show_name=False)
    assert get(api, f"api/shared/{make_share(api, sid, job, show_name=True)}")[2]["author"] is None  # profile does not allow it
    set_profile(api, sid, show_name=True)
    named = get(api, f"api/shared/{make_share(api, sid, job, show_name=True)}")[2]
    unnamed = get(api, f"api/shared/{make_share(api, sid, job)}")[2]  # this share did not choose the name
    assert named["author"] == "Ada L" and unnamed["author"] is None
    for doc in (named, unnamed):
        assert "example.com" not in json.dumps(doc).lower()
    assert named["attribution"]["author"]["name"] == "Ada L" and named["attribution"]["mine"] is False  # TICKET-232 AC-6
    assert unnamed["attribution"]["author"] is None  # negative: the share did not choose the name


def test_profile_delete_ends_my_share_links_and_leaves_another_users(api: Api) -> None:
    ada, grace = sign_in(api, ADA), sign_in(api, GRACE)
    mine, theirs = make_share(api, ada, owned_job(api, ada)), make_share(api, grace, owned_job(api, grace))
    assert get(api, f"api/shared/{mine}")[0] == 200
    assert send(api, "DELETE", "api/me/profile", {}, ada)[0] == 200
    assert get(api, f"api/shared/{mine}")[0] == 404  # negative: the deleted profile's link is dead
    assert {s["state"] for s in owner_shares(api, ada)} == {"revoked"}
    assert get(api, f"api/shared/{theirs}")[0] == 200
    assert [s["state"] for s in owner_shares(api, grace)] == ["active"]


def test_the_export_carries_my_shares_and_sessions_without_tokens_hashes_or_other_users(api: Api) -> None:  # TICKET-236
    ada, grace = sign_in(api, ADA), sign_in(api, GRACE)
    mine = make_share(api, ada, owned_job(api, ada), show_name=True)
    theirs = make_share(api, grace, owned_job(api, grace))
    status, _, doc = get(api, "api/me/export", cookie=ada)
    assert status == 200
    [row] = doc["shares"]
    assert row["kind"] == "take_result" and row["includes"] == ["name"] and row["state"] == "active"
    assert len(doc["sessions"]) == 1 and set(doc["sessions"][0]) == {"device", "signed_in", "last_active"}
    text = json.dumps(doc)
    for secret in (mine, theirs, share.token_hash(mine), share.token_hash(theirs), ada, grace, "grace@example.com"):
        assert secret not in text  # negative: no token, hash, session id or other account
    assert get(api, "api/me/export", cookie=grace)[2]["shares"][0]["state"] == "active"
    assert send(api, "DELETE", f"api/me/shares/{share.token_hash(mine)}", {}, ada)[0] == 200
    assert get(api, "api/me/export", cookie=ada)[2]["shares"][0]["state"] == "revoked"


def test_revoke_all_is_per_owner_and_safe_without_the_table(api: Api) -> None:
    store = auth.identity(api.app)
    assert share.revoke_all(store, "u-none") == 0  # no shares table yet
    sid = sign_in(api, ADA)
    job = owned_job(api, sid)
    make_share(api, sid, job)
    assert share.revoke_all(store, "u-other") == 0
    assert share.revoke_all(store, identity.owner_of_job(api.app.state, job)) == 1
