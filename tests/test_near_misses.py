"""docs/specs/near-misses.md: the candidate faults detection considered and dropped (TICKET-043, analysis 1.8.0).

AC-NM-01 (purely additive), AC-NM-02 to 06 (candidates, persistence, size, frames, explained_by), AC-NM-07 (the bound),
AC-NM-08 (no candidates, no detection), AC-NM-09 (sides and NaN), AC-NM-10 (determinism), AC-NM-11 (profiles), AC-NM-13
(the contract: validation, schema, doctor) and AC-NM-NFR-02. Rep mode (AC-NM-12) is in tests/test_near_misses_reps.py.
The `seed5` fixture is in tests/conftest.py."""
import copy
import json
import re
from pathlib import Path

import jsonschema
import numpy as np
import pytest

from part5 import contract, doctor, pipeline, profiles
from part5.align import Alignment, AlignmentError, align
from part5.detect import (EXPLAINED_BY, MAX_NEAR_MISSES, PERSISTENCE, REPORTED, Detection, detect, detect_full,
                          load_rules, on_file, reports, summary)
from part5.io import load_clip
from part5.measures import MEASURES, compute
from part5.normalise import normalise
from part5.output import OutputError, validate_analysis, write_analysis

ROOT = Path(__file__).resolve().parent.parent
EXPECTED = ROOT / "fixtures/input/expected/exercise/animation.json"
SCHEMA = contract.load_schema("analysis")
LABELS = json.loads((ROOT / "fixtures/input/followers/labels.json").read_text())


def synthetic(n, **spans):
    """All measures zero except `name=[(start, end, value), ...]` (inclusive frames); NaN values stay NaN."""
    m = {k: np.zeros(n) for k in MEASURES}
    for name, runs in spans.items():
        for s, e, v in runs:
            m[name][s:e + 1] = v
    return m


def identity(n, shift=0):
    exp_to_fol = np.arange(n) + shift
    return Alignment([(i, i + shift) for i in range(n)], exp_to_fol, np.linspace(0, 1, n), 0.0, [])


def rules_with(smooth=1, **default):
    """The shipped rules with no smoothing (so a run is as long as it is written), both floors at the 8 frames the floor
    was before attempt 4 (these cases are worked out for it; the measures here are body measures, so
    `min_frames_floor_body` decides) and `default` on top."""
    r = copy.deepcopy(load_rules())
    r["smooth_frames"] = smooth
    r["default"].update({"min_frames_floor": 8, "min_frames_floor_body": 8}, **default)
    return r


def found(n, rules=None, **spans):
    return detect_full(synthetic(n), synthetic(n, **spans), identity(n), rules or rules_with())


def only(detection, measure, side="left", direction="more"):
    [c] = [c for c in detection.candidates if (c.measure, c.side, c.direction) == (measure, side, direction)]
    return c


def keys(faults):
    return sorted((f.measure, f.side, f.direction) for f in faults)


# --- AC-NM-03: a persistence shortfall, with the numbers ---
def test_a_run_too_short_in_total_is_a_persistence_near_miss_with_its_numbers():
    """100 frames, min_fraction 0.38 (38 frames needed): a 30 frame upper arm run, 8 short. The shape of the reporter's
    take (68 counted, 114 needed on 300 frames)."""
    d = found(100, left_upper_arm_out=[(10, 39, 25.0)])
    assert d.faults == []
    [miss] = d.near_misses
    assert (miss.measure, miss.side, miss.direction, miss.joint, miss.body_part) == (
        "upper_arm_out", "left", "more", "left_shoulder", "arms")
    assert (miss.outcome, miss.frames_over, miss.counted_frames, miss.needed_frames, miss.min_run_frames) == (
        PERSISTENCE, 30, 30, 38, 4)
    item = miss.to_dict()
    assert item["reason"] == "persistence" and item["shortfall_frames"] == 8 and "explained_by" not in item
    assert item["threshold_deg"] == load_rules()["measures"]["upper_arm_out"]["threshold_deg"] == 11.0
    assert item["magnitude_deg"] == item["peak_deg"] == 25.0


