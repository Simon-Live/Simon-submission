import json
from pathlib import Path

import numpy as np
import pytest

from part5.io import JOINTS, load_clip
from part5.measures import MEASURES, compute

ROOT = Path(__file__).resolve().parent.parent
J = {n: i for i, n in enumerate(JOINTS)}


def pose(**overrides):
    """Standing pose, arms hanging, legs straight; hip midpoint at the origin."""
    p = {
        "nose": [0, 0.75, 0.05], "left_eye": [0.03, 0.78, 0.06], "right_eye": [-0.03, 0.78, 0.06],
        "left_ear": [0.08, 0.77, 0.02], "right_ear": [-0.08, 0.77, 0.02],
        "left_shoulder": [0.2, 0.5, 0], "right_shoulder": [-0.2, 0.5, 0],
        "left_elbow": [0.2, 0.22, 0], "right_elbow": [-0.2, 0.22, 0],
        "left_wrist": [0.2, -0.03, 0], "right_wrist": [-0.2, -0.03, 0],
        "left_hip": [0.1, 0, 0], "right_hip": [-0.1, 0, 0],
        "left_knee": [0.1, -0.42, 0], "right_knee": [-0.1, -0.42, 0],
        "left_ankle": [0.1, -0.82, 0], "right_ankle": [-0.1, -0.82, 0],
    }
    p.update(overrides)
    return np.array([[p[n] for n in JOINTS]], float)


def m(positions):
    return {k: float(v[0]) for k, v in compute(positions).items()}


def test_standing_pose_is_neutral():
    r = m(pose())
    for k in ["left_elbow_flexion", "right_knee_flexion", "left_upper_arm_out", "right_upper_arm_out",
              "left_thigh_out", "trunk_lean_forward", "trunk_lean_side", "shoulder_tilt"]:
        assert r[k] == pytest.approx(0, abs=1e-6), k


def test_t_pose_arms_are_90_out():
    r = m(pose(left_elbow=[0.48, 0.5, 0], left_wrist=[0.73, 0.5, 0],
               right_elbow=[-0.48, 0.5, 0], right_wrist=[-0.73, 0.5, 0]))
    assert r["left_upper_arm_out"] == pytest.approx(90)
    assert r["right_upper_arm_out"] == pytest.approx(90)
    assert r["left_elbow_flexion"] == pytest.approx(0, abs=1e-6)


def test_straight_arm_reaching_forward_is_not_out():
    r = m(pose(left_elbow=[0.2, 0.5, 0.28], left_wrist=[0.2, 0.5, 0.53]))
    assert r["left_upper_arm_out"] == pytest.approx(0, abs=1e-6)
    assert r["left_upper_arm_forward"] == pytest.approx(90)


def test_right_angle_knee_and_elbow():
    r = m(pose(left_ankle=[0.1, -0.42, -0.4], right_wrist=[-0.2, 0.22, 0.25]))
    assert r["left_knee_flexion"] == pytest.approx(90)
    assert r["right_elbow_flexion"] == pytest.approx(90)


def test_trunk_lean_forward_30():
    c, s = np.cos(np.radians(30)), np.sin(np.radians(30))
    up = {k: [x, y * c, y * s] for k, (x, y, _) in
          {"left_shoulder": (0.2, 0.5, 0), "right_shoulder": (-0.2, 0.5, 0)}.items()}
    r = m(pose(**up))
    assert r["trunk_lean_forward"] == pytest.approx(30)


def test_foot_out_sign_is_away_from_midline_on_both_sides():
    r = m(pose(left_ankle=[0.3, -0.8, 0], right_ankle=[-0.3, -0.8, 0]))
    assert r["left_foot_out"] > 10 and r["right_foot_out"] > 10
    assert r["left_foot_out"] == pytest.approx(r["right_foot_out"])


def test_masked_joint_gives_nan_only_where_used():
    p = pose()
    p[0, J["left_wrist"]] = np.nan
    r = m(p)
    assert np.isnan(r["left_elbow_flexion"])
    assert np.isnan(r["left_forearm_out"])
    assert not np.isnan(r["left_upper_arm_out"])
    assert not np.isnan(r["right_elbow_flexion"])


def test_scale_invariant():
    a, b = m(pose()), m(pose() * 1.15)
    for k in a:
        assert a[k] == pytest.approx(b[k], abs=1e-9)


