#!/usr/bin/env python3
"""Read the rest (bind) joints of a rigged GLB with the standard library only (docs/specs/model-retarget.md, AC-RT9).

Prints {"schema": "simon.rest.v1", ...bones: {canonical: {head, tail, world}}} in the world frame after every node
transform, matrices included. --normalize applies one rotation so that up is +Y and the character's left is +X,
which is the frame web/skin/retarget.js expects (the rotation is printed as "fix").
Exit 0 on success, 2 with one stderr line on bad input.
"""
from __future__ import annotations

import argparse
import json
import math
import struct
import sys
from pathlib import Path

Vec = list
SIDES = (("left", "l", "L"), ("right", "r", "R"))


class RestError(Exception):
    pass


def _presets() -> dict[str, dict[str, str]]:
    ual: dict[str, str] = {
        "pelvis": "hips", "spine_01": "spine", "spine_02": "chest", "spine_03": "upperChest",
        "neck_01": "neck", "Head": "head",
    }
    fig: dict[str, str] = {
        "torso_joint_1": "hips", "torso_joint_2": "spine", "torso_joint_3": "chest", "neck_joint_1": "neck",
        "neck_joint_2": "head",
    }
    for side, lc, uc in SIDES:
        ual.update({
            f"clavicle_{lc}": f"{side}Shoulder", f"upperarm_{lc}": f"{side}UpperArm",
            f"lowerarm_{lc}": f"{side}LowerArm", f"hand_{lc}": f"{side}Hand", f"thigh_{lc}": f"{side}UpperLeg",
            f"calf_{lc}": f"{side}LowerLeg", f"foot_{lc}": f"{side}Foot", f"ball_{lc}": f"{side}Toes",
        })
        fig.update({
            f"arm_joint_{uc}_1": f"{side}UpperArm", f"arm_joint_{uc}_2": f"{side}LowerArm",
            f"arm_joint_{uc}_3": f"{side}Hand", f"leg_joint_{uc}_1": f"{side}UpperLeg",
            f"leg_joint_{uc}_2": f"{side}LowerLeg", f"leg_joint_{uc}_3": f"{side}Foot",
            f"leg_joint_{uc}_5": f"{side}Toes",
        })
    return {"ual": ual, "riggedfigure": fig, "canonical": {}}


PRESETS = _presets()
TAIL_CHILD = {
    "hips": ["spine"], "spine": ["chest", "upperChest", "neck"], "chest": ["upperChest", "neck"],
    "upperChest": ["neck"], "neck": ["head"],
    **{f"{s}Shoulder": [f"{s}UpperArm"] for s, _, _ in SIDES},
    **{f"{s}UpperArm": [f"{s}LowerArm"] for s, _, _ in SIDES},
    **{f"{s}LowerArm": [f"{s}Hand"] for s, _, _ in SIDES},
    **{f"{s}UpperLeg": [f"{s}LowerLeg"] for s, _, _ in SIDES},
    **{f"{s}LowerLeg": [f"{s}Foot"] for s, _, _ in SIDES},
    **{f"{s}Foot": [f"{s}Toes"] for s, _, _ in SIDES},
}
REQUIRED = ["hips", "spine", "head"] + [
    f"{s}{b}" for s, _, _ in SIDES for b in ("UpperArm", "LowerArm", "Hand", "UpperLeg", "LowerLeg", "Foot")
]


def read_glb_json(data: bytes) -> dict:
    if len(data) < 20 or data[:4] != b"glTF":
        raise RestError("not a GLB file")
    length, kind = struct.unpack("<II", data[12:20])
    if kind != 0x4E4F534A or 20 + length > len(data):
        raise RestError("the GLB JSON chunk is missing or truncated")
    try:
        return json.loads(data[20:20 + length])
    except ValueError as e:
        raise RestError("the GLB JSON chunk is not valid JSON") from e


def mat_mul(a: list[float], b: list[float]) -> list[float]:
    """Column-major 4x4 product a * b."""
    return [sum(a[k * 4 + r] * b[c * 4 + k] for k in range(4)) for c in range(4) for r in range(4)]


