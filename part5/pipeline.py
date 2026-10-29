"""The whole analysis for one follower take: load → normalise → align → guard → measures → detect → words.

`analyse` returns a validated `simon.analysis.v1` document (see docs/schemas.md) without
writing anything, so the CLI, `make check-5` and the example script share one code path.
"""
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np

from .align import ALIGN_MEASURES, Alignment, align
from .detect import detect, load_rules
from .guard import GuardResult, check_movement
from .guard import diagnostics as guard_diagnostics
from .io import Clip, load_clip, parse_clip
from .joints_map import fault_joints
from .measures import compute
from .normalise import normalise
from .output import build_analysis, validate_analysis
from .phrasing import BACKENDS, phrase

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


PHRASING_BACKENDS = tuple(BACKENDS)


class AnalysisError(ValueError):
    """The takes loaded but can't be compared (e.g. the follower is far too fast)."""


@dataclass
class PipelineResult:
    """One analysis with what the replay needs: the normalised clips and the alignment.

    `follower` is the follower clip on its own frames; `follower_positions` is it resampled onto
    the expected clock (what was aligned), and `to_original[j]` is the follower file's frame for
    resampled frame `j`. `alignment` indexes the resampled frames. `guard` is the movement
    guard's verdict (a refused take has no faults).
    """
    analysis: dict
    alignment: Alignment | None
    expected: Clip
    follower: Clip
    follower_positions: np.ndarray
    to_original: np.ndarray
    guard: GuardResult | None = None


def analyse(expected, follower, rules=None):
    """`expected`/`follower` are paths, or objects with `path` plus ids that pass through
    to the output (e.g. `take_id`). Raises `io.InputError` for a bad file, `AnalysisError`
    if the takes can't be aligned."""
    return run(expected, follower, rules).analysis


def run(expected, follower, rules=None, *, phrasing="template", phrasing_client=None):
    """`analyse` keeping the clips and the alignment (`PipelineResult`).

    A ref may carry the parsed JSON under `doc` (an upload held in memory): the clip is parsed
    from it, `path` names it in the output, and `doc` itself never reaches the output.
    """
    if phrasing not in PHRASING_BACKENDS:
        raise AnalysisError(f"phrasing must be one of {list(PHRASING_BACKENDS)}, got {phrasing!r}")
    rules = rules or load_rules()
    exp_ref, fol_ref = _ref(expected, "expected"), _ref(follower, "follower")
    exp = normalise(_load(exp_ref))
    fol = normalise(_load(fol_ref))
    exp_ref.pop("doc", None)
    fol_ref.pop("doc", None)
    # Alignment works in frames, so put the follower on the expected clip's clock first;
    # `to_original` maps each resampled frame back to the follower file's own frame index.
    fps = _bounded_fps(exp, exp_ref, fol, fol_ref)
    fol_positions, to_original = resample(fol.positions, fol.t, fps)
    exp_m, fol_m = compute(exp.positions), compute(fol_positions)
    for ref, m in ((exp_ref, exp_m), (fol_ref, fol_m)):
        available = np.mean([np.isfinite(m[n]).mean() for n in ALIGN_MEASURES])
        if available < MIN_AVAILABLE:
            raise AnalysisError(f"{ref['path']}: only {available:.0%} of the body could be measured "
                                "(joints missing or below the confidence cutoff)")
    try:
        alignment = align(exp.positions, fol_positions)
    except ValueError as e:
        raise AnalysisError(f"{fol_ref['path']}: cannot align with {exp_ref['path']} ({e})") from e
    # A different movement is refused before detection: DTW always finds a closest phase.
    guard = check_movement(alignment, exp_m, fol_m, rules)
    faults = [] if not guard.ok else [
        replace(f, follower_frames=tuple(int(to_original[j]) for j in f.follower_frames))
        for f in detect(exp_m, fol_m, alignment, rules)]
    span = tuple(int(to_original[j]) for j in alignment.follower_span)
    diagnostics = _diagnostics(alignment, span, len(fol.t), guard_diagnostics(guard, rules))
    analysis = build_analysis(exp_ref, fol_ref, faults, diagnostics=diagnostics,
                              status={"code": guard.code, "text": guard.text})
    analysis = _phrased(analysis, phrasing, phrasing_client)
    return PipelineResult(analysis, alignment, exp, fol, fol_positions, np.asarray(to_original), guard)


def _phrased(analysis, backend, client):
    """Canonical joints and the coaching line per fault, and the `phrasing` record (ADR-0005,
    ADR-0006). Scored fields never depend on the backend: only `coaching` and `phrasing` do."""
    for f in analysis["faults"]:
        f["joints"] = fault_joints(f)
    lines, record = phrase(analysis["faults"], backend, client=client)
    for f, line in zip(analysis["faults"], lines):
        f["coaching"] = line
    analysis["phrasing"] = record
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
    cells = frames * exp.n_frames
    if cells > MAX_CELLS:
        raise AnalysisError(f"{fol_ref['path']}: {frames:.0f} follower frames against {exp.n_frames} expected "
                            f"frames are too long to compare together (the limit is {MAX_CELLS:,} frame pairs)")
    return fps


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
