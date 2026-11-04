"""Attempt 4 (ADR-0017, TICKET-044, docs/specs/rep-persistence.md): persistence judged in each rep of the example, rep
by rep whenever the example holds two or more reps, each follower rep against the example rep that matches it, and the
foot measures compared rep by rep. The trunk's side lean that does not wrap is in test_measures.py.

Worked by hand on synthetic series (detect), on the real dance example and committed seed 5 takes (the pipeline). No
held-out seed is read."""
import copy
import json
import math
from pathlib import Path

import jsonschema
import numpy as np
import pytest

from part5 import persistence, pipeline, profiles, repwise
from part5.align import Alignment, AlignmentError
from part5.detect import detect_full, load_rules
from part5.measures import MEASURES
from part5.replay import build_replay
from part5.reps import Segmentation, segment
from part5.score_report import feet_kwargs, score_block
from part5.visibility import measures_of

ROOT = Path(__file__).resolve().parent.parent
LABELS = json.loads((ROOT / "fixtures/input/followers/labels.json").read_text())
REPLAY_SCHEMA = json.loads((ROOT / "contracts/replay.schema.json").read_text())
FOUR = ["left_foot_rotation", "right_foot_rotation", "left_ankle_inversion", "right_ankle_inversion"]


def take(take_id):
    return next(t for t in LABELS["takes"] if t["take_id"] == take_id)


def analyse_take(take_id, **kw):
    t = take(take_id)
    return pipeline.run({"path": str(ROOT / t["expected"])}, {"path": str(ROOT / t["follower"]), "take_id": take_id},
                        **feet_kwargs(t, ROOT), **kw)


# --- persistence in each rep (detect) -----------------------------------------------------------------------
def zero(n):
    return {k: np.zeros(n) for k in MEASURES}


def identity(n):
    return Alignment([(i, i) for i in range(n)], np.arange(n), np.linspace(0, 1, n), 0.0, [])


def rules_with(**default):
    """The shipped rules, no smoothing (a run is as long as it is written), both floors at 8 and `default` on top. The
    measures these tests plant are body measures, so `min_frames_floor_body` is the floor that decides."""
    r = copy.deepcopy(load_rules())
    r["smooth_frames"] = 1
    r["default"].update({"min_frames_floor": 8, "min_frames_floor_body": 8, "min_fraction": 0.38, "min_run_frames": 4},
                        **default)
    return r


def found(n, runs, spans=None, rules=None, measure="trunk_lean_forward"):
    """`detect_full` for a follower that is `value` past the example on the `(start, end, value)` runs, inclusive."""
    fol = zero(n)
    for s, e, v in runs:
        fol[measure][s:e + 1] = v
    return detect_full(zero(n), fol, identity(n), rules or rules_with(), rep_spans=spans)


FOUR_REPS = ((0, 74), (75, 149), (150, 224), (225, 299))      # a 300 frame example of four reps of 75


def test_ac_rp_01_a_deviation_that_fills_most_of_one_rep_is_a_fault_though_it_is_a_small_share_of_the_clip():
    """moalborati/simon#59: 69 frames of a 300 frame take is 23% of it, under the 38% the whole clip needs (114 frames), and
    92% of the rep it is in, over the 38% that rep needs (29 frames)."""
    runs = [(80, 148, 22.0)]
    whole = found(300, runs)
    by_rep = found(300, runs, FOUR_REPS)
    [cand] = whole.candidates
    assert whole.faults == [] and cand.counted_frames == 69 and cand.needed_frames == 114 and not cand.persists
    [fault] = by_rep.faults
    assert (fault.measure, fault.direction, fault.runs) == ("trunk_lean_forward", "more", ((80, 148),))
    assert fault.magnitude_deg == 22.0 and fault.expected_frames == (80, 148)


def test_ac_rp_02_an_example_of_one_rep_is_judged_as_the_whole_clip_it_always_was():
    runs = [(10, 40, 15.0), (60, 90, 15.0)]
    plain = found(100, runs)
    for spans in (None, ((0, 99),)):
        same = found(100, runs, spans)
        assert [f.to_dict() for f in same.faults] == [f.to_dict() for f in plain.faults]
        assert [c.to_dict() for c in same.candidates] == [c.to_dict() for c in plain.candidates]


def test_ac_rp_03_each_rep_needs_min_fraction_of_itself_and_its_own_runs_alone():
    """Two reps of 100 frames, 30 frames past the threshold in each: 30% of every rep, 30% of the clip. The runs of one
    rep do not help the other. 45 frames in one rep and 10 in the other: only the first rep persists, and the fault
    is the first rep's run (the 10 frame run belongs to a rep that does not persist and is not one of its runs)."""
    spans = ((0, 99), (100, 199))
    assert found(200, [(10, 39, 15.0), (110, 139, 15.0)], spans).faults == []
    [fault] = found(200, [(10, 54, 15.0), (110, 119, 15.0)], spans).faults
    assert fault.runs == ((10, 54),)


