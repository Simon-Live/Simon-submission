"""Repetition-by-repetition comparison (ADR-0010, docs/specs/part5-fault-analysis.md "Repetitions").

The whole-clip comparison cannot tell a trainer's three slow reps from a follower's eight fast ones:
DTW is limited to a ½x to 2x slope, so the guard refuses a correct take on `timing_corr`. When the
whole-clip guard refuses and either clip holds more than one repetition (`part5.reps`), this module
compares one repetition at a time instead:

- the expected reference is the expected clip's first complete rep (the whole clip when it has one);
- each follower rep is resampled to the reference's frame count, then aligned, guarded and
  detected on its own, with the frozen limits;
- the take is accepted when a strict majority of the follower reps pass (and at least one);
- a fault is reported once when it is detected in at least half of the accepted reps.

`compare` returns `None` when neither clip has more than one rep (nothing new to try). A pair the
whole-clip guard accepts never gets here, so a single-rep take is analysed exactly as before.
"""
from dataclasses import dataclass, field, replace
from statistics import median

import numpy as np

from .align import Alignment, align
from .detect import detect
from .guard import DIFFERENT_MOVEMENT, OK, OK_TEXT, REFUSAL_TEXT, GuardResult, check_movement
from .measures import compute
from .output import fault_to_dict
from .reps import Segmentation, segment

MIN_FAULT_SHARE = 0.5   # a fault counts when detected in at least this share of the accepted reps
# A rep passes only when the matched stretch covers most of it. Against a short reference, the open ends
# of the alignment would otherwise let any long take match one lucky stretch (a dance against a squat rep).
MIN_REP_SPAN_SHARE = 0.6


@dataclass
class RepResult:
    """One follower repetition compared with the expected reference.

    `expected` is the reference clip, `follower_positions` the rep resampled to the reference's frame
    count, `to_original[j]` the follower file's frame shown at rep frame `j`, `alignment` indexes the rep
    frames. `faults` have their follower frames mapped to the file's own. `analysis` is the small
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


def _one_rep(index, pos, orig, span, ref, ref_m, rules):
    """Align, guard and detect one follower rep against the reference."""
    try:
        alignment = align(ref.positions, pos)
    except ValueError:  # the rep cannot be aligned at all: it does not pass
        return RepResult(index, span, False, None, None, ref, pos, orig)
    fol_m = compute(pos)
    guard = check_movement(alignment, ref_m, fol_m, rules)
    ok = bool(guard.ok and guard.stats["span_share"] >= MIN_REP_SPAN_SHARE)
    faults = []
    if ok:
        faults = [replace(f, follower_frames=tuple(int(orig[j]) for j in f.follower_frames))
                  for f in detect(ref_m, fol_m, alignment, rules)]
    return RepResult(index, span, ok, guard, alignment, ref, pos, orig, faults)


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


def aggregate_faults(reps):
    """`(faults, rep_lists)` over the accepted reps: a fault (same measure, side and direction) is kept
    when detected in at least `MIN_FAULT_SHARE` of them, or always when there is a single rep.
    `rep_lists[i]` holds the indices of the reps fault `i` was found in. Sorted by size, like `detect`."""
    accepted = [r for r in reps if r.ok]
    groups = {}
    for r in accepted:
        for f in r.faults:
            groups.setdefault(_fault_key(f), []).append((r, f))
    kept = [(_aggregate([f for _, f in occ]), [r.index for r, _ in occ], occ)
            for occ in groups.values() if len(occ) >= MIN_FAULT_SHARE * len(accepted)]
    kept.sort(key=lambda k: -abs(k[0].magnitude_deg))
    return kept


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


def compare(exp, fol, exp_m, fol_positions, to_original, fps, rules, fault_times):
    """The repetition-by-repetition comparison, or `None` when neither clip has more than one rep.

    `fol_positions` is the follower on the expected clip's clock and `to_original` maps its frames to the
    follower file's. `fault_times` is `pipeline._fault_times` (passed in to keep the modules apart)."""
    fol_m = compute(fol_positions)
    es = segment(exp_m, fps)
    fs = segment(fol_m, fps, prefer=(es.measure, es.bound) if es.bound else None)
    if es.reps == 1 and fs.reps == 1:
        return None
    ref, ref_m = _reference(exp, exp_m, es.spans[0])
    n = ref.n_frames
    reps = []
    for k, (a, b) in enumerate(fs.spans):
        if fs.reps == 1:  # one follower segment: the whole take, as the whole-clip comparison saw it
            pos, orig = fol_positions, np.asarray(to_original)
        else:
            pos, idx = _resample_rep(fol_positions, a, b, n)
            orig = np.asarray(to_original)[idx]
        reps.append(_one_rep(k, pos, orig, (int(orig[0]), int(orig[-1])), ref, ref_m, rules))
    guard = _verdict(reps)
    kept = aggregate_faults(reps) if guard.ok else []
    kept_keys = {_fault_key(f) for f, _, _ in kept}
    for r in reps:
        mine = [f for f in r.faults if _fault_key(f) in kept_keys]
        r.analysis = {"status": {"code": OK if r.ok else DIFFERENT_MOVEMENT},
                      "faults": [fault_to_dict(f) for f in mine]}
    return RepRun(guard, reps, [f for f, _, _ in kept], _times(kept, fol, fault_times), es.spans[0], es, fs)