def test_every_measure_has_a_spec_and_fixtures_are_finite():
    clip = load_clip(ROOT / "fixtures/input/expected/dance/animation.json")
    res = compute(clip.positions)
    assert set(res) == set(MEASURES)
    for k, v in res.items():
        assert v.shape == (clip.n_frames,) and np.isfinite(v).all(), k


def test_dummy_fault_shows_up_in_its_measure():
    labels = json.loads((ROOT / "fixtures/input/followers/labels.json").read_text())
    take = next(t for t in labels["takes"] if t["take_id"].startswith("exercise_front_good")
                and t["faults"] and t["faults"][0]["type"] == "knees_shallow")
    exp = compute(load_clip(ROOT / take["expected"]).positions)
    fol = compute(load_clip(ROOT / take["follower"]).positions)
    # Peak knee bend of the squat: the follower bends clearly less.
    assert np.nanmax(exp["left_knee_flexion"]) - np.nanmax(fol["left_knee_flexion"]) > 25


# knee_valgus (ADR-0004): the knee's offset inside the hip to ankle line, over the thigh length.

def leg_with_knee(side, knee_xyz):
    """A standing pose whose `side` knee is at `knee_xyz` (the ankle stays under the hip)."""
    return pose(**{f"{side}_knee": knee_xyz})


def inward_swing(side, beta_deg):
    """The knee of a leg swung `beta_deg` toward the midline about the hip, in the frontal plane."""
    hip_x = 0.1 if side == "left" else -0.1
    sign = -1 if side == "left" else 1  # toward the midline
    b = np.radians(beta_deg)
    return [hip_x + sign * 0.42 * np.sin(b), -0.42 * np.cos(b), 0]


def test_ac002_straight_leg_reads_zero_on_both_sides():
    """AC-002: a straight leg reads 0 plus or minus 0.5."""
    r = m(pose())
    assert r["left_knee_valgus"] == pytest.approx(0, abs=0.5)
    assert r["right_knee_valgus"] == pytest.approx(0, abs=0.5)


def test_ac002_bent_knee_in_the_sagittal_plane_reads_zero():
    """A squat's forward knee is not caving: it stays in the plane of the hip to ankle line."""
    r = m(pose(left_knee=[0.1, -0.4, 0.3], right_knee=[-0.1, -0.4, 0.3]))
    assert r["left_knee_valgus"] == pytest.approx(0, abs=0.5)
    assert r["right_knee_valgus"] == pytest.approx(0, abs=0.5)


@pytest.mark.parametrize("side, other", [("left", "right"), ("right", "left")])
def test_ac002_knee_caving_in_by_20_reads_20_on_that_side_only(side, other):
    """AC-002: a knee displaced inward until the measure reads 20 degrees reads 20 plus or minus 1
    on that side and 0 plus or minus 1 on the other.

    For a leg swung inward by beta about the hip the measure is atan(sin(beta)), so 20 degrees of
    the measure is a swing of asin(tan 20) = 21.3 degrees; a 20 degree swing reads 18.9."""
    beta = np.degrees(np.arcsin(np.tan(np.radians(20))))
    r = m(leg_with_knee(side, inward_swing(side, beta)))
    assert r[f"{side}_knee_valgus"] == pytest.approx(20, abs=1)
    assert r[f"{other}_knee_valgus"] == pytest.approx(0, abs=1)
    r20 = m(leg_with_knee(side, inward_swing(side, 20)))
    assert r20[f"{side}_knee_valgus"] == pytest.approx(np.degrees(np.arctan(np.sin(np.radians(20)))), abs=0.01)


@pytest.mark.parametrize("side", ["left", "right"])
def test_knee_pushed_out_reads_negative(side):
    r = m(leg_with_knee(side, inward_swing(side, -20)))
    assert r[f"{side}_knee_valgus"] < -15


def test_knee_valgus_rotation_about_the_hip_ankle_line_follows_the_formula():
    """A bent knee (0.2 m off the hip to ankle line) rotated by phi about that line toward the
    midline reads atan2(0.2 sin(phi), thigh length), and 0 at phi = 0."""
    for phi in (0, 20, 45):
        p = np.radians(phi)
        knee = [0.1 - 0.2 * np.sin(p), -0.4, 0.2 * np.cos(p)]  # left: inward is -x
        want = np.degrees(np.arctan2(0.2 * np.sin(p), np.hypot(0.4, 0.2)))
        assert m(leg_with_knee("left", knee))["left_knee_valgus"] == pytest.approx(want, abs=1e-6)


