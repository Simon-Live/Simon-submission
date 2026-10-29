"""Fault detection: turn aligned per-frame differences into a short list of faults.

For each measure, diff[i] = follower(matched frame) − expected(frame i), median-filtered to drop
single-frame spikes. A fault is every run of at least `min_run_frames` frames where the diff stays
past the measure's threshold in one direction, if those runs together cover at least
`min_fraction` of the expected clip (floor `min_frames_floor`). The longest run is the fault's
frames; `runs` lists them all (#30). Then:
- faults that follow from a kept fault (rules["explained_by"], same direction, or
  rules["explained_by_opposite"], the other direction: a knee caving in pulls the thigh in) are dropped;
- the same measure and direction on both sides, with overlapping frames, merges into side "both".
Both steps need the faults to share at least `min_overlap` of the shorter one's frames.
"""
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from .align import Alignment
from .measures import MEASURES

RULES_PATH = Path(__file__).with_name("rules.json")
DEFAULT_MIN_RUN_FRAMES = 4
DEFAULT_MIN_OVERLAP = 0.5


def load_rules(path=RULES_PATH):
    return json.loads(Path(path).read_text())


@dataclass
class Fault:
    measure: str            # generic measure, e.g. "upper_arm_out" (side-less)
    side: str               # left / right / both / center
    joint: str              # e.g. "left_shoulder"; for "both", the left joint's name with side stripped
    body_part: str
    direction: str          # "more" or "less" than the example
    magnitude_deg: float    # median signed diff over all counted runs (follower − expected)
    peak_deg: float         # largest |diff| in the counted runs, signed
    threshold_deg: float
    expected_frames: tuple  # inclusive longest run, expected-clip frames
    follower_frames: tuple  # matched follower frames for that run
    phase: tuple            # 0..1 of the expected movement
    coverage: float         # fraction of the counted frames with both measures available
    confidence: float       # 0..1, from the margin over the threshold and coverage
    runs: tuple = ()        # every counted run, inclusive expected-clip frames (the longest is expected_frames)

    def __post_init__(self):
        if not self.runs:
            self.runs = (tuple(self.expected_frames),)

    def to_dict(self):
        d = asdict(self)
        for k in ("expected_frames", "follower_frames", "phase"):
            d[k] = list(d[k])
        d["runs"] = [list(r) for r in self.runs]
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


def _runs(flags):
    """Maximal runs of True in `flags` as inclusive (start, end) frame pairs."""
    out, start = [], None
    for i, f in enumerate(list(flags) + [False]):
        if f and start is None:
            start = i
        elif not f and start is not None:
            out.append((start, i - 1))
            start = None
    return out


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
        sm = _median_filter(d, rules.get("smooth_frames", 1))
        for sign, direction in ((1, "more"), (-1, "less")):
            fault = _fault(name, g, side, direction, sign, d, sm, cfg, alignment, n)
            if fault is not None:
                raw.append(fault)
    overlap = rules["default"].get("min_overlap", DEFAULT_MIN_OVERLAP)
    kept = _drop_explained(raw, rules.get("explained_by", {}), overlap, rules.get("explained_by_opposite", {}))
    return _merge_sides(kept, overlap)


def _counted_runs(flags, cfg, n):
    """The runs that count toward persistence, or [] when together they are too short.

    Deliberate faults are held through a good part of the movement, possibly in several
    stretches; noise comes in short runs. A run counts from `min_run_frames`, and the runs
    must sum to `min_frames` (the fraction of the clip, floored)."""
    min_run = cfg.get("min_run_frames", DEFAULT_MIN_RUN_FRAMES)
    min_frames = cfg.get("min_frames") or max(cfg["min_frames_floor"], int(round(cfg["min_fraction"] * n)))
    runs = [(s, e) for s, e in _runs(flags) if e - s + 1 >= min_run]
    return runs if sum(e - s + 1 for s, e in runs) >= min_frames else []


