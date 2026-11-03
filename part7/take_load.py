"""Read one person's `mesh3d.json`, `mesh3d.bin` and `pose3d.json` (Part 2) into a rigged `Figure` (docs/specs/take-ar.md).

The mesh header and bin layout is Part 2's CONTRACT.md "mesh3d.json + mesh3d.bin"; the rest frame is the one the
result page's person skin uses (mesh_files.rest_frame). A frame is kept when the mesh and pose3d both hold the person
with all 17 joints seen; the others are left out and the player carries on from the last pose it has.
"""

from __future__ import annotations

import array
import struct
import sys
from pathlib import Path
from typing import Any

from part7 import job_lookup, mesh_files, take_rig

MAX_BIN_BYTES = 64 * 1024 * 1024  # a mesh bin larger than this is not read (a 3 minute take at 2500 vertices is 20 MB)


def _faces(header: dict[str, Any], blob: bytes) -> list[int] | None:
    count = header.get("face_count")
    spec = header.get("faces") or {}
    code = {"uint16": "H", "uint32": "I"}.get(spec.get("dtype"))
    if not isinstance(count, int) or count < 1 or code is None:
        return None
    arr = array.array(code)
    start, end = int(spec.get("offset", 0)), int(spec.get("offset", 0)) + count * 3 * arr.itemsize
    if end > len(blob):
        return None
    arr.frombytes(blob[start:end])
    if sys.byteorder == "big":
        arr.byteswap()
    return list(arr)


def _verts(blob: bytes, offset: int, n: int, unit_m: float) -> list[take_rig.Vec] | None:
    if offset < 0 or offset + n * 6 > len(blob):
        return None
    arr = array.array("h")
    arr.frombytes(blob[offset:offset + n * 6])
    if sys.byteorder == "big":
        arr.byteswap()
    return [(arr[3 * i] * unit_m, arr[3 * i + 1] * unit_m, arr[3 * i + 2] * unit_m) for i in range(n)]


def _mirror_names(names: list[str]) -> list[str]:
    out = []
    for n in names:
        side, _, rest = n.partition("_")
        out.append({"left": "right", "right": "left"}[side] + "_" + rest if side in ("left", "right") else n)
    return out


def load_figure(folder: Path, name: str, person: int | None = None) -> take_rig.Figure | None:
    """The figure of the person in `folder`, or None when a file is missing, malformed, or fewer than two frames are usable."""
    header = job_lookup.read_json(folder / "mesh3d.json")
    pose = job_lookup.read_json(folder / "pose3d.json")
    bin_path = folder / "mesh3d.bin"
    if not isinstance(header, dict) or not isinstance(pose, dict) or not bin_path.is_file() or bin_path.is_symlink():
        return None
    try:
        if bin_path.stat().st_size > MAX_BIN_BYTES:
            return None
        blob = bin_path.read_bytes()
        return _figure(name, header, pose, blob, person)
    except (OSError, ValueError, KeyError, TypeError, IndexError, struct.error):
        return None


def _figure(name: str, header: dict[str, Any], pose: dict[str, Any], blob: bytes, person: int | None) -> take_rig.Figure | None:
    n = header.get("vertex_count")
    unit_m = float((header.get("vertices") or {}).get("unit_m", 0.0001))
    faces = _faces(header, blob)
    if not isinstance(n, int) or n < 1 or faces is None or max(faces) >= n:
        return None
    mirrored = pose.get("mirrored") is True
    if mirrored:  # Part 2 CONTRACT.md: negate x, swap the left_ and right_ names, reverse the winding
        faces = [v for t in range(0, len(faces), 3) for v in (faces[t], faces[t + 2], faces[t + 1])]
    pose_by_frame = {f.get("frame"): f for f in pose.get("frames") or [] if isinstance(f, dict)}
    frames: list[take_rig.Frame] = []
    mesh_ix: list[int] = []
    for index, mf in enumerate(header.get("frames") or []):
        people = [p for p in mf.get("people") or [] if isinstance(p, dict)]
        mine = [p for p in people if person is None or p.get("id") == person]
        pf = pose_by_frame.get(mf.get("frame"))
        if not mine or pf is None:
            continue
        match = [p for p in pf.get("people") or [] if isinstance(p, dict) and p.get("id") == mine[0].get("id")]
        joints = mesh_files._keypoints(match[0]) if match else None
        verts = _verts(blob, int(mine[0]["offset"]), n, unit_m)
        if joints is None or verts is None:
            continue
        j3, v3 = _flip(joints, verts, mirrored)
        frames.append(take_rig.Frame(float(mf["t_ms"]) / 1000.0, j3, v3))
        mesh_ix.append(index)
    rest = mesh_files.rest_frame(header, pose)
    if rest is None or rest["index"] not in mesh_ix:
        return None
    return take_rig.build_figure(name, faces, frames, mesh_ix.index(rest["index"]))


def _flip(joints: dict[str, list[float]], verts: list[take_rig.Vec], mirrored: bool) -> tuple[dict[str, take_rig.Vec], list[take_rig.Vec]]:
    """The joints as tuples and the vertices, mirrored (x negated, left and right swapped) when the clip was."""
    if not mirrored:
        return {k: (v[0], v[1], v[2]) for k, v in joints.items()}, verts
    swap = dict(zip(_mirror_names(list(joints)), joints))
    return ({k: (-joints[src][0], joints[src][1], joints[src][2]) for k, src in swap.items()},
            [(-x, y, z) for x, y, z in verts])