def test_ac_rp_04_a_run_belongs_to_the_rep_that_holds_most_of_it_and_is_never_cut():
    spans = ((0, 99), (100, 199))
    [fault] = found(200, [(70, 129, 15.0)], spans).faults       # 30 frames in each rep: a tie goes to the earlier rep
    assert fault.runs == ((70, 129),)                           # all 60 frames count for it, 60% of that rep
    [cand] = found(200, [(60, 139, 15.0)], spans).candidates    # 40 in the first rep, 40 in the second: a tie again
    assert cand.counted_frames == 80 and cand.persists          # the run counts whole (min_run_frames is its own length)
    assert found(200, [(96, 103, 15.0)], spans).faults == []    # an 8 frame run on the boundary is 8% of the rep that owns it
    [late] = found(200, [(60, 150, 15.0)], spans).candidates    # 40 frames in the first rep, 51 in the second: the later
    assert late.counted_frames == 91 and late.needed_frames == 38


def test_ac_rp_05_the_floor_and_an_explicit_count_are_frames_of_a_rep_not_shares_of_it():
    spans = ((0, 29), (30, 99))      # a 30 frame rep and a 70 frame rep
    short = found(100, [(0, 9, 15.0)], spans, rules_with(min_frames_floor_body=12))
    assert short.faults == [] and short.candidates[0].needed_frames == 12      # 38% of 30 is 11: the floor decides
    assert [f.runs for f in found(100, [(0, 12, 15.0)], spans, rules_with(min_frames_floor_body=12)).faults] == [((0, 12),)]
    explicit = found(100, [(30, 59, 15.0)], spans, rules_with(min_frames=31))
    assert explicit.faults == [] and explicit.candidates[0].needed_frames == 31


def test_b1_the_floor_is_a_duration_in_frames_at_30_fps_capped_at_three_quarters_of_a_rep():
    """Pre-freeze review B1: 32 frames at 30 fps is 1.07 s. At the example's own rate it is 16 frames at 15 fps and 5 at
    5 fps, and it never asks more than three quarters of the rep. Seed 5's shortest rep, the dance example's 43 frames,
    needs exactly the 32 it needed (round(0.75 * 43) is 32; a share of 0.7 or less would move 68 of its takes)."""
    cfg = {"min_frames_floor": 32, "min_frames_floor_body": 32, "reference_fps": 30.0, "floor_share": 0.75,
           "min_fraction": 0.38}
    assert [persistence.floor_frames(cfg, 91, fps) for fps in (None, 30, 15, 5, 60)] == [32, 32, 16, 5, 64]
    assert persistence.floor_frames(cfg, 43) == 32 and persistence.floor_frames(cfg, 30) == 22
    assert persistence.floor_frames(cfg, 20) == 15 and persistence.floor_frames({**cfg, "min_frames_floor_body": 0}, 91, 15) == 0
    assert persistence.needed(cfg, 91) == 35 and persistence.needed(cfg, 46, 15) == 17      # min_fraction decides at 15 fps
    assert persistence.needed(cfg, 43) == 32 and persistence.needed(cfg, 20) == 15          # the cap lets a short rep persist
    assert persistence.needed({**cfg, "min_frames": 9}, 91, 15) == 9                         # an explicit count is frames


def test_n2_the_floor_splits_by_measure_class_and_both_constants_come_from_the_rules():
    """Recheck N2 and residual 5: a foot measure reads `min_frames_floor`, every other measure `min_frames_floor_body`,
    and the reference frame rate and the cap on a rep are keys of the config, not constants of the module."""
    cfg = {"min_frames_floor": 32, "min_frames_floor_body": 8, "reference_fps": 30.0, "floor_share": 0.75,
           "min_fraction": 0.1}
    assert persistence.floor_frames(cfg, 91) == 8 and persistence.floor_frames(cfg, 91, foot=True) == 32
    assert persistence.needed(cfg, 91) == 9 and persistence.needed(cfg, 91, foot=True) == 32
    assert persistence.floor_frames({**cfg, "reference_fps": 60.0}, 91, 30.0) == 4          # 8 frames at 60 fps, played at 30
    assert persistence.floor_frames({**cfg, "floor_share": 0.5}, 40, foot=True) == 20       # the cap is the config's
    for constant in ("REFERENCE_FPS", "FLOOR_SHARE"):
        assert not hasattr(persistence, constant)
    default = load_rules()["default"]
    assert default["reference_fps"] == 30.0 and default["floor_share"] == 0.75 and default["min_frames_floor"] == 32
    # The fast-rep limit that remains, recorded (docs/specs/rep-persistence.md Edge Cases): in the 46 frame rep of a 1.5 s
    # squat at 30 fps a foot measure needs 32 frames (70% of it), a body measure 17 (min_fraction, 37%).
    assert persistence.needed(default, 46, 30.0, foot=True) == 32 and persistence.needed(default, 46, 30.0) == 17


