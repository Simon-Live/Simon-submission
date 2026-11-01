"""simon.score.v3 (ADR-0019, docs/specs/score-v3.md): v2's weight and 89 ceiling for a take that reports one fault, and a ceiling
of 79 for a take whose faults list holds two or more entries, applied once to the mean of the windows and written in
`score.fault_cap`; `uncapped` as the value before every cap; v1 and v2 kept verbatim in the rules; the floor rule run again
under the v3 code; what the report publishes beside ADR-0018's five targets.

The weight, the foot measures and the freeze code are v2's and are tested in tests/test_score_v2.py (they run under the v3 tree
too); this file is what v3 adds."""
import json
from pathlib import Path

import pytest

from part5 import check, output, score, score_report
from part5.detect import load_rules
from shipped_score import (DETECTION_SHA, FLOOR, IS_V3, V1, V1_SHA, V2, V2_SHA, V3, aligned, analysis, check_share_of_the_take,
                           check_windows_add_up, fault, fresh_v1, frozen_v1, frozen_v2, lateral_raise_run, lengths, small_set,
                           timed_take, v2_rules, v3_only, v3_rules, window)

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def rules():
    """v3 built on the small test v1 params (base 10, slope 5, cap 30) and the shipped floor, so a light fault costs a couple of points."""
    v1 = fresh_v1()
    return {**load_rules(), "score": score.block_v3(v1, score.block_v2(fresh_v1(), FLOOR), FLOOR)}


@pytest.fixture(params=["test params", "shipped params"])
def either_params(request, rules):
    """v3 rules built on the small test params (the arithmetic is easy to read) and, in a second run, on the shipped params:
    `v3_rules()`, the params the pre-freeze review R9 asked the length and add-up tests to be pinned on as well."""
    return rules if request.param == "test params" else v3_rules()


@pytest.fixture
def rules_v2():
    return {**load_rules(), "score": score.block_v2(fresh_v1(), FLOOR)}


@pytest.fixture
def rules_v1():
    return {**load_rules(), "score": fresh_v1()}


LIGHT = dict(mag=10.0, runs=((0, 1),), cov=0.5)   # a light fault: it costs about 2 points, so a take is in the high 90s with it


def light(measure="foot_out", side="left"):
    return fault(measure=measure, side=side, **LIGHT)


# ---------------------------------------------------------------- AC-V3-01: the two ceilings
def test_ac_v3_01_the_ceiling_is_chosen_by_the_number_of_entries_in_the_faults_list(rules, rules_v2, rules_v1):
    p3, p2, p1 = (score.params_of(r) for r in (rules, rules_v2, rules_v1))
    assert [score.ceiling_of(p3, n) for n in (0, 1, 2, 3, 10)] == [None, 89, 79, 79, 79]
    assert [score.ceiling_of(p2, n) for n in (0, 1, 2, 10)] == [None, 89, 89, 89]   # v2: 89 for any number
    assert [score.ceiling_of(p1, n) for n in (0, 1, 2)] == [None, None, None]        # v1: no ceiling


def test_ac_v3_01_one_reported_fault_scores_at_most_89(rules):
    s = score.compute(analysis([light()]), aligned(), rules)
    assert s["version"] == "simon.score.v3" and (s["value"], s["grade"], s["fault_cap"]) == (89, "B", 89)
    assert s["uncapped"]["value"] > 89 and s["uncapped"]["grade"] == "A" and "capped_by" not in s


@pytest.mark.parametrize("n", [2, 3, 5])
def test_ac_v3_01_two_or_more_reported_faults_score_at_most_79(rules, n):
    faults = [light(measure=m) for m in ("foot_out", "elbow_flexion", "knee_flexion", "trunk_lean_forward", "shoulder_tilt")[:n]]
    s = score.compute(analysis(faults), aligned(), rules)
    assert (s["value"], s["grade"], s["fault_cap"]) == (79, "C", 79)
    assert s["uncapped"]["value"] > 79 and "capped_by" not in s


def test_ac_v3_01_the_ceiling_counts_entries_so_one_measure_on_two_sides_is_two_faults(rules):
    s = score.compute(analysis([light(side="left"), light(side="right")]), aligned(), rules)
    assert (s["value"], s["fault_cap"]) == (79, 79)


def test_ac_v3_01_a_two_fault_take_below_the_ceiling_still_says_the_ceiling_in_force_and_has_no_uncapped(rules):
    heavy = [fault(mag=100.0, runs=((0, 19),)), fault(measure="elbow_flexion", mag=100.0, runs=((0, 19),))]
    s = score.compute(analysis(heavy), aligned(), rules)
    assert s["value"] < 79 and s["fault_cap"] == 79 and "uncapped" not in s and "capped_by" not in s


