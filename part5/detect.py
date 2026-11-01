"""Fault detection: turn aligned per-frame differences into a short list of faults.

For each measure, diff[i] = follower(matched frame) − expected(frame i), median-filtered to drop
single-frame spikes. A fault is every run of at least `min_run_frames` frames where the diff stays
past the measure's threshold in one direction, if those runs together cover at least
`min_fraction` of the expected clip (floor `min_frames_floor_body`, or `min_frames_floor` for a foot measure; recheck N2). The longest run is the fault's
frames (a profile's fault: see below); `runs` lists them all (#30). Persistence (`persistence.judge`) is judged against
the expected rep the frames fall in (ADR-0017): an example with two or more reps passes its reps as `rep_spans`, a run
belongs to the rep that holds most of it, and each rep needs `min_fraction` of itself; the floor is a duration, so
`fps` (the example's frame rate) turns it into frames. An example of one rep is one rep, the whole clip, as it always
was, and a take compared rep by rep (ADR-0010) detects each rep against its own reference. Then:
- faults that follow from a kept fault (rules["explained_by"], same direction, or
  rules["explained_by_opposite"], the other direction: a knee caving in pulls the thigh in) are dropped;
- the same measure and direction on both sides, with overlapping frames, merges into side "both"; its frames are the
  span from the earlier start to the later end of the two sides' reported runs, so a merged fault's frames can span
  several of its `runs` instead of being one of them.
Both steps need the faults to share at least `min_overlap` of the shorter one's frames.

With profile rules (ADR-0016, `profiles.effective_rules`) each fault is built twice, at the baseline (fitness) config
and at the profile's looser one: explanation is judged on the baseline faults, and each survivor is replaced by its
profile counterpart or dropped when the looser config no longer finds it. A profile therefore reports no fault that
fitness does not, in one detection (a fault fitness reports on both sides may stay on one side). Before any merge,
the frames of a profile fault on one side are the one of its own counted runs that shares the most frames with the
run fitness reports for the same measure, side and direction: a mode names the moment fitness names. Equal overlap is
broken by the longest run, then by the earliest. When no run shares a frame with the fitness run, the longest run
(the earliest on a tie) is reported, as for fitness. A take compared
repetition by repetition runs one detection per rep, and `repwise.compare` then keeps only the take-level faults
that fitness reports for the take too.

The foot measures (ADR-0015, `measures.FOOT_MEASURES`) are visited only when both measure dicts carry them, which
the pipeline arranges for a pair with usable feet on both sides, and only when `rules["measures"]` has an entry
for them: they have no default threshold. Everything above applies to them unchanged.

Near misses (TICKET-043, docs/specs/near-misses.md): `detect_full` also returns a `Candidate` for every measure, side and
direction that had a frame past its threshold, tagged with what became of it (a reported fault, dropped for persistence,
or explained by a kept fault). `detect` is `detect_full` without them, so the faults are the same list either way, and
nothing in a candidate feeds back into detection.
"""
import json
from dataclasses import asdict, dataclass, replace
from pathlib import Path

import numpy as np

from .align import Alignment
from .measures import ALL_SPECS, FOOT_MEASURES, MEASURES
from .persistence import judge

RULES_PATH = Path(__file__).with_name("rules.json")
DEFAULT_MIN_OVERLAP = 0.5
MAX_NEAR_MISSES = 10   # items listed in diagnostics.near_misses; `summary` counts the rest
# What became of a candidate. A take compared rep by rep adds REPS and FITNESS (`repwise.across_reps`).
REPORTED, PERSISTENCE, EXPLAINED_BY, REPS, FITNESS = "reported", "persistence", "explained_by", "reps", "fitness"
REASONS = (PERSISTENCE, EXPLAINED_BY, REPS, FITNESS)   # the outcomes of a near miss: every one but REPORTED


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
    expected_frames: tuple  # inclusive reported run, expected-clip frames: the longest run (a profile's: see _reported_run)
    follower_frames: tuple  # matched follower frames for that run (a merged side "both" fault: the span of its sides')
    phase: tuple            # 0..1 of the expected movement
    coverage: float         # fraction of the counted frames with both measures available
    confidence: float       # 0..1, from the margin over the threshold and coverage
    runs: tuple = ()        # every counted run, inclusive expected-clip frames; expected_frames is one of them, except on
                            # a merged side "both" fault: it spans its two sides' reported runs, e.g. (5, 79) over
                            # the runs ((5, 30), (40, 79))

    def __post_init__(self):
        if not self.runs:
            self.runs = (tuple(self.expected_frames),)

    def to_dict(self):
        d = asdict(self)
        for k in ("expected_frames", "follower_frames", "phase"):
            d[k] = list(d[k])
        d["runs"] = [list(r) for r in self.runs]
        return d


