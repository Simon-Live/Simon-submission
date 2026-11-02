"""Repetition-by-repetition comparison (ADR-0010, docs/specs/part5-fault-analysis.md "Repetitions").

The whole-clip comparison cannot tell a trainer's three slow reps from a follower's eight fast ones:
DTW is limited to a ½x to 2x slope, so the guard refuses a correct take on `timing_corr`. When the
whole-clip guard refuses and either clip holds more than one repetition (`part5.reps`), this module
compares one repetition at a time instead, and since attempt 4 (ADR-0017) it does so whenever the *expected* clip
holds two or more, whatever the whole-clip guard says (`pipeline.run`):

- each follower rep has a reference, an expected rep (`matched_rep`): the one with its own index when the follower has no
  more reps than the example, else the example's first complete rep (the whole clip when it has one);
- each follower rep is resampled to its reference's frame count, then aligned, guarded and
  detected on its own, with the frozen limits, the foot measures included (`_foot_rep`); persistence is judged in the
  reference, which is one rep of the example;
- the take is accepted when a strict majority of the follower reps pass (and at least one);
- a fault is reported once when it is detected in at least half of the accepted reps, placed on the expected
  file's own frames (the reference rep's first frame added to the rep-local ones, `_on_expected_file`); a fault that
  some rep found on both sides is reported once, and the half rule is applied to each side over the reps that found it,
  alone or as part of `both`: on `both` when both sides pass, else on the side that does (`aggregate_faults`);
- a reported fault also says how big it was in each rep that found it (`rep_sizes`, analysis 1.12.0): the occurrences
  the aggregation already keeps, listed rep by rep with the side that rep found, and nothing else is read from them;
- under a profile (ADR-0016) the reps are also detected with the profile's `fitness` rules (`profiles.fitness_rules`),
  that half rule is applied to those too, and only the take-level faults `fitness` also reports, covered in the sense
  of `profiles.covered_by`, are kept. Each rep's faults are covered by construction, but a fault seen on one side in
  some reps and on both in others can pass the half rule under a profile and not under `fitness`;
- near misses (TICKET-043, docs/specs/near-misses.md) live at the take level like the faults: each rep also keeps its
  candidates, and `across_reps` turns them into one near miss per measure, side and direction the take does not report.

`compare` returns `None` when neither clip has more than one rep (nothing new to try). A pair of one-rep clips the
whole-clip guard accepts never gets here, so a single-rep take is analysed exactly as before. The reps together
are bounded like the whole pair (`max_cells`, `TooManyPairs`, `_pairs`).
"""
import copy
import math
from dataclasses import dataclass, field, replace
from statistics import median

import numpy as np

from .align import Alignment, AlignmentError, align
from .detect import FITNESS, REPS, as_both, detect_full, on_file, overlaps_side, reports
from .feet import resampled_series
from .guard import DIFFERENT_MOVEMENT, OK, OK_TEXT, REFUSAL_TEXT, GuardResult, check_movement
from .visibility import measures_of
from .output import fault_to_dict
from .persistence import FLOOR_KEYS
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
    ref_start: int = 0              # the expected file's frame the reference starts at (ADR-0017: it differs by rep)
    measures: tuple | None = None   # (reference measures, rep measures) of a rep that passed: `continued` detects again
    continued: list = field(default_factory=list)    # faults the take reports that this rep shows at `min_fraction` alone


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


def _detected(ref_m, fol_m, alignment, rules, orig, candidates=False, fps=None):
    """`detect_full` on one rep, the follower frames mapped to the file's own: `(faults, candidates)`. `fps` is the
    example's frame rate, which turns the persistence floor into frames."""
    found = detect_full(ref_m, fol_m, alignment, rules, candidates, fps=fps)
    faults = [replace(f, follower_frames=tuple(int(orig[j]) for j in f.follower_frames)) for f in found.faults]
    return faults, on_file(found.candidates, orig)