def test_ac_v3_01_a_take_without_a_fault_has_no_ceiling_and_no_fault_cap(rules):
    s = score.compute(analysis(), aligned(), rules)
    assert (s["value"], s["grade"]) == (100, "A") and "fault_cap" not in s and "uncapped" not in s


def test_ac_v3_01_under_v2_two_faults_stay_at_89_and_under_v1_there_is_no_ceiling(rules_v2, rules_v1):
    two = analysis([light(), light(measure="elbow_flexion")])
    s2, s1 = score.compute(two, aligned(), rules_v2), score.compute(two, aligned(), rules_v1)
    assert (s2["version"], s2["value"], s2["fault_cap"]) == ("simon.score.v2", 89, 89)
    assert s1["version"] == "simon.score.v1" and s1["value"] > 89 and "fault_cap" not in s1 and "uncapped" not in s1


# ---------------------------------------------------------------- AC-V3-02: fault_cap is the ceiling in force, also on a zero block
def test_ac_v3_02_a_take_with_faults_that_nothing_could_be_measured_on_says_the_ceiling_in_force(rules):
    for faults, cap in (([light()], 89), ([light(), light(measure="elbow_flexion")], 79)):
        s = score.compute(analysis(faults), aligned(nan=True), rules)
        assert (s["value"], s["grade"], s["fault_cap"]) == (0, "F", cap) and "uncapped" not in s
    assert "fault_cap" not in score.compute(analysis(), aligned(nan=True), rules)


def test_ac_v3_02_no_window_compared_and_two_faults_reported_still_has_fault_cap_79(rules):
    uncompared = [{"t_s": (0.0, 5.0), "compared": False}]
    block = score.timeline_block(uncompared, "reps", rules, n_faults=2)
    assert (block["value"], block["fault_cap"]) == (0, 79) and block["timeline"][0]["compared"] is False
    assert score.timeline_block(uncompared, "reps", rules, n_faults=1)["fault_cap"] == 89
    assert "fault_cap" not in score.timeline_block(uncompared, "reps", rules, n_faults=0)


# ---------------------------------------------------------------- AC-V3-03: applied once, to the mean of the windows
def test_ac_v3_03_the_ceiling_is_applied_to_the_mean_and_never_to_a_window(rules):
    windows = [window(95.0, 0), window(97.0, 1)]
    block = score.timeline_block(windows, "windows", rules, n_faults=2)
    assert block["value"] == 79 and block["uncapped"] == {"value": 96, "grade": "A"} and block["fault_cap"] == 79
    assert [w["value"] for w in block["timeline"]] == [95, 97]
    one = score.timeline_block(windows, "windows", rules, n_faults=1)
    assert one["value"] == 89 and one["fault_cap"] == 89 and one["uncapped"] == {"value": 96, "grade": "A"}
    none = score.timeline_block(windows, "windows", rules, n_faults=0)
    assert none["value"] == 96 and "fault_cap" not in none and "uncapped" not in none


def test_ac_v3_03_there_is_no_worst_window_rule(rules):
    assert score.timeline_block([window(100.0, 0), window(60.0, 1)], "windows", rules, n_faults=2)["value"] == 79   # mean 80, not 60
    low = score.timeline_block([window(90.0, 0), window(50.0, 1)], "windows", rules, n_faults=2)   # mean 70: under the ceiling
    assert low["value"] == 70 and low["fault_cap"] == 79 and "uncapped" not in low


def test_ac_v3_03_the_count_is_of_the_takes_faults_list_not_of_a_window(rules):
    """Thirty seconds, six windows, two one-second faults far apart: no window holds both, the take reports two."""
    block = timed_take(rules, 30, 2)
    assert all(len(w["misses"]) <= 1 for w in block["timeline"] if w["compared"])
    assert block["fault_cap"] == 79 and block["value"] <= 79 and block["uncapped"]["value"] > 79


def test_ac_v3_03_one_miss_a_minute_is_capped_at_89_and_two_at_79_whatever_the_length(rules):
    one, two, long_two = timed_take(rules, 60, 1), timed_take(rules, 60, 2), timed_take(rules, 600, 2)
    assert (one["value"], one["fault_cap"]) == (89, 89)
    assert (two["value"], two["fault_cap"], long_two["value"], long_two["fault_cap"]) == (79, 79, 79, 79)