def test_n2_a_foot_measure_keeps_the_foot_floor_and_a_body_measure_the_body_floor_through_detection():
    """The same 20 frame deviation in a 60 frame clip: a body measure (trunk lean) persists at body floor 8, and a foot
    measure of the same size does not while its floor is 32 (round(0.75 * 60) = 45 caps nothing here)."""
    rules = rules_with(min_frames_floor=32, min_frames_floor_body=8, min_fraction=0.1)
    body = zero(60)
    body["trunk_lean_forward"][10:30] = 15.0
    assert [f.measure for f in detect_full(zero(60), body, identity(60), rules).faults] == ["trunk_lean_forward"]
    rules["measures"]["foot_rotation"] = {"threshold_deg": 10.0}
    exp, foot = {**zero(60), "left_foot_rotation": np.zeros(60)}, {**zero(60), "left_foot_rotation": np.zeros(60)}
    foot["left_foot_rotation"][10:30] = 15.0
    got = detect_full(exp, foot, identity(60), rules)
    assert got.faults == [] and got.candidates[0].measure == "foot_rotation" and got.candidates[0].needed_frames == 32
    rules["default"]["min_frames_floor"] = 8
    assert [f.measure for f in detect_full(exp, foot, identity(60), rules).faults] == ["foot_rotation"]


def test_b1_the_frame_rate_of_the_example_turns_the_floor_into_frames():
    """A 20 frame deviation in a 60 frame clip needs 32 frames at 30 fps (the floor), 16 at 15 fps."""
    rules = rules_with(min_frames_floor_body=32, min_fraction=0.1)
    fol = zero(60)
    fol["trunk_lean_forward"][10:30] = 15.0
    for fps, faults in ((None, 0), (30, 0), (15, 1), (10, 1)):
        got = detect_full(zero(60), fol, identity(60), rules, fps=fps)
        assert len(got.faults) == faults, fps
        assert got.candidates[0].needed_frames == max(6, min(round(32 * (fps or 30) / 30), 45))


def test_b1_a_rep_shorter_than_the_floor_can_still_hold_a_fault_and_noise_still_does_not():
    """Two reps of 30 frames, under the floor of 32. A fault held through 25 frames of each persists in both (the floor
    asks 22, three quarters of a rep, not 32); 12 frames of each is under it (and 38% of 30 is 11, so the floor is what
    stops it)."""
    spans = ((0, 29), (30, 59))
    rules = rules_with(min_frames_floor_body=32)
    [fault] = found(60, [(2, 26, 15.0), (32, 56, 15.0)], spans, rules).faults
    assert fault.runs == ((2, 26), (32, 56))
    assert found(60, [(2, 13, 15.0), (32, 43, 15.0)], spans, rules).faults == []
    [cand] = found(60, [(2, 13, 15.0), (32, 43, 15.0)], spans, rules).candidates
    assert (cand.counted_frames, cand.needed_frames) == (12, 22)


def thinned(src, dst, step, fps):
    """The animation file `src` with every `step`-th frame kept, written to `dst` as a clip of `fps` frames per second."""
    doc = json.loads(Path(src).read_text())
    frames = doc["frames"][::step]
    for i, f in enumerate(frames):
        f["index"], f["t"] = i, round(i / fps, 6)
    doc.update(frames=frames, fps=fps, frame_count=len(frames), duration_s=frames[-1]["t"])
    Path(dst).write_text(json.dumps(doc))


def faults_of_pair(tmp_path, t, step, fps):
    """What a seed 5 take reports with its example and follower both thinned to every `step`-th frame at `fps`."""
    expected, follower = tmp_path / "expected.json", tmp_path / "follower.json"
    thinned(ROOT / t["expected"], expected, step, fps)
    thinned(ROOT / t["follower"], follower, step, fps)
    res = pipeline.run({"path": str(expected)}, {"path": str(follower)})
    return sorted((f["measure"], f["side"], f["direction"]) for f in res.analysis["faults"]), res


@pytest.mark.parametrize("step, fps", [(2, 15), (6, 5)])
def test_b1_a_squat_at_a_lower_frame_rate_reports_what_it_reports_at_30_fps(tmp_path, step, fps):
    """The review's /tmp/review5 method: the seed 5 exercise takes with the example and the follower thinned to 15 and 5
    frames per second (a 46 and a 16 frame example) report the faults they report at 30. The new floor was frames at the
    example's rate, so six of the eight planted faults were dropped at 15 fps (a 46 frame squat could not hold 32)."""
    for t in LABELS["takes"]:
        if t["take_id"].startswith("exercise_front_good_") and int(t["take_id"].split("_")[3]) <= 8:
            at_30, _ = faults_of_pair(tmp_path, t, 1, 30)
            assert faults_of_pair(tmp_path, t, step, fps)[0] == at_30, t["take_id"]
            assert bool(at_30) == (not t["correct"]), t["take_id"]


