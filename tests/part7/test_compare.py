"""Tests for `part7.compare` (check-7.md AC-K2, AC-K6, AC-K9 to AC-K11; ADR-0005, ADR-0006)."""

from __future__ import annotations

import copy
from typing import Any

from part7 import compare


def fault(measure: str = "upper_arm_out", side: str = "left", direction: str = "too_high",
          mag: float = 20.0, at_s: float = 2.0, text: str | None = "Arm is too high at 2s") -> dict[str, Any]:
    f: dict[str, Any] = {"measure": measure, "side": side, "direction": direction,
                         "magnitude_deg": mag, "at_s": at_s, "expected_frames": [10]}
    if text is not None:
        f["text_timed"] = text
    return f


def analysis(faults: list[dict[str, Any]], score: int | None = 80, status: str | None = None) -> dict[str, Any]:
    a: dict[str, Any] = {"faults": faults, "score": None if score is None else {"value": score, "grade": "B"}}
    if status is not None:
        a["status"] = {"code": status}
    return a


def test_tolerance_constants_match_adr_0005() -> None:
    assert compare.TOLERANCE == {"deg_abs": 2.0, "m_abs": 0.01, "rel": 0.10}


def test_identical_sets_match_and_count_compared() -> None:
    a = analysis([fault(), fault(side="right", mag=15.0)])
    res = compare.match(a, copy.deepcopy(a))
    assert res["matched"] and res["faults_compared"] == 2 and res["at_s_equal"]


def test_magnitude_within_two_degrees_matches() -> None:
    res = compare.match(analysis([fault(mag=20.0)]), analysis([fault(mag=21.9)]))
    assert res["matched"]


def test_magnitude_outside_tolerance_fails() -> None:
    res = compare.match(analysis([fault(mag=20.0)]), analysis([fault(mag=30.0)]))
    assert res["faults_equal"] and not res["magnitudes_within"] and not res["matched"]


def test_relative_tolerance_applies_to_large_magnitudes() -> None:
    assert compare.match(analysis([fault(mag=100.0)]), analysis([fault(mag=109.0)]))["matched"]
    assert not compare.match(analysis([fault(mag=100.0)]), analysis([fault(mag=115.0)]))["matched"]


def test_metre_faults_use_metre_tolerance() -> None:
    a = {"faults": [{"measure": "foot_x", "side": "left", "direction": "out", "magnitude_m": 0.10}]}
    d = {"faults": [{"measure": "foot_x", "side": "left", "direction": "out", "magnitude_m": 0.105}]}
    assert compare.match(a, d)["matched"]
    d["faults"][0]["magnitude_m"] = 0.14
    assert not compare.match(a, d)["matched"]


def test_missing_fault_fails() -> None:
    res = compare.match(analysis([fault()]), analysis([fault(), fault(side="right")]))
    assert not res["faults_equal"] and not res["matched"]


def test_extra_fault_fails() -> None:
    res = compare.match(analysis([fault(), fault(side="right")]), analysis([fault()]))
    assert not res["faults_equal"] and not res["matched"]


def test_side_swap_fails() -> None:
    res = compare.match(analysis([fault(side="left")]), analysis([fault(side="right")]))
    assert not res["matched"] and res["faults_compared"] == 0


def test_direction_flip_fails() -> None:
    res = compare.match(analysis([fault(direction="too_high")]), analysis([fault(direction="too_low")]))
    assert not res["matched"]


def test_empty_sets_match_with_zero_compared() -> None:
    res = compare.match(analysis([]), analysis([]))
    assert res["matched"] and res["faults_compared"] == 0


def test_file_without_status_reads_as_ok() -> None:
    assert compare.status_code({"faults": []}) == "ok"
    assert compare.match({"faults": []}, analysis([], status="ok"))["status_equal"]


def test_status_difference_fails_match() -> None:
    res = compare.match(analysis([], status="different_movement", score=None), analysis([]))
    assert not res["matched"] and not res["status_equal"]


def test_score_equal_fails_on_one_point() -> None:
    assert compare.score_equal(analysis([], score=80), analysis([], score=80))
    assert not compare.score_equal(analysis([], score=80), analysis([], score=79))


