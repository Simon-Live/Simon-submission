import json
from pathlib import Path

import numpy as np
import pytest

from part5.align import align, dtw
from part5.io import load_clip

ROOT = Path(__file__).resolve().parent.parent


def expected(name="exercise"):
    return load_clip(ROOT / f"fixtures/input/expected/{name}/animation.json").positions


def resample(p, speed, lead_in=0, tail=0):
    n = len(p)
    u = np.arange(0, n - 1 + 1e-9, speed)
    i0 = np.floor(u).astype(int)
    i1 = np.minimum(i0 + 1, n - 1)
    a = (u - i0)[:, None, None]
    out = p[i0] * (1 - a) + p[i1] * a
    return np.concatenate([np.repeat(p[:1], lead_in, 0), out, np.repeat(p[-1:], tail, 0)]), u


def test_dtw_on_identical_sequences_is_diagonal():
    x = np.arange(10.0)
    path, cost = dtw(np.abs(x[:, None] - x[None, :]), open_begin=False, open_end=False)
    assert path == [(i, i) for i in range(10)] and cost == 0


@pytest.mark.parametrize("name", ["exercise", "dance"])
def test_identity(name):
    p = expected(name)
    a = align(p, p)
    assert a.residual < 1e-9
    assert (a.exp_to_fol == np.arange(len(p))).all()


@pytest.mark.parametrize("speed, lead_in, tail", [(0.5, 0, 0), (1.5, 0, 0), (1.0, 12, 0), (0.8, 7, 9), (1.25, 15, 5)])
def test_time_warped_copy_aligns(speed, lead_in, tail):
    p = expected("dance")
    f, u = resample(p, speed, lead_in, tail)
    a = align(p, f)
    assert a.residual < 0.05
    # Where the expected frame has a follower sample at the same time, the match is within 1 frame.
    true = lead_in + np.arange(len(p)) / speed
    moving = np.arange(5, len(p) - 5)
    assert np.median(np.abs(a.exp_to_fol[moving] - true[moving])) <= 1.0


@pytest.fixture(scope="module")
def dummy_errors():
    """Median |matched − true| follower frame per dummy take, from the generator's known warp."""
    labels = json.loads((ROOT / "fixtures/input/followers/labels.json").read_text())
    out = {}
    for t in labels["takes"]:
        e = load_clip(ROOT / t["expected"]).positions
        f = load_clip(ROOT / t["follower"]).positions
        a = align(e, f)
        k = np.arange(5, len(e) - 5)
        out[t["take_id"]] = (t, float(np.median(np.abs(a.exp_to_fol[k] - (t["lead_in_frames"] + k / t["speed"])))))
    return out


@pytest.mark.parametrize("lighting, kind, p50, p90", [
    ("good", "correct", 1.5, 2.5), ("good", "fault", 1.5, 4.0),
    ("low", "correct", 2.5, 4.5), ("low", "fault", 2.5, 4.5),
])
def test_dummy_takes_recover_their_timing(dummy_errors, lighting, kind, p50, p90):
    errs = [e for t, e in dummy_errors.values() if t["lighting"] == lighting and bool(t["faults"]) == (kind == "fault")]
    assert np.median(errs) <= p50
    assert np.percentile(errs, 90) <= p90


def test_held_fault_offset_does_not_shift_timing():
    p = expected("dance")
    f, _ = resample(p, 1.1, 6, 4)
    # Elbows held 30° wider all the way through: a constant offset in the out measures.
    from part5.io import JOINTS
    sh, el, wr = (JOINTS.index(f"left_{x}") for x in ("shoulder", "elbow", "wrist"))
    th = np.radians(30)
    R = np.array([[np.cos(th), -np.sin(th), 0], [np.sin(th), np.cos(th), 0], [0, 0, 1]])
    for j in (el, wr):
        f[:, j] = f[:, sh] + (f[:, j] - f[:, sh]) @ R.T
    a = align(p, f)
    true = 6 + np.arange(len(p)) / 1.1
    k = np.arange(5, len(p) - 5)
    assert np.median(np.abs(a.exp_to_fol[k] - true[k])) <= 1.0


def test_masked_follower_joint_still_aligns():
    p = expected("exercise")
    f, _ = resample(p, 0.9, 5, 0)
    f[20:45, 9] = np.nan  # left wrist lost for almost a second
    a = align(p, f)
    true = 5 + np.arange(len(p)) / 0.9
    k = np.arange(5, len(p) - 5)
    assert np.median(np.abs(a.exp_to_fol[k] - true[k])) <= 1.0
    assert np.isfinite(a.residual)


def test_phase_is_monotonic_and_spans_0_to_1():
    p = expected("exercise")
    f, _ = resample(p, 1.2, 8, 6)
    a = align(p, f)
    ph = a.fol_phase[np.isfinite(a.fol_phase)]
    assert ph[0] == 0 and ph[-1] == 1 and np.all(np.diff(ph) >= 0)
    assert np.isnan(a.fol_phase[:a.follower_span[0]]).all()
    assert all(b[0] >= a_[0] and b[1] >= a_[1] for a_, b in zip(a.path, a.path[1:]))


def test_out_of_range_speed_is_an_error():
    p = expected("exercise")
    with pytest.raises(ValueError, match="too short or too long"):
        align(p, p[::3])