@pytest.mark.parametrize("step, fps", [(2, 15), (6, 5)])
def test_b1_a_dance_at_a_lower_frame_rate_reports_what_it_reports_at_30_fps_rep_by_rep(tmp_path, step, fps):
    wanted = ("02_arms_wider", "03_foot_out", "05_elbow_bent", "06_trunk_lean")
    takes = [t for t in LABELS["takes"] if t["take_id"].startswith(("dance_front_good_", "dance_45_good_"))
             and t["take_id"].split("_", 3)[3].startswith(wanted)]
    assert len(takes) == 8
    for t in takes:
        at_30, _ = faults_of_pair(tmp_path, t, 1, 30)
        assert at_30 and faults_of_pair(tmp_path, t, step, fps)[0] == at_30, t["take_id"]


def test_b1_a_dance_at_twice_the_speed_keeps_the_faults_whose_reps_are_under_the_floor(tmp_path):
    """The dance example thinned to every second frame and still read as 30 fps is twice as fast: its reps are 22 and 31
    frames, both under the floor of 32. arms_wider and trunk_lean, which scored 80 B and 83 B before attempt 4, went to
    100 A with no fault in the review's run; they are found again."""
    for name in ("dance_front_good_02_arms_wider-left", "dance_front_good_06_trunk_lean-center"):
        t = next(x for x in LABELS["takes"] if x["take_id"] == name)
        at_30, _ = faults_of_pair(tmp_path, t, 1, 30)
        fast, res = faults_of_pair(tmp_path, t, 2, 30)
        assert fast == at_30 and res.reps and max(r.expected.n_frames for r in res.reps) < 32, name


def test_ac_rp_06_a_candidate_that_fails_reports_the_rep_that_came_closest_and_the_longest_run_in_it():
    spans = ((0, 99), (100, 199))
    cands = found(200, [(0, 9, 15.0), (100, 134, 15.0)], spans).candidates       # 10 of 38 and 35 of 38
    [cand] = cands
    assert (cand.counted_frames, cand.needed_frames, cand.persists) == (35, 38, False)
    assert cand.expected_frames == (100, 134) and cand.frames_over == 45
    assert cand.to_dict()["shortfall_frames"] == 3 and cand.to_dict()["reason"] == "persistence"


def test_b4_a_failed_candidate_points_at_the_run_of_the_rep_its_numbers_describe():
    """Pre-freeze review B4: runs (0, 29), (100, 119) and (130, 145) over two reps of 100 frames. Rep 0 holds 30 frames
    of 38 needed, rep 1 holds 20 + 16 = 36 of 38, so rep 1 is the closest and the candidate says so: counted 36, needed
    38, and the longest run in rep 1, (100, 119). It used to point at (0, 29), the longest run anywhere, in rep 0."""
    spans = ((0, 99), (100, 199))
    [cand] = found(200, [(0, 29, 15.0), (100, 119, 15.0), (130, 145, 15.0)], spans).candidates
    assert (cand.counted_frames, cand.needed_frames, cand.persists) == (36, 38, False)
    assert cand.expected_frames == (100, 119) and cand.follower_frames == (100, 119)
    assert cand.to_dict()["shortfall_frames"] == 2
    # a run that straddles the boundary is looked for by the frames it has in the closest rep
    [straddle] = found(200, [(0, 9, 15.0), (90, 125, 15.0)], spans).candidates
    assert straddle.expected_frames == (90, 125) and straddle.counted_frames == 36
    # nothing counted anywhere (every run under min_run_frames): the rep with the longest run (the earlier on a tie), and
    # that run: the 3 frame runs tie across the reps and rep 0's (5, 7) stands, not the 2 frame run of rep 1
    [none] = found(200, [(5, 7, 15.0), (110, 112, 15.0), (150, 152, 15.0), (160, 161, 15.0)], spans).candidates
    assert none.counted_frames == 0 and none.expected_frames == (5, 7)
    [later] = found(200, [(5, 6, 15.0), (110, 112, 15.0), (160, 161, 15.0)], spans).candidates
    assert later.counted_frames == 0 and later.expected_frames == (110, 112)
    # a candidate that persists points at the longest run that persists, whichever rep it is in
    [kept] = found(200, [(0, 44, 15.0), (100, 150, 15.0)], spans).candidates
    assert kept.persists and kept.expected_frames == (100, 150)


def test_ac_rp_07_a_reported_fault_and_its_candidate_agree_on_size_and_frames():
    spans = ((0, 99), (100, 199))
    got = found(200, [(5, 60, 12.0), (105, 120, 30.0)], spans)
    [fault], [cand] = got.faults, got.candidates
    assert cand.outcome == "reported" and cand.persists
    assert (cand.magnitude_deg, cand.peak_deg, cand.expected_frames) == (fault.magnitude_deg, fault.peak_deg,
                                                                         fault.expected_frames)
    assert fault.runs == ((5, 60),)              # the 16 frame run is under 38% of its rep and not one of its runs


def test_ac_rp_08_a_profiles_looser_config_is_judged_in_the_reps_too():
    profile = profiles.effective_rules(rules_with(), "dance")      # 1.25 times the threshold, a longer share and run
    whole = found(300, [(80, 148, 22.0)], None, profile)
    by_rep = found(300, [(80, 148, 22.0)], FOUR_REPS, profile)
    assert whole.faults == [] and [f.measure for f in by_rep.faults] == ["trunk_lean_forward"]


