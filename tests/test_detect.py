import copy
import json
import sys
from pathlib import Path

import numpy as np
import pytest

from part5.align import align
from part5.detect import detect, differences, load_rules
from part5.io import JOINTS, load_clip
from part5.measures import compute
from part5.normalise import normalise

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import make_dummy_followers as gen  # noqa: E402  (the generator's fault functions, stdlib only)


def expected(name):
    return load_clip(ROOT / f"fixtures/input/expected/{name}/animation.json").positions


def with_fault(positions, ftype, side, amount, start=0.1, end=0.9):
    """Apply one of the generator's faults over [start, end] of the clip, noise-free."""
    frames = [{j: list(map(float, positions[i, k])) for k, j in enumerate(JOINTS)} for i in range(len(positions))]
    n = len(frames)
    w = [1.0 if start * n <= i <= end * n else 0.0 for i in range(n)]
    gen.APPLY[ftype](frames, side, amount, w)
    return np.array([[f[j] for j in JOINTS] for f in frames])


def run(exp, fol, rules=None):
    return detect(compute(exp), compute(fol), align(exp, fol), rules)


@pytest.mark.parametrize("name", ["exercise", "dance"])
def test_identical_inputs_give_no_faults(name):
    p = expected(name)
    assert run(p, p) == []


@pytest.mark.parametrize("name, ftype, side, amount, measure, want_side, direction", [
    ("dance", "arms_wider", "both", 20, "upper_arm_out", "both", "more"),
    ("dance", "arms_wider", "left", 20, "upper_arm_out", "left", "more"),
    ("exercise", "foot_out", "right", 15, "foot_out", "right", "more"),
    ("exercise", "knees_shallow", "both", 0.4, "knee_flexion", "both", "less"),
    ("dance", "elbow_bent", "right", 30, "elbow_flexion", "right", "more"),
    ("exercise", "trunk_lean", "center", 20, "trunk_lean_forward", "center", "more"),
])
def test_each_injected_fault_is_found_on_the_right_joint_and_side(name, ftype, side, amount, measure, want_side, direction):
    p = expected(name)
    faults = run(p, with_fault(p, ftype, side, amount))
    assert faults, "nothing detected"
    top = faults[0]
    assert (top.measure, top.side, top.direction) == (measure, want_side, direction), [
        (f.measure, f.side, f.direction, f.magnitude_deg) for f in faults]
    # Nothing else is reported for a single clean fault.
    assert len(faults) == 1, [(f.measure, f.side, f.direction, f.magnitude_deg) for f in faults]


def test_magnitude_and_frames_match_the_injection():
    p = expected("dance")
    f = run(p, with_fault(p, "elbow_bent", "left", 30, 0.2, 0.8))[0]
    assert f.magnitude_deg == pytest.approx(30, abs=3)
    s, e = f.expected_frames
    n = len(p)
    assert abs(s - 0.2 * n) <= 3 and abs(e - 0.8 * n) <= 3
    assert f.follower_frames == (s, e)  # identical timing
    assert 0 < f.confidence <= 1


def test_short_deviation_is_not_a_fault():
    p = expected("dance")
    assert run(p, with_fault(p, "elbow_bent", "left", 30, 0.4, 0.5)) == []


def test_forearm_follows_upper_arm_so_only_the_arm_is_reported():
    p = expected("dance")
    faults = run(p, with_fault(p, "arms_wider", "right", 25))
    assert [f.measure for f in faults] == ["upper_arm_out"]


def test_masked_joint_gives_no_fault_there():
    p = expected("dance")
    fol = with_fault(p, "elbow_bent", "left", 30)
    fol[:, JOINTS.index("left_wrist")] = np.nan
    assert all(f.measure not in ("elbow_flexion", "forearm_out") or f.side == "right" for f in run(p, fol))


def test_threshold_comes_from_rules():
    p = expected("dance")
    fol = with_fault(p, "elbow_bent", "left", 15)
    rules = load_rules()
    assert [f.measure for f in run(p, fol, rules)] == ["elbow_flexion"]
    strict = copy.deepcopy(rules)
    strict["measures"]["elbow_flexion"]["threshold_deg"] = 20
    assert run(p, fol, strict) == []


def test_timing_tolerance_absorbs_a_small_shift_only():
    e = {"knee": np.sin(np.linspace(0, np.pi, 50)) * 90}
    from part5.align import Alignment
    from part5 import detect as d
    m = {k: np.zeros(50) for k in d.MEASURES}
    em, fm = dict(m), dict(m)
    em["left_knee_flexion"] = e["knee"]
    fm["left_knee_flexion"] = np.roll(e["knee"], 2)
    a = Alignment([(i, i) for i in range(50)], np.arange(50), np.linspace(0, 1, 50), 0.0, [])
    loose = differences(em, fm, a, tolerance_frames=3)["left_knee_flexion"]
    tight = differences(em, fm, a, tolerance_frames=0)["left_knee_flexion"]
    assert np.abs(loose[5:-5]).max() < 1e-9 < np.abs(tight[5:-5]).max()
    fm["left_knee_flexion"] = e["knee"] + 20  # a held offset is not absorbed
    assert differences(em, fm, a, tolerance_frames=3)["left_knee_flexion"][10:40].min() > 5


def test_no_faults_on_good_light_correct_dummy_takes():
    labels = json.loads((ROOT / "fixtures/input/followers/labels.json").read_text())
    for t in labels["takes"]:
        if not t["correct"] or t["lighting"] != "good":
            continue
        e = normalise(load_clip(ROOT / t["expected"])).positions
        f = normalise(load_clip(ROOT / t["follower"])).positions
        assert run(e, f) == [], t["take_id"]
