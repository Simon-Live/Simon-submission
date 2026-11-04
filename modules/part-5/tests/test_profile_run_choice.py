"""docs/specs/profiles.md "Which run a profile fault reports": a dance or rehab fault reports the counted run that
overlaps the run fitness reports for the same measure, side and direction (ADR-0016, stakeholder ruling on R1).

The looser config trims the runs, so two runs of nearly the same length could tie and the earliest one won, while
fitness reported the later one: the headline moment then jumped between modes. Fitness itself does not change."""
import copy

import numpy as np
import pytest

from part5 import profiles, profiles_report
from part5.align import Alignment
from part5.detect import _reported_run, detect, load_rules
from part5.measures import MEASURES

TAKE = "exercise_front_good_03_foot_out-right"   # Squat, take 03: foot_out right, held in two stretches


# --- the choice itself ---
def test_without_a_fitness_run_the_longest_run_wins_and_the_earliest_on_a_tie():
    assert _reported_run([(0, 9), (20, 34), (40, 54)], None) == (20, 34)
    assert _reported_run([(0, 9), (20, 29)], None) == (0, 9)


def test_the_run_sharing_the_most_frames_with_fitness_wins():
    assert _reported_run([(0, 29), (40, 49)], (35, 60)) == (40, 49)   # shorter, but it is where fitness reports
    assert _reported_run([(0, 14), (20, 49)], (10, 25)) == (20, 49)   # 6 shared frames against 5


def test_equal_overlap_falls_back_to_the_longest_then_the_earliest():
    assert _reported_run([(0, 9), (20, 34)], (5, 24)) == (20, 34)
    assert _reported_run([(0, 9), (20, 29)], (5, 24)) == (0, 9)


def test_no_overlap_falls_back_to_the_longest_then_the_earliest():
    assert _reported_run([(0, 9), (20, 34)], (50, 60)) == (20, 34)
    assert _reported_run([(0, 9), (20, 29)], (50, 60)) == (0, 9)
    assert _reported_run([(0, 9), (20, 29)], (10, 19)) == (0, 9)   # touching is not overlapping


# --- the choice inside detect ---
N = 100


def series(*stretches):
    """left_foot_out of the follower: zero except `stretches` of (start, end, degrees); the example is all zero."""
    fol = {k: np.zeros(N) for k in MEASURES}
    for start, end, degrees in stretches:
        fol["left_foot_out"][start:end + 1] = degrees
    return fol


def foot_out_runs(follower, rules):
    exp = {k: np.zeros(N) for k in MEASURES}
    alignment = Alignment([(i, i) for i in range(N)], np.arange(N), np.linspace(0, 1, N), 0.0, [])
    faults = [f for f in detect(exp, follower, alignment, rules) if f.measure == "foot_out"]
    assert len(faults) == 1
    return faults[0]


def test_a_profile_reports_the_run_fitness_reports_not_the_earliest_of_two_equal_runs():
    # Fitness (threshold 6) counts [5, 24] (20 frames) and [40, 79] (40 frames) and reports the later. Rehab
    # (threshold 9) trims the later to [60, 79]: two runs of 20 frames, which the old rule broke by taking the first.
    follower = series((5, 24, 12), (40, 59, 7), (60, 79, 12))
    rules = load_rules()
    fitness = foot_out_runs(follower, rules)
    assert fitness.runs == ((5, 24), (40, 79)) and fitness.expected_frames == (40, 79)
    rehab = foot_out_runs(follower, profiles.effective_rules(rules, "rehab"))
    assert rehab.runs == ((5, 24), (60, 79))
    assert rehab.expected_frames == (60, 79) and rehab.follower_frames == (60, 79)
    assert rehab.phase == (round(60 / (N - 1), 3), round(79 / (N - 1), 3))
    assert (rehab.magnitude_deg, rehab.threshold_deg) == (12.0, 9.0)   # the profile's own numbers


def test_a_profile_with_no_run_where_fitness_reports_keeps_the_longest_then_earliest_rule():
    # Fitness reports [30, 69]; the profile's runs [0, 24] and [75, 99] lie elsewhere, both 25 frames.
    follower = series((0, 24, 12), (30, 69, 7), (75, 99, 12))
    rules = load_rules()
    assert foot_out_runs(follower, rules).expected_frames == (30, 69)
    rehab = foot_out_runs(follower, profiles.effective_rules(rules, "rehab"))
    assert rehab.runs == ((0, 24), (75, 99)) and rehab.expected_frames == (0, 24)


