"""Phase alignment: match each expected frame to the follower frame at the same point in the movement.

Dynamic time warping over the #6 measures that move in the expected clip, z-scaled per measure
by the expected clip's spread, with constant follower offsets (held faults) removed.
Open begin and open end: the follower may idle before starting or after finishing, and
those frames are skipped instead of being forced onto the first or last expected pose.
"""
from dataclasses import dataclass

import numpy as np

from .measures import MEASURES, compute

# Measures that drive alignment; head_forward is noisy and adds little timing information.
ALIGN_MEASURES = [m for m in MEASURES if m != "head_forward"]
MIN_SPREAD_DEG = 5.0


@dataclass
class Alignment:
    path: list[tuple[int, int]]   # (expected frame, follower frame), monotonic
    exp_to_fol: np.ndarray        # (N_expected,) follower frame matched to each expected frame
    fol_phase: np.ndarray         # (N_follower,) 0..1 phase, NaN outside the matched span
    residual: float               # mean cost per path cell (z units)
    measures: list[str]           # measures the timing was taken from

    @property
    def follower_span(self):
        return self.path[0][1], self.path[-1][1]


def _fill_nan(x):
    """Linear interpolation over time for each column; all-NaN columns become 0."""
    x = x.copy()
    t = np.arange(len(x))
    for c in range(x.shape[1]):
        ok = np.isfinite(x[:, c])
        if not ok.any():
            x[:, c] = 0.0
        elif not ok.all():
            x[:, c] = np.interp(t, t[ok], x[ok, c])
    return x


def features(measures, names, scale):
    """(F, M) in z-units of the expected clip's spread per measure."""
    return _fill_nan(np.stack([measures[n] for n in names], axis=1)) / scale


def timing_measures(exp_measures, min_spread=MIN_SPREAD_DEG):
    """Measures that move in the expected clip carry timing; static ones only add noise."""
    names, spread = [], []
    for n in ALIGN_MEASURES:
        sd = np.nanstd(exp_measures[n])
        if np.isfinite(sd) and sd >= min_spread:
            names.append(n)
            spread.append(sd)
    if not names:  # a nearly static clip: fall back to everything, floored
        names = list(ALIGN_MEASURES)
        spread = [max(np.nanstd(exp_measures[n]), min_spread) for n in names]
    return names, np.array(spread)


def dtw(cost, open_begin=True, open_end=True):
    """Slope-constrained DTW (rows = expected, cols = follower).

    Steps (1,1), (1,2) and (2,1), so the follower runs between half and double the expected
    speed and the path can't collapse onto a few frames. With open begin/end the follower
    may start late and finish early (idle lead-in and tail are skipped).
    Returns the path (every cell visited, monotonic) and the mean cost per cell.
    """
    n, m = cost.shape
    INF = np.inf
    D = np.full((n, m), INF)     # accumulated cost
    L = np.zeros((n, m))         # cells on the best path so far
    step = np.full((n, m), -1, np.int8)  # 0 = (1,1), 1 = (1,2), 2 = (2,1)
    if open_begin:
        D[0] = cost[0]
    else:
        D[0, 0] = cost[0, 0]
    L[0] = 1
    for i in range(1, n):
        c = cost[i]
        cands = np.full((3, m), INF)
        lens = np.zeros((3, m))
        cands[0, 1:] = D[i - 1, :-1] + c[1:]
        lens[0, 1:] = L[i - 1, :-1] + 1
        cands[1, 2:] = D[i - 1, :-2] + c[1:-1] + c[2:]
        lens[1, 2:] = L[i - 1, :-2] + 2
        if i >= 2:
            cands[2, 1:] = D[i - 2, :-1] + cost[i - 1, 1:] + c[1:]
            lens[2, 1:] = L[i - 2, :-1] + 2
        # Choose by mean cost per cell, so longer steps aren't favoured or penalised.
        with np.errstate(invalid="ignore", divide="ignore"):
            k = np.argmin(np.where(lens > 0, cands / np.maximum(lens, 1), INF), axis=0)
        cols = np.arange(m)
        D[i], L[i], step[i] = cands[k, cols], lens[k, cols], k
        step[i][~np.isfinite(D[i])] = -1
    with np.errstate(invalid="ignore"):
        mean_last = D[n - 1] / np.maximum(L[n - 1], 1)
    if not np.isfinite(mean_last).any():
        raise ValueError("follower clip is too short or too long to align (speed outside 0.5x–2x)")
    j = int(np.nanargmin(np.where(np.isfinite(mean_last), mean_last, np.inf))) if open_end else m - 1
    if not np.isfinite(D[n - 1, j]):
        raise ValueError("no alignment ends at the last follower frame")
    end_cost = float(mean_last[j])
    i, path = n - 1, [(n - 1, j)]
    while i > 0:
        s = step[i, j]
        if s == 0:
            i, j = i - 1, j - 1
        elif s == 1:
            path.append((i, j - 1))
            i, j = i - 1, j - 2
        else:
            path.append((i - 1, j))
            i, j = i - 2, j - 1
        path.append((i, j))
    path.reverse()
    if not open_begin and path[0] != (0, 0):
        raise ValueError("no alignment starts at the first follower frame")
    return path, end_cost


COST_CLIP_Z = 1.0


def _cost(fe, ff, clip=COST_CLIP_Z):
    """RMS over measures, each capped at `clip` z-units, so one measure that disagrees a lot
    (a fault in a measure that barely moves) can't drag the timing on its own."""
    d2 = (fe[:, None, :] - ff[None, :, :]) ** 2
    return np.sqrt(np.minimum(d2, clip * clip).mean(axis=2))


def align(expected_positions, follower_positions):
    exp_m, fol_m = compute(expected_positions), compute(follower_positions)
    names, scale = timing_measures(exp_m)
    fe, ff = features(exp_m, names, scale), features(fol_m, names, scale)
    # Two passes: a fault held all the way through (e.g. elbows wider) is a constant offset in
    # one measure, and it shouldn't pull the timing. Align, take the median follower − expected
    # offset along that path, remove it, then align again.
    path, _ = dtw(_cost(fe, ff))
    offset = np.median(np.array([ff[j] - fe[i] for i, j in path]), axis=0)
    path, mean_cost = dtw(_cost(fe, ff - offset))
    n, m = len(fe), len(ff)
    exp_to_fol = np.zeros(n, int)
    for i in range(n):
        js = [j for ii, j in path if ii == i]
        exp_to_fol[i] = js[len(js) // 2]
    fol_phase = np.full(m, np.nan)
    for i, j in path:
        if np.isnan(fol_phase[j]):
            fol_phase[j] = i / max(n - 1, 1)
    return Alignment(path, exp_to_fol, fol_phase, mean_cost, names)
