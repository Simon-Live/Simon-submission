"""Operator notices never carry personal data or a secret, and a failure rate raises one (observability.md)."""

from __future__ import annotations

import logging
from pathlib import Path
import time
from typing import Any

import pytest

from part7 import applog, keys, mail, ops_notice


@pytest.fixture
def outbox(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    sent: list[dict[str, Any]] = []

    class _Mailer:
        def __init__(self, state: Path) -> None:
            pass

        def send_notice_now(self, to: str, subject: str, text: str) -> bool:
            sent.append({"to": to, "subject": subject, "text": text})
            return True

    monkeypatch.setattr(mail, "Mailer", _Mailer)
    monkeypatch.setattr(mail, "is_prod", lambda: True)
    ops_notice.reset()
    return sent


LEAKS = {
    "mail address": "person.name+tag@example.co.uk",
    "account id": "u-0123456789abcdef01234567",
    "movement name": "jane-doe-solo-1a2b3c4d",
    "share token": "/api/shared/Zm9vYmFyYmF6cXV4",
    "take token": "/api/take-ar/Zm9vYmFyYmF6cXV4",
    "query string": "/api/x?name=Jane",
    "smtp url": "smtps://resend:re_abcdef@smtp.resend.com:465",
    "labelled secret": "password=hunter2",
    "bearer": "Authorization: Bearer abc.def",
    "long token": "A" * 40,
    "ip address": "203.0.113.9",
}
SECRET_PART = {"mail address": "person.name", "account id": "0123456789abcdef01234567", "movement name": "jane-doe",
               "share token": "Zm9vYmFyYmF6cXV4", "take token": "Zm9vYmFyYmF6cXV4", "query string": "Jane",
               "smtp url": "re_abcdef", "labelled secret": "hunter2", "bearer": "abc.def", "long token": "AAAA",
               "ip address": "203.0.113.9"}


@pytest.mark.parametrize("what", sorted(LEAKS))
def test_no_notice_field_can_carry_it(what: str, tmp_path: Path, outbox: list[dict[str, Any]]) -> None:
    assert ops_notice.send(f"Fault {LEAKS[what]} seen", f"Detail: {LEAKS[what]} end.", tmp_path) is True
    assert SECRET_PART[what] not in outbox[0]["subject"] and SECRET_PART[what] not in outbox[0]["text"]


def test_a_key_value_never_leaves(tmp_path: Path, outbox: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(keys, "redact", lambda text, keys_dir=None: text.replace("s3cr3tv4lue", "<redacted>"))
    ops_notice.send("A s3cr3tv4lue", "B s3cr3tv4lue", tmp_path)
    assert "s3cr3tv4lue" not in str(outbox[0])


def test_a_notice_is_bounded_and_goes_to_the_forward(tmp_path: Path, outbox: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SIMON7_OPS_NOTICE_TO", raising=False)
    monkeypatch.setenv("SIMON7_PROD_HOSTS", "www.simon.live,simon.live")
    ops_notice.send("s" * 500, "word " * 1000, tmp_path)
    assert outbox[0]["to"] == "hello@simon.live"
    assert len(outbox[0]["subject"]) < 140 and len(outbox[0]["text"]) <= ops_notice.BODY_MAX


def test_the_address_is_not_logged(tmp_path: Path, outbox: list[dict[str, Any]], caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="part7"):
        ops_notice.send("Subject", "Body", tmp_path)
    assert "NOTICE sent: Subject" in caplog.text and "hello@" not in caplog.text


def test_outside_prod_nothing_is_mailed(tmp_path: Path, outbox: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mail, "is_prod", lambda: False)
    assert ops_notice.send("Subject", "Body", tmp_path) is False and outbox == []


def _flood(state: Path, n: int, now: float) -> int:
    return sum(ops_notice.note_failure("GET api/x", state, now=now + i) for i in range(n))


def test_a_failure_rate_raises_one_notice_not_one_per_event(tmp_path: Path, outbox: list[dict[str, Any]]) -> None:
    now = time.time()
    assert _flood(tmp_path, ops_notice.THRESHOLD - 1, now) == 0
    assert _flood(tmp_path, 100, now + 20) == 1
    deadline = time.time() + 5
    while not outbox and time.time() < deadline:
        time.sleep(0.01)
    assert len(outbox) == 1 and "GET api/x" in outbox[0]["text"]


def test_a_restart_does_not_send_a_second_one(tmp_path: Path, outbox: list[dict[str, Any]]) -> None:
    now = time.time()
    assert _flood(tmp_path, ops_notice.THRESHOLD, now) == 1
    ops_notice.reset()  # a new process: only the file remembers
    assert _flood(tmp_path, ops_notice.THRESHOLD, now + 60) == 0
    ops_notice.reset()
    assert _flood(tmp_path, ops_notice.THRESHOLD, now + ops_notice.COOLDOWN_S + 60) == 1


def test_an_old_failure_leaves_the_window(tmp_path: Path, outbox: list[dict[str, Any]]) -> None:
    now = time.time()
    for i in range(ops_notice.THRESHOLD - 1):
        assert ops_notice.note_failure("r", tmp_path, now=now + i * 300) is False


def test_notice_cli_needs_a_subject(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PROD_NOTICE_SUBJECT", raising=False)
    assert ops_notice.cli_notice(tmp_path) == 2


def test_scrub_removes_a_mail_address_from_every_log_line() -> None:
    assert applog.scrub("a person@example.com b") == "a <mail> b"


def test_the_notice_cli_mails_and_records_it_in_the_log(tmp_path: Path, outbox: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROD_NOTICE_SUBJECT", "Prod is failing")
    monkeypatch.setenv("PROD_NOTICE_BODY", "Reported by person@example.com")
    assert ops_notice.cli_notice(tmp_path) == 0
    assert "person@example.com" not in str(outbox[0])
    assert "NOTICE sent: Prod is failing" in (tmp_path / "part7.log").read_text(encoding="utf-8")
