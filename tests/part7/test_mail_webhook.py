"""The Resend webhook: Svix-style signature, bounce and complaint handling, suppression of notices and invites."""

from __future__ import annotations

import base64
import json
import logging
import time
from pathlib import Path
from typing import Any

import pytest

from auth_support import authenv, get, post  # noqa: F401
from part7 import mail, mail_suppress, mail_webhook
from support import Api

SECRET_B64 = "MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSw"  # the example signing secret of the Svix documentation
KEY = base64.b64decode(SECRET_B64)
ADDRESS = "bounced.person@example.com"
ROUTE = "api/auth/mail-webhook"


def test_the_documented_vector_verifies() -> None:
    # The values on https://resend.com/docs/webhooks/verify-webhooks-requests (Svix manual example).
    body, stamp = b'{"test": 2432232314}', "1614265330"
    header = "v1,g0hM9SsE+OTPJTGt/tmIKtSyZlE3uFJELVlNIOLJ1OE="
    assert mail_webhook.verify(KEY, "msg_p5jXN8AQM9LWM0D4loKWxJek", stamp, header, body, now=1614265330 + 10)
    assert not mail_webhook.verify(KEY, "msg_p5jXN8AQM9LWM0D4loKWxJek", stamp, header, body + b" ", now=1614265340)  # one byte changed
    assert not mail_webhook.verify(KEY, "msg_other", stamp, header, body, now=1614265340)
    assert not mail_webhook.verify(KEY, "msg_p5jXN8AQM9LWM0D4loKWxJek", stamp, header, body, now=1614265330 + 301)  # replay
    assert not mail_webhook.verify(KEY, "msg_p5jXN8AQM9LWM0D4loKWxJek", "not-a-number", header, body, now=1614265340)
    assert mail_webhook.verify(KEY, "msg_p5jXN8AQM9LWM0D4loKWxJek", stamp, "v1,AAAA " + header, body, now=1614265340)  # a list: any entry


def signed(event: str, to: Any, **data: Any) -> tuple[bytes, dict[str, str]]:
    body = json.dumps({"type": event, "created_at": "2026-11-03T10:00:00Z", "data": {"email_id": "56761188-7520", "to": to, **data}}).encode()
    stamp = str(int(time.time()))
    return body, {"svix-id": "msg_abc123", "svix-timestamp": stamp, "svix-signature": mail_webhook.sign(KEY, "msg_abc123", stamp, body),
                  "Content-Type": "application/json"}


def send(api: Api, body: bytes, headers: dict[str, str]) -> tuple[int, Any]:
    status, _, data = api.request("POST", ROUTE, body, headers)
    return status, (json.loads(data) if data else None)


def enable(authenv: Path) -> None:
    (authenv / "SIMON7_RESEND_WEBHOOK_SECRET").write_text("whsec_" + SECRET_B64 + "\n")


def test_without_the_secret_file_the_route_is_off_and_status_says_so(api: Api, authenv: Path) -> None:
    body, headers = signed("email.bounced", [ADDRESS])
    assert send(api, body, headers)[0] == 404
    assert mail_webhook.status()["state"] == "off" and "SIMON7_RESEND_WEBHOOK_SECRET" in mail_webhook.status()["why"]
    assert not mail_suppress.is_suppressed(api.app.state, ADDRESS)
    enable(authenv)
    assert mail_webhook.status() == {"state": "on", "route": ROUTE}
    (authenv / "SIMON7_RESEND_WEBHOOK_SECRET").write_text("whsec_not base64 !!\n")
    assert mail_webhook.status()["state"] == "off" and send(api, body, headers)[0] == 404


def test_a_bad_or_missing_signature_changes_nothing(api: Api, authenv: Path, caplog: pytest.LogCaptureFixture) -> None:
    enable(authenv)
    body, headers = signed("email.bounced", [ADDRESS])
    with caplog.at_level(logging.INFO, logger="part7"):
        assert send(api, body, {**headers, "svix-signature": "v1,AAAAAAAA"})[0] == 400
        assert send(api, body, {k: v for k, v in headers.items() if k != "svix-signature"})[0] == 400
        assert send(api, body.replace(b"bounced", b"forged"), headers)[0] == 400
        assert send(api, b"", headers)[0] == 400
        assert send(api, b"x" * (mail_webhook.BODY_MAX + 1), headers)[0] == 413
    assert not mail_suppress.is_suppressed(api.app.state, ADDRESS) and "signature refused" in caplog.text and ADDRESS not in caplog.text


