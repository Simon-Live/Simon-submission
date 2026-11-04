"""offline-takes.md AC-OT13, AC-OT14: a refused take names its route, status and reason in the log; a follow take with
the catalog down is told the catalog is down, so the browser keeps it."""
from __future__ import annotations

import logging
from pathlib import Path

import pytest

from part7 import server
from support import Api


def _named(caplog: pytest.LogCaptureFixture, *words: str) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING and all(w in r.getMessage() for w in words)]


def test_a_signed_out_upload_in_prod_names_route_status_and_reason(api: Api, tiny_mp4: Path, monkeypatch: pytest.MonkeyPatch,
                                                                   caplog: pytest.LogCaptureFixture) -> None:
    monkeypatch.setattr(server, "is_prod", lambda: True)
    with caplog.at_level(logging.INFO):
        status, doc = api.upload(tiny_mp4)
    assert status == 401
    assert doc["error"] == server.MSG_UPLOAD_SIGN_IN
    assert _named(caplog, "api/uploads", "answered 401", server.MSG_UPLOAD_SIGN_IN)


def test_a_refused_job_request_is_named_too(api: Api, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO):
        status, _ = api.json("POST", "api/people", {"upload_id": "nope"})
    assert status == 400
    assert _named(caplog, "api/people", "answered 400")


def test_a_refusal_outside_the_take_routes_stays_quiet(api: Api, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO):
        api.json("POST", "api/auth/verify", {"email": "a", "code": "1"})
    assert not _named(caplog, "api/auth/verify", "answered 4")


def _follow_entry_missing(api: Api, tiny_mp4: Path, monkeypatch: pytest.MonkeyPatch, health: object) -> tuple[int, dict]:
    status, sent = api.upload(tiny_mp4)
    assert status == 201, sent
    monkeypatch.setattr(api.app.child, "get_entry", lambda _e: None)
    monkeypatch.setattr(api.app.child, "health", lambda: health, raising=False)
    return api.json("POST", "api/follow", {"upload_id": sent["upload_id"], "entry_id": "lateral-raise"})


def test_follow_with_the_catalog_down_is_503_not_a_missing_movement(api: Api, tiny_mp4: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    status, doc = _follow_entry_missing(api, tiny_mp4, monkeypatch, None)
    assert status == 503, doc
    assert doc["error"] == server.MSG_CATALOG_DOWN


def test_follow_with_the_catalog_up_still_says_the_movement_is_missing(api: Api, tiny_mp4: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    status, doc = _follow_entry_missing(api, tiny_mp4, monkeypatch, {"ok": True})
    assert status == 404, doc
    assert doc["error"] == server.MSG_NO_ENTRY
