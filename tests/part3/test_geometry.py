"""Shared vector maths (part3/geometry.py)."""

import numpy as np

from clipkit import doc_arrays
from part3 import bones, geometry as g
from part3.joints import BONE_NAMES, BONES, INDEX, JOINTS, PAIRS, swap_index


def test_joint_table_matches_contract():
    assert len(JOINTS) == 17 and len(BONES) == 18 and len(PAIRS) == 8
    perm = swap_index()
    assert perm[INDEX["left_knee"]] == INDEX["right_knee"] and perm[INDEX["nose"]] == INDEX["nose"]


def test_interior_angle_right_angle_and_degenerate():
    assert np.isclose(g.interior_angle([1, 0, 0], [0, 0, 0], [0, 1, 0]), 90.0)
    assert np.isnan(g.interior_angle([0, 0, 0], [0, 0, 0], [0, 1, 0]))


def test_pelvis_frame_is_identity_on_part2_input(real_doc):
    J = doc_arrays(real_doc)[0]
    out, valid = g.pelvis_frame(J, [0, 1, 0])
    assert valid.all()
    assert np.abs(out - J).max() < 2e-3


def test_pelvis_frame_removes_a_rotation(real_doc):
    J = doc_arrays(real_doc)[0]
    R = g.rotation([0.3, 1, 0.2], 40)
    up = R @ np.array([0, 1, 0])
    out, _ = g.pelvis_frame(J @ R.T, up)
    assert np.abs(out - J).max() < 2e-3


def test_body_up_on_real_squat_is_standing_and_near_vertical(real_doc):
    up, source = g.body_up(doc_arrays(real_doc)[0])
    assert source == "standing_frames"
    assert g.angle_between(up, [0, 1, 0]) < 6.0


def test_retarget_sets_every_length_and_keeps_directions(real_doc):
    J = doc_arrays(real_doc)[0]
    # Paired bones share a length (as in the standard body), so root and neck stay midpoints.
    base = sorted({name.replace("left_", "").replace("right_", "") for name in BONE_NAMES})
    target = np.array([0.05 + 0.04 * base.index(n.replace("left_", "").replace("right_", ""))
                       for n in BONE_NAMES])
    out = bones.retarget(J, target)
    assert np.allclose(bones.measure(out), target, atol=1e-9)
    assert np.allclose(g.point(out, "root"), g.point(J, "root"))
    d_in = g.normalize(g.point(J, "left_knee") - g.point(J, "left_hip"))
    d_out = g.normalize(g.point(out, "left_knee") - g.point(out, "left_hip"))
    assert np.allclose(d_in, d_out)


def test_retarget_per_frame_lengths(real_doc):
    J = doc_arrays(real_doc)[0][:3]
    L = np.array([np.full(18, 0.2), np.full(18, 0.3), np.full(18, 0.4)])
    assert np.allclose(bones.measure(bones.retarget(J, L)), L)


def test_body_up_falls_back_to_all_frames():
    J = np.zeros((6, 17, 3))
    J[:, INDEX["left_hip"]] = [0.1, 0, 0]
    J[:, INDEX["right_hip"]] = [-0.1, 0, 0]
    J[:, INDEX["left_knee"]] = [0.1, -0.2, 0.3]
    J[:, INDEX["right_knee"]] = [-0.1, -0.2, 0.3]
    J[:, INDEX["left_ankle"]] = [0.1, -0.4, 0]
    J[:, INDEX["right_ankle"]] = [-0.1, -0.4, 0]
    J[:, INDEX["left_shoulder"]] = [0.2, 0.5, 0]
    J[:, INDEX["right_shoulder"]] = [-0.2, 0.5, 0]
    up, source = g.body_up(J)
    assert source == "all_frames" and np.allclose(up, [0, 1, 0])
