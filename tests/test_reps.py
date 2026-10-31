"""Repetition-by-repetition comparison (ADR-0010, docs/specs/part5-fault-analysis.md "Repetitions").

Segmentation on synthetic signals, the fault and score aggregation, and the real lateral-raise pairs: a
trainer's three slow reps against a follower's eight fast reps and another's two slow ones. Seed 5 passes
through unchanged: no seed 5 take is ever compared rep by rep.
"""
import copy
import json
from dataclasses import replace
from pathlib import Path

import jsonschema
import numpy as np
import pytest

from part5 import pipeline, profiles, profiles_report, reps, repwise
from part5.detect import Fault, load_rules
from part5.pipeline import run
from part5.replay import build_replay
from part5.score_report import score_block
from part5.visibility import measures_of

ROOT = Path(__file__).resolve().parent.parent
LATERAL = ROOT / "fixtures/input/real/lateral-raise"
TRAINER = LATERAL / "pexels-5319084/animation.json"
FAST = LATERAL / "pexels-40297504/animation.json"
SLOW = LATERAL / "pexels-8836968/animation.json"
MISMATCH = ROOT / "fixtures/input/mismatch"
SQUAT = ROOT / "fixtures/input/eval/real/pexels-5034562/skeleton.json"
SQUAT_FRONT = ROOT / "fixtures/input/eval/real/pexels-5034577/skeleton.json"
SEED5 = json.loads((ROOT / "fixtures/input/followers/labels.json").read_text())
SCHEMA = json.loads((ROOT / "contracts/analysis.schema.json").read_text())
REPLAY_SCHEMA = json.loads((ROOT / "contracts/replay.schema.json").read_text())
FPS = 30


def wave(cycles, per_cycle_s=2.0, lead=0, amp=60.0, tail=0):
    """`cycles` dips-to-dip repetitions of a raise (0 to `amp` degrees), with `lead` idle frames before."""
    n = int(per_cycle_s * FPS)
    one = amp * (1 - np.cos(2 * np.pi * np.arange(n) / n)) / 2
    return np.concatenate([np.zeros(lead)] + [one] * cycles + [np.zeros(tail + 1)])


# --- segmentation ---
def test_three_cycles_are_three_segments_cut_at_the_dips():
    seg = reps.segment({"right_upper_arm_out": wave(3, lead=5)}, FPS)
    assert seg.reps == 3 and seg.bound == reps.DIP and seg.measure == "right_upper_arm_out"
    assert all(58 <= b - a <= 65 for a, b in seg.spans)   # a flat rest is cut at its first frame
    assert seg.spans[0][1] == seg.spans[1][0]   # a boundary frame is shared by neighbours


def test_a_clip_starting_at_the_top_is_cut_at_the_peaks():
    x = wave(3)[30:-30]   # starts and ends at the top of the movement
    seg = reps.segment({"left_knee_flexion": x}, FPS)
    assert seg.bound == reps.PEAK and seg.reps == 2


def test_one_cycle_none_flat_and_small_movement_are_one_whole_segment():
    for x in (wave(1), np.zeros(90), wave(3, amp=10.0), np.full(90, np.nan)):
        seg = reps.segment({"right_upper_arm_out": x}, FPS)
        assert seg.spans == ((0, len(x) - 1),) and seg.reps == 1


def test_ripple_below_the_prominence_is_not_a_cut():
    rng = np.random.default_rng(3)
    x = wave(2, lead=20, tail=20) + rng.normal(0, 1.5, 161)   # noise far below 35% of the range
    seg = reps.segment({"right_upper_arm_out": x}, FPS)
    assert seg.reps == 2 and seg.spans[0][0] <= 25 and seg.spans[-1][1] >= 120   # idle ends: no extra rep


def test_cuts_closer_than_the_minimum_rep_are_one_cut():
    fast = wave(8, per_cycle_s=0.4)   # 12 frames a cycle, below MIN_REP_S
    seg = reps.segment({"right_upper_arm_out": fast}, FPS)
    assert all((b - a) / FPS >= reps.MIN_REP_S for a, b in seg.spans)


