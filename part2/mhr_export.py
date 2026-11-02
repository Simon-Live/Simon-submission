"""MHR body (rest mesh, 127 joints, skinning) -> a skinned glTF 2.0 binary, and a reader for tests.

numpy only: torch tensors are accepted where they arrive (anything with .detach().cpu().numpy()), but this module never
imports torch. Spec: docs/specs/avatar.md (AC-5 to AC-10, AC-17, AC-18). Licences: ADR-0005 (SAM License for the SAM 3D
Body weights and the mirror's copy of the MHR model; MHR upstream Apache-2.0).

The export is bind-normalised: every joint node has an identity rotation and unit scale, so a node's world rotation at
rest is the identity and its world position is the MHR joint position (joint scale and prerotation are baked into the
positions). The inverse bind matrices are pure translations. At bind the skinned mesh equals the rest mesh exactly.
Units: metres, Y up, facing +Z, the subject's left on +X, soles on y = 0.
"""
import json
import struct
from dataclasses import dataclass

import numpy as np

JOINTS = 127
MAX_INFLUENCES = 4
LICENCE = "SAM License; MHR Apache-2.0 notice"
NOTICE = ("Made with SAM 3D Body (SAM License, Meta, 2025-11-19) and the MHR body model (Apache-2.0, "
          "facebookresearch/MHR). Passing this file on needs a copy of the SAM License and the MHR Apache-2.0 "
          "licence text and notice.")
MIN_HEIGHT_M, MAX_HEIGHT_M = 0.5, 2.6

# canonical bone -> MHR joint index (the asset's fixed order; canonical_map checks it against the asset)
MHR_INDEX = {
    "hips": 1, "spine": 34, "chest": 36, "upperChest": 37, "neck": 110, "head": 113,
    "leftShoulder": 74, "leftUpperArm": 75, "leftLowerArm": 76, "leftHand": 77,
    "rightShoulder": 38, "rightUpperArm": 39, "rightLowerArm": 40, "rightHand": 41,
    "leftUpperLeg": 2, "leftLowerLeg": 3, "leftFoot": 4, "leftToes": 7,
    "rightUpperLeg": 18, "rightLowerLeg": 19, "rightFoot": 20, "rightToes": 23,
}
# canonical bone -> the canonical bone it must sit under (anywhere above it in the tree)
UNDER = {
    "spine": "hips", "chest": "spine", "upperChest": "chest", "neck": "upperChest", "head": "neck",
    "leftShoulder": "upperChest", "leftUpperArm": "leftShoulder", "leftLowerArm": "leftUpperArm",
    "leftHand": "leftLowerArm", "rightShoulder": "upperChest", "rightUpperArm": "rightShoulder",
    "rightLowerArm": "rightUpperArm", "rightHand": "rightLowerArm",
    "leftUpperLeg": "hips", "leftLowerLeg": "leftUpperLeg", "leftFoot": "leftLowerLeg", "leftToes": "leftFoot",
    "rightUpperLeg": "hips", "rightLowerLeg": "rightUpperLeg", "rightFoot": "rightLowerLeg",
    "rightToes": "rightFoot",
}


class ExportError(ValueError):
    """The body or the rig cannot be exported; the message is one line for the user."""


class LayoutError(ExportError):
    """The MHR asset does not have the joint layout this module maps (AC-17)."""

    def __init__(self, check: str):
        super().__init__(f"the MHR model does not have the joint layout avatar expects: {check}")


@dataclass
class MhrStatic:
    """What does not change with the person: faces, joint parents, up to four skin joints and weights per vertex."""
    faces: np.ndarray       # (F, 3) int
    parents: np.ndarray     # (127,) int, -1 for the root
    skin_idx: np.ndarray    # (V, 4) int
    skin_w: np.ndarray      # (V, 4) float, rows sum to 1
    max_weight_error: float  # largest |sum of source weights - 1| over the vertices (information only)


@dataclass
class GlbResult:
    glb: bytes
    mapped: dict      # canonical bone -> glTF node index
    height_m: float
    max_weight_error: float


def _np(x) -> np.ndarray:
    if hasattr(x, "detach"):
        x = x.detach().cpu().numpy()
    return np.asarray(x)


def static_from_mhr(mhr) -> MhrStatic:
    """The static rig of a loaded MHR model (the torchscript module of mhr_model.pt)."""
    ch = mhr.character_torch
    lbs = ch.linear_blend_skinning
    return skin_arrays(_np(ch.mesh.faces), _np(ch.skeleton.joint_parents), _np(lbs.vert_indices_flattened),
                       _np(lbs.skin_indices_flattened), _np(lbs.skin_weights_flattened), len(_np(ch.mesh.rest_vertices)))


