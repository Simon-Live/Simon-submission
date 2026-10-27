"""Joint angles of a skeleton.json (spec "Phase alignment", Angles; AC-008 machinery)."""

import math

import numpy as np

from part3.angles import ANGLE_NAMES, joint_angles, joints_array
from part3.joints import JOINTS

# A hand-built standing pose, x left, y up, z anterior, metres. Left elbow 90, right arm straight out
# sideways (right shoulder 90, right elbow 180), left knee 90, right leg straight, trunk upright.
POSE = {
    "nose": (0.0, 0.65, 0.1), "left_eye": (0.03, 0.68, 0.08), "right_eye": (-0.03, 0.68, 0.08),
    "left_ear": (0.07, 0.66, 0.0), "right_ear": (-0.07, 0.66, 0.0),
    "left_shoulder": (0.15, 0.5, 0.0), "right_shoulder": (-0.15, 0.5, 0.0),
    "left_elbow": (0.15, 0.2, 0.0), "right_elbow": (-0.45, 0.5, 0.0),
    "left_wrist": (0.15, 0.2, 0.3), "right_wrist": (-0.75, 0.5, 0.0),
    "left_hip": (0.15, 0.0, 0.0), "right_hip": (-0.15, 0.0, 0.0),
    "left_knee": (0.15, -0.4, 0.0), "right_knee": (-0.15, -0.4, 0.0),
    "left_ankle": (0.15, -0.4, -0.4), "right_ankle": (-0.15, -0.8, 0.0),
}


def skeleton(poses):
    """A skeleton-like dict; a pose of None is a frame without a person."""
    frames = []
    for i, pose in enumerate(poses):
        people = [] if pose is None else [{"id": 0, "joints": {
            n: {"x": pose[n][0], "y": pose[n][1], "z": pose[n][2], "conf": 1.0} for n in JOINTS}}]
        frames.append({"frame": i, "t_ms": 1000.0 * i / 15, "people": people})
    return {"frames": frames}


def test_angle_names_in_spec_order():
    assert ANGLE_NAMES == ("left_elbow", "right_elbow", "left_shoulder", "right_shoulder",
                           "left_hip", "right_hip", "left_knee", "right_knee", "trunk_inclination")


def test_known_angles():
    row = dict(zip(ANGLE_NAMES, joint_angles(skeleton([POSE]))[0]))
    assert math.isclose(row["left_elbow"], 90.0, abs_tol=1e-9)
    assert math.isclose(row["right_elbow"], 180.0, abs_tol=1e-6)
    assert math.isclose(row["right_shoulder"], 90.0, abs_tol=1e-9)
    assert math.isclose(row["left_shoulder"], 0.0, abs_tol=1e-6)  # arm hangs along the trunk
    assert math.isclose(row["left_knee"], 90.0, abs_tol=1e-9)
    assert math.isclose(row["right_knee"], 180.0, abs_tol=1e-6)
    assert math.isclose(row["left_hip"], 180.0, abs_tol=1e-6)
    assert math.isclose(row["right_hip"], 180.0, abs_tol=1e-6)


def test_upright_trunk_has_zero_inclination():
    assert math.isclose(joint_angles(skeleton([POSE]))[0, 8], 0.0, abs_tol=1e-9)


def test_trunk_inclination_catches_lean_and_ignores_rotation_about_y():
    leaned = dict(POSE, left_shoulder=(0.40, 0.5, 0.0), right_shoulder=(0.10, 0.5, 0.0))
    # neck - root = (0.25, 0.5, 0): atan(0.25 / 0.5) = 26.565 degrees
    assert math.isclose(joint_angles(skeleton([leaned]))[0, 8], math.degrees(math.atan(0.5)), abs_tol=1e-9)
    forward = dict(POSE, left_shoulder=(0.15, 0.5, 0.5), right_shoulder=(-0.15, 0.5, 0.5))
    assert math.isclose(joint_angles(skeleton([forward]))[0, 8], 45.0, abs_tol=1e-9)


def test_interior_angles_do_not_change_under_rotation():
    c, s = math.cos(0.7), math.sin(0.7)
    R = np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])
    rotated = {n: tuple(R @ np.array(p)) for n, p in POSE.items()}
    a, b = joint_angles(skeleton([POSE]))[0], joint_angles(skeleton([rotated]))[0]
    assert np.allclose(a[:8], b[:8], atol=1e-9) and math.isclose(a[8], b[8], abs_tol=1e-9)


def test_frames_without_a_person_are_nan_rows():
    out = joint_angles(skeleton([POSE, None, POSE]))
    assert out.shape == (3, 9)
    assert np.isnan(out[1]).all()
    assert np.isfinite(out[[0, 2]]).all()


def test_joints_array_shape_and_order():
    J = joints_array(skeleton([POSE, None]))
    assert J.shape == (2, 17, 3)
    assert np.allclose(J[0, JOINTS.index("left_knee")], POSE["left_knee"])
    assert np.isnan(J[1]).all()
