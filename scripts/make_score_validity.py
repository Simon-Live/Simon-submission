"""Scoring validity, GPU free and at the skeleton level (docs/specs/scoring-validity.md, TICKET-082).

The library behind `scripts/make_bench_score.py` (`make bench-score`) and `tests/test_score_validity.py`,
`tests/test_score_properties.py`. It plants joint-angle errors in a clean seed 5 take, transforms a clip in ways that
should not change its verdict, and reads the outcome of Part 5's own pipeline (`part5.pipeline.run` with
`part5.score_report.score_block`) as plain data. It changes no rule and no score param.

    plant(doc, "knee", 10.0)          the follower doc with a 10 degree knee error in every frame
    analyse(expected_doc, follower)   the validated analysis (a score block included)
    outcome(analysis)                 {value, grade, faults, warnings}: the numbers the tables are made of
    TRANSFORMS                        the invariance rows: name -> Transform

A clip is a `simon.animation.v1` dict. Transforms return a new dict and never edit their argument.

ADR-0019: the score read is the shipped `simon.score.v3`, frozen; ASM-001: the input is in the subject's frame with the hip
midpoint at the origin (a translation or a yaw is outside the contract); ASM-002: the seed 5 takes are synthetic stand-ins.
"""
import copy
import json
import math
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
for _dir in (ROOT, ROOT / "scripts", ROOT / "tests"):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))

import make_dummy_followers as gen  # noqa: E402  (the geometry of the planted faults, reused and never copied)
import retimed  # noqa: E402  (tests/retimed.py: the seed 5 take picker and the frame-rate resampler)
from part5.io import JOINTS, InputError  # noqa: E402
from part5.measures import compute  # noqa: E402
from part5.pipeline import AnalysisError, run  # noqa: E402
from part5.score_report import score_block  # noqa: E402
from part5.visibility import MIRROR  # noqa: E402

SEED = 5   # ASM-002: the tuning set; no held-out file is ever read
GRID = [2.5 * i for i in range(13)]   # planted degrees, 0 to 30
SETS = ("exercise", "dance")
SIDES = {"left": "right", "right": "left", "both": "both", "center": "center"}
ODD_MEASURES = ("trunk_lean_side", "shoulder_tilt")   # change sign under a mirror: they are signed toward the subject's left


# ---------------------------------------------------------------- a clip as arrays
def positions_of(doc):
    """`(t, P)` of a clip dict: seconds `(F,)` and positions `(F, 17, 3)` with NaN where a joint is null or left out."""
    frames = doc["frames"]
    t = np.array([f["t"] for f in frames], float)
    P = np.full((len(frames), len(JOINTS), 3), np.nan)
    for i, fr in enumerate(frames):
        for k, name in enumerate(JOINTS):
            p = fr["joints"].get(name)
            if p is not None:
                P[i, k] = p
    return t, P


def with_positions(doc, t, P):
    """A copy of `doc` with the frames rebuilt from `t` and `P` (NaN joints written as null), indexes renumbered."""
    out = {k: copy.deepcopy(v) for k, v in doc.items() if k != "frames"}
    out["frames"] = [{"index": i, "t": float(t[i]), "interpolated": False,
                      "joints": {name: (None if np.isnan(P[i, k]).any() else [float(c) for c in P[i, k]])
                                 for k, name in enumerate(JOINTS)}} for i in range(len(t))]
    out["frame_count"] = len(t)
    out["duration_s"] = float(t[-1] - t[0])
    return out


def load_doc(path):
    return json.loads(Path(path).read_text())


# ---------------------------------------------------------------- planting (scripts/make_dummy_followers.py geometry)
def _frames(P):
    return [{name: [float(c) for c in P[i, k]] for k, name in enumerate(JOINTS)} for i in range(len(P))]


def _array(frames):
    return np.array([[f[name] for name in JOINTS] for f in frames], float)


def _plant_knee(frames, deg):
    """Bend the left knee `deg` degrees more: the left ankle turns about the left knee, about the axis of the deepest
    frame (thigh by shin), which is the squat's plane normal and so defined in every frame, a straight leg included."""
    hip, knee, ank = "left_hip", "left_knee", "left_ankle"
    depth = [180 - gen.angle_at(f[hip], f[knee], f[ank]) for f in frames]
    deepest = frames[max(range(len(frames)), key=depth.__getitem__)]
    axis = gen.unit(gen.cross(gen.sub(deepest[knee], deepest[hip]), gen.sub(deepest[ank], deepest[knee])))
    for f in frames:
        f[ank] = gen.rotate(f[ank], f[knee], axis, deg)


