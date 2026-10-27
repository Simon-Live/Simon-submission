"""Step 5b: centred 5-frame mean of every joint position within runs of present frames."""

import numpy as np

WINDOW = 5


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
