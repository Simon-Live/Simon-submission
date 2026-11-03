"""The history entry and report payloads carry `attribution`, read now and never written by the model (TICKET-232 AC-5)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from part7 import history_report
from history_support import ENTRY, USER, World, record_two, world  # noqa: F401
from support import Api

ANSWER = json.dumps({"summary": {"text": "Take 2 scored 77.", "cites": [{"take": 2}]}, "trends": [], "observations": []})
BASE = "api/me/history"
HEAD = {"X-Test-User": USER}


@pytest.fixture()
def seeded(api: Api, world: World, monkeypatch: pytest.MonkeyPatch) -> Api:
    world.install_model(monkeypatch)
    record_two(api.app.state, world)
    return api


def test_entry_and_report_payloads_have_an_attribution_with_no_invented_name(seeded: Api) -> None:
    status, doc = seeded.json("GET", f"{BASE}/{ENTRY}", headers=HEAD)
    assert status == 200 and doc["attribution"]["kind"] == "take" and doc["attribution"]["trainer_credit"] is None
    assert doc["attribution"]["author"] in (None, {"name": None, "avatar": None})
    status, report = seeded.json("POST", f"{BASE}/{ENTRY}/report", headers={**HEAD, "Origin": f"http://127.0.0.1:{seeded.port}"})
    assert status in (200, 202)
    if status == 202:
        assert history_report.runner_for(seeded.app.state, seeded.app.child.catalog_dir).wait_idle()
        status, report = seeded.json("GET", f"{BASE}/{ENTRY}/report", headers=HEAD)
    assert status == 200 and report["attribution"]["trainer_credit"] is None


def test_the_report_cache_holds_no_name(seeded: Api) -> None:
    sample: Any = history_report.cached(seeded.app.state, USER, ENTRY, "none")
    assert sample is None or "attribution" not in sample  # the line is added at request time, never stored
