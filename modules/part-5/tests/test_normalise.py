from dataclasses import replace
from pathlib import Path

import numpy as np

from part5.io import JOINTS, load_clip
from part5.normalise import normalise, recentre, savgol_coeffs, smooth

ROOT = Path(__file__).resolve().parent.parent
EXPECTED = ROOT / "fixtures/input/expected/exercise/animation.json"
L_HIP, R_HIP = JOINTS.index("left_hip"), JOINTS.index("right_hip")


def test_savgol_preserves_quadratics():
    w = savgol_coeffs(5, 2)
    x = np.arange(-2, 3)
    assert np.isclose(w.sum(), 1)
    assert np.isclose(w @ (3 + 2 * x + 0.5 * x**2), 3)


def test_recentre_puts_hip_midpoint_at_origin():
    clip = load_clip(EXPECTED)
    shifted = clip.positions + np.array([0.005, -0.004, 0.003])
    out = recentre(shifted, clip.mask)
    hip = (out[:, L_HIP] + out[:, R_HIP]) / 2
    assert np.abs(hip).max() < 1e-12


def test_smoothing_reduces_jitter_but_keeps_motion():
    clip = load_clip(EXPECTED)
    rng = np.random.default_rng(0)
    noisy = clip.positions + rng.normal(0, 0.01, clip.positions.shape)
    out = smooth(noisy, clip.mask, window=5)
    err_before = np.abs(noisy - clip.positions)[2:-2].mean()
    err_after = np.abs(out - clip.positions)[2:-2].mean()
    assert err_after < 0.75 * err_before


def test_masked_joints_stay_nan_and_do_not_leak():
    clip = load_clip(EXPECTED)
    mask = clip.mask.copy()
    pos = clip.positions.copy()
    wr = JOINTS.index("left_wrist")
    mask[10, wr] = False
    pos[10, wr] = np.nan
    out = normalise(replace(clip, positions=pos, mask=mask))
    assert np.isnan(out.positions[10, wr]).all()
    assert np.isfinite(out.positions[8:13, wr][[0, 1, 3, 4]]).all()
    assert np.isfinite(out.positions[:, JOINTS.index("right_wrist")]).all()


def test_clean_clip_barely_changes():
    clip = load_clip(EXPECTED)
    out = normalise(clip)
    assert np.nanmax(np.abs(out.positions - clip.positions)) < 0.01