def skin_arrays(faces, parents, vert, joint, weight, n_vertices: int) -> MhrStatic:
    """Flat (vertex, joint, weight) triples -> the (V, 4) arrays: the four heaviest joints, renormalised to sum 1."""
    vert, joint, weight = (np.asarray(a) for a in (vert, joint, weight))
    sums = np.bincount(vert, weights=weight, minlength=n_vertices)
    if (sums <= 0).any() or not np.isfinite(weight).all() or (weight < 0).any():
        raise ExportError("the MHR skin weights are not usable (a vertex has no positive weight)")
    order = np.lexsort((-weight, vert))
    vert, joint, weight = vert[order], joint[order], weight[order]
    start = np.concatenate([[0], np.cumsum(np.bincount(vert, minlength=n_vertices))[:-1]])
    rank = np.arange(len(vert)) - start[vert]
    keep = rank < MAX_INFLUENCES
    idx = np.zeros((n_vertices, MAX_INFLUENCES), dtype=np.int64)
    w = np.zeros((n_vertices, MAX_INFLUENCES), dtype=np.float64)
    idx[vert[keep], rank[keep]] = joint[keep]
    w[vert[keep], rank[keep]] = weight[keep]
    w /= w.sum(axis=1, keepdims=True)
    return MhrStatic(np.asarray(faces, dtype=np.int64), np.asarray(parents, dtype=np.int64), idx, w,
                     float(np.abs(sums - 1).max()))


def is_under(parents: np.ndarray, node: int, ancestor: int) -> bool:
    for _ in range(len(parents)):
        node = int(parents[node])
        if node < 0:
            return False
        if node == ancestor:
            return True
    return False


def canonical_map(parents, joints) -> dict:
    """{canonical bone: MHR joint index}, after checking that the asset has the layout MHR_INDEX assumes (AC-17):
    127 joints, each bone under the one the chain rule names, sides on the right x, head above hips above feet."""
    parents, joints = np.asarray(parents), np.asarray(joints, dtype=float)
    if len(parents) != JOINTS or joints.shape != (JOINTS, 3):
        raise LayoutError(f"{len(parents)} joints, not {JOINTS}")
    for bone, above in UNDER.items():
        if not is_under(parents, MHR_INDEX[bone], MHR_INDEX[above]):
            raise LayoutError(f"{bone} is not under {above}")
    x = {b: joints[i, 0] for b, i in MHR_INDEX.items()}
    y = {b: joints[i, 1] for b, i in MHR_INDEX.items()}
    for part in ("UpperArm", "Hand", "UpperLeg", "Foot"):
        if not (x["left" + part] > 0 > x["right" + part]):
            raise LayoutError(f"left{part} is not on +x and right{part} on -x")
    if not (y["head"] > y["neck"] > y["hips"] > y["leftFoot"] and y["hips"] > y["rightFoot"]):
        raise LayoutError("head, neck, hips and feet are not stacked upward")
    return dict(MHR_INDEX)


def joint_names(mapping: dict) -> list:
    names = [f"mhr_{i}" for i in range(JOINTS)]
    for bone, i in mapping.items():
        names[i] = bone
    return names


def vertex_normals(v: np.ndarray, f: np.ndarray) -> np.ndarray:
    a, b, c = v[f[:, 0]], v[f[:, 1]], v[f[:, 2]]
    fn = np.cross(b - a, c - a)
    n = np.zeros_like(v)
    for k in range(3):
        np.add.at(n, f[:, k], fn)
    length = np.linalg.norm(n, axis=1, keepdims=True)
    return n / np.where(length > 0, length, 1)


def _pad(b: bytes, fill: bytes = b"\0") -> bytes:
    return b + fill * (-len(b) % 4)