@dataclass
class Candidate:
    """A measure on one side in one direction with at least one frame past its threshold, and what became of it.

    Sized like a fault (`magnitude_deg`, `peak_deg`: over the counted runs, else over every frame past the threshold).
    The side is never "both": sides are merged for reported faults only. A near miss is a candidate that is not
    reported; `to_dict` is its `diagnostics.near_misses.items` entry."""
    measure: str
    side: str               # left / right / center
    joint: str
    body_part: str
    direction: str          # "more" or "less" than the example
    magnitude_deg: float    # signed median of the smoothed difference
    peak_deg: float         # largest signed value of the same frames
    threshold_deg: float
    expected_frames: tuple  # inclusive, the longest run past the threshold (the earliest on a tie)
    follower_frames: tuple  # matched follower frames for that run
    frames_over: int        # frames past the threshold, any run length
    counted_frames: int     # those in runs of at least min_run_frames
    needed_frames: int      # what persistence needed
    min_run_frames: int
    outcome: str = REPORTED
    explained_by: tuple | None = None   # (measure, side, direction) of the kept fault that explains it
    reps: tuple = ()                    # rep mode: the reps in which it crossed the threshold
    found_in_reps: int = 0              # rep mode: the reps that reported its side of it, alone or as part of `both`
    needed_reps: int = 0                # rep mode: half the accepted reps, rounded up

    @property
    def key(self):
        return self.measure, self.side, self.direction

    @property
    def persists(self):
        """Do the counted frames meet persistence? The test `persistence.judge` makes."""
        return self.counted_frames > 0 and self.counted_frames >= self.needed_frames

    def to_dict(self):
        d = {"measure": self.measure, "side": self.side, "joint": self.joint, "body_part": self.body_part,
             "direction": self.direction, "magnitude_deg": float(self.magnitude_deg),
             "peak_deg": float(self.peak_deg), "threshold_deg": float(self.threshold_deg),
             "expected_frames": [int(f) for f in self.expected_frames],
             "follower_frames": [int(f) for f in self.follower_frames],
             "frames_over": int(self.frames_over), "counted_frames": int(self.counted_frames),
             "needed_frames": int(self.needed_frames), "min_run_frames": int(self.min_run_frames),
             "reason": self.outcome}
        if self.outcome == PERSISTENCE:
            d["shortfall_frames"] = max(0, int(self.needed_frames - self.counted_frames))
        elif self.outcome == EXPLAINED_BY:
            d["explained_by"] = dict(zip(("measure", "side", "direction"), self.explained_by))
        elif self.outcome in (REPS, FITNESS):
            d["found_in_reps"], d["needed_reps"] = int(self.found_in_reps), int(self.needed_reps)
        if self.reps:
            d["reps"] = [int(i) for i in self.reps]
        return d


@dataclass
class Detection:
    """What `detect_full` found: the take's faults and, unless switched off, every candidate with its outcome."""
    faults: list
    candidates: list

    @property
    def near_misses(self):
        return [c for c in self.candidates if c.outcome != REPORTED]


def reports(fault_keys, key):
    """Does a fault in `fault_keys` ((measure, side, direction) tuples) report the candidate `key`: the same measure
    and direction on its side, or on both sides."""
    measure, side, direction = key
    return any(m == measure and d == direction and s in (side, "both") for m, s, d in fault_keys)


def overlaps_side(fault_keys, key):
    """Does a fault in `fault_keys` have the measure and direction of `key` on a side that overlaps its side: the same
    side, or `both` against either (a fault on both sides covers each of them, and each of them is part of it)."""
    measure, side, direction = key
    return any(m == measure and d == direction and (s == side or "both" in (s, side)) for m, s, d in fault_keys)


def as_both(fault):
    """`fault`, found on one side, as the fault on both sides it is part of: the side `both` and the joint named as
    `_both` names it (the side stripped). A fault that is already `both` is returned as it is."""
    if fault.side != "both":
        fault = replace(fault, side="both", joint=fault.joint.removeprefix(f"{fault.side}_"))
    return fault


def on_file(candidates, to_original):
    """`candidates` with their follower frames mapped to the follower file's own (`to_original[j]` is the file's frame
    for resampled frame `j`), as the pipeline does for a fault."""
    return [replace(c, follower_frames=tuple(int(to_original[j]) for j in c.follower_frames)) for c in candidates]


