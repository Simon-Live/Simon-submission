import json
from pathlib import Path

import numpy as np

from part5.align import align
from part5.io import load_clip
from part5.normalise import normalise
from part5.pipeline import analyse, resample

ROOT = Path(__file__).resolve().parent.parent
EXPECTED = ROOT / "fixtures/input/expected/exercise/animation.json"
TAKE = ROOT / "fixtures/input/followers/exercise/exercise_front_good_08_arms_wider-both+elbow_bent-right/skeleton.json"


def decimate(src, dst, step):
    doc = json.loads(Path(src).read_text())
    doc["frames"] = [dict(f, index=i) for i, f in enumerate(doc["frames"][::step])]
    doc["fps"] = doc["fps"] / step
    doc["frame_count"] = len(doc["frames"])
    dst.write_text(json.dumps(doc))
    return doc


def test_same_rate_is_a_no_op():
    t = np.arange(10) / 30
    p = np.random.default_rng(0).normal(size=(10, 17, 3))
    out, idx = resample(p, t, 30.0)
    assert out is p and list(idx) == list(range(10))


def test_the_last_frame_survives_a_gap_just_before_it():
    t = np.arange(4) / 15
    p = np.zeros((4, 17, 3))
    p[2, 3] = np.nan
    out, idx = resample(p, t, 30.0)
    assert idx[-1] == 3 and np.isfinite(out[-1, 3]).all()
    assert np.isnan(out[4:6, 3]).all()


def test_half_rate_doubles_frames_and_maps_back():
    t = np.arange(5) / 15
    p = np.zeros((5, 17, 3))
    p[:, 0, 0] = np.arange(5)
    out, idx = resample(p, t, 30.0)
    assert len(out) == 9
    assert np.allclose(out[:, 0, 0], np.arange(9) / 2)
    assert list(idx[::2]) == list(range(5))


def test_a_missing_joint_is_not_bridged():
    t = np.arange(4) / 15
    p = np.zeros((4, 17, 3))
    p[1, 3] = np.nan
    out, _ = resample(p, t, 30.0)
    assert np.isnan(out[1:4, 3]).all() and np.isfinite(out[[0, 4, 5, 6], 3]).all()


def test_a_15fps_take_gives_the_same_faults_in_its_own_frames(tmp_path):
    full = analyse(EXPECTED, TAKE)
    decimate(TAKE, tmp_path / "skeleton.json", 2)
    half = analyse(EXPECTED, tmp_path / "skeleton.json")
    key = lambda f: (f["measure"], f["side"], f["direction"])
    assert sorted(map(key, half["faults"])) == sorted(map(key, full["faults"]))
    # Which run a fault reports can shift with resampling noise (only the longest counts, #30),
    # so check consistency with the 30 fps timing rather than identical runs: each 15 fps fault's
    # follower_frames must be where the 30 fps alignment puts its expected_frames, halved.
    exp_to_fol = align(normalise(load_clip(EXPECTED)).positions,
                       normalise(load_clip(TAKE)).positions).exp_to_fol
    for f in half["faults"]:
        want = [exp_to_fol[i] / 2 for i in f["expected_frames"]]
        assert all(abs(got - w) <= 2 for got, w in zip(f["follower_frames"], want)), (f, want)
    for a, b in zip(sorted(full["faults"], key=key), sorted(half["faults"], key=key)):
        assert abs(a["magnitude_deg"] - b["magnitude_deg"]) <= 1.5
    n = len(json.loads((tmp_path / "skeleton.json").read_text())["frames"])
    assert 0 <= half["diagnostics"]["follower_span"][0] <= half["diagnostics"]["follower_span"][1] < n


def test_a_5fps_copy_of_the_expected_clip_matches_it(tmp_path):
    # Track A's case on #33: same movement, same speed, 5 fps against 30 fps used to fail
    # as "more than 2x faster". Resampled, it aligns over the whole clip with no faults.
    doc = decimate(EXPECTED, tmp_path / "skeleton.json", 6)
    r = analyse(EXPECTED, tmp_path / "skeleton.json")
    assert r["faults"] == [] and r["diagnostics"]["warnings"] == []
    assert r["diagnostics"]["follower_span"][1] == len(doc["frames"]) - 1
