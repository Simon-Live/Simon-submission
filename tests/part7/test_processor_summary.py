"""A pinned-Part-5 refusal (null score) reads as 0 and F in the job summary (app.md "Always analysed")."""

from __future__ import annotations

import json
from pathlib import Path

from part7.processor import _score_summary


def test_null_score_is_zero_and_f(tmp_path: Path) -> None:
    f = tmp_path / "analysis.json"
    f.write_text(json.dumps({"status": {"code": "different_movement"}, "score": None, "faults": []}), encoding="utf-8")
    s = _score_summary(f)
    assert (s["score"], s["grade"], s["status_code"]) == (0, "F", "different_movement")


def test_scored_and_unreadable(tmp_path: Path) -> None:
    f = tmp_path / "a.json"
    f.write_text(json.dumps({"status": {"code": "ok"}, "score": {"value": 61, "grade": "D"}, "faults": [{}]}), encoding="utf-8")
    assert _score_summary(f)["score"] == 61
    assert _score_summary(tmp_path / "missing.json") == {}
