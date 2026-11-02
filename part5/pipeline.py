"""The whole analysis for one follower take: load → normalise → align → guard → measures → detect → words.

`analyse` returns a validated `simon.analysis.v1` document (see docs/schemas.md) without
writing anything, so the CLI, `make check-5` and the example script share one code path.
"""
from dataclasses import dataclass, field, replace
from pathlib import Path

import numpy as np

from .align import ALIGN_MEASURES, Alignment, AlignmentError, align, diagonal_alignment
from .detect import detect_full, load_rules, on_file, summary
from .feet import jitter_limits, load_side, pair_of, resampled_series
from .guard import GuardResult, check_movement
from .guard import diagnostics as guard_diagnostics
from .insights import insights_of
from .io import Clip, load_clip, parse_clip
from .joints_map import fault_joints
from .lateral import lateral_m
from .normalise import normalise
from .output import build_analysis, validate_analysis
from . import profiles
from .phrasing import BACKENDS, phrase
from .quality import assess as assess_quality   # ADR-0021: the block is reported only
from .quality import read_signals, shown_joints
from .repwise import RepRun, TooManyPairs, compare, rep_entries, reference_entry
from .reps import segment
from .guard import (LOW_MATCH, MOVING_PART_OUT_OF_FRAME, NO_USABLE_MEASURES, NO_USABLE_TEXT, NOT_ENOUGH_VISIBLE, OK,
                    OK_MANY_WARNINGS_TEXT, OK_ONE_WARNING_TEXT, OK_TEXT, REFUSAL_TEXT)
from .visibility import (NOT_ENOUGH_TEXT, clip_usable, hide_unseen, load_conf, measures_of, moving_check,
                         moving_text, resolve, usable_from_conf)

# On the dummy takes the matched span always covers ≥76% of the follower clip. Much less than
# that usually means a follower slower than ½x, which aligns to a subsegment (see align.dtw).
MIN_SPAN_SHARE = 0.6
# Below this share of usable measure values a take is mostly missing joints, and "no faults"
# would only mean "nothing could be measured". The dummy takes are all at 100%.
MIN_AVAILABLE = 0.5
# Frame rates closer than this are treated as equal; otherwise the follower is resampled.
FPS_TOLERANCE = 0.01
# Work is bounded before the follower is resampled (docs/specs/staging.md): at most this many
# frames per clip once on the expected clip's clock, and no expected clip faster than MAX_FPS.
MAX_FRAMES = 6000
MAX_FPS = 240
# The alignment builds expected x follower cost arrays per timing measure, so the pair is bounded
# too: 4,000,000 cells (about 2000 x 2000 frames) keeps one analysis near 1 GB at its peak.
MAX_CELLS = 4_000_000
# Why `diagnostics.feet` lists no compared measure when the take could not be aligned (ADR-0015).
UNALIGNED_REASON = "the take could not be aligned, so nothing was compared"


PHRASING_BACKENDS = tuple(BACKENDS)
WARNING_ORDER = (LOW_MATCH, MOVING_PART_OUT_OF_FRAME, NOT_ENOUGH_VISIBLE, NO_USABLE_MEASURES)


class AnalysisError(ValueError):
    """The takes loaded but can't be compared (e.g. the follower is far too fast)."""


@dataclass
class PipelineResult:
    """One analysis with what the replay needs: the normalised clips and the alignment.

    `follower` is the follower clip on its own frames; `follower_positions` is it resampled onto
    the expected clock (what was aligned), and `to_original[j]` is the follower file's frame for
    resampled frame `j`. `alignment` indexes the resampled frames. `guard` is the movement
    guard's verdict (None when the take could not be aligned, ADR-0012). `vis` is the pair's `Visibility`
    (ADR-0011), which the score needs to leave out the measures the camera did not see. `foot_expected` is the
    trainer's foot series the pair was compared on (`_foot_series`: the compared foot measures on the expected clip's own
    frames, `{}` without feet files), which the score reads for the range weight of a foot fault (ADR-0018).
    """
    analysis: dict
    alignment: Alignment | None
    expected: Clip
    follower: Clip
    follower_positions: np.ndarray
    to_original: np.ndarray
    guard: GuardResult | None = None
    reps: list | None = None   # RepResult per follower rep when the take was compared rep by rep (ADR-0010)
    rep_run: RepRun | None = None
    vis: object = None
    rules: dict | None = None   # the effective rules the take was detected and scored with (ADR-0016)
    profile: str = profiles.IDENTITY
    foot_expected: dict = field(default_factory=dict)


