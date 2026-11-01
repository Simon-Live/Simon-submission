"""A foot that is not steady is not measured (docs/specs/foot-keypoints.md "Attempt 5", AC-FOOT-22 to AC-FOOT-27,
ADR-0015 Amendment 4, TICKET-040).

The far foot of a side view is the case it exists for: the model sees it least, its heel and toe points jitter, and the
roll of a foot plane whose toe pair is 7 cm across reads tens of degrees from noise alone (`ankle_inversion` on the far
foot of a correct side take, the failure of seeds 37 and 67). The tests build side files with `test_feet.side_doc`, whose
planted feet are steady, and flicker one foot by hand, so the foot that jitters is known by construction; the seed 5
numbers are read from the committed fixtures.
"""
import copy
import json

import numpy as np
import pytest

from part5 import profiles
from part5.detect import load_rules
from part5.feet import FOOT_POINTS, JITTER_MIN_PAIRS, jitter, jitter_limits, load_side, pair_of
from part5.io import InputError, load_clip
from part5.measures import FOOT_MEASURES, MEASURES, compute_feet
from part5.pipeline import run
from test_feet import EXPECTED, FOUR, NO_FEET, ROOT, TAKE, WITH_FEET, foot_faults, planted_feet, point, side_doc, write

NAN = float("nan")
LIMIT = 4.0                                              # the shipped limit of both foot measures, degrees per frame
SAWTOOTH = [12.0 + 6.0 * (i % 8) for i in range(500)]    # a roll that sweeps 6 degrees a frame from 12 to 54: jitter 6
FRAMES = [0.0, 0.033333, 0.066667, 0.1]                  # the hand-made side files' four frames
NOTHING_MEETS = {name: -1.0 for name in FOOT_MEASURES}   # a limit below zero: a still foot (jitter 0) is above it too


def rules_with(limit=LIMIT, measures=("foot_rotation", "ankle_inversion")):
    """The shipped rules with `max_jitter_deg` set to `limit` on `measures` and removed from the others (None: from both)."""
    rules = copy.deepcopy(load_rules())
    for m in ("foot_rotation", "ankle_inversion"):
        rules["measures"][m].pop("max_jitter_deg", None)
        if limit is not None and m in measures:
            rules["measures"][m]["max_jitter_deg"] = limit
    return rules


UNGATED = rules_with(None)
SHIPPED = jitter_limits(load_rules())


def replanted(clip_path, side, roll=None, yaw=None):
    """A side_doc of `clip_path` whose `side` foot is planted again with `roll` and `yaw` (degrees per frame; a roll
    that sweeps 6 degrees a frame and a steady 7 degree toe-out by default); the other foot is as `side_doc` has it."""
    doc, clip = side_doc(clip_path), load_clip(clip_path)
    n = clip.n_frames
    angles = {s: np.full(n, 7.0) for s in ("left", "right")}
    rolls = {s: np.zeros(n) for s in ("left", "right")}
    rolls[side] = np.asarray(SAWTOOTH[:n] if roll is None else roll, float)
    angles[side] = np.asarray(angles[side] if yaw is None else yaw, float)
    planted = planted_feet(clip.positions, angles, rolls)
    for i, frame in enumerate(doc["frames"]):
        for name in FOOT_POINTS:
            if name.startswith(side):
                frame["people"][0]["extra_joints"][name] = point(planted[name][i])
    return doc


def loaded(doc, tmp_path, limits, label="follower", clip=TAKE):
    return load_side(label, write(tmp_path, doc, f"{label}.json"), 0, load_clip(clip).t, limits)