def test_adr_0013_the_score_stays_a_share_of_the_take_before_the_ceiling(either_params):
    """ADR-0013 under v3 (the v1 tests of tests/test_score_timeline.py, written for the value, are skipped while a ceiling is in
    force): the mean of the windows, before the cap, is the same for one miss in a minute and ten in ten minutes, and more misses
    in the same time cost more. Pinned on the test params and on the shipped ones (pre-freeze review R9)."""
    one, ten, crowded = lengths(either_params)
    check_share_of_the_take(one, ten, crowded)
    assert (one["value"], ten["value"], crowded["value"]) == (89, 79, 79)   # then each take is capped by how many faults it reports


def test_adr_0013_each_window_lists_its_misses_and_they_add_up_to_its_value_and_the_take_to_the_mean_before_the_cap(either_params):
    block = timed_take(either_params, 30, 3)
    assert block["basis"] == "windows" and len(block["timeline"]) == 6 and block["fault_cap"] == 79
    check_windows_add_up(block, 6)


# ---------------------------------------------------------------- AC-V3-04: uncapped is the value before every cap; capped_by is the warning only
@pytest.mark.parametrize("rules_name, faults, cap", [("rules_v2", ("foot_out",), 89), ("rules", ("foot_out", "elbow_flexion"), 79)],
                         ids=["v2-one-fault-89", "v3-two-faults-79"])
def test_ac_v2_05_and_ac_v3_04_with_both_caps_uncapped_is_the_value_before_the_first_and_capped_by_names_the_warning_only(
        request, rules_name, faults, cap):
    """AC-V2-05 (v2 rules, one reported fault, ceiling 89) and AC-V3-04 (v3 rules, two reported faults, ceiling 79): the
    ceiling lowers the take to `cap`, the warning to 59; `uncapped` stays the value before the first and `fault_cap` the ceiling."""
    rules = request.getfixturevalue(rules_name)
    a = analysis([light(measure=m) for m in faults], warnings=[{"code": "low_match", "text": "x"}])
    block = score.compute(a, aligned(), rules)
    before = block["uncapped"]
    assert block["value"] == cap and before["value"] > cap
    capped = score.cap_by_warnings(block, a, rules)
    assert capped["value"] == 59 and capped["grade"] == "F" and capped["capped_by"] == ["low_match"]
    assert capped["uncapped"] == before and capped["fault_cap"] == cap


def test_ac_v3_04_a_warning_that_lowers_a_value_the_ceiling_left_alone_gets_its_own_uncapped(rules):
    heavy = analysis([fault(mag=20.0, runs=((0, 19),)), fault(measure="elbow_flexion", mag=20.0, runs=((0, 19),))],
                     warnings=[{"code": "low_match", "text": "x"}])
    block = score.compute(heavy, aligned(), rules)
    assert 59 < block["value"] < 79 and "uncapped" not in block   # under both ceilings: the 79 did not lower it
    capped = score.cap_by_warnings(block, heavy, rules)
    assert capped["uncapped"] == {"value": block["value"], "grade": block["grade"]} and capped["fault_cap"] == 79


# ---------------------------------------------------------------- targets 3 and 5 hold by construction (ADR-0019)
@pytest.mark.parametrize("mean", range(0, 101))
def test_adr_0019_a_take_that_reports_a_fault_is_never_an_a_and_one_that_reports_two_is_never_above_c(rules, mean):
    for n_faults, grades in ((1, "BCDF"), (2, "CDF"), (3, "CDF")):
        block = score.timeline_block([window(float(mean), 0)], "windows", rules, n_faults=n_faults)
        assert block["grade"] in grades and block["value"] <= block["fault_cap"], (mean, n_faults)
    block = score.timeline_block([window(float(mean), 0)], "windows", rules, n_faults=0)
    assert block["value"] == mean and "fault_cap" not in block   # no fault, no ceiling: a correct take can be an A


# ---------------------------------------------------------------- AC-V3-05: the rules keep v1 and v2 verbatim
def test_ac_v3_05_block_v3_is_v1s_numbers_the_v2_params_the_second_ceiling_and_both_frozen_blocks():
    v1, v2 = frozen_v1(), frozen_v2()
    block = score.block_v3(v1, v2, 0.8)
    assert block["version"] == "simon.score.v3" and block["range_floor"] == 0.8 and block["v1"] == v1 and block["v2"] == v2
    assert {k: block[k] for k in score.SHARED_V1} == {k: v1[k] for k in score.SHARED_V1}
    assert (block["range_full"], block["fault_cap"], block["fault_cap_many"], block["many_faults"]) == (3.0, 89, 79, 2)
    assert set(block) == {"version", *score.SHARED_V1, "range_floor", "range_full", "fault_cap", "fault_cap_many", "many_faults",
                          "calibrated_on", "v1", "v2"}


