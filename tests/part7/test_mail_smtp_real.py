"""The SMTP path against a real local SMTP server: STARTTLS, implicit TLS, a refusal, an untrusted certificate.

No provider and no real mail: the server is `smtp_server.SmtpServer` on 127.0.0.1 (docs/specs/mail-delivery.md).
"""

from __future__ import annotations

import email
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import pytest

from part7 import mail
from smtp_server import SmtpServer

ADDRESS = "ada.lovelace@example.com"


@pytest.fixture(autouse=True)
def quick(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mail, "RETRY_DELAY_S", 0.01)


@pytest.fixture()
def server_factory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    made: list[SmtpServer] = []

    def make(**kw: Any) -> SmtpServer:
        folder = tmp_path / f"srv{len(made)}"
        folder.mkdir()
        srv = SmtpServer(folder, **kw)
        monkeypatch.setenv("SSL_CERT_FILE", str(srv.cert))  # the client trusts this one certificate and no other
        made.append(srv)
        return srv

    yield make
    for srv in made:
        srv.close()


def a_message(kind: str = "sign_in") -> Any:
    msg = mail.build_message(ADDRESS, "Simon <signin@simon.live>", "123456", "https://x/#/signin/t", datetime.now(timezone.utc))
    msg.kind, msg.rcpt_key = kind, "feedfacecafe"
    return msg


def test_starttls_login_and_the_message_reach_the_server(server_factory, caplog: pytest.LogCaptureFixture) -> None:
    srv = server_factory(mode="starttls", reply_id="queued-as-49a1c0de12345678")
    with caplog.at_level(logging.INFO, logger="part7"):
        assert mail._smtp_send(f"smtp://user:p%40ss@localhost:{srv.port}", a_message()) is True
    (session,) = srv.sessions
    assert session["tls"] is True and session["auth"] == ("user", "p@ss")
    assert "AUTH" not in session["clear_commands"] and "MAIL" not in session["clear_commands"]  # nothing but EHLO and STARTTLS in the clear
    parsed = email.message_from_bytes(session["data"])
    assert parsed["To"] == ADDRESS and parsed["Date"] and parsed["Message-ID"].endswith("@simon.live>")
    assert "kind=sign_in to=feedfacecafe id=queued-as-49a1c0de12345678" in caplog.text and ADDRESS not in caplog.text


def test_implicit_tls_sends(server_factory) -> None:
    srv = server_factory(mode="implicit")
    assert mail._smtp_send(f"smtps://user:pw@localhost:{srv.port}", a_message()) is True
    assert srv.sessions[0]["tls"] is True and srv.sessions[0]["data"]


def test_a_server_without_starttls_gets_nothing(server_factory, caplog: pytest.LogCaptureFixture) -> None:
    srv = server_factory(mode="plain")
    with caplog.at_level(logging.INFO, logger="part7"):
        assert mail._smtp_send(f"smtp://user:pw@localhost:{srv.port}", a_message()) is False
    assert len(srv.sessions) == 1 and srv.sessions[0]["data"] is None and srv.sessions[0]["auth"] is None  # not retried, nothing in the clear
    assert caplog.text.count("ANOMALY mail_failed") == 1 and "SMTPNotSupportedError" in caplog.text


def test_a_permanent_refusal_is_one_try_and_one_anomaly(server_factory, caplog: pytest.LogCaptureFixture) -> None:
    srv = server_factory(rcpt_code=550)
    with caplog.at_level(logging.INFO, logger="part7"):
        assert mail._smtp_send(f"smtp://u:p@localhost:{srv.port}", a_message()) is False
    assert len(srv.sessions) == 1 and caplog.text.count("ANOMALY mail_failed") == 1
    assert "SMTPRecipientsRefused 550" not in caplog.text and "SMTPRecipientsRefused" in caplog.text and ADDRESS not in caplog.text


def test_a_temporary_refusal_is_tried_twice(server_factory, caplog: pytest.LogCaptureFixture) -> None:
    srv = server_factory(data_code=451)
    with caplog.at_level(logging.INFO, logger="part7"):
        assert mail._smtp_send(f"smtp://u:p@localhost:{srv.port}", a_message()) is False
    assert len(srv.sessions) == 2 and caplog.text.count("ANOMALY mail_failed") == 1 and "SMTPDataError 451" in caplog.text


def test_an_untrusted_certificate_is_refused_without_a_retry(server_factory, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    srv = server_factory(mode="starttls")
    other = SmtpServer(tmp_path, mode="starttls")  # a second certificate: the client trusts only `other`
    try:
        monkeypatch.setenv("SSL_CERT_FILE", str(other.cert))
        assert mail._smtp_send(f"smtp://u:p@localhost:{srv.port}", a_message()) is False
        assert len(srv.sessions) == 1 and srv.sessions[0]["data"] is None
    finally:
        other.close()


def test_the_mailer_thread_sends_through_the_server_and_the_board_says_sent(server_factory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    srv = server_factory()
    keys = tmp_path / "keys"
    keys.mkdir()
    (keys / "SIMON7_SMTP_URL").write_text(f"smtp://u:p@localhost:{srv.port}\n")
    (keys / "SIMON7_MAIL_FROM").write_text("Simon <signin@simon.live>\n")
    sender = mail.Mailer(tmp_path, keys_dir=keys)
    assert sender.transport == "smtp"
    sender.send_sign_in(ADDRESS, "654321", "https://x/#/signin/t", "0123456789abcdef")
    for _ in range(200):
        if sender.board.get("0123456789abcdef") != "pending":
            break
        time.sleep(0.02)
    assert sender.board.get("0123456789abcdef") == "sent" and b"654321" in srv.sessions[0]["data"]