# ---------------------------------------------------------------------------------------------------------------
# AC-FOOT-22: the jitter of a series
# ---------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("values,want", [
    ([5.0] * 20, 0.0),                                                          # a still foot
    ([2.0 * i for i in range(20)], 2.0),                                        # a steady rise reads its slope
    ([5.0 * (-1) ** i for i in range(20)], 10.0),                               # plus and minus 5 reads the swing
    ([0.0] * 30 + [40.0] * 30, 0.0),                                            # one jump is one step of fifty-nine
    ([0.0] * 30 + [25.0 * i / 20 for i in range(21)] + [25.0] * 30, 0.0),       # a fault's ramp is a minority of the steps
])
def test_ac_foot_22_jitter_is_the_median_absolute_step_between_consecutive_frames(values, want):
    assert jitter(values) == pytest.approx(want, abs=1e-9)


def test_ac_foot_22_a_gap_breaks_the_pairs_it_touches_and_leaves_the_rest():
    values = [0.0, 1.0, 2.0, NAN, 10.0, 11.0, 12.0, 13.0, NAN, NAN, 20.0, 21.0, 22.0]
    # the pairs with both frames numbers are (0,1) (1,2) (10,11) (11,12) (12,13) (20,21) (21,22): every step is 1
    assert jitter(values) == pytest.approx(1.0) and jitter(np.array(values)) == pytest.approx(1.0)
    assert jitter([0.0, 1.0, NAN, 9.0, 11.0, NAN, 20.0, 23.0, NAN, 30.0, 34.0, NAN, 40.0, 45.0]) == pytest.approx(3.0)


def test_ac_foot_22_too_few_pairs_is_not_judged_and_not_a_number():
    assert JITTER_MIN_PAIRS == 5
    assert np.isnan(jitter([0.0, 9.0, 0.0, 9.0, 0.0]))                           # 4 pairs
    assert jitter([0.0, 9.0, 0.0, 9.0, 0.0, 9.0]) == pytest.approx(9.0)           # 5 pairs
    assert np.isnan(jitter([])) and np.isnan(jitter([1.0])) and np.isnan(jitter([NAN] * 20))


def test_ac_foot_22_the_noise_is_read_and_a_fault_added_to_it_is_not():
    noise = np.random.default_rng(5).normal(0.0, 5.0, 90)
    bump = np.zeros(90)
    bump[30:50] = np.sin(np.linspace(0.0, np.pi, 20)) * 25.0                     # a 25 degree fault over 20 frames
    assert jitter(noise) == pytest.approx(0.6745 * np.sqrt(2) * 5.0, rel=0.25)   # about 4.8
    assert abs(jitter(noise + bump) - jitter(noise)) < 0.6


# ---------------------------------------------------------------------------------------------------------------
# AC-FOOT-23: the limits come from the rules
# ---------------------------------------------------------------------------------------------------------------
def test_ac_foot_23_the_limits_are_the_max_jitter_deg_of_each_foot_measures_entry_for_both_sides():
    assert jitter_limits(rules_with(3.5, measures=("ankle_inversion",))) == {
        "left_ankle_inversion": 3.5, "right_ankle_inversion": 3.5}
    assert jitter_limits(rules_with(6.0)) == {name: 6.0 for name in FOOT_MEASURES}
    assert jitter_limits(UNGATED) == {} and jitter_limits({}) == {} and jitter_limits(None) == {}
    assert jitter_limits({"measures": {"ankle_inversion": {"threshold_deg": 14.0}}}) == {}   # an entry with no key


def test_ac_foot_23_a_body_measure_is_never_gated_whatever_its_entry_says():
    rules = copy.deepcopy(load_rules())
    rules["measures"]["knee_flexion"]["max_jitter_deg"] = 0.001
    assert set(jitter_limits(rules)) == set(FOOT_MEASURES) and not set(jitter_limits(rules)) & set(MEASURES)


def test_ac_foot_23_both_foot_measures_ship_with_a_limit_of_four_degrees_a_frame_and_no_other_measure_has_one():
    rules = load_rules()
    assert SHIPPED == {name: 4.0 for name in FOOT_MEASURES}
    assert [m for m, cfg in rules["measures"].items() if "max_jitter_deg" in cfg] == ["foot_rotation", "ankle_inversion"]
    assert "max_jitter_deg" not in rules["default"]


