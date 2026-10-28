"""Step 5b: centred mean over 1/3 s of every joint position within runs of present frames."""

import numpy as np

WINDOW = 5          # frames at CALIBRATED_FPS, the rate the filter was calibrated on
CALIBRATED_FPS = 15.0
WINDOW_S = WINDOW / CALIBRATED_FPS


def window_for(t_ms):
    """Odd window width in frames for a clip whose frames sit at `t_ms` (spec step 5b, ASM-018).

    fps is 1000 over the median step; the width is the odd number nearest to fps * WINDOW_S, the
    smaller on a tie, at least 1. Without two increasing times it is WINDOW.
    """
    t = np.asarray([v for v in t_ms if v is not None], dtype=float)
    steps = np.diff(t)
    steps = steps[steps > 0]
    if steps.size == 0:
        return WINDOW
    target = (1000.0 / float(np.median(steps))) * WINDOW_S
    below = max(1, int(np.floor((target - 1) / 2)) * 2 + 1)
    above = below + 2
    return above if abs(above - target) < abs(target - below) else below


def centred_mean(x, width):
    """Centred moving average of `x` over axis 0 with edge values repeated (odd `width`)."""
    x = np.asarray(x, dtype=float)
    half = width // 2
    padded = np.pad(x, [(half, half)] + [(0, 0)] * (x.ndim - 1), mode="edge")
    return sum(padded[k:k + len(x)] for k in range(width)) / width


def runs(present):
    """(start, stop) index pairs of the consecutive True stretches of a boolean sequence."""
    present = np.asarray(present, dtype=bool)
    edges = np.diff(np.concatenate([[0], present.astype(int), [0]]))
    return list(zip(np.flatnonzero(edges == 1).tolist(), np.flatnonzero(edges == -1).tolist()))


def smooth(J, present, window=WINDOW):
    """Centred `window`-frame mean of J (N, 17, 3) inside each run of `present` frames.

    The end frame of a run is repeated at the run's ends. Frames that are not present are copied
    unchanged. Returns a new array.
    """
    J = np.asarray(J, dtype=float)
    out = np.array(J, copy=True)
    for start, stop in runs(present):
        out[start:stop] = centred_mean(J[start:stop], window)
    return out