def test_a_hard_bounce_suppresses_logs_an_anomaly_and_no_address(api: Api, authenv: Path, caplog: pytest.LogCaptureFixture) -> None:
    enable(authenv)
    body, headers = signed("email.bounced", [ADDRESS.upper()], bounce={"type": "Permanent", "subType": "General", "message": f"no {ADDRESS}"})
    with caplog.at_level(logging.INFO, logger="part7"):
        assert send(api, body, headers) == (200, {"ok": True})
    assert mail_suppress.is_suppressed(api.app.state, ADDRESS)
    line = next(r.getMessage() for r in caplog.records if "ANOMALY mail_bounced" in r.getMessage())
    key = api.app.state and __import__("part7").auth.state(api.app).mailer.keyer(ADDRESS)
    assert f"to={key}" in line and "email_id=56761188-7520" in line and "blocked=yes" in line
    assert ADDRESS not in caplog.text and ADDRESS.upper() not in caplog.text
    stored = (api.app.state / mail_suppress.FILE).read_text()
    assert ADDRESS not in stored and mail_suppress.digest(ADDRESS) in stored
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="part7"):
        assert send(api, *signed("email.bounced", [ADDRESS], bounce={"type": "Permanent"}))[0] == 200
    assert "ANOMALY mail_bounced" not in caplog.text  # already blocked: no second anomaly


def test_a_complaint_suppresses_and_a_soft_bounce_does_not(api: Api, authenv: Path, caplog: pytest.LogCaptureFixture) -> None:
    enable(authenv)
    with caplog.at_level(logging.INFO, logger="part7"):
        assert send(api, *signed("email.bounced", ["soft@example.com"], bounce={"type": "Transient", "subType": "MailboxFull"}))[0] == 200
        assert send(api, *signed("email.complained", ["angry@example.com"]))[0] == 200
        assert send(api, *signed("email.suppressed", ["resend.held@example.com"]))[0] == 200
    state = api.app.state
    assert not mail_suppress.is_suppressed(state, "soft@example.com") and "blocked=no" in caplog.text
    assert mail_suppress.is_suppressed(state, "angry@example.com") and "ANOMALY mail_complaint" in caplog.text
    assert mail_suppress.is_suppressed(state, "resend.held@example.com") and "ANOMALY mail_suppressed" in caplog.text


def test_other_events_are_acknowledged_and_ignored(api: Api, authenv: Path) -> None:
    enable(authenv)
    for event in ("email.delivered", "email.opened", "domain.updated"):
        assert send(api, *signed(event, [ADDRESS]))[0] == 200
    assert mail_suppress.count(api.app.state) == 0
    assert send(api, *signed("email.bounced", "not-a-list-and-no-at"))[0] == 200 and mail_suppress.count(api.app.state) == 0


def test_a_suppressed_address_gets_no_notice_or_invite_but_still_gets_a_sign_in_code(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[Any] = []
    monkeypatch.setattr(mail, "_smtp_send", lambda url, msg: sent.append((msg["To"], msg.kind)) or True)
    monkeypatch.setattr(mail, "smtp_url", lambda keys_dir=None: "smtp://x.example.test")
    sender = mail.Mailer(tmp_path, transport="smtp")
    mail_suppress.add(tmp_path, ADDRESS, "email.bounced")
    sender.send_notice(ADDRESS.upper(), "Invited", "Open the board.", kind="invite")
    sender.send_notice(ADDRESS, "Token saved", "Ending 1234.")
    sender.send_notice("other@example.com", "Invited", "Open the board.", kind="invite")
    sender.send_sign_in(ADDRESS, "123456", "https://x/#/signin/t")
    mail.drain(2.0)
    assert sorted(sent) == [(ADDRESS, "sign_in"), ("other@example.com", "invite")]


def test_the_key_file_is_one_prod_reads_and_the_how_to_names_the_clicks() -> None:
    from part7 import keys

    assert "SIMON7_RESEND_WEBHOOK_SECRET" in keys.PROD_KEYS and "SIMON7_RESEND_WEBHOOK_SECRET" in keys.KEY_NAMES
    spec = (Path(__file__).resolve().parents[2] / "docs/specs/mail-delivery.md").read_text(encoding="utf-8")
    for click in ("Webhooks", "Add Webhook", "email.bounced", "email.complained", "Signing Secret", "/api/auth/mail-webhook"):
        assert click in spec