def _plant_hip(frames, deg):
    gen.fault_foot_out(frames, "left", deg, [1.0] * len(frames))   # the left leg swings away from the midline


def _plant_elbow(frames, deg):
    gen.fault_elbow_bent(frames, "left", deg, [1.0] * len(frames))   # the left forearm flexes forward


def _plant_trunk(frames, deg):
    gen.fault_trunk_lean(frames, "center", deg, [1.0] * len(frames))   # the head, shoulders and arms tip forward


@dataclass(frozen=True)
class Joint:
    """A joint errors are planted on: how, the side and the measures a matching fault has, and the measure the planted
    change is read in (`realised`)."""
    plant: Callable
    side: str
    measures: tuple
    realised: str


PLANTED = {
    "knee": Joint(_plant_knee, "left", ("knee_flexion",), "left_knee_flexion"),
    "hip": Joint(_plant_hip, "left", ("foot_out", "thigh_out"), "left_thigh_out"),
    "elbow": Joint(_plant_elbow, "left", ("elbow_flexion",), "left_elbow_flexion"),
    "trunk": Joint(_plant_trunk, "center", ("trunk_lean_forward",), "trunk_lean_forward"),
}


def plant(doc, joint, deg):
    """`doc` with a `deg` degree error planted on `joint` in every frame. 0 degrees returns an equal copy."""
    t, P = positions_of(doc)
    frames = _frames(P)
    if deg:
        PLANTED[joint].plant(frames, deg)
    return with_positions(doc, t, _array(frames))


def realised_deg(before, after, joint):
    """The median over frames of the absolute change in the joint's own measure between two clips (degrees)."""
    name = PLANTED[joint].realised
    change = np.abs(compute(positions_of(after)[1])[name] - compute(positions_of(before)[1])[name])
    return float(np.nanmedian(change))


# ---------------------------------------------------------------- the pipeline as data
def analyse(expected, follower, follower_id="follower"):
    """The analysis of `follower` (a clip dict) against `expected` (a clip dict or a path), score included."""
    exp = {"path": str(expected)} if isinstance(expected, (str, Path)) else {"path": "expected", "doc": expected}
    return run(exp, {"path": follower_id, "doc": follower}, None, score=score_block).analysis


def outcome(analysis):
    """The numbers a table row holds: score value and grade, the fault list as `(measure, side, direction, magnitude)`
    and the warning codes."""
    score = analysis["score"]
    faults = [(f["measure"], f["side"], f["direction"], f["magnitude_deg"]) for f in analysis["faults"]]
    return {"value": score["value"], "grade": score["grade"], "faults": faults,
            "warnings": [w["code"] for w in analysis.get("warnings", [])]}


def fault_set(out):
    """`{(measure, side, direction)}` of an outcome."""
    return {(m, s, d) for m, s, d, _ in out["faults"]}


def mirrored_set(faults):
    """The fault set of the mirror image: sides swapped, and the direction turned for the two lateral measures."""
    flip = {"more": "less", "less": "more"}
    return {(m, SIDES[s], flip[d] if m in ODD_MEASURES else d) for m, s, d in faults}


# ---------------------------------------------------------------- the pool
def pool():
    """The seed 5 takes the bench uses: good light, clean, numbers 00 to 08, of the exercise and dance sets (54). The
    helper refuses any other seed."""
    return retimed.picked_takes(sets=SETS)


def correct_exercise(takes):
    """The dose-response takes: the correct takes of the exercise set (numbers 00 and 01 of the three angles: 6)."""
    return [t for t in takes if t["set"] == "exercise" and t["correct"]]


# ---------------------------------------------------------------- dose-response
def match_of(analysis, joint):
    """The matching fault of `joint` in an analysis as `{measure, side, direction, magnitude_deg}`, or None."""
    spec = PLANTED[joint]
    for f in analysis["faults"]:
        if f["measure"] in spec.measures and f["direction"] == "more" and f["side"] in (spec.side, "both"):
            return {k: f[k] for k in ("measure", "side", "direction", "magnitude_deg")}
    return None


def dose_row(take, base_doc, expected_doc, joint, deg):
    planted = plant(base_doc, joint, deg)
    analysis = analyse(expected_doc, planted, take["take_id"])
    match = match_of(analysis, joint)
    extra = [[f["measure"], f["side"], f["direction"], f["magnitude_deg"]] for f in analysis["faults"]
             if match is None or [f["measure"], f["side"], f["direction"]] != [match["measure"], match["side"], match["direction"]]]
    return {"joint": joint, "take_id": take["take_id"], "angle": take["angle"], "planted_deg": deg,
            "realised_deg": round(realised_deg(base_doc, planted, joint), 2), "value": analysis["score"]["value"],
            "grade": analysis["score"]["grade"], "n_faults": len(analysis["faults"]), "matching": match,
            "extra_faults": extra}


