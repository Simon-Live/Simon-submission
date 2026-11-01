"""docs/specs/near-misses.md AC-NM-12: a take compared rep by rep (ADR-0010) lists its near misses at the take level,
like its faults, aggregated over the accepted reps (`repwise.across_reps`), on the expected file's frames."""
import json
import math
from pathlib import Path

import jsonschema
import pytest

from part5 import contract, profiles, repwise
from part5.detect import (EXPLAINED_BY, FITNESS, PERSISTENCE, REPORTED, REPS, Candidate, Detection, load_rules,
                          reports)
from part5.io import load_clip
from part5.pipeline import run
from part5.visibility import measures_of

ROOT = Path(__file__).resolve().parent.parent
LATERAL = ROOT / "fixtures/input/real/lateral-raise"
TRAINER, FAST, SLOW = (LATERAL / n / "animation.json" for n in ("pexels-5319084", "pexels-40297504", "pexels-8836968"))
SCHEMA = contract.load_schema("analysis")


def cand(measure="thigh_out", side="left", direction="more", counted=20, outcome=PERSISTENCE, **kw):
    """A candidate with `counted` frames out of 39 needed, in the frames 10 to 10 + counted."""
    fields = dict(measure=measure, side=side, joint=f"{side}_hip", body_part="legs", direction=direction,
                  magnitude_deg=15.0 if direction == "more" else -15.0, peak_deg=18.0 if direction == "more" else -18.0,
                  threshold_deg=13.0, expected_frames=(10, 10 + counted), follower_frames=(100, 100 + counted),
                  frames_over=counted + 2, counted_frames=counted, needed_frames=39, min_run_frames=4, outcome=outcome)
    return Candidate(**{**fields, **kw})


def key(c):
    return (c.measure, c.side, c.direction)


def per_rep(*reps):
    """[(index, fault keys, candidates)] from (faults, candidates) pairs."""
    return [(i, faults, cands) for i, (faults, cands) in enumerate(reps)]


# --- across_reps, rep by rep ---
def test_a_candidate_dropped_in_every_rep_is_one_item_with_the_closest_reps_numbers():
    reps = per_rep(([], [cand(counted=12)]), ([], [cand(counted=30)]), ([], [cand(counted=30, magnitude_deg=19.0)]), ([], []))
    [miss] = repwise.across_reps(reps, [])
    assert miss.outcome == PERSISTENCE and miss.reps == (0, 1, 2) and (miss.found_in_reps, miss.needed_reps) == (0, 2)
    assert miss.counted_frames == 30 and miss.magnitude_deg == 15.0         # rep 1: the closest, the earliest on a tie
    assert miss.to_dict()["shortfall_frames"] == 9 and miss.to_dict()["reps"] == [0, 1, 2]


def test_a_candidate_reported_in_fewer_than_half_the_reps_is_a_reps_near_miss_that_says_how_many():
    fault = ("thigh_out", "left", "more")
    reps = per_rep(([fault], [cand(counted=45, outcome=REPORTED)]), ([], [cand(counted=10)]), ([], [cand(counted=12)]), ([], []))
    [miss] = repwise.across_reps(reps, [])
    item = miss.to_dict()
    assert item["reason"] == "reps" and (item["found_in_reps"], item["needed_reps"]) == (1, 2) and item["reps"] == [0, 1, 2]
    assert miss.counted_frames == 45                                        # the rep that reported it came closest
    assert "shortfall_frames" not in item and "explained_by" not in item


def test_the_take_reporting_a_candidate_leaves_it_out_and_a_both_sides_fault_covers_each_side():
    reps = per_rep(([], [cand(counted=45)]), ([], [cand(counted=45)]))
    assert repwise.across_reps(reps, [("thigh_out", "left", "more")]) == []
    assert repwise.across_reps(reps, [("thigh_out", "both", "more")]) == []
    for other in ([("thigh_out", "right", "more")], [("thigh_out", "left", "less")], [("foot_out", "left", "more")]):
        assert len(repwise.across_reps(reps, other)) == 1, other


def test_half_the_reps_reporting_it_on_one_side_while_a_profile_dropped_it_is_a_fitness_near_miss():
    fault = ("thigh_out", "left", "more")
    reps = per_rep(([fault], [cand(counted=45, outcome=REPORTED)]), ([fault], [cand(counted=46, outcome=REPORTED)]),
                   ([], []), ([], []))
    [miss] = repwise.across_reps(reps, [])        # the take does not report it: the profile's check dropped it
    assert miss.outcome == FITNESS and (miss.found_in_reps, miss.needed_reps) == (2, 2)
    assert miss.to_dict()["reason"] == "fitness"


