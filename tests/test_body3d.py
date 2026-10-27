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
