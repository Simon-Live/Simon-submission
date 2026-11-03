"""A pinned-Part-5 refusal (null score) reads as 0 and F in the job summary (app.md "Always analysed")."""

from __future__ import annotations

import json
from pathlib import Path

from part7 import quality_cap
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


def _major_file(tmp_path: Path, value: int, **extra: object) -> Path:
    f = tmp_path / "q.json"
    quality = {"version": "simon.quality.v1", "level": "major", "score_cap": 59, "signals": {},
               "reasons": [{"code": "joints_unseen", "words": "Your left knee was out of view for 40% of the take.", "value": 0.4, "threshold": 0.3}]}
    f.write_text(json.dumps({"status": {"code": "ok"}, "score": {"value": value, "grade": "B", **extra}, "faults": [], "quality": quality}), encoding="utf-8")
    return f


def test_a_major_quality_caps_the_summary_and_names_the_reason(tmp_path: Path) -> None:
    s = quality_cap.apply(_score_summary(_major_file(tmp_path, 88)))
    assert (s["score"], s["grade"]) == (59, "F") and s["uncapped"] == {"value": 88, "grade": "B"} and s["capped_by"] == ["quality_major"]
    assert s["quality_note"] == "Your left knee was out of view for 40% of the take."


def test_a_major_quality_keeps_part_5s_own_uncapped_and_a_low_score(tmp_path: Path) -> None:
    s = quality_cap.apply(_score_summary(_major_file(tmp_path, 95, uncapped={"value": 97, "grade": "A"})))
    assert s["score"] == 59 and s["uncapped"] == {"value": 97, "grade": "A"}
    low = quality_cap.apply(_score_summary(_major_file(tmp_path, 40)))
    assert low["score"] == 40 and low["grade"] == "B" and "capped_by" not in low and "uncapped" not in low


def test_ok_degraded_and_absent_quality_never_cap(tmp_path: Path) -> None:
    f = tmp_path / "a.json"
    for quality in ({"level": "ok", "score_cap": None}, {"level": "degraded", "score_cap": None}, None):
        doc: dict = {"status": {"code": "ok"}, "score": {"value": 88, "grade": "B"}, "faults": []}
        if quality:
            doc["quality"] = quality
        f.write_text(json.dumps(doc), encoding="utf-8")
        s = quality_cap.apply(_score_summary(f))
        assert s["score"] == 88 and "quality_note" not in s
    assert quality_cap.level_of(None) == "not_assessed" and quality_cap.level_of({"level": "ok"}) == "ok"
    assert quality_cap.cap_of({"level": "degraded", "score_cap": 59}) is None  # only a major block caps
    assert quality_cap.label_of({"level": "major", "reasons": []}) == quality_cap.FALLBACK_LABEL