def local_matrix(node: dict) -> list[float]:
    if "matrix" in node:
        m = node["matrix"]
        if len(m) != 16:
            raise RestError("a node matrix does not have 16 numbers")
        return [float(v) for v in m]
    x, y, z, w = node.get("rotation", [0, 0, 0, 1])
    sx, sy, sz = node.get("scale", [1, 1, 1])
    tx, ty, tz = node.get("translation", [0, 0, 0])
    return [
        (1 - 2 * (y * y + z * z)) * sx, (2 * (x * y + z * w)) * sx, (2 * (x * z - y * w)) * sx, 0,
        (2 * (x * y - z * w)) * sy, (1 - 2 * (x * x + z * z)) * sy, (2 * (y * z + x * w)) * sy, 0,
        (2 * (x * z + y * w)) * sz, (2 * (y * z - x * w)) * sz, (1 - 2 * (x * x + y * y)) * sz, 0,
        tx, ty, tz, 1,
    ]


def world_matrices(nodes: list[dict]) -> list[list[float]]:
    parent = {c: i for i, n in enumerate(nodes) for c in n.get("children", [])}
    cache: dict[int, list[float]] = {}

    def of(i: int, depth: int = 0) -> list[float]:
        if depth > len(nodes):
            raise RestError("the node tree has a cycle")
        if i not in cache:
            m = local_matrix(nodes[i])
            cache[i] = mat_mul(of(parent[i], depth + 1), m) if i in parent else m
        return cache[i]

    return [of(i) for i in range(len(nodes))]


def mat_to_quat(m: list[float]) -> Vec:
    """Rotation of a column-major matrix whose columns may be scaled."""
    cols = []
    for c in range(3):
        v = m[c * 4:c * 4 + 3]
        n = math.sqrt(sum(a * a for a in v)) or 1.0
        cols.append([a / n for a in v])
    (m00, m10, m20), (m01, m11, m21), (m02, m12, m22) = cols
    tr = m00 + m11 + m22
    if tr > 0:
        s = math.sqrt(tr + 1) * 2
        q = [(m21 - m12) / s, (m02 - m20) / s, (m10 - m01) / s, 0.25 * s]
    elif m00 > m11 and m00 > m22:
        s = math.sqrt(1 + m00 - m11 - m22) * 2
        q = [0.25 * s, (m01 + m10) / s, (m02 + m20) / s, (m21 - m12) / s]
    elif m11 > m22:
        s = math.sqrt(1 + m11 - m00 - m22) * 2
        q = [(m01 + m10) / s, 0.25 * s, (m12 + m21) / s, (m02 - m20) / s]
    else:
        s = math.sqrt(1 + m22 - m00 - m11) * 2
        q = [(m02 + m20) / s, (m12 + m21) / s, 0.25 * s, (m10 - m01) / s]
    n = math.sqrt(sum(a * a for a in q))
    return [a / n for a in q]


def q_mul(a: Vec, b: Vec) -> Vec:
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return [
        aw * bx + ax * bw + ay * bz - az * by, aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw, aw * bw - ax * bx - ay * by - az * bz,
    ]


def q_rotate(q: Vec, v: Vec) -> Vec:
    x, y, z, w = q
    u = [x, y, z]
    t = [2 * c for c in _cross(u, v)]
    c = _cross(u, t)
    return [v[i] + w * t[i] + c[i] for i in range(3)]


def _cross(a: Vec, b: Vec) -> Vec:
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def q_between(a: Vec, b: Vec) -> Vec:
    """Smallest rotation taking unit vector a to unit vector b."""
    d = sum(x * y for x, y in zip(a, b))
    if d < -0.999999:
        axis = _cross(a, [1, 0, 0]) if abs(a[0]) < 0.9 else _cross(a, [0, 1, 0])
        n = math.sqrt(sum(c * c for c in axis))
        return [axis[0] / n, axis[1] / n, axis[2] / n, 0.0]
    c = _cross(a, b)
    q = [c[0], c[1], c[2], 1 + d]
    n = math.sqrt(sum(v * v for v in q))
    return [v / n for v in q]