def dose_rows(takes, grid=GRID, joints=tuple(PLANTED)):
    """One row per joint, take and step. The expected clip of a take is read once. A step the pipeline refuses is a row
    with an `error` and nothing else to read: the run goes on and the caller reports it."""
    rows, expected = [], {}
    for take in takes:
        exp = expected.setdefault(take["expected"], load_doc(ROOT / take["expected"]))
        base = load_doc(ROOT / take["follower"])
        for joint in joints:
            for deg in grid:
                try:
                    rows.append(dose_row(take, base, exp, joint, deg))
                except (InputError, AnalysisError) as e:
                    rows.append({"joint": joint, "take_id": take["take_id"], "planted_deg": deg, "error": str(e)})
    return rows


def measured(rows):
    """The rows that have a score: those that did not end in an `error`."""
    return [r for r in rows if "error" not in r]


def first_fire(rows):
    """`{joint: {take_id: {"first": deg or None, "stable": bool}}}`: the smallest planted angle that reports the matching
    fault, and whether it is reported at every larger step."""
    out = {}
    for r in measured(rows):
        out.setdefault(r["joint"], {}).setdefault(r["take_id"], []).append(r)
    result = {}
    for joint, takes in out.items():
        result[joint] = {}
        for take_id, series in takes.items():
            series = sorted(series, key=lambda r: r["planted_deg"])
            fires = [r["planted_deg"] for r in series if r["matching"]]
            first = fires[0] if fires else None
            stable = bool(fires) and all(r["matching"] for r in series if r["planted_deg"] >= first)
            result[joint][take_id] = {"first": first, "stable": stable}
    return result


def fire_summary(fires):
    """Per joint: the lower median (a grid angle, `median_low`), minimum and maximum first fire over its takes (a take that never fires counts as above the
    grid, so a median or a maximum can be None), how many never fire and how many are stable."""
    out = {}
    for joint, takes in fires.items():
        firsts = sorted(t["first"] if t["first"] is not None else math.inf for t in takes.values())
        finite = lambda v: None if math.isinf(v) else v   # noqa: E731  (JSON has no infinity)
        out[joint] = {"median_low": finite(statistics.median_low(firsts)), "min": finite(firsts[0]), "max": finite(firsts[-1]),
                      "takes": len(firsts), "never": sum(math.isinf(v) for v in firsts),
                      "stable": sum(t["stable"] for t in takes.values())}
    return out


def mean_curves(rows):
    """`{joint: [(planted_deg, mean value over takes, min, max)]}` in growing angle."""
    grouped = {}
    for r in measured(rows):
        grouped.setdefault((r["joint"], r["planted_deg"]), []).append(r["value"])
    joints = sorted({j for j, _ in grouped}, key=list(PLANTED).index)
    return {j: [(d, sum(v) / len(v), min(v), max(v)) for (jj, d), v in sorted(grouped.items()) if jj == j]
            for j in joints}


def rises(series):
    """The steps where a score series `[(deg, value)]` goes up: `[(deg0, value0, deg1, value1)]`."""
    return [(d0, v0, d1, v1) for (d0, v0), (d1, v1) in zip(series, series[1:]) if v1 > v0]


# ---------------------------------------------------------------- transforms of a clip
def mirror_doc(doc):
    """The mirror image: x negated, the left and right joints swapped (a left-right swap of the names)."""
    t, P = positions_of(doc)
    flipped = P * np.array([-1.0, 1.0, 1.0])
    out = flipped.copy()
    for k, other in enumerate(MIRROR):
        if other is not None:
            out[:, k] = flipped[:, other]
    return with_positions(doc, t, out)


def yaw_doc(doc, deg):
    """The clip turned `deg` degrees about the vertical axis through the origin (the hip midpoint)."""
    t, P = positions_of(doc)
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    out = P.copy()
    out[..., 0] = c * P[..., 0] + s * P[..., 2]
    out[..., 2] = -s * P[..., 0] + c * P[..., 2]
    return with_positions(doc, t, out)


def scale_doc(doc, factor):
    t, P = positions_of(doc)
    return with_positions(doc, t, P * factor)


def translate_doc(doc, vector):
    t, P = positions_of(doc)
    return with_positions(doc, t, P + np.asarray(vector, float))


