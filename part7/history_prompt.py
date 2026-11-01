"""Packing and schema for the history call (docs/specs/history-meta.md, TICKET-181 AC-1 and AC-6).

`pack` turns a student's takes of one entry into the ordered content of one request: instructions, the teacher clip
and narration, then every take oldest first (the prefix stays the same as takes are added, so the API's automatic
cache can reuse it). Each take is a JSON digest from the fact table; up to MAX_VIDEOS videos including the teacher's ride along by priority
first, latest, best, worst, then the newest of the rest, inside a token budget. Without the video consent no
clip is packed. A private-mode take is not packed at all (no digest, no clip) and is removed from the facts that
come back, so the guard's input set is exactly what the model saw.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

PROMPT_VERSION = "history.v1"
MAX_VIDEOS = 5             # the API refuses a sixth video in one request (HTTP 400, spike.json)
CLIP_MAX_S = 60.0          # a clip longer than this is not sent (Simon's stored copies are 480 px, 8 fps, no audio)
BUDGET_TOKENS = 250_000    # input budget for one call
# Measured 193 tokens per second of video (demos/rubric/HISTORY/spike.json); 220 is the planning rate. The token
# counter is blind to video, so history_api prices clips with this rate itself.
VIDEO_TOKENS_PER_S = 220
CHARS_PER_TOKEN = 4

INSTRUCTIONS = (
    "You read one student's takes of one movement over time. You are given the teacher's recording and what the "
    "teacher said while recording, then every take of the student, oldest first, each labelled Take n with a JSON "
    "digest of the measured differences and, for some takes, the video.\n"
    "Return only JSON in the given format: a summary, at most 5 trends, one focus, an optional teacher_link and at "
    "most 3 observations.\n"
    "Rules:\n"
    "- Every item cites takes by their number n, and a time in seconds (at_s) when it is about one moment. "
    "A time is between 0 and that take's length.\n"
    "- A trend has a kind: improved, persistent, fixed or new. Use only measures and sides that appear in the digests, "
    "and cite the take and the time of the measured difference.\n"
    "- The focus cue is copied word for word from the latest take's cues.\n"
    "- teacher_link quotes the teacher word for word, in double quotes, from the narration cue you name by index.\n"
    "- Observations are things you see in a take's video that the digests do not hold.\n"
    "- Write one plain sentence of at most 160 characters per item. The only numbers allowed are the times you cite, "
    "the exact scores of the takes you cite and take labels such as Take 2.\n"
    "- No praise. Never mention health, pain, injury, medicine, therapy or rehab. Write in English."
)

_CITES = {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["take", "at_s"],
                                     "properties": {"take": {"type": "integer"}, "at_s": {"type": ["number", "null"]}}}}


def _obj(**props: Any) -> dict[str, Any]:
    return {"type": "object", "additionalProperties": False, "required": list(props), "properties": props}


_STR = {"type": "string"}
# strict mode needs every property required, so optional ones are nullable; the guard treats null as absent.
SCHEMA: dict[str, Any] = _obj(
    summary=_obj(text=_STR, cites=_CITES),
    trends={"type": "array", "items": _obj(
        kind={"type": "string", "enum": ["improved", "persistent", "fixed", "new"]}, measure=_STR, side=_STR,
        text=_STR, cites=_CITES)},
    focus=_obj(measure=_STR, side=_STR, cue=_STR, text=_STR, cites=_CITES),
    teacher_link={"anyOf": [_obj(cue_index={"type": "integer"}, text=_STR, cites=_CITES), {"type": "null"}]},
    observations={"type": "array", "items": _obj(take={"type": "integer"}, at_s={"type": "number"}, text=_STR)},
)
SCHEMA_NAME = "simon_history_v1"


def _tokens_text(text: str) -> int:
    return math.ceil(len(text) / CHARS_PER_TOKEN)


def _tokens_clip(duration_s: float) -> int:
    return math.ceil(min(float(duration_s), CLIP_MAX_S) * VIDEO_TOKENS_PER_S)


def _num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def clip_order(rows: list[dict[str, Any]]) -> list[int]:
    """Take numbers in clip priority: first, latest, best, worst, then the rest newest first. `rows` are oldest first
    and already limited to takes that may be sent."""
    scored = [r for r in rows if _num(r.get("score"))]
    picks = [rows[0], rows[-1]] if rows else []
    if scored:
        picks += [max(scored, key=lambda r: (r["score"], -r["take"])), min(scored, key=lambda r: (r["score"], r["take"]))]
    picks += list(reversed(rows))
    order: list[int] = []
    for row in picks:
        if row["take"] not in order:
            order.append(row["take"])
    return order


def _eligible(row: dict[str, Any], video_consent: bool) -> bool:
    return bool(video_consent and row.get("clip") and _num(row.get("duration_s")) and 0 < row["duration_s"] <= CLIP_MAX_S)


def _digest(take: dict[str, Any]) -> str:
    keep = {k: take.get(k) for k in ("take", "at", "score", "grade", "duration_s", "faults", "cues")}
    return json.dumps(keep, sort_keys=True, separators=(",", ":"))


def _narration_text(narration: dict[str, Any] | None) -> str | None:
    cues = narration.get("cues") if isinstance(narration, dict) else None
    rows = [{"index": c.get("index"), "start_s": c.get("start_s"), "end_s": c.get("end_s"), "text": c.get("text")}
            for c in cues or [] if isinstance(c, dict) and isinstance(c.get("text"), str)]
    return "What the teacher said while recording (JSON): " + json.dumps(rows, sort_keys=True) if rows else None


def pack(entry_id: str, facts: dict[str, Any], rows: list[dict[str, Any]], *, teacher_clip: Path | str | None = None,
         teacher_duration_s: float | None = None, narration: dict[str, Any] | None = None,
         video_consent: bool = False, budget_tokens: int = BUDGET_TOKENS) -> dict[str, Any]:
    """The packed request for `history_api.ask`.

    `rows` are the C-STORE rows of the student's takes, oldest first: `{take, job_id, duration_s, score, private,
    clip}`. `facts` is the C-FACTS fact table. The result holds `content` (ordered `text` and `video` items),
    `facts` (the facts of the takes sent, for the guard), `clips_sent` (the student's take clips only, not the teacher's), `video_seconds`, `video_consent` and `est_input_tokens`.
    """
    sent = sorted((r for r in rows if not r.get("private")), key=lambda r: r["take"])
    numbers = {r["take"] for r in sent}
    by_take = {t["take"]: t for t in facts.get("takes") or [] if t.get("take") in numbers}
    sent = [r for r in sent if r["take"] in by_take]
    used = _tokens_text(INSTRUCTIONS) + _tokens_text(json.dumps(SCHEMA))
    content: list[dict[str, Any]] = [{"type": "text", "text": INSTRUCTIONS}]
    clips, seconds = 0, 0.0
    if video_consent and teacher_clip and _num(teacher_duration_s) and 0 < teacher_duration_s <= CLIP_MAX_S:
        content += [{"type": "text", "text": "The teacher's recording:"},
                    {"type": "video", "path": str(teacher_clip), "label": "teacher"}]
        used, clips, seconds = used + _tokens_clip(teacher_duration_s), 1, float(teacher_duration_s)
    teacher_videos = clips  # the teacher's clip counts against MAX_VIDEOS but is not one of the student's clips_sent
    note = _narration_text(narration)
    if note:
        content.append({"type": "text", "text": note})
        used += _tokens_text(note)
    digests = {n: f"Take {n} digest (JSON): {_digest(by_take[n])}" for n in numbers & by_take.keys()}
    used += sum(_tokens_text(d) for d in digests.values())
    chosen: set[int] = set()
    by_row = {r["take"]: r for r in sent}
    for n in clip_order(sent):
        row = by_row[n]
        cost = _tokens_clip(row["duration_s"]) if _eligible(row, video_consent) else 0
        if cost and len(chosen) < MAX_VIDEOS - 1 and used + cost <= budget_tokens:  # at most 4 take clips, with or without the teacher's
            chosen.add(n)
            clips, used, seconds = clips + 1, used + cost, seconds + row["duration_s"]
    for row in sent:
        n = row["take"]
        content.append({"type": "text", "text": digests[n]})
        if n in chosen:
            content.append({"type": "video", "path": str(row["clip"]), "label": f"Take {n}"})
    kept_facts = {**facts, "takes": [by_take[r["take"]] for r in sent],
                  "measures": [{**m, "present_in": [n for n in m.get("present_in") or [] if n in by_take]}
                               for m in facts.get("measures") or [] if set(m.get("present_in") or []) & set(by_take)]}
    return {"entry_id": entry_id, "prompt_version": PROMPT_VERSION, "content": content, "schema": SCHEMA,
            "facts": kept_facts, "clips_sent": clips - teacher_videos, "video_seconds": seconds, "video_consent": bool(video_consent), "est_input_tokens": used}