def test_ac_v3_05_the_frozen_blocks_hash_to_what_was_recorded_for_them():
    assert score.params_sha256(frozen_v1()) == V1_SHA and score.params_sha256(frozen_v2()) == V2_SHA
    record = json.loads((ROOT / "fixtures/score-heldout.json").read_text())
    assert {f["params_sha256"] for f in record["freezes"] if f["version"] == V2} == {V2_SHA}   # the freeze of seed 59


@v3_only
def test_ac_v3_05_the_shipped_section_keeps_v1_and_v2_byte_for_byte_beside_the_v3_params():
    section = load_rules()["score"]
    assert section["version"] == "simon.score.v3"
    assert score.params_sha256(section["v1"]) == V1_SHA and score.params_sha256(section["v2"]) == V2_SHA
    assert section["v2"]["v1"] == section["v1"]
    for key in score.SHARED_V1:
        assert section[key] == section["v1"][key], key
    assert section["range_floor"] == FLOOR, "tests/shipped_score.FLOOR is the floor the rule picked; change it there"
    assert (section["range_full"], section["fault_cap"], section["fault_cap_many"], section["many_faults"]) == (3.0, 89, 79, 2)
    assert section == score.block_v3(section["v1"], section["v2"], FLOOR)
    assert check.detection_hash() == DETECTION_SHA   # detection untouched: the hash leaves the score section out


def test_ac_v3_05_rules_of_swaps_the_kept_block_in_and_says_what_is_missing():
    v1, v2 = frozen_v1(), frozen_v2()
    shipped = {**load_rules(), "score": score.block_v3(v1, v2, FLOOR)}
    assert score.rules_v1(shipped)["score"] == v1 and score.rules_v2(shipped)["score"] == v2
    assert score.params_of(score.rules_v2(shipped))["version"] == "simon.score.v2"
    with pytest.raises(ValueError, match="no simon.score.v2 'v2' block"):
        score.rules_v2({"score": {"version": "simon.score.v3"}})
    with pytest.raises(ValueError, match="no simon.score.v1 'v1' block"):
        score.rules_v1({"score": {"version": "simon.score.v3", "v2": v2}})


@pytest.mark.parametrize("version", [V1, V2])
def test_ac_v3_05_ships_and_has_ceiling_read_the_version_the_rules_name(version):
    v1, v2 = frozen_v1(), frozen_v2()
    rules = {"score": {V1: v1, V2: v2}[version]}
    assert score.ships(version, rules) and not score.ships(V3, rules)
    assert score.has_ceiling(rules) is (version == V2)
    assert score.has_ceiling({"score": score.block_v3(v1, v2, FLOOR)}) and score.ships(V3, {"score": score.block_v3(v1, v2, FLOOR)})


def test_ac_v3_05_one_take_through_the_pipeline_has_a_v1_a_v2_and_a_v3_value_from_the_kept_blocks(seed5_scored):
    shipped = v3_rules()
    # (v1, v2, v3) per take: v2 and v3 differ only for a take that reports two or more faults, and only above the 79 ceiling
    want = {"exercise_front_good_08_arms_wider-both+elbow_bent-right": ((67, "D"), (75, "C"), (75, "C")),
            "exercise_front_good_00_correct": ((100, "A"), (100, "A"), (100, "A")),
            "dance_side_good_11_ankle_rolled_in-right": ((93, "A"), (89, "B"), (89, "B"))}
    for take, result in (x for x in seed5_scored[2] if x[0]["take_id"] in want):
        blocks = [score_report.score_block(result, r) for r in (score.rules_v1(shipped), score.rules_v2(shipped), shipped)]
        assert [b["version"] for b in blocks] == [V1, V2, V3]
        assert [(b["value"], b["grade"]) for b in blocks] == list(want[take["take_id"]]), take["take_id"]
        assert [b.get("fault_cap") for b in blocks][0] is None