def summary(near_misses, limit=MAX_NEAR_MISSES):
    """`diagnostics.near_misses`: the `limit` largest by `abs(magnitude_deg)` (then measure, side, direction, so the
    order is fixed), how many there are and how many are left out."""
    ordered = sorted(near_misses, key=lambda c: (-abs(c.magnitude_deg), c.measure, c.side, c.direction))
    return {"total": len(ordered), "omitted": max(0, len(ordered) - limit),
            "items": [c.to_dict() for c in ordered[:limit]]}


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


def differences(exp_m, fol_m, alignment: Alignment, tolerance_frames=0):
    """Follower − expected per expected frame, along the alignment.

    With a tolerance of k frames, a follower value that falls within the range the expected
    clip covers in frames i−k..i+k counts as a match (diff 0); otherwise the diff is the distance
    to the nearest edge of that range. This absorbs small timing errors on fast-changing
    measures, without hiding an offset that is held.
    """
    j = alignment.exp_to_fol
    out = {}
    # ADR-0015: the foot measures are visited only when both dicts carry them (a pair with usable feet on both sides).
    for name in (*MEASURES, *(n for n in FOOT_MEASURES if n in exp_m and n in fol_m)):
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


def detect(exp_m, fol_m, alignment: Alignment, rules=None, rep_spans=None, fps=None):
    """The faults of a take. `detect_full` without the candidates."""
    return detect_full(exp_m, fol_m, alignment, rules, candidates=False, rep_spans=rep_spans, fps=fps).faults


def detect_full(exp_m, fol_m, alignment: Alignment, rules=None, candidates=True, rep_spans=None, fps=None):
    """`Detection(faults, candidates)`: the faults `detect` returns and, unless `candidates` is False, a `Candidate` for
    every measure, side and direction with a frame past its threshold, each tagged with what became of it.

    `rep_spans` (ADR-0017) is the expected clip's reps as disjoint inclusive frame spans tiling the clip
    (`reps.Segmentation.partition`); persistence is then judged in each rep (`persistence.judge`). None, or one span, is
    a clip judged as one rep, which is what a single-rep example and every rep of a rep-by-rep take are. `fps` is the
    expected clip's frame rate: the floor is a duration (`persistence.floor_frames`), and None reads it as frames at
    the reference rate of 30."""
    rules = rules or load_rules()
    diffs = differences(exp_m, fol_m, alignment, rules.get("tolerance_frames", 0))
    n = len(alignment.exp_to_fol)
    # ADR-0016: rules from `profiles.effective_rules` carry a `profile` holding the unrelaxed config of each measure.
    # Plain rules (fitness) have none, `relaxed` stays empty and everything below is what detection did before profiles.
    profile = rules.get("profile")
    raw, relaxed, seen = [], {}, []
    for name, d in diffs.items():
        g, side = generic(name)
        if name in FOOT_MEASURES and g not in rules["measures"]:
            continue   # ADR-0015: a foot measure has no default threshold; without a rules entry it is computed, not reported
        cfg = {**rules["default"], **rules["measures"].get(g, {})}
        base = cfg if profile is None else profile["baseline"].get(g, cfg)
        sm = _median_filter(d, rules.get("smooth_frames", 1))
        for sign, direction in ((1, "more"), (-1, "less")):
            fault = _fault(name, g, side, direction, sign, d, sm, base, alignment, n, rep_spans, fps=fps)
            cand = _candidate(name, g, side, direction, sign, sm, cfg, alignment, n, rep_spans, fps) if candidates else None
            if cand is not None:   # TICKET-043: the same measure at the config in force (a profile's own), beside its fault
                seen.append((cand, fault))
            if fault is None:
                continue
            raw.append(fault)
            if profile is not None:   # the same fault at the profile's own tolerances; None when it no longer holds
                # It reports the run that overlaps the fitness fault's reported run most, so a mode keeps the headline moment.
                relaxed[id(fault)] = _fault(name, g, side, direction, sign, d, sm, cfg, alignment, n, rep_spans,
                                            fitness_run=fault.expected_frames, fps=fps)
    overlap = rules["default"].get("min_overlap", DEFAULT_MIN_OVERLAP)
    kept, why = _drop_explained(raw, rules.get("explained_by", {}), overlap, rules.get("explained_by_opposite", {}))
    if profile is not None:   # explanation was judged at the baseline; what survives is re-tested at the profile's config
        kept = [r for r in (relaxed[id(f)] for f in kept) if r is not None]
    faults = _merge_sides(kept, overlap)
    return Detection(faults, _tagged(seen, why, faults))


