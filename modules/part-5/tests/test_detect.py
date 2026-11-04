import copy
import json
import sys
from pathlib import Path

import numpy as np
import pytest

from part5.align import Alignment, align
from part5.detect import Fault, detect, differences, load_rules
from part5.io import JOINTS, load_clip
from part5.measures import MEASURES, compute
from part5.normalise import normalise

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import make_dummy_followers as gen  # noqa: E402  (the generator's fault functions, stdlib only)


def expected(name):
    return load_clip(ROOT / f"fixtures/input/expected/{name}/animation.json").positions


def with_fault(positions, ftype, side, amount, start=0.1, end=0.9, windows=None):
    """Apply one of the generator's faults over [start, end] of the clip (or over each of
    `windows`, a list of (start, end) fractions), noise-free."""
    frames = [{j: list(map(float, positions[i, k])) for k, j in enumerate(JOINTS)} for i in range(len(positions))]
    n = len(frames)
    windows = windows or [(start, end)]
    w = [1.0 if any(a * n <= i <= b * n for a, b in windows) else 0.0 for i in range(n)]
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
    rules["measures"]["elbow_flexion"]["threshold_deg"] = 12
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


def test_merge_sides_does_not_depend_on_order():
    from part5.detect import Fault, _merge_sides

    def fault(side, mag):
        return Fault(measure="upper_arm_out", side=side, joint=f"{side}_shoulder", body_part="upper arm",
                     direction="more", magnitude_deg=mag, peak_deg=mag + 2, threshold_deg=9,
                     expected_frames=(10, 60), follower_frames=(12, 64), phase=(0.1, 0.7),
                     coverage=1.0, confidence=0.9)

    for order in ([fault("left", 20), fault("right", 22)], [fault("right", 22), fault("left", 20)]):
        merged = _merge_sides(order)
        assert [(f.side, f.joint, f.magnitude_deg) for f in merged] == [("both", "shoulder", 21.0)]


# Persistence over runs, overlap and knee caving (#30, ADR-0004).

def synthetic(n, **spans):
    """All measures zero except `name=[(start, end, value), ...]` (inclusive frames)."""
    m = {k: np.zeros(n) for k in MEASURES}
    for name, runs in spans.items():
        for s, e, v in runs:
            m[name][s:e + 1] = v
    return m


def detect_synthetic(n, rules=None, **spans):
    """Detect on a follower that is the expected clip (all zero) plus `spans`, identity timing."""
    a = Alignment([(i, i) for i in range(n)], np.arange(n), np.linspace(0, 1, n), 0.0, [])
    return detect(synthetic(n), synthetic(n, **spans), a, rules)


def loose_rules(**default):
    """The shipped rules with a 10-frame persistence floor on a 100-frame clip, plus `default`.
    The elbow threshold is pinned at 12 degrees so these tests do not move with the seed 5 tuning."""
    r = copy.deepcopy(load_rules())
    r["default"].update(min_fraction=0.1, min_frames_floor=8, **default)
    r["measures"]["elbow_flexion"]["threshold_deg"] = 12.0
    return r


def keys(faults):
    return sorted((f.measure, f.side, f.direction) for f in faults)


def test_ac006_three_short_runs_that_add_up_are_one_fault_with_three_runs():
    """AC-006: a 25 degree upper_arm_out held for 15% of the clip in three runs of 5% each, with
    min_fraction 0.12, is one fault with three runs."""
    p = expected("dance")
    n = len(p)
    fol = with_fault(p, "arms_wider", "left", 25, windows=[(0.15, 0.20), (0.40, 0.45), (0.65, 0.70)])
    rules = copy.deepcopy(load_rules())
    rules["default"]["min_fraction"] = 0.12
    rules["default"]["min_frames_floor"] = 8    # the shipped floor (32, attempt 4) is above the 12% of this clip
    faults = run(p, fol, rules)
    assert keys(faults) == [("upper_arm_out", "left", "more")]
    f = faults[0]
    assert len(f.runs) == 3
    assert all(r[1] - r[0] + 1 < 0.12 * n for r in f.runs), "no single run is long enough on its own"
    assert sum(r[1] - r[0] + 1 for r in f.runs) >= 0.12 * n
    longest = max(f.runs, key=lambda r: r[1] - r[0])
    assert f.expected_frames == longest
    assert f.magnitude_deg == pytest.approx(25, abs=3)
    # The shipped min_fraction asks for much more of the clip, so 15% is not a held fault there.
    assert run(p, fol) == []


def test_runs_cover_the_longest_run_for_a_single_run_fault():
    p = expected("dance")
    f = run(p, with_fault(p, "elbow_bent", "left", 30, 0.2, 0.8))[0]
    assert f.runs == (f.expected_frames,)
    assert f.to_dict()["runs"] == [list(f.expected_frames)]


