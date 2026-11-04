"""Phase alignment of takes for the 4-take agreement (spec part3-skeleton.md "Phase alignment", ADR-0003).

One summary signal per take (the mean of the 8 interior angles), dynamic time warping of each take
to the reference take under a Sakoe-Chiba band, a smoothed fractional frame map, and linear
interpolation of the 9 angles at the mapped positions.
"""

import math

import numpy as np

from part3.temporal import centred_mean

BAND_FRACTION = 0.25
SIGNAL_ANGLES = 8  # the 8 interior angles; trunk inclination is not part of the signal
SIGNAL_SMOOTH = 5
MAP_SMOOTH = 3


def phase_signal(angles):
    """(n,) phase signal: mean of the 8 interior angles (degrees, not z-scored), 5-frame centred mean.

    Frames without a person (NaN rows) are filled by linear interpolation before smoothing so the
    signal stays defined; an all-NaN input gives an all-NaN signal.
    """
    a = np.asarray(angles, dtype=float)[:, :SIGNAL_ANGLES]
    valid = np.isfinite(a).all(axis=1)
    if not valid.any():
        return np.full(len(a), np.nan)
    raw = a.mean(axis=1)
    idx = np.arange(len(a))
    raw = np.interp(idx, idx[valid], raw[valid])
    return centred_mean(raw, SIGNAL_SMOOTH)


def _band(i, n, m):
    """Allowed j for row i: |i (m-1)/(n-1) - j| <= ceil(0.25 max(n, m))."""
    half = math.ceil(BAND_FRACTION * max(n, m))
    centre = i * (m - 1) / (n - 1) if n > 1 else 0.0
    lo = max(0, math.ceil(centre - half))
    hi = min(m - 1, math.floor(centre + half))
    return range(lo, hi + 1)


def _accumulate(a, b):
    """Cumulative cost matrix (list of rows, inf outside the band); steps (1,0), (0,1), (1,1), weight 1."""
    n, m = len(a), len(b)
    inf = math.inf
    D = [[inf] * m for _ in range(n)]
    for i in range(n):
        for j in _band(i, n, m):
            if i == 0 and j == 0:
                best = 0.0
            else:
                diag = D[i - 1][j - 1] if i and j else inf
                up = D[i - 1][j] if i else inf
                left = D[i][j - 1] if j else inf
                best = min(diag, up, left)
            D[i][j] = abs(a[i] - b[j]) + best
    return D


def dtw_path(a, b):
    """Optimal warping path [(i, j), ...] from (0, 0) to (n-1, m-1) between 1-D signals a and b.

    Local cost |a_i - b_j|; ties prefer the diagonal step, then (1,0), then (0,1).
    """
    a = [float(v) for v in a]
    b = [float(v) for v in b]
    n, m = len(a), len(b)
    D = _accumulate(a, b)
    i, j = n - 1, m - 1
    path = [(i, j)]
    while (i, j) != (0, 0):
        options = []
        if i and j:
            options.append((D[i - 1][j - 1], 0, (i - 1, j - 1)))
        if i:
            options.append((D[i - 1][j], 1, (i - 1, j)))
        if j:
            options.append((D[i][j - 1], 2, (i, j - 1)))
        i, j = min(options)[2]
        path.append((i, j))
    path.reverse()
    return path


def frame_map(ref_signal, signal):
    """(n_ref,) fractional positions in the other take for every reference frame.

    The middle of the sorted j paired with i (index (count-1)//2), then a centred 3-frame mean.
    """
    n = len(ref_signal)
    paired = [[] for _ in range(n)]
    for i, j in dtw_path(ref_signal, signal):
        paired[i].append(j)
    middle = np.array([sorted(js)[(len(js) - 1) // 2] for js in paired], dtype=float)
    return centred_mean(middle, MAP_SMOOTH)


def sample(angles, positions):
    """(n_ref, 9) linear interpolation of the angles at fractional frame `positions`.

    NaN where either neighbouring frame (floor and ceil of the position) has no person.
    """
    a = np.asarray(angles, dtype=float)
    p = np.clip(np.asarray(positions, dtype=float), 0, len(a) - 1)
    lo = np.floor(p).astype(int)
    hi = np.ceil(p).astype(int)
    w = (p - lo)[:, None]
    return a[lo] * (1.0 - w) + a[hi] * w
