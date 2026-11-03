"""TICKET-210: ledger fields hold no personal data, and a feature may have its own caps (off unless set)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from part7 import history_api as api
from test_history_api import FakeTransport, packed


def test_ledger_fields_hold_no_user_text_file_or_job(tmp_path: Path) -> None:
    api.ask({**packed(), "feature": "report"}, transport=FakeTransport(), state=tmp_path)
    raw = (tmp_path / "history" / "spend.jsonl").read_text()
    for line in raw.splitlines():
        row = json.loads(line)
        assert row["feature"] == "report" and row["prompt_version"]
        assert not any(k in row for k in ("user", "user_id", "job_id", "path", "text", "file"))
    assert "job0000" not in raw and ".mp4" not in raw and "file-" not in raw


def test_feature_caps_are_off_unless_the_variable_is_set(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("SIMON7_HISTORY_PLAN_CAP_USD", "SIMON7_HISTORY_PLAN_CALL_MAX_USD"):
        monkeypatch.delenv(name, raising=False)
    assert api.feature_cap("plan", "total") is None and api.feature_cap("plan", "call") is None
    monkeypatch.setenv("SIMON7_HISTORY_PLAN_CAP_USD", "0.01")
    monkeypatch.setenv("SIMON7_HISTORY_PLAN_CALL_MAX_USD", "junk")
    assert api.feature_cap("plan", "total") == 0.01 and api.feature_cap("plan", "call") is None
    monkeypatch.setenv("SIMON7_HISTORY_PLAN_CAP_USD", "-1")
    assert api.feature_cap("plan", "total") is None
    assert api.feature_cap("my-feature", "total") is None   # the name becomes MY_FEATURE


def test_a_second_feature_stops_at_its_own_cap_while_the_report_feature_does_not(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIMON7_HISTORY_PLAN_CAP_USD", "0.06")
    api.ask({**packed(), "feature": "plan"}, transport=FakeTransport(), state=tmp_path)    # settles near 0.03
    with pytest.raises(api.HistoryError, match="cap reached for plan"):
        api.ask({**packed(), "feature": "plan"}, transport=FakeTransport(), state=tmp_path)
    api.ask({**packed(), "feature": "report"}, transport=FakeTransport(), state=tmp_path)   # no cap of its own
    by = api.spent_by_feature(tmp_path / "history" / "spend.jsonl")
    assert set(by) == {"plan", "report"}


def test_a_per_call_cap_refuses_before_any_line_is_written(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIMON7_HISTORY_PLAN_CALL_MAX_USD", "0.0001")
    with pytest.raises(api.HistoryError, match="for this feature"):
        api.ask({**packed(), "feature": "plan"}, transport=FakeTransport(), state=tmp_path)
    assert not (tmp_path / "history" / "spend.jsonl").exists()
    api.ask(packed(), transport=FakeTransport(), state=tmp_path)    # the default feature is untouched