@pytest.mark.parametrize("profile", profiles.names())
def test_ac_foot_23_a_profile_keeps_the_limits_they_are_a_property_of_the_points_not_a_tolerance(profile):
    assert jitter_limits(profiles.effective_rules(load_rules(), profile)) == SHIPPED


# ---------------------------------------------------------------------------------------------------------------
# AC-FOOT-24: load_side withdraws a foot measure that jitters above its limit
# ---------------------------------------------------------------------------------------------------------------
def test_ac_foot_24_a_flickering_foot_loses_the_measure_that_jitters_and_nothing_else(tmp_path):
    side = loaded(replanted(TAKE, "right"), tmp_path, SHIPPED)
    assert set(side.unsteady) == {"right_ankle_inversion"} and side.unsteady["right_ankle_inversion"] > LIMIT
    assert side.usable == [n for n in FOUR if n != "right_ankle_inversion"]     # its heading, and the other foot, are kept
    assert side.limits == SHIPPED


def test_ac_foot_24_the_series_is_left_as_measured_only_its_use_is_withdrawn(tmp_path):
    doc = replanted(TAKE, "right")
    gated, plain = loaded(doc, tmp_path, SHIPPED), loaded(doc, tmp_path, None)
    assert np.allclose(gated.series["right_ankle_inversion"], plain.series["right_ankle_inversion"], equal_nan=True)
    assert np.isfinite(plain.series["right_ankle_inversion"]).mean() > 0.9
    assert loaded(side_doc(TAKE), tmp_path, SHIPPED).usable == FOUR              # a steady foot loses nothing


@pytest.mark.parametrize("limits", [None, {}])
def test_ac_foot_24_without_limits_nothing_is_withdrawn_as_before(tmp_path, limits):
    side = loaded(replanted(TAKE, "right"), tmp_path, limits)
    assert side.usable == FOUR and side.unsteady == {} and side.limits == {}


def test_ac_foot_24_a_measure_with_no_limit_is_not_withdrawn_however_it_jitters(tmp_path):
    side = loaded(replanted(TAKE, "right"), tmp_path, jitter_limits(rules_with(LIMIT, measures=("foot_rotation",))))
    assert "right_ankle_inversion" in side.usable and side.unsteady == {}


def test_ac_foot_24_the_limit_is_inclusive_a_measure_exactly_at_it_is_kept(tmp_path):
    doc = replanted(TAKE, "right")
    value = jitter(loaded(doc, tmp_path, None).series["right_ankle_inversion"])
    assert "right_ankle_inversion" in loaded(doc, tmp_path, {"right_ankle_inversion": value}).usable
    assert "right_ankle_inversion" not in loaded(doc, tmp_path, {"right_ankle_inversion": value - 1e-6}).usable


def test_ac_foot_24_a_series_too_short_to_judge_is_kept_the_missing_data_rule_covers_it():
    side = load_side("follower", WITH_FEET, 7, FRAMES, NOTHING_MEETS)
    assert side.unsteady == {} and side.usable == FOUR      # 4 frames, 3 pairs: not judged, whatever the limit


def test_ac_foot_24_only_the_stretch_of_the_file_the_clip_takes_is_judged(tmp_path):
    """The first 40 frames of the side file flicker and the rest are steady: a clip that takes the steady stretch is
    steady, and a clip that takes the whole file is not."""
    clip = load_clip(TAKE)
    roll = np.where(np.arange(clip.n_frames) < 40, SAWTOOTH[:clip.n_frames], 0.0)
    path = write(tmp_path, replanted(TAKE, "right", roll=roll), "side.json")
    whole, late = (load_side("follower", path, 0, t, SHIPPED) for t in (clip.t, clip.t[45:]))
    assert "right_ankle_inversion" in whole.unsteady
    assert late.unsteady == {} and late.usable == FOUR