def test_ac_v3_05_a_real_rep_by_rep_take_with_two_faults_is_80_b_under_v1_82_b_under_v2_and_79_c_under_v3():
    lateral_raise, shipped = lateral_raise_run(), v3_rules()
    b1, b2, b3 = (score_report.score_block(lateral_raise, r) for r in (score.rules_v1(shipped), score.rules_v2(shipped), shipped))
    assert len(lateral_raise.analysis["faults"]) == 2 and b3["basis"] == "reps"
    assert [(b["value"], b["grade"]) for b in (b1, b2, b3)] == [(80, "B"), (82, "B"), (79, "C")]
    assert "fault_cap" not in b1 and b2["fault_cap"] == 89 and "uncapped" not in b2
    assert (b3["fault_cap"], b3["uncapped"]) == (79, {"value": 82, "grade": "B"}) and "capped_by" not in b3
    assert [w["value"] for w in b3["timeline"] if w["compared"]] == [w["value"] for w in b2["timeline"] if w["compared"]]   # no window capped


def test_ac_v3_03_the_rep_by_rep_take_is_scored_on_each_reps_own_misses_and_its_mean_is_the_value_before_the_ceiling():
    """The v1 test of tests/test_reps.py (a teammate's, skipped while v3 ships) pinned the first reps clean, the later ones with
    misses, each rep adding up to its points and the take being the mean of the reps; under v3 the mean is `uncapped`."""
    sc = score_report.score_block(lateral_raise_run(), v3_rules())
    timeline = [w for w in sc["timeline"] if w["compared"]]
    assert sc["basis"] == "reps" and len(sc["per_rep"]) == 8
    assert all(w["misses"] == [] and w["value"] >= 90 for w in timeline[:3]) and all(w["misses"] for w in timeline[4:])
    check_windows_add_up(sc, 8)
    assert sc["value"] == sc["fault_cap"] == 79 < sc["uncapped"]["value"]


# ---------------------------------------------------------------- AC-V3-06: the floor rule, run again under the v3 code, on seed 5 only
@pytest.fixture(scope="module")
def rule_run(seed5_scored):
    """ADR-0018's rule under the v3 code (the doubles measured after the 79 ceiling): (block, measurements per floor of the grid)."""
    labels, _, results = seed5_scored
    return score_report.calibrate_floor_set(labels, v3_rules(), results=results, version=V3)


def test_ac_v3_06_the_rule_run_under_the_v3_code_picks_the_shipped_floor_and_returns_the_shipped_block(rule_run):
    """About 20 s: eleven floors, each with the sweep. The unchanged rule gives the v2 floor again (no hand nudge, ADR-0019)."""
    block, measured = rule_run
    assert score.choose_floor(measured) == block["range_floor"] == FLOOR
    assert block == v3_rules()["score"]
    if IS_V3:
        assert block == load_rules()["score"]


def test_ac_v3_06_the_table_under_v3_differs_from_v2s_only_where_the_79_ceiling_lowers_a_double(rule_run, seed5_scored):
    labels, _, results = seed5_scored
    _, v3 = rule_run
    _, v2 = score_report.calibrate_floor_set(labels, v2_rules(), results=results, version=V2)
    for floor in score.FLOOR_GRID:
        a, b = v2[floor], v3[floor]
        assert (a["correct_all_a"], a["single_min"], a["sweep_rises"]) == (b["correct_all_a"], b["single_min"], b["sweep_rises"]), floor
        assert a["double_max"] == b["double_max_uncapped"] and b["double_max"] == min(a["double_max"], 79), floor
        assert score.floor_holds(a) == score.floor_holds(b), floor   # the same rule, the same answer at every floor
    assert [f for f in score.FLOOR_GRID if v3[f]["double_max_uncapped"] > 79] == [0.5, 0.55, 0.6]   # where the ceiling binds on seed 5


def test_ac_v3_06_on_seed_5_the_shipped_v3_block_meets_the_conditions_and_the_four_targets(seed5_scored):
    labels, _, results = seed5_scored
    rules = v3_rules()
    m = score_report.measure_floor(results, rules)
    assert score.floor_holds(m) and m["correct_all_a"] and m["single_min"] >= 70 and m["double_max"] <= 75 and not m["sweep_rises"]
    scored = score_report.scored_results(labels, rules, results=results)
    entries = [(tk, r.analysis, b) for tk, r, b in scored]
    t = score_report.targets_v2(entries)
    assert [t[k]["verdict"] for k in score_report.TARGET_KEYS] == ["pass"] * 4
    beside = score_report.beside_targets(entries, score_report.verdicts(score_report.distribution([(tk, b) for tk, _, b in scored])))
    assert beside["n"] == 5 and beside["lowered"] == 0 and beside["d_or_f"] + beside["c"] == 5   # the ceiling does no work on seed 5