def test_the_persistence_keys_a_sweep_moves_include_the_floor_since_a_rep_is_shorter_than_a_clip():
    from part5.sweep import PERSISTENCE as SWEPT
    assert [k for k, *_ in SWEPT][:2] == ["min_frames_floor_body", "min_fraction"]    # the foot floor is held (recheck N2)


# --- the example's reps ------------------------------------------------------------------------------------
def test_ac_rp_09_the_reps_tile_the_clip_with_no_gap_and_no_shared_frame():
    seg = Segmentation(((0, 42), (42, 102)), "m", "dip", 90.0)
    assert seg.partition(121) == ((0, 41), (42, 120))      # the lead-in and the tail belong to the nearest rep
    three = Segmentation(((38, 140), (140, 243), (243, 346)), "m", "dip", 90.0)
    assert three.partition(400) == ((0, 139), (140, 242), (243, 399))
    assert Segmentation(((0, 90),), None, None, 0.0).partition(91) == ((0, 90),)
    for spans, n in ((seg.partition(121), 121), (three.partition(400), 400)):
        assert [i for a, b in spans for i in range(a, b + 1)] == list(range(n))


def test_the_real_examples_reps_are_as_the_spec_says():
    """The dance example starts mid-cycle: a short first rep (43 frames), then a whole cycle (61); the squat is one rep."""
    from part5.io import load_clip
    from part5.measures import compute
    from part5.normalise import normalise
    reps = {}
    for name in ("exercise", "dance"):
        clip = normalise(load_clip(str(ROOT / f"fixtures/input/expected/{name}/animation.json")))
        reps[name] = segment(compute(clip.positions), 30.0)
    assert reps["exercise"].reps == 1 and reps["dance"].spans == ((0, 42), (42, 102))


@pytest.mark.parametrize("k, expected, follower, want", [
    (0, 2, 2, 0), (1, 2, 2, 1),          # the dance: rep k against the example's rep k
    (0, 3, 2, 0), (1, 3, 2, 1),          # fewer reps than the example: still one to one
    (0, 3, 8, 0), (5, 3, 8, 0), (7, 3, 8, 0),      # more reps than the example: the first, as ADR-0010 chose
    (0, 2, 1, 0),                        # one follower segment against two example reps: the first
])
def test_ac_rp_10_a_follower_rep_is_compared_with_the_example_rep_that_matches_it(k, expected, follower, want):
    assert repwise.matched_rep(k, expected, follower) == want


def test_ac_rp_11_the_frame_pairs_of_references_of_different_lengths_are_squared_one_by_one():
    spans = ((0, 42), (42, 102))
    assert repwise._pairs(spans, 2, 100) == (43 * 43 + 61 * 61, 61)
    assert repwise._pairs(spans, 1, 100) == (100 * 43, 43)                  # a lone segment is aligned whole
    assert repwise._pairs(((0, 99), (99, 199), (199, 299)), 8, 800) == (8 * 100 * 100, 100)   # more reps: all the first


def test_ac_rp_11_the_bound_counts_those_pairs_and_the_error_names_numbers_that_multiply_to_at_least_them():
    res = analyse_take("dance_front_good_00_correct")

    def compare_with(max_cells):
        return repwise.compare(res.expected, res.follower, measures_of(res.expected.positions, res.vis),
                               res.follower_positions, res.to_original, 30.0, load_rules(), pipeline._fault_times,
                               res.vis, max_cells=max_cells)
    pairs = 43 * 43 + 61 * 61
    assert len(compare_with(pairs).reps) == 2                               # exactly the limit runs
    with pytest.raises(repwise.TooManyPairs) as e:
        compare_with(pairs - 1)
    assert (e.value.follower_frames, e.value.expected_frames) == (math.ceil(pairs / 61), 61)
    assert e.value.follower_frames * e.value.expected_frames >= pairs


# --- the pipeline -----------------------------------------------------------------------------------------
def test_ac_rp_12_an_example_of_two_reps_is_compared_rep_by_rep_though_the_whole_clip_guard_accepts_it():
    res = analyse_take("dance_front_good_00_correct")
    assert res.reps is not None and [r.ok for r in res.reps] == [True, True]
    score = score_block(res)
    assert score["basis"] == "reps" and res.analysis["faults"] == []
    assert score["value"] == 100 and "warnings" not in res.analysis
    assert res.analysis["diagnostics"]["guard"]["reps"] and res.analysis["diagnostics"]["expected_reference"]


def test_ac_rp_12_an_example_of_one_rep_is_compared_as_a_whole_exactly_as_before():
    res = analyse_take("exercise_front_good_00_correct")
    assert res.reps is None and score_block(res)["basis"] == "windows"
    assert "reps" not in res.analysis["diagnostics"]["guard"] and "expected_reference" not in res.analysis["diagnostics"]


