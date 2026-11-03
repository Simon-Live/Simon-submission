"""Synthetic follower mesh, pose3d and replay.json for the heat tests (docs/specs/heat.md). Labelled synthetic."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct
from typing import Any

from part7 import mesh_files

JOINTS = list(mesh_files.JOINTS)
STAND = {
    "nose": (0, 0.68, 0.1), "left_eye": (0.03, 0.7, 0.09), "right_eye": (-0.03, 0.7, 0.09),
    "left_ear": (0.08, 0.7, 0), "right_ear": (-0.08, 0.7, 0),
    "left_shoulder": (0.2, 0.5, 0), "right_shoulder": (-0.2, 0.5, 0),
    "left_elbow": (0.2, 0.2, 0), "right_elbow": (-0.2, 0.2, 0), "left_wrist": (0.2, -0.1, 0), "right_wrist": (-0.2, -0.1, 0),
    "left_hip": (0.1, 0, 0), "right_hip": (-0.1, 0, 0), "left_knee": (0.1, -0.45, 0), "right_knee": (-0.1, -0.45, 0),
    "left_ankle": (0.1, -0.9, 0), "right_ankle": (-0.1, -0.9, 0),
}


def raise_knee(sk: dict[str, tuple[float, float, float]], side: str = "right") -> dict[str, tuple[float, float, float]]:
    """The thigh turned forward 90 degrees and the shin hanging: a knee raise."""
    out = dict(sk)
    hip = sk[f"{side}_hip"]
    out[f"{side}_knee"] = (hip[0], hip[1], hip[2] + 0.45)
    out[f"{side}_ankle"] = (hip[0], hip[1] - 0.45, hip[2] + 0.45)
    return out


def shape(sk: dict[str, tuple[float, float, float]], k: float) -> dict[str, tuple[float, float, float]]:
    """Another body in the same pose: every joint scaled about the origin (hip midpoint)."""
    return {n: (p[0] * k, p[1] * k, p[2] * k) for n, p in sk.items()}


def cluster(sk: dict[str, tuple[float, float, float]]) -> list[tuple[float, float, float]]:
    """Three vertices around each joint, label = joint index."""
    out = []
    for n in JOINTS:
        x, y, z = sk[n]
        out += [(x, y, z), (x + 0.01, y, z), (x, y + 0.01, z)]
    return out


def write_pair(folder: Path, skeletons: list[dict | None]) -> None:
    """mesh3d.json, mesh3d.bin and pose3d.json for the frames; None is a frame without a person."""
    folder.mkdir(parents=True, exist_ok=True)
    n = len(JOINTS) * 3
    faces = [t for j in range(len(JOINTS)) for t in [(3 * j, 3 * j + 1, 3 * j + 2)]]
    faces += [(3 * j, 3 * j + 3, 3 * j + 4) for j in range(len(JOINTS) - 1)]
    fb = b"".join(struct.pack("<3H", *f) for f in faces)
    fb += bytes(-len(fb) % 4)
    lab_off = len(fb)
    lb = bytes(j for j in range(len(JOINTS)) for _ in range(3))
    lb += bytes(-len(lb) % 4)
    blob, frames, poses = bytearray(fb + lb), [], []
    for i, sk in enumerate(skeletons):
        entry: dict[str, Any] = {"frame": i, "t_ms": i * 100.0, "people": []}
        if sk is not None:
            entry["people"] = [{"id": 0, "offset": len(blob)}]
            blob += b"".join(struct.pack("<3h", *(round(c / 0.0001) for c in v)) for v in cluster(sk))
            poses.append({"frame": i, "t_ms": i * 100.0, "people": [{"id": 0, "joints": {k: {"x": v[0], "y": v[1], "z": v[2], "conf": 1.0} for k, v in sk.items()}}]})
        frames.append(entry)
    header = {"format": "part2.mesh3d/2026-10-31", "bin": "mesh3d.bin", "vertex_count": n, "face_count": len(faces),
              "faces": {"offset": 0, "dtype": "uint16"}, "vertices": {"dtype": "int16", "unit_m": 0.0001},
              "vertex_joint": {"offset": lab_off, "names": JOINTS}, "bin_sha256": hashlib.sha256(bytes(blob)).hexdigest(),
              "bin_bytes": len(blob), "frames": frames}
    (folder / "mesh3d.json").write_text(json.dumps(header))
    (folder / "mesh3d.bin").write_bytes(bytes(blob))
    (folder / "pose3d.json").write_text(json.dumps({"frames": poses}))


def replay(trainer: list[dict], mirrored: bool = False) -> dict[str, Any]:
    """A replay.json whose trainer frame i answers follower frame i (identity DTW) at 10 fps."""
    n = len(trainer)
    return {"format": "simon.replay.v1", "joints": JOINTS, "follower_t": [i * 0.1 for i in range(n)], "exp_to_fol": list(range(n)),
            "expected": [[list(t[j]) for j in JOINTS] for t in trainer]}