def test_a_fault_split_between_one_side_and_both_sides_counts_the_reps_that_found_the_side_alone_or_as_both():
    """Recheck N1: the left side found in one rep alone and in another as part of `both` was found in 2 reps (it used to
    be the best exact key, 1), the same count the half rule makes: 2 of 6, under the 3 needed. The same reps found the
    right side only as part of `both`, 1 of 6."""
    sides = [([("thigh_out", "left", "more")], [cand(counted=45, outcome=REPORTED)]),
             ([("thigh_out", "both", "more")], [cand(counted=45, outcome=REPORTED)])] + [([], [])] * 4
    [miss] = repwise.across_reps(per_rep(*sides), [])
    assert miss.outcome == REPS and (miss.found_in_reps, miss.needed_reps) == (2, 3)
    right = per_rep(([("thigh_out", "both", "more")], [cand("thigh_out", "right", counted=45, outcome=REPORTED)]), *[([], [])] * 5)
    [miss] = repwise.across_reps(right, [])
    assert miss.outcome == REPS and (miss.found_in_reps, miss.needed_reps) == (1, 3)


def test_an_explained_candidate_keeps_what_explains_it():
    cause = ("trunk_lean_forward", "center", "more")
    reps = per_rep(([], [cand("head_forward", "center", counted=45, outcome=EXPLAINED_BY, explained_by=cause)]),
                   ([], [cand("head_forward", "center", counted=10)]))
    [miss] = repwise.across_reps(reps, [])
    item = miss.to_dict()
    assert item["reason"] == "explained_by" and item["explained_by"] == dict(zip(("measure", "side", "direction"), cause))
    assert item["reps"] == [0, 1]


def test_the_reps_needed_are_half_the_accepted_reps_rounded_up_and_one_for_one_rep():
    for accepted, need in [(1, 1), (2, 1), (3, 2), (4, 2), (8, 4), (9, 5)]:
        reps = per_rep(*[([], [cand(counted=10)])] * accepted)
        assert repwise.across_reps(reps, [])[0].needed_reps == need == math.ceil(0.5 * accepted)
    assert repwise.across_reps(per_rep(([], []), ([], [])), []) == []
    assert repwise.across_reps([], []) == []


def test_each_key_is_its_own_item_and_the_input_candidates_are_not_changed():
    left, right = cand(side="left"), cand(side="right")
    reps = per_rep(([], [left, right, cand(direction="less")]), ([], [cand(side="left", counted=15)]))
    items = repwise.across_reps(reps, [])
    assert sorted(key(m) for m in items) == [("thigh_out", "left", "less"), ("thigh_out", "left", "more"),
                                             ("thigh_out", "right", "more")]
    assert left.outcome == PERSISTENCE and left.reps == () and left.found_in_reps == 0


# --- compare(): scripted detection on the real 3 and 8 rep pair ---
@pytest.fixture(scope="module")
def slow_example():
    """The slow take as the example (its first rep starts at frame 38) and the fast one as the follower (8 reps)."""
    return run(str(SLOW), str(FAST))


def compare_with(res, rules=None):
    return repwise.compare(res.expected, res.follower, measures_of(res.expected.positions, res.vis),
                           res.follower_positions, res.to_original, 30.0, rules or load_rules(),
                           lambda *a: {"follower_t_s": [0.0, 1.0], "follower_runs": [[0, 1]], "lateral_m": None}, res.vis)


def test_compare_lists_near_misses_at_the_take_level_on_the_expected_files_frames(slow_example, monkeypatch):
    calls = []

    def scripted(ref_m, fol_m, alignment, rules, candidates=False, fps=None):
        calls.append(candidates)
        k = len(calls) - 1
        return Detection([], [cand(counted=10 + k, expected_frames=(5, 20 + k), follower_frames=(3, 9))])

    monkeypatch.setattr(repwise, "detect_full", scripted)
    run_ = compare_with(slow_example)
    start = run_.expected_span[0]
    assert start == 38 and len(run_.reps) == 8 and all(r.ok for r in run_.reps) and calls == [True] * 8
    [miss] = run_.near_misses
    assert miss.reps == tuple(range(8)) and (miss.found_in_reps, miss.needed_reps) == (0, 4)
    assert miss.counted_frames == 17 and miss.expected_frames == (5 + 38, 20 + 7 + 38)     # the last rep came closest; on the file
    assert miss.follower_frames == tuple(int(run_.reps[7].to_original[j]) for j in (3, 9))   # mapped to the follower file
    assert [c.expected_frames for c in run_.reps[0].candidates] == [(5, 20)]                # the rep's own stay local
    assert run_.faults == [] and run_.times == []