def _fault(name, g, side, direction, sign, d, sm, cfg, alignment, n):
    thr = cfg["threshold_deg"]
    with np.errstate(invalid="ignore"):
        flags = sign * sm > thr
    runs = _counted_runs(flags, cfg, n)
    if not runs:
        return None
    s, e = max(runs, key=lambda r: r[1] - r[0])  # the longest run, the earliest on a tie
    vals = np.concatenate([sm[a:b + 1] for a, b in runs])
    mag = float(np.nanmedian(vals))
    peak = float(vals[np.nanargmax(np.abs(vals))])
    coverage = float(np.concatenate([np.isfinite(d[a:b + 1]) for a, b in runs]).mean())
    margin = min(1.0, (abs(mag) - thr) / thr + 0.5)
    spec = MEASURES[name]
    return Fault(
        measure=g, side=side, joint=spec.joint, body_part=spec.body_part, direction=direction,
        magnitude_deg=round(mag, 1), peak_deg=round(peak, 1), threshold_deg=thr,
        expected_frames=(s, e),
        follower_frames=(int(alignment.exp_to_fol[s]), int(alignment.exp_to_fol[e])),
        phase=(round(s / max(n - 1, 1), 3), round(e / max(n - 1, 1), 3)),
        coverage=round(coverage, 3), confidence=round(max(0.0, margin) * coverage, 3),
        runs=tuple(runs))


def _frames(fault):
    return {i for s, e in fault.runs for i in range(s, e + 1)}


def _overlaps(a, b, min_overlap=DEFAULT_MIN_OVERLAP):
    """Do two faults share frames, at least `min_overlap` of the shorter one's counted frames?"""
    fa, fb = _frames(a), _frames(b)
    shared = len(fa & fb)
    return shared > 0 and shared >= min_overlap * min(len(fa), len(fb))


def _explains(cause, fault, explained_by, min_overlap, opposite):
    """Does `cause` explain `fault`: a listed measure on the same side (or the centre), overlapping
    enough, in the same direction (`explained_by`) or the other one (`opposite`)."""
    same = cause.direction == fault.direction
    listed = cause.measure in (explained_by if same else opposite).get(fault.measure, [])
    return (cause is not fault and listed and cause.side in (fault.side, "center")
            and _overlaps(cause, fault, min_overlap))


def _drop_explained(faults, explained_by, min_overlap=DEFAULT_MIN_OVERLAP, opposite=None):
    """Drop the faults that a kept fault explains. A dropped fault explains nothing, so a chain
    is judged from its root down."""
    opposite = opposite or {}
    causes = [[j for j, c in enumerate(faults) if _explains(c, f, explained_by, min_overlap, opposite)]
              for f in faults]
    state = {}

    def kept(i):
        if i not in state:
            state[i] = True  # a cycle in the rules lets the fault stand rather than loop
            state[i] = not any(kept(j) for j in causes[i])
        return state[i]

    return [f for i, f in enumerate(faults) if kept(i)]


def _union_runs(a, b):
    """Two lists of inclusive runs as one sorted list, joining runs that overlap or touch."""
    out = []
    for s, e in sorted(a + b):
        if out and s <= out[-1][1] + 1:
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            out.append((s, e))
    return tuple(out)


def _both(f, o):
    """The left fault `f` and the right fault `o` as one fault on both sides."""
    return Fault(
        measure=f.measure, side="both", joint=f.joint.removeprefix("left_"),
        body_part=f.body_part, direction=f.direction,
        magnitude_deg=round((f.magnitude_deg + o.magnitude_deg) / 2, 1),
        peak_deg=max(f.peak_deg, o.peak_deg, key=abs), threshold_deg=f.threshold_deg,
        expected_frames=(min(f.expected_frames[0], o.expected_frames[0]),
                         max(f.expected_frames[1], o.expected_frames[1])),
        follower_frames=(min(f.follower_frames[0], o.follower_frames[0]),
                         max(f.follower_frames[1], o.follower_frames[1])),
        phase=(min(f.phase[0], o.phase[0]), max(f.phase[1], o.phase[1])),
        coverage=min(f.coverage, o.coverage), confidence=min(f.confidence, o.confidence),
        runs=_union_runs(list(f.runs), list(o.runs)))


def _merge_sides(faults, min_overlap=DEFAULT_MIN_OVERLAP):
    # Lefts first, so a right fault listed before its left partner still gets merged.
    faults = sorted(faults, key=lambda f: f.side != "left")
    out, used = [], set()
    for i, f in enumerate(faults):
        if i in used:
            continue
        if f.side == "left":
            for k, o in enumerate(faults):
                if (k not in used and k != i and o.side == "right" and o.measure == f.measure
                        and o.direction == f.direction and _overlaps(f, o, min_overlap)):
                    used.add(k)
                    f = _both(f, o)
                    break
        out.append(f)
        used.add(i)
    return sorted(out, key=lambda f: -abs(f.magnitude_deg))
