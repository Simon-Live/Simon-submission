"""The follower's 2D skeleton on their own video (docs/specs/models-and-skeleton-data.md R2, TICKET-154).

Part 2's `pose3d.json` holds canonical joints in metres and `camera.json` the per frame pose that puts them back into
the camera: `p_cam = R @ p + t`, then the intrinsics `K` (Part 2 `contracts/camera.schema.json`). Projecting them gives
the joints where Part 2 saw them in the clip. Part 7 adds no measurement: it only re-expresses Part 2's numbers as
shares of the image so the browser can draw them over the video at any size.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

JOINTS = (
    "nose", "left_eye", "right_eye", "left_ear", "right_ear", "left_shoulder", "right_shoulder", "left_elbow",
    "right_elbow", "left_wrist", "right_wrist", "left_hip", "right_hip", "left_knee", "right_knee", "left_ankle",
    "right_ankle",
)
# The same COCO-17 bones the 3D views draw (web/compare.js BODY_BONES), as joint index pairs.
BONES = (
    (0, 1), (0, 2), (1, 3), (2, 4), (0, 5), (0, 6), (5, 6), (11, 12), (5, 11), (6, 12), (5, 7), (7, 9), (6, 8),
    (8, 10), (11, 13), (13, 15), (12, 14), (14, 16),
)
MIN_DEPTH_M = 0.05  # a joint this close to (or behind) the camera has no place on the image


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _pick(people: list[Any], person_id: str | None) -> Any:
    if not isinstance(people, list) or not people:
        return None
    if person_id is not None:
        for p in people:
            if isinstance(p, dict) and str(p.get("id")) == str(person_id):
                return p
    return people[0] if isinstance(people[0], dict) else None


def project(joint: Any, rot: list[list[float]], trans: list[float], k: list[list[float]],
            size: tuple[float, float]) -> list[float] | None:
    """`[u, v]` as shares of the image for one canonical joint `{x, y, z, conf}`; None when unseen or behind."""
    if not isinstance(joint, dict):
        return None
    try:
        x, y, z = float(joint["x"]), float(joint["y"]), float(joint["z"])
        if float(joint.get("conf", 1.0)) <= 0:
            return None
        cam = [rot[i][0] * x + rot[i][1] * y + rot[i][2] * z + trans[i] for i in range(3)]
        if cam[2] < MIN_DEPTH_M:
            return None
        u = k[0][0] * cam[0] / cam[2] + k[0][2]
        v = k[1][1] * cam[1] / cam[2] + k[1][2]
    except (KeyError, TypeError, ValueError, IndexError):
        return None
    return [round(u / size[0], 4), round(v / size[1], 4)]


def build(part2_dir: Path, person_id: str | None = None) -> dict[str, Any] | None:
    """The skeleton document of a follow job's `work/follower/part2` folder, or None when it cannot be made."""
    pose, cam = _load(part2_dir / "pose3d.json"), _load(part2_dir / "camera.json")
    if not isinstance(pose, dict) or not isinstance(cam, dict):
        return None
    try:
        k = cam["K"]
        size = (float(cam["image_size"][0]), float(cam["image_size"][1]))
    except (KeyError, TypeError, ValueError, IndexError):
        return None
    if size[0] <= 0 or size[1] <= 0:
        return None
    cams = {f.get("frame"): f for f in cam.get("frames") or [] if isinstance(f, dict)}
    frames = []
    for f in pose.get("frames") or []:
        if not isinstance(f, dict) or not isinstance(f.get("t_ms"), (int, float)):
            continue
        who = _pick(f.get("people"), person_id)
        place = _pick((cams.get(f.get("frame")) or {}).get("people"), str(who.get("id"))) if who else None
        if who is None or place is None:
            frames.append({"t": round(f["t_ms"] / 1000, 3), "pts": [None] * len(JOINTS)})
            continue
        joints = who.get("joints") or {}
        pts = [project(joints.get(n), place.get("R"), place.get("t"), k, size) for n in JOINTS]
        frames.append({"t": round(f["t_ms"] / 1000, 3), "pts": pts})
    if not frames:
        return None
    return {"format": "simon.skeleton2d.v1", "image_size": [size[0], size[1]], "joints": list(JOINTS),
            "bones": [list(b) for b in BONES], "frames": frames}