def test_ac_foot_24_a_clip_sampled_slower_than_the_file_is_judged_on_the_files_consecutive_frames(tmp_path):
    """Every other clip frame takes every other file frame; judging the clip's frames would read steps of two."""
    clip = load_clip(TAKE)
    path = write(tmp_path, replanted(TAKE, "right"), "side.json")
    every_other, every = (load_side("follower", path, 0, t, SHIPPED) for t in (clip.t[::2], clip.t))
    assert every_other.unsteady["right_ankle_inversion"] == pytest.approx(every.unsteady["right_ankle_inversion"], rel=0.05)


def test_ac_foot_24_a_mirrored_file_is_gated_after_its_sides_are_swapped(tmp_path):
    doc = replanted(TAKE, "right")       # the file's right foot flickers; the file is mirrored, so it is the subject's left
    doc["mirrored"] = True
    side = loaded(doc, tmp_path, SHIPPED)
    assert set(side.unsteady) == {"left_ankle_inversion"} and "right_ankle_inversion" in side.usable


def test_ac_foot_24_why_not_names_the_measure_its_jitter_and_its_limit_when_nothing_is_left(tmp_path):
    side = loaded(side_doc(TAKE, extra_roll={"left": 25.0}), tmp_path, NOTHING_MEETS)
    assert side.usable == [] and set(side.unsteady) == set(FOUR)       # every measure is above a limit below zero
    worst = max(side.unsteady, key=side.unsteady.get)
    assert side.why_not() == (f"no foot measure is steady enough to read in the follower frames ({worst} jitters "
                              f"{side.unsteady[worst]:.1f} degrees a frame, the limit is -1)")


def test_ac_foot_24_a_missing_person_is_still_an_input_error_and_no_file_is_still_an_empty_side():
    with pytest.raises(InputError):
        load_side("follower", WITH_FEET, 99, FRAMES, SHIPPED)
    none = load_side("follower", None, 0, FRAMES, SHIPPED)
    assert none.source is None and none.usable == [] and none.unsteady == {}


def test_ac_foot_24_a_file_with_no_foot_points_is_not_a_jitter_case():
    side = load_side("follower", NO_FEET, 0, FRAMES, SHIPPED)
    assert side.usable == [] and side.unsteady == {}
    assert side.why_not() == "the follower feet file has no extra_joints (no foot points)"


def test_ac_foot_24_a_quiet_planted_foot_is_far_below_the_limit():
    doc = side_doc(TAKE)
    points = {name: np.array([[fr["people"][0]["joints"][name][k] for k in "xyz"] for fr in doc["frames"]])
              for name in ("left_hip", "right_hip")}
    points.update({name: np.array([[fr["people"][0]["extra_joints"][name][k] for k in "xyz"] for fr in doc["frames"]])
                   for name in FOOT_POINTS})
    raw = compute_feet(points)
    assert max(jitter(raw[name]) for name in FOOT_MEASURES) < 1.0


# ---------------------------------------------------------------------------------------------------------------
# AC-FOOT-25: in the pipeline, a far foot that jitters raises no fault and a near foot's roll is found
# ---------------------------------------------------------------------------------------------------------------
def analyse(tmp_path, follower, rules, expected=None):
    return run(str(EXPECTED), str(TAKE), rules, expected_feet=str(write(tmp_path, expected or side_doc(EXPECTED), "e.json")),
               follower_feet=str(write(tmp_path, follower, "f.json"))).analysis


def kinds(analysis):
    return {(f["measure"], f["side"], f["direction"]) for f in foot_faults(analysis)}