def _candidate(name, g, side, direction, sign, sm, cfg, alignment, n, spans=None, fps=None):
    """The candidate for one measure, side and direction at `cfg`, or None when no frame is past the threshold. Sized
    like a fault: over the runs that persist, else the counted runs, else every frame past the threshold. It points at
    the longest run that persists, else at the longest run of the rep its counted and needed frames describe."""
    thr = cfg["threshold_deg"]
    with np.errstate(invalid="ignore"):
        flags = sign * sm > thr
    over = int(flags.sum())
    if not over:
        return None
    p = judge(flags, cfg, n, spans, fps, name in FOOT_MEASURES)
    s, e = p.longest()
    vals = np.concatenate([sm[a:b + 1] for a, b in (p.kept or p.counted or p.runs)])
    spec = ALL_SPECS[name]
    return Candidate(
        measure=g, side=side, joint=spec.joint, body_part=spec.body_part, direction=direction,
        magnitude_deg=round(float(np.nanmedian(vals)), 1), peak_deg=round(float(vals[np.nanargmax(np.abs(vals))]), 1),
        threshold_deg=thr, expected_frames=(s, e),
        follower_frames=(int(alignment.exp_to_fol[s]), int(alignment.exp_to_fol[e])),
        frames_over=over, counted_frames=p.counted_frames, needed_frames=p.needed_frames,
        min_run_frames=p.min_run)


def _reported_side(cause, faults):
    """The side `cause` is reported on: its own, or `both` when `_merge_sides` joined it with the other side's."""
    return next((f.side for f in faults if f.measure == cause.measure and f.direction == cause.direction
                 and f.side in (cause.side, "both")), cause.side)


def _tagged(seen, why, faults):
    """The candidates of `seen` ((candidate, its baseline fault or None) pairs) with their outcome. Persistence is the
    first test detection makes, then explanation (`why`, from `_drop_explained`); a candidate that fails neither is
    one of the final `faults`, merged or not."""
    for cand, fault in seen:
        if not cand.persists:
            cand.outcome = PERSISTENCE
        elif fault is not None and id(fault) in why:
            cause = why[id(fault)]
            cand.outcome, cand.explained_by = EXPLAINED_BY, (cause.measure, _reported_side(cause, faults), cause.direction)
    return [cand for cand, _ in seen]


def _reported_run(runs, fitness_run):
    """The run a fault reports. Fitness (`fitness_run` None): the longest, the earliest on a tie. A profile fault
    (ADR-0016): the counted run that shares the most frames with the run fitness reports for the same measure, side
    and direction (the longest, then the earliest, among equals), and the longest rule only when none shares a frame.
    The looser config trims the runs, so without this a mode could report a different moment than fitness does."""
    longest = max(runs, key=lambda r: r[1] - r[0])
    if fitness_run is None:
        return longest

    def shared(run):
        return max(0, min(run[1], fitness_run[1]) - max(run[0], fitness_run[0]) + 1)

    best = max(runs, key=lambda r: (shared(r), r[1] - r[0]))
    return best if shared(best) else longest


def _fault(name, g, side, direction, sign, d, sm, cfg, alignment, n, spans=None, fitness_run=None, fps=None):
    thr = cfg["threshold_deg"]
    with np.errstate(invalid="ignore"):
        flags = sign * sm > thr
    runs = judge(flags, cfg, n, spans, fps, name in FOOT_MEASURES).kept
    if not runs:
        return None
    s, e = _reported_run(runs, fitness_run)
    vals = np.concatenate([sm[a:b + 1] for a, b in runs])
    mag = float(np.nanmedian(vals))
    peak = float(vals[np.nanargmax(np.abs(vals))])
    coverage = float(np.concatenate([np.isfinite(d[a:b + 1]) for a, b in runs]).mean())
    margin = min(1.0, (abs(mag) - thr) / thr + 0.5)
    spec = ALL_SPECS[name]
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
    """`(kept faults, why)`: the faults without those that a kept fault explains, and `why`, `{id(dropped fault): the
    kept fault that explains it}` (the largest magnitude when several do). A dropped fault explains nothing, so a chain
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

    def cause_of(i):
        # a cycle in the rules can leave a dropped fault with no kept cause: name the largest listed one then
        named = [faults[j] for j in causes[i] if kept(j)] or [faults[j] for j in causes[i]]
        return max(named, key=lambda c: abs(c.magnitude_deg))

    return ([f for i, f in enumerate(faults) if kept(i)],
            {id(f): cause_of(i) for i, f in enumerate(faults) if not kept(i)})


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