def test_runs_shorter_than_min_run_frames_add_to_frames_over_and_not_to_counted_frames():
    d = found(100, left_upper_arm_out=[(5, 7, 25.0), (20, 29, 25.0)])
    miss = only(d, "upper_arm_out")
    assert (miss.frames_over, miss.counted_frames) == (13, 10)
    assert miss.expected_frames == (20, 29) and miss.to_dict()["shortfall_frames"] == 28


def test_with_no_run_long_enough_nothing_counts_and_the_size_is_over_every_frame_past_the_threshold():
    d = found(100, left_upper_arm_out=[(5, 7, 20.0), (40, 41, 30.0)])
    miss = only(d, "upper_arm_out")
    assert (miss.frames_over, miss.counted_frames) == (5, 0)
    assert miss.magnitude_deg == 20.0 and miss.peak_deg == 30.0       # median and largest of 20, 20, 20, 30, 30
    assert miss.expected_frames == (5, 7) and miss.to_dict()["shortfall_frames"] == miss.needed_frames == 38


@pytest.mark.parametrize("changes, needed", [
    ({}, 38),                                               # round(0.38 x 100)
    ({"min_fraction": 0.2}, 20),
    ({"min_fraction": 0.05, "min_frames_floor_body": 30}, 30),   # the floor wins (the body floor: this is a body measure)
    ({"min_frames": 55}, 55),                               # an explicit count wins over both
])
def test_the_frames_needed_come_from_min_fraction_the_floor_or_min_frames(changes, needed):
    d = found(100, rules_with(**changes), left_upper_arm_out=[(10, 17, 25.0)])
    miss = only(d, "upper_arm_out")
    assert miss.needed_frames == needed and miss.to_dict()["shortfall_frames"] == needed - 8


# --- AC-NM-04 and AC-NM-05: size and frames ---
def test_a_candidate_that_persists_is_a_reported_fault_and_has_its_size_and_frames():
    d = found(100, left_upper_arm_out=[(10, 59, 25.0)])
    [fault] = d.faults
    cand = only(d, "upper_arm_out")
    assert cand.outcome == REPORTED and d.near_misses == []
    assert (cand.magnitude_deg, cand.peak_deg) == (fault.magnitude_deg, fault.peak_deg)
    assert cand.expected_frames == fault.expected_frames and cand.follower_frames == fault.follower_frames
    assert cand.persists and cand.counted_frames == 50


def test_a_less_than_the_example_candidate_is_negative_and_a_more_one_positive():
    d = found(100, left_upper_arm_out=[(10, 25, -25.0)], right_upper_arm_out=[(10, 25, 25.0)])
    assert only(d, "upper_arm_out", "left", "less").magnitude_deg == -25.0
    assert only(d, "upper_arm_out", "right", "more").magnitude_deg == 25.0
    assert keys(d.near_misses) == [("upper_arm_out", "left", "less"), ("upper_arm_out", "right", "more")]


def test_the_frames_are_the_longest_run_and_the_follower_frames_follow_the_alignment():
    """The follower starts 7 frames late: expected frame i is follower frame i + 7."""
    follower = synthetic(107, left_upper_arm_out=[(17, 21, 25.0), (37, 51, 25.0), (67, 71, 25.0)])
    d = detect_full(synthetic(100), follower, identity(100, shift=7), rules_with())
    miss = only(d, "upper_arm_out")
    assert miss.expected_frames == (30, 44) and miss.follower_frames == (37, 51)
    twin = found(100, left_upper_arm_out=[(10, 14, 25.0), (30, 34, 25.0)])
    assert only(twin, "upper_arm_out").expected_frames == (10, 14)    # equal runs: the earliest


def test_on_file_maps_the_follower_frames_to_the_follower_files_own():
    miss = found(100, left_upper_arm_out=[(10, 20, 25.0)]).near_misses
    [mapped] = on_file(miss, np.arange(200) * 2)
    assert miss[0].follower_frames == (10, 20) and mapped.follower_frames == (20, 40)
    assert on_file([], np.arange(3)) == []


