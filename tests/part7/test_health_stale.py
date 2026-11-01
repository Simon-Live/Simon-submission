"""api/health tolerates a slow Part 6 child while the last good probe is fresh (TICKET-188)."""

from __future__ import annotations

import logging
from typing import Any

import pytest

from part7 import health_probe
from support import Api


class _Child:
    def __init__(self) -> None:
        self.up = True

    def health(self) -> dict[str, Any] | None:
        return {"ok": True} if self.up else None

    def list_entries(self) -> list[dict[str, Any]]:
        return [{"id": "a"}, {"id": "b"}]


class _Clock:
    now = 1000.0

    def __call__(self) -> float:
        return self.now


def _wire(api: Api) -> tuple[_Child, _Clock]:
    child, clock = _Child(), _Clock()
    api.app.child = child
    api.app.part6_probe = health_probe.Part6Probe(clock)
    return child, clock


def test_a_missed_probe_with_a_fresh_cache_answers_200_and_marks_stale(api: Api, caplog: pytest.LogCaptureFixture) -> None:
    child, clock = _wire(api)
    status, doc = api.json("GET", "api/health")
    assert status == 200 and doc["part6"] == {"ok": True, "entries": 2}
    child.up, clock.now = False, clock.now + 30
    with caplog.at_level(logging.WARNING):
        status, doc = api.json("GET", "api/health")
        api.json("GET", "api/health")  # rate limited: one warning for both
    assert status == 200 and doc["ok"] is True
    assert doc["part6"] == {"ok": True, "entries": 2, "stale_s": 30}
    assert len([r for r in caplog.records if "last good probe" in r.getMessage()]) == 1


def test_a_missed_probe_with_an_old_cache_answers_503(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    child, clock = _wire(api)
    api.json("GET", "api/health")
    child.up, clock.now = False, clock.now + 121
    status, doc = api.json("GET", "api/health")
    assert status == 503 and doc["ok"] is False and doc["part6"]["ok"] is False
    monkeypatch.setenv("SIMON7_HEALTH_PART6_STALE_S", "500")  # the window is configurable
    assert api.json("GET", "api/health")[0] == 200


def test_a_missed_probe_with_no_cache_answers_503(api: Api) -> None:
    child, _ = _wire(api)
    child.up = False
    status, doc = api.json("GET", "api/health")
    assert status == 503 and "stale_s" not in doc["part6"]
