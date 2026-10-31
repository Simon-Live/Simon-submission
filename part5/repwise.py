"""Repetition-by-repetition comparison (ADR-0010, docs/specs/part5-fault-analysis.md "Repetitions").

The whole-clip comparison cannot tell a trainer's three slow reps from a follower's eight fast ones:
DTW is limited to a ½x to 2x slope, so the guard refuses a correct take on `timing_corr`. When the
whole-clip guard refuses and either clip holds more than one repetition (`part5.reps`), this module
compares one repetition at a time instead:

- the expected reference is the expected clip's first complete rep (the whole clip when it has one);
- each follower rep is resampled to the reference's frame count, then aligned, guarded and
  detected on its own, with the frozen limits;
- the take is accepted when a strict majority of the follower reps pass (and at least one);
- a fault is reported once when it is detected in at least half of the accepted reps, placed on the expected
  file's own frames (the reference rep's first frame added to the rep-local ones, `_on_expected_file`);
- under a profile (ADR-0016) the reps are also detected with the profile's `fitness` rules (`profiles.fitness_rules`),
  that half rule is applied to those too, and only the take-level faults `fitness` also reports, covered in the sense
  of `profiles.covered_by`, are kept. Each rep's faults are covered by construction, but a fault seen on one side in
  some reps and on both in others can pass the half rule under a profile and not under `fitness`;
- near misses (TICKET-043, docs/specs/near-misses.md) live at the take level like the faults: each rep also keeps its
  candidates, and `across_reps` turns them into one near miss per measure, side and direction the take does not report.

`compare` returns `None` when neither clip has more than one rep (nothing new to try). A pair the
whole-clip guard accepts never gets here, so a single-rep take is analysed exactly as before. The reps together
are bounded like the whole pair (`max_cells`, `TooManyPairs`).
"""
import math
from dataclasses import dataclass, field, replace
from statistics import median

import numpy as np

from .align import Alignment, AlignmentError, align
from .detect import FITNESS, REPS, detect_full, on_file, reports
from .guard import DIFFERENT_MOVEMENT, OK, OK_TEXT, REFUSAL_TEXT, GuardResult, check_movement
from .visibility import measures_of
from .output import fault_to_dict
from .profiles import covered_by, fitness_rules
from .reps import Segmentation, segment

MIN_FAULT_SHARE = 0.5   # a fault counts when detected in at least this share of the accepted reps
# A rep passes only when the matched stretch covers most of it. Against a short reference, the open ends
# of the alignment would otherwise let any long take match one lucky stretch (a dance against a squat rep).
MIN_REP_SPAN_SHARE = 0.6


class TooManyPairs(ValueError):
    """The reps together would align more expected x follower frame pairs than `max_cells` allows.

    `follower_frames` is how many follower frames are aligned in total and `expected_frames` the reference's
    length, so the pairs are their product. `part5.pipeline` turns it into the plain `AnalysisError`."""

    def __init__(self, follower_frames, expected_frames):
        super().__init__(f"{follower_frames} follower frames against {expected_frames} expected frames")
        self.follower_frames, self.expected_frames = follower_frames, expected_frames


@dataclass
class RepResult:
    """One follower repetition compared with the expected reference.

    `expected` is the reference clip, `follower_positions` the rep resampled to the reference's frame
    count, `to_original[j]` the follower file's frame shown at rep frame `j`, `alignment` indexes the rep
    frames. `faults` have their follower frames mapped to the file's own. `fitness_faults` are the same rep's faults
    under the `fitness` rules, filled only for a profile other than fitness. `analysis` is the small
    `{status, faults}` document the score reads (only the faults the take reports).
    """
    index: int
    span: tuple                     # follower file frames, inclusive
    ok: bool
    guard: GuardResult | None
    alignment: Alignment | None
    expected: object
    follower_positions: np.ndarray
    to_original: np.ndarray
    faults: list = field(default_factory=list)
    analysis: dict = field(default_factory=dict)
    fitness_faults: list = field(default_factory=list)
    candidates: list = field(default_factory=list)   # the rep's `detect.Candidate`s, reported ones included (TICKET-043)