def test_the_measure_with_the_largest_range_is_cut_and_a_preferred_one_when_it_moves_enough():
    m = {"left_elbow_flexion": wave(2, amp=40.0), "right_upper_arm_out": wave(3, amp=80.0)}
    assert reps.segment(m, FPS).measure == "right_upper_arm_out"
    pref = reps.segment(m, FPS, prefer=("left_elbow_flexion", reps.DIP))
    assert pref.measure == "left_elbow_flexion" and pref.reps == 2    # 40 is half of 80: enough
    weak = {"left_elbow_flexion": wave(2, amp=20.0), "right_upper_arm_out": wave(3, amp=80.0)}
    assert reps.segment(weak, FPS, prefer=("left_elbow_flexion", reps.DIP)).measure == "right_upper_arm_out"


def test_real_lateral_raise_clips_segment_into_their_reps():
    from part5.measures import compute
    from part5.normalise import normalise
    from part5.pipeline import _load, clip_fps

    def spans(path):
        clip = normalise(_load({"path": str(path)}))
        return reps.segment(compute(clip.positions), clip_fps(clip))

    trainer, fast, slow = spans(TRAINER), spans(FAST), spans(SLOW)
    assert (trainer.reps, fast.reps, slow.reps) == (3, 8, 2)
    assert all(3.0 <= (b - a) / FPS <= 3.8 for a, b in trainer.spans)
    assert all(1.1 <= (b - a) / FPS <= 1.5 for a, b in fast.spans)
    assert all(6.5 <= (b - a) / FPS <= 8.2 for a, b in slow.spans)


# --- rep helpers ---
def test_resample_rep_keeps_the_ends_and_a_missing_joint_missing():
    pos = np.zeros((10, 17, 3))
    pos[:, 0, 0] = np.arange(10)
    pos[4, 1, :] = np.nan
    out, nearest = repwise._resample_rep(pos, 2, 8, 13)
    assert out.shape == (13, 17, 3) and out[0, 0, 0] == 2 and out[-1, 0, 0] == 8
    assert nearest[0] == 2 and nearest[-1] == 8 and (np.diff(nearest) >= 0).all()
    assert np.isnan(out[3:6, 1, 0]).all() and not np.isnan(out[0, 1, 0])   # source frame 4 is output index 4


def fault(measure="knee_flexion", mag=-12.0, peak=-15.0):
    return Fault(measure=measure, side="both", joint="knee", body_part="legs", direction="less", magnitude_deg=mag,
                 peak_deg=peak, threshold_deg=9.0, expected_frames=(2, 9), follower_frames=(3, 20), phase=(0.1, 0.4),
                 coverage=1.0, confidence=0.8)


def rep(index, faults, ok=True):
    return repwise.RepResult(index, (0, 1), ok, None, None, None, None, None, faults)


def test_a_fault_counts_when_found_in_at_least_half_of_the_accepted_reps():
    reps3 = [rep(0, [fault(mag=-12.0), fault("trunk_lean_forward", 11.0, 12.0)]), rep(1, [fault(mag=-14.0)]),
             rep(2, [fault(mag=-20.0, peak=-30.0)])]
    kept = repwise.aggregate_faults(reps3)
    assert [(f.measure, i) for f, i, _ in kept] == [("knee_flexion", [0, 1, 2])]   # the one-off is dropped
    assert kept[0][0].magnitude_deg == -14.0 and kept[0][0].peak_deg == -30.0     # median size, largest peak
    two_of_four = [rep(0, [fault()]), rep(1, [fault()]), rep(2, []), rep(3, [])]
    assert len(repwise.aggregate_faults(two_of_four)) == 1                         # exactly half counts
    assert repwise.aggregate_faults([rep(0, [fault()]), rep(1, []), rep(2, []), rep(3, [])]) == []


def test_a_single_rep_keeps_every_fault_and_refused_reps_are_not_counted():
    only = [rep(0, [fault(), fault("elbow_flexion", 25.0, 30.0)]), rep(1, [fault()], ok=False)]
    kept = repwise.aggregate_faults(only)
    assert {f.measure for f, _, _ in kept} == {"knee_flexion", "elbow_flexion"}
    assert all(i == [0] for _, i, _ in kept)


# --- the real lateral-raise pairs ---
@pytest.fixture(scope="module")
def fast():
    return run(str(TRAINER), str(FAST), score=score_block)


@pytest.fixture(scope="module")
def slow():
    return run(str(TRAINER), str(SLOW), score=score_block)


