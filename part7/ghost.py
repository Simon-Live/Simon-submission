"""The trainer's 2D ghost for the live camera preview (docs/specs/follow-ghost.md, TICKET-264).

`GET api/ghost/<entry_id>.json` answers a `simon.skeleton2d.v1` document (the format `skeleton2d.py` writes for a
follower) made from the entry's own trainer data: Part 4's `animation.json` (30 frames a second) or, without one,
Part 3's `skeleton.json`. Part 7 measures nothing new and runs no pose model: it only drops the depth axis of the
trainer's canonical joints (x the subject's left, y up, hip midpoint at the origin) and scales them so the body's
full height over the clip is 1. The picture is the camera's own view of a trainer facing it: the subject's left is
on the image's right. `box` is "body": shares of that body box, which the browser places over the preview after the
"stand in the outline" step; the browser mirrors it when the reference is mirrored.
"""

from __future__ import annotations

import json
import re
from typing import Any

from part7.skeleton2d import BONES, JOINTS

ROUTE_RE = re.compile(r"^ghost/(?P<id>[a-z0-9][a-z0-9-]{0,62})\.json$")
FORMAT = "simon.skeleton2d.v1"
MSG_NONE = "This movement has no trainer skeleton to show."
MSG_ENTRY = "This movement is not in the catalog."


def _xyz(joint: Any) -> tuple[float, float] | None:
    """`(x, y)` of one joint in either layout ({x, y, z[, conf]} or [x, y, z]); None when missing or unseen."""
    try:
        if isinstance(joint, dict):
            if float(joint.get("conf", 1.0)) <= 0:
                return None
            return float(joint["x"]), float(joint["y"])
        if isinstance(joint, (list, tuple)) and len(joint) >= 2:
            return float(joint[0]), float(joint[1])
    except (KeyError, TypeError, ValueError):
        return None
    return None


def _frames(doc: Any) -> list[tuple[float, dict[str, Any]]]:
    """`[(t seconds, {joint: value})]` of an animation (both Part 4 layouts) or a Part 3 skeleton."""
    if not isinstance(doc, dict) or not isinstance(doc.get("frames"), list):
        return []
    fps = doc.get("fps") if isinstance(doc.get("fps"), (int, float)) and doc.get("fps") > 0 else 30
    out = []
    for i, f in enumerate(doc["frames"]):
        if not isinstance(f, dict):
            continue
        if isinstance(f.get("t"), (int, float)):
            t = float(f["t"])
        elif isinstance(f.get("t_ms"), (int, float)):
            t = float(f["t_ms"]) / 1000.0
        else:
            t = i / fps
        joints = f.get("joints")
        if not isinstance(joints, dict):
            people = f.get("people")
            first = people[0] if isinstance(people, list) and people and isinstance(people[0], dict) else {}
            joints = first.get("joints")
        if isinstance(joints, dict):
            out.append((t, joints))
    return sorted(out, key=lambda fr: fr[0])


def build(doc: Any) -> dict[str, Any] | None:
    """The ghost document of one trainer animation or skeleton, or None when it has no seen joint."""
    frames = _frames(doc)
    seen = [[_xyz(joints.get(n)) for n in JOINTS] for _, joints in frames]
    ys = [p[1] for pts in seen for p in pts if p is not None]
    if not ys or max(ys) - min(ys) <= 0:
        return None
    top, height = max(ys), max(ys) - min(ys)
    out = []
    for (t, _), pts in zip(frames, seen):
        out.append({"t": round(t, 3), "pts": [
            None if p is None else [round(0.5 + p[0] / height, 4), round((top - p[1]) / height, 4)] for p in pts]})
    return {"format": FORMAT, "box": "body", "mirrored": False, "image_size": [1, 1], "joints": list(JOINTS),
            "bones": [list(b) for b in BONES], "frames": out}


def for_entry(child: Any, entry_id: str) -> tuple[int, dict[str, Any]]:
    """`(200, ghost)`; `(200, {available: false})` for an entry with no trainer joints; `(404, error)` for no entry."""
    manifest = child.get_entry(entry_id)
    if not isinstance(manifest, dict):
        return 404, {"error": MSG_ENTRY}
    for key in ("animation", "skeleton"):
        name = manifest.get(key)
        raw = child.get_entry_file(entry_id, str(name)) if isinstance(name, str) and name else None
        if raw is None:
            continue
        try:
            ghost = build(json.loads(raw.decode("utf-8")))
        except (ValueError, UnicodeDecodeError):
            ghost = None
        if ghost is not None:
            return 200, {**ghost, "available": True, "entry_id": entry_id, "source": key}
    return 200, {"available": False, "entry_id": entry_id, "reason": MSG_NONE}  # not an error: the page shows no ghost


def handle(h: Any, method: str, route: str) -> bool:
    """Answer `ghost/<entry_id>.json`; False for any other route."""
    m = ROUTE_RE.match(route)
    if not m or method not in ("GET", "HEAD"):
        return False
    status, body = for_entry(h.app.child, m.group("id"))
    if status == 200:
        h._json(200, body)
    else:
        h._error(status, body["error"])
    return True