# --- AC-NM-06: explained_by ---
def test_a_fault_a_kept_fault_explains_is_an_explained_by_near_miss_that_names_the_cause():
    d = detect_full(synthetic(60), synthetic(60, trunk_lean_forward=[(10, 50, 12.0)], head_forward=[(10, 50, 35.0)]),
                    identity(60), load_rules())
    assert keys(d.faults) == [("trunk_lean_forward", "center", "more")]
    [miss] = d.near_misses
    assert (miss.measure, miss.outcome, miss.counted_frames >= miss.needed_frames) == ("head_forward", EXPLAINED_BY, True)
    item = miss.to_dict()
    assert item["explained_by"] == {"measure": "trunk_lean_forward", "side": "center", "direction": "more"}
    assert item["reason"] == "explained_by" and "shortfall_frames" not in item


def test_a_dropped_fault_never_explains_another_and_a_chain_is_named_from_its_root():
    """trunk explains foot_out, foot_out would explain thigh_out; the dropped foot_out cannot, so thigh_out is a fault."""
    rules = rules_with(min_fraction=0.1)
    rules["explained_by"] = {"foot_out": ["trunk_lean_forward"], "thigh_out": ["foot_out"]}
    d = found(100, rules, trunk_lean_forward=[(10, 60, 15.0)], right_foot_out=[(10, 60, 10.0)],
              right_thigh_out=[(10, 60, 20.0)])
    assert keys(d.faults) == [("thigh_out", "right", "more"), ("trunk_lean_forward", "center", "more")]
    [miss] = d.near_misses
    assert (miss.measure, miss.explained_by) == ("foot_out", ("trunk_lean_forward", "center", "more"))
    assert only(d, "thigh_out", "right").outcome == REPORTED


def test_when_two_kept_faults_explain_it_the_larger_one_is_named():
    rules = rules_with(min_fraction=0.1)
    rules["explained_by"] = {"forearm_out": ["upper_arm_out", "trunk_lean_forward"]}
    d = found(100, rules, left_forearm_out=[(10, 60, 25.0)], left_upper_arm_out=[(10, 60, 20.0)],
              trunk_lean_forward=[(10, 60, 30.0)])
    [miss] = d.near_misses
    assert miss.measure == "forearm_out" and miss.explained_by == ("trunk_lean_forward", "center", "more")


def test_a_cause_that_was_merged_to_both_sides_is_named_as_reported():
    arms = [(10, 50, 25.0)]
    d = found(60, rules_with(min_fraction=0.1), left_upper_arm_out=arms, right_upper_arm_out=arms,
              left_forearm_out=[(10, 50, 25.0)])
    assert keys(d.faults) == [("upper_arm_out", "both", "more")]
    [miss] = d.near_misses
    assert (miss.measure, miss.side, miss.explained_by) == ("forearm_out", "left", ("upper_arm_out", "both", "more"))
    assert miss.to_dict()["explained_by"]["side"] == "both"


def test_a_cycle_in_the_rules_does_not_loop_and_still_names_a_cause():
    rules = rules_with(min_fraction=0.1)
    rules["explained_by"] = {"foot_out": ["thigh_out"], "thigh_out": ["foot_out"]}
    d = found(100, rules, left_foot_out=[(10, 60, 20.0)], left_thigh_out=[(10, 60, 20.0)])
    assert len(d.faults) + len(d.near_misses) == 2 and d.near_misses
    for miss in d.near_misses:
        assert miss.outcome == EXPLAINED_BY and miss.explained_by[0] in ("foot_out", "thigh_out")


# --- AC-NM-07 and AC-NM-08: the bound, and no candidates ---
NAMES = [m for m in MEASURES if m.startswith(("left_", "right_"))][:12]


def many(count):
    """`count` measures each with a 5 frame run (too short to persist), larger the earlier they come."""
    return {name: [(10, 14, 60.0 - 2 * i)] for i, name in enumerate(NAMES[:count])}