def test_knee_valgus_spec_and_masking():
    spec = MEASURES["right_knee_valgus"]
    assert (spec.joint, spec.side, spec.body_part, spec.kind) == ("right_knee", "right", "legs", "direction")
    assert spec.description == "knee caving in, inside the hip to ankle line"
    p = pose()
    p[0, J["left_ankle"]] = np.nan
    r = m(p)
    assert np.isnan(r["left_knee_valgus"]) and not np.isnan(r["right_knee_valgus"])


def test_knee_valgus_is_flat_on_the_expected_clips_so_alignment_does_not_time_by_it():
    from part5.align import timing_measures
    for name in ("exercise", "dance"):
        res = compute(load_clip(ROOT / f"fixtures/input/expected/{name}/animation.json").positions)
        assert not [n for n in timing_measures(res)[0] if n.endswith("knee_valgus")]


# --- trunk_lean_side does not wrap through a deep forward hinge (ADR-0017, moalborati/simon#59 item 4) ---
def hinged_trunk(hinge_deg, side_deg=0.0, length=0.5):
    """The standing pose with the trunk bent `side_deg` toward the subject's left and then hinged `hinge_deg` forward
    about the hips: the shoulder midpoint is `length` from the hip midpoint along the rotated spine. 90 is horizontal,
    180 upside down."""
    h, s = np.radians(hinge_deg), np.radians(side_deg)
    mid = np.array([length * np.sin(s), length * np.cos(s) * np.cos(h), length * np.cos(s) * np.sin(h)])
    return pose(left_shoulder=list(mid + [0.2, 0, 0]), right_shoulder=list(mid - [0.2, 0, 0]))


HINGES = range(0, 181, 5)


@pytest.mark.parametrize("hinge", HINGES)
def test_ac_sl_01_trunk_lean_side_reads_zero_for_a_forward_hinge_with_no_side_lean(hinge):
    assert m(hinged_trunk(hinge))["trunk_lean_side"] == pytest.approx(0, abs=1e-6)


@pytest.mark.parametrize("hinge", HINGES)
@pytest.mark.parametrize("side", [-20.0, -4.0, 4.0, 20.0])
def test_ac_sl_02_trunk_lean_side_keeps_its_size_and_sign_for_a_real_side_lean_at_any_hinge(hinge, side):
    """Positive is toward the subject's left; a lean of `side` degrees reads `side` whether the trunk is upright, level
    or past level, where the angle of the frontal projection reads about 180 degrees minus the lean."""
    got = m(hinged_trunk(hinge, side))["trunk_lean_side"]
    assert got == pytest.approx(side, abs=1e-6) and np.sign(got) == np.sign(side)


def test_ac_sl_03_trunk_lean_side_is_bounded_and_continuous_through_a_hinge_of_0_to_120_degrees():
    hinges = np.arange(0, 120.5, 0.5)
    for side in (0.0, 8.0, -8.0):
        series = np.array([m(hinged_trunk(h, side))["trunk_lean_side"] for h in hinges])
        assert np.all(np.abs(series) <= 90.0)
        assert np.max(np.abs(np.diff(series))) < 1e-6      # no jump anywhere on the way down


def test_ac_sl_03_trunk_lean_side_is_the_angle_out_of_the_sagittal_plane_not_of_its_frontal_projection():
    """A trunk leaning 30 degrees to the left reads 30 upright and 30 hinged 60 degrees forward (the projection onto
    the frontal plane would read 45 there), and a trunk hinged past level still reads the lean, not 180 minus it."""
    assert m(hinged_trunk(0, 30))["trunk_lean_side"] == pytest.approx(30)
    assert m(hinged_trunk(60, 30))["trunk_lean_side"] == pytest.approx(30)
    assert m(hinged_trunk(120, 30))["trunk_lean_side"] == pytest.approx(30)


def test_ac_sl_05_a_zero_length_trunk_is_not_a_division():
    p = hinged_trunk(0, 10, length=1e-12)
    assert np.isfinite(m(p)["trunk_lean_side"])


def test_ac_sl_04_the_frontal_projection_the_neck_still_uses_wraps_where_the_trunks_measure_does_not():
    """Only the trunk changed: `neck_lean_side` (head-and-shoulder takes, which cannot hinge) is as it was."""
    from part5.measures import _lateral, _sideways
    hinged = np.array([[0.05, -0.5, 0.8]])    # 5 degrees of sideways lean at the top of a trunk hinged past level
    assert _lateral(hinged)[0] > 150 and abs(_sideways(hinged)[0]) < 5