def test_a_rep_that_reports_it_in_half_the_reps_is_a_fault_and_no_near_miss(slow_example, monkeypatch):
    from part5.detect import Fault
    fault = Fault(measure="thigh_out", side="left", joint="left_hip", body_part="legs", direction="more",
                  magnitude_deg=15.0, peak_deg=18.0, threshold_deg=13.0, expected_frames=(5, 30),
                  follower_frames=(10, 40), phase=(0.1, 0.2), coverage=1.0, confidence=0.9)
    calls = []

    def scripted(ref_m, fol_m, alignment, rules, candidates=False, fps=None):
        calls.append(1)
        reported = len(calls) <= 4                       # 4 of 8 reps: exactly half
        return Detection([fault] if reported else [], [cand(counted=45 if reported else 10,
                                                            outcome=REPORTED if reported else PERSISTENCE)])

    monkeypatch.setattr(repwise, "detect_full", scripted)
    run_ = compare_with(slow_example)
    assert [f.measure for f in run_.faults] == ["thigh_out"] and run_.near_misses == []


def test_a_profiles_second_detection_per_rep_collects_no_candidates(slow_example, monkeypatch):
    calls = []

    def scripted(ref_m, fol_m, alignment, rules, candidates=False, fps=None):
        calls.append(("profile" in rules, candidates))
        return Detection([], [])

    monkeypatch.setattr(repwise, "detect_full", scripted)
    compare_with(slow_example, profiles.effective_rules(load_rules(), "rehab"))
    assert sorted(calls) == [(False, False)] * 8 + [(True, True)] * 8     # the fitness pass of a profile collects none


# --- the real pairs ---
PAIRS = {"trainer-fast": (TRAINER, FAST), "trainer-slow": (TRAINER, SLOW), "slow-fast": (SLOW, FAST)}


@pytest.fixture(scope="module")
def analyses():
    return {(name, profile): run(str(a), str(b), profile=profile).analysis
            for name, (a, b) in PAIRS.items() for profile in (None, "dance", "rehab")}


def test_the_real_rep_takes_list_valid_take_level_near_misses_that_agree_with_their_faults(analyses):
    for (name, profile), a in analyses.items():
        where = (name, profile)
        block, diag = a["diagnostics"]["near_misses"], a["diagnostics"]
        accepted = [i for i, r in enumerate(diag["guard"]["reps"]) if r["ok"]]
        first, _ = diag["expected_reference"]["frames"]
        last = load_clip(PAIRS[name][0]).n_frames - 1    # a later rep can sit in another example rep (ADR-0017)
        fault_keys = [(f["measure"], f["side"], f["direction"]) for f in a["faults"]]
        assert a["schema_version"] == "1.8.0" and block["total"] == block["omitted"] + len(block["items"]), where
        assert not list(jsonschema.Draft202012Validator(SCHEMA).iter_errors(a)), where
        for item in block["items"]:
            assert not reports(fault_keys, (item["measure"], item["side"], item["direction"])), (where, item)
            assert item["reps"] == sorted(item["reps"]) and set(item["reps"]) <= set(accepted), (where, item)
            assert first <= item["expected_frames"][0] <= item["expected_frames"][1] <= last, (where, item)
            if item["reason"] in ("reps", "fitness"):
                assert item["needed_reps"] == math.ceil(0.5 * len(accepted)), (where, item)
                assert 1 <= item["found_in_reps"] and (item["found_in_reps"] < item["needed_reps"]) == (item["reason"] == "reps")
            else:
                assert item["reason"] in ("persistence", "explained_by") and "found_in_reps" not in item


def test_the_eight_rep_follower_shows_faults_found_in_some_reps_but_not_enough(analyses):
    block = analyses[("trainer-fast", None)]["diagnostics"]["near_misses"]
    reps = [i for i in block["items"] if i["reason"] == "reps"]
    assert reps and all(i["found_in_reps"] < i["needed_reps"] == 4 and len(i["reps"]) >= i["found_in_reps"] for i in reps)


def test_a_rep_mode_document_is_the_same_twice(analyses):
    again = run(str(TRAINER), str(FAST)).analysis
    assert json.dumps(again, sort_keys=True) == json.dumps(analyses[("trainer-fast", None)], sort_keys=True)
