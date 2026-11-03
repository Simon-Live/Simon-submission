"""The "What Simon sent" receipt (docs/specs/history-receipt.md, TICKET-212).

One reusable block for every model feature on the history rails. `build(packed, usage, feature=...)` turns the
packed request (`history_prompt.pack`, or any packed dict that carries a `manifest`) and the settled usage of
`history_api.ask` into a `sent` dict that a report stores beside its text. The block is rebuilt from an allowlist,
so it never holds a file path, a user id, an email, a job id or model text: take numbers, counts, plain words and
numbers only. The page renders it with `web/views/receipt.js` (`renderReceipt`).
"""

from __future__ import annotations

import math
import re
from typing import Any

from part7 import history_api

SAFE_WORD = re.compile(r"^[A-Za-z0-9._-]{1,40}$")
MAX_TAKES = 200
MAX_FIELDS = 24


def _count(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _takes(value: Any) -> list[int]:
    items = value if isinstance(value, (list, tuple, set)) else []
    return sorted({n for n in items if isinstance(n, int) and not isinstance(n, bool) and 0 < n < 10_000})[:MAX_TAKES]


SAFE_NAME = re.compile(r"^[A-Za-z0-9 ._-]{1,60}$")


def _cites(value: Any) -> list[list[Any]]:
    """`[movement name, take number]` pairs: the take numbers the movement's own page uses (Ask numbers its refs across movements)."""
    items = value if isinstance(value, (list, tuple)) else []
    pairs = [[p[0].strip(), p[1]] for p in items if isinstance(p, (list, tuple)) and len(p) == 2 and isinstance(p[0], str) and SAFE_NAME.match(p[0].strip())
             and isinstance(p[1], int) and not isinstance(p[1], bool) and 0 < p[1] < 10_000]
    return pairs[:MAX_TAKES]


def _word(value: Any, default: str = "") -> str:
    return value if isinstance(value, str) and SAFE_WORD.match(value) else default


def _usage_fields(usage: Any) -> dict[str, Any]:
    if not isinstance(usage, dict) or _count(usage.get("input_tokens")) is None:
        return {}
    usd = usage.get("usd")
    return {"settled": True, "input_tokens": _count(usage.get("input_tokens")),
            "cached_tokens": _count(usage.get("cached_tokens")) or 0, "output_tokens": _count(usage.get("output_tokens")) or 0,
            "usd": round(float(usd), 6) if isinstance(usd, (int, float)) and math.isfinite(usd) and usd >= 0 else None}


def build(packed: dict[str, Any], usage: dict[str, Any] | None = None, *, feature: str | None = None,
          extra_fields: list[str] | None = None) -> dict[str, Any]:
    """The `sent` block for one call. Without `usage` (the call failed before it settled) the token counts and the
    cost stay out and `settled` is false. `feature` is the ledger feature name (default `packed['feature']`, else
    `compare`); `extra_fields` adds the names of fields a feature sends beyond the take digest."""
    manifest = packed.get("manifest") if isinstance(packed.get("manifest"), dict) else {}
    digest = _takes(manifest.get("digest_takes", list((packed.get("seen") or {}).keys())))
    clips = _takes(manifest.get("clip_takes", packed.get("clip_takes")))
    fields = [f for f in [*(manifest.get("fields") or []), *(extra_fields or [])] if _word(f)][:MAX_FIELDS]
    return {
        "feature": _word(feature or packed.get("feature"), history_api.DEFAULT_FEATURE),
        "prompt_version": _word(manifest.get("prompt_version") or packed.get("prompt_version"), "unknown"),
        "model": history_api.MODEL, "store": False, "file_expires_s": history_api.EXPIRES_AFTER_S,
        "digest_takes": digest, "digest_cites": _cites(manifest.get("digest_cites")), "clip_takes": clips, "fields": fields,
        "teacher_clip": manifest.get("teacher_clip") is True,
        "video_consent": bool(manifest.get("video_consent", packed.get("video_consent"))),
        "narration_cues": _count(manifest.get("narration_cues")) or 0, "notes_sent": _count(manifest.get("notes_sent")) or 0,  # a count, never the text
        "est_input_tokens": _count(manifest.get("est_input_tokens", packed.get("est_input_tokens"))) or 0,
        "settled": False, **_usage_fields(usage),
    }


def with_actual(sent: dict[str, Any], usage: dict[str, Any] | None) -> dict[str, Any]:
    """`sent` with the settled token counts and cost of `usage` filled in; unchanged when `usage` has no count."""
    return {**sent, **_usage_fields(usage)}


def leaks(sent: dict[str, Any], *needles: str) -> list[str]:
    """Which of `needles` (a path, a user id, an email, a job id) appear anywhere in `sent`; empty when it is clean."""
    text = repr(sent)
    return [n for n in needles if n and n in text]
