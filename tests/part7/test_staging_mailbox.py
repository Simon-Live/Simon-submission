"""The staging test mailbox (TICKET-176, operator 2026-11-01): sign-in mail kept in the app for 30 minutes, listed only
for the exact address asked, enabled only on staging's own origin with SIMON7_MAIL_TRANSPORT=outbox."""

from __future__ import annotations

import logging
import re
from pathlib import Path

import pytest

from auth_support import EMAIL, authenv, get, post  # noqa: F401
from part7 import mail, staging_mailbox
from test_auth_origin import TUNNEL, provider_keys, root_api  # noqa: F401

OTHER = "grace.hopper@example.com"


@pytest.fixture()
def staged(authenv, monkeypatch: pytest.MonkeyPatch) -> Path:  # noqa: F811
    monkeypatch.setenv("STAGING_ROUTE", "root")
    monkeypatch.setenv("SIMON7_MAIL_TRANSPORT", "outbox")
    return authenv


def listing(api, email: str | None, headers: dict[str, str] | None = None):
    query = "" if email is None else f"?email={email}"
    return get(api, f"api/auth/outbox{query}", headers=headers or TUNNEL)


def test_outbox_is_chosen_only_on_the_own_origin(authenv, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    monkeypatch.setenv("SIMON7_MAIL_TRANSPORT", "outbox")
    assert mail.select_transport() == "file"  # local: the plain file outbox, never the staging mailbox
    for route in ("prefix", "strip"):
        monkeypatch.setenv("STAGING_ROUTE", route)
        assert mail.select_transport() == "off"
    monkeypatch.setenv("STAGING_ROUTE", "root")
    assert mail.select_transport() == "outbox" and not mail.file_refused_on_staging()
    provider_keys(authenv)
    assert mail.select_transport() == "outbox"  # the explicit setting wins over a provider
    monkeypatch.setenv("SIMON7_MAIL_TRANSPORT", "auto")
    assert mail.select_transport() == "api"  # "auto" hands the mail to the provider
    monkeypatch.setenv("SIMON7_MAIL_TRANSPORT", "off")
    assert mail.select_transport() == "off"


def test_sign_in_through_the_mailbox_end_to_end(staged, root_api) -> None:  # noqa: F811
    me = get(root_api, "api/auth/me")[2]
    assert me == {"available": True, "signed_in": False, "outbox": True}
    assert post(root_api, "api/auth/start", {"email": EMAIL}, TUNNEL)[0] == 202
    status, head, body = listing(root_api, EMAIL)
    assert status == 200 and head["cache-control"] == "no-store" and head["referrer-policy"] == "no-referrer"
    (msg,) = body["messages"]
    assert msg["to"] == EMAIL.lower() and re.fullmatch(r"\d{6}", msg["code"]) and msg["link"].startswith(f"https://{TUNNEL['Host']}/#/signin/")
    assert body["minutes"] == 30
    status, head, _ = post(root_api, "api/auth/verify", {"email": EMAIL, "code": msg["code"]}, TUNNEL)
    assert status == 200 and "Secure" in head["set-cookie"]
    token = msg["link"].rsplit("/", 1)[1]
    assert post(root_api, "api/auth/verify", {"token": token}, TUNNEL)[0] == 400  # the code used up the challenge


def test_two_addresses_each_see_only_their_own(staged, root_api) -> None:  # noqa: F811
    post(root_api, "api/auth/start", {"email": EMAIL}, TUNNEL)
    post(root_api, "api/auth/start", {"email": OTHER}, TUNNEL)
    mine, theirs = listing(root_api, EMAIL)[2]["messages"], listing(root_api, OTHER)[2]["messages"]
    assert [m["to"] for m in mine] == [EMAIL.lower()] and [m["to"] for m in theirs] == [OTHER]
    assert mine[0]["code"] != theirs[0]["code"] or mine[0]["link"] != theirs[0]["link"]
    assert listing(root_api, "nobody@example.com")[2]["messages"] == []
    assert listing(root_api, "ada.lovelace@example.co")[2]["messages"] == []  # the exact address, not a prefix of it


@pytest.mark.parametrize("email", [None, "", "not-an-address", "%20"])
def test_no_address_lists_nothing(staged, root_api, email) -> None:  # noqa: F811
    post(root_api, "api/auth/start", {"email": EMAIL}, TUNNEL)
    status, _, body = listing(root_api, email)
    assert status == 400 and "messages" not in body


def test_the_route_does_not_exist_unless_the_mailbox_is_on(authenv, root_api, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    assert listing(root_api, EMAIL, {})[0] == 404  # local file transport
    monkeypatch.setenv("STAGING_ROUTE", "prefix")
    monkeypatch.setenv("SIMON7_MAIL_TRANSPORT", "outbox")
    assert listing(root_api, EMAIL)[0] == 404  # the shared origin
    assert "outbox" not in get(root_api, "api/auth/me")[2]


def test_messages_expire_after_30_minutes_and_only_50_are_kept(tmp_path: Path) -> None:
    staging_mailbox.add(tmp_path, EMAIL, "111111", "https://x/#/signin/a", now=1000.0)
    assert staging_mailbox.messages_for(tmp_path, EMAIL, now=1000.0 + 1799)[0]["code"] == "111111"
    assert staging_mailbox.messages_for(tmp_path, EMAIL, now=1000.0 + 1800) == []
    for i in range(60):
        staging_mailbox.add(tmp_path, EMAIL, f"{i:06d}", "https://x/#/signin/b", now=5000.0 + i)
    rows = staging_mailbox.messages_for(tmp_path, EMAIL, now=5100.0)
    assert len(rows) == staging_mailbox.KEEP and rows[0]["code"] == "000059" and rows[-1]["code"] == "000010"  # newest first
    assert oct((tmp_path / "mailbox" / "messages.json").stat().st_mode & 0o777) == "0o600"
    assert staging_mailbox.messages_for(tmp_path, "") == []


def test_delete_my_data_removes_the_mailbox_messages_and_the_log_holds_nothing(staged, root_api, caplog: pytest.LogCaptureFixture) -> None:  # noqa: F811
    with caplog.at_level(logging.INFO, logger="part7"):
        post(root_api, "api/auth/start", {"email": EMAIL}, TUNNEL)
        (msg,) = listing(root_api, EMAIL)[2]["messages"]
    assert msg["code"] not in caplog.text and EMAIL.lower() not in caplog.text and "signin/" not in caplog.text
    assert staging_mailbox.purge(root_api.app.state, EMAIL) == 1
    assert listing(root_api, EMAIL)[2]["messages"] == []