def analyse(expected, follower, rules=None, *, expected_feet=None, follower_feet=None,
            expected_feet_person=0, follower_feet_person=0, profile=None):
    """`expected`/`follower` are paths, or objects with `path` plus ids that pass through
    to the output (e.g. `take_id`). Raises `io.InputError` for a bad file and `AnalysisError` for a bad ref, an
    unknown phrasing backend or a pair over the work bounds (frames, frame rate, frame pairs). A readable pair
    within the bounds is always analysed (ADR-0012): one that does not match the example, or shows too little of
    the body, comes back with a warning and grade F, never a refusal. The `*_feet` arguments and `profile` are
    `run`'s."""
    return run(expected, follower, rules, expected_feet=expected_feet, follower_feet=follower_feet,
               expected_feet_person=expected_feet_person, follower_feet_person=follower_feet_person,
               profile=profile).analysis


def run(expected, follower, rules=None, *, phrasing="template", phrasing_client=None, score=None,
        live=False, selected_by=None, expected_visibility=None, expected_feet=None, follower_feet=None,
        expected_feet_person=0, follower_feet_person=0, profile=None, lang=None):
    """`analyse` keeping the clips and the alignment (`PipelineResult`).

    A ref may carry the parsed JSON under `doc` (an upload held in memory): the clip is parsed
    from it, `path` names it in the output, and `doc` itself never reaches the output.

    `score` (ADR-0007) is the hook for `part5.score`: a callable taking the `PipelineResult` and
    returning the `score` block, or a ready block. Given, the analysis carries a `score` key, never null
    (ADR-0012). Absent, no `score` key.

    `expected_visibility` (ADR-0011) is the trainer's own skeleton or pose3d file, whose `conf` says which
    measures the example shows; without it an expected clip that carries no `conf` takes the follower's.

    `expected_feet` and `follower_feet` (ADR-0015, docs/specs/foot-keypoints.md) are paths to Part 2 `pose3d.json`
    files that carry the heel and toe points (`extra_joints`) of each clip's person (`*_feet_person`, matched to
    `people[].id`). Given for either clip, the document carries `diagnostics.feet`; the foot measures are compared
    when both clips have them and hidden, with the reason, when not. A foot measure whose rules entry has a
    `max_jitter_deg` is not compared in a clip where it jitters above it (the far foot of a side view, ADR-0015
    Amendment 4). Without either file, nothing changes.

    `profile` (ADR-0016) names the analysis profile, one of `profiles.names()`; None means `fitness`, the identity,
    which leaves `rules` untouched.
    `lang` (TICKET-046) is the follower's BCP 47 tag for the phrased lines; None means English. It changes only
    `coaching` and `phrasing`. Any other profile detects and scores with `profiles.effective_rules(rules, profile)`
    (kept on the result as `rules`), and the document names the profile. An unknown name is a `profiles.ProfileError`.
    """
    if phrasing not in PHRASING_BACKENDS:
        raise AnalysisError(f"phrasing must be one of {list(PHRASING_BACKENDS)}, got {phrasing!r}")
    rules = profiles.effective_rules(rules or load_rules(), profile)
    profile = profiles.IDENTITY if profile is None else profile
    exp_ref, fol_ref = _ref(expected, "expected"), _ref(follower, "follower")
    exp = normalise(_load(exp_ref))
    fol_file = _load(fol_ref)   # ADR-0021: the quality block reads the follower's file as loaded, before smoothing
    fol = normalise(fol_file)
    exp_ref.pop("doc", None)
    fol_ref.pop("doc", None)
    # ADR-0015: the optional feet side files, each read on its own clip's clock; None when neither was given. A foot
    # measure that jitters above its rules entry's `max_jitter_deg` is not read (Amendment 4: the far foot of a side view).
    limits = jitter_limits(rules)
    feet = pair_of(load_side("expected", expected_feet, expected_feet_person, exp.t, limits),
                   load_side("follower", follower_feet, follower_feet_person, fol.t, limits))
    extra_conf = None if expected_visibility is None else load_conf(expected_visibility)
    # ADR-0021, ADR-0011: the quality block holds the follower to the joints the example itself shows (its conf, or
    # `--expected-visibility`); an example of unknown visibility counts every joint
    readings = read_signals(fol_file, shown_joints(exp.conf, extra_conf))
    vis = resolve(clip_usable(exp), clip_usable(fol), usable_from_conf(extra_conf))
    notes = {}   # warning code -> text (ADR-0012): the take is analysed all the same, best effort
    moving_info = None
    exp, fol = hide_unseen(exp, vis), hide_unseen(fol, vis)
    if not vis.enough:
        notes[NOT_ENOUGH_VISIBLE] = NOT_ENOUGH_TEXT
    elif not vis.full:   # ADR-0011: the part the example moves should be in frame in the take
        moving_info = moving_check(exp.positions, vis, [exp.conf, extra_conf])
        if moving_info["moving_measures"] and not moving_info["moving_usable"]:
            notes[MOVING_PART_OUT_OF_FRAME] = moving_text(moving_info["moving_measures"])
    usable = vis.align_usable   # None: the full-body choice; fewer than 3 measures are still used
    ctx = _Context(exp_ref, fol_ref, exp, fol, vis, moving_info, notes,
                   (phrasing, phrasing_client, live, selected_by, lang), score, feet, rules, profile, readings)
    if usable is not None and not usable:   # nothing the camera sees can carry timing
        return _unaligned(ctx, NO_USABLE_MEASURES, NO_USABLE_TEXT, rules)
    # Alignment works in frames, so put the follower on the expected clip's clock first;
    # `to_original` maps each resampled frame back to the follower file's own frame index.
    fps = _bounded_fps(exp, exp_ref, fol, fol_ref)
    fol_positions, to_original = resample(fol.positions, fol.t, fps)
    exp_m, fol_m = measures_of(exp.positions, vis), measures_of(fol_positions, vis)
    align_names = list(ALIGN_MEASURES) if usable is None else usable
    for m in (exp_m, fol_m):
        if np.mean([np.isfinite(m[n]).mean() for n in align_names]) < MIN_AVAILABLE:
            return _unaligned(ctx, NO_USABLE_MEASURES, NO_USABLE_TEXT, rules)   # mostly missing joints: nothing to compare
    try:
        alignment = align(exp.positions, fol_positions, usable)
        guard = check_movement(alignment, exp_m, fol_m, rules)
    except AlignmentError:   # a follower with more reps than the whole-clip band can follow; any other error is a bug
        alignment, guard = None, None
    # An example of two or more reps is compared one repetition at a time (ADR-0017, ADR-0010); so is a take the whole-clip
    # guard refuses when either clip holds several reps. A rep-by-rep verdict that does not accept the take leaves the
    # whole-clip comparison as it was, and its verdict. The floor is a duration (persistence.floor_frames), so every
    # detection below is told the example's frame rate.
    exp_f, fol_f = _foot_series(feet, fol.t, fps)
    exp_reps = segment(exp_m, fps)
    try:
        rep_run = None if guard is not None and guard.ok and exp_reps.reps < 2 else \
            compare(exp, fol, exp_m, fol_positions, to_original, fps, rules, _fault_times, vis, max_cells=MAX_CELLS,
                    expected_segmentation=exp_reps, foot_exp=exp_f, foot_fol=fol_f)
    except TooManyPairs as e:   # reps x reference frames^2 is bounded like the whole pair
        raise _too_many_pairs(fol_ref, e.follower_frames, e.expected_frames) from None
    accepted = rep_run is not None and rep_run.guard.ok
    if guard is None and not accepted:   # cannot be aligned at all: analysed unaligned, never refused
        return _unaligned(ctx, LOW_MATCH, REFUSAL_TEXT, rules)
    if accepted:
        guard, faults, times = rep_run.guard, rep_run.faults, rep_run.times
        diagnostics = _rep_diagnostics(rep_run, exp, fol, fps, rules)
        alignment = next(r.alignment for r in rep_run.reps if r.ok)
    else:
        # persistence is judged in each of the example's reps (ADR-0017); an example of one rep is one rep
        spans = exp_reps.partition(exp.n_frames) if exp_reps.reps > 1 else None
        found = detect_full({**exp_m, **exp_f}, {**fol_m, **fol_f}, alignment, rules, rep_spans=spans, fps=fps)
        faults = [replace(f, follower_frames=tuple(int(to_original[j]) for j in f.follower_frames))
                  for f in found.faults]
        span = tuple(int(to_original[j]) for j in alignment.follower_span)
        diagnostics = _diagnostics(alignment, span, len(fol.t), guard_diagnostics(guard, rules))
        diagnostics["near_misses"] = summary(on_file(found.near_misses, to_original))   # additive to 1.7.0 (TICKET-043)
        times = [_fault_times(f, exp, fol, fol_positions, alignment, to_original) for f in faults]
    if not guard.ok:
        notes[LOW_MATCH] = REFUSAL_TEXT
    if not vis.full:   # additive to 1.3.0; a full-body take has no `visibility`, so its document is unchanged
        diagnostics["visibility"] = vis.diagnostics(moving_info)
    if feet is not None:   # additive to 1.6.0: only when a feet file was given for either clip
        diagnostics["feet"] = feet.diagnostics()   # ADR-0017: compared rep by rep too, it is no longer hidden in rep mode
    result = PipelineResult(None, alignment, exp, fol, fol_positions, np.asarray(to_original), guard,
                            reps=rep_run.reps if accepted else None, rep_run=rep_run if accepted else None, vis=vis,
                            rules=rules, profile=profile, foot_expected=exp_f)
    return _finish(ctx, result, faults, times, diagnostics, guard.stats, not guard.ok, rules)