def test_ac_rp_13_each_follower_rep_is_compared_with_the_example_rep_that_matches_it():
    res = analyse_take("dance_front_good_00_correct")
    assert [(r.index, r.ref_start, r.expected.n_frames) for r in res.reps] == [(0, 0, 43), (1, 42, 61)]


def test_ac_rp_13_a_fault_sits_in_the_reference_of_the_rep_that_found_it_on_the_example_file():
    res = analyse_take("dance_front_good_03_foot_out-right")
    [fault] = [f for f in res.analysis["faults"] if f["measure"] == "foot_out"]
    first = fault["reps"][0]
    start, n = res.reps[first].ref_start, res.reps[first].expected.n_frames
    assert start <= fault["expected_frames"][0] <= fault["expected_frames"][1] < start + n
    assert fault["phase"][0] == pytest.approx(fault["expected_frames"][0] / (res.expected.n_frames - 1), abs=1e-3)


def test_ac_rp_14_the_foot_measures_are_compared_rep_by_rep_and_a_planted_foot_fault_is_found():
    res = analyse_take("dance_front_good_09_foot_turned_out-right")
    feet = res.analysis["diagnostics"]["feet"]
    assert res.reps is not None and feet["compared"] == FOUR and feet["hidden_reason"] is None
    [fault] = res.analysis["faults"]
    assert (fault["measure"], fault["side"], fault["direction"]) == ("foot_rotation", "right", "more")
    assert fault["reps"] == [1] and fault["body_part"] == "feet"    # the 43 frame first rep is under the floor of 32


def test_ac_rp_14_a_correct_dance_take_with_feet_reports_no_foot_fault():
    res = analyse_take("dance_45_good_00_correct")
    assert res.analysis["diagnostics"]["feet"]["compared"] == FOUR and res.analysis["faults"] == []


def test_ac_rp_15_the_foot_series_are_cut_and_resampled_like_the_joints():
    series = {"left_foot_rotation": np.arange(10.0), "right_foot_rotation": np.array([np.nan] * 5 + [1.0] * 5)}
    got = repwise._foot_rep(series, 2, 8, 13)
    assert set(got) == set(series) and all(len(v) == 13 for v in got.values())
    assert got["left_foot_rotation"][0] == 2.0 and got["left_foot_rotation"][-1] == 8.0
    assert np.isnan(got["right_foot_rotation"][:6]).all() and np.isfinite(got["right_foot_rotation"][-1])
    assert repwise._foot_rep({}, 0, 5, 7) == {}


def test_ac_rp_16_a_rep_verdict_that_refuses_the_take_leaves_the_whole_clip_comparison(monkeypatch):
    """Every rep refused (here: none can be aligned): the whole-clip guard still accepts this take, so it is analysed as
    a whole with no warning, persistence judged in the example's reps, as before attempt 4 but for that."""
    def refuse(*a, **k):
        raise AlignmentError("scripted")
    monkeypatch.setattr(repwise, "align", refuse)
    res = analyse_take("dance_front_good_00_correct")
    assert res.reps is None and score_block(res)["basis"] == "windows"
    assert "warnings" not in res.analysis and res.analysis["faults"] == []


def test_ac_rp_16_the_whole_clip_fallback_judges_persistence_in_the_examples_reps(monkeypatch):
    seen = []
    real = pipeline.detect_full

    def spy(*args, **kw):
        seen.append(kw.get("rep_spans"))
        return real(*args, **kw)
    monkeypatch.setattr(pipeline, "detect_full", spy)
    monkeypatch.setattr(repwise, "align", lambda *a, **k: (_ for _ in ()).throw(AlignmentError("scripted")))
    analyse_take("dance_front_good_00_correct")
    assert seen == [((0, 41), (42, 120))]
    seen.clear()
    analyse_take("exercise_front_good_00_correct")
    assert seen == [None]                                  # one rep: no spans, the whole clip


def test_ac_rp_17_the_replay_plays_each_rep_against_its_own_reference():
    res = analyse_take("dance_front_good_03_foot_out-right")
    r = build_replay(res)
    jsonschema.Draft202012Validator(REPLAY_SCHEMA).validate(r)
    assert len(r["expected"]) == len(r["exp_to_fol"]) == len(r["expected_t"]) == 43 + 61
    assert [x["expected_frames"] for x in r["reps"]] == [[0, 42], [43, 103]]
    assert r["expected_t"][0] == pytest.approx(float(res.expected.t[0])) and np.all(np.diff(r["expected_t"]) > 0)
    assert r["expected"][0] == [[round(float(x), 4) + 0.0 for x in p] for p in res.reps[0].expected.positions[0]]
    assert r["expected"][43] == [[round(float(x), 4) + 0.0 for x in p] for p in res.reps[1].expected.positions[0]]


def test_ac_rp_18_rules_json_holds_the_persistence_keys_the_sweep_moves():
    d = load_rules()["default"]
    assert {"min_frames_floor", "min_frames_floor_body", "min_fraction", "min_run_frames", "min_overlap"} <= set(d)


