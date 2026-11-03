"""Part 5's `quality` block (simon.quality.v1, analysis 1.13.0) and the cap Part 7 applies for it.

Part 5 only reports: `score.value` is unchanged by the block and `quality.score_cap` is 59 when `level` is `major`
(modules/part-5/CONTRACT.md, "Read quality"). So the shown score is `min(score.value, quality.score_cap)`, grade F
when the cap changed it, `score.uncapped` keeps the figure before the cap. A document without the block is
not assessed: it is never read as `ok`.
"""

from __future__ import annotations

from typing import Any

CAP_CODE = "quality_major"
NOT_ASSESSED = "not_assessed"
LEVELS = ("ok", "degraded", "major")
FALLBACK_LABEL = "The video quality was too low to judge form reliably"


def level_of(quality: Any) -> str:
    """`ok`, `degraded` or `major`; `not_assessed` for an absent, malformed or unknown block (never `ok`)."""
    level = quality.get("level") if isinstance(quality, dict) else None
    return level if level in LEVELS else NOT_ASSESSED


def cap_of(quality: Any) -> int | None:
    """`score_cap` of a `major` block (59), else None."""
    cap = quality.get("score_cap") if isinstance(quality, dict) else None
    if level_of(quality) != "major" or isinstance(cap, bool) or not isinstance(cap, (int, float)):
        return None
    return int(cap)


def reason_words(quality: Any) -> str:
    """The block's `reasons[].words`, in Part 5's order, joined into plain text."""
    reasons = quality.get("reasons") if isinstance(quality, dict) else None
    words = [r["words"].strip() for r in reasons or [] if isinstance(r, dict) and isinstance(r.get("words"), str) and r["words"].strip()]
    return " ".join(words)


def label_of(quality: Any) -> str:
    return reason_words(quality) or FALLBACK_LABEL


def apply(summary: dict[str, Any]) -> dict[str, Any]:
    """`summary` (a job result's score fields) with the quality cap: score, grade F, `uncapped`, `capped_by`, `quality_note`."""
    quality = summary.get("quality")
    cap = cap_of(quality)
    if cap is None:
        return summary
    out = {**summary, "quality_note": label_of(quality)}
    score = summary.get("score")
    if isinstance(score, (int, float)) and not isinstance(score, bool) and score > cap:
        out["uncapped"] = summary.get("uncapped") or {"value": score, "grade": summary.get("grade")}
        out["score"] = cap
        out["grade"] = "F"
        out["capped_by"] = [*(summary.get("capped_by") or []), CAP_CODE]
    return out