def matched_rep(k, expected_reps, follower_reps):
    """The expected rep that follower rep `k` is compared with (ADR-0017). A follower with no more reps than the example
    plays the example's sequence, so rep `k` is judged against the example's rep `k`: an example that starts mid-cycle
    has a short first rep, the follower's first rep starts mid-cycle too, and each is compared with the rep it repeats.
    A follower with more reps than the example repeats it, and which rep repeats which is unknown, so every rep is
    compared with the example's first, as ADR-0010 chose."""
    return k if follower_reps <= expected_reps else 0


def _foot_rep(foot, a, b, n):
    """The follower's foot series (ADR-0015, on the expected clock like its joints) for the frames a..b, resampled to
    the reference's `n` frames the way `_resample_rep` does the joints. `{}` for a pair without feet."""
    return resampled_series(foot, lambda stack: _resample_rep(stack, a, b, n))


def _one_rep(index, pos, orig, span, ref, ref_m, rules, vis=None, fitness=None, foot=None, ref_start=0, fps=None):
    """Align, guard and detect one follower rep against the reference. `fitness`, the fitness rules of a profile's
    effective `rules`, makes the rep also detect with those. `foot` is the rep's follower foot series (ADR-0015); the
    reference's are already in `ref_m`, and a foot measure is compared when both carry it. `ref_start` is the expected
    file's frame the reference starts at; `fps` is the example's frame rate (the persistence floor is a duration)."""
    try:
        alignment = align(ref.positions, pos, None if vis is None else vis.align_usable)
    except AlignmentError:  # the rep cannot be aligned at all: it does not pass; any other error is a bug
        return RepResult(index, span, False, None, None, ref, pos, orig, ref_start=ref_start)
    fol_m = {**measures_of(pos, vis), **(foot or {})}
    guard = check_movement(alignment, ref_m, fol_m, rules)
    ok = bool(guard.ok and guard.stats["span_share"] >= MIN_REP_SPAN_SHARE)
    faults, fitness_faults, candidates = [], [], []
    if ok:
        faults, candidates = _detected(ref_m, fol_m, alignment, rules, orig, candidates=True, fps=fps)
        if fitness is not None:
            fitness_faults = _detected(ref_m, fol_m, alignment, fitness, orig, fps=fps)[0]
    return RepResult(index, span, ok, guard, alignment, ref, pos, orig, faults, fitness_faults=fitness_faults,
                     candidates=candidates, ref_start=ref_start, measures=(ref_m, fol_m) if ok else None)


def without_floor(rules):
    """`rules` with both floors (`persistence.FLOOR_KEYS`, the foot and the body one) taken out (0) wherever a config
    carries one: the persistence of a fault that is already reported, which is a share of the rep alone (a profile copies
    the floors into every measure's config and its baseline, so all three are lowered). `rules` itself is not changed."""
    out = copy.deepcopy(rules)
    configs = [out["default"], *out.get("measures", {}).values(), *(out.get("profile") or {}).get("baseline", {}).values()]
    for cfg in configs:
        for key in FLOOR_KEYS:
            if key in cfg:
                cfg[key] = 0
    return out


def continue_reported(reps, kept_keys, rules, fps=None):
    """Count the faults the take reports in every rep that shows them (ADR-0017). A fault starts to count where it
    persists in a rep with the floor, which keeps noise out of the list; once the take reports it, a rep that shows it
    for `min_fraction` of itself, floor or not, shows it in its own window, so a short rep that the floor blinds is not
    scored clean for a fault the follower made in it too (ADR-0013 scores a rep on its own misses). Each such fault is
    put in `RepResult.continued`; the aggregation, `faults[].reps` and the near misses read the strict `faults` only.
    A rep is charged for a fault once: one whose measure and direction the rep already has on an overlapping side (the
    same side, or `both` against either) is not continued, so a fault reported on both sides is not counted again in the
    rep that holds it on one side. The same overlap decides what is continued: a rep's `both` fault is continued when
    the take reports either side of it (recheck N1). `fps` is the example's frame rate."""
    if not kept_keys:
        return
    reported, easy = list(kept_keys), without_floor(rules)
    for r in reps:
        if r.ok:
            found = _detected(*r.measures, r.alignment, easy, r.to_original, fps=fps)[0]
            have = [_fault_key(f) for f in r.faults]
            r.continued = [f for f in found if overlaps_side(reported, _fault_key(f))
                           and not overlaps_side(have, _fault_key(f))]


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


