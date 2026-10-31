"""Part 7's own analysis keeps Part 2's picture signal as minor tips (video quality feedback)."""

from __future__ import annotations

import json
from pathlib import Path

from part7 import chain
from part7.quality_constants import QUALITY_TIPS


def _pose3d(path: Path, issues: list[dict]) -> Path:
    path.write_text(json.dumps({"quality": {"format": "simon.quality.v1", "producer": "part2",
                                            "thresholds": {"dark_mild_luma": 70}, "issues": issues}}), encoding="utf-8")
    return path


def test_dark_signal_becomes_a_minor_tip_and_the_score_stays_zero(tmp_path: Path) -> None:
    pose = _pose3d(tmp_path / "pose3d.json", [
        {"code": "dark", "level": "severe", "share": 0.9, "spans_s": [[0.0, 1.0], [2.0, 5.0]], "evidence": {}},
        {"code": "not_a_code", "level": "mild", "share": 0.5, "spans_s": []},
    ])
    out = chain.write_own_analysis(tmp_path / "analysis.json", "pose", "no person found", quality_paths=[pose])
    doc = json.loads(out.read_text())
    assert doc["score"]["value"] == 0 and doc["score"]["grade"] == "F"
    assert len(doc["warnings"]) == 1
    issues = doc["quality"]["issues"]
    assert [i["code"] for i in issues] == ["dark"]  # unknown codes are dropped
    assert issues[0]["impact"] == "minor" and issues[0]["rule"] is None  # severe signal is not major
    assert issues[0]["tip"] == QUALITY_TIPS["dark"] and issues[0]["text"].startswith("The room was dark")
    assert issues[0]["at_s"] == 2.0  # start of the largest span
    assert doc["score"]["capped_by"] == [doc["warnings"][0]["code"]]


def test_no_quality_input_leaves_the_analysis_unchanged(tmp_path: Path) -> None:
    missing = tmp_path / "nope.json"
    bare = tmp_path / "bare.json"
    bare.write_text("{}", encoding="utf-8")
    for paths in (None, [missing], [bare]):
        doc = json.loads(chain.write_own_analysis(tmp_path / "a.json", "pose", "r", quality_paths=paths).read_text())
        assert "quality" not in doc


def test_a_selected_person_never_gets_another_persons_problems(tmp_path: Path) -> None:
    tracks = tmp_path / "tracks.json"
    tracks.write_text(json.dumps({"people_quality": {
        "1": {"format": "simon.quality.v1", "issues": [{"code": "subject_small", "level": "mild", "spans_s": [[0, 2]]}]},
        "2": {"format": "simon.quality.v1", "issues": []}}}), encoding="utf-8")
    doc = json.loads(chain.write_own_analysis(tmp_path / "a.json", "pose", "r", quality_paths=[tracks], person_id="2").read_text())
    assert "quality" not in doc
    doc = json.loads(chain.write_own_analysis(tmp_path / "b.json", "pose", "r", quality_paths=[tracks], person_id="1").read_text())
    assert [i["code"] for i in doc["quality"]["issues"]] == ["subject_small"]