def test_ac_v3_06_calibrate_v3_on_seed_5_prints_the_table_with_the_value_before_the_cap_and_the_block(tmp_path, capsys, monkeypatch):
    labels = json.loads((ROOT / "fixtures/input/followers/labels.json").read_text())
    (tmp_path / "labels.json").write_text(json.dumps({**labels, "takes": []}))
    block = score.block_v3(frozen_v1(), frozen_v2(), 0.8)
    m = {"correct_all_a": True, "single_min": 75, "double_max": 79, "double_max_uncapped": 83, "sweep_rises": False}
    seen = {}
    monkeypatch.setattr(score_report, "calibrate_floor_set", lambda *a, **k: seen.update(k) or (block, {0.8: m}))
    assert score_report.main(["--calibrate-v3", "--set", str(tmp_path)]) == 0
    out, err = capsys.readouterr()
    assert json.loads(out) == block and seen["version"] == V3
    assert "before cap" in err and "83" in err and "<- chosen" in err


def test_ac_v3_06_calibrate_set_gives_the_v3_form_to_rules_that_ship_it(monkeypatch):
    labels, shipped = {"takes": []}, v3_rules()
    seen = {}
    monkeypatch.setattr(score_report, "calibrate_floor_set", lambda *a, **k: seen.update(k) or ("v3 form", {}))
    assert score_report.calibrate_set(labels, shipped) == "v3 form" and seen["version"] == V3
    monkeypatch.setattr(score_report, "calibrate_floor_set", lambda *a, **k: ("v2 form", {}))
    assert score_report.calibrate_set(labels, v2_rules()) == "v2 form"
    no_v2 = {**shipped, "score": {k: v for k, v in shipped["score"].items() if k != "v2"}}   # a v3 section that lost its v2 block
    monkeypatch.setattr(score_report, "rows_of_set", lambda *a, **k: "rows")
    monkeypatch.setattr(score, "calibrate", lambda rows, min_fraction: ("v1 calibration", rows, min_fraction))
    assert score_report.calibrate_set(labels, no_v2)[0] == "v1 calibration"


# ---------------------------------------------------------------- AC-V3-09: published beside the targets
def double(take_id, before, after=None, cap=79, labelled=2, reported=2):
    """(label, analysis, v3 score block) of a take with two labelled faults that reports `reported` of them: `before` the
    ceiling, `after` it (default: the lower of before and the cap)."""
    after = min(before, cap) if after is None else after
    block = {"value": after, "grade": score.grade(after), "fault_cap": cap}
    if before > after:
        block["uncapped"] = {"value": before, "grade": score.grade(before)}
    plant = [("foot_out", "left", "more", "foot_out"), ("arms_wider", "both", "more", "upper_arm_out")]
    label = {"take_id": take_id, "lighting": "good", "faults": [{"type": t, "side": s, "direction": d} for t, s, d, _ in plant[:labelled]]}
    found = {"faults": [{"measure": m, "side": "left", "direction": d} for _, _, d, m in plant[:reported]]}
    return label, found, block


def test_ac_v3_09_beside_the_targets_each_exact_doubles_value_before_and_after_the_ceiling_and_how_many_it_lowered():
    entries = [double("lowered-b", 85), double("lowered-a", 91), double("kept-c", 76), double("kept-d", 66), double("kept-f", 40)]
    beside = score_report.beside_targets(entries, {"good/0": "pass", "good/1": "fail", "good/2": "pass"})
    assert [(r["take_id"], r["before"], r["after"], r["lowered"]) for r in beside["doubles"]] == [
        ("lowered-b", 85, 79, True), ("lowered-a", 91, 79, True), ("kept-c", 76, 76, False), ("kept-d", 66, 66, False),
        ("kept-f", 40, 40, False)]
    assert (beside["n"], beside["lowered"], beside["d_or_f"], beside["c"]) == (5, 2, 2, 3)   # C: the two lowered and 76
    assert beside["strict_verdicts"] == {"good/0": "pass", "good/1": "fail", "good/2": "pass"}


def test_ac_v3_09_only_takes_that_report_exactly_their_two_faults_are_doubles_and_low_light_is_left_out():
    missed = double("missed-one", 90, reported=1)         # one of two found: a detection result, not a double
    extra = double("extra", 90, reported=2, labelled=1)   # one label, two reported: not a double either
    low = double("low", 90)
    low[0]["lighting"] = "low"
    beside = score_report.beside_targets([missed, extra, low, double("exact", 90)], {})
    assert [r["take_id"] for r in beside["doubles"]] == ["exact"]


