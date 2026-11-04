"""Mail audit fixes: what the log says, headers, the retry, the drain and the sign-in status (docs/specs/mail-delivery.md).

Providers are faked at the smtplib seam; `test_mail_smtp_real.py` talks to a real local SMTP server.
"""

from __future__ import annotations

import logging
import smtplib
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from auth_support import authenv, get, post  # noqa: F401
from part7 import mail, mail_status
from support import Api

ADDRESS = "ada.lovelace@example.com"


@pytest.fixture(autouse=True)
def quick_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mail, "RETRY_DELAY_S", 0.01)


def message(kind: str = "sign_in") -> Any:
    msg = mail.build_message(ADDRESS, "Simon <signin@simon.live>", "123456", "https://x/#/signin/t", datetime.now(timezone.utc))
    msg.kind, msg.rcpt_key = kind, "abc123def456"
    return msg


class FakeSMTP:
    """Scripted smtplib.SMTP: `script` holds one outcome per connection: an exception to raise or a DATA reply."""

    script: list[Any] = []
    connections = 0

    def __init__(self, host: str, port: int, timeout: int) -> None:
        type(self).connections += 1
        self.step = type(self).script.pop(0) if type(self).script else b"250 Ok 0123456789abcdef-0123"

    def __enter__(self) -> "FakeSMTP":
        return self

    def __exit__(self, *a: object) -> None: ...

    def starttls(self, context: object) -> None: ...

    def login(self, user: str, password: str) -> None: ...

    def data(self, body: Any) -> tuple[int, bytes]:
        return 250, self.step

    def send_message(self, msg: Any) -> None:
        if isinstance(self.step, BaseException):
            raise self.step
        self.data(msg)


@pytest.fixture()
def smtp(monkeypatch: pytest.MonkeyPatch) -> type[FakeSMTP]:
    FakeSMTP.script, FakeSMTP.connections = [], 0
    monkeypatch.setattr(mail.smtplib, "SMTP", FakeSMTP)
    return FakeSMTP


def test_sent_line_says_handed_over_with_kind_key_and_provider_id(smtp, caplog: pytest.LogCaptureFixture) -> None:
    smtp.script = [b"250 Ok 49a1c0de-1234-4abc-9def-0123456789ab"]
    with caplog.at_level(logging.INFO, logger="part7"):
        assert mail._smtp_send("smtp://u:p@smtp.example.test:587", message()) is True
    line = next(r.getMessage() for r in caplog.records if "handed to provider" in r.getMessage())
    assert line == "auth: mail handed to provider kind=sign_in to=abc123def456 id=49a1c0de-1234-4abc-9def-0123456789ab"
    assert "mail sent" not in caplog.text and ADDRESS not in caplog.text and "example.com" not in caplog.text


def test_a_reply_without_a_long_word_is_logged_trimmed(smtp, caplog: pytest.LogCaptureFixture) -> None:
    smtp.script = [b"250 queued"]
    with caplog.at_level(logging.INFO, logger="part7"):
        mail._smtp_send("smtp://smtp.example.test", message("invite"))
    assert "kind=invite to=abc123def456 id=250 queued" in caplog.text


def test_mailer_keys_the_recipient_and_never_logs_the_address(tmp_path: Path, smtp, caplog: pytest.LogCaptureFixture) -> None:
    sender = mail.Mailer(tmp_path, transport="smtp")
    sender.keyer = lambda address: "k" + str(len(address))
    msg = sender._tag(sender._notice_message(ADDRESS, "S", "T"), "invite", ADDRESS)
    with caplog.at_level(logging.INFO, logger="part7"):
        assert mail._smtp_send("smtp://smtp.example.test", msg) is True
    assert f"kind=invite to=k{len(ADDRESS)}" in caplog.text and ADDRESS not in caplog.text


