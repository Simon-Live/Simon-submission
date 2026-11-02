"""part2/autorig_joints.py: the fitted skeleton moved to the middle of the mesh in depth. Spec: docs/specs/autorig.md (AC-22).
No GPU, torch or scipy."""
import numpy as np
import pytest
from autorig_helpers import (
    humanoid,
    surface_points,
    synthetic_joints,
    synthetic_parents,
)

from part2 import autorig_joints
from part2.autorig import MHR_INDEX


def figure():
    return surface_points(humanoid(), 20000), synthetic_joints(), synthetic_parents()


def test_joints_fitted_behind_the_mesh_come_back_to_its_middle():
    v, joints, parents = figure()
    behind = joints.copy()
    behind[:, 2] -= 0.15
    moved, info = autorig_joints.centre_in_depth(v, behind, parents, MHR_INDEX)
    legs = [MHR_INDEX[n] for n in ("leftUpperLeg", "leftLowerLeg", "rightUpperLeg", "rightLowerLeg")]
    assert np.abs(moved[legs, 2] - joints[legs, 2]).max() < 0.03
    assert np.allclose(moved[:, :2], behind[:, :2])  # only Z moves
    assert info["median_shift_m"] == pytest.approx(0.15, abs=0.03) and info["bones"] >= 10


def test_joints_already_in_the_middle_barely_move():
    v, joints, parents = figure()
    moved, info = autorig_joints.centre_in_depth(v, joints, parents, MHR_INDEX)
    legs = [MHR_INDEX[n] for n in ("hips", "leftUpperLeg", "leftLowerLeg", "rightUpperLeg", "rightLowerLeg")]
    assert np.abs(moved[legs] - joints[legs]).max() < 0.03 and info["median_shift_m"] < 0.03


def test_a_shift_is_clipped():
    v, joints, parents = figure()
    far = joints.copy()
    far[:, 2] -= 1.0
    moved, info = autorig_joints.centre_in_depth(v, far, parents, MHR_INDEX)
    assert info["max_shift_m"] == autorig_joints.MAX_SHIFT_M
    assert (moved[:, 2] - far[:, 2]).max() <= autorig_joints.MAX_SHIFT_M + 1e-12


def test_a_bone_with_no_mesh_near_takes_the_median_and_others_follow_their_ancestor():
    v, joints, parents = figure()
    behind = joints.copy()
    behind[:, 2] -= 0.1
    behind[MHR_INDEX["leftHand"], 0] += 5.0  # nothing of the mesh within reach of this joint
    off = autorig_joints.depth_offsets(v, behind, MHR_INDEX)
    assert "leftHand" not in off and "hips" in off
    moved, _ = autorig_joints.centre_in_depth(v, behind, parents, MHR_INDEX)
    assert moved[MHR_INDEX["leftHand"], 2] - behind[MHR_INDEX["leftHand"], 2] == pytest.approx(np.median(list(off.values())))
    other = next(j for j in range(127) if j not in MHR_INDEX.values() and parents[j] == MHR_INDEX["hips"])
    assert moved[other, 2] - behind[other, 2] == pytest.approx(moved[MHR_INDEX["hips"], 2] - behind[MHR_INDEX["hips"], 2])


def test_a_mesh_with_no_points_near_any_joint_leaves_them_alone():
    v, joints, parents = figure()
    moved, info = autorig_joints.centre_in_depth(v + 50.0, joints, parents, MHR_INDEX)
    assert np.array_equal(moved, joints) and info["bones"] == 0
