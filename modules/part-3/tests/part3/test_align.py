"""Phase alignment machinery (AC-008): signal, DTW, frame map, sampling."""

import math

import numpy as np
import pytest

from part3 import align
from part3.align import dtw_path, frame_map, phase_signal, sample
from part3.temporal import centred_mean


def curve(x, n):
    """A smooth, non-flat test signal with several turning points over [0, n-1]."""
    return 100 + 20 * np.sin(2 * np.pi * x / n * 2.3) + 9 * np.sin(2 * np.pi * x / n * 5.1 + 1.0) + x * 0.4


def in_band(i, j, n, m):
    return abs(i * (m - 1) / (n - 1) - j) <= math.ceil(0.25 * max(n, m))


def test_phase_signal_is_the_mean_of_the_first_eight_angles_smoothed():
    angles = np.tile(np.arange(9, dtype=float) * 10, (7, 1))
    angles[:, 8] = 999.0  # trunk inclination is not part of the signal
    assert np.allclose(phase_signal(angles), np.arange(8).mean() * 10)
    ramp = np.zeros((9, 9))
    ramp[:, 0] = np.arange(9) * 8.0  # mean over 8 angles = i
    expected = centred_mean(np.arange(9.0), 5)
    assert np.allclose(phase_signal(ramp), expected)


def test_phase_signal_fills_frames_without_a_person():
    angles = np.full((6, 9), 50.0)
    angles[2] = np.nan
    signal = phase_signal(angles)
    assert np.isfinite(signal).all() and np.allclose(signal, 50.0)
    assert np.isnan(phase_signal(np.full((4, 9), np.nan))).all()


def test_identical_sequences_align_on_the_diagonal():
    a = curve(np.arange(40), 40)
    assert dtw_path(a, a) == [(i, i) for i in range(40)]
    mapped = frame_map(a, a)
    assert np.allclose(mapped[1:-1], np.arange(1, 39))
    assert np.allclose(mapped[[0, -1]], [1 / 3, 39 - 1 / 3])  # the 3-frame mean repeats edge frames


def test_time_stretched_copy_maps_within_one_frame_of_truth():
    n, stretch = 90, 1.15
    m = int(round(n * stretch))
    a = curve(np.arange(n), n)
    b = curve(np.arange(m) / stretch, n)
    mapped = frame_map(a, b)
    truth = np.minimum(np.arange(n) * stretch, m - 1)
    assert np.abs(mapped - truth)[1:-1].max() <= 1.0


def test_path_starts_and_ends_at_the_corners_with_legal_steps():
    a, b = curve(np.arange(50), 50), curve(np.arange(61) / 1.2, 50)
    path = dtw_path(a, b)
    assert path[0] == (0, 0) and path[-1] == (49, 60)
    assert {(i2 - i1, j2 - j1) for (i1, j1), (i2, j2) in zip(path, path[1:])} <= {(1, 0), (0, 1), (1, 1)}


def test_band_constraint_holds_even_when_the_best_match_is_outside():
    n = 40
    a = np.zeros(n)
    a[5] = 50.0
    b = np.zeros(n)
    b[32] = 50.0  # the peak sits 27 frames away, band half-width is ceil(0.25 * 40) = 10
    path = dtw_path(a, b)
    assert all(in_band(i, j, n, n) for i, j in path)
    assert (5, 32) not in path  # the unconstrained optimum would pair the two peaks


STEP_PRIORITY = {(1, 1): 0, (1, 0): 1, (0, 1): 2}  # diagonal, then (1,0), then (0,1)


def all_paths(n, m):
    """Every monotone in-band path from (0,0) to (n-1,m-1)."""
    def walk(i, j, cells):
        if (i, j) == (n - 1, m - 1):
            yield list(cells)
            return
        for di, dj in STEP_PRIORITY:
            ni, nj = i + di, j + dj
            if ni < n and nj < m and in_band(ni, nj, n, m):
                cells.append((ni, nj))
                yield from walk(ni, nj, cells)
                cells.pop()
    yield from walk(0, 0, [(0, 0)])


def reference_path(a, b):
    """Brute force: the cheapest path; ties broken by the step priorities read from the end."""
    def key(path):
        cost = sum(abs(a[i] - b[j]) for i, j in path)
        backwards = [STEP_PRIORITY[(p[0] - q[0], p[1] - q[1])] for p, q in zip(path[:0:-1], path[-2::-1])]
        return cost, backwards
    return min(all_paths(len(a), len(b)), key=key)


@pytest.mark.parametrize("seed", range(20))
def test_ties_prefer_diagonal_then_down_then_right(seed):
    rng = np.random.default_rng(seed)
    n, m = rng.integers(3, 6, size=2)
    a, b = rng.integers(0, 3, n), rng.integers(0, 3, m)  # small integers: many equal costs
    assert dtw_path(a, b) == reference_path(a, b)


def test_constant_signals_take_the_diagonal():
    assert dtw_path([0, 0, 0], [0, 0, 0]) == [(0, 0), (1, 1), (2, 2)]


def test_frame_map_takes_the_middle_paired_frame_then_smooths(monkeypatch):
    path = [(0, 0), (0, 1), (0, 2), (1, 3), (2, 3), (2, 4)]
    monkeypatch.setattr(align, "dtw_path", lambda a, b: path)
    # i=0 pairs j 0,1,2 -> middle 1; i=1 -> 3; i=2 pairs 3,4 -> index (2-1)//2 = 0 -> 3
    assert np.allclose(frame_map([0, 0, 0], [0] * 5), centred_mean([1, 3, 3], 3))
    assert np.allclose(frame_map([0, 0, 0], [0] * 5), [5 / 3, 7 / 3, 3.0])


def test_sample_interpolates_linearly_and_clips():
    angles = np.stack([np.arange(5.0) * 10, np.arange(5.0) * -2], axis=1)
    out = sample(angles, [0.0, 0.5, 1.25, 4.0, 9.0, -3.0])
    assert np.allclose(out[:, 0], [0, 5, 12.5, 40, 40, 0])
    assert np.allclose(out[:, 1], [0, -1, -2.5, -8, -8, 0])


def test_sample_is_nan_where_a_neighbour_frame_has_no_person():
    angles = np.arange(12.0).reshape(4, 3)
    angles[1] = np.nan
    out = sample(angles, [0.0, 0.5, 1.0, 1.5, 2.0, 2.5])
    assert np.isfinite(out[[0, 4, 5]]).all()
    assert np.isnan(out[[1, 2, 3]]).all()
