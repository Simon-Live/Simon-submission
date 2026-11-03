"""Part 5's heading signal (analysis 1.14.0, TICKET-086) as Part 7 reads it (docs/specs/heading-note.md, TICKET-246).

`quality.signals.heading_offset_deg` is the angle left between the trainer and the follower after Part 3's facing
step. Part 5 adds the degraded-only reason `heading_offset` at or above 5 degrees (`part5/quality.json`), the angle its
TICKET-082 bench found starts to move the score. A take at or past it is a rough score: never the judge view's hero.
It is a note, not a cap; the score is left as it is.
"""

from __future__ import annotations

from typing import Any

REASON = "heading_offset"
ROUGH_DEG = 5.0  # Part 5's degraded limit for heading_offset_deg (modules/part-5/part5/quality.json), at or above
FAR_DEG = 15.0  # Part 5 docs/evaluation.md: at 15 degrees 8 of the 12 correct takes gain a fault


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def offset_of(quality: Any) -> float | None:
    """The heading offset in degrees: the signal, else the `heading_offset` reason's value; None when neither is read."""
    if not isinstance(quality, dict):
        return None
    signals = quality.get("signals")
    found = _number(signals.get("heading_offset_deg")) if isinstance(signals, dict) else None
    if found is not None:
        return found
    reasons = quality.get("reasons")
    for reason in reasons if isinstance(reasons, list) else []:
        if isinstance(reason, dict) and reason.get("code") == REASON:
            return _number(reason.get("value"))
    return None


def has_reason(quality: Any) -> bool:
    reasons = quality.get("reasons") if isinstance(quality, dict) else None
    return any(isinstance(r, dict) and r.get("code") == REASON for r in (reasons if isinstance(reasons, list) else []))


def is_rough(quality: Any) -> bool:
    """True when Part 5 gave the `heading_offset` reason or the offset is at or above ROUGH_DEG."""
    offset = offset_of(quality)
    return has_reason(quality) or (offset is not None and offset >= ROUGH_DEG)