def _unit(v: Vec) -> Vec:
    n = math.sqrt(sum(a * a for a in v))
    if n < 1e-12:
        raise RestError("two mapped bones share a position, cannot orient the character")
    return [a / n for a in v]


def normalize_fix(bones: dict) -> Vec:
    """Rotation that makes pelvis to shoulder-midpoint +Y and left minus right upper arm +X."""
    h = lambda n: bones[n]["head"]  # noqa: E731
    pelvis = [(a + b) / 2 for a, b in zip(h("leftUpperLeg"), h("rightUpperLeg"))]
    neck = [(a + b) / 2 for a, b in zip(h("leftUpperArm"), h("rightUpperArm"))]
    up_fix = q_between(_unit([a - b for a, b in zip(neck, pelvis)]), [0, 1, 0])
    lat = q_rotate(up_fix, [a - b for a, b in zip(h("leftUpperArm"), h("rightUpperArm"))])
    lat = _unit([lat[0], 0.0, lat[2]])
    yaw = q_between(lat, [1, 0, 0])
    return q_mul(yaw, up_fix)


def rest_joints(glb: bytes, preset: str = "canonical", name_map: dict[str, str] | None = None,
                normalize: bool = False, source: str = "") -> dict:
    j = read_glb_json(glb)
    nodes = j.get("nodes") or []
    if not j.get("skins"):
        raise RestError("the model has no skin")
    joints = {n for s in j["skins"] for n in s.get("joints", [])}
    mapping = dict(PRESETS[preset]) if name_map is None else dict(name_map)
    canon_of = {name: name for name in set(TAIL_CHILD) | {"head", "leftToes", "rightToes", "leftHand", "rightHand"}}
    if preset == "canonical":
        mapping = {**canon_of, **mapping}
    mats = world_matrices(nodes)
    bones: dict[str, dict] = {}
    for i in sorted(joints):
        canon = mapping.get(nodes[i].get("name", ""))
        if canon and canon not in bones:
            m = mats[i]
            bones[canon] = {"head": m[12:15], "tail": None, "world": mat_to_quat(m)}
    missing = [n for n in REQUIRED if n not in bones]
    if missing:
        raise RestError("mapped bones missing: " + ", ".join(missing))
    fix = normalize_fix(bones) if normalize else [0.0, 0.0, 0.0, 1.0]
    for name, b in bones.items():
        if normalize:
            b["head"] = q_rotate(fix, b["head"])
            b["world"] = q_mul(fix, b["world"])
    for name, b in bones.items():
        kid = next((k for k in TAIL_CHILD.get(name, []) if k in bones), None)
        b["tail"] = bones[kid]["head"] if kid else None
    r6 = lambda v: [round(a, 6) for a in v]  # noqa: E731
    out = {name: {"head": r6(b["head"]), "tail": r6(b["tail"]) if b["tail"] else None, "world": r6(b["world"])}
           for name, b in bones.items()}
    return {"schema": "simon.rest.v1", "source": source, "preset": preset, "fix": r6(fix), "bones": out}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("glb")
    ap.add_argument("--preset", choices=sorted(PRESETS), default="canonical")
    ap.add_argument("--map", help="JSON file {node name: canonical bone}, replaces the preset")
    ap.add_argument("--normalize", action="store_true")
    ap.add_argument("--source", default="")
    args = ap.parse_args(argv)
    try:
        data = Path(args.glb).read_bytes()
        name_map = json.loads(Path(args.map).read_text()) if args.map else None
        out = rest_joints(data, args.preset, name_map, args.normalize, args.source or Path(args.glb).name)
    except (OSError, ValueError, RestError) as e:
        print(f"rest_joints_from_glb: {e}", file=sys.stderr)
        return 2
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
