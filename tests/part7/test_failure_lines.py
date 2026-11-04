"""Every 5xx and every browser failure is logged with a request id and a reason, without personal data (observability.md)."""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

import pytest

from part7 import applog, client_log, mail, selfheal
from support import Api


def _anomalies(caplog: pytest.LogCaptureFixture, kind: str) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.getMessage().startswith(f"ANOMALY {kind}")]


def test_every_answer_carries_a_request_id(api: Api) -> None:
    headers = api.request("GET", "api/version")[1]
    assert re.fullmatch(r"[0-9a-f]{12}", headers["x-request-id"])


def test_a_client_sent_id_is_not_trusted(api: Api) -> None:
    headers = api.request("GET", "api/version", headers={"X-Request-Id": "forged line"})[1]
    assert "forged" not in headers["x-request-id"]


def test_a_crash_is_logged_with_its_id_reason_and_route(api: Api, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(self: Any) -> None:
        raise ValueError("person@example.com broke it")

    handler = api.http.RequestHandlerClass
    monkeypatch.setattr(handler, "_health", boom)
    with caplog.at_level(logging.INFO, logger="part7"):
        status, headers, _ = api.request("GET", "api/health")
        deadline = time.monotonic() + 5  # the server writes the line after it has answered
        while not _anomalies(caplog, "http_5xx") and time.monotonic() < deadline:
            time.sleep(0.02)
    assert status == 500
    (line,) = _anomalies(caplog, "http_5xx")
    assert f"rid={headers['x-request-id']}" in line and "reason=" in line and "ValueError" in line
    assert 'route="GET api/health"' in line
    assert "person@example.com" not in caplog.text


def test_a_share_token_never_reaches_a_failure_line() -> None:
    assert applog.safe_path("api/shared/SECRET123/x?name=Jane") == "api/shared/<token>/x"
    assert applog.safe_path("/api/take-ar/SECRET123") == "/api/take-ar/<token>"


def test_a_browser_failure_gets_an_id_a_route_and_no_query(caplog: pytest.LogCaptureFixture) -> None:
    code, event = client_log.parse(json.dumps({"level": "error", "event": "client_error", "page": "#/x", "detail": {
        "source": "fetch", "status": 503, "path": "api/shared/TOKEN1/x?name=Jane", "message": "from person@example.com", "rid": "abc123abc123"}}).encode())
    assert code == 200
    fields = client_log.error_fields(event)
    assert fields["server_rid"] == "abc123abc123"
    assert "TOKEN1" not in fields["path"] and "Jane" not in fields["path"] and fields["route"].startswith("GET api/shared")
    with caplog.at_level(logging.INFO, logger="part7"):
        applog.anomaly("client_error", **fields)
    assert "person@example.com" not in caplog.text


def test_a_forged_server_id_is_dropped() -> None:
    _, event = client_log.parse(json.dumps({"level": "error", "event": "client_error", "page": "", "detail": {"rid": "x y\nz"}}).encode())
    assert "server_rid" not in client_log.error_fields(event)


def test_a_mail_that_did_not_leave_is_a_failure(caplog: pytest.LogCaptureFixture, tmp_path) -> None:  # type: ignore[no-untyped-def]
    selfheal.configure(tmp_path)
    with caplog.at_level(logging.INFO, logger="part7"):
        assert mail._smtp_send("ftp://bad", None) is False  # type: ignore[arg-type]
    assert _anomalies(caplog, "mail_failed")
    assert "mail_send" in selfheal.status(tmp_path)["open"]


def test_send_notice_now_reports_the_outcome(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    sender = mail.Mailer(tmp_path, transport="smtp")
    monkeypatch.setattr(mail, "_smtp_send", lambda url, msg: str(msg["Subject"]) == "S")
    monkeypatch.setattr(sender, "_sender", lambda: "a@b.c")
    assert sender.send_notice_now("x@y.z", "S", "T") is True
    assert sender.send_notice_now("x@y.z", "other", "T") is False
    assert mail.Mailer(tmp_path, transport="file").send_notice_now("x@y.z", "S", "T") is False
