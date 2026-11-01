"""Part 7's own analysis keeps Part 2's picture signal as minor tips (video quality feedback)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from part7 import chain, modules
from part7.parts import p5_analyse
from part7.quality_constants import QUALITY_TIPS


def _own(path: Path, take: str, reason: str, **kw) -> Path:
    return chain.write_own_analysis(path, take, reason, expected="trainer.json", follower="take.mp4", **kw)


def _pose3d(path: Path, issues: list[dict]) -> Path:
    path.write_text(json.dumps({"quality": {"format": "simon.quality.v1", "producer": "part2",
                                            "thresholds": {"dark_mild_luma": 70}, "issues": issues}}), encoding="utf-8")
    return path


def test_dark_signal_becomes_a_minor_tip_and_the_score_stays_zero(tmp_path: Path) -> None:
    pose = _pose3d(tmp_path / "pose3d.json", [
        {"code": "dark", "level": "severe", "share": 0.9, "spans_s": [[0.0, 1.0], [2.0, 5.0]], "evidence": {}},
        {"code": "not_a_code", "level": "mild", "share": 0.5, "spans_s": []},
    ])
    out = _own(tmp_path / "analysis.json", "no_person", "no person found", quality_paths=[pose])
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
        doc = json.loads(_own(tmp_path / "a.json", "no_person", "r", quality_paths=paths).read_text())
        assert "quality" not in doc


def test_a_selected_person_never_gets_another_persons_problems(tmp_path: Path) -> None:
    tracks = tmp_path / "tracks.json"
    tracks.write_text(json.dumps({"people_quality": {
        "1": {"format": "simon.quality.v1", "issues": [{"code": "subject_small", "level": "mild", "spans_s": [[0, 2]]}]},
        "2": {"format": "simon.quality.v1", "issues": []}}}), encoding="utf-8")
    doc = json.loads(_own(tmp_path / "a.json", "no_person", "r", quality_paths=[tracks], person_id="2").read_text())
    assert "quality" not in doc
    doc = json.loads(_own(tmp_path / "b.json", "no_person", "r", quality_paths=[tracks], person_id="1").read_text())
    assert [i["code"] for i in doc["quality"]["issues"]] == ["subject_small"]


def test_own_analysis_declares_the_part5_schema_it_conforms_to(tmp_path: Path) -> None:
    """1.6.0 (TICKET-118): warnings, match and a capped score; no insights or profile; the pinned doctor requires profile from 1.7.0."""
    doc = json.loads(_own(tmp_path / "a.json", "no_person", "r").read_text())
    assert doc["schema_version"] == "1.6.0" and doc["source"] == "part7"
    assert not {"insights", "profile"} & set(doc)


def test_own_analysis_names_both_clips_and_has_no_faults(tmp_path: Path) -> None:
    """Part 5's schema needs `expected` and `follower` with a non-empty `path`; the 1.4.0 / part7 stamp stays."""
    doc = json.loads(_own(tmp_path / "a.json", "no_person", "r").read_text())
    assert doc["expected"] == {"path": "trainer.json"} and doc["follower"] == {"path": "take.mp4"}
    assert doc["faults"] == [] and doc["schema_version"] == "1.6.0" and doc["source"] == "part7"


@pytest.mark.parametrize("take", [
    "no_usable_measures",
    # Part 5's warnings enum (analysis.schema.json 1.7.0) has no `no_person`; strict, so Part 5 adding it flags this.
    "no_person",  # Part 5 d6700e8 (TICKET-048) added no_person to the warnings enum
])
def test_pinned_part5_doctor_accepts_the_own_analysis(tmp_path: Path, take: str) -> None:
    """The pinned Part 5's `doctor --for part7` passes Part 7's own analysis (exit 0, no problems)."""
    lk = modules.load()
    if not (lk.path("5") / "part5").is_dir():
        pytest.skip("Part 5 module not set up")
    step = p5_analyse.doctor(_own(tmp_path / f"{take}.json", take, "r"), tmp_path, consumer="part7", lock=lk)
    assert step["exit"] == 0, step
