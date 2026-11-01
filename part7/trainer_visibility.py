"""Which joints of the trainer's own Part 3 skeleton the camera never saw, for the 3D compare and the results summary.

Part 4's `animation.json` (and so Part 5's replay) carries no per-joint confidence, so a seated trainer's invented
knees and ankles look like any other joint. Part 7 keeps the trainer's Part 3 skeleton (`expected_skeleton.json`, the
file it already passes to Part 5 as `--expected-visibility`) and answers the unseen joints from it. Part 7 measures
nothing: the mark is Part 3's own, `conf` at the 0.3 sentinel (Part 5 `visibility.py` UNSEEN_CONF); a `conf` below it
is a missing joint, dimmed the same way. No other value counts, so a standing trainer yields no unseen joint.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from part7.skeleton2d import JOINTS

SCHEMA = "simon.trainer_visibility.v1"
UNSEEN_CONF = 0.3
TOLERANCE = 1e-6


def _number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _frame(frame: Any, fallback_t: float) -> tuple[float, list[int]] | None:
    people = frame.get("people") if isinstance(frame, dict) else None
    who = people[0] if isinstance(people, list) and people and isinstance(people[0], dict) else None
    if who is None or not isinstance(who.get("joints"), dict):
        return None
    t = float(frame["t_ms"]) / 1000.0 if _number(frame.get("t_ms")) else fallback_t
    unseen = []
    for i, name in enumerate(JOINTS):
        joint = who["joints"].get(name)
        conf = joint.get("conf") if isinstance(joint, dict) else None
        if _number(conf) and conf <= UNSEEN_CONF + TOLERANCE:
            unseen.append(i)
    return round(t, 4), unseen


def build(path: Path) -> dict[str, Any] | None:
    """`{schema, joints, threshold, t, unseen}` from a Part 3 skeleton file: `unseen[k]` lists the joint indices unseen
    at `t[k]` seconds. None when the file is missing or is no skeleton."""
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    frames = doc.get("frames") if isinstance(doc, dict) else None
    fps = doc.get("fps") if isinstance(doc, dict) else None
    step = 1.0 / fps if _number(fps) and fps > 0 else 0.0
    rows = [_frame(f, i * step) for i, f in enumerate(frames if isinstance(frames, list) else [])]
    kept = [r for r in rows if r is not None]
    if not kept:
        return None
    return {"schema": SCHEMA, "joints": list(JOINTS), "threshold": UNSEEN_CONF,
            "t": [r[0] for r in kept], "unseen": [r[1] for r in kept]}