def drop_frames(doc, n):
    """The clip without its first `n` frames, times rebased to 0."""
    t, P = positions_of(doc)
    return with_positions(doc, t[n:] - t[n], P[n:])


def trim_doc(doc, seconds):
    """The clip without its first `seconds`, times rebased to 0."""
    t, _ = positions_of(doc)
    return drop_frames(doc, int(np.sum(t < t[0] + seconds - 1e-9)))


def null_frames(doc, indexes):
    """The clip with every joint of the frames at `indexes` left out (null): the estimator lost them."""
    t, P = positions_of(doc)
    P = P.copy()
    P[list(indexes)] = np.nan
    return with_positions(doc, t, P)


def noisy_doc(doc, sigma, seed):
    """The clip with Gaussian noise of `sigma` metres on every coordinate, then the hip midpoint put back at the origin."""
    t, P = positions_of(doc)
    P = P + np.random.default_rng(seed).normal(0.0, sigma, P.shape)
    mid = (P[:, JOINTS.index("left_hip")] + P[:, JOINTS.index("right_hip")]) / 2
    return with_positions(doc, t, P - mid[:, None, :])


def resample_doc(take, fps, tmp):
    """The take's follower at `fps` frames per second, through `tests/retimed.py` (a temporary file under `tmp`)."""
    dst = Path(tmp) / f"{take['take_id']}_{fps}fps.json"
    retimed.retime(ROOT / take["follower"], dst, 1.0, fps)
    return load_doc(dst)


# ---------------------------------------------------------------- the invariance rows
@dataclass(frozen=True)
class Transform:
    """One invariance row. `apply(take, expected_doc, follower_doc, tmp)` returns the `(expected, follower)` to analyse.
    `claim` is "exact" (a spread of 0 and equal fault sets), "refused" (an `InputError`) or "reported" (no claim);
    `mirrors` says the fault sets are compared after the side swap; `text` is the row's definition for the tables."""
    name: str
    text: str
    claim: str
    apply: Callable
    mirrors: bool = False
    applies: Callable = lambda take: True   # does the row make sense for this take? (a trim of 0 frames does not)


def _follower_only(fn):
    return lambda take, exp, fol, tmp: (exp, fn(fol))


TRANSFORMS = {t.name: t for t in (
    Transform("fps_60", "follower resampled to 60 frames per second", "exact",
              lambda take, exp, fol, tmp: (exp, resample_doc(take, 60, tmp))),
    Transform("fps_24", "follower resampled to 24 frames per second (a non-integer ratio, an extra row)", "reported",
              lambda take, exp, fol, tmp: (exp, resample_doc(take, 24, tmp))),
    Transform("mirror_follower", "follower mirrored, sides swapped", "exact", _follower_only(mirror_doc), mirrors=True),
    Transform("mirror_both", "example and follower mirrored, sides swapped", "exact",
              lambda take, exp, fol, tmp: (mirror_doc(exp), mirror_doc(fol)), mirrors=True),
    Transform("trim_0.5s", "first 0.5 s of the follower removed", "exact", _follower_only(lambda d: trim_doc(d, 0.5))),
    Transform("trim_lead_in", "only the take's own idle lead-in removed (1 to 15 frames; takes with none are skipped; an extra row)", "exact",
              lambda take, exp, fol, tmp: (exp, drop_frames(fol, take["lead_in_frames"])),
              applies=lambda take: take["lead_in_frames"] > 0),
    Transform("translate_5mm", "follower moved 5 mm on every axis (inside the 1 cm the loader recentres)", "exact",
              _follower_only(lambda d: translate_doc(d, [0.005] * 3))),
    Transform("translate_0.5m", "follower moved 0.5 m on x (outside the contract: refused)", "refused",
              _follower_only(lambda d: translate_doc(d, [0.5, 0.0, 0.0]))),
    Transform("yaw_5", "follower turned 5 degrees about the vertical axis", "exact", _follower_only(lambda d: yaw_doc(d, 5))),
    Transform("yaw_15", "follower turned 15 degrees about the vertical axis", "exact", _follower_only(lambda d: yaw_doc(d, 15))),
    Transform("yaw_45", "follower turned 45 degrees about the vertical axis", "exact", _follower_only(lambda d: yaw_doc(d, 45))),
    Transform("yaw_45_both", "example and follower turned 45 degrees about the vertical axis", "exact",
              lambda take, exp, fol, tmp: (yaw_doc(exp, 45), yaw_doc(fol, 45))),
    Transform("scale_0.8", "follower scaled to 0.8 times", "exact", _follower_only(lambda d: scale_doc(d, 0.8))),
    Transform("scale_1.25", "follower scaled to 1.25 times", "exact", _follower_only(lambda d: scale_doc(d, 1.25))),
)}


