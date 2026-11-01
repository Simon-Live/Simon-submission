"""The take's score out of 100 with a grade A to F. Part 5 ships `simon.score.v1` (ADR-0007, docs/specs/journey-followup.md
J-4): `simon.score.v2` (ADR-0018, docs/specs/score-v2.md) failed held-out score seed 59 (docs/thresholds.md), so the
`score` block of part5/rules.json is its frozen v1 block (`make score-fallback`). This module still reads both versions
and scores by the one the rules' block names.

    compute(analysis, aligned, rules=None) -> {version, value, grade, components: {faults, similarity},
                                               params_sha256}   or None when the take was refused

`analysis` is the validated `simon.analysis.v1` document (`status.code`, `faults[]` with `magnitude_deg`,
`threshold_deg`, `runs`, `coverage`). `aligned` is the one extra input the similarity term needs, a mapping:

    {"expected":   {measure name: array over the expected clip's frames},    # measures.compute(exp positions)
     "follower":   {measure name: array over the resampled follower frames}, # measures.compute(fol_positions)
     "exp_to_fol": sequence, one follower frame index per expected frame}    # Alignment.exp_to_fol

In `part5.pipeline.run` these are `exp_m`, `fol_m` and `alignment.exp_to_fol`, so the call is
`score.compute(analysis, {"expected": exp_m, "follower": fol_m, "exp_to_fol": alignment.exp_to_fol})`.
The expected clip's frame count N is `len(exp_to_fol)`.

Formula (params under `score` in part5/rules.json): per fault `r = |magnitude_deg| / threshold_deg`,
`penalty = min(cap, base + slope * (r - 1))`, `dur` the share of N the fault's runs cover, `F = sum of
penalty * (0.5 + 0.5 * dur) * coverage`; `z = |follower - expected| / threshold` per measure and frame
(clipped to [0, 2]), `S = s_max * clip((mean_z - z0) / (z1 - z0), 0, 1)`; `value = clamp(round_half_up(100 - F - S))`.

Version 2 (ADR-0018; kept in the code, not shipped) changes two things when the rules' block is a v2 one: each miss is
also multiplied by the weight `w = min(1, max(range_floor, u / range_full))`, `u` the trainer's range (max minus min, in
detection thresholds) of the missed measure on the window's expected frames (1 only where that series is not in
`aligned["expected"]`: no feet file, or a foot measure that was not compared; the trainer's foot series sit there beside
the body measures, and the similarity term reads the body measures only), and a take whose `analysis["faults"]` is not
empty is capped at `fault_cap` (89), with `fault_cap` in the block and `uncapped` holding the value before every cap.
A v2 block holds the v1 params as `v1` (`rules_v1`).

Under the dance profile (ADR-0016) each window is also charged a tempo term T, `profiles.tempo_points` of the window's
tempo ratio, taken off the value (`100 - F - S - T`) and shown as `components.tempo`. It is a run-time term of the
profile, not a score param: `params_sha256` and the frozen `score` block are the same in every profile. Thresholds in
`rules` are the profile's own, so a score is only comparable within one profile.
"""
import hashlib
import json
import math
from decimal import ROUND_HALF_UP, Decimal

import numpy as np

from . import profiles
from .cues import tempo_block
from .detect import load_rules
from .measures import MEASURES

VERSION_V1 = "simon.score.v1"
VERSION = "simon.score.v2"
VERSIONS = (VERSION_V1, VERSION)
SIDES = ("left", "right")
MIN_COVER = 0.5      # the penalty weight of a fault with no duration: 0.5 + 0.5 * dur
CLIP_Z = 2.0         # a measure frame is never worse than twice its threshold
S_MAX = 4.0          # similarity costs at most this many points (calibration rule)
SINGLE_FLOOR = 10.5  # the smallest counted fault must cost more than 10 points (never an A)
WORST_SINGLE = 30.0  # the worst single good-light fault still lands at 70 or above (a C)
BANDS = [[90, "A"], [80, "B"], [70, "C"], [60, "D"], [0, "F"]]
WARNING_CAP = 59     # a take with any warning never scores above this, so its grade is F (ADR-0012)
# ADR-0018, the v2 design constants (not fitted); `range_floor` is the one fitted number (`choose_floor`).
RANGE_FULL = 3.0     # a measure the trainer moves this many of its own thresholds in a window costs in full
FAULT_CAP = 89       # a take that reports a fault scores at most this (the top of B); ruled, not fitted
FLOOR_GRID = [round(0.5 + 0.05 * i, 2) for i in range(11)]   # 0.50 to 1.00
SINGLE_MIN = 70      # a take that reports exactly its one labelled fault scores at least this (ADR-0007 worst single)
DOUBLE_MAX = 75      # a take that reports exactly its two labelled faults scores at most this (5 under 80, the first B)
SHARED_V1 = ("z0", "z1", "s_max", "base", "slope", "cap", "bands")   # v2 repeats these from v1, equal