@dataclass
class RepRun:
    """What the repetition comparison found: the reps, the take's verdict and its aggregated faults."""
    guard: GuardResult              # the take's verdict; stats are medians over the reps
    reps: list
    faults: list                    # aggregated Fault objects, follower frames on the file's clock
    times: list                     # one `fault_to_dict` times entry per fault
    expected_span: tuple            # the reference, in expected frames
    expected_segmentation: Segmentation
    follower_segmentation: Segmentation
    near_misses: list = field(default_factory=list)   # take-level `detect.Candidate`s on the expected file's frames


def _resample_rep(positions, a, b, n):
    """The frames a..b (inclusive) of `positions` linearly resampled to `n` frames; a joint missing in
    either neighbour stays missing. Returns the positions and the nearest source frame per new frame."""
    idx = np.linspace(a, b, n)
    lo = np.floor(idx).astype(int)
    hi = np.minimum(lo + 1, len(positions) - 1)
    w = (idx - lo)[:, None, None]
    out = positions[lo] * (1 - w) + positions[hi] * w
    exact = np.isclose(w[:, 0, 0], 0.0)
    out[exact] = positions[lo[exact]]
    return out, np.rint(idx).astype(int)


def _fault_key(f):
    return f.measure, f.side, f.direction


def _reference(exp, exp_m, span):
    a, b = span
    clip = replace(exp, t=exp.t[a:b + 1], positions=exp.positions[a:b + 1], mask=exp.mask[a:b + 1],
                   interpolated=exp.interpolated[a:b + 1])
    return clip, {k: np.asarray(v)[a:b + 1] for k, v in exp_m.items()}


def _detected(ref_m, fol_m, alignment, rules, orig, candidates=False):
    """`detect_full` on one rep, the follower frames mapped to the file's own: `(faults, candidates)`."""
    found = detect_full(ref_m, fol_m, alignment, rules, candidates)
    faults = [replace(f, follower_frames=tuple(int(orig[j]) for j in f.follower_frames)) for f in found.faults]
    return faults, on_file(found.candidates, orig)


def _one_rep(index, pos, orig, span, ref, ref_m, rules, vis=None, fitness=None):
    """Align, guard and detect one follower rep against the reference. `fitness`, the fitness rules of a profile's
    effective `rules`, makes the rep also detect with those."""
    try:
        alignment = align(ref.positions, pos, None if vis is None else vis.align_usable)
    except AlignmentError:  # the rep cannot be aligned at all: it does not pass; any other error is a bug
        return RepResult(index, span, False, None, None, ref, pos, orig)
    fol_m = measures_of(pos, vis)
    guard = check_movement(alignment, ref_m, fol_m, rules)
    ok = bool(guard.ok and guard.stats["span_share"] >= MIN_REP_SPAN_SHARE)
    faults, fitness_faults, candidates = [], [], []
    if ok:
        faults, candidates = _detected(ref_m, fol_m, alignment, rules, orig, candidates=True)
        if fitness is not None:
            fitness_faults = _detected(ref_m, fol_m, alignment, fitness, orig)[0]
    return RepResult(index, span, ok, guard, alignment, ref, pos, orig, faults, fitness_faults=fitness_faults,
                     candidates=candidates)


def _aggregate(occurrences):
    """One Fault from the same fault found in several reps: the first occurrence's place, the median
    magnitude, the largest peak, the median coverage and confidence."""
    first = occurrences[0]
    peaks = [f.peak_deg for f in occurrences]
    return replace(first,
                   magnitude_deg=round(float(median(f.magnitude_deg for f in occurrences)), 1),
                   peak_deg=max(peaks, key=abs),
                   coverage=round(float(median(f.coverage for f in occurrences)), 3),
                   confidence=round(float(median(f.confidence for f in occurrences)), 3))


def aggregate_faults(reps, which="faults"):
    """`[(fault, rep_indices, occurrences)]` over the accepted reps: a fault (same measure, side and direction) is
    kept when detected in at least `MIN_FAULT_SHARE` of them, or always when there is a single rep. `rep_indices`
    are the reps the fault was found in. Sorted by size, like `detect`. `which` names the per-rep list read:
    `faults`, or `fitness_faults` for the take-level result `fitness` itself would give."""
    accepted = [r for r in reps if r.ok]
    groups = {}
    for r in accepted:
        for f in getattr(r, which):
            groups.setdefault(_fault_key(f), []).append((r, f))
    kept = [(_aggregate([f for _, f in occ]), [r.index for r, _ in occ], occ)
            for occ in groups.values() if len(occ) >= MIN_FAULT_SHARE * len(accepted)]
    kept.sort(key=lambda k: -abs(k[0].magnitude_deg))
    return kept