def test_a_fault_built_without_runs_lists_its_longest_run():
    f = Fault(measure="upper_arm_out", side="left", joint="left_shoulder", body_part="arms",
              direction="more", magnitude_deg=20, peak_deg=22, threshold_deg=9,
              expected_frames=(10, 60), follower_frames=(12, 64), phase=(0.1, 0.7),
              coverage=1.0, confidence=0.9)
    assert f.runs == ((10, 60),)


def test_magnitude_is_the_median_over_all_counted_runs():
    faults = detect_synthetic(100, loose_rules(), left_elbow_flexion=[(10, 15, 20), (40, 49, 40), (60, 69, 30)])
    assert keys(faults) == [("elbow_flexion", "left", "more")]
    f = faults[0]
    assert f.runs == ((10, 15), (40, 49), (60, 69))
    assert f.expected_frames == (40, 49) and f.follower_frames == (40, 49)  # the longest run, the first on a tie
    assert f.magnitude_deg == 30.0 and f.peak_deg == 40.0
    assert f.coverage == 1.0


def test_min_run_frames_decides_which_runs_count():
    spans = dict(left_elbow_flexion=[(10, 21, 20), (50, 52, 40)])
    only_long = detect_synthetic(100, loose_rules(min_run_frames=4), **spans)[0]
    assert only_long.runs == ((10, 21),) and only_long.magnitude_deg == 20.0
    both = detect_synthetic(100, loose_rules(min_run_frames=3), **spans)[0]
    assert both.runs == ((10, 21), (50, 52))
    # Runs that are each too short count for nothing, however many there are.
    short = dict(left_elbow_flexion=[(s, s + 2, 20) for s in range(5, 90, 8)])
    assert detect_synthetic(100, loose_rules(min_run_frames=4), **short) == []


def test_ac007_a_one_frame_overlap_does_not_explain_a_fault_away():
    """AC-007: a 6.1 degree foot_out overlapping a 30 degree thigh_out by one frame leaves thigh_out."""
    spans = dict(right_foot_out=[(10, 30, 6.1)], right_thigh_out=[(30, 60, 30.0)])
    faults = detect_synthetic(100, loose_rules(), **spans)
    assert keys(faults) == [("foot_out", "right", "more"), ("thigh_out", "right", "more")]
    # With the old "any shared frame" rule thigh_out is the one that disappears.
    assert keys(detect_synthetic(100, loose_rules(min_overlap=0), **spans)) == [("foot_out", "right", "more")]


def test_a_real_overlap_still_explains_thigh_out_by_foot_out():
    spans = dict(right_foot_out=[(10, 60, 12.0)], right_thigh_out=[(12, 58, 12.0)])
    assert keys(detect_synthetic(100, loose_rules(), **spans)) == [("foot_out", "right", "more")]


def test_ac007_a_dropped_fault_never_explains_another_away():
    """trunk explains foot_out, foot_out would explain thigh_out; the dropped foot_out cannot."""
    rules = loose_rules()
    rules["explained_by"] = {"foot_out": ["trunk_lean_forward"], "thigh_out": ["foot_out"]}
    spans = dict(trunk_lean_forward=[(10, 60, 15.0)], right_foot_out=[(10, 60, 10.0)],
                 right_thigh_out=[(10, 60, 20.0)])
    assert keys(detect_synthetic(100, rules, **spans)) == [
        ("thigh_out", "right", "more"), ("trunk_lean_forward", "center", "more")]


def test_the_opposite_direction_map_lets_a_caving_knee_explain_the_thigh_pulled_in():
    spans = dict(left_knee_valgus=[(10, 60, 15.0)], left_thigh_out=[(10, 60, -15.0)])
    assert keys(detect_synthetic(100, loose_rules(), **spans)) == [("knee_valgus", "left", "more")]
    # A thigh pushed the same way as the knee is not explained by it, nor is the other side's.
    same = dict(left_knee_valgus=[(10, 60, 15.0)], left_thigh_out=[(10, 60, 15.0)])
    assert keys(detect_synthetic(100, loose_rules(), **same)) == [
        ("knee_valgus", "left", "more"), ("thigh_out", "left", "more")]
    other_side = dict(left_knee_valgus=[(10, 60, 15.0)], right_thigh_out=[(10, 60, -15.0)])
    assert keys(detect_synthetic(100, loose_rules(), **other_side)) == [
        ("knee_valgus", "left", "more"), ("thigh_out", "right", "less")]


def test_merge_sides_needs_min_overlap_of_the_shorter_run():
    from part5.detect import _merge_sides

    def fault(side, frames):
        return Fault(measure="knee_flexion", side=side, joint=f"{side}_knee", body_part="legs",
                     direction="less", magnitude_deg=-20.0, peak_deg=-25.0, threshold_deg=10,
                     expected_frames=frames, follower_frames=frames, phase=(0.1, 0.7),
                     coverage=1.0, confidence=0.9)

    right, left = fault("right", (29, 66)), fault("left", (55, 87))  # 12 shared frames of 33
    merged = _merge_sides([left, right], min_overlap=0.3)
    assert [(f.side, f.expected_frames, f.runs) for f in merged] == [("both", (29, 87), ((29, 87),))]
    assert [f.side for f in _merge_sides([left, right], min_overlap=0.5)] == ["left", "right"]
    touching = _merge_sides([fault("left", (10, 60)), fault("right", (60, 110))], min_overlap=0.3)
    assert sorted(f.side for f in touching) == ["left", "right"]


