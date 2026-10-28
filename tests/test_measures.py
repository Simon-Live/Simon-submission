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