def only_what_fitness_reports(kept, reps):
    """`kept` (a profile's aggregated faults) without those `fitness` does not report for the same take: the half
    rule on each rep's `fitness_faults` gives the take's fitness faults, and a kept fault stays when it is covered
    by them (`profiles.covered_by`). The reps' own faults are covered by construction (`detect`); this closes the
    one gap left, a fault that is split over sides differently in different reps."""
    reported = [_fault_key(f) for f, _, _ in aggregate_faults(reps, "fitness_faults")]
    return [k for k in kept if covered_by(_fault_key(k[0]), reported)]


def across_reps(per_rep, reported, share=MIN_FAULT_SHARE):
    """The near misses of a take compared rep by rep (TICKET-043): one per measure, side and direction that crossed its
    threshold in an accepted rep and that the take does not report.

    `per_rep` is `[(rep index, [(measure, side, direction) of the rep's faults], [the rep's Candidate])]` for the
    accepted reps and `reported` the keys of the faults the take reports. Each near miss is the record of the rep where
    the candidate came closest to being reported (the most counted frames, the earliest rep on a tie), with `reps`
    the reps it crossed the threshold in. Its reason is that rep's when no rep reported it; `reps` when some did but
    fewer than half of the accepted reps (`found_in_reps` against `needed_reps`); `fitness` when half or more did and a
    profile's take-level check dropped it all the same. Expected frames stay the rep's own: the caller moves them."""
    need = math.ceil(share * len(per_rep))
    groups = {}
    for index, _, candidates in per_rep:
        for c in candidates:
            groups.setdefault(c.key, []).append((index, c))
    out = []
    for (measure, side, direction), occurrences in groups.items():
        if reports(reported, (measure, side, direction)):
            continue
        found = max(sum((measure, s, direction) in keys for _, keys, _ in per_rep) for s in {side, "both"})
        _, best = max(occurrences, key=lambda ic: (ic[1].counted_frames, -ic[0]))
        outcome = best.outcome if not found else REPS if found < need else FITNESS
        out.append(replace(best, outcome=outcome, reps=tuple(i for i, _ in occurrences),
                           found_in_reps=found, needed_reps=need))
    return out


def _times(kept, fol, fault_times):
    """The time fields of each aggregated fault: the first occurrence's place on the follower's file
    clock, the median lateral offset, and the reps it was found in."""
    out = []
    for fault, indices, occ in kept:
        per = [(fault_times(f, r.expected, fol, r.follower_positions, r.alignment, r.to_original)) for r, f in occ]
        times = dict(per[0])
        laterals = [t["lateral_m"] for t in per if t.get("lateral_m") is not None]
        if laterals:
            times["lateral_m"] = float(median(laterals))
        times["reps"] = indices
        out.append(times)
    return out


def _verdict(reps):
    """The take's guard result: accepted when a strict majority of reps pass (and one at least); the
    statistics are medians over the reps that could be aligned."""
    passed = sum(r.ok for r in reps)
    ok = bool(passed >= 1 and 2 * passed > len(reps))
    stats = {}
    for key in ("residual", "timing_corr", "span_share"):
        vals = [r.guard.stats[key] for r in reps if r.guard is not None and np.isfinite(r.guard.stats[key])]
        stats[key] = float(median(vals)) if vals else float("nan")
    return GuardResult(ok, OK if ok else DIFFERENT_MOVEMENT, OK_TEXT if ok else REFUSAL_TEXT, stats)


def rep_entries(reps, fol):
    """`diagnostics.guard.reps`: per follower rep its span on the file's clock, its numbers and its verdict."""
    def num(r, key):
        v = None if r.guard is None else r.guard.stats[key]
        return None if v is None or not np.isfinite(v) else round(float(v), 4)

    return [{"span_s": [round(float(fol.t[r.span[0]]), 3), round(float(fol.t[r.span[1]]), 3)],
             "residual": num(r, "residual"), "timing_corr": num(r, "timing_corr"), "ok": bool(r.ok)}
            for r in reps]


