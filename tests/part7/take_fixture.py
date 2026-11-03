"""A small synthetic person for the take-AR tests: 17 joints, a tetrahedron on each, six frames (no real person)."""

from __future__ import annotations

import json
import math
import struct
from pathlib import Path

from part7 import take_rig as rig

N_FRAMES = 6
STEP_MS = 100.0
UNIT = 0.0001
REST = {
    "nose": (0, 0.68, 0.1), "left_eye": (0.03, 0.7, 0.08), "right_eye": (-0.03, 0.7, 0.08),
    "left_ear": (0.08, 0.68, 0), "right_ear": (-0.08, 0.68, 0), "left_shoulder": (0.2, 0.5, 0),
    "right_shoulder": (-0.2, 0.5, 0), "left_elbow": (0.45, 0.5, 0), "right_elbow": (-0.45, 0.5, 0),
    "left_wrist": (0.7, 0.5, 0), "right_wrist": (-0.7, 0.5, 0), "left_hip": (0.1, 0, 0), "right_hip": (-0.1, 0, 0),
    "left_knee": (0.1, -0.45, 0), "right_knee": (-0.1, -0.45, 0), "left_ankle": (0.1, -0.9, 0),
    "right_ankle": (-0.1, -0.9, 0),
}
TETRA = ((0.02, 0.02, 0.02), (-0.02, -0.02, 0.02), (-0.02, 0.02, -0.02), (0.02, -0.02, -0.02))
FACES = ((0, 1, 2), (0, 3, 1), (0, 2, 3), (1, 3, 2))


def pose_at(k: int) -> dict[str, tuple[float, float, float]]:
    """Frame k: the right forearm bends up by 15 degrees a frame (the elbow stays), the left knee comes forward."""
    j = dict(REST)
    ang = 0.26 * k
    ex, ey, _ = REST["right_elbow"]
    j["right_wrist"] = (ex - 0.25 * math.cos(ang), ey + 0.25 * math.sin(ang), 0.0)
    j["left_knee"] = (0.1, -0.45, 0.04 * k)
    return j


def write_person(folder: Path, frames: int = N_FRAMES, drop: tuple[int, ...] = (), mirrored: bool = False) -> None:
    """mesh3d.json, mesh3d.bin and pose3d.json in `folder`; frames in `drop` have no person in pose3d."""
    folder.mkdir(parents=True, exist_ok=True)
    names = list(rig.COCO)
    n = len(names) * 4
    faces = b"".join(struct.pack("<3H", *(4 * j + a for a in tri)) for j in range(len(names)) for tri in FACES)
    faces += b"\0" * (-len(faces) % 4)
    labels = bytes(j for j in range(len(names)) for _ in range(4))
    labels += b"\0" * (-len(labels) % 4)
    blob = bytearray(faces)
    label_offset = len(blob)
    blob += labels
    header_frames, pose_frames = [], []
    for k in range(frames):
        joints = pose_at(k)
        offset = len(blob)
        for name in names:
            for d in TETRA:
                blob += struct.pack("<3h", *(round((c + e) / UNIT) for c, e in zip(joints[name], d)))
        header_frames.append({"frame": k, "t_ms": k * STEP_MS, "people": [{"id": 0, "offset": offset}]})
        if k not in drop:
            pose_frames.append({"frame": k, "t_ms": k * STEP_MS, "people": [{"id": 0, "joints": {
                nm: {"x": v[0], "y": v[1], "z": v[2], "conf": 1.0} for nm, v in joints.items()}}]})
    header = {"format": "part2.mesh3d/2026-10-31", "bin": "mesh3d.bin", "vertex_count": n, "face_count": len(names) * 4,
              "faces": {"offset": 0, "dtype": "uint16"}, "vertices": {"dtype": "int16", "unit_m": UNIT},
              "vertex_joint": {"offset": label_offset, "names": names}, "frames": header_frames}
    pose: dict = {"frames": pose_frames}
    if mirrored:
        pose["mirrored"] = True
    (folder / "mesh3d.json").write_text(json.dumps(header), encoding="utf-8")
    (folder / "mesh3d.bin").write_bytes(bytes(blob))
    (folder / "pose3d.json").write_text(json.dumps(pose), encoding="utf-8")