@dataclass
class _Context:
    """What `run` has settled before the comparison: the refs, the clips, the visibility and the warnings so far."""
    exp_ref: dict
    fol_ref: dict
    exp: Clip
    fol: Clip
    vis: object
    moving: dict | None
    notes: dict
    phrasing: tuple
    score: object
    feet: object = None   # the `feet.FootPair`, None when no feet file was given
    rules: dict | None = None   # the effective rules (ADR-0016): the caller's rules, relaxed when a profile is named
    profile: str = profiles.IDENTITY
    readings: object = None   # the follower file's quality signals (`quality.Readings`, ADR-0021), None when not read


def _foot_series(feet, fol_t, fps):
    """The foot series the pair is compared on (ADR-0015): `(expected, follower)` dicts by measure name, the
    expected on its own frames and the follower on the expected clock like its joints. Empty without feet."""
    if feet is None or not feet.compared:
        return {}, {}
    names = feet.compared
    return ({n: feet.expected.series[n] for n in names},
            resampled_series({n: feet.follower.series[n] for n in names}, lambda stack: resample(stack, fol_t, fps)))


def _match(stats, low, rules):
    """`match` (ADR-0012): the guard's two numbers, null when unmeasured, and the limits in force."""
    def num(key):
        v = (stats or {}).get(key)
        return None if v is None or not np.isfinite(v) else round(float(v), 4)

    return {"quality": "low" if low else "ok", "residual": num("residual"), "timing_corr": num("timing_corr"),
            "limits": {k: rules["guard"][k] for k in ("max_residual", "min_timing_corr")}}


