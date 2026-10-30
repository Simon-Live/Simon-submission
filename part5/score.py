"""The take's score out of 100 with a grade A to F (`simon.score.v1`, ADR-0007, docs/specs/journey-followup.md J-4).

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
"""
import hashlib
import json
import math
from decimal import ROUND_HALF_UP, Decimal

import numpy as np

from .detect import load_rules
from .measures import MEASURES

VERSION = "simon.score.v1"
MIN_COVER = 0.5      # the penalty weight of a fault with no duration: 0.5 + 0.5 * dur
CLIP_Z = 2.0         # a measure frame is never worse than twice its threshold
S_MAX = 4.0          # similarity costs at most this many points (calibration rule)
SINGLE_FLOOR = 10.5  # the smallest counted fault must cost more than 10 points (never an A)
WORST_SINGLE = 30.0  # the worst single good-light fault still lands at 70 or above (a C)
BANDS = [[90, "A"], [80, "B"], [70, "C"], [60, "D"], [0, "F"]]


def params_of(rules):
    """The `score` block of the rules, or a ValueError naming what is missing."""
    block = (rules or {}).get("score")
    if not isinstance(block, dict) or block.get("version") != VERSION:
        raise ValueError(f"part5/rules.json has no {VERSION} 'score' block")
    return block


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


def fault_features(fault, n_frames):
    """(r, dur, coverage) of one fault of the analysis."""
    runs = fault.get("runs") or [fault["expected_frames"]]
    dur = sum(e - s + 1 for s, e in runs) / n_frames
    return {"r": abs(fault["magnitude_deg"]) / fault["threshold_deg"], "dur": min(1.0, dur), "cov": fault["coverage"]}


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
    """What the score is computed from: {"faults": [{r, dur, cov}], "mean_z": float}, or None for a refused take."""
    if (analysis.get("status") or {}).get("code") != "ok":
        return None
    z = mean_z(aligned, rules)
    if z is None:
        return None
    n = len(aligned["exp_to_fol"])
    return {"faults": [fault_features(f, n) for f in analysis.get("faults", [])], "mean_z": z}


def penalty(r, p):
    return min(p["cap"], p["base"] + p["slope"] * (r - 1))


def components(feats, p):
    """(F, S) unrounded."""
    f = sum(penalty(x["r"], p) * (MIN_COVER + 0.5 * x["dur"]) * x["cov"] for x in feats["faults"])
    s = p["s_max"] * min(1.0, max(0.0, (feats["mean_z"] - p["z0"]) / (p["z1"] - p["z0"])))
    return f, s


def compute(analysis, aligned, rules=None):
    """The `score` block of the analysis, or None for a refused take (never a 0)."""
    rules = rules or load_rules()
    p = params_of(rules)
    feats = features(analysis, aligned, rules)
    if feats is None:
        return None
    f, s = components(feats, p)
    value = max(0, min(100, int(round_half_up(100 - f - s))))
    return {"version": VERSION, "value": value, "grade": grade(value, p["bands"]),
            "components": {"faults": float(round_half_up(f, 2)), "similarity": float(round_half_up(s, 2))},
            "params_sha256": params_sha256(p)}


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
    return {"version": VERSION, "z0": round(z0, 3), "z1": round(z1, 3), "s_max": S_MAX, "base": base,
            "slope": k, "cap": round(cap, 1), "bands": BANDS, "calibrated_on": "seed 5"}
