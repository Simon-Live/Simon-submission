"""simon.score.v2 (ADR-0018, docs/specs/score-v2.md): the weight by the trainer's range, the ceiling of a take that reports a
fault and its own field `fault_cap`, `uncapped` as the value before every cap, v1 kept reproducible, the rule for the
floor, the five targets and the freeze lookup."""
import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from part5 import score, score_report
from part5.detect import load_rules
from part5.measures import MEASURES
from part5.output import fault_to_dict
from shipped_score import (FLOOR, IS_V3, N, SHIPPED, V1_SHA, V2, V2_SHA, V3, aligned, analysis, by_version, capped_only,
                           check_share_of_the_take, check_windows_add_up, fault, fresh_v1, frozen_v1, frozen_v2, lateral_raise_run,
                           lengths, small_set, timed_take, v2_rules, window)

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def rules():
    return {**load_rules(), "score": score.block_v2(fresh_v1(), FLOOR)}


@pytest.fixture
def rules_v1():
    return {**load_rules(), "score": fresh_v1()}


# ---------------------------------------------------------------- AC-V2-01: the weight
@pytest.mark.parametrize("u, w", [(0.0, FLOOR), (1.0, FLOOR), (3 * FLOOR, FLOOR), (3 * (FLOOR + 0.05), FLOOR + 0.05),
                                  (3.0, 1.0), (9.0, 1.0)])
def test_ac_v2_01_the_weight_rises_from_the_floor_to_one_at_range_full(rules, u, w):
    assert score.weight(u, score.params_of(rules)) == pytest.approx(w)


def test_ac_v2_01_a_v1_block_and_an_unknown_range_weigh_one(rules, rules_v1):
    assert score.weight(0.0, score.params_of(rules_v1)) == 1.0
    assert score.weight(None, score.params_of(rules)) == 1.0


def test_ac_v2_01_a_miss_on_a_still_measure_costs_the_floor_share_of_its_v1_cost(rules, rules_v1):
    f = [fault(runs=((0, 9),))]
    v1 = score.compute(analysis(f), aligned(still=True), rules_v1)["components"]["faults"]
    v2 = score.compute(analysis(f), aligned(still=True), rules)["components"]["faults"]
    assert v1 == 15.0 * 0.75 and v2 == pytest.approx(v1 * FLOOR, abs=0.01)


def test_ac_v2_01_a_miss_on_a_measure_the_trainer_moves_costs_in_full(rules, rules_v1):
    f = [fault()]
    v1 = score.compute(analysis(f), aligned(still=False), rules_v1)["components"]["faults"]
    v2 = score.compute(analysis(f), aligned(still=False), rules)["components"]["faults"]
    assert v2 == v1


def test_ac_v2_01_the_miss_entry_on_the_timeline_is_the_weighted_points_and_the_window_adds_up(rules):
    n = N
    a = analysis([fault()], warnings=None)
    window = score.window_score(a, aligned(still=True), np.arange(n), rules, score.params_of(rules))
    assert window["components"]["faults"] == pytest.approx(sum(m["points"] for m in window["misses"]), abs=0.05)
    assert window["value"] == int(score.round_half_up(100 - window["components"]["faults"] - window["components"]["similarity"]))


# ---------------------------------------------------------------- AC-V2-02: which series, and when the range is unknown
def expected_with(**series):
    return {k: np.asarray(v, dtype=float) for k, v in series.items()}


def test_ac_v2_02_a_sided_fault_reads_its_own_side_and_both_reads_the_larger(rules):
    exp = expected_with(left_foot_out=[0, 12], right_foot_out=[0, 60], trunk_lean_forward=[0, 9])
    thr = score.threshold_of("left_foot_out", rules)
    assert score.trainer_range(fault(side="left"), exp, rules) == pytest.approx(12 / thr)
    assert score.trainer_range(fault(side="right"), exp, rules) == pytest.approx(60 / thr)
    assert score.trainer_range(fault(side="both"), exp, rules) == pytest.approx(60 / thr)
    assert score.trainer_range(fault(measure="trunk_lean_forward", side="center"), exp, rules) == pytest.approx(
        9 / score.threshold_of("trunk_lean_forward", rules))


def test_ac_v2_02_a_series_that_is_not_there_or_has_no_finite_value_is_unknown_and_weighs_one(rules):
    exp = expected_with(left_foot_out=[np.nan, np.nan])
    p = score.params_of(rules)
    assert score.trainer_range(fault(measure="foot_rotation", side="left"), exp, rules) is None   # a foot measure
    assert score.trainer_range(fault(side="left"), exp, rules) is None                             # all NaN
    assert score.weight(score.trainer_range(fault(measure="foot_rotation"), exp, rules), p) == 1.0


def test_ac_v2_02_a_nan_inside_the_series_is_skipped(rules):
    exp = expected_with(left_foot_out=[0, np.nan, 6])
    assert score.trainer_range(fault(side="left"), exp, rules) == pytest.approx(1.0)