def _warning_list(notes):
    return [{"code": c, "text": notes[c]} for c in WARNING_ORDER if c in notes]


def _status_text(warnings):
    """`status.text` of an analysed take (ADR-0012 note): `OK_TEXT` with no warning, else the text that names how many
    warnings cap the grade at F. `status.code` is `ok` either way."""
    if not warnings:
        return OK_TEXT
    return OK_ONE_WARNING_TEXT if len(warnings) == 1 else OK_MANY_WARNINGS_TEXT.format(n=len(warnings))


def _quality_block(ctx):
    """The `quality` block of the take (ADR-0021): the follower file's readings and the warnings the take carries. It is
    reported only; `build_analysis` writes it and nothing after it reads it. None when the readings were not taken."""
    return None if ctx.readings is None else assess_quality(ctx.readings, ctx.notes)


def _finish(ctx, result, faults, times, diagnostics, stats, low, rules):
    """Build, phrase and score the document of a take; a take with any warning is capped at F (score_block)."""
    warnings = _warning_list(ctx.notes)
    analysis = build_analysis(ctx.exp_ref, ctx.fol_ref, faults, diagnostics=diagnostics,
                              status={"code": OK, "text": _status_text(warnings)}, times=times,
                              warnings=warnings or None, match=_match(stats, low, rules) if warnings else None,
                              profile=ctx.profile, quality=_quality_block(ctx))
    analysis = _phrased(analysis, *ctx.phrasing)
    result.analysis = analysis
    if ctx.score is not None:
        block = ctx.score(result) if callable(ctx.score) else ctx.score
        scored = dict(analysis, score=block)
        scored["insights"] = insights_of(scored)   # ranked by the timeline's points (ADR-0014)
        result.analysis = validate_analysis(scored, source="<built analysis>")
    return result


