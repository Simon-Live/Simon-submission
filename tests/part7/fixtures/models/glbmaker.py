"""Test helper: build small rigged GLB files by hand (a 15-bone humanoid) so hostile and odd variants can be made on demand.

Not product code. `humanoid()` returns GLB bytes; keyword options bend one thing at a time (names, up axis, units,
facing, extensions, URIs, weights).
"""

from __future__ import annotations

import json
import struct
from typing import Any

# canonical -> (parent canonical, world position of a model facing +Z, Y up, in metres, T pose)
BODY: dict[str, tuple[str | None, tuple[float, float, float]]] = {
    "hips": (None, (0, 1.0, 0)), "spine": ("hips", (0, 1.15, 0)), "chest": ("spine", (0, 1.35, 0)),
    "neck": ("chest", (0, 1.55, 0)), "head": ("neck", (0, 1.65, 0)),
    "leftUpperArm": ("chest", (0.2, 1.5, 0)), "leftLowerArm": ("leftUpperArm", (0.5, 1.5, 0)), "leftHand": ("leftLowerArm", (0.75, 1.5, 0)),
    "rightUpperArm": ("chest", (-0.2, 1.5, 0)), "rightLowerArm": ("rightUpperArm", (-0.5, 1.5, 0)), "rightHand": ("rightLowerArm", (-0.75, 1.5, 0)),
    "leftUpperLeg": ("hips", (0.1, 0.95, 0)), "leftLowerLeg": ("leftUpperLeg", (0.1, 0.5, 0)), "leftFoot": ("leftLowerLeg", (0.1, 0.08, 0)),
    "rightUpperLeg": ("hips", (-0.1, 0.95, 0)), "rightLowerLeg": ("rightUpperLeg", (-0.1, 0.5, 0)), "rightFoot": ("rightLowerLeg", (-0.1, 0.08, 0)),
}
ORDER = list(BODY)


def _pad(data: bytes, fill: bytes) -> bytes:
    return data + fill * (-len(data) % 4)


def _rot(p: tuple[float, float, float], up: str, face: str) -> tuple[float, float, float]:
    x, y, z = p
    if face == "-z":
        x, z = -x, -z
    if up == "z":  # Z up: the figure lies on its back looking at -Y, left leg stays at +X
        return (x, -z, y)
    return (x, y, z)


def humanoid(names: dict[str, str] | None = None, *, up: str = "y", face: str = "+z", unit: float = 1.0, extra: dict[str, Any] | None = None,
             buffer_uri: str | None = None, image_uri: str | None = None, skin: bool = True, weights: list[float] | None = None,
             required: list[str] | None = None, joint_index: int | None = None, ibm: bool = True, joints_attr: bool = True,
             images: list[bytes] | None = None, parents: dict[str, str | None] | None = None, extra_nodes: list[dict[str, Any]] | None = None,
             root_matrix: list[float] | None = None, skip: tuple[str, ...] = ()) -> bytes:
    """GLB bytes of a humanoid. `names` renames canonical bones; `parents` re-parents some; `skip` leaves bones out."""
    names = names or {}
    parents = {**{k: v[0] for k, v in BODY.items()}, **(parents or {})}
    order = [c for c in ORDER if c not in skip]
    world = {c: tuple(v * unit for v in _rot(BODY[c][1], up, face)) for c in order}
    index = {c: i for i, c in enumerate(order)}
    nodes: list[dict[str, Any]] = []
    for c in order:
        parent = parents[c]
        base = world[parent] if parent in world else (0, 0, 0)
        node: dict[str, Any] = {"name": names.get(c, c), "translation": [world[c][i] - base[i] for i in range(3)]}
        kids = [index[k] for k in order if parents[k] == c]
        if kids:
            node["children"] = kids
        nodes.append(node)
    for extra_node in extra_nodes or []:
        nodes.append(extra_node)
    mesh_node = len(nodes)
    nodes.append({"name": "Body", "mesh": 0, **({"skin": 0} if skin else {})})
    roots = [index[c] for c in order if parents[c] not in world]
    scene_nodes = roots + [mesh_node] + [mesh_node - i - 1 for i in range(len(extra_nodes or []))]
    if root_matrix is not None:
        nodes.append({"name": "Z_UP", "matrix": root_matrix, "children": roots})
        scene_nodes = [len(nodes) - 1, mesh_node]
    chunks: list[bytes] = []
    views: list[dict[str, Any]] = []
    accessors: list[dict[str, Any]] = []

    def add(data: bytes, comp: int, count: int, kind: str, **more: Any) -> int:
        offset = sum(len(c) for c in chunks)
        chunks.append(_pad(data, b"\0"))
        views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(data)})
        accessors.append({"bufferView": len(views) - 1, "componentType": comp, "count": count, "type": kind, **more})
        return len(accessors) - 1

    pts = [(-0.2, 0.0, -0.1), (0.2, 0.0, -0.1), (0.0, 1.7 * unit, 0.1)]
    pos = add(b"".join(struct.pack("<3f", *p) for p in pts), 5126, 3, "VEC3", min=[-0.2, 0.0, -0.1], max=[0.2, 1.7 * unit, 0.1])
    attrs: dict[str, int] = {"POSITION": pos}
    if skin:
        j = joint_index if joint_index is not None else 0
        wts = weights or [1.0, 0.0, 0.0, 0.0]
        if joints_attr:
            attrs["JOINTS_0"] = add(struct.pack("<4B", j, 0, 0, 0) * 3, 5121, 3, "VEC4")
        attrs["WEIGHTS_0"] = add(struct.pack("<4f", *wts) * 3, 5126, 3, "VEC4")
    gltf: dict[str, Any] = {"asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": scene_nodes}], "nodes": nodes,
                            "meshes": [{"primitives": [{"attributes": attrs, "mode": 4}]}]}
    if skin:
        skin_doc: dict[str, Any] = {"joints": list(range(len(order)))}
        if ibm:
            mats = b"".join(struct.pack("<16f", 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, -world[c][0], -world[c][1], -world[c][2], 1) for c in order)
            skin_doc["inverseBindMatrices"] = add(mats, 5126, len(order), "MAT4")
        gltf["skins"] = [skin_doc]
    for blob in images or []:
        offset = sum(len(c) for c in chunks)
        chunks.append(_pad(blob, b"\0"))
        views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(blob)})
        gltf.setdefault("images", []).append({"bufferView": len(views) - 1, "mimeType": "image/png"})
    if image_uri is not None:
        gltf.setdefault("images", []).append({"uri": image_uri})
    blob = b"".join(chunks)
    gltf["bufferViews"], gltf["accessors"] = views, accessors
    gltf["buffers"] = [{"byteLength": len(blob), **({"uri": buffer_uri} if buffer_uri else {})}]
    gltf.update(extra or {})
    return pack(gltf, blob if not buffer_uri else b"")