@pytest.mark.parametrize("which,n_reps", [("fast", 8), ("slow", 2)])
def test_real_lateral_raise_followers_are_accepted_rep_by_rep(which, n_reps, request):
    a = request.getfixturevalue(which).analysis
    jsonschema.Draft202012Validator(SCHEMA).validate(a)
    assert a["status"]["code"] == "ok" and a["schema_version"] == "1.7.0"
    guard = a["diagnostics"]["guard"]
    assert len(guard["reps"]) == n_reps and all(r["ok"] for r in guard["reps"])
    for r in guard["reps"]:   # the frozen limits, the numbers of the diagnosis
        assert r["residual"] <= guard["limits"]["max_residual"] and r["timing_corr"] >= guard["limits"]["min_timing_corr"]
        assert r["timing_corr"] >= 0.9 and len(r["span_s"]) == 2 and r["span_s"][0] < r["span_s"][1]
    ref = a["diagnostics"]["expected_reference"]
    assert ref["kind"] == "first_rep" and ref["expected_reps"] == 3 and ref["follower_reps"] == n_reps
    assert a["score"]["value"] >= 0 and a["score"]["grade"] in "ABCDF"
    assert [p["grade"] for p in a["score"]["per_rep"]] and len(a["score"]["per_rep"]) == n_reps


def test_the_slow_follower_reports_its_faults_once_with_reps_and_the_files_clock(slow):
    faults = slow.analysis["faults"]
    # ADR-0011: its knees and ankles are outside the image (conf 0.3), so they are no longer compared; the
    # 2 faults it carried (63 points) came from those invented legs and hips, and the measured arms are clean.
    assert "right_knee_flexion" in slow.analysis["diagnostics"]["visibility"]["excluded"]
    keys = [(f["measure"], f["side"], f["direction"]) for f in faults]
    assert len(keys) == len(set(keys))                              # once each, not once per rep
    for f in faults:
        assert f["reps"] and set(f["reps"]) <= {0, 1}
        assert f["follower_t_s"][0] < 16.5 and f["at_s"] == pytest.approx(f["follower_t_s"][0], abs=0.06)


def test_a_rep_by_rep_take_is_scored_on_each_reps_own_misses(fast):
    """ADR-0013: no fault is in half the reps, so the take reports none, but each rep's own misses cost it
    points and the score is the mean of the reps, which the timeline shows rep by rep."""
    sc = fast.analysis["score"]
    assert fast.analysis["faults"] == []
    timeline = [w for w in sc["timeline"] if w["compared"]]
    assert sc["basis"] == "reps" and len(timeline) == len(sc["per_rep"]) == 8
    assert all(w["misses"] == [] and w["value"] >= 90 for w in timeline[:3])          # the first reps are clean
    assert all(w["misses"] for w in timeline[4:])                                    # the later ones are not
    for w in timeline:
        assert w["value"] == round(100 - sum(m["points"] for m in w["misses"]) - w["components"]["similarity"])
    assert abs(sc["value"] - sum(w["value"] for w in timeline) / len(timeline)) <= 1


def test_the_replay_tiles_the_expected_rep_against_the_whole_follower_take(fast):
    r = build_replay(fast)
    jsonschema.Draft202012Validator(REPLAY_SCHEMA).validate(r)
    n = fast.reps[0].expected.n_frames
    assert len(r["expected"]) == len(r["exp_to_fol"]) == len(r["expected_t"]) == 8 * n
    assert len(r["follower"]) == fast.follower.n_frames and max(r["exp_to_fol"]) < fast.follower.n_frames
    assert r["reps"][1]["expected_frames"] == [n, 2 * n - 1] and all(x["ok"] for x in r["reps"])
    assert r["expected"][0] == r["expected"][n]                      # the same rep each time
    assert r["exp_to_fol"][0] < r["exp_to_fol"][n] < r["exp_to_fol"][-1]   # the follower moves on


# --- a profile in rep mode never reports a take-level fault that fitness does not (ADR-0016, AC-PROF-05) ---
def side_fault(side, measure="thigh_out", direction="more"):
    return replace(fault(measure), side=side, direction=direction, joint=f"{side}_hip")


def profile_rep(index, faults, fitness_faults):
    return repwise.RepResult(index, (0, 1), True, None, None, None, None, None, faults, fitness_faults=fitness_faults)