def ships_v2(rules=None):
    """Do the rules ship `simon.score.v2`? (After `make score-fallback`, ADR-0018, they ship v1.) The one place that asks."""
    return params_of(rules or load_rules())["version"] == VERSION


def params_of(rules):
    """The `score` block of the rules (v1 or v2), or a ValueError naming what is missing."""
    block = (rules or {}).get("score")
    if not isinstance(block, dict) or block.get("version") not in VERSIONS:
        raise ValueError(f"part5/rules.json has no {VERSION_V1} or {VERSION} 'score' block")
    return block


def rules_v1(rules):
    """`rules` scored by the frozen v1 params: the `score` section replaced by its `v1` block (ADR-0018, reversal)."""
    v1 = ((rules or {}).get("score") or {}).get("v1")
    if not isinstance(v1, dict) or v1.get("version") != VERSION_V1:
        raise ValueError(f"part5/rules.json 'score' block has no {VERSION_V1} 'v1' block")
    return {**rules, "score": v1}


def params_sha256(block):
    return hashlib.sha256(json.dumps(block, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def grade(value, bands=BANDS):
    return next(g for lo, g in bands if value >= lo)


def round_half_up(x, places=0):
    """Decimal-safe half-up rounding: 82.5 -> 83, 2.675 -> 2.68."""
    q = Decimal(1).scaleb(-places)
    return Decimal(repr(round(float(x), 9))).quantize(q, rounding=ROUND_HALF_UP)


def threshold_of(measure, rules):
    """The detection threshold of a measure (`left_foot_out` uses `foot_out`), else the default's."""
    base = measure.removeprefix("left_").removeprefix("right_")
    return float(rules["measures"].get(base, rules["default"])["threshold_deg"])


def trainer_range(fault, expected, rules):
    """How far the trainer moves the fault's measure over `expected` (measure name -> array over the window's expected
    frames), in that measure's detection thresholds (ADR-0018); None when no series of it is there with a finite value.
    The series is `{side}_{measure}`, the larger range of the two sides for `both`, the bare name for `center`."""
    side, measure = fault.get("side"), fault.get("measure")
    if not measure:
        return None   # a fault that names no measure has no series to read: it weighs one
    names = [f"{side}_{measure}"] if side in SIDES else [f"{s}_{measure}" for s in SIDES] if side == "both" else [measure]
    spans = []
    for name in names:
        series = expected.get(name)
        if series is None:
            continue
        v = np.asarray(series, dtype=float)
        v = v[np.isfinite(v)]
        if v.size:
            spans.append((float(v.max()) - float(v.min())) / threshold_of(name, rules))
    return max(spans) if spans else None


def weight(u, p):
    """The v2 weight of a miss whose trainer moves its measure `u` thresholds in the window (None: unknown): 1 for a
    v1 block, 1 where `u` is unknown, else `min(1, max(range_floor, u / range_full))`."""
    if "range_floor" not in p or u is None:
        return 1.0
    return min(1.0, max(p["range_floor"], u / p["range_full"]))


def fault_features(fault, n_frames, expected=None, rules=None):
    """(r, dur, coverage) of one fault of the analysis; with `expected` (measure -> array over the window's expected
    frames) and the rules, also `u`, the trainer's range of its measure in thresholds (None when unknown)."""
    runs = fault.get("runs") or [fault["expected_frames"]]
    dur = sum(e - s + 1 for s, e in runs) / n_frames
    out = {"r": abs(fault["magnitude_deg"]) / fault["threshold_deg"], "dur": min(1.0, dur), "cov": fault["coverage"]}
    if expected is not None:
        out["u"] = trainer_range(fault, expected, rules)
    return out


def mean_z(aligned, rules):
    """Mean clipped |follower - expected| / threshold over every measure and expected frame; None when nothing is measurable."""
    idx = np.asarray(aligned["exp_to_fol"])
    errs = []
    for name in MEASURES:
        d = np.asarray(aligned["follower"][name])[idx] - np.asarray(aligned["expected"][name])
        errs.append(np.abs(d) / threshold_of(name, rules))
    e = np.vstack(errs)
    ok = np.isfinite(e)
    return float(np.mean(np.minimum(e[ok], CLIP_Z))) if ok.any() else None


def features(analysis, aligned, rules):
    """What the score is computed from: {"faults": [{r, dur, cov}], "mean_z": float}, or None when nothing is measurable."""
    if (analysis.get("status") or {}).get("code") not in ("ok", None):
        return None   # a document written before ADR-0012 that was refused
    z = mean_z(aligned, rules)
    if z is None:
        return None
    n = len(aligned["exp_to_fol"])
    return {"faults": [fault_features(f, n, aligned["expected"], rules) for f in analysis.get("faults", [])],
            "mean_z": z}


def penalty(r, p):
    return min(p["cap"], p["base"] + p["slope"] * (r - 1))


def miss_cost(x, p):
    """Points one fault costs: its penalty, by duration and coverage, and (v2) by the trainer's range of its measure."""
    return penalty(x["r"], p) * (MIN_COVER + 0.5 * x["dur"]) * x["cov"] * weight(x.get("u"), p)


def components(feats, p):
    """(F, S) unrounded."""
    f = sum(miss_cost(x, p) for x in feats["faults"])
    s = p["s_max"] * min(1.0, max(0.0, (feats["mean_z"] - p["z0"]) / (p["z1"] - p["z0"])))
    return f, s


def zero_block(rules=None):
    """The score of a take nothing could be measured on: 0, grade F (ADR-0012)."""
    p = params_of(rules or load_rules())
    return {"version": p["version"], "value": 0, "grade": grade(0, p["bands"]),
            "components": {"faults": 0.0, "similarity": 0.0}, "params_sha256": params_sha256(p)}


def apply_fault_cap(block, reports_fault, rules=None):
    """v2 (ADR-0018): a take that reports a fault scores at most `fault_cap`. `block` gains `fault_cap` (an integer, in
    force whether or not it lowered the value) and, when it lowered the value, `uncapped`, the value and grade before.
    Not `capped_by`: that names the warning codes of the low-match cap and nothing else. A v1 block, or a take that
    reports no fault, is returned as it is."""
    p = params_of(rules or load_rules())
    cap = p.get("fault_cap")
    if cap is None or not reports_fault:
        return block
    out = dict(block, fault_cap=int(cap))
    if block["value"] > cap:
        out.update(value=int(cap), grade=grade(int(cap), p["bands"]),
                   uncapped={"value": block["value"], "grade": block["grade"]})
    return out


def cap_by_warnings(block, analysis, rules=None):
    """`block` capped at WARNING_CAP when the analysis carries warnings (ADR-0012), with `capped_by` naming them.
    A take without warnings, or already at or under the cap, keeps its value; `capped_by` is recorded either way.
    When the cap lowers the value, `uncapped` keeps what it was, so a reader can say what the warning cost. From v2
    `uncapped` is the value before every cap: a block the fault cap already lowered keeps the `uncapped` it has."""
    codes = [w["code"] for w in analysis.get("warnings") or []]
    if not codes:
        return block
    p = params_of(rules or load_rules())
    value = min(block["value"], WARNING_CAP)
    out = dict(block, value=value, grade=grade(value, p["bands"]), capped_by=codes)
    if value < block["value"] and "uncapped" not in block:
        out["uncapped"] = {"value": block["value"], "grade": block["grade"]}
    return out


def compute(analysis, aligned, rules=None):
    """The `score` block of the analysis, or `zero_block` when nothing is measurable (never null, ADR-0012)."""
    rules = rules or load_rules()
    p = params_of(rules)
    feats = features(analysis, aligned, rules)
    if feats is None:   # a take with faults still says its ceiling (fault_cap), though its value is 0
        return apply_fault_cap(zero_block(rules), bool(analysis.get("faults")), rules)
    f, s = components(feats, p)
    value = max(0, min(100, int(round_half_up(100 - f - s))))
    block = {"version": p["version"], "value": value, "grade": grade(value, p["bands"]),
             "components": {"faults": float(round_half_up(f, 2)), "similarity": float(round_half_up(s, 2))},
             "params_sha256": params_sha256(p)}
    return apply_fault_cap(block, bool(analysis.get("faults")), rules)


# --- calibration on seed 5 only (part5.calibrate --score) ---
def calibrate(rows, min_fraction):
    """The `score` block from seed 5 rows `{lighting, n_labelled, faults: [{r, dur, cov}], mean_z}`.

    z0 the 95th percentile of the correct good-light takes' mean_z, z1 the worst take's; `base` makes the
    smallest counted fault (r = 1, shortest run, full coverage) cost more than 10 points; `slope` makes the
    worst single good-light fault (one labelled, one detected) land at 70 or above with the full similarity cost.
    """
    good = [r for r in rows if r["lighting"] == "good"]
    corr = sorted(r["mean_z"] for r in good if r["n_labelled"] == 0)
    z0 = corr[math.ceil(0.95 * len(corr)) - 1]
    z1 = max(r["mean_z"] for r in rows)
    base = math.ceil(SINGLE_FLOOR / (MIN_COVER + 0.5 * min_fraction))
    singles = [f for r in good if r["n_labelled"] == 1 and len(r["faults"]) == 1 for f in r["faults"]]
    worst = max(singles, key=lambda f: f["r"] * (MIN_COVER + 0.5 * f["dur"]))
    k = (WORST_SINGLE - S_MAX) / (MIN_COVER + 0.5 * worst["dur"]) - base
    k = math.floor(k / (worst["r"] - 1) * 10) / 10
    cap = base + k * (worst["r"] - 1)
    return {"version": VERSION_V1, "z0": round(z0, 3), "z1": round(z1, 3), "s_max": S_MAX, "base": base,
            "slope": k, "cap": round(cap, 1), "bands": BANDS, "calibrated_on": "seed 5"}


def floor_holds(m):
    """Does the floor behind the seed 5 measurement `m` meet ADR-0018's four conditions? `m` is
    `{correct_all_a, single_min, double_max, sweep_rises}`; a floor with no single or no double take (None) cannot fail
    the condition it has no data for."""
    return (m["correct_all_a"] and not m["sweep_rises"]
            and (m["single_min"] is None or m["single_min"] >= SINGLE_MIN)
            and (m["double_max"] is None or m["double_max"] <= DOUBLE_MAX))


def choose_floor(measured):
    """`range_floor` by ADR-0018's rule: the lowest floor of FLOOR_GRID whose measurement holds (`floor_holds`), else
    1.0. `measured` maps a floor of the grid to its seed 5 measurement."""
    return next((f for f in FLOOR_GRID if f in measured and floor_holds(measured[f])), 1.0)


def block_v2(v1, floor):
    """The v2 `score` block: v1's numbers repeated at the top level (the penalty curve, the similarity term and the bands
    are unchanged, ADR-0018), the three v2 params, and the frozen v1 block verbatim as `v1`."""
    return {"version": VERSION, **{k: v1[k] for k in SHARED_V1}, "range_floor": floor, "range_full": RANGE_FULL,
            "fault_cap": FAULT_CAP, "calibrated_on": "seed 5", "v1": v1}


# --- the score timeline (ADR-0013) ---
# A take is scored in windows (its repetitions, or slices of about WINDOW_S seconds) with the formula above,
# and its value is the mean of the window values. So the score is a share of the take, not points per
# mistake: one miss in one minute costs about what ten misses in ten minutes cost. Each window lists its
# misses with the points each one cost, so the timeline adds up to the score. A take of one window
# (under 7.5 s, or one rep) scores exactly as `compute` does.
WINDOW_S = 5.0
MIN_TEMPO_S = 1.0     # ADR-0014: a stretch of the example shorter than this is not timed
NO_TEMPO = object()   # timeline_block(tempo=NO_TEMPO): no `score.tempo` key at all


def windows_of(frame_times, window_s=WINDOW_S):
    """`(window index per expected frame, [(t0, t1)] per window)`: the follower span the expected frames land
    on, cut into max(1, round(span / window_s)) equal slices."""
    t = np.asarray(frame_times, dtype=float)
    t0, t1 = float(np.min(t)), float(np.max(t))
    k = max(1, int(round((t1 - t0) / window_s)))
    edges = t0 + (t1 - t0) * np.arange(k + 1) / k
    index = np.clip(np.searchsorted(edges, t, side="right") - 1, 0, k - 1)
    return index, [(float(edges[i]), float(edges[i + 1])) for i in range(k)]


def _frames_in(fault, frames):
    runs = fault.get("runs") or [fault["expected_frames"]]
    return sum(int(np.count_nonzero((frames >= s) & (frames <= e))) for s, e in runs)


def miss_entry(fault, points):
    """One miss on the timeline: what to say, what to do (1.5.0 cue, ADR-0014), where, and what it cost."""
    out = {"text": fault.get("coaching") or fault.get("text_timed") or fault["text"],
           "measure": fault["measure"], "side": fault.get("side"), "joint": fault.get("joint"),
           "t_s": fault.get("follower_t_s"), "at_s": fault.get("at_s"), "points": float(round_half_up(points, 1))}
    if fault.get("cue"):
        out.update(cue=fault["cue"], cue_kind=fault["cue_kind"], direction=fault["direction"])
    return out


def tempo_charge(ratio, tempo):
    """Points a window's tempo costs under a profile's `tempo` block (ADR-0016, dance), or None when the profile
    charges no tempo (weight 0), in which case the window has no `components.tempo`. The charge is worked from the
    ratio as the document shows it (rounded to 0.01), so a reader can reproduce it from `tempo.ratio`."""
    if not tempo["weight"] > 0:
        return None
    shown = None if ratio is None else round(float(ratio), 2)
    return profiles.tempo_points(shown, tempo["weight"], tempo["cap"])


def window_score(analysis, aligned, frames, rules, p, tempo_points=None):
    """`{value, components, misses}` of the expected `frames` (an index array) of a take, or None when
    nothing in them can be measured. The unrounded value is kept for the take's mean.

    `tempo_points` (ADR-0016) is the window's tempo charge from `tempo_charge`: None for a profile that charges no
    tempo (no `components.tempo` key, the score as it always was), else points taken off the value."""
    if (analysis.get("status") or {}).get("code") not in ("ok", None):
        return None
    frames = np.asarray(frames)
    sub = {"expected": {n: np.asarray(v)[frames] for n, v in aligned["expected"].items()},
           "follower": aligned["follower"], "exp_to_fol": np.asarray(aligned["exp_to_fol"])[frames]}
    z = mean_z(sub, rules)
    if z is None:
        return None
    feats, misses = [], []
    for fault in analysis.get("faults", []):
        n_in = _frames_in(fault, frames)
        if not n_in:
            continue
        x = {"r": abs(fault["magnitude_deg"]) / fault["threshold_deg"], "dur": min(1.0, n_in / len(frames)),
             "cov": fault["coverage"]}
        x["u"] = trainer_range(fault, sub["expected"], rules)   # ADR-0018: the window's range
        feats.append(x)
        misses.append(miss_entry(fault, miss_cost(x, p)))
    f, s = components({"faults": feats, "mean_z": z}, p)
    raw = max(0.0, min(100.0, 100 - f - s - (tempo_points or 0.0)))
    value = int(round_half_up(raw))
    parts = {"faults": float(round_half_up(f, 2)), "similarity": float(round_half_up(s, 2))}
    if tempo_points is not None:
        parts["tempo"] = float(round_half_up(tempo_points, 2))
    return {"raw": raw, "value": value, "grade": grade(value, p["bands"]), "components": parts,
            "misses": sorted(misses, key=lambda m: (m["at_s"] is None, m["at_s"] or 0))}


def timeline_window(span, analysis, aligned, frames, rules, p, tempo, ratio, timed=True):
    """One entry of a take's timeline: the `window_score` of the expected `frames` under `t_s` = `span`, charged
    what the profile's `tempo` block charges for the window's tempo `ratio` (follower over example time, None when
    unmeasured; ADR-0016) and, when `timed`, carrying that tempo block (ADR-0014). `{t_s, compared: False}` when
    nothing in the window can be scored. The windows of a take compared as a whole and of one compared rep by rep
    are both made here."""
    scored = window_score(analysis, aligned, frames, rules, p, tempo_charge(ratio, tempo)) if np.size(frames) else None
    if not scored:
        return {"t_s": span, "compared": False}
    if timed:
        scored["tempo"] = tempo_block(ratio, tempo["cues"])
    return {"t_s": span, **scored}


def timeline_block(windows, basis, rules=None, tempo=NO_TEMPO, reports_fault=False):
    """The take's `score` block from its windows, each `{t_s, ...window_score}` or `{t_s, compared: False}`.
    The value is the mean of the compared windows; `timeline` lists every window. `tempo`, when given, is the
    take's follower/example time ratio (or None, unmeasured) and becomes `score.tempo` (ADR-0014). `reports_fault` is
    whether the take's `faults` list has anything in it: a v2 block (ADR-0018) then carries `fault_cap` and the value
    is capped once, on the mean, never on a window."""
    p = params_of(rules or load_rules())
    scored = [w for w in windows if w.get("compared", True)]
    cues = profiles.tempo_of(rules or {})["cues"]   # the profile's tempo words (ADR-0016); none for plain rules
    extra = {} if tempo is NO_TEMPO else {"tempo": tempo_block(tempo, cues)}
    if not scored:
        block = dict(zero_block(rules), basis=basis, timeline=[_public(w) for w in windows], **extra)
        return apply_fault_cap(block, reports_fault, rules)   # value 0 under any ceiling; fault_cap iff the take reports a fault
    value = int(round_half_up(sum(w["raw"] for w in scored) / len(scored)))
    parts = {key: float(round_half_up(sum(w["components"][key] for w in scored) / len(scored), 2))
             for key in ("faults", "similarity", *(("tempo",) if "tempo" in scored[0]["components"] else ()))}
    block = {"version": p["version"], "value": value, "grade": grade(value, p["bands"]), "components": parts,
             "params_sha256": params_sha256(p), "basis": basis, "timeline": [_public(w) for w in windows], **extra}
    return apply_fault_cap(block, reports_fault, rules)


def span_ratio(follower_t, expected_t):
    """Tempo of a stretch of movement (ADR-0014): follower seconds per example second, or None when the
    example side spans under MIN_TEMPO_S (too short to time)."""
    fol, exp = np.asarray(follower_t, dtype=float), np.asarray(expected_t, dtype=float)
    if fol.size < 2 or exp.size < 2:
        return None
    d_exp = float(np.max(exp) - np.min(exp))
    if d_exp < MIN_TEMPO_S:
        return None
    return float(np.max(fol) - np.min(fol)) / d_exp


def _public(window):
    out = {k: v for k, v in window.items() if k != "raw"}
    out["t_s"] = [round(float(window["t_s"][0]), 3), round(float(window["t_s"][1]), 3)]
    out.setdefault("compared", True)
    return out


def compute_timeline(analysis, aligned, frame_times, rules=None, window_s=WINDOW_S, expected_times=None):
    """The `score` block of a take compared as a whole: windows of about `window_s` on the follower's clock.
    `frame_times[i]` is the follower file time expected frame i was matched to. With `expected_times` (the
    example's own time per frame) each compared window and the take get their tempo (ADR-0014)."""
    rules = rules or load_rules()
    p = params_of(rules)
    index, spans = windows_of(frame_times, window_s)
    fol_t = np.asarray(frame_times, dtype=float)
    exp_t = None if expected_times is None else np.asarray(expected_times, dtype=float)
    tempo = profiles.tempo_of(rules)   # ADR-0016: the profile's tempo words and, for dance, its charge
    windows = []
    for k, span in enumerate(spans):
        frames = np.flatnonzero(index == k)
        ratio = span_ratio(fol_t[frames], exp_t[frames]) if exp_t is not None and frames.size else None
        windows.append(timeline_window(span, analysis, aligned, frames, rules, p, tempo, ratio, timed=exp_t is not None))
    return timeline_block(windows, "windows", rules, NO_TEMPO if exp_t is None else span_ratio(fol_t, exp_t),
                          reports_fault=bool(analysis.get("faults")))