def _unaligned(ctx, code, text, rules):
    """A take nothing could be aligned or measured on (ADR-0012): analysed with a warning, no faults, score 0,
    and a straight-line stand-in alignment so the replay still plays. `rules` is the caller's, which `match`
    reports the limits of."""
    ctx.notes[code] = text
    diagnostics = {"warnings": []}
    if not ctx.vis.full:
        diagnostics["visibility"] = ctx.vis.diagnostics(ctx.moving)
    if ctx.feet is not None:
        diagnostics["feet"] = ctx.feet.hidden(UNALIGNED_REASON).diagnostics()
    n_fol = ctx.fol.n_frames
    result = PipelineResult(None, diagonal_alignment(ctx.exp.n_frames, n_fol), ctx.exp, ctx.fol, ctx.fol.positions,
                            np.arange(n_fol), None, vis=ctx.vis, rules=rules, profile=ctx.profile)
    return _finish(ctx, result, [], [], diagnostics, None, True, rules)


def _fault_times(fault, exp, fol, fol_positions, alignment, to_original):
    """The 1.2.0 time fields of one fault (ADR-0009): the follower file's own clock at the fault,
    every run mapped to the follower file's frames, and the foot offset."""
    def original(i):  # expected frame -> follower file frame
        return int(to_original[alignment.exp_to_fol[i]])

    t = fol.t
    return {"follower_t_s": [float(t[fault.follower_frames[0]]), float(t[fault.follower_frames[1]])],
            "follower_runs": [[original(s), original(e)] for s, e in fault.runs],
            "lateral_m": lateral_m(fault, exp.positions, fol_positions, alignment.exp_to_fol)}


def _phrased(analysis, backend, client, live=False, selected_by=None, lang=None):
    """Canonical joints and the coaching line per fault, and the `phrasing` record (ADR-0005,
    ADR-0006). Scored fields never depend on the backend or the language: only `coaching`, `phrasing` and the `why` of
    an insight that repeats a validated live English line (ADR-0014, Amendment 2) do, so the insights are made again."""
    for f in analysis["faults"]:
        f["joints"] = fault_joints(f)
    lines, record = phrase(analysis["faults"], backend, client=client, live=live, selected_by=selected_by, lang=lang)
    for f, line in zip(analysis["faults"], lines):
        f["coaching"] = line
    analysis["phrasing"] = record
    analysis["insights"] = insights_of(analysis)
    return validate_analysis(analysis, source="<built analysis>")


def clip_fps(clip):
    """The clip's frame rate: `fps` if given, else from the median step of `t`.

    The median-step clock assumes roughly uniform timing; for event-timed keyframes
    (`simon.skeleton.v1`) it is a heuristic, as aligning to sparse keyframes already is.
    """
    if clip.fps:
        return float(clip.fps)
    steps = np.diff(clip.t)
    return 1.0 / float(np.median(steps)) if len(steps) else 1.0


def resampled_length(t, fps):
    """How many frames `resample` puts on the `fps` grid over `t` (a float, so a huge span can't overflow)."""
    if len(t) < 2:
        return float(len(t))
    return float(np.floor((float(t[-1]) - float(t[0])) * fps + 1e-9)) + 1


def _bounded_fps(exp, exp_ref, fol, fol_ref):
    """The expected clip's frame rate, after refusing work no honest clip needs: a frame rate over
    MAX_FPS, or a follower that would be longer than MAX_FRAMES once resampled to it."""
    fps = clip_fps(exp)
    if not (np.isfinite(fps) and fps > 0):
        raise AnalysisError(f"{exp_ref['path']}: frame times give no usable frame rate ({fps!r})")
    if fps > MAX_FPS:
        raise AnalysisError(f"{exp_ref['path']}: {fps:g} frames per second, the limit is {MAX_FPS}")
    frames = resampled_length(fol.t, fps)
    if frames > MAX_FRAMES:
        raise AnalysisError(f"{fol_ref['path']}: {frames:.0f} frames at the example's {fps:g} frames per "
                            f"second ({float(fol.t[-1]) - float(fol.t[0]):g} s), the limit is {MAX_FRAMES}")
    if frames * exp.n_frames > MAX_CELLS:
        raise _too_many_pairs(fol_ref, frames, exp.n_frames)
    return fps