def test_the_reviewers_split_is_dropped_because_fitness_does_not_report_it():
    """4 reps. fitness: left in rep 0, both in rep 1, so neither is in half the reps and the take reports nothing.
    rehab splits rep 1 into left: left is then in 2 of 4 and passes the half rule on its own, which fitness never did."""
    reps4 = [profile_rep(0, [side_fault("left")], [side_fault("left")]),
             profile_rep(1, [side_fault("left")], [side_fault("both")]),
             profile_rep(2, [], []), profile_rep(3, [], [])]
    assert repwise.aggregate_faults(reps4, "fitness_faults") == []
    kept = repwise.aggregate_faults(reps4)
    assert [(f.measure, f.side) for f, _, _ in kept] == [("thigh_out", "left")]   # the gap: the profile alone keeps it
    assert repwise.only_what_fitness_reports(kept, reps4) == []


def test_a_fault_fitness_reports_on_both_sides_may_stay_on_one_side_under_a_profile():
    reps4 = [profile_rep(i, [side_fault("left")], [side_fault("both")]) for i in range(2)] + \
            [profile_rep(2, [], []), profile_rep(3, [], [])]
    kept = repwise.only_what_fitness_reports(repwise.aggregate_faults(reps4), reps4)
    assert [(f.measure, f.side) for f, _, _ in kept] == [("thigh_out", "left")] and kept[0][1] == [0, 1]
    other = [profile_rep(i, [side_fault("left")], [side_fault("right")]) for i in range(2)]
    assert repwise.only_what_fitness_reports(repwise.aggregate_faults(other), other) == []   # the other side is not covered
    wrong_way = [profile_rep(i, [side_fault("left", direction="less")], [side_fault("left")]) for i in range(2)]
    assert repwise.only_what_fitness_reports(repwise.aggregate_faults(wrong_way), wrong_way) == []


def compare_under(res, rules):
    return repwise.compare(res.expected, res.follower, measures_of(res.expected.positions, res.vis),
                           res.follower_positions, res.to_original, pipeline.clip_fps(res.expected), rules,
                           pipeline._fault_times, res.vis)


def script_detect(monkeypatch, profile_sides, fitness_sides):
    """`repwise.detect` answering, rep by rep, with these sides: one list for the profile's rules, one for fitness's."""
    calls = {"profile": 0, "fitness": 0}

    def scripted(ref_m, fol_m, alignment, rules):
        kind = "profile" if "profile" in rules else "fitness"
        i, calls[kind] = calls[kind], calls[kind] + 1
        return [side_fault(side) for side in (profile_sides if kind == "profile" else fitness_sides)[i]]

    monkeypatch.setattr(repwise, "detect", scripted)
    return calls


def test_compare_under_a_profile_drops_the_split_fitness_does_not_report(fast, monkeypatch):
    """The same split through `compare` on the real 8-rep take: fitness left, left, both, both (2 of 8 each, nothing
    reported), rehab left in the first four (4 of 8, enough on its own)."""
    rules = profiles.effective_rules(load_rules(), "rehab")
    calls = script_detect(monkeypatch, [["left"]] * 4 + [[]] * 4, [["left"]] * 2 + [["both"]] * 2 + [[]] * 4)
    run_ = compare_under(fast, rules)
    assert calls == {"profile": 8, "fitness": 8} and run_.guard.ok and len(run_.reps) == 8
    assert run_.faults == [] and run_.times == []
    assert all(r.analysis["faults"] == [] and r.analysis["status"]["code"] == "ok" for r in run_.reps)


def test_compare_under_a_profile_keeps_a_fault_fitness_reports(fast, monkeypatch):
    rules = profiles.effective_rules(load_rules(), "rehab")
    script_detect(monkeypatch, [["left"]] * 4 + [[]] * 4, [["both"]] * 4 + [[]] * 4)
    run_ = compare_under(fast, rules)
    assert [(f.measure, f.side) for f in run_.faults] == [("thigh_out", "left")] and run_.times[0]["reps"] == [0, 1, 2, 3]
    assert [len(r.analysis["faults"]) for r in run_.reps] == [1, 1, 1, 1, 0, 0, 0, 0]


def test_compare_under_fitness_is_untouched_and_runs_no_second_detection(fast, monkeypatch):
    calls = script_detect(monkeypatch, [], [["left"]] * 4 + [[]] * 4)
    run_ = compare_under(fast, load_rules())
    assert calls == {"profile": 0, "fitness": 8}   # the plain rules are the fitness rules: one detect per rep
    assert [(f.measure, f.side) for f in run_.faults] == [("thigh_out", "left")]   # 4 of 8 reps, as before
    assert all(r.fitness_faults == [] for r in run_.reps)