def reference_entry(run, exp, fps):
    a, b = run.expected_span
    es = run.expected_segmentation
    return {"kind": "first_rep" if es.reps > 1 else "whole", "frames": [int(a), int(b)],
            "span_s": [round(float(exp.t[a]), 3), round(float(exp.t[b]), 3)],
            "expected_reps": es.reps, "follower_reps": run.follower_segmentation.reps,
            "measure": es.measure}


def _on_expected_file(fault, start, n_file):
    """`fault`, found against the reference rep that starts at expected frame `start`, placed on the expected
    file's own frames: `expected_frames` and `runs` shifted by `start`, `phase` the fraction of the whole
    expected file (frame / (n_file - 1), as `detect` computes it for a whole-clip comparison)."""
    def shift(run):
        return run[0] + start, run[1] + start

    frames = shift(fault.expected_frames)
    last = max(n_file - 1, 1)
    return replace(fault, expected_frames=frames, runs=tuple(shift(r) for r in fault.runs),
                   phase=tuple(round(f / last, 3) for f in frames))


def compare(exp, fol, exp_m, fol_positions, to_original, fps, rules, fault_times, vis=None, max_cells=None):
    """The repetition-by-repetition comparison, or `None` when neither clip has more than one rep.

    `fol_positions` is the follower on the expected clip's clock and `to_original` maps its frames to the
    follower file's. `fault_times` is `pipeline._fault_times` (passed in to keep the modules apart).
    `max_cells` bounds the frame pairs all the alignments together need (each rep is aligned against the
    whole reference, so reps x reference frames squared); `TooManyPairs` before any is aligned. The faults
    returned are placed on the expected file's frames (`_on_expected_file`); the per-rep ones stay local."""
    fol_m = measures_of(fol_positions, vis)
    es = segment(exp_m, fps)
    fs = segment(fol_m, fps, prefer=(es.measure, es.bound) if es.bound else None)
    if es.reps == 1 and fs.reps == 1:
        return None
    ref, ref_m = _reference(exp, exp_m, es.spans[0])
    n = ref.n_frames
    follower_frames = len(fol_positions) if fs.reps == 1 else fs.reps * n   # a lone segment is aligned whole
    if max_cells is not None and follower_frames * n > max_cells:
        raise TooManyPairs(follower_frames, n)
    fitness = fitness_rules(rules)
    under_profile = fitness is not rules   # ADR-0016: only a profile's rules differ from their fitness rules
    reps = []
    for k, (a, b) in enumerate(fs.spans):
        if fs.reps == 1:  # one follower segment: the whole take, as the whole-clip comparison saw it
            pos, orig = fol_positions, np.asarray(to_original)
        else:
            pos, idx = _resample_rep(fol_positions, a, b, n)
            orig = np.asarray(to_original)[idx]
        reps.append(_one_rep(k, pos, orig, (int(orig[0]), int(orig[-1])), ref, ref_m, rules, vis,
                             fitness if under_profile else None))
    guard = _verdict(reps)
    kept = aggregate_faults(reps) if guard.ok else []
    if under_profile:   # a profile never reports a take-level fault that fitness does not (the fitness path is untouched)
        kept = only_what_fitness_reports(kept, reps)
    kept_keys = {_fault_key(f) for f, _, _ in kept}
    for r in reps:
        mine = [f for f in r.faults if _fault_key(f) in kept_keys]
        r.analysis = {"status": {"code": OK if r.ok else DIFFERENT_MOVEMENT},
                      "faults": [fault_to_dict(f) for f in mine]}
    start = es.spans[0][0]
    per_rep = [(r.index, [_fault_key(f) for f in r.faults], r.candidates) for r in reps if r.ok]
    near = [replace(c, expected_frames=tuple(f + start for f in c.expected_frames))   # onto the expected file, like a fault
            for c in across_reps(per_rep, list(kept_keys))] if guard.ok else []
    return RepRun(guard, reps, [_on_expected_file(f, start, exp.n_frames) for f, _, _ in kept],
                  _times(kept, fol, fault_times), es.spans[0], es, fs, near)
