import numpy as np

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


def test_choose_subject_follows_previous_box_over_larger_passerby():
    from part2.body3d import choose_subject, iou_xyxy

    subject, passerby = [100, 100, 200, 400], [300, 0, 700, 720]
    dets = np.array([passerby, subject], dtype=float)
    assert choose_subject(dets, None) == 0  # first frame: largest
    assert choose_subject(dets, np.array([105, 98, 205, 402.0])) == 1  # then: continue the subject
    assert choose_subject(dets, np.array([900, 900, 950, 950.0])) == 0  # lost: back to largest
    assert iou_xyxy(subject, subject) == 1.0 and iou_xyxy(subject, [500, 500, 600, 600]) == 0.0