def test_ac_foot_25_a_far_foot_that_reads_a_roll_from_noise_alone_raises_a_fault_without_the_gate(tmp_path):
    """The failure of seeds 37 and 67 in miniature: a roll sweeping 12 to 54 degrees at 6 a frame. Without the gate the
    take reports it, so what keeps it out in the next test is the gate."""
    a = analyse(tmp_path, replanted(TAKE, "right"), UNGATED)
    assert ("ankle_inversion", "right", "more") in kinds(a) and a["diagnostics"]["feet"]["compared"] == FOUR


def test_ac_foot_25_with_the_gate_the_far_foots_ankle_is_left_out_of_the_comparison_and_the_take_has_no_fault(tmp_path):
    a = analyse(tmp_path, replanted(TAKE, "right"), load_rules())
    assert a["faults"] == []
    info, steady = a["diagnostics"]["feet"], [n for n in FOUR if n != "right_ankle_inversion"]
    assert info["follower"]["usable"] == steady and info["expected"]["usable"] == FOUR
    assert info["compared"] == steady and info["hidden_reason"] is None


def test_ac_foot_25_a_near_foots_roll_is_found_while_the_far_foot_jitters(tmp_path):
    follower, near = replanted(TAKE, "right"), side_doc(TAKE, extra_roll={"left": 25.0})
    for frame, other in zip(follower["frames"], near["frames"]):     # the left foot of `near`, the right foot flickering
        for name in ("left_heel", "left_big_toe", "left_small_toe"):
            frame["people"][0]["extra_joints"][name] = other["people"][0]["extra_joints"][name]
    a = analyse(tmp_path, follower, load_rules())
    assert kinds(a) == {("ankle_inversion", "left", "more")}
    fault = foot_faults(a)[0]
    assert fault["joint"] == "left_ankle" and fault["cue"] == "Keep your left ankle straight"
    assert fault["magnitude_deg"] == pytest.approx(25.0, abs=4.0)


def test_ac_foot_25_the_gate_reads_each_measure_on_its_own_a_toe_out_fault_on_the_flickering_foot_is_found(tmp_path):
    n = load_clip(TAKE).n_frames
    yaw = np.where((np.arange(n) >= int(0.2 * n)) & (np.arange(n) < int(0.8 * n)), 27.0, 7.0)    # 20 degrees more, mid-clip
    a = analyse(tmp_path, replanted(TAKE, "right", yaw=yaw), load_rules())
    assert ("foot_rotation", "right", "more") in kinds(a) and ("ankle_inversion", "right", "more") not in kinds(a)


def test_ac_foot_25_a_pair_of_steady_feet_is_analysed_as_without_the_gate(tmp_path):
    follower = side_doc(TAKE, extra_roll={"left": 25.0}, extra_yaw={"right": 20.0})
    gated = analyse(tmp_path, follower, load_rules())
    assert gated == analyse(tmp_path, follower, UNGATED) and kinds(gated) == {
        ("ankle_inversion", "left", "more"), ("foot_rotation", "right", "more")}


def test_ac_foot_25_the_example_is_gated_like_the_follower(tmp_path):
    """A trainer's own file that jitters is no reference: its measure leaves the pair, on that side only."""
    a = analyse(tmp_path, side_doc(TAKE), load_rules(), expected=replanted(EXPECTED, "left"))
    info = a["diagnostics"]["feet"]
    assert info["expected"]["usable"] == [n for n in FOUR if n != "left_ankle_inversion"] and info["follower"]["usable"] == FOUR
    assert "left_ankle_inversion" not in info["compared"] and a["faults"] == []


def test_ac_foot_25_a_limit_nothing_can_meet_hides_the_foot_measures_and_the_reason_names_both_clips(tmp_path):
    a = analyse(tmp_path, side_doc(TAKE), rules_with(-1.0))
    info = a["diagnostics"]["feet"]
    assert info["compared"] == [] and a["faults"] == []
    reason = info["hidden_reason"]
    assert "no foot measure is steady enough to read in the expected frames" in reason
    assert "no foot measure is steady enough to read in the follower frames" in reason and "; " in reason