def _too_many_pairs(fol_ref, follower_frames, expected_frames):
    """The plain error both work bounds raise when the frame pairs to align pass MAX_CELLS: the whole pair
    here, and the reps together in `repwise.compare`."""
    return AnalysisError(f"{fol_ref['path']}: {follower_frames:.0f} follower frames against {expected_frames} "
                         f"expected frames are too long to compare together (the limit is {MAX_CELLS:,} frame pairs)")


def resample(positions, t, fps, tolerance=FPS_TOLERANCE):
    """Linear resampling of (F, 17, 3) positions onto a uniform `fps` grid over `t`.

    A joint missing (NaN) in either neighbouring frame stays missing, so gaps aren't
    bridged. Returns the positions and, per new frame, the nearest original frame index.
    Clips already at `fps` (and uniformly timed) come back unchanged.
    """
    n = len(t)
    steps = np.diff(t)
    if n < 2 or (np.allclose(steps, 1.0 / fps, rtol=tolerance)):
        return positions, np.arange(n)
    grid = t[0] + np.arange(int(resampled_length(t, fps))) / fps
    hi = np.clip(np.searchsorted(t, grid, side="right"), 1, n - 1)
    lo = hi - 1
    w = ((grid - t[lo]) / (t[hi] - t[lo]))[:, None, None]
    out = positions[lo] * (1 - w) + positions[hi] * w
    # On an original frame, take it as is (w is 1 at the last frame, where hi is clipped).
    at_lo, at_hi = np.isclose(w[:, 0, 0], 0.0), np.isclose(w[:, 0, 0], 1.0)
    out[at_lo] = positions[lo[at_lo]]
    out[at_hi] = positions[hi[at_hi]]
    nearest = np.where(grid - t[lo] <= t[hi] - grid, lo, hi)
    return out, nearest


def _load(ref):
    if "doc" in ref:
        return parse_clip(ref["doc"], source=ref["path"])
    return load_clip(ref["path"])


def _ref(ref, key):
    if isinstance(ref, (str, Path)):
        ref = {"path": str(ref)}
    if not (isinstance(ref, dict) and isinstance(ref.get("path"), (str, Path)) and str(ref["path"])):
        raise AnalysisError(f"{key} must be a path or an object with a 'path', got {ref!r}")
    return dict(ref, path=str(ref["path"]))


def _rep_diagnostics(rep_run, exp, fol, fps, rules):
    """`diagnostics` of a take compared rep by rep: the usual fields (the residual a median over the
    accepted reps, the span from the first rep to the last) plus `guard.reps` and `expected_reference`."""
    accepted = [r for r in rep_run.reps if r.ok]
    first = accepted[0].alignment
    alignment = replace(first, residual=float(np.median([r.alignment.residual for r in accepted])))
    span = (rep_run.reps[0].span[0], rep_run.reps[-1].span[1])
    out = _diagnostics(alignment, span, len(fol.t), guard_diagnostics(rep_run.guard, rules))
    out["guard"]["reps"] = rep_entries(rep_run.reps, fol)
    out["expected_reference"] = reference_entry(rep_run, exp, fps)
    out["near_misses"] = summary(rep_run.near_misses)   # take level, like the faults (TICKET-043)
    return out


def _diagnostics(alignment, span, n_follower, guard):
    start, end = span
    share = (end - start + 1) / n_follower
    warnings = []
    if share < MIN_SPAN_SHARE:
        warnings.append(f"only {share:.0%} of the follower clip matched the expected movement: "
                        "fine if the rest is standing still, but if the follower is much slower "
                        "than the example or repeats the movement, timing and faults may be wrong")
    return {"alignment_residual": round(float(alignment.residual), 4),
            "alignment_measures": list(alignment.measures),
            "follower_span": [start, end],
            "warnings": warnings,
            "guard": guard}