def test_fitness_still_reports_the_longest_run():
    follower = series((5, 24, 12), (40, 59, 12), (60, 79, 12))
    fault = foot_out_runs(follower, load_rules())
    assert fault.runs == ((5, 24), (40, 79)) and fault.expected_frames == (40, 79)


@pytest.mark.parametrize("profile", [None, "rehab"])
def test_a_merged_both_fault_spans_its_two_sides_runs_and_is_none_of_them(profile):
    # Left holds [5, 30] and [40, 60], right [5, 25] and [40, 79]: each side reports its longest run, the two sides merge
    # into side "both", and the merged frames are the span (5, 79), which is not one of the runs ((5, 30), (40, 79)).
    follower = {k: np.zeros(N) for k in MEASURES}
    for name, stretches in (("left_foot_out", ((5, 30), (40, 60))), ("right_foot_out", ((5, 25), (40, 79)))):
        for start, end in stretches:
            follower[name][start:end + 1] = 12
    rules = load_rules() if profile is None else profiles.effective_rules(load_rules(), profile)
    fault = foot_out_runs(follower, rules)
    assert fault.side == "both" and fault.runs == ((5, 30), (40, 79))
    assert fault.expected_frames == (5, 79) and fault.expected_frames not in fault.runs


def test_fitness_rules_are_not_touched_by_the_choice():
    rules = load_rules()
    before = copy.deepcopy(rules)
    follower = series((5, 24, 12), (40, 59, 7), (60, 79, 12))
    foot_out_runs(follower, rules)
    foot_out_runs(follower, profiles.effective_rules(rules, "rehab"))
    assert rules == before and "profile" not in rules


# --- Squat, take 03 on the shipped example ---
@pytest.fixture(scope="module")
def take03():
    labels = profiles_report.tuning_labels()
    take = next(t for t in labels["takes"] if t["take_id"] == TAKE)
    return {name: profiles_report.analyse_take(take, profiles_report.ROOT, name) for name in ("fitness", "dance", "rehab")}


def foot_out(analysis):
    found = [f for f in analysis["faults"] if f["measure"] == "foot_out" and f["side"] == "right"]
    assert len(found) == 1
    return found[0]


def inside(inner, outer):
    return outer[0] <= inner[0] and inner[1] <= outer[1]


def test_take_03_rehab_reports_a_moment_inside_the_one_fitness_reports(take03):
    fit, rehab = foot_out(take03["fitness"]), foot_out(take03["rehab"])
    assert fit["expected_frames"] == [50, 76] and fit["follower_frames"] == [58, 89] and fit["at_s"] == 1.9
    # Both counted stretches of rehab stay what they were; the report moves to the one that lies in fitness's run.
    assert rehab["runs"] == [[20, 38], [58, 76]]
    assert rehab["expected_frames"] == [58, 76] and rehab["follower_frames"] == [67, 89]
    assert inside(rehab["expected_frames"], fit["expected_frames"])
    assert inside(rehab["follower_frames"], fit["follower_frames"])   # 0-based; 59 to 90 in 1-based take frames
    assert rehab["follower_runs"][1] == rehab["follower_frames"]
    assert rehab["at_s"] == 2.2 and rehab["follower_t_s"][0] > fit["follower_t_s"][0]
    assert rehab["text_timed"] == "right foot slightly too far right at 2.2 s"
    assert rehab["text"] == "right foot slightly too far out"


def test_take_03_rehab_keeps_its_own_numbers(take03):
    rehab = foot_out(take03["rehab"])
    # Median over both counted stretches, as before the choice moved: the size does not follow the reported run.
    assert (rehab["magnitude_deg"], rehab["threshold_deg"], rehab["confidence"]) == (11.2, 9.0, 0.748)


def test_take_03_dance_and_fitness_already_agreed_and_still_do(take03):
    fit, dance = foot_out(take03["fitness"]), foot_out(take03["dance"])
    assert dance["expected_frames"] == [52, 76] and dance["at_s"] == 2.0
    assert inside(dance["expected_frames"], fit["expected_frames"])
