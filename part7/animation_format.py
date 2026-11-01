"""Expected clips as Part 5 reads them (TICKET-110, processor.md "Expected clip formats").

The six built-in sample entries carry `simon.animation/1`: frames of `{frame, t_ms, interpolated, people: [{id,
joints: {<name>: {x, y, z, conf}}}]}`. Part 5 accepts `simon.animation.v1` (input-animation.schema.json):
`frames[].joints[name] = [x, y, z]` or null, seconds in `t`, and a per-frame `conf` object. `to_v1` converts the
former; a simon.animation.v1 document is returned byte-identical and any other input is returned untouched, so
Part 5 gives its own error for it.
"""

from __future__ import annotations

import json
import math
from typing import Any

SAMPLE_SCHEMA = "simon.animation/1"
V1 = "simon.animation.v1"
JOINTS = (
    "nose", "left_eye", "right_eye", "left_ear", "right_ear", "left_shoulder", "right_shoulder", "left_elbow",
    "right_elbow", "left_wrist", "right_wrist", "left_hip", "right_hip", "left_knee", "right_knee", "left_ankle",
    "right_ankle",
)
COORDINATE_FRAME = {
    "origin": "hip_midpoint", "x": "subject_left", "y": "world_up", "z": "anterior",
    "position_unit": "metres", "angle_unit": "degrees",
}


def _num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _person(frame: dict[str, Any], person_id: int | None) -> dict[str, Any] | None:
    people = [p for p in frame.get("people") or [] if isinstance(p, dict)]
    if person_id is not None:
        people = [p for p in people if p.get("id") == person_id] or people[:1]
    return people[0] if people else None


def _joint(j: Any) -> tuple[list[float] | None, float]:
    """`([x, y, z], conf)`; `(None, 0.0)` when a coordinate is missing or not finite, or conf is 0 or less."""
    if not isinstance(j, dict) or not all(_num(j.get(k)) for k in "xyz"):
        return None, 0.0
    conf = j.get("conf", 1.0)
    conf = float(conf) if _num(conf) else 1.0
    if conf <= 0:
        return None, 0.0
    return [float(j["x"]), float(j["y"]), float(j["z"])], min(conf, 1.0)


def _time_s(fr: dict[str, Any], i: int, fps: Any) -> float:
    if _num(fr.get("t_ms")):
        return float(fr["t_ms"]) / 1000.0
    index = fr.get("frame", i)
    return float(index if _num(index) else i) / (fps if _num(fps) and fps > 0 else 30.0)


def _frame(fr: Any, i: int, fps: Any, person_id: int | None) -> dict[str, Any]:
    fr = fr if isinstance(fr, dict) else {}
    who = _person(fr, person_id)
    raw = (who or {}).get("joints")
    joints: dict[str, Any] = {}
    conf: dict[str, float] = {}
    for name in JOINTS:
        joints[name], conf[name] = _joint(raw.get(name) if isinstance(raw, dict) else None)
    out: dict[str, Any] = {"index": fr.get("frame", i), "t": _time_s(fr, i, fps)}
    if isinstance(fr.get("interpolated"), bool):
        out["interpolated"] = fr["interpolated"]
    return {**out, "joints": joints, "conf": conf}


def convert(doc: dict[str, Any], person_id: int | None = None) -> dict[str, Any]:
    """The simon.animation/1 document `doc` as simon.animation.v1 (first person, or the one with `person_id`)."""
    fps = doc.get("fps")
    result: dict[str, Any] = {"format": V1, "joints": list(JOINTS), "coordinate_frame": dict(COORDINATE_FRAME)}
    if _num(fps) and fps > 0:
        result["fps"] = fps
    result["frames"] = [_frame(fr, i, fps, person_id) for i, fr in enumerate(doc.get("frames") or [])]
    return result


def to_v1(data: bytes, person_id: int | None = None) -> bytes:
    """`data` as bytes Part 5 accepts: a simon.animation/1 document is converted, anything else is returned as is."""
    try:
        doc = json.loads(data)
    except ValueError:
        return data
    if not isinstance(doc, dict) or doc.get("format") or doc.get("schema") != SAMPLE_SCHEMA:
        return data
    return json.dumps(convert(doc, person_id), separators=(",", ":")).encode()