TRIM_FRAMES = 15   # 0.5 s at the 30 frames per second of the seed 5 takes


def group_of(transform, take, symmetric):
    """The group of a row whose claim holds for part of the takes only: a trim of 0.5 s removes just idle frames when the
    take's lead-in is at least that long, and a mirrored follower matches a left-right symmetric example only."""
    if transform.name == "trim_0.5s":
        return "lead-in at least 15 frames" if take["lead_in_frames"] >= TRIM_FRAMES else "lead-in under 15 frames"
    if transform.name == "mirror_follower":
        return "symmetric example" if symmetric else "asymmetric example"
    return "all takes"


NO_CLAIM = {("mirror_follower", "asymmetric example"), ("trim_0.5s", "lead-in under 15 frames")}   # groups with no claim


def claimed(name, group):
    """The claim that applies to a row group: the transform's, except for the groups that have none."""
    return "reported" if (name, group) in NO_CLAIM else TRANSFORMS[name].claim


def is_symmetric(exp_doc):
    """Does the example score 100 and report no fault against its own mirror image?"""
    out = outcome(analyse(exp_doc, mirror_doc(exp_doc), "mirror_of_example"))
    return out["value"] == 100 and not out["faults"]


def invariance_row(transform, take, exp_doc, fol_doc, base, tmp, symmetric=True):
    """One row: the untransformed outcome `base` and the transformed one, or `refused` with the loader's error."""
    row = {"transform": transform.name, "group": group_of(transform, take, symmetric), "take_id": take["take_id"],
           "set": take["set"], "angle": take["angle"], "correct": take["correct"],
           "lead_in_frames": take["lead_in_frames"], "base": base, "variant": None, "refused": None, "delta": None,
           "fault_set_equal": None}
    try:
        exp, fol = transform.apply(take, exp_doc, fol_doc, tmp)
        variant = outcome(analyse(exp, fol, take["take_id"]))
    except InputError as e:   # the loader's own refusal is a result (a contract fact), not a failure of the run
        row["refused"] = str(e)
        return row
    except AnalysisError as e:
        row["error"] = str(e)
        return row
    expected_set = mirrored_set(fault_set(base)) if transform.mirrors else fault_set(base)
    row.update(variant=variant, delta=variant["value"] - base["value"], fault_set_equal=fault_set(variant) == expected_set)
    return row


def invariance_rows(takes, names=None, tmp="."):
    """Every transform of `names` (default all) on every take; the untransformed outcome is analysed once per take and
    the symmetry of each example once."""
    rows, docs, symmetric = [], {}, {}
    for take in takes:
        exp = docs.setdefault(take["expected"], load_doc(ROOT / take["expected"]))
        sym = symmetric.setdefault(take["expected"], is_symmetric(exp))
        fol = load_doc(ROOT / take["follower"])
        base = outcome(analyse(exp, fol, take["take_id"]))
        rows += [invariance_row(TRANSFORMS[n], take, exp, fol, base, tmp, sym) for n in (names or TRANSFORMS)
                 if TRANSFORMS[n].applies(take)]
    return rows


def summarise(rows):
    """One entry per transform and group, in row order: takes, refused, largest absolute change, mean absolute change,
    signed range, takes whose value changed, takes whose fault set changed, and the verdict in words: refused, exact,
    fault set changed or score moved."""
    out = []
    for name, group in dict.fromkeys((r["transform"], r["group"]) for r in rows):
        mine = [r for r in rows if (r["transform"], r["group"]) == (name, group)]
        ran = [r for r in mine if r["refused"] is None and "error" not in r]
        deltas = [r["delta"] for r in ran]
        changed_sets = sum(not r["fault_set_equal"] for r in ran)
        refused = sum(r["refused"] is not None for r in mine)
        verdict = ("refused" if refused == len(mine) else "fault set changed" if changed_sets
                   else "exact" if not any(deltas) else "score moved")
        out.append({"transform": name, "group": group, "takes": len(mine), "refused": refused,
                    "errors": sum("error" in r for r in mine),
                    "max_abs_delta": max((abs(d) for d in deltas), default=None),
                    "mean_abs_delta": round(sum(abs(d) for d in deltas) / len(deltas), 3) if deltas else None,
                    "min_delta": min(deltas, default=None), "max_delta": max(deltas, default=None),
                    "value_changed": sum(d != 0 for d in deltas), "fault_set_changed": changed_sets, "verdict": verdict})
    return out