def test_merged_sides_keep_every_counted_run():
    faults = detect_synthetic(100, loose_rules(), left_upper_arm_out=[(10, 30, 20), (50, 70, 20)],
                              right_upper_arm_out=[(12, 28, 20), (55, 72, 20)])
    assert [(f.measure, f.side) for f in faults] == [("upper_arm_out", "both")]
    assert faults[0].runs == ((10, 30), (50, 72))


def test_a_held_fault_is_kept_and_scattered_blips_are_not():
    p = expected("dance")
    assert run(p, with_fault(p, "elbow_bent", "left", 30, 0.2, 0.8))[0].measure == "elbow_flexion"
    assert run(p, with_fault(p, "elbow_bent", "left", 30, windows=[(0.2, 0.25), (0.5, 0.55)])) == []


def with_knee_valgus(positions, side, target_deg, start=0.1, end=0.9):
    """Move the `side` knee toward the midline (away from it for a negative target) over
    [start, end] of the clip until the hip to ankle line offset reads `target_deg`, noise-free.

    The thigh keeps its length; the measure is re-derived here from its definition (offset of the
    knee from the hip to ankle line, toward the midline, over the thigh length) and bisected."""
    pos, n = positions.copy(), len(positions)
    toward = np.array([-1.0, 0, 0]) if side == "left" else np.array([1.0, 0, 0])
    sign = 1 if target_deg >= 0 else -1
    j = {name: i for i, name in enumerate(JOINTS)}
    for i in range(n):
        if not start * n <= i <= end * n:
            continue
        h, k, a = (pos[i, j[f"{side}_{x}"]] for x in ("hip", "knee", "ankle"))
        thigh, length = k - h, np.linalg.norm(k - h)
        u = (a - h) / np.linalg.norm(a - h)

        def reading(s):
            t = thigh + s * sign * toward
            t = t / np.linalg.norm(t) * length
            return np.degrees(np.arctan2((t - t @ u * u) @ toward, length)), h + t

        lo, hi = 0.0, 2 * length
        for _ in range(60):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if sign * reading(mid)[0] < abs(target_deg) else (lo, mid)
        pos[i, j[f"{side}_knee"]] = reading(hi)[1]
    return pos


@pytest.mark.parametrize("name", ["exercise", "dance"])
@pytest.mark.parametrize("side", ["left", "right"])
def test_ac003_knee_caving_is_found_on_the_labelled_side_and_nothing_else(name, side):
    """AC-003 on noise-free takes: 15 to 25 degrees of knee_valgus is one `knee_valgus` fault,
    direction more, on that side; the thigh and the knee bend it drags along are not reported."""
    p = expected(name)
    for amount in (15, 20, 25):
        faults = run(p, with_knee_valgus(p, side, amount))
        assert keys(faults) == [("knee_valgus", side, "more")], (amount, keys(faults))
        assert faults[0].magnitude_deg == pytest.approx(amount, abs=1.5)
        assert faults[0].joint == f"{side}_knee" and faults[0].body_part == "legs"


def test_a_knee_pushed_out_is_knee_valgus_less_and_explains_the_thigh_out():
    p = expected("exercise")
    faults = run(p, with_knee_valgus(p, "left", -15))
    assert keys(faults) == [("knee_valgus", "left", "less")]
    assert faults[0].magnitude_deg == pytest.approx(-15, abs=1.5)


def test_both_knees_caving_merge_to_both():
    p = expected("exercise")
    faults = run(p, with_knee_valgus(with_knee_valgus(p, "left", 20), "right", 20))
    assert keys(faults) == [("knee_valgus", "both", "more")]
    assert faults[0].joint == "knee"


def test_ac003_seed_5_knee_caving_takes_in_good_light_report_knee_valgus_on_the_labelled_side():
    """AC-003: every seed 5 knee_caving take in good light reports knee_valgus, direction more, on the
    labelled side."""
    from part5.pipeline import analyse
    root = Path(__file__).resolve().parent.parent
    labels = json.loads((root / "fixtures/input/followers/labels.json").read_text())
    takes = [t for t in labels["takes"] if t["lighting"] == "good"
             and any(f["type"] == "knee_caving" for f in t["faults"])]
    assert takes
    for t in takes:
        side = next(f["side"] for f in t["faults"] if f["type"] == "knee_caving")
        faults = analyse(str(root / t["expected"]), str(root / t["follower"]))["faults"]
        assert any(f["measure"] == "knee_valgus" and f["direction"] == "more" and f["side"] in (side, "both")
                   for f in faults), (t["take_id"], [(f["measure"], f["side"], f["direction"]) for f in faults])
