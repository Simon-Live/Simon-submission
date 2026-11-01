"""Movement guard: tell a take that is not the expected movement at all (ADR-0004, ADR-0012).

DTW always finds a closest phase, so cat-cow yoga against the squat still yields faults. Two
statistics from the alignment tell a different movement from a sloppy copy of the right one:

- `residual`: the mean capped z cost per path cell (`Alignment.residual`), how far the
  follower's pose is from the expected pose along the best path;
- `timing_corr`: the median, over the measures that carry timing, of the Pearson correlation
  between the expected series and the follower series sampled along the path, so a follower
  that bends when the example straightens scores low even if the poses are near.

A take is a low match (analysed all the same, ADR-0012, with a warning and grade F) when `residual` is above `guard.max_residual` or `timing_corr` is below
`guard.min_timing_corr` (both in `rules.json`). `span_share` is reported, never a reason for a low match.
"""
from dataclasses import dataclass

import numpy as np

OK, DIFFERENT_MOVEMENT = "ok", "different_movement"   # DIFFERENT_MOVEMENT: the guard verdict; no longer a status code (ADR-0012)
LOW_MATCH, NO_USABLE_MEASURES = "low_match", "no_usable_measures"   # warning codes (ADR-0012)
MOVING_PART_OUT_OF_FRAME = "moving_part_out_of_frame"   # ADR-0011: the part the example moves is not in frame
NOT_ENOUGH_VISIBLE = "not_enough_visible"   # ADR-0011: too little of the body in frame to compare
OK_TEXT = "Compared with the expected movement."
# status.text of a take that was compared with a warning (ADR-0012 note): status.code stays "ok", the text names the cap.
OK_ONE_WARNING_TEXT = "Compared with the expected movement, with a warning that caps the grade at F."
OK_MANY_WARNINGS_TEXT = "Compared with the expected movement, with {n} warnings that cap the grade at F."
REFUSAL_TEXT = ("This take doesn't closely match the trainer's movement, so the grade is capped at F. "
                "Check that you picked the right movement and that the whole movement is in the take.")
NO_USABLE_TEXT = ("Nothing in this take could be compared with the example, so the grade is F. "
                  "Make sure you are in frame and the whole movement is in the take.")
MIN_CORR_FRAMES = 3     # fewer measurable frames than this give no correlation
FLAT = 1e-9             # a series with a smaller spread is constant


@dataclass
class GuardResult:
    ok: bool
    code: str       # "ok" or "different_movement"
    text: str       # the status text for the analysis
    stats: dict     # residual, timing_corr, span_share (unrounded; timing_corr may be NaN)


def _correlation(expected, follower):
    """Pearson correlation of two series over the frames where both exist, or None when it
    is undefined (too few frames, or either series constant)."""
    ok = np.isfinite(expected) & np.isfinite(follower)
    if ok.sum() < MIN_CORR_FRAMES:
        return None
    e, f = expected[ok], follower[ok]
    if np.std(e) < FLAT or np.std(f) < FLAT:
        return None
    return float(np.corrcoef(e, f)[0, 1])


def _timing_corr(alignment, exp_measures, fol_measures):
    """Median correlation over the timing measures; NaN when none has one."""
    corrs = [_correlation(np.asarray(exp_measures[n], float),
                          np.asarray(fol_measures[n], float)[alignment.exp_to_fol])
             for n in alignment.measures]
    corrs = [c for c in corrs if c is not None]
    return float(np.median(corrs)) if corrs else float("nan")


def _span_share(alignment):
    start, end = alignment.follower_span
    return (end - start + 1) / len(alignment.fol_phase)


def movement_stats(alignment, exp_measures, fol_measures):
    """The guard's three statistics for one aligned take (follower on the expected clock)."""
    return {"residual": float(alignment.residual),
            "timing_corr": _timing_corr(alignment, exp_measures, fol_measures),
            "span_share": float(_span_share(alignment))}


def check_movement(alignment, exp_measures, fol_measures, rules):
    """Refuse when the residual is above `guard.max_residual` or the timing correlation is below
    `guard.min_timing_corr`. A take with no measurable timing correlation (nothing moved along
    the path) cannot show it is the expected movement, so it is refused too."""
    stats = movement_stats(alignment, exp_measures, fol_measures)
    limits = rules["guard"]
    ok = bool(stats["residual"] <= limits["max_residual"]
              and stats["timing_corr"] >= limits["min_timing_corr"])
    return GuardResult(ok, OK if ok else DIFFERENT_MOVEMENT, OK_TEXT if ok else REFUSAL_TEXT, stats)


def diagnostics(result, rules):
    """`diagnostics.guard` for the analysis: the statistics (rounded, a missing timing
    correlation left out because JSON has no NaN) and the two limits in force."""
    out = {k: round(v, 4) for k, v in result.stats.items() if np.isfinite(v)}
    out["limits"] = {k: rules["guard"][k] for k in ("max_residual", "min_timing_corr")}
    return out