def test_ac_v3_09_a_warning_that_also_lowered_the_value_does_not_hide_the_value_before_the_ceiling():
    entry = double("both", 90)
    entry[2].update(value=59, grade="F", capped_by=["low_match"])   # cap_by_warnings keeps the `uncapped` of the first cap
    beside = score_report.beside_targets([entry], {})
    assert (beside["doubles"][0]["before"], beside["doubles"][0]["after"], beside["doubles"][0]["lowered"]) == (90, 59, True)


def test_ac_v3_09_the_lines_name_what_was_lowered_the_d_or_f_reading_and_the_strict_verdicts():
    entries = [double("lowered", 85), double("kept", 66)]
    beside = score_report.beside_targets(entries, {"good/0": "pass", "good/1": "pass", "good/2": "pass"})
    text = "\n".join(score_report.beside_lines(beside))
    for needle in ("published beside the targets (as measured, not targets; ADR-0019)", "the 79 ceiling lowered 1 of 2",
                   "lowered: 85 -> 79 (C) lowered", "kept: 66 -> 66 (D)", "ADR-0007's reading of the doubles (D or F): 1 of 2 grade D or F, 1 grade C",
                   "strict slice verdicts (every take of the slice, nothing excluded): good/0 pass, good/1 pass, good/2 pass"):
        assert needle in text, needle


def test_ac_v3_09_the_comparability_sentence_of_v3_says_the_targets_3_and_5_hold_by_construction():
    assert score_report.comparability_of(V3) == score_report.COMPARABILITY_V3
    assert score_report.comparability_of(V2) == score_report.COMPARABILITY
    for text in ("v1 itself would have met targets 1, 3, 4 and 5", "v3 does not break those targets", "not that it fixes v1's recorded misses",
                 "targets 3 and 5 hold by construction", "ADR-0019"):
        assert text in score_report.COMPARABILITY_V3, text


SMALL = ("exercise_front_good_00_correct", "exercise_front_good_03_foot_out-right", "exercise_front_good_08_arms_wider-both+elbow_bent-right")


def test_ac_v3_09_the_text_report_prints_the_five_targets_then_the_measures_beside_them_then_the_sentence(tmp_path, capsys, report_as):
    report_as(v3_rules)
    assert score_report.main(["--set", str(small_set(tmp_path, SMALL))]) == 0
    out = capsys.readouterr().out
    assert "simon.score.v3" in out and "ADR-0018 targets" in out and "all five hold: yes" in out
    assert out.index("all five hold") < out.index("published beside the targets") < out.index(score_report.COMPARABILITY_V3)
    assert "exercise_front_good_08_arms_wider-both+elbow_bent-right: 75 -> 75 (C)" in out and "the 79 ceiling lowered 0 of 1" in out
    assert "strict slice verdicts" in out and "targets 3 and 5 hold by construction" in out


