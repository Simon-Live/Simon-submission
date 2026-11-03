"""A binary glTF 2.0 of one or two rigged, animated figures (docs/specs/take-ar.md, TICKET-282).

`build_glb([figure, ghost?])` writes a skinned mesh per figure (17 joints, two bones per vertex), one animation named
"take" that plays every figure (rotation of each joint, translation of the hips) and a flat-colour material. No image,
texture, UV set or colour from the source video is written: the surface is the measured body shape only. Standard
glTF only, so model-viewer shows it (Scene Viewer on Android, Quick Look through the USDZ on iOS, WebXR).
"""

from __future__ import annotations

import json
import struct
from typing import Any

from part7 import take_rig as rig

LICENCE = "SAM 3D Body: SAM License (Meta, 2025-11-19); MHR body model: Apache-2.0 (facebookresearch/MHR)"
GENERATOR = "Simon Part 7 take-ar"
ANIMATION = "take"
BODY_RGBA = (0.80, 0.62, 0.50, 1.0)  # a flat skin tone for the person; the ghost is the same hue, see-through
GHOST_RGBA = (0.45, 0.70, 0.95, 0.45)
FLOAT, USHORT, UINT, UBYTE = 5126, 5123, 5125, 5121


class _Buffer:
    """The binary chunk and its views and accessors, 4-byte aligned."""

    def __init__(self) -> None:
        self.data = bytearray()
        self.views: list[dict[str, Any]] = []
        self.accessors: list[dict[str, Any]] = []

    def add(self, raw: bytes, comp: int, count: int, kind: str, target: int | None = None, bounds: bool = False,
            values: list[float] | None = None, normalized: bool = False) -> int:
        while len(self.data) % 4:
            self.data.append(0)
        view: dict[str, Any] = {"buffer": 0, "byteOffset": len(self.data), "byteLength": len(raw)}
        if target:
            view["target"] = target
        self.data += raw
        self.views.append(view)
        acc: dict[str, Any] = {"bufferView": len(self.views) - 1, "componentType": comp, "count": count, "type": kind}
        if normalized:
            acc["normalized"] = True
        if bounds and values is not None:
            width = {"VEC3": 3, "SCALAR": 1, "VEC4": 4}[kind]
            cols = [values[i::width] for i in range(width)]
            acc["min"], acc["max"] = [min(c) for c in cols], [max(c) for c in cols]
        self.accessors.append(acc)
        return len(self.accessors) - 1


def _normals(positions: list[rig.Vec], faces: list[int]) -> list[float]:
    acc = [[0.0, 0.0, 0.0] for _ in positions]
    for t in range(0, len(faces), 3):
        a, b, c = faces[t], faces[t + 1], faces[t + 2]
        n = rig.cross(rig.sub(positions[b], positions[a]), rig.sub(positions[c], positions[a]))
        for v in (a, b, c):
            acc[v][0] += n[0]
            acc[v][1] += n[1]
            acc[v][2] += n[2]
    out: list[float] = []
    for n in acc:
        u = rig.unit((n[0], n[1], n[2])) or (0.0, 1.0, 0.0)
        out += u
    return out


def _flat(vs: list[tuple[float, ...]]) -> list[float]:
    return [c for v in vs for c in v]


def _figure(buf: _Buffer, fig: rig.Figure, prefix: str, nodes: list[dict[str, Any]], skins: list[dict[str, Any]],
            meshes: list[dict[str, Any]], materials: list[dict[str, Any]], channels: list[dict[str, Any]],
            samplers: list[dict[str, Any]], rgba: tuple[float, float, float, float], ghost: bool) -> int:
    """Add one figure's nodes, skin, mesh, material and animation; returns the index of its root node."""
    base = len(nodes)
    joint_ix = [base + i for i in range(len(rig.NAMES))]
    for i, n in enumerate(rig.NAMES):
        node: dict[str, Any] = {"name": prefix + n, "translation": [round(c, 6) for c in fig.local_offset(i)]}
        kids = [joint_ix[j] for j, p in enumerate(rig.PARENT) if p == i]
        if kids:
            node["children"] = kids
        nodes.append(node)
    root = len(nodes)
    mesh_node = root + 1
    nodes.append({"name": prefix + "figure", "children": [joint_ix[0], mesh_node]})
    nodes.append({"name": prefix + "body", "mesh": len(meshes), "skin": len(skins)})
    ibm = _flat([(1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, -h[0], -h[1], -h[2], 1) for h in fig.bone_head])
    skins.append({"name": prefix + "skin", "joints": joint_ix, "skeleton": joint_ix[0],
                  "inverseBindMatrices": buf.add(struct.pack(f"<{len(ibm)}f", *ibm), FLOAT, len(fig.bone_head), "MAT4")})
    pos = _flat(fig.positions)
    nv = len(fig.positions)
    big = nv > 65535
    joints = b"".join(struct.pack("<4B", b0, b1, 0, 0) for b0, b1 in fig.bones)
    wts = _flat([(w0, w1, 0.0, 0.0) for w0, w1 in fig.weights])
    nrm = _normals(fig.positions, fig.faces)
    attrs = {
        "POSITION": buf.add(struct.pack(f"<{len(pos)}f", *pos), FLOAT, nv, "VEC3", 34962, True, pos),
        "NORMAL": buf.add(struct.pack(f"<{len(nrm)}f", *nrm), FLOAT, nv, "VEC3", 34962),
        "JOINTS_0": buf.add(joints, UBYTE, nv, "VEC4", 34962),
        "WEIGHTS_0": buf.add(struct.pack(f"<{len(wts)}f", *wts), FLOAT, nv, "VEC4", 34962),
    }
    idx = buf.add(struct.pack(f"<{len(fig.faces)}{'I' if big else 'H'}", *fig.faces), UINT if big else USHORT,
                  len(fig.faces), "SCALAR", 34963)
    meshes.append({"name": prefix + "body", "primitives": [{"attributes": attrs, "indices": idx, "material": len(materials)}]})
    mat: dict[str, Any] = {"name": prefix + "material", "pbrMetallicRoughness": {
        "baseColorFactor": list(rgba), "metallicFactor": 0.0, "roughnessFactor": 0.85}}
    if ghost:
        mat["alphaMode"] = "BLEND"
    materials.append(mat)
    times = [round(t, 5) for t in fig.times]
    t_acc = buf.add(struct.pack(f"<{len(times)}f", *times), FLOAT, len(times), "SCALAR", bounds=True, values=times)
    _channels(buf, fig, joint_ix, t_acc, channels, samplers)
    return root


