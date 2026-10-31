import numpy as np
import pytest

from part2.body3d import project
from part2.joints import CANONICAL, MHR70, MHR70_INDEX


def test_canonical_joints_match_readme_order_and_map_to_mhr70():
    assert len(CANONICAL) == 17 == len(set(MHR70_INDEX))
    assert CANONICAL[9:11] == ["left_wrist", "right_wrist"]
    assert MHR70_INDEX[9:11] == [62, 41]
    assert set(MHR70) == set(CANONICAL)


def test_project_pinhole():
    K = np.array([[1000.0, 0, 640], [0, 1000.0, 360], [0, 0, 1]])
    pts = np.array([[0.0, 0.0, 2.0], [0.2, -0.1, 4.0]])
    np.testing.assert_allclose(project(pts, K), [[640, 360], [690, 335]])


def test_one_guarded_projection_serves_the_model_the_rungs_and_the_foot_points():
    from part2 import lifters
    from part2.refine import kp2d_fit, temporal

    assert project is lifters.project is kp2d_fit.project is temporal.project  # R5: not a second formula
    K = np.array([[1000.0, 0, 640], [0, 1000.0, 360], [0, 0, 1]])
    for z in (0.0, 1e-12, -1e-12):  # a point in the camera plane: finite pixels, no division by zero
        with np.errstate(all="raise"):
            uv = project(np.array([[0.1, -0.2, z], [0.0, 0.0, 2.0]]), K)
        assert np.isfinite(uv).all()
        np.testing.assert_allclose(uv[1], [640, 360])
    assert project(np.array([[0.5, 0.25, 0.0]]), K)[0, 0] == pytest.approx(640 + 0.5 / 1e-9 * 1000.0)


def test_moved_feet_projects_a_foot_point_in_the_camera_plane_to_finite_pixels():
    from part2.body3d import moved_feet

    K = np.array([[1000.0, 0, 640], [0, 1000.0, 360], [0, 0, 1]])
    joints = {j: [0.0, 0.0, 3.0] for j in CANONICAL}
    person = {"kp3d_cam": joints, "extra_kp3d_cam": {"left_heel": [0.1, 0.0, 0.0], "right_heel": [0.0, 0.0, 3.0]},
              "extra_kp2d": {"left_heel": [0.0, 0.0], "right_heel": [0.0, 0.0]}}
    with np.errstate(all="raise"):
        out = moved_feet(person, joints, K)
    assert np.isfinite(list(out["extra_kp2d"].values())).all() and out["extra_kp2d"]["right_heel"] == [640.0, 360.0]
    assert moved_feet({"kp3d_cam": joints}, joints, K) == {}


def test_choose_subject_follows_previous_box_over_larger_passerby():
    from part2.body3d import choose_subject, iou_xyxy

    subject, passerby = [100, 100, 200, 400], [300, 0, 700, 720]
    dets = np.array([passerby, subject], dtype=float)
    assert choose_subject(dets, None) == 0  # first frame: largest
    assert choose_subject(dets, np.array([105, 98, 205, 402.0])) == 1  # then: continue the subject
    assert choose_subject(dets, np.array([900, 900, 950, 950.0])) == 0  # lost: back to largest
    assert iou_xyxy(subject, subject) == 1.0 and iou_xyxy(subject, [500, 500, 600, 600]) == 0.0