def test_headers_date_message_id_and_reply_to(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(mail, "is_prod", lambda: False)
    plain = message()
    assert plain["Date"] and plain["Message-ID"].endswith("@simon.live>") and plain["Reply-To"] is None
    assert plain["Message-ID"] != message()["Message-ID"]
    monkeypatch.setattr(mail, "is_prod", lambda: True)
    monkeypatch.setenv("SIMON7_PROD_HOSTS", "www.simon.live,other.example")
    assert message()["Reply-To"] == "support@simon.live"
    note = mail.Mailer(tmp_path, transport="smtp")._notice_message(ADDRESS, "S", "T")
    assert note["Date"] and note["Message-ID"] and note["Reply-To"] == "support@simon.live"


def test_support_is_a_registered_inbound_address() -> None:
    block = (Path(__file__).resolve().parents[2] / "docs/prod/registry-block.yaml").read_text(encoding="utf-8")
    assert "inbound: [privacy, support, hello]" in block  # the Reply-To address exists


def test_a_transient_failure_is_tried_once_more(smtp, caplog: pytest.LogCaptureFixture) -> None:
    smtp.script = [smtplib.SMTPServerDisconnected("gone"), b"250 Ok aaaaaaaaaaaaaaaa1111"]
    assert mail._smtp_send("smtp://smtp.example.test", message()) is True and smtp.connections == 2


def test_a_4xx_is_retried_and_a_second_failure_raises_one_anomaly(smtp, caplog: pytest.LogCaptureFixture) -> None:
    busy = smtplib.SMTPDataError(451, b"try later")
    smtp.script = [busy, busy]
    with caplog.at_level(logging.INFO, logger="part7"):
        assert mail._smtp_send("smtp://smtp.example.test", message()) is False
    assert smtp.connections == 2 and caplog.text.count("ANOMALY mail_failed") == 1 and "SMTPDataError 451" in caplog.text


@pytest.mark.parametrize("exc", [smtplib.SMTPDataError(550, b"no such user"), smtplib.SMTPAuthenticationError(535, b"bad login"),
                                 smtplib.SMTPNotSupportedError("no tls"), __import__("ssl").SSLCertVerificationError("bad cert")])
def test_a_permanent_failure_is_not_retried(smtp, exc: Exception) -> None:
    smtp.script = [exc]
    assert mail._smtp_send("smtp://smtp.example.test", message()) is False and smtp.connections == 1


def test_a_refused_connection_is_retried(smtp) -> None:
    smtp.script = [ConnectionRefusedError("down"), ConnectionRefusedError("down")]
    assert mail._smtp_send("smtp://smtp.example.test", message()) is False and smtp.connections == 2


def test_api_retries_a_429_and_a_5xx_but_not_a_403(monkeypatch: pytest.MonkeyPatch) -> None:
    import io
    from urllib import error as urlerror

    codes: list[int] = []

    def fake(req: Any, timeout: int) -> Any:
        codes.append(len(codes))
        raise urlerror.HTTPError(req.full_url, answers.pop(0), "x", {}, io.BytesIO(b""))

    monkeypatch.setattr(mail.urlrequest, "urlopen", fake)
    answers = [429, 503]
    assert mail._api_send(mail.DEFAULT_API_URL, "k", message()) is False and len(codes) == 2
    codes.clear()
    answers = [403, 403]
    assert mail._api_send(mail.DEFAULT_API_URL, "k", message()) is False and len(codes) == 1


def test_drain_waits_for_a_mail_in_flight(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    release, finished = threading.Event(), []
    monkeypatch.setattr(mail, "_smtp_send", lambda url, msg: release.wait(5) and finished.append(1) or True)
    sender = mail.Mailer(tmp_path, transport="smtp")
    monkeypatch.setattr(mail, "smtp_url", lambda keys_dir=None: "smtp://x.example.test")
    sender.send_sign_in(ADDRESS, "123456", "https://x/#/signin/t", "0123456789abcdef")
    assert sender.board.get("0123456789abcdef") == "pending"
    threading.Timer(0.1, release.set).start()
    assert mail.drain(5.0) == 0 and finished == [1]
    assert sender.board.get("0123456789abcdef") == "sent"


def test_drain_reports_what_it_cut_off(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    release = threading.Event()
    monkeypatch.setattr(mail, "_smtp_send", lambda url, msg: release.wait(5))
    monkeypatch.setattr(mail, "smtp_url", lambda keys_dir=None: "smtp://x.example.test")
    mail.Mailer(tmp_path, transport="smtp").send_sign_in(ADDRESS, "123456", "https://x/#/signin/t")
    with caplog.at_level(logging.INFO, logger="part7"):
        assert mail.drain(0.05) == 1
    release.set()
    assert "ANOMALY drain_cut_off" in caplog.text and "kind=mail" in caplog.text
    mail.drain(2.0)


# ----- the sign-in status the code screen asks ------------------------------------------------------
def provider_api(authenv: Path, monkeypatch: pytest.MonkeyPatch, result: Any) -> None:
    (authenv / "SIMON7_SMTP_URL").write_text("smtps://u:p@smtp.example.test:465\n")
    (authenv / "SIMON7_MAIL_FROM").write_text("Simon <signin@example.test>\n")
    monkeypatch.setattr(mail, "_smtp_send", result)


def wait_status(api: Api, attempt: str, want: str) -> str:
    for _ in range(100):
        got = get(api, f"api/auth/mail-status?id={attempt}")[2]["status"]
        if got == want:
            return got
        time.sleep(0.02)
    return got


def test_start_answers_at_once_and_the_status_turns_failed(api: Api, authenv: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    gate = threading.Event()
    provider_api(authenv, monkeypatch, lambda url, msg: gate.wait(5) and False)
    status, _, body = post(api, "api/auth/start", {"email": ADDRESS})
    assert status == 202 and body["ok"] is True
    attempt = body["attempt"]
    assert get(api, f"api/auth/mail-status?id={attempt}")[2] == {"status": "pending"}
    gate.set()
    assert wait_status(api, attempt, "failed") == "failed"


def test_status_turns_sent_when_the_provider_takes_the_mail(api: Api, authenv: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    provider_api(authenv, monkeypatch, lambda url, msg: True)
    attempt = post(api, "api/auth/start", {"email": ADDRESS})[2]["attempt"]
    assert wait_status(api, attempt, "sent") == "sent"
    status, head, _ = get(api, f"api/auth/mail-status?id={attempt}")
    assert status == 200 and head["cache-control"] == "no-store"


def test_a_limited_address_reads_the_same_sent_as_any_other(api: Api, authenv: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    provider_api(authenv, monkeypatch, lambda url, msg: False)
    for _ in range(5):
        post(api, "api/auth/start", {"email": ADDRESS})
    attempt = post(api, "api/auth/start", {"email": ADDRESS})[2]["attempt"]  # the 6th: no mail goes
    assert get(api, f"api/auth/mail-status?id={attempt}")[2] == {"status": "sent"}


def test_unknown_or_malformed_ids_read_unknown_and_nothing_else(api: Api, authenv: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    provider_api(authenv, monkeypatch, lambda url, msg: True)
    for bad in ("0" * 16, "not-an-id", "", "../etc"):
        assert get(api, f"api/auth/mail-status?id={bad}")[2] == {"status": "unknown"}
    assert get(api, "api/auth/mail-status")[2] == {"status": "unknown"}


def test_status_is_404_when_sign_in_is_off(api: Api, authenv: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIMON7_MAIL_TRANSPORT", "off")
    assert get(api, "api/auth/mail-status?id=" + "0" * 16)[0] == 404


def test_the_board_expires_and_caps() -> None:
    now = [0.0]
    board = mail_status.AttemptBoard(clock=lambda: now[0])
    board.set("a" * 16, "sent")
    now[0] = mail_status.TTL_S + 1
    assert board.get("a" * 16) == "unknown"
    for n in range(mail_status.CAP + 5):
        board.set(f"{n:016x}", "sent")
    assert board.get(f"{0:016x}") == "unknown" and board.get(f"{mail_status.CAP + 4:016x}") == "sent"


# ----- the global limit is an anomaly ------------------------------------------------------------------
def test_the_global_limit_raises_an_anomaly_and_the_address_limit_does_not(api: Api, authenv: Path, monkeypatch: pytest.MonkeyPatch,
                                                                         caplog: pytest.LogCaptureFixture) -> None:
    provider_api(authenv, monkeypatch, lambda url, msg: True)
    monkeypatch.setattr("part7.identity.GLOBAL_MAILS_PER_HOUR", 2)
    with caplog.at_level(logging.INFO, logger="part7"):
        for n in range(2):
            post(api, "api/auth/start", {"email": f"p{n}@example.com"}, {"Cf-Connecting-Ip": f"198.51.100.{n}"})
        assert "ANOMALY signin_global_limited" not in caplog.text
        status, _, body = post(api, "api/auth/start", {"email": "p9@example.com"}, {"Cf-Connecting-Ip": "198.51.100.9"})
    assert status == 202 and body["ok"] is True and "ANOMALY signin_global_limited" in caplog.text
    assert "p9@example.com" not in caplog.text
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="part7"):
        monkeypatch.setattr("part7.identity.GLOBAL_MAILS_PER_HOUR", 200)
        for _ in range(6):
            post(api, "api/auth/start", {"email": "q@example.com"}, {"Cf-Connecting-Ip": "198.51.100.77"})
    assert "sign-in limited" in caplog.text and "ANOMALY signin_global_limited" not in caplog.text


# ----- staging parity: the mailbox keeps every kind ---------------------------------------------------------
def test_the_staging_mailbox_keeps_notices_and_invites_not_only_codes(tmp_path: Path) -> None:
    from part7 import staging_mailbox

    sender = mail.Mailer(tmp_path, transport="outbox")
    sender.send_sign_in(ADDRESS, "123456", "https://x/#/signin/t", "0123456789abcdef")
    sender.send_notice(ADDRESS, "A Modal token was saved", "Token ending 1234.")
    sender.send_notice(ADDRESS, "You were invited", "Open the board.", kind="invite")
    rows = staging_mailbox.messages_for(tmp_path, ADDRESS)
    assert [r["kind"] for r in rows] == ["invite", "notice", "sign_in"]
    assert rows[0]["subject"] == "You were invited" and rows[0]["body"] == "Open the board." and rows[2]["code"] == "123456"
    assert sender.board.get("0123456789abcdef") == "sent"
    assert mail.Mailer(tmp_path, transport="outbox").send_notice_now(ADDRESS, "S", "T") is False  # an operator notice is never "delivered" here