def test_the_list_is_bounded_and_counts_the_rest():
    near = detect_full(synthetic(100), synthetic(100, **many(12)), identity(100), rules_with()).near_misses
    block = summary(near)
    assert len(near) == 12 and MAX_NEAR_MISSES == 10
    assert (block["total"], block["omitted"], len(block["items"])) == (12, 2, 10)
    assert [abs(i["magnitude_deg"]) for i in block["items"]] == [60.0 - 2 * i for i in range(10)]   # the 10 largest, in order
    assert summary(near[:10])["omitted"] == 0 and summary(near[:3])["total"] == 3


def test_equal_sizes_are_ordered_by_measure_side_and_direction_so_the_list_is_fixed():
    spans = {name: [(10, 14, 25.0)] for name in ("right_upper_arm_out", "left_upper_arm_out", "left_forearm_out")}
    items = summary(detect_full(synthetic(100), synthetic(100, **spans), identity(100), rules_with()).near_misses)["items"]
    assert [(i["measure"], i["side"]) for i in items] == [
        ("forearm_out", "left"), ("upper_arm_out", "left"), ("upper_arm_out", "right")]


def test_a_take_with_no_frame_past_any_threshold_has_no_candidate_and_an_empty_block():
    d = found(100)
    assert d.candidates == [] and d.near_misses == [] and d.faults == []
    assert summary(d.near_misses) == {"total": 0, "omitted": 0, "items": []}
    assert found(100, left_upper_arm_out=[(10, 59, 9.9)]).candidates == []     # just under the threshold of 10


def test_detect_builds_no_candidate_and_returns_the_same_faults():
    """AC-NM-NFR-02: the call the calibration sweeps make does no candidate work."""
    spans = dict(left_upper_arm_out=[(10, 59, 25.0)], right_forearm_out=[(10, 14, 40.0)])
    full, plain = found(100, **spans), detect(synthetic(100), synthetic(100, **spans), identity(100), rules_with())
    assert plain == full.faults and full.candidates
    assert detect_full(synthetic(100), synthetic(100, **spans), identity(100), rules_with(), candidates=False) == \
        Detection(plain, [])


# --- AC-NM-09: sides and NaN ---
def test_sides_are_never_merged_a_side_that_persists_is_reported_and_the_other_is_a_near_miss():
    d = found(100, left_upper_arm_out=[(10, 59, 25.0)], right_upper_arm_out=[(10, 39, 25.0)])
    assert keys(d.faults) == [("upper_arm_out", "left", "more")]
    [miss] = d.near_misses
    assert (miss.side, miss.joint) == ("right", "right_shoulder") and miss.outcome == PERSISTENCE
    both = found(100, left_upper_arm_out=[(10, 59, 25.0)], right_upper_arm_out=[(10, 59, 25.0)])
    assert keys(both.faults) == [("upper_arm_out", "both", "more")] and both.near_misses == []
    assert sorted(c.side for c in both.candidates) == ["left", "right"]     # the candidates stay per side


def test_a_frame_with_no_value_is_never_past_a_threshold_and_counts_in_no_field():
    nan = float("nan")
    d = found(100, left_upper_arm_out=[(10, 29, 25.0), (30, 39, nan), (40, 49, 25.0)], right_elbow_flexion=[(0, 99, nan)])
    miss = only(d, "upper_arm_out")
    assert (miss.frames_over, miss.counted_frames, miss.expected_frames) == (30, 30, (10, 29))
    assert miss.needed_frames == 38 and miss.magnitude_deg == 25.0
    assert not [c for c in d.candidates if c.measure == "elbow_flexion"]


def test_with_the_shipped_smoothing_a_two_frame_blip_is_no_candidate_and_a_longer_run_keeps_its_ends():
    rules = load_rules()
    assert rules["smooth_frames"] == 5
    assert found(100, rules, left_upper_arm_out=[(10, 11, 30.0)]).candidates == []
    miss = only(found(100, rules, left_upper_arm_out=[(10, 19, 30.0)]), "upper_arm_out")
    assert miss.expected_frames == (10, 19) and miss.counted_frames == 10


# --- AC-NM-02: every fault is a reported candidate and the reverse, on real takes ---
def real_pair(take):
    return (normalise(load_clip(ROOT / take["expected"])).positions, normalise(load_clip(ROOT / take["follower"])).positions)