# --- a fault the take reports counts in every rep that shows it (continue_reported, ADR-0017) ------------------------
def scripted_fault(measure="upper_arm_out", side="left", direction="more"):
    from part5.detect import Fault
    sign = 1 if direction == "more" else -1
    return Fault(measure=measure, side=side, joint=f"{side}_shoulder", body_part="arms", direction=direction,
                 magnitude_deg=sign * 20.0, peak_deg=sign * 24.0, threshold_deg=10.0, expected_frames=(0, 20),
                 follower_frames=(0, 20), phase=(0.0, 0.5), coverage=1.0, confidence=0.8)


def scripted_rep(index, faults, ok=True):
    return repwise.RepResult(index, (0, 1), ok, None, "alignment", None, None, "orig", faults,
                             measures=("ref", "fol") if ok else None)


def test_ac_rp_19_the_floor_is_taken_out_wherever_a_config_carries_one_and_the_rules_are_not_changed():
    rules = profiles.effective_rules(load_rules(), "dance")
    easy = repwise.without_floor(rules)
    configs = [easy["default"], *easy["measures"].values(), *easy["profile"]["baseline"].values()]
    assert all(c["min_frames_floor"] == 0 == c["min_frames_floor_body"] for c in configs) and len(configs) > 20   # both floors
    assert rules["default"]["min_frames_floor"] == 32 and rules["measures"]["foot_out"]["min_frames_floor"] == 32
    assert rules["measures"]["foot_out"]["min_frames_floor_body"] == rules["default"]["min_frames_floor_body"] > 0
    assert easy["default"]["min_fraction"] == rules["default"]["min_fraction"]      # only the floor goes


def test_ac_rp_19_a_reported_fault_is_added_to_a_rep_that_shows_it_below_the_floor_and_nothing_else(monkeypatch):
    reported, noise = scripted_fault(), scripted_fault("forearm_out", "right", "less")
    calls = []

    def lenient(ref_m, fol_m, alignment, rules, orig, candidates=False, fps=None):
        calls.append(rules["default"]["min_frames_floor"])
        return [reported, noise], []
    monkeypatch.setattr(repwise, "_detected", lenient)
    reps = [scripted_rep(0, []), scripted_rep(1, [reported]), scripted_rep(2, [], ok=False)]
    repwise.continue_reported(reps, {("upper_arm_out", "left", "more")}, load_rules())
    assert reps[0].continued == [reported]       # rep 0 shows the reported fault under the floor; the noise key is not reported
    assert reps[1].continued == []               # rep 1 counted it already
    assert reps[2].continued == []               # a refused rep is not detected at all
    assert calls == [0, 0]


def test_ac_rp_19_a_take_that_reports_nothing_runs_no_second_detection(monkeypatch):
    monkeypatch.setattr(repwise, "_detected", lambda *a, **k: (_ for _ in ()).throw(AssertionError("detected")))
    reps = [scripted_rep(0, [scripted_fault()])]
    repwise.continue_reported(reps, set(), load_rules())
    assert reps[0].continued == []


def test_ac_rp_19_a_fault_reported_on_both_sides_is_continued_where_one_side_shows_it(monkeypatch):
    left = scripted_fault(side="left")
    monkeypatch.setattr(repwise, "_detected", lambda *a, **k: ([left], []))
    reps = [scripted_rep(0, [])]
    repwise.continue_reported(reps, {("upper_arm_out", "both", "more")}, load_rules())
    assert reps[0].continued == [left]


def answering(monkeypatch, *per_rep):
    """`repwise._detected` answering rep after rep with these floor-free faults; returns the `fps` it was handed."""
    answers, seen = iter(per_rep), []

    def detected(*args, fps=None, **kw):
        seen.append(fps)
        return list(next(answers)), []
    monkeypatch.setattr(repwise, "_detected", detected)
    return seen


def test_b2_a_rep_that_holds_a_fault_on_one_side_is_not_charged_again_for_the_take_reporting_it_on_both(monkeypatch):
    """Pre-freeze review B2: rep 0 found `left` strictly, the take reports `both`, and the floor-free detection of rep 0
    answers `both` (its right side shows too). Rep 0 already has the fault on an overlapping side, so its window is
    charged once; rep 1, which has nothing, is charged for what it shows."""
    left, both = scripted_fault(side="left"), scripted_fault(side="both")
    answering(monkeypatch, [both], [both])
    reps = [scripted_rep(0, [left]), scripted_rep(1, [])]
    repwise.continue_reported(reps, {("upper_arm_out", "both", "more")}, load_rules())
    assert reps[0].continued == []
    assert reps[1].continued == [both]


def test_b2_the_other_side_and_the_other_direction_of_a_held_fault_are_still_continued(monkeypatch):
    right, less = scripted_fault(side="right"), scripted_fault(side="left", direction="less")
    answering(monkeypatch, [right, less])
    reps = [scripted_rep(0, [scripted_fault(side="left")])]
    repwise.continue_reported(reps, {("upper_arm_out", "both", "more"), ("upper_arm_out", "left", "less")}, load_rules())
    assert reps[0].continued == [right, less]      # right is not an overlapping side of left; less is another direction