# ---------------------------------------------------------------------------------------------------------------
# AC-FOOT-26: the pair keeps the reason of the side that has nothing steady
# ---------------------------------------------------------------------------------------------------------------
def test_ac_foot_26_a_pair_with_no_steady_measure_on_one_side_says_which_side_and_compares_nothing(tmp_path):
    steady = loaded(side_doc(TAKE), tmp_path, {}, "expected")
    shaky = loaded(side_doc(TAKE), tmp_path, NOTHING_MEETS, "follower")
    pair = pair_of(steady, shaky)
    assert pair.compared == [] and pair.hidden_reason.startswith("no foot measure is steady enough to read in the follower")
    assert pair_of(steady, loaded(side_doc(TAKE), tmp_path, {}, "follower")).compared == FOUR


# ---------------------------------------------------------------------------------------------------------------
# AC-FOOT-27: seed 5, from the committed fixtures (the numbers of docs/specs/foot-keypoints.md "Attempt 5")
# ---------------------------------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def seed5():
    """(take, FootSide) of every seed 5 take, loaded with the shipped limits."""
    labels = json.loads((ROOT / "fixtures/input/followers/labels.json").read_text())
    return [(t, load_side("follower", ROOT / t["follower_feet"], 0, load_clip(ROOT / t["follower"]).t, SHIPPED))
            for t in labels["takes"]]


def test_ac_foot_27_no_foot_the_camera_sees_is_withdrawn_at_good_light(seed5):
    """Both feet at the front and the left foot at 45 degrees and at the side (the right foot is the far one in the
    generator's views): 104 feet, 208 measures, none withdrawn."""
    near = [(t["take_id"], name) for t, side in seed5 if t["lighting"] == "good"
            for name in side.unsteady if t["angle"] == "front" or name.startswith("left_")]
    assert near == []


def test_ac_foot_27_the_far_foots_roll_is_withdrawn_in_24_of_26_side_takes_and_11_of_26_takes_at_45_at_good_light(seed5):
    count = lambda angle, name: sum(name in s.unsteady for t, s in seed5 if t["lighting"] == "good" and t["angle"] == angle)
    assert [count("side", "right_ankle_inversion"), count("45", "right_ankle_inversion")] == [24, 11]
    assert [count("side", "right_foot_rotation"), count("45", "right_foot_rotation")] == [11, 1]


def test_ac_foot_27_the_correct_good_light_takes_report_no_foot_fault_and_a_far_foot_labelled_nothing_is_not_a_fault(seed5):
    correct = [t for t, _ in seed5 if t["lighting"] == "good" and t["correct"]]
    assert len(correct) == 12
    for take in correct:
        a = run({"path": str(ROOT / take["expected"])}, {"path": str(ROOT / take["follower"])},
                expected_feet=str(ROOT / take["expected_feet"]), follower_feet=str(ROOT / take["follower_feet"])).analysis
        assert foot_faults(a) == [], take["take_id"]


def test_ac_foot_27_a_both_sides_fault_whose_far_foot_is_withdrawn_is_reported_on_the_near_foot(seed5):
    """dance_45_good_12 and dance_side_good_12 planted `ankle_rolled_out` on both feet: the right foot is withdrawn,
    the left is found and is still the label (a `both` label accepts either side, evaluate.py)."""
    for take_id in ("dance_45_good_12_ankle_rolled_out-both", "dance_side_good_12_ankle_rolled_out-both"):
        take = next(t for t, _ in seed5 if t["take_id"] == take_id)
        a = run({"path": str(ROOT / take["expected"])}, {"path": str(ROOT / take["follower"])},
                expected_feet=str(ROOT / take["expected_feet"]), follower_feet=str(ROOT / take["follower_feet"])).analysis
        assert [(f["measure"], f["side"], f["direction"]) for f in foot_faults(a)] == [("ankle_inversion", "left", "less")]