def pack(gltf: dict[str, Any], blob: bytes) -> bytes:
    body = _pad(json.dumps(gltf).encode(), b" ")
    out = struct.pack("<II", len(body), 0x4E4F534A) + body
    if blob:
        out += struct.pack("<II", len(blob), 0x004E4942) + blob
    return struct.pack("<4sII", b"glTF", 2, 12 + len(out)) + out


def png_header(width: int, height: int) -> bytes:
    return b"\x89PNG\r\n\x1a\n" + struct.pack(">I4sII", 13, b"IHDR", width, height) + b"\x08\x06\0\0\0" + b"\0\0\0\0"


MIXAMO = {c: "mixamorig:" + n for c, n in {
    "hips": "Hips", "spine": "Spine", "chest": "Spine1", "neck": "Neck", "head": "Head",
    "leftUpperArm": "LeftArm", "leftLowerArm": "LeftForeArm", "leftHand": "LeftHand",
    "rightUpperArm": "RightArm", "rightLowerArm": "RightForeArm", "rightHand": "RightHand",
    "leftUpperLeg": "LeftUpLeg", "leftLowerLeg": "LeftLeg", "leftFoot": "LeftFoot",
    "rightUpperLeg": "RightUpLeg", "rightLowerLeg": "RightLeg", "rightFoot": "RightFoot"}.items()}
UE5 = {"hips": "pelvis", "spine": "spine_01", "chest": "spine_02", "neck": "neck_01", "head": "head",
       "leftUpperArm": "upperarm_l", "leftLowerArm": "lowerarm_l", "leftHand": "hand_l",
       "rightUpperArm": "upperarm_r", "rightLowerArm": "lowerarm_r", "rightHand": "hand_r",
       "leftUpperLeg": "thigh_l", "leftLowerLeg": "calf_l", "leftFoot": "foot_l",
       "rightUpperLeg": "thigh_r", "rightLowerLeg": "calf_r", "rightFoot": "foot_r"}
RIGIFY = {"hips": "DEF-hips", "spine": "DEF-spine.001", "chest": "DEF-spine.002", "neck": "DEF-neck", "head": "DEF-head",
          "leftUpperArm": "DEF-upper_arm.L", "leftLowerArm": "DEF-forearm.L", "leftHand": "DEF-hand.L",
          "rightUpperArm": "DEF-upper_arm.R", "rightLowerArm": "DEF-forearm.R", "rightHand": "DEF-hand.R",
          "leftUpperLeg": "DEF-thigh.L", "leftLowerLeg": "DEF-shin.L", "leftFoot": "DEF-foot.L",
          "rightUpperLeg": "DEF-thigh.R", "rightLowerLeg": "DEF-shin.R", "rightFoot": "DEF-foot.R"}
BLENDER_LR = {"hips": "Hips", "spine": "Abdomen", "chest": "Torso", "neck": "Neck", "head": "Head",
              "leftUpperArm": "UpperArm.L", "leftLowerArm": "LowerArm.L", "leftHand": "Hand.L",
              "rightUpperArm": "UpperArm.R", "rightLowerArm": "LowerArm.R", "rightHand": "Hand.R",
              "leftUpperLeg": "UpperLeg.L", "leftLowerLeg": "LowerLeg.L", "leftFoot": "Foot.L",
              "rightUpperLeg": "UpperLeg.R", "rightLowerLeg": "LowerLeg.R", "rightFoot": "Foot.R"}
UNITY = {"hips": "Hips", "spine": "Spine", "chest": "Chest", "neck": "Neck", "head": "Head",
         "leftUpperArm": "LeftUpperArm", "leftLowerArm": "LeftLowerArm", "leftHand": "LeftHand",
         "rightUpperArm": "RightUpperArm", "rightLowerArm": "RightLowerArm", "rightHand": "RightHand",
         "leftUpperLeg": "LeftUpperLeg", "leftLowerLeg": "LeftLowerLeg", "leftFoot": "LeftFoot",
         "rightUpperLeg": "RightUpperLeg", "rightLowerLeg": "RightLowerLeg", "rightFoot": "RightFoot"}
