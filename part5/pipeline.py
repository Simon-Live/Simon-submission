"""The whole analysis for one follower take: load → normalise → align → measures → detect → words.

`analyse` returns a validated `simon.analysis.v1` document (see docs/schemas.md) without
writing anything, so the CLI, `make check-5` and the example script share one code path.
"""
from pathlib import Path

import numpy as np

from .align import ALIGN_MEASURES, align
from .detect import detect
from .io import load_clip
from .measures import compute
from .normalise import normalise
from .output import build_analysis

# On the dummy takes the matched span always covers ≥76% of the follower clip. Much less than
# that usually means a follower slower than ½x, which aligns to a subsegment (see align.dtw).
MIN_SPAN_SHARE = 0.6
# Below this share of usable measure values a take is mostly missing joints, and "no faults"
# would only mean "nothing could be measured". The dummy takes are all at 100%.
MIN_AVAILABLE = 0.5


class AnalysisError(ValueError):
    """The takes loaded but can't be compared (e.g. the follower is far too fast)."""


def analyse(expected, follower, rules=None):
    """`expected`/`follower` are paths, or objects with `path` plus ids that pass through
    to the output (e.g. `take_id`). Raises `io.InputError` for a bad file, `AnalysisError`
    if the takes can't be aligned."""
    exp_ref, fol_ref = _ref(expected), _ref(follower)
    exp = normalise(load_clip(exp_ref["path"]))
    fol = normalise(load_clip(fol_ref["path"]))
    exp_m, fol_m = compute(exp.positions), compute(fol.positions)
    for ref, m in ((exp_ref, exp_m), (fol_ref, fol_m)):
        available = np.mean([np.isfinite(m[n]).mean() for n in ALIGN_MEASURES])
        if available < MIN_AVAILABLE:
            raise AnalysisError(f"{ref['path']}: only {available:.0%} of the body could be measured "
                                "(joints missing or below the confidence cutoff)")
    try:
        alignment = align(exp.positions, fol.positions)
    except ValueError as e:
        raise AnalysisError(f"{fol_ref['path']}: cannot align with {exp_ref['path']} ({e})") from e
    faults = detect(exp_m, fol_m, alignment, rules)
    return build_analysis(exp_ref, fol_ref, faults, diagnostics=_diagnostics(alignment, len(fol.positions)))


def _ref(ref):
    return {"path": str(ref)} if isinstance(ref, (str, Path)) else dict(ref)


def _diagnostics(alignment, n_follower):
    start, end = (int(x) for x in alignment.follower_span)
    share = (end - start + 1) / n_follower
    warnings = []
    if share < MIN_SPAN_SHARE:
        warnings.append(f"only {share:.0%} of the follower clip matched the expected movement; "
                        "it may be much slower than the example or repeat the movement, "
                        "so timing and faults are unreliable")
    return {"alignment_residual": round(float(alignment.residual), 4),
            "alignment_measures": list(alignment.measures),
            "follower_span": [start, end],
            "warnings": warnings}