def _once_per_rep(by_side):
    """`by_side` ({side: [(rep, fault)]}) as one occurrence per rep that found the fault on either side: the rep's `both`
    fault, else its one-sided fault with the largest magnitude (the left one on a tie). A rep whose left and right
    faults did not merge in its own detection still found the fault on both sides, and counts once."""
    picked = {r.index: (r, f) for r, f in by_side.get("both", [])}
    for one in ("left", "right"):
        for r, f in by_side.get(one, []):
            best = picked.get(r.index)
            if best is None or (best[1].side != "both" and abs(f.magnitude_deg) > abs(best[1].magnitude_deg)):
                picked[r.index] = (r, f)
    return [picked[i] for i in sorted(picked)]


def _found_on(by_side, side):
    """The sorted indices of the reps that found `side` (left or right) of a fault: on its own, or as part of its `both`."""
    return sorted({r.index for r, _ in by_side.get(side, []) + by_side["both"]})


def _report_on(by_side, accepted):
    """Where a fault that some rep found on `both` sides is reported, the half rule applied to each side on its own
    (recheck N1): each side is counted over the reps that found it, alone or as part of `both`. It is `both` when both
    sides reach `MIN_FAULT_SHARE` of the `accepted` reps, the side that does when only one does, and None when neither."""
    passing = [s for s in ("left", "right") if len(_found_on(by_side, s)) >= MIN_FAULT_SHARE * accepted]
    return "both" if len(passing) == 2 else passing[0] if passing else None