# ---------------------------------------------------------------- AC-V2-03: the window is the window
def test_ac_v2_03_the_range_is_taken_over_the_windows_own_frames(rules):
    exp = aligned(still=True)
    exp["expected"]["left_foot_out"] = np.r_[np.zeros(N // 2), np.linspace(0, 60, N // 2)]   # moves in the second half only
    p = score.params_of(rules)
    a = analysis([fault(runs=((0, N - 1),))])
    first = score.window_score(a, exp, np.arange(0, N // 2), rules, p)
    second = score.window_score(a, exp, np.arange(N // 2, N), rules, p)
    assert first["misses"][0]["points"] == pytest.approx(second["misses"][0]["points"] * FLOOR, abs=0.1)


# ---------------------------------------------------------------- AC-V2-04: the ceiling and its field
def test_ac_v2_04_a_take_that_reports_a_fault_scores_at_most_89_and_says_so_in_fault_cap(rules):
    light = fault(mag=10.0, runs=((0, 1),), cov=0.5)   # a light fault: v2 charges well under 11 points
    s = score.compute(analysis([light]), aligned(), rules)
    assert s["version"] == "simon.score.v2" and s["value"] == 89 and s["grade"] == "B" and s["fault_cap"] == 89
    assert s["uncapped"]["value"] > 89 and s["uncapped"]["grade"] == "A"
    assert "capped_by" not in s


def test_ac_v2_04_fault_cap_is_present_when_the_cap_did_not_lower_the_value_and_has_no_uncapped(rules):
    s = score.compute(analysis([fault(mag=100.0, runs=((0, 19),))]), aligned(), rules)
    assert s["value"] < 89 and s["fault_cap"] == 89 and "uncapped" not in s and "capped_by" not in s


def test_ac_v2_04_a_take_without_a_fault_has_no_fault_cap_and_is_not_capped(rules):
    s = score.compute(analysis(), aligned(), rules)
    assert (s["value"], s["grade"]) == (100, "A") and "fault_cap" not in s and "uncapped" not in s


def test_ac_v2_04_a_v1_block_has_no_ceiling_and_no_fault_cap(rules_v1):
    s = score.compute(analysis([fault(mag=10.0, runs=((0, 0),), cov=0.1)]), aligned(), rules_v1)
    assert s["version"] == "simon.score.v1" and s["value"] > 89 and "fault_cap" not in s and "uncapped" not in s


def test_ac_v2_04_a_take_nothing_could_be_measured_on_has_no_fault_cap(rules):
    zero = score.zero_block(rules)
    assert zero["version"] == "simon.score.v2" and zero["value"] == 0 and "fault_cap" not in zero


# ---------------------------------------------------------------- AC-V2-05: uncapped is the value before every cap
def test_ac_v2_05_a_faulted_take_with_no_warning_has_uncapped_and_no_capped_by(rules):
    s = score.cap_by_warnings(score.compute(analysis([fault(mag=10.0, runs=((0, 1),), cov=0.5)]), aligned(), rules),
                              analysis(), rules)
    assert s["value"] <= 89 and "uncapped" in s and "capped_by" not in s


# The case of a faulted take that also carries the low-match warning (both caps) is one parametrized test with AC-V3-04's, in
# tests/test_score_v3.py: test_ac_v2_05_and_ac_v3_04_with_both_caps_..., its "v2, one fault, 89" row is this file's old case.
def test_ac_v2_05_a_warning_cap_alone_keeps_the_uncapped_it_always_had(rules):
    good = score.compute(analysis(), aligned(), rules)
    capped = score.cap_by_warnings(good, analysis(warnings=[{"code": "low_match", "text": "x"}]), rules)
    assert capped["uncapped"] == {"value": 100, "grade": "A"} and "fault_cap" not in capped


# ---------------------------------------------------------------- AC-V2-06: the mean of the windows, capped once
def test_ac_v2_06_the_ceiling_is_applied_to_the_mean_and_never_to_a_window(rules):
    windows = [window(95.0, 0), window(97.0, 1)]
    block = score.timeline_block(windows, "windows", rules, n_faults=1)
    assert block["value"] == 89 and block["uncapped"] == {"value": 96, "grade": "A"} and block["fault_cap"] == 89
    assert [w["value"] for w in block["timeline"]] == [95, 97]


def test_ac_v2_06_there_is_no_worst_window_rule(rules):
    windows = [window(100.0, 0), window(60.0, 1)]   # one bad window: the take is the mean, 80, not the worst, 60
    assert score.timeline_block(windows, "windows", rules, n_faults=1)["value"] == 80


def test_ac_v2_06_no_reported_fault_no_ceiling(rules):
    block = score.timeline_block([window(95.0, 0), window(97.0, 1)], "windows", rules, n_faults=0)
    assert block["value"] == 96 and "fault_cap" not in block


def test_ac_v2_06_one_miss_a_minute_costs_like_ten_in_ten_minutes_before_the_ceiling_and_all_three_takes_are_capped(rules):
    one, ten, crowded = lengths(rules)
    check_share_of_the_take(one, ten, crowded)   # more misses in the same time cost more
    assert one["value"] == ten["value"] == crowded["value"] == one["fault_cap"] == 89   # a take that reports a fault is a B at most


def test_ac_v2_06_each_window_lists_its_misses_and_they_add_up_to_its_value_and_the_take_to_the_mean(rules):
    block = timed_take(rules, 30, 3)
    assert block["basis"] == "windows" and len(block["timeline"]) == 6
    check_windows_add_up(block, 6)   # the points shown are rounded to 0.1 (a v2 miss costs a weighted, fractional number of points)


# ---------------------------------------------------------------- AC-V2-07: v1 stays reproducible
def test_ac_v2_07_the_v1_block_is_the_frozen_one_and_hashes_to_the_recorded_seeds_47_and_53():
    record = json.loads((ROOT / "fixtures/score-heldout.json").read_text())
    frozen = {a["params_sha256"] for a in record["attempts"] if a["seed"] in (47, 53)}   # a seed 59 attempt is v2's
    v1 = frozen_v1()
    assert frozen == {V1_SHA}
    assert score.params_sha256(v1) == frozen.pop() and v1["version"] == "simon.score.v1"
    assert hashlib.sha256(json.dumps(v1, sort_keys=True, separators=(",", ":")).encode()).hexdigest() == score.params_sha256(v1)


def test_ac_v2_07_the_v2_block_repeats_the_v1_numbers_it_does_not_change():
    """The v2 block as frozen for seed 59 (`V2_SHA`): kept verbatim in a v3 score section (ADR-0019), rebuilt from the
    frozen v1 params in a v1 tree. Either way it is the same dict."""
    block = frozen_v2()
    assert score.params_sha256(block) == V2_SHA
    assert block["version"] == "simon.score.v2"
    for key in score.SHARED_V1:
        assert block[key] == block["v1"][key], key
    assert block["range_full"] == 3.0 and block["fault_cap"] == 89 and block["calibrated_on"] == "seed 5"
    assert block["range_floor"] == FLOOR, "tests/shipped_score.FLOOR is the floor the rule picked; change it there"
    assert set(block) == {"version", *score.SHARED_V1, "range_floor", "range_full", "fault_cap", "calibrated_on", "v1"}
    assert block["v1"] == frozen_v1() and score.block_v2(frozen_v1(), FLOOR) == block


def test_ac_v2_07_rules_v2_scores_as_v2_did_and_the_v2_code_reads_the_kept_block():
    """`score.rules_v2` swaps the kept v2 block in; a seed 5 take scored with it has the values v2 gave it (docs/thresholds.md)."""
    rules = {**load_rules(), "score": frozen_v2()}
    assert score.params_of(rules)["version"] == "simon.score.v2"
    labels = json.loads((ROOT / "fixtures/input/followers/labels.json").read_text())
    want = {"exercise_front_good_08_arms_wider-both+elbow_bent-right": (75, "C"), "exercise_front_good_00_correct": (100, "A"),
            "dance_side_good_11_ankle_rolled_in-right": (89, "B")}
    labels["takes"] = [t for t in labels["takes"] if t["take_id"] in want]
    for take, result in score_report.run_set(labels):
        block = score_report.score_block(result, rules)
        assert block["version"] == "simon.score.v2" and (block["value"], block["grade"]) == want[take["take_id"]]
        assert block["params_sha256"] == V2_SHA
    if IS_V3:   # the tree's own substitution gives the same rules
        assert score.rules_v2(load_rules())["score"] == frozen_v2()


def test_ac_v2_07_rules_v1_scores_as_v1_did_on_seed_5_takes():
    """Three seed 5 takes through the pipeline under the shipped v1 block: the values they had before v2 existed."""
    labels = json.loads((ROOT / "fixtures/input/followers/labels.json").read_text())
    want = {"exercise_front_good_08_arms_wider-both+elbow_bent-right": (67, "D"), "exercise_front_good_00_correct": (100, "A"),
            "dance_side_good_11_ankle_rolled_in-right": (93, "A")}
    labels["takes"] = [t for t in labels["takes"] if t["take_id"] in want]
    v1_rules = {**load_rules(), "score": frozen_v1()}
    for take, result in score_report.run_set(labels):
        block = score_report.score_block(result, v1_rules)
        assert block["version"] == "simon.score.v1" and (block["value"], block["grade"]) == want[take["take_id"]]
        assert "fault_cap" not in block and "uncapped" not in block


def test_ac_v2_07_rules_v1_refuses_a_score_section_that_has_none():
    with pytest.raises(ValueError, match="no simon.score.v1 'v1' block"):
        score.rules_v1({"score": {"version": "simon.score.v2"}})


def test_params_of_accepts_all_three_versions_and_names_them_when_none(rules, rules_v1):
    assert score.params_of(rules)["version"] == "simon.score.v2" and score.params_of(rules_v1)["version"] == "simon.score.v1"
    assert score.params_of({"score": {"version": "simon.score.v3"}})["version"] == "simon.score.v3"
    with pytest.raises(ValueError, match="has no simon.score.v1, simon.score.v2 or simon.score.v3 'score' block"):   # TICKET-054 R8
        score.params_of({"score": {"version": "simon.score.v0"}})


# ---------------------------------------------------------------- AC-V2-08: the rule for the floor
def measured(**kw):
    return {"correct_all_a": True, "single_min": 75, "double_max": 70, "sweep_rises": False, **kw}


def test_ac_v2_08_the_floor_is_the_lowest_on_the_grid_whose_four_conditions_hold():
    grid = {f: measured(double_max=int(100 - 40 * f)) for f in score.FLOOR_GRID}   # 80 at 0.5 ... 60 at 1.0
    assert score.FLOOR_GRID[0] == 0.5 and score.FLOOR_GRID[-1] == 1.0 and len(score.FLOOR_GRID) == 11
    assert score.choose_floor(grid) == 0.65   # double_max 74 is the first at or under 75
    assert score.choose_floor({f: measured(double_max=76) for f in score.FLOOR_GRID}) == 1.0   # none holds: 1.0


@pytest.mark.parametrize("bad", [{"correct_all_a": False}, {"single_min": 69}, {"double_max": 76}, {"sweep_rises": True}])
def test_ac_v2_08_any_one_condition_failing_rejects_a_floor(bad):
    assert score.floor_holds(measured()) and not score.floor_holds(measured(**bad))


def test_ac_v2_08_a_floor_with_no_single_or_no_double_take_is_not_failed_by_them():
    assert score.floor_holds(measured(single_min=None, double_max=None))


def test_ac_v2_08_the_boundaries_are_inclusive():
    assert score.floor_holds(measured(single_min=70, double_max=75)) and not score.floor_holds(measured(single_min=69))


def test_ac_v2_08_block_v2_is_v1_plus_the_three_params_and_the_frozen_v1():
    v1 = frozen_v1()
    block = score.block_v2(v1, 0.8)
    assert block["range_floor"] == 0.8 and block["v1"] == v1 and block["version"] == "simon.score.v2"
    assert {k: block[k] for k in score.SHARED_V1} == {k: v1[k] for k in score.SHARED_V1}


def test_ac_v2_08_the_floor_rule_run_under_the_v2_code_returns_the_v2_block_that_was_frozen(seed5_scored):
    """Seed 5 under the shipped detection, the sweep included: ADR-0018's rule run under the v2 code (as `--calibrate-v2` does)
    returns the v2 block frozen for seed 59 whichever score the rules ship, so the v2 table is reproducible from a v3 tree.
    (About 20 s: eleven floors, each with the sweep.)"""
    labels, rules, results = seed5_scored
    block, measured = score_report.calibrate_floor_set(labels, v2_rules(), results=results, version=V2)
    assert block == frozen_v2() and score.choose_floor(measured) == block["range_floor"] == FLOOR


def test_calibrate_set_gives_the_v2_form_to_rules_that_ship_it_and_the_v1_calibration_to_any_other(monkeypatch):
    labels, shipped = {"takes": []}, v2_rules()
    monkeypatch.setattr(score_report, "calibrate_floor_set", lambda *a, **k: ("v2 form", {}))
    monkeypatch.setattr(score_report, "rows_of_set", lambda *a, **k: "rows")
    monkeypatch.setattr(score, "calibrate", lambda rows, min_fraction: ("v1 calibration", rows, min_fraction))
    assert score_report.calibrate_set(labels, shipped) == "v2 form"   # the block, not the measurements
    assert score_report.calibrate_set(labels, {**shipped, "score": {}}) == ("v1 calibration", "rows", shipped["default"]["min_fraction"])


def test_ac_v2_08_on_seed_5_the_shipped_block_meets_the_conditions_and_every_target(seed5_scored):
    labels, _, results = seed5_scored
    rules = v2_rules()   # v2 at the shipped floor, whichever score the rules ship
    m = score_report.measure_floor(results, rules)
    assert score.floor_holds(m) and m["correct_all_a"] and m["single_min"] >= 70 and m["double_max"] <= 75
    scored = score_report.scored_results(labels, rules, results=results)
    t = score_report.targets_v2([(tk, r.analysis, b) for tk, r, b in scored])
    assert [t[k]["verdict"] for k in ("correct_all_a", "no_reported_fault_grades_a", "single_b_or_c", "double_c_d_or_f")] == ["pass"] * 4
    worst_single = min(b["value"] for tk, r, b in scored if tk["lighting"] == "good" and len(tk["faults"]) == 1
                       and len(r.analysis["faults"]) == 1)
    assert worst_single >= 70   # ADR-0007's worst-single rule still holds


# ---------------------------------------------------------------- AC-V2-11: the five targets
PLANTED = [("foot_out", "left", "more", "foot_out"), ("arms_wider", "both", "more", "upper_arm_out")]   # label, measure


def entry(take_id, labelled, reported, value, lighting="good", extra=0):
    """(label, analysis, score block): `labelled` planted faults, the first `reported` of them reported, `extra` more that
    match nothing."""
    labels = [{"type": t, "side": s, "direction": d} for t, s, d, _ in PLANTED[:labelled]]
    found = [{"measure": m, "side": "left", "direction": d} for _, _, d, m in PLANTED[:reported]]
    found += [{"measure": "knee_flexion", "side": "left", "direction": "more"}] * extra
    return ({"take_id": take_id, "lighting": lighting, "faults": labels}, {"faults": found},
            {"value": value, "grade": score.grade(value)})


def targets_of(*entries):
    return score_report.targets_v2([(t, a, b) for t, a, b in entries])


def test_ac_v2_11_each_target_passes_on_takes_that_meet_it():
    t = targets_of(entry("c", 0, 0, 100), entry("s", 1, 1, 84), entry("d", 2, 2, 66))
    assert [t[k]["verdict"] for k in ("correct_all_a", "no_reported_fault_grades_a", "single_b_or_c", "double_c_d_or_f")] == ["pass"] * 4
    assert t["not_judged"] == []


def test_ac_v2_11_a_take_that_reports_a_fault_and_grades_a_breaks_target_3():
    t = targets_of(entry("s", 1, 1, 91))
    assert t["no_reported_fault_grades_a"]["verdict"] == "fail" and t["no_reported_fault_grades_a"]["breaks"] == ["s: scored 91 (A)"]


def test_ac_v2_11_single_and_double_are_judged_on_takes_that_report_exactly_their_labels():
    t = targets_of(entry("missed", 1, 0, 100),            # undetected: a detection result, listed, not judged
                   entry("extra", 1, 1, 74, extra=1),     # its fault and one more: not exact, listed, not judged
                   entry("exact", 1, 1, 80),              # exactly its one fault: judged
                   entry("half", 2, 1, 84),               # one of two found
                   entry("both", 2, 2, 82))               # B for a double: breaks target 5
    assert [x["take_id"] for x in t["not_judged"]] == ["missed", "extra", "half"]
    assert t["single_b_or_c"]["n"] == 1 and t["single_b_or_c"]["verdict"] == "pass"
    assert t["double_c_d_or_f"]["verdict"] == "fail" and t["double_c_d_or_f"]["breaks"] == ["both: scored 82 (B)"]


def test_ac_v2_11_a_correct_good_light_take_that_is_not_an_a_breaks_target_1_and_low_light_is_never_judged():
    t = targets_of(entry("c", 0, 0, 88), entry("low", 1, 1, 30, lighting="low"))
    assert t["correct_all_a"]["verdict"] == "fail" and t["correct_all_a"]["breaks"] == ["c: scored 88 (B)"]
    assert t["single_b_or_c"]["verdict"] == "no takes"


def test_ac_v2_11_the_report_lines_name_every_target_and_the_takes_not_judged():
    lines = "\n".join(score_report.targets_v2_lines(targets_of(entry("c", 0, 0, 100), entry("m", 1, 0, 100)), []))
    for text in ("1 correct good-light takes all A: pass", "2 the sweep never rises: pass", "3 no take that reports a fault grades A",
                 "4 single faults B or C", "5 double faults C, D or F", "not judged by 4 and 5", "m (1 labelled, 0 reported, 100 A)"):
        assert text in lines, text


def test_the_slice_targets_follow_the_version_the_rules_ship():
    assert score_report.targets_of("simon.score.v1")["good/2"] == "DF"
    assert score_report.targets_of(V2)["good/2"] == score_report.targets_of(V3)["good/2"] == "CDF"   # v3 reuses ADR-0018's
    assert score_report.shipped_targets()["good/2"] == by_version("DF", "CDF", "CDF")
    dist = score_report.distribution([({"lighting": "good", "faults": [1, 2]}, {"value": 72})])
    assert score_report.verdicts(dist, score_report.TARGETS_V2)["good/2"] == "pass"
    assert score_report.verdicts(dist, score_report.TARGETS_V1)["good/2"] == "fail"


# ---------------------------------------------------------------- through the pipeline
def test_a_dance_take_that_reports_a_fault_hits_the_ceiling_through_the_pipeline():
    labels = json.loads((ROOT / "fixtures/input/followers/labels.json").read_text())
    take = next(t for t in labels["takes"] if t["take_id"].startswith("dance_side_good_11"))
    a = score_report.analyse({"path": str(ROOT / take["expected"])}, {"path": str(ROOT / take["follower"])}, v2_rules())
    s = a["score"]
    assert a["faults"] and s["version"] == "simon.score.v2" and s["value"] == 89 and s["grade"] == "B"
    assert s["fault_cap"] == 89 and s["uncapped"] == {"value": 94, "grade": "A"} and "capped_by" not in s


def test_a_real_rep_by_rep_take_adds_up_under_v2_rep_by_rep_and_to_the_mean_of_the_reps():
    """The real fast lateral-raise follower (8 reps, tests/test_reps.py), scored under v2 whichever score the rules ship."""
    block = score_report.score_block(lateral_raise_run(), v2_rules())
    assert block["version"] == "simon.score.v2" and block["basis"] == "reps"
    check_windows_add_up(block, 8)
    assert (block["value"], block["grade"]) == (82, "B")   # 80 (B) under v1: a miss on a measure the trainer moves little costs less


@capped_only
def test_the_committed_sample_for_part_7_is_that_take():
    """One fault reported, so the ceiling in force is 89 under v2 and under v3 alike (a v3 take with two faults has 79)."""
    sample = json.loads((ROOT / "fixtures/output/analysis.fault-capped.example.json").read_text())
    s = sample["score"]
    assert sample["schema_version"] == "1.12.0" and len(sample["faults"]) == 1
    assert (s["version"], s["value"], s["grade"], s["fault_cap"]) == (SHIPPED, 89, "B", 89)
    assert s["uncapped"] == {"value": 94, "grade": "A"} and "capped_by" not in s and "warnings" not in sample


# ---------------------------------------------------------------- the command
def test_params_sha256_flag_prints_the_hash_of_the_shipped_score_block(capsys):
    assert score_report.main(["--params-sha256"]) == 0
    printed = capsys.readouterr().out.strip()
    assert printed == score.params_sha256(load_rules()["score"])
    if IS_V3:   # the shipped block is v3 as designed: v1 and v2 kept verbatim beside the v3 params at the floor the rule picked
        assert printed == score.params_sha256(score.block_v3(frozen_v1(), frozen_v2(), FLOOR))


def test_the_set_is_required_unless_a_flag_replaces_it(capsys):
    with pytest.raises(SystemExit):
        score_report.main([])
    assert "--set is required" in capsys.readouterr().err


@capped_only
def test_the_report_on_a_small_seed_5_set_prints_the_five_targets(tmp_path, capsys):
    keep = ("exercise_front_good_00_correct", "exercise_front_good_08_arms_wider-both+elbow_bent-right",
            "exercise_front_good_03_foot_out-right")
    assert score_report.main(["--set", str(small_set(tmp_path, keep))]) == 0
    out = capsys.readouterr().out
    assert SHIPPED in out and "ADR-0018 targets" in out and "all five hold: yes" in out
    assert score_report.comparability_of(SHIPPED) in out   # R3: the publication reads the strict verdict with this beside it
    assert ("published beside the targets" in out) is IS_V3   # ADR-0019: only a v3 report prints the measures beside them


# ---------------------------------------------------------------- B1: a target with no judged take does not hold
PASSING = (entry("c", 0, 0, 100), entry("s", 1, 1, 84), entry("d", 2, 2, 66))


def test_adr_0018_all_five_hold_when_each_target_judged_a_take_and_none_broke_it_and_the_sweep_ran():
    t = targets_of(*PASSING)
    assert score_report.targets_hold(t, []) is True
    assert score_report.targets_hold(t, None) is False                       # the sweep was not run
    assert score_report.targets_hold(t, ["sweep arms_wider both: score rises"]) is False


@pytest.mark.parametrize("dropped, target", [("c", "correct_all_a"), ("s", "single_b_or_c"), ("d", "double_c_d_or_f")])
def test_adr_0018_a_target_with_no_judged_take_does_not_hold(dropped, target):
    """The stakeholder-proxy ruling of 2026-11-01T05:45Z: fail closed (ADR-0003 #36)."""
    t = targets_of(*[e for e in PASSING if e[0]["take_id"] != dropped])
    assert t[target]["verdict"] == "no takes" and t[target]["n"] == 0
    assert score_report.targets_hold(t, []) is False


def test_adr_0018_target_3_with_no_take_that_reports_a_fault_does_not_hold_either():
    t = targets_of(entry("c", 0, 0, 100), entry("m", 1, 0, 100))   # nothing reports a fault
    assert t["no_reported_fault_grades_a"]["verdict"] == "no takes" and not score_report.targets_hold(t, [])


NO_DOUBLE = ("exercise_front_good_00_correct", "exercise_front_good_03_foot_out-right")   # a correct take and a single fault


def test_adr_0018_the_summary_says_all_five_hold_no_when_target_5_has_no_judged_take(tmp_path, capsys, report_as):
    report_as(v2_rules)
    assert score_report.main(["--set", str(small_set(tmp_path, NO_DOUBLE))]) == 0
    out = capsys.readouterr().out
    assert "5 double faults C, D or F (reported exactly): no takes (n 0)" in out
    assert "all five hold: no  (a target with no judged take does not hold)" in out


def test_adr_0018_the_json_carries_holds_false_when_target_4_or_5_has_no_judged_take(tmp_path, capsys, report_as):
    report_as(v2_rules)
    only_correct = small_set(tmp_path, ("exercise_front_good_00_correct",))
    assert score_report.main(["--set", str(only_correct), "--json"]) == 0
    t = json.loads(capsys.readouterr().out)["targets_v2"]
    assert t["single_b_or_c"]["n"] == 0 and t["double_c_d_or_f"]["n"] == 0 and t["holds"] is False and t["sweep_failures"] == []


def test_adr_0018_the_json_carries_holds_true_when_all_five_hold(tmp_path, capsys, report_as):
    report_as(v2_rules)
    keep = (*NO_DOUBLE, "exercise_front_good_08_arms_wider-both+elbow_bent-right")
    assert score_report.main(["--set", str(small_set(tmp_path, keep)), "--json"]) == 0
    t = json.loads(capsys.readouterr().out)["targets_v2"]
    assert t["holds"] is True and all(t[k]["n"] >= 1 for k in score_report.TARGET_KEYS)


# ---------------------------------------------------------------- Q4: the foot measures take the range weight
FOOT_TAKE = "exercise_front_good_09_foot_turned_out-right"
TWO_REPS_FOOT_TAKE = "dance_front_good_10_foot_turned_in-left"


def run_take(take_id, feet=True):
    labels = json.loads((ROOT / "fixtures/input/followers/labels.json").read_text())
    take = next(dict(t) for t in labels["takes"] if t["take_id"] == take_id)
    if not feet:
        take.pop("expected_feet", None), take.pop("follower_feet", None)
    return score_report.run_set({"takes": [take]})[0][1]


def foot_faults_of(result):
    return [f for f in result.analysis["faults"] if f["measure"] in ("foot_rotation", "ankle_inversion")]


def test_q4_with_feet_files_the_trainers_foot_series_reach_the_score_and_a_foot_fault_takes_the_range_weight():
    result, rules = run_take(FOOT_TAKE), v2_rules()
    n = result.expected.n_frames
    assert sorted(result.foot_expected) == sorted(m for m in result.analysis["diagnostics"]["feet"]["compared"]) and len(result.foot_expected) == 4
    assert all(len(v) == n for v in result.foot_expected.values())
    aligned = score_report.aligned_of(result)
    assert set(result.foot_expected) <= set(aligned["expected"]) and set(MEASURES) <= set(aligned["expected"])
    fault = foot_faults_of(result)[0]
    x = score.fault_features(fault, len(aligned["exp_to_fol"]), aligned["expected"], rules)
    p = score.params_of(rules)
    w = score.weight(x["u"], p)
    assert x["u"] is not None and x["u"] < p["range_full"] and w == pytest.approx(max(p["range_floor"], x["u"] / p["range_full"]))
    assert w < 1.0
    block = score_report.score_block(result, rules)
    miss = next(m for w in block["timeline"] for m in w["misses"] if m["measure"] == fault["measure"])
    assert miss["points"] == float(score.round_half_up(score.miss_cost(x, p), 1))
    assert score.miss_cost(x, p) < score.miss_cost(x, score_report.v1_of(rules))   # cheaper than v1 charged it


def test_q4_without_feet_files_there_is_no_trainer_foot_series_no_foot_fault_and_a_foot_fault_would_weigh_one():
    result, rules = run_take(FOOT_TAKE, feet=False), v2_rules()
    assert result.foot_expected == {} and not foot_faults_of(result)
    assert set(score_report.aligned_of(result)["expected"]) == set(MEASURES)
    fault = {"measure": "foot_rotation", "side": "right", "magnitude_deg": 20.0, "threshold_deg": 14.0, "coverage": 1.0,
             "runs": [[0, 9]], "expected_frames": [0, 9]}
    x = score.fault_features(fault, 10, score_report.aligned_of(result)["expected"], rules)
    assert x["u"] is None and score.weight(x["u"], score.params_of(rules)) == 1.0   # no series: charged in full, as v1 did


def test_q4_the_foot_series_is_the_one_compared_so_a_foot_measure_left_out_by_the_jitter_gate_is_not_in_the_input():
    result = run_take(FOOT_TAKE)
    compared = result.analysis["diagnostics"]["feet"]["compared"]
    assert set(result.foot_expected) == set(compared)


def test_q4_a_rep_by_rep_take_reads_the_trainer_foot_series_of_its_reference_rep():
    result = run_take(TWO_REPS_FOOT_TAKE)
    assert result.reps, "a dance take is compared rep by rep (ADR-0017)"
    rep = next(r for r in result.reps if r.ok)
    feet = score_report.trainer_feet(rep)
    assert set(feet) == set(result.analysis["diagnostics"]["feet"]["compared"]) and feet
    assert all(len(v) == rep.expected.n_frames for v in feet.values()), "the reference rep's frames, not the example's"
    assert rep.expected.n_frames < result.expected.n_frames
    assert set(feet) <= set(score_report.aligned_of(rep, result.vis)["expected"])


def test_q4_the_foot_fault_the_score_prices_is_still_reported_by_detection():
    """Detection itself is pinned by tests/test_detection_baseline.py; this is the take the weight tests above price."""
    result = run_take(FOOT_TAKE)
    assert [f["measure"] for f in foot_faults_of(result)] == ["foot_rotation"]


def rep_foot_misses(result, rules):
    """`[(rep, fault dict, features x, points shown)]` of the foot misses of a rep-by-rep take: `x` is priced from the reference
    rep's own trainer series (`aligned_of(rep)`), `points` is what the take's timeline shows for that miss."""
    block, p, out = score_report.score_block(result, rules), score.params_of(rules), []
    for k, rep in enumerate(result.reps):
        if not rep.ok:
            continue
        aligned = score_report.aligned_of(rep, result.vis)
        for f in [*rep.faults, *rep.continued]:
            if f.measure in ("foot_rotation", "ankle_inversion"):
                fd = fault_to_dict(f)
                x = score.fault_features(fd, len(aligned["exp_to_fol"]), aligned["expected"], rules)
                shown = [m["points"] for m in block["timeline"][k]["misses"] if (m["measure"], m["side"]) == (f.measure, f.side)]
                out.append((rep, f, x, shown))
    return out, p


def test_n7_a_rep_takes_foot_miss_is_priced_from_the_reference_reps_trainer_series():
    result, rules = run_take(TWO_REPS_FOOT_TAKE), v2_rules()
    priced, p = rep_foot_misses(result, rules)
    assert priced and result.reps
    for rep, fault, x, shown in priced:
        assert x["u"] is not None and float(score.round_half_up(score.miss_cost(x, p), 1)) in shown


def test_n7_the_score_reads_the_reference_reps_foot_series_and_not_the_whole_examples():
    """The synthetic trainer's feet are flat, so a rep and the whole example read the same range (about 0) and a mix-up would pass
    unseen. Swing the reference rep's own foot series only: the miss must be charged in full while the take's whole-example
    series (`foot_expected`) is still flat."""
    result, rules = run_take(TWO_REPS_FOOT_TAKE), v2_rules()
    (rep, fault, x, shown), p = rep_foot_misses(result, rules)[0][0], score.params_of(rules)
    key = f"{fault.side}_{fault.measure}"
    assert x["u"] < 0.1 and all(float(np.nanmax(v) - np.nanmin(v)) < 1.0 for v in result.foot_expected.values())   # flat feet
    ref_m, fol_m = rep.measures
    rep.measures = ({**ref_m, key: np.linspace(0.0, 10 * score.threshold_of(key, rules), rep.expected.n_frames)}, fol_m)
    swung, _ = rep_foot_misses(result, rules)
    _, _, x2, shown2 = next(e for e in swung if e[0] is rep and e[1].measure == fault.measure)
    assert x2["u"] == pytest.approx(10.0) and score.weight(x2["u"], p) == 1.0
    assert float(score.round_half_up(score.miss_cost(x2, p), 1)) in shown2 and max(shown2) > max(shown)   # full cost, not the floor's


# ---------------------------------------------------------------- R8: the floor is tuned on seed 5 only
@pytest.mark.parametrize("flag, seed", [("--calibrate-v2", 29), ("--calibrate-v3", 61)])
def test_r8_calibrate_refuses_a_set_that_is_not_seed_5(tmp_path, capsys, monkeypatch, flag, seed):
    labels = json.loads((ROOT / "fixtures/input/followers/labels.json").read_text())
    (tmp_path / "labels.json").write_text(json.dumps({**labels, "seed": seed, "takes": []}))
    monkeypatch.setattr(score_report, "run_set", lambda *a, **k: pytest.fail("a set that is not seed 5 must not be run"))
    assert score_report.main([flag, "--set", str(tmp_path)]) == 2
    err = capsys.readouterr().err
    assert f"{flag} runs on the seed 5 tuning set only, not seed {seed}" in err and "ADR-0003" in err


def test_r8_calibrate_v2_on_seed_5_prints_the_table_and_the_block(tmp_path, capsys, monkeypatch):
    labels = json.loads((ROOT / "fixtures/input/followers/labels.json").read_text())
    (tmp_path / "labels.json").write_text(json.dumps({**labels, "takes": []}))
    block = score.block_v2(frozen_v1(), 0.8)
    monkeypatch.setattr(score_report, "calibrate_floor_set", lambda *a, **k: (block, {0.8: measured()}))
    assert score_report.main(["--calibrate-v2", "--set", str(tmp_path)]) == 0
    out, err = capsys.readouterr()
    assert json.loads(out) == block and "0.80" in err and "<- chosen" in err


# ---------------------------------------------------------------- R9: the zero block still says the ceiling
def test_r9_a_take_with_faults_that_nothing_could_be_measured_on_has_fault_cap_and_value_0(rules):
    s = score.compute(analysis([fault()]), aligned(nan=True), rules)
    assert (s["value"], s["grade"], s["fault_cap"]) == (0, "F", 89) and "uncapped" not in s
    assert "fault_cap" not in score.compute(analysis(), aligned(nan=True), rules)


def test_r9_no_window_compared_and_a_fault_reported_still_has_fault_cap(rules):
    uncompared = [{"t_s": (0.0, 5.0), "compared": False}]
    with_fault = score.timeline_block(uncompared, "reps", rules, n_faults=1)
    assert (with_fault["value"], with_fault["fault_cap"]) == (0, 89) and with_fault["timeline"][0]["compared"] is False
    assert "fault_cap" not in score.timeline_block(uncompared, "reps", rules, n_faults=0)


# ---------------------------------------------------------------- R10: the rep path's range is the reference rep's
def test_r10_a_rep_takes_range_is_the_reference_reps_not_the_whole_examples():
    result, rules = run_take("dance_front_good_02_arms_wider-left", feet=False), v2_rules()
    assert result.reps
    rep = next(r for r in result.reps if r.ok)
    from part5.visibility import measures_of
    want = measures_of(rep.expected.positions, result.vis)
    whole = measures_of(result.expected.positions, result.vis)
    aligned = score_report.aligned_of(rep, result.vis)
    assert all(np.array_equal(aligned["expected"][m], want[m], equal_nan=True) for m in MEASURES)
    assert len(aligned["expected"]["left_upper_arm_out"]) == rep.expected.n_frames < result.expected.n_frames
    spans = {m: float(np.nanmax(v) - np.nanmin(v)) for m, v in want.items()}
    whole_spans = {m: float(np.nanmax(v) - np.nanmin(v)) for m, v in whole.items()}
    differs = [m for m in MEASURES if abs(spans[m] - whole_spans[m]) > 1e-6]
    assert differs, "a rep of the dance moves some measure less than the whole example does"
    m = differs[0]
    side, measure = ("left", m.removeprefix("left_")) if m.startswith("left_") else ("right", m.removeprefix("right_")) if m.startswith("right_") else (None, m)
    u = score.trainer_range({"measure": measure, "side": side}, aligned["expected"], rules)
    assert u == pytest.approx(spans[m] / score.threshold_of(m, rules)) and u != pytest.approx(whole_spans[m] / score.threshold_of(m, rules))
    # and the timeline's misses of that rep are charged by that range: the weight of a window's miss is the reference rep's
    block = score_report.score_block(result, rules)
    assert block["basis"] == "reps" and any(w.get("misses") for w in block["timeline"] if w["compared"])