@pytest.mark.parametrize("take", LABELS["takes"][::7], ids=lambda t: t["take_id"])
def test_on_seed_5_takes_candidates_and_faults_agree(take):
    exp, fol = real_pair(take)
    alignment = align(exp, fol)
    d = detect_full(compute(exp), compute(fol), alignment)
    assert d.faults == detect(compute(exp), compute(fol), alignment)
    fault_keys = [(f.measure, f.side, f.direction) for f in d.faults]
    for c in d.candidates:
        assert (c.outcome == REPORTED) == reports(fault_keys, c.key), c.key
        assert c.persists == (c.outcome in (REPORTED, EXPLAINED_BY)), c.key
        assert c.frames_over >= 1 and 0 <= c.counted_frames <= c.frames_over
    for f in d.faults:   # every side of every fault is a reported candidate
        sides = ("left", "right") if f.side == "both" else (f.side,)
        assert all(any(c.key == (f.measure, s, f.direction) and c.outcome == REPORTED for c in d.candidates)
                   for s in sides), f


# --- AC-NM-11: profiles ---
def profile_found(name, n=100, **spans):
    return detect_full(synthetic(n), synthetic(n, **spans), identity(n), profiles.effective_rules(load_rules(), name))


def test_a_fault_fitness_reports_and_dance_no_longer_finds_is_a_persistence_near_miss_with_dances_numbers():
    spans = dict(trunk_lean_forward=[(10, 50, 12.0)])    # 41 frames: fitness needs 38, dance needs 44 and a 6 frame run
    assert keys(found(100, rules_with(smooth=load_rules()["smooth_frames"]), **spans).faults) == [
        ("trunk_lean_forward", "center", "more")]
    d = profile_found("dance", **spans)
    assert d.faults == detect(synthetic(100), synthetic(100, **spans), identity(100),
                              profiles.effective_rules(load_rules(), "dance"))
    [miss] = d.near_misses
    assert miss.outcome == PERSISTENCE and miss.threshold_deg == 11.25
    assert (miss.frames_over, miss.counted_frames, miss.needed_frames, miss.min_run_frames) == (41, 41, 44, 6)
    assert miss.to_dict()["shortfall_frames"] == 3


def test_a_difference_under_the_profiles_threshold_is_no_candidate_of_that_profile():
    spans = dict(trunk_lean_forward=[(10, 50, 12.0)])    # past fitness's 9 degrees, under rehab's 13.5
    assert profile_found("rehab", **spans).candidates == []
    assert profile_found("rehab", trunk_lean_forward=[(10, 30, 15.0)]).near_misses[0].threshold_deg == 13.5


def test_an_explanation_is_judged_at_the_baseline_and_names_the_fitness_fault():
    spans = dict(trunk_lean_forward=[(10, 50, 10.0)], head_forward=[(10, 50, 35.0)])
    assert keys(found(60, rules_with(smooth=5), **spans).faults) == [("trunk_lean_forward", "center", "more")]
    d = detect_full(synthetic(60), synthetic(60, **spans), identity(60), profiles.effective_rules(load_rules(), "dance"))
    assert d.faults == []                                  # dance tolerates the trunk and head_forward stays explained
    [miss] = d.near_misses
    assert (miss.measure, miss.outcome) == ("head_forward", EXPLAINED_BY)
    assert miss.explained_by == ("trunk_lean_forward", "center", "more")   # a fitness fault the profile does not report


@pytest.mark.parametrize("name", ["dance", "rehab"])
def test_a_profiles_near_misses_never_include_a_fault_it_reports(name):
    spans = dict(trunk_lean_forward=[(10, 70, 16.0)], left_thigh_out=[(10, 30, 30.0)], right_upper_arm_out=[(5, 80, 30.0)])
    d = profile_found(name, **spans)
    fault_keys = [(f.measure, f.side, f.direction) for f in d.faults]
    assert d.faults and d.near_misses
    assert not [m for m in d.near_misses if reports(fault_keys, m.key)]