def aggregate_faults(reps, which="faults"):
    """`[(fault, rep_indices, occurrences)]` over the accepted reps: a fault (same measure, side and direction) is
    kept when detected in at least `MIN_FAULT_SHARE` of them, or always when there is a single rep. `rep_indices`
    are the reps the fault was found in. Sorted by size, like `detect`. `which` names the per-rep list read:
    `faults`, or `fitness_faults` for the take-level result `fitness` itself would give.

    A fault on both sides is one fault (pre-freeze review B2). When some rep found a measure and direction on `both`
    sides, the take reports it once, and where is `_report_on`'s: the half rule is applied to each side over the
    reps that found it, alone or as part of `both` (recheck N1), so a side found in under half the reps never rides in
    on the other's `both`. Reported on `both`, it is placed and sized from one occurrence per rep (`_once_per_rep`), the
    first one's side rewritten to `both`; reported on one side, from that side's own occurrences, with `rep_indices` also
    holding the reps that found it as part of `both` (the size of a `both` fault is the two sides' mean, not this one's).
    Without a `both` occurrence each key is judged on its own, as it always was."""
    accepted = [r for r in reps if r.ok]
    groups, family = {}, {}
    for r in accepted:
        for f in getattr(r, which):
            groups.setdefault(_fault_key(f), []).append((r, f))
    for (measure, side, direction), occ in groups.items():
        family.setdefault((measure, direction), {})[side] = occ
    kept = []
    for (measure, side, direction), occ in groups.items():
        by_side = family[(measure, direction)]
        if "both" not in by_side:
            found = [r.index for r, _ in occ] if len(occ) >= MIN_FAULT_SHARE * len(accepted) else None
        elif _report_on(by_side, len(accepted)) != side:
            found = None
        elif side == "both":
            occ = _once_per_rep(by_side)
            found = [r.index for r, _ in occ]
        else:
            found = _found_on(by_side, side)
        if found is not None:
            fault = _aggregate([f for _, f in occ])
            kept.append((as_both(fault) if side == "both" else fault, found, occ))
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
    profile's take-level check dropped it all the same. Expected frames are those the candidates carry: `compare` has
    already moved them onto the expected file's frames (each by the start of its own rep's reference)."""
    need = math.ceil(share * len(per_rep))
    groups = {}
    for index, _, candidates in per_rep:
        for c in candidates:
            groups.setdefault(c.key, []).append((index, c))
    out = []
    for (measure, side, direction), occurrences in groups.items():
        if reports(reported, (measure, side, direction)):
            continue
        found = sum(any((measure, s, direction) in keys for s in (side, "both")) for _, keys, _ in per_rep)   # N1: the reps that found this side, alone or as `both`
        _, best = max(occurrences, key=lambda ic: (ic[1].counted_frames, -ic[0]))
        outcome = best.outcome if not found else REPS if found < need else FITNESS
        out.append(replace(best, outcome=outcome, reps=tuple(i for i, _ in occurrences),
                           found_in_reps=found, needed_reps=need))
    return out


def rep_sizes(fault, indices, occ, reps):
    """`faults[].rep_sizes` (analysis 1.12.0, TICKET-071): the size of `fault` in each of the `indices` reps that found
    it, as `{rep, magnitude_deg, side, body_part}` in rep order. The size is the rep's own occurrence (`occ`, the
    one `aggregate_faults` sized the fault from, signed like `magnitude_deg`) and `side` is the side that rep found it
    on. A fault reported on one side also counts the reps that found it as part of `both` (N1); those reps are not in
    `occ`, so their size is the rep's own `both` fault (the two sides' mean, side `both`). `reps` are the take's reps."""
    own = {r.index: f for r, f in occ}
    both_sides = {r.index: f for r in reps if r.ok for f in r.faults
                  if f.side == "both" and (f.measure, f.direction) == (fault.measure, fault.direction)}
    sized = [own[i] if i in own else both_sides[i] for i in indices]
    return [{"rep": i, "magnitude_deg": f.magnitude_deg, "side": f.side, "body_part": f.body_part}
            for i, f in zip(indices, sized, strict=True)]


def _times(kept, fol, fault_times, reps):
    """The time fields of each aggregated fault: the first occurrence's place on the follower's file
    clock, the median lateral offset, the reps it was found in and its size in each of them (`rep_sizes`)."""
    out = []
    for fault, indices, occ in kept:
        per = [(fault_times(f, r.expected, fol, r.follower_positions, r.alignment, r.to_original)) for r, f in occ]
        times = dict(per[0])
        laterals = [t["lateral_m"] for t in per if t.get("lateral_m") is not None]
        if laterals:
            times["lateral_m"] = float(median(laterals))
        times["reps"] = indices
        times["rep_sizes"] = rep_sizes(fault, indices, occ, reps)
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


def _pairs(expected_spans, follower_reps, follower_frames):
    """`(frame pairs, widest reference)` the alignments of a rep-by-rep take need together. Each follower rep is
    resampled to its reference's frame count and aligned against it, so a rep costs reference frames squared; a lone
    follower segment is aligned whole, follower frames times its reference's."""
    lengths = [b - a + 1 for a, b in (expected_spans[matched_rep(k, len(expected_spans), follower_reps)]
                                      for k in range(follower_reps))]
    if follower_reps == 1:
        return follower_frames * lengths[0], lengths[0]
    return sum(n * n for n in lengths), max(lengths)