def test_b2_a_rep_holding_both_sides_is_not_charged_for_a_one_sided_part_of_it(monkeypatch):
    answering(monkeypatch, [scripted_fault(side="left")])
    reps = [scripted_rep(0, [scripted_fault(side="both")])]
    repwise.continue_reported(reps, {("upper_arm_out", "both", "more")}, load_rules())
    assert reps[0].continued == []


def test_n1_a_rep_showing_both_sides_is_continued_when_the_take_reports_either_one(monkeypatch):
    """Recheck N1: the take reports the right side only (the left is in under half the reps). A rep that shows the fault
    on both sides, floor-free, has the right one in it, so its `both` fault is continued; a rep that shows only the left
    does not."""
    both, left = scripted_fault(side="both"), scripted_fault(side="left")
    answering(monkeypatch, [both], [left], [both])
    reps = [scripted_rep(0, []), scripted_rep(1, []), scripted_rep(2, [scripted_fault(side="right")])]
    repwise.continue_reported(reps, {("upper_arm_out", "right", "more")}, load_rules())
    assert [r.continued for r in reps] == [[both], [], []]     # rep 2 holds the right side already: charged once


def test_b1_continue_reported_hands_the_example_frame_rate_to_the_detection(monkeypatch):
    seen = answering(monkeypatch, [])
    repwise.continue_reported([scripted_rep(0, [])], {("upper_arm_out", "left", "more")}, load_rules(), fps=15.0)
    assert seen == [15.0]


def test_b2_the_split_dance_take_reports_one_fault_and_charges_each_window_once():
    """dance_45_good_12_ankle_rolled_out-both: the far ankle showed `left` in rep 0 and `both` in rep 1. It was two faults
    ("ankles rolling in" and "left ankle rolling in slightly"), and window 0 was charged for `left` and `both`. Since
    attempt 5 the far (right) ankle of this take jitters above 4 degrees a frame and is withdrawn (ADR-0015 Amendment 4),
    so the take reports the near ankle alone: one fault, `left` in both reps, and no window is charged twice."""
    res = analyse_take("dance_45_good_12_ankle_rolled_out-both")
    inversion = [f for f in res.analysis["faults"] if f["measure"] == "ankle_inversion"]
    assert [(f["side"], f["reps"]) for f in inversion] == [("left", [0, 1])]
    assert "right_ankle_inversion" not in res.analysis["diagnostics"]["feet"]["compared"]
    for w in score_block(res)["timeline"]:
        assert len([m for m in w["misses"] if m["measure"] == "ankle_inversion"]) <= 1      # not once per side


def test_b2_a_take_with_both_feet_read_still_reports_one_fault_and_charges_each_window_once():
    """The same invariant where the steadiness gate leaves both feet in: dance_45_good_10_foot_turned_in-both turns both
    toes in; the rotation shows `left` in the first window and `both` in the second, and is one fault charged once per
    window. (The scripted tests above pin the merge itself, side by side, for any measure.)"""
    res = analyse_take("dance_45_good_10_foot_turned_in-both")
    rotation = [f for f in res.analysis["faults"] if f["measure"] == "foot_rotation"]
    assert [(f["side"], f["reps"]) for f in rotation] == [("both", [1])]
    assert {"left_foot_rotation", "right_foot_rotation"} <= set(res.analysis["diagnostics"]["feet"]["compared"])
    for w in score_block(res)["timeline"]:
        assert len([m for m in w["misses"] if m["measure"] == "foot_rotation"]) <= 1


def test_ac_rp_19_the_short_first_rep_the_floor_blinds_is_scored_for_the_fault_the_take_reports():
    """dance_front_good_09_foot_turned_out-right: the foot is turned out through part of the first rep's 43 frames (more
    than the 16 a share of 38% needs, fewer than the 32 the foot floor needs) and through most of the second. The take
    reports it from the second rep (`reps` [1], strict), and the first rep's window costs its points too, so the take is
    not scored as if half of it were clean. A foot measure keeps the 32 frame floor (recheck N2); a body measure of the
    same dance take no longer needs this, its floor is 8."""
    res = analyse_take("dance_front_good_09_foot_turned_out-right")
    assert [f["reps"] for f in res.analysis["faults"]] == [[1]] and res.reps[0].faults == []
    assert [f.measure for f in res.reps[0].continued] == ["foot_rotation"]
    windows = score_block(res)["timeline"]
    assert [m["measure"] for m in windows[0]["misses"]] == ["foot_rotation"] == [m["measure"] for m in windows[1]["misses"]]
    assert score_block(res)["value"] < 90


def test_ac_rp_19_a_correct_take_has_nothing_continued_and_still_scores_a():
    res = analyse_take("dance_45_good_01_correct")
    assert all(r.continued == [] for r in res.reps) and score_block(res)["value"] == 100
