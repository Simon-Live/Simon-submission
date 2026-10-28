"""Fault detection: turn aligned per-frame differences into a short list of faults.

For each measure, diff[i] = follower(matched frame) − expected(frame i), median-filtered to drop
single-frame spikes. A fault is the longest run of frames where the diff stays past the
measure's threshold in one direction, if that run covers at least `min_fraction` of the
expected clip (floor `min_frames_floor`). Then:
- faults that follow from another fault (rules["explained_by"]) are dropped;
- the same measure and direction on both sides, with overlapping frames, merges into side "both".
"""
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from .align import Alignment
from .measures import MEASURES

RULES_PATH = Path(__file__).with_name("rules.json")


def load_rules(path=RULES_PATH):
    return json.loads(Path(path).read_text())


@dataclass
class Fault:
    measure: str            # generic measure, e.g. "upper_arm_out" (side-less)
    side: str               # left / right / both / center
    joint: str              # e.g. "left_shoulder"; for "both", the left joint's name with side stripped
    body_part: str
    direction: str          # "more" or "less" than the example
    magnitude_deg: float    # median signed diff over the run (follower − expected)
    peak_deg: float         # largest |diff| in the run, signed
    threshold_deg: float
    expected_frames: tuple  # inclusive run, expected-clip frames
    follower_frames: tuple  # matched follower frames for that run
    phase: tuple            # 0..1 of the expected movement
    coverage: float         # fraction of the run with both measures available
    confidence: float       # 0..1, from the margin over the threshold and coverage

    def to_dict(self):
        d = asdict(self)
        for k in ("expected_frames", "follower_frames", "phase"):
            d[k] = list(d[k])
        return d


def generic(name):
    for side in ("left_", "right_"):
        if name.startswith(side):
            return name[len(side):], side[:-1]
    return name, "center"


def _median_filter(x, k):
    if k <= 1:
        return x.copy()
    h = k // 2
    out = np.full_like(x, np.nan)
    for i in range(len(x)):
        w = x[max(0, i - h):i + h + 1]
        w = w[np.isfinite(w)]
        if len(w) > h:  # need most of the window to be real data
            out[i] = np.median(w)
    return out


def _longest_run(flags):
    best, start = (0, -1, -1), None
    for i, f in enumerate(list(flags) + [False]):
        if f and start is None:
            start = i
        elif not f and start is not None:
            if i - start > best[0]:
                best = (i - start, start, i - 1)
            start = None
    return best


def differences(exp_m, fol_m, alignment: Alignment, tolerance_frames=0):
    """Follower − expected per expected frame, along the alignment.

    With a tolerance of k frames, a follower value that falls within the range the expected
    clip covers in frames i−k..i+k counts as a match (diff 0); otherwise the diff is the distance
    to the nearest edge of that range. This absorbs small timing errors on fast-changing
    measures, without hiding an offset that is held.
    """
    j = alignment.exp_to_fol
    out = {}
    for name in MEASURES:
        e, f = exp_m[name], fol_m[name][j]
        if tolerance_frames <= 0:
            out[name] = f - e
            continue
        n = len(e)
        lo, hi = np.empty(n), np.empty(n)
        for i in range(n):
            w = e[max(0, i - tolerance_frames):i + tolerance_frames + 1]
            w = w[np.isfinite(w)]
            lo[i], hi[i] = (w.min(), w.max()) if len(w) else (np.nan, np.nan)
        with np.errstate(invalid="ignore"):
            out[name] = np.where(f > hi, f - hi, np.where(f < lo, f - lo, 0.0))
        out[name][~np.isfinite(f) | ~np.isfinite(e)] = np.nan
    return out


def detect(exp_m, fol_m, alignment: Alignment, rules=None):
    rules = rules or load_rules()
    diffs = differences(exp_m, fol_m, alignment, rules.get("tolerance_frames", 0))
    n = len(alignment.exp_to_fol)
    raw = []
    for name, d in diffs.items():
        g, side = generic(name)
        cfg = {**rules["default"], **rules["measures"].get(g, {})}
        thr = cfg["threshold_deg"]
        # Deliberate faults are held through a good part of the movement; noise comes in short runs.
        min_frames = cfg.get("min_frames") or max(cfg["min_frames_floor"], int(round(cfg["min_fraction"] * n)))
        sm = _median_filter(d, rules.get("smooth_frames", 1))
        for sign, direction in ((1, "more"), (-1, "less")):
            with np.errstate(invalid="ignore"):
                flags = sign * sm > thr
            length, s, e = _longest_run(flags)
            if length < min_frames:
                continue
            run = sm[s:e + 1]
            valid = np.isfinite(d[s:e + 1])
            mag = float(np.nanmedian(run))
            peak = float(run[np.nanargmax(np.abs(run))])
            coverage = float(valid.mean())
            margin = min(1.0, (abs(mag) - thr) / thr + 0.5)
            spec = MEASURES[name]
            raw.append(Fault(
                measure=g, side=side, joint=spec.joint, body_part=spec.body_part, direction=direction,
                magnitude_deg=round(mag, 1), peak_deg=round(peak, 1), threshold_deg=thr,
                expected_frames=(s, e),
                follower_frames=(int(alignment.exp_to_fol[s]), int(alignment.exp_to_fol[e])),
                phase=(round(s / max(n - 1, 1), 3), round(e / max(n - 1, 1), 3)),
                coverage=round(coverage, 3), confidence=round(max(0.0, margin) * coverage, 3)))
    return _merge_sides(_drop_explained(raw, rules.get("explained_by", {})))


def _overlaps(a, b):
    return a.expected_frames[0] <= b.expected_frames[1] and b.expected_frames[0] <= a.expected_frames[1]


def _drop_explained(faults, explained_by):
    keep = []
    for f in faults:
        causes = explained_by.get(f.measure, [])
        if any(c.measure in causes and c.direction == f.direction and c.side in (f.side, "center")
               and _overlaps(c, f) for c in faults if c is not f):
            continue
        keep.append(f)
    return keep


def _merge_sides(faults):
    # Lefts first, so a right fault listed before its left partner still gets merged.
    faults = sorted(faults, key=lambda f: f.side != "left")
    out, used = [], set()
    for i, f in enumerate(faults):
        if i in used:
            continue
        if f.side == "left":
            for k, o in enumerate(faults):
                if (k not in used and k != i and o.side == "right" and o.measure == f.measure
                        and o.direction == f.direction and _overlaps(f, o)):
                    used.add(k)
                    s = min(f.expected_frames[0], o.expected_frames[0])
                    e = max(f.expected_frames[1], o.expected_frames[1])
                    fs = min(f.follower_frames[0], o.follower_frames[0])
                    fe = max(f.follower_frames[1], o.follower_frames[1])
                    f = Fault(
                        measure=f.measure, side="both", joint=f.joint.removeprefix("left_"),
                        body_part=f.body_part, direction=f.direction,
                        magnitude_deg=round((f.magnitude_deg + o.magnitude_deg) / 2, 1),
                        peak_deg=max(f.peak_deg, o.peak_deg, key=abs), threshold_deg=f.threshold_deg,
                        expected_frames=(s, e), follower_frames=(fs, fe),
                        phase=(min(f.phase[0], o.phase[0]), max(f.phase[1], o.phase[1])),
                        coverage=min(f.coverage, o.coverage), confidence=min(f.confidence, o.confidence))
                    break
        out.append(f)
        used.add(i)
    return sorted(out, key=lambda f: -abs(f.magnitude_deg))