def compare(exp, fol, exp_m, fol_positions, to_original, fps, rules, fault_times, vis=None, max_cells=None,
            expected_segmentation=None, foot_exp=None, foot_fol=None):
    """The repetition-by-repetition comparison, or `None` when neither clip has more than one rep.

    `fol_positions` is the follower on the expected clip's clock and `to_original` maps its frames to the
    follower file's. `fault_times` is `pipeline._fault_times` (passed in to keep the modules apart).
    Each follower rep is compared with the expected rep that matches it (`matched_rep`, ADR-0017), resampled to that
    rep's frame count. `expected_segmentation` is the expected clip's `reps.segment` when the caller has it already;
    `foot_exp` and `foot_fol` are the foot series of the pair (`pipeline._foot_series`: the expected on its own frames,
    the follower on the expected clock), empty for a pair without usable feet, and are cut and resampled like the
    joints so a foot measure is compared rep by rep too.
    `max_cells` bounds the frame pairs all the alignments together need (`_pairs`); `TooManyPairs` before any is
    aligned. The faults returned are placed on the expected file's frames (`_on_expected_file`); the per-rep ones stay
    local."""
    fol_m = measures_of(fol_positions, vis)
    es = expected_segmentation or segment(exp_m, fps)
    fs = segment(fol_m, fps, prefer=(es.measure, es.bound) if es.bound else None)
    if es.reps == 1 and fs.reps == 1:
        return None
    pairs, widest = _pairs(es.spans, fs.reps, len(fol_positions))
    if max_cells is not None and pairs > max_cells:
        raise TooManyPairs(math.ceil(pairs / widest), widest)
    foot_exp, foot_fol = foot_exp or {}, foot_fol or {}
    fitness = fitness_rules(rules)
    under_profile = fitness is not rules   # ADR-0016: only a profile's rules differ from their fitness rules
    references, reps = {}, []
    for k, (a, b) in enumerate(fs.spans):
        j = matched_rep(k, es.reps, fs.reps)
        if j not in references:
            references[j] = _reference(exp, {**exp_m, **foot_exp}, es.spans[j])
        ref, ref_m = references[j]
        if fs.reps == 1:  # one follower segment: the whole take, as the whole-clip comparison saw it
            pos, orig, foot = fol_positions, np.asarray(to_original), foot_fol
        else:
            pos, idx = _resample_rep(fol_positions, a, b, ref.n_frames)
            orig = np.asarray(to_original)[idx]
            foot = _foot_rep(foot_fol, a, b, ref.n_frames)
        reps.append(_one_rep(k, pos, orig, (int(orig[0]), int(orig[-1])), ref, ref_m, rules, vis,
                             fitness if under_profile else None, foot, es.spans[j][0], fps))
    guard = _verdict(reps)
    kept = aggregate_faults(reps) if guard.ok else []
    if under_profile:   # a profile never reports a take-level fault that fitness does not (the fitness path is untouched)
        kept = only_what_fitness_reports(kept, reps)
    kept_keys = {_fault_key(f) for f, _, _ in kept}
    continue_reported(reps, kept_keys, rules, fps)
    for r in reps:
        # a rep's fault is the take's when the take reports it on an overlapping side (aggregate_faults): the rep's
        # one-sided fault under a `both` report, and the rep's `both` fault under a report of either of its sides
        mine = [f for f in r.faults if overlaps_side(list(kept_keys), _fault_key(f))]
        r.analysis = {"status": {"code": OK if r.ok else DIFFERENT_MOVEMENT},
                      "faults": [fault_to_dict(f) for f in mine]}
    # onto the expected file, like a fault: each candidate sits in its own rep's reference
    per_rep = [(r.index, [_fault_key(f) for f in r.faults],
                [replace(c, expected_frames=tuple(f + r.ref_start for f in c.expected_frames)) for c in r.candidates])
               for r in reps if r.ok]
    near = across_reps(per_rep, list(kept_keys)) if guard.ok else []
    # a fault sits where its first occurrence was found, in the reference of the rep that found it
    return RepRun(guard, reps, [_on_expected_file(f, occ[0][0].ref_start, exp.n_frames) for f, _, occ in kept],
                  _times(kept, fol, fault_times, reps), es.spans[0], es, fs, near)