def test_ac_v3_09_the_json_carries_the_same_beside_the_targets_and_holds(tmp_path, capsys, report_as):
    report_as(v3_rules)
    assert score_report.main(["--set", str(small_set(tmp_path, SMALL)), "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["version"] == "simon.score.v3" and doc["targets_v2"]["holds"] is True
    beside = doc["beside_targets"]
    assert beside["n"] == 1 and beside["lowered"] == 0 and beside["doubles"][0]["before"] == beside["doubles"][0]["after"] == 75
    assert beside["strict_verdicts"] == doc["verdicts"]


def test_ac_v3_09_a_v2_report_has_no_measures_beside_its_targets(tmp_path, capsys, report_as):
    report_as(v2_rules)
    assert score_report.main(["--set", str(small_set(tmp_path, SMALL)), "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["version"] == "simon.score.v2" and "beside_targets" not in doc and doc["targets_v2"]["holds"] is True


def test_ac_v3_09_a_v3_report_that_has_no_double_still_fails_closed_and_says_so(tmp_path, capsys, report_as):
    report_as(v3_rules)
    only_single = ("exercise_front_good_00_correct", "exercise_front_good_03_foot_out-right")
    assert score_report.main(["--set", str(small_set(tmp_path, only_single))]) == 0
    out = capsys.readouterr().out
    assert "all five hold: no" in out and "the 79 ceiling lowered 0 of 0" in out


# ---------------------------------------------------------------- pre-freeze review R6, R7: what the report says is settled and what it counts
def test_r6_the_comparability_line_says_targets_2_3_and_5_are_settled_before_seed_61_and_only_1_and_4_test_anything():
    text = score_report.COMPARABILITY_V3
    for needle in ("targets 2, 3 and 5 are settled before seed 61", "Random(1234)", "never reads the seed",
                   "targets 3 and 5 hold by construction", "only targets 1 and 4 test anything"):
        assert needle in text, needle
    assert "settled before" not in score_report.COMPARABILITY   # v2's sentence is as it was published for seed 59


def test_r11_the_two_comparability_sentences_share_one_template():
    """v3's sentence is v2's with the version changed and the settled-before-seed-61 statement added: no second copy to drift."""
    v2 = score_report.COMPARABILITY
    assert score_report.COMPARABILITY_V3.startswith(v2.replace("v2 does not break", "v3 does not break"))


def test_r7_the_report_says_what_the_ceiling_counts_beside_the_targets():
    beside = score_report.beside_targets([double("exact", 85)], {"good/0": "pass", "good/1": "pass", "good/2": "pass"})
    text = "\n".join(score_report.beside_lines(beside))
    for needle in ("counts the entries of the take's faults list", "same direction with overlapping frames", "two entries put the 79 ceiling"):
        assert needle in text, needle


# ---------------------------------------------------------------- R13: score.fault_cap must be the ceiling in force
def golden_with(n_faults, version, cap="absent"):
    """A valid golden analysis that reports `n_faults` faults (0, 1 or 2) with its score block made the `version` score and its
    `fault_cap` set to `cap` ("absent": left out)."""
    name = "analysis.no-faults.example.json" if n_faults == 0 else "analysis.example.json"
    doc = json.loads((ROOT / "fixtures/output" / name).read_text())
    if n_faults == 1:
        doc["faults"], doc["phrasing"]["faults"] = doc["faults"][:1], doc["phrasing"]["faults"][:1]
    doc["score"]["version"] = version
    doc["score"].pop("fault_cap", None)
    if cap != "absent":
        doc["score"]["fault_cap"] = cap
    return doc


@pytest.mark.parametrize("version, n_faults, cap", [(V3, 0, "absent"), (V3, 1, 89), (V3, 2, 79), (V2, 0, "absent"), (V2, 1, 89),
                                                    (V2, 2, 89), (V1, 0, "absent"), (V1, 2, "absent")])
def test_r13_a_document_that_carries_the_ceiling_in_force_validates(version, n_faults, cap):
    output.validate_analysis(golden_with(n_faults, version, cap))
    assert score.document_ceiling(version, n_faults) == (None if cap == "absent" else cap)


@pytest.mark.parametrize("version, n_faults, cap, message", [
    (V3, 2, 89, "must be 79 for a simon.score.v3 take that reports 2 faults, got 89"),     # the producer bug the review named
    (V3, 1, 79, "must be 89 for a simon.score.v3 take that reports 1 fault, got 79"),
    (V3, 2, "absent", "must be 79 for a simon.score.v3 take that reports 2 faults, got None"),
    (V3, 2, True, "must be 79 for a simon.score.v3 take that reports 2 faults, got True"),
    (V3, 2, 79.5, "must be 79 for a simon.score.v3 take that reports 2 faults, got 79.5"),
    (V2, 2, 79, "must be 89 for a simon.score.v2 take that reports 2 faults, got 79"),
    (V2, 1, "absent", "must be 89 for a simon.score.v2 take that reports 1 fault, got None"),
    (V3, 0, 89, "must be absent for a take that reports no fault, got 89"),
    (V2, 0, 89, "must be absent for a take that reports no fault, got 89"),
    (V1, 1, 89, "must be absent from a simon.score.v1 score block, which has no ceiling, got 89"),   # v1 has no ceiling to write
    (V1, 2, 79, "must be absent from a simon.score.v1 score block, which has no ceiling, got 79"),
    (V1, 0, 89, "must be absent from a simon.score.v1 score block, which has no ceiling, got 89"),
    (V1, 2, None, "must be absent from a simon.score.v1 score block, which has no ceiling, got None")])
def test_r13_a_document_whose_fault_cap_is_not_the_ceiling_in_force_is_refused(version, n_faults, cap, message):
    with pytest.raises(output.OutputError, match="score.fault_cap " + message):
        output.validate_analysis(golden_with(n_faults, version, cap))


def test_r13_the_check_leaves_the_at_s_rule_of_ticket_061_and_a_score_of_none_alone():
    doc = golden_with(2, V3, 79)
    doc["faults"][0]["at_s"] = doc["faults"][0]["follower_t_s"][0] + 0.5
    with pytest.raises(output.OutputError, match="at_s"):
        output.validate_analysis(doc)
    old = golden_with(2, V3, 79)
    old["score"] = None
    output.validate_analysis(old)   # a refused take of 1.3.0 or earlier had no score: nothing to check