# --- AC-NM-01: purely additive, and the whole document ---
def test_the_baseline_digest_leaves_out_exactly_the_near_misses_of_a_document():
    from part5 import profiles_report
    a = {"schema_version": "1.8.0", "profile": "fitness", "expected": {"path": "x.json"}, "faults": [],
         "diagnostics": {"guard": {}, "near_misses": {"total": 0, "omitted": 0, "items": []}}}
    b = {"expected": {"path": "x.json"}, "faults": [], "diagnostics": {"guard": {}}}
    assert profiles_report.analysis_digest(a) == profiles_report.analysis_digest(b)
    assert profiles_report.analysis_digest(b) != profiles_report.analysis_digest(
        {**b, "diagnostics": {"guard": {"residual": 0.1}}})


def test_every_seed_5_fitness_document_is_the_prefeature_baseline_apart_from_the_added_fields(seed5):
    """AC-NM-01: the faults, the score, the insights and every other field of the 156 takes hash to what they did before
    the feature (`fixtures/profiles-fitness-baseline.json`, taken before any near miss existed); only `profile`,
    `schema_version` and `diagnostics.near_misses` are left out of the hash, and the last is present in every one. Since
    1.9.0 the hash also leaves out the language fields of `phrasing` (docs/specs/second-opinion.md)."""
    from part5 import profiles_report
    analyses, labels = seed5
    baseline = json.loads(profiles_report.BASELINE.read_text())["takes"]
    assert len(baseline) == len(labels["takes"]) >= 108
    fitness = analyses["fitness"]
    assert {t: profiles_report.analysis_digest(a) for t, a in fitness.items()} == baseline
    assert all("near_misses" in a["diagnostics"] and a["score"] and "faults" in a for a in fitness.values())


@pytest.fixture(scope="module")
def clean():
    return pipeline.analyse(EXPECTED, EXPECTED)


def test_a_take_identical_to_the_example_says_nothing_came_close(clean):
    assert clean["faults"] == [] and clean["diagnostics"]["near_misses"] == {"total": 0, "omitted": 0, "items": []}
    assert clean["schema_version"] == "1.10.0"


def test_a_take_with_candidates_lists_them_in_the_file_frames_and_two_runs_write_the_same_bytes(tmp_path):
    take = next(t for t in LABELS["takes"] if t["take_id"].startswith("exercise_front_good_08"))
    ref, fol = {"path": str(ROOT / take["expected"])}, {"path": str(ROOT / take["follower"]), "take_id": take["take_id"]}
    a, b = pipeline.analyse(ref, fol), pipeline.analyse(ref, fol)
    assert write_analysis(tmp_path / "a.json", a) == a
    write_analysis(tmp_path / "b.json", b)
    assert (tmp_path / "a.json").read_bytes() == (tmp_path / "b.json").read_bytes()      # AC-NM-10
    block = a["diagnostics"]["near_misses"]
    assert block["total"] == len(block["items"]) + block["omitted"]
    n = len(load_clip(ROOT / take["follower"]).t)
    fault_keys = [(f["measure"], f["side"], f["direction"]) for f in a["faults"]]
    for item in block["items"]:
        assert 0 <= item["follower_frames"][0] <= item["follower_frames"][1] < n
        assert not reports(fault_keys, (item["measure"], item["side"], item["direction"]))
    assert not list(jsonschema.Draft202012Validator(SCHEMA).iter_errors(a))


def decimated(tmp_path, take, step=2):
    doc = json.loads((ROOT / take["follower"]).read_text())
    doc["frames"] = [dict(f, index=i) for i, f in enumerate(doc["frames"][::step])]
    doc["fps"] = doc["fps"] / step
    doc["frame_count"] = len(doc["frames"])
    (tmp_path / "skeleton.json").write_text(json.dumps(doc))
    return tmp_path / "skeleton.json", len(doc["frames"])