def build_glb(static: MhrStatic, vertices, joints, notice: str = NOTICE) -> GlbResult:
    """The skinned GLB of a body: `vertices` (V, 3) and `joints` (127, 3) in metres in MHR's frame (Y up, +Z forward)."""
    v, j = np.asarray(vertices, dtype=np.float64), np.asarray(joints, dtype=np.float64)
    if not (np.isfinite(v).all() and np.isfinite(j).all()):
        raise ExportError("the fitted body is not plausible (a vertex or joint is not a number)")
    mapping = canonical_map(static.parents, j)
    drop = -float(v[:, 1].min())
    v, j = (v + [0, drop, 0]).astype(np.float32), (j + [0, drop, 0]).astype(np.float32)
    height = float(v[:, 1].max())
    if not MIN_HEIGHT_M <= height <= MAX_HEIGHT_M:
        raise ExportError(f"the fitted body is not plausible (height {height:.2f} m)")
    parents = static.parents
    local = j.astype(np.float64)
    has_parent = parents >= 0
    local[has_parent] -= j[parents[has_parent]].astype(np.float64)
    names = joint_names(mapping)
    children = {i: [] for i in range(JOINTS)}
    for i, p in enumerate(parents):
        if p >= 0:
            children[int(p)].append(i)
    nodes = []
    for i in range(JOINTS):
        node = {"name": names[i], "translation": [float(t) for t in local[i].astype(np.float32)]}
        if children[i]:
            node["children"] = children[i]
        nodes.append(node)
    nodes.append({"name": "body", "mesh": 0, "skin": 0})
    ibm = np.tile(np.eye(4, dtype=np.float32), (JOINTS, 1, 1))
    ibm[:, 3, :3] = -j  # column-major: the last column holds the translation
    f = static.faces.astype(np.uint32)
    chunks = [(v.tobytes(), 34962, 3, 5126, "VEC3", True),
              (vertex_normals(v.astype(np.float64), static.faces).astype(np.float32).tobytes(), 34962, 3, 5126, "VEC3", False),
              (static.skin_idx.astype(np.uint16).tobytes(), 34962, 4, 5123, "VEC4", False),
              (static.skin_w.astype(np.float32).tobytes(), 34962, 4, 5126, "VEC4", False),
              (f.reshape(-1).tobytes(), 34963, 1, 5125, "SCALAR", False),
              (ibm.tobytes(), None, 16, 5126, "MAT4", False)]
    views, accessors, blob = [], [], b""
    for k, (raw, target, width, ctype, kind, with_bounds) in enumerate(chunks):
        view = {"buffer": 0, "byteOffset": len(blob), "byteLength": len(raw)}
        if target:
            view["target"] = target
        views.append(view)
        count = len(raw) // (width * 4 if ctype != 5123 else width * 2)
        acc = {"bufferView": k, "componentType": ctype, "count": count, "type": kind}
        if with_bounds:
            acc["min"], acc["max"] = [float(a) for a in v.min(0)], [float(a) for a in v.max(0)]
        accessors.append(acc)
        blob += _pad(raw)
    doc = {
        "asset": {"version": "2.0", "generator": "part2 avatar", "copyright": notice,
                  "extras": {"licence": LICENCE, "notice": notice}},
        "scene": 0, "scenes": [{"nodes": [0, JOINTS]}], "nodes": nodes,
        "skins": [{"joints": list(range(JOINTS)), "inverseBindMatrices": 5, "skeleton": 0}],
        "meshes": [{"name": "body", "primitives": [{"attributes": {"POSITION": 0, "NORMAL": 1, "JOINTS_0": 2, "WEIGHTS_0": 3},
                                                    "indices": 4, "material": 0, "mode": 4}]}],
        "materials": [{"name": "skin", "pbrMetallicRoughness": {"baseColorFactor": [0.78, 0.62, 0.52, 1.0],
                                                                "metallicFactor": 0.0, "roughnessFactor": 0.85}}],
        "accessors": accessors, "bufferViews": views, "buffers": [{"byteLength": len(blob)}],
    }
    js = _pad(json.dumps(doc, separators=(",", ":"), sort_keys=True).encode(), b" ")
    total = 12 + 8 + len(js) + 8 + len(blob)
    glb = (struct.pack("<4sII", b"glTF", 2, total) + struct.pack("<I4s", len(js), b"JSON") + js
           + struct.pack("<I4s", len(blob), b"BIN\0") + blob)
    return GlbResult(glb, dict(mapping), round(height, 3), static.max_weight_error)


def read_glb(data: bytes) -> tuple:
    """(json document, binary chunk) of a GLB; ExportError when the header or chunks are wrong."""
    if len(data) < 28 or data[:4] != b"glTF":
        raise ExportError("not a GLB")
    version, total = struct.unpack_from("<II", data, 4)
    if version != 2 or total != len(data):
        raise ExportError("GLB version or length is wrong")
    jlen, jtype = struct.unpack_from("<I4s", data, 12)
    if jtype != b"JSON":
        raise ExportError("first GLB chunk is not JSON")
    doc = json.loads(data[20:20 + jlen])
    blen, btype = struct.unpack_from("<I4s", data, 20 + jlen)
    if btype != b"BIN\0":
        raise ExportError("second GLB chunk is not BIN")
    return doc, data[28 + jlen:28 + jlen + blen]


_DTYPE = {5123: np.uint16, 5125: np.uint32, 5126: np.float32}
_WIDTH = {"SCALAR": 1, "VEC3": 3, "VEC4": 4, "MAT4": 16}


def read_accessor(doc: dict, blob: bytes, index: int) -> np.ndarray:
    """An accessor's values as an array of shape (count, width) (tightly packed buffer views only)."""
    acc = doc["accessors"][index]
    view = doc["bufferViews"][acc["bufferView"]]
    n = acc["count"] * _WIDTH[acc["type"]]
    a = np.frombuffer(blob, dtype=_DTYPE[acc["componentType"]], count=n, offset=view["byteOffset"])
    return a.reshape(acc["count"], _WIDTH[acc["type"]])