def _channels(buf: _Buffer, fig: rig.Figure, joint_ix: list[int], t_acc: int, channels: list[dict[str, Any]],
              samplers: list[dict[str, Any]]) -> None:
    for i in range(len(rig.NAMES)):
        qs, prev = [], None
        for frame in fig.rotations:  # one hemisphere, so linear interpolation takes the short way
            q = frame[i]
            if prev is not None and sum(a * b for a, b in zip(q, prev)) < 0:
                q = (-q[0], -q[1], -q[2], -q[3])
            qs.append(q)
            prev = q
        flat = _flat(qs)
        out = buf.add(struct.pack(f"<{len(flat)}f", *flat), FLOAT, len(qs), "VEC4")
        samplers.append({"input": t_acc, "output": out, "interpolation": "LINEAR"})
        channels.append({"sampler": len(samplers) - 1, "target": {"node": joint_ix[i], "path": "rotation"}})
    hips = _flat(fig.hips)
    out = buf.add(struct.pack(f"<{len(hips)}f", *hips), FLOAT, len(fig.hips), "VEC3")
    samplers.append({"input": t_acc, "output": out, "interpolation": "LINEAR"})
    channels.append({"sampler": len(samplers) - 1, "target": {"node": joint_ix[0], "path": "translation"}})


def build_glb(figures: list[rig.Figure], extras: dict[str, Any] | None = None) -> bytes:
    """The GLB of `figures[0]` (the person) and, when given, `figures[1]` as a see-through ghost on the same spot."""
    if not figures or len(figures) > 2:
        raise rig.RigError("A take file holds one or two figures.")
    buf = _Buffer()
    nodes: list[dict[str, Any]] = []
    skins: list[dict[str, Any]] = []
    meshes: list[dict[str, Any]] = []
    materials: list[dict[str, Any]] = []
    channels: list[dict[str, Any]] = []
    samplers: list[dict[str, Any]] = []
    roots = []
    for k, fig in enumerate(figures):
        prefix = "" if k == 0 else "ghost_"
        roots.append(_figure(buf, fig, prefix, nodes, skins, meshes, materials, channels, samplers,
                             GHOST_RGBA if k else BODY_RGBA, bool(k)))
    scene_root = len(nodes)
    nodes.append({"name": "take", "children": roots})
    doc: dict[str, Any] = {
        "asset": {"version": "2.0", "generator": GENERATOR, "copyright": LICENCE,
                  "extras": {"figures": [f.name for f in figures], "joints": len(rig.NAMES),
                             "duration_s": round(max(f.duration_s for f in figures), 3), **(extras or {})}},
        "scene": 0, "scenes": [{"name": "take", "nodes": [scene_root]}], "nodes": nodes, "skins": skins,
        "meshes": meshes, "materials": materials,
        "animations": [{"name": ANIMATION, "channels": channels, "samplers": samplers}],
        "buffers": [{"byteLength": len(buf.data)}], "bufferViews": buf.views, "accessors": buf.accessors,
    }
    return _pack(doc, bytes(buf.data))


def _pack(doc: dict[str, Any], blob: bytes) -> bytes:
    js = json.dumps(doc, separators=(",", ":")).encode("utf-8")
    js += b" " * (-len(js) % 4)
    blob += b"\0" * (-len(blob) % 4)
    total = 12 + 8 + len(js) + 8 + len(blob)
    return (struct.pack("<4sII", b"glTF", 2, total) + struct.pack("<I4s", len(js), b"JSON") + js
            + struct.pack("<I4s", len(blob), b"BIN\0") + blob)


def read_glb(data: bytes) -> tuple[dict[str, Any], bytes]:
    """The JSON document and the binary chunk of a GLB (for tests and tools)."""
    magic, version, total = struct.unpack_from("<4sII", data, 0)
    if magic != b"glTF" or version != 2 or total != len(data):
        raise ValueError("not a GLB 2.0")
    n, kind = struct.unpack_from("<I4s", data, 12)
    doc = json.loads(data[20:20 + n])
    m, kind2 = struct.unpack_from("<I4s", data, 20 + n)
    return doc, data[28 + n:28 + n + m] if kind2 == b"BIN\0" else b""