@pytest.mark.parametrize("which", ["fast", "slow"])
@pytest.mark.parametrize("name", ["dance", "rehab"])
def test_real_rep_takes_under_a_profile_report_only_what_fitness_reports(which, name, request):
    base = request.getfixturevalue(which)
    under = run(str(TRAINER), str(FAST if which == "fast" else SLOW), profile=name)
    assert under.analysis["profile"] == name and under.reps
    assert profiles_report.uncovered(under.analysis["faults"], base.analysis["faults"]) == []
    if not base.analysis["faults"]:
        assert under.analysis["faults"] == []


# --- tempo: faster than the whole-clip band can follow, and slower ---
def retimed(path, speed):
    """The clip played `speed` times faster: every frame time divided by it."""
    doc = copy.deepcopy(json.loads(Path(path).read_text()))
    for fr in doc["frames"]:
        fr["t"] = round(fr["t"] / speed, 6)
    doc["fps"] = doc["fps"] * speed
    doc["duration_s"] = round(doc["duration_s"] / speed, 4)
    return {"path": f"tempo-{speed}.upload", "doc": doc}


def test_a_trainer_clip_played_four_times_faster_is_compared_rep_by_rep():
    a = run(str(TRAINER), retimed(TRAINER, 4)).analysis    # the whole-clip alignment cannot follow 4x at all
    assert a["status"]["code"] == "ok" and a["faults"] == []
    assert len(a["diagnostics"]["guard"]["reps"]) == 3


def test_a_trainer_clip_played_two_and_a_half_times_faster_is_accepted():
    assert run(str(TRAINER), retimed(TRAINER, 2.5)).analysis["status"]["code"] == "ok"


def test_a_trainer_clip_played_at_a_third_of_the_speed_is_accepted():
    a = run(str(TRAINER), retimed(TRAINER, 1 / 3)).analysis
    assert a["status"]["code"] == "ok" and a["faults"] == []


def test_the_fast_and_the_slow_follower_agree_with_the_trainer_on_the_verdict(fast, slow):
    assert fast.analysis["status"]["code"] == slow.analysis["status"]["code"] == "ok"


# --- different movements are analysed with a low_match warning and grade F (ADR-0012) ---
def low_match(a):
    return a["status"]["code"] == "ok" and [w["code"] for w in a["warnings"]] == ["low_match"] \
        and a["match"]["quality"] == "low" and a["schema_version"] == "1.7.0"


@pytest.mark.parametrize("name", ["part2-dance", "part2-class", "part2-single", "part2-stretch"])
def test_part2_outputs_are_a_low_match_against_the_lateral_raise(name):
    a = run(str(TRAINER), str(MISMATCH / name / "skeleton.json"), score=score_block).analysis
    assert low_match(a) and a["score"]["grade"] == "F" and a["score"]["capped_by"] == ["low_match"]


def test_the_stock_squat_is_a_low_match_against_the_lateral_raise_and_the_other_way_round():
    assert low_match(run(str(TRAINER), str(SQUAT)).analysis)
    assert low_match(run(str(SQUAT), str(TRAINER)).analysis)
    assert low_match(run(str(SQUAT), str(FAST)).analysis)


@pytest.mark.parametrize("name", ["part2-dance", "part2-class", "part2-stretch"])
def test_a_short_stock_squat_rep_does_not_accept_a_long_take_that_matches_one_stretch(name):
    assert low_match(run(str(SQUAT), str(MISMATCH / name / "skeleton.json")).analysis)


def test_the_stock_squat_front_view_is_now_compared_rep_by_rep():
    r = run(str(SQUAT), str(SQUAT_FRONT), score=score_block)
    assert r.analysis["status"]["code"] == "ok" and r.reps and r.analysis["score"] is not None


# --- seed 5 passes through unchanged ---
def test_no_seed5_take_is_compared_rep_by_rep_and_its_document_has_no_rep_fields():
    for take in SEED5["takes"]:
        r = run(str(ROOT / take["expected"]), {"path": str(ROOT / take["follower"]), "take_id": take["take_id"]})
        assert r.reps is None, take["take_id"]
        assert r.analysis["schema_version"] == "1.7.0", take["take_id"]
        assert "reps" not in r.analysis["diagnostics"]["guard"] and "expected_reference" not in r.analysis["diagnostics"]
        assert all("reps" not in f for f in r.analysis["faults"])