def test_a_half_rate_follower_gets_near_misses_in_its_own_frames(tmp_path):
    """AC-NM-05: the follower frames index the file as given, like a fault's (the resampling is mapped back): each
    one is where the 30 fps alignment puts the item's expected frame, halved (the check test_resample makes for faults)."""
    take = next(t for t in LABELS["takes"] if t["take_id"].startswith("exercise_front_good_08"))
    path, frames = decimated(tmp_path, take)
    half = pipeline.analyse(ROOT / take["expected"], path)["diagnostics"]["near_misses"]["items"]
    exp, fol = real_pair(take)
    exp_to_fol = align(exp, fol).exp_to_fol
    assert half and all(0 <= i["follower_frames"][0] <= i["follower_frames"][1] < frames for i in half)
    for item in half:
        want = [exp_to_fol[i] / 2 for i in item["expected_frames"]]
        assert all(abs(got - w) <= 2 for got, w in zip(item["follower_frames"], want)), (item, want)


def test_a_take_that_could_not_be_aligned_ran_no_detection_and_has_no_near_misses(monkeypatch):
    def too_fast(*args, **kwargs):
        raise AlignmentError("follower clip is too short to align")

    take = next(t for t in LABELS["takes"] if t["take_id"].startswith("exercise_45_good_02"))
    monkeypatch.setattr("part5.pipeline.align", too_fast)
    a = pipeline.analyse(ROOT / take["expected"], ROOT / take["follower"])
    assert [w["code"] for w in a["warnings"]] == ["low_match"] and "near_misses" not in a["diagnostics"]


def test_a_low_match_take_still_lists_its_near_misses():
    """Detection ran (the take is analysed, ADR-0012), so the block is there even though the grade is capped."""
    dance = ROOT / "fixtures/input/expected/dance/animation.json"
    a = pipeline.analyse(EXPECTED, dance)
    assert a["warnings"] and "near_misses" in a["diagnostics"]


# --- AC-NM-13: validation, schema, doctor ---
def valid_doc():
    take = next(t for t in LABELS["takes"] if t["take_id"].startswith("exercise_front_good_08"))
    doc = pipeline.analyse(ROOT / take["expected"], ROOT / take["follower"])
    assert doc["diagnostics"]["near_misses"]["items"]
    return copy.deepcopy(doc)


def first_item(doc):
    return doc["diagnostics"]["near_misses"]["items"][0]


@pytest.mark.parametrize("edit, message", [
    (lambda d: d["diagnostics"].update(near_misses=[]), "diagnostics.near_misses must be"),
    (lambda d: d["diagnostics"]["near_misses"].update(omitted=5), "omitted equal to total minus"),
    (lambda d: d["diagnostics"]["near_misses"].update(total=0), "omitted equal to total minus"),
    (lambda d: d["diagnostics"]["near_misses"].update(items=d["diagnostics"]["near_misses"]["items"] * 11,
                                                      total=11 * len(d["diagnostics"]["near_misses"]["items"]), omitted=0),
     "at most 10 items"),
    (lambda d: first_item(d).update(measure="elbow"), ".measure must be one of"),
    (lambda d: first_item(d).update(side="both"), ".side must be left, right or center"),
    (lambda d: first_item(d).update(joint="spine"), ".joint and body_part must be"),
    (lambda d: first_item(d).update(direction="up"), ".direction must be one of"),
    (lambda d: first_item(d).update(magnitude_deg=-abs(first_item(d)["magnitude_deg"]) if first_item(d)["direction"] == "more"
                                    else abs(first_item(d)["magnitude_deg"])), ".magnitude_deg must be a nonzero number signed"),
    (lambda d: first_item(d).update(threshold_deg=0), ".threshold_deg must be a positive number"),
    (lambda d: first_item(d).update(expected_frames=[5, 2]), ".expected_frames must be [start, end]"),
    (lambda d: first_item(d).update(counted_frames=first_item(d)["frames_over"] + 1), "frames_over must be at least 1"),
    (lambda d: first_item(d).update(needed_frames=-1), ".needed_frames must be an integer of at least 0"),
    (lambda d: first_item(d).update(reason="because"), ".reason must be one of"),
    (lambda d: first_item(d).pop("shortfall_frames"), ".shortfall_frames must be an integer"),
    (lambda d: first_item(d).update(reason="explained_by"), ".explained_by must be {measure, side, direction}"),
    (lambda d: first_item(d).update(reason="reps"), ".found_in_reps and needed_reps must be integers"),
    (lambda d: first_item(d).update(reps=[]), ".reps must be a non-empty list"),
])
def test_a_malformed_near_miss_block_is_an_output_error_that_names_the_field(edit, message):
    doc = valid_doc()
    assert first_item(doc)["reason"] == "persistence"
    edit(doc)
    with pytest.raises(OutputError, match=re.escape(message)):
        validate_analysis(doc)