def test_score_null_on_refused_take_is_equal_and_null_on_ok_take_is_not() -> None:
    refused = analysis([], score=None, status="different_movement")
    assert compare.score_equal(refused, copy.deepcopy(refused))
    assert not compare.score_equal(analysis([], score=None), analysis([], score=None))


def test_at_s_equal_fails_on_tenth_of_a_second() -> None:
    res = compare.match(analysis([fault(at_s=2.0)]), analysis([fault(at_s=2.1)]))
    assert res["faults_equal"] and res["magnitudes_within"] and not res["at_s_equal"]


def test_at_s_missing_is_not_equal() -> None:
    f = fault()
    del f["at_s"]
    assert not compare.match(analysis([f]), analysis([fault()]))["at_s_equal"]


def test_fault_without_text_timed_fails_app_result_complete() -> None:
    assert compare.app_result_complete(analysis([fault()]))
    assert not compare.app_result_complete(analysis([fault(text=None)]))
    assert not compare.app_result_complete(analysis([fault(text="  ")]))


def test_app_result_without_score_fails_unless_refused() -> None:
    assert not compare.app_result_complete({"faults": []})
    assert compare.app_result_complete(analysis([], score=None, status="different_movement"))


def test_pose3d_diff_reports_identity_and_max_joint_distance() -> None:
    a = {"frames": [{"frame": 0, "joints": {"hip": [0.0, 0.0, 0.0]}}]}
    b = {"frames": [{"frame": 0, "joints": {"hip": [0.0, 0.003, 0.004]}}]}
    same, diff = compare.pose3d_diff(a, copy.deepcopy(a))
    assert same and diff == 0.0
    same, diff = compare.pose3d_diff(a, b)
    assert not same and abs(diff - 0.005) < 1e-9


def test_warning_codes_and_effective_grade_read_old_refusals_as_warnings() -> None:
    old = analysis([], score=None, status="different_movement")
    assert compare.warning_codes(old) == ["different_movement"]
    assert compare.effective_grade(old) == "F"
    new = {"status": {"code": "ok"}, "warnings": [{"code": "low_match"}, {"code": "low_match"}], "score": {"value": 41, "grade": "F"}}
    assert compare.warning_codes(new) == ["low_match"]
    assert compare.effective_grade(new) == "F"
    assert compare.effective_grade(analysis([])) == "B"
    assert compare.warning_codes(analysis([])) == []
    assert compare.match(old, new)["warnings_equal"] is False


def test_quality_helpers_ignore_absent_fields_and_never_promote_signal_level() -> None:
    old = analysis([])
    minor = copy.deepcopy(old)
    minor["quality"] = {"issues": [{"code": "dark", "impact": "minor", "level": "severe"}]}
    assert compare.quality_codes(old, "major") == []
    assert compare.quality_codes(minor, "major") == []
    assert compare.quality_codes(minor, "minor") == ["dark"]
    assert compare.quality_cap_equal(old, minor)


def test_quality_caps_require_major_codes_score_and_grade() -> None:
    major = {"quality": {"issues": [{"code": "dark", "impact": "major"}]},
             "score": {"value": 59, "grade": "F", "capped_by": ["quality_dark"]}}
    assert compare.quality_cap_valid(major)
    assert compare.match(major, copy.deepcopy(major))["quality_major_codes_equal"]
    for value in (60, float("nan"), True, None):
        broken = copy.deepcopy(major)
        broken["score"]["value"] = value
        assert not compare.quality_cap_valid(broken)
    for field, value in (("grade", "D"), ("capped_by", []), ("capped_by", ["quality_blurry"])):
        broken = copy.deepcopy(major)
        broken["score"][field] = value
        assert not compare.quality_cap_equal(major, broken)
    major["score"]["value"] = 45
    assert compare.quality_cap_valid(major)


def test_quality_cap_on_minor_fails_and_codes_are_sets() -> None:
    a = {"quality": {"issues": [{"code": "dark", "impact": "minor"},
                                {"code": "dark", "impact": "minor"}, None, {"unknown": 1}]},
         "score": {"value": 59, "grade": "F", "capped_by": ["quality_dark"]}}
    assert compare.quality_codes(a, "minor") == ["dark"]
    assert not compare.quality_cap_valid(a)
    a["quality"]["issues"] = "future unknown field"
    assert compare.quality_codes(a, "major") == []
