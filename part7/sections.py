"""Trainer sections for "Learn in sections" (practice-and-modes.md "Sections").

A section is a time range of the trainer clip, `{start_ms, end_ms, index, count}` with `index` counted from 1.
Optional: `first` (sections `first` to `index` joined) and `speed` (0.25 to 1: the clip is stretched by 1/speed).
The follow request cuts the expected clip to that range, so Part 5 compares the follower's take of the section
with the same part of the trainer. Frame times are rebased to start at 0 (the take starts at 0 too; Part 5
reads `t` and needs it strictly increasing, input-animation.schema.json).
"""

from __future__ import annotations

import json
from typing import Any

MIN_SECTION_MS = 1000
MAX_SECTIONS = 8
MIN_SPEED = 0.25
END_SLACK_S = 1.5
FRAME_KEYS = ("frames", "keyframes")  # simon.animation.v1 and simon.skeleton.v1

MSG_SHAPE = "The section needs start_ms, end_ms, index and count as whole numbers."
MSG_ORDER = "The section must start before it ends, inside the movement."
MSG_SHORT = "The section is too short (1 s at least)."
MSG_COUNT = "The section number must be between 1 and the number of sections (8 at most)."
MSG_SPEED = "The practice speed must be between 0.25 and 1."
MSG_EMPTY = "The section has no movement data to follow."


class SectionError(ValueError):
    """The section is not acceptable; the message is plain words for the person."""


def _int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def parse(value: Any) -> dict[str, int] | None:
    """None when absent, the section when its shape is valid, else `SectionError`."""
    if value is None:
        return None
    keys = ("start_ms", "end_ms", "index", "count")
    if not isinstance(value, dict) or not all(_int(value.get(k)) for k in keys):
        raise SectionError(MSG_SHAPE)
    sec = {k: value[k] for k in keys}
    first, speed = value.get("first"), value.get("speed")
    if first is not None:  # sections `first` to `index` joined (the ladder's joined steps)
        if not _int(first) or not 1 <= first <= sec["index"]:
            raise SectionError(MSG_COUNT)
        sec["first"] = first
    if speed is not None:  # the trainer clip is slowed by this factor, as the practice step plays it
        if isinstance(speed, bool) or not isinstance(speed, (int, float)) or not MIN_SPEED <= speed <= 1:
            raise SectionError(MSG_SPEED)
        sec["speed"] = speed
    if not 0 <= sec["start_ms"] < sec["end_ms"]:
        raise SectionError(MSG_ORDER)
    if sec["end_ms"] - sec["start_ms"] < MIN_SECTION_MS:
        raise SectionError(MSG_SHORT)
    if not 1 <= sec["count"] <= MAX_SECTIONS or not 1 <= sec["index"] <= sec["count"]:
        raise SectionError(MSG_COUNT)
    return sec


def _times(frames: list[Any], fps: Any) -> list[float]:
    out: list[float] = []
    for i, fr in enumerate(frames):
        if isinstance(fr, dict) and isinstance(fr.get("t"), (int, float)):
            out.append(float(fr["t"]))
        elif isinstance(fps, (int, float)) and fps > 0 and isinstance(fr, dict):
            index = fr.get("index", i)
            out.append(float(index if isinstance(index, (int, float)) else i) / fps)
        else:
            raise SectionError(MSG_EMPTY)
    return out


def cut(data: bytes, section: dict[str, int]) -> bytes:
    """The expected clip `data` restricted to the section, times rebased to 0; `SectionError` when it does not fit."""
    try:
        doc = json.loads(data)
    except ValueError:
        raise SectionError(MSG_EMPTY) from None
    key = next((k for k in FRAME_KEYS if isinstance(doc, dict) and isinstance(doc.get(k), list) and doc[k]), None)
    if key is None:
        raise SectionError(MSG_EMPTY)
    frames = doc[key]
    times = _times(frames, doc.get("fps"))
    start_s, end_s = section["start_ms"] / 1000.0, section["end_ms"] / 1000.0
    # the section must lie inside the clip; an end up to END_SLACK_S past it is the end of the clip (the catalog
    # length is the video's, the animation can be a little shorter)
    if start_s >= times[-1] or end_s > times[-1] + END_SLACK_S:
        raise SectionError(MSG_ORDER)
    kept = [(t, fr) for t, fr in zip(times, frames) if start_s <= t <= end_s]
    if len(kept) < 2:
        raise SectionError(MSG_EMPTY)
    speed = float(section.get("speed") or 1.0)  # a slow step: the trainer's clip is stretched to match the slow take
    out = []
    for n, (t, fr) in enumerate(kept):
        row = dict(fr)
        row["t"] = round((t - kept[0][0]) / speed, 6)
        if "index" in row:
            row["index"] = n
        out.append(row)
    doc[key] = out
    if isinstance(doc.get("fps"), (int, float)) and not isinstance(doc["fps"], bool):
        doc["fps"] = doc["fps"] * speed  # Part 5 prefers fps over t (clip_fps): the stretched clip plays at fps * speed
    if "frame_count" in doc:
        doc["frame_count"] = len(out)
    if "duration_s" in doc:
        doc["duration_s"] = out[-1]["t"]
    return json.dumps(doc).encode("utf-8")