def test_the_schema_requires_what_the_reason_goes_with():
    doc = valid_doc()
    validator = jsonschema.Draft202012Validator(SCHEMA)
    assert SCHEMA["version"] == "1.10.0" and not list(validator.iter_errors(doc))
    item = first_item(doc)
    item["reason"] = "explained_by"
    assert any("explained_by" in e.message for e in validator.iter_errors(doc))
    item["explained_by"] = {"measure": "trunk_lean_forward", "side": "center", "direction": "more"}
    del item["shortfall_frames"]
    assert not list(validator.iter_errors(doc)) and validate_analysis(doc)
    item["side"] = "both"
    assert list(validator.iter_errors(doc))


def test_a_1_7_0_reader_still_takes_the_document_because_diagnostics_allows_extras():
    props = SCHEMA["properties"]["diagnostics"]
    assert "additionalProperties" not in props and "near_misses" in props["properties"]
    assert "near_misses" not in SCHEMA["required"]


def test_doctor_for_part7_notes_how_many_near_misses_a_document_lists(tmp_path):
    doc = valid_doc()
    path = tmp_path / "analysis.json"
    write_analysis(path, doc)
    report = doctor.inspect_file(path, "part7")
    block = doc["diagnostics"]["near_misses"]
    assert report.exit_code == 0
    assert any(f"{block['total']} near miss" in n and "not for the follower" in n for n in report.notes)
    empty = copy.deepcopy(doc)
    empty["diagnostics"]["near_misses"] = {"total": 0, "omitted": 0, "items": []}
    write_analysis(path, empty)
    notes = doctor.inspect_file(path, "part7").notes
    assert any("no near misses" in n for n in notes)
    # TICKET-057 P2: an empty list says that nothing past a threshold was left out, not that nothing differed
    assert ("no near misses (diagnostics.near_misses is empty): no difference that came past a threshold "
            "went unreported") in notes
    del empty["diagnostics"]["near_misses"]
    write_analysis(path, empty)
    assert not any("near miss" in n for n in doctor.inspect_file(path, "part7").notes)


# --- the seed 5 set under every profile ---
def test_every_seed_5_take_under_every_profile_has_a_valid_block_that_agrees_with_its_faults(seed5):
    analyses, labels = seed5
    for name, per_take in analyses.items():
        assert len(per_take) == len(labels["takes"]) >= 108
        for take_id, a in per_take.items():
            block = a["diagnostics"]["near_misses"]
            fault_keys = [(f["measure"], f["side"], f["direction"]) for f in a["faults"]]
            assert block["total"] == block["omitted"] + len(block["items"]) and a["schema_version"] == "1.10.0", (name, take_id)
            for item in block["items"]:
                assert not reports(fault_keys, (item["measure"], item["side"], item["direction"])), (name, take_id, item)
                assert item["reason"] in ("persistence", "explained_by") and item["frames_over"] >= 1
                if item["reason"] == "persistence":
                    assert item["counted_frames"] < item["needed_frames"] or item["counted_frames"] == 0
                else:
                    assert item["counted_frames"] >= item["needed_frames"]
    # a profile only loosens: its thresholds on a near miss are never under fitness's
    for take_id, a in analyses["dance"].items():
        fit = {(i["measure"], i["side"], i["direction"]): i["threshold_deg"]
               for i in analyses["fitness"][take_id]["diagnostics"]["near_misses"]["items"]}
        for item in a["diagnostics"]["near_misses"]["items"]:
            assert item["threshold_deg"] >= fit.get((item["measure"], item["side"], item["direction"]), 0.0)
