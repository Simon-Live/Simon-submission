"""Step 5b: centred 5-frame mean inside runs of present frames."""

import numpy as np

from clipkit import doc_arrays, make_doc, skeleton_arrays
from part3 import cli, geometry, temporal


def ramp(n):
    """(n, 17, 3) where every coordinate of frame i equals i squared."""
    return np.broadcast_to((np.arange(n, dtype=float) ** 2)[:, None, None], (n, 17, 3)).copy()


def test_centred_mean_repeats_edges():
    assert np.allclose(temporal.centred_mean([1, 2, 3, 4, 5], 3), [4 / 3, 2, 3, 4, 14 / 3])
    assert np.allclose(temporal.centred_mean([2, 2, 2, 2], 5), 2)
    two_d = temporal.centred_mean(np.arange(10.0).reshape(5, 2), 3)
    assert two_d.shape == (5, 2) and np.allclose(two_d[2], [4, 5])


def test_centred_five_frame_mean_with_repeated_ends():
    out = temporal.smooth(ramp(8), np.ones(8, dtype=bool))
    v = np.arange(8, dtype=float) ** 2
    padded = np.concatenate([[v[0], v[0]], v, [v[-1], v[-1]]])
    expected = np.array([padded[i:i + 5].mean() for i in range(8)])
    assert np.allclose(out[:, 0, 0], expected)
    assert np.allclose(out[:, 16, 2], expected)
    assert np.isclose(out[0, 0, 0], (3 * v[0] + v[1] + v[2]) / 5)  # the end frame is repeated
    assert np.isclose(out[7, 0, 0], (3 * v[7] + v[6] + v[5]) / 5)
    assert np.isclose(out[3, 0, 0], v[1:6].mean())  # centred on the frame itself


def test_runs_are_split_by_frames_without_the_person():
    present = np.array([1, 1, 1, 0, 1, 1, 1, 1, 0, 0, 1], dtype=bool)
    assert temporal.runs(present) == [(0, 3), (4, 8), (10, 11)]
    assert temporal.runs(np.zeros(4, dtype=bool)) == []
    assert temporal.runs(np.ones(4, dtype=bool)) == [(0, 4)]
    out = temporal.smooth(ramp(11), present)
    v = np.arange(11, dtype=float) ** 2
    # Frame 2 ends the run 0-2: its window is frames 0, 1, 2, 2, 2 and never reaches frame 4.
    assert np.isclose(out[2, 0, 0], (v[0] + v[1] + 3 * v[2]) / 5)
    assert np.isclose(out[4, 0, 0], (3 * v[4] + v[5] + v[6]) / 5)
    assert out[10, 0, 0] == v[10]  # a run of one frame is unchanged
    assert out[3, 0, 0] == v[3] and out[8, 0, 0] == v[8]  # absent frames are copied unchanged


def test_constant_signal_and_short_runs():
    J = np.full((6, 17, 3), 0.25)
    assert np.allclose(temporal.smooth(J, np.ones(6, dtype=bool)), J)
    two = temporal.smooth(ramp(2), np.ones(2, dtype=bool))  # frame values 0 and 1
    assert np.allclose(two[:, 0, 0], [0.4, 0.6])


def test_input_is_not_modified_and_empty_is_fine():
    J = ramp(5)
    before = J.copy()
    temporal.smooth(J, np.ones(5, dtype=bool))
    assert np.array_equal(J, before)
    assert temporal.smooth(np.zeros((0, 17, 3)), np.zeros(0, dtype=bool)).shape == (0, 17, 3)


def test_pipeline_filters_only_inside_runs_and_leaves_conf_alone(real_doc):
    J, conf = doc_arrays(real_doc)
    whole = cli.process(make_doc(J, conf))
    cut = make_doc(J, conf)
    cut["frames"][50]["people"] = []
    split = cli.process(cut)
    whole_J, whole_conf, _ = skeleton_arrays(whole)
    split_J, split_conf, present = skeleton_arrays(split)
    assert not present[50] and present.sum() == len(J) - 1
    assert np.array_equal(whole_conf, conf)  # conf is copied unchanged
    assert np.array_equal(whole_conf[present], split_conf[present])
    far = [i for i in range(len(J)) if abs(i - 50) > 2]
    assert np.allclose(whole_J[far], split_J[far], atol=1e-4)  # beyond the filter's reach: equal
    assert np.abs(whole_J[[49, 51]] - split_J[[49, 51]]).max() > 1e-4  # next to the gap the window is cut


def test_filter_moves_the_deepest_knee_angle_by_under_a_degree(real_doc):
    J, _ = doc_arrays(real_doc)
    out_J, _, _ = skeleton_arrays(cli.process(real_doc))
    # Interior angles ignore the body frame and the retarget keeps bone directions: only the filter acts.
    assert abs(geometry.knee_angles(out_J).min() - geometry.knee_angles(J).min()) < 1.0
