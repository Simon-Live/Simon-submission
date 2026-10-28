"""Put a loaded clip into the shape the measurements expect.

- Re-centre every frame on the hip midpoint (inputs are allowed up to 1 cm off).
- Light Savitzky–Golay smoothing over time to cut estimator jitter. Masked joints stay NaN
  and are never smoothed into their neighbours.
"""
from dataclasses import replace

import numpy as np

from .io import JOINTS, Clip

L_HIP, R_HIP = JOINTS.index("left_hip"), JOINTS.index("right_hip")


def savgol_coeffs(window, order):
    """Centre-point Savitzky–Golay weights (least-squares polynomial fit over the window)."""
    if window % 2 == 0 or window <= order:
        raise ValueError("window must be odd and larger than order")
    half = window // 2
    x = np.arange(-half, half + 1)
    A = np.vander(x, order + 1, increasing=True)
    return np.linalg.pinv(A)[0]


def recentre(positions, mask):
    """Subtract the hip midpoint per frame; frames without both hips are left as they are."""
    out = positions.copy()
    ok = mask[:, L_HIP] & mask[:, R_HIP]
    hip = (positions[:, L_HIP] + positions[:, R_HIP]) / 2
    out[ok] -= hip[ok][:, None, :]
    return out


def smooth(positions, mask, window=5, order=2):
    """Smooth each joint over time. A frame is smoothed only if its whole window is valid."""
    if window <= 1:
        return positions.copy()
    w = savgol_coeffs(window, order)
    half = window // 2
    out = positions.copy()
    n = len(positions)
    for j in range(positions.shape[1]):
        for i in range(half, n - half):
            if mask[i - half:i + half + 1, j].all():
                out[i, j] = w @ positions[i - half:i + half + 1, j]
    return out


def normalise(clip: Clip, window=5, order=2) -> Clip:
    pos = recentre(clip.positions, clip.mask)
    pos = smooth(pos, clip.mask, window, order)
    pos = recentre(pos, clip.mask)
    pos[~clip.mask] = np.nan
    return replace(clip, positions=pos)
