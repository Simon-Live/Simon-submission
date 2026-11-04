"""A skinned glTF 2.0 binary from a mesh, a joint tree and per-vertex influences, for `part2 autorig`. numpy only.

    glb = build(mesh, joints, parents, names, skin_idx, skin_w, notice)  -> bytes
    doc, arrays = read(glb)                    # the JSON and the accessors, for tests

Bind-normalised like part2 avatar: every joint node has an identity rotation and unit scale, so its world position is the
joint position and the inverse bind matrix is a pure translation. At bind the skinned mesh equals the input mesh.
Spec: docs/specs/autorig.md (AC-12 to AC-15).
"""
import json
import struct

import numpy as np

DEFAULT_RGBA = [0.78, 0.78, 0.8, 1.0]


class GlbError(ValueError):
    """The arrays cannot make a valid skinned GLB."""


def build(mesh, joints, parents, names, skin_idx, skin_w, notice: dict) -> bytes:
    """mesh: vertices (n,3), faces (m,3), colors (n,3) or None. joints (j,3) world positions, parents (j,) with -1 at
    the root(s), names (j,), skin_idx (n,4) joint indices, skin_w (n,4) weights summing to 1. notice: {"copyright",
    "licence"} written to asset."""
    joints, parents = np.asarray(joints, dtype=float), np.asarray(parents, dtype=np.int64)
    n, j = len(mesh.vertices), len(joints)
    skin_idx, skin_w = np.asarray(skin_idx), np.asarray(skin_w, dtype=np.float32)
    if skin_idx.shape != (n, 4) or skin_w.shape != (n, 4) or len(parents) != j or len(names) != j:
        raise GlbError("the skin arrays do not match the mesh and the joints")
    if skin_idx.min() < 0 or skin_idx.max() >= j or (skin_w < 0).any() or not np.allclose(skin_w.sum(1), 1, atol=1e-5):
        raise GlbError("a vertex has a joint index out of range or weights that do not sum to 1")
    pos = np.asarray(mesh.vertices, dtype="<f4")
    chunks, views, accessors = [], [], []

    def add(arr, ctype, kind, target=None, minmax=None, normalized=False):
        data = np.ascontiguousarray(arr).tobytes()
        offset = sum(len(c) for c in chunks)
        chunks.append(data + b"\x00" * (-len(data) % 4))
        view = {"buffer": 0, "byteOffset": offset, "byteLength": len(data)}
        if target:
            view["target"] = target
        views.append(view)
        acc = {"bufferView": len(views) - 1, "componentType": ctype, "count": len(arr), "type": kind}
        if normalized:
            acc["normalized"] = True
        if minmax:
            acc["min"], acc["max"] = minmax
        accessors.append(acc)
        return len(accessors) - 1

    attrs = {"POSITION": add(pos, 5126, "VEC3", 34962, ([float(x) for x in pos.min(0)], [float(x) for x in pos.max(0)])),
             "NORMAL": add(vertex_normals(mesh.vertices, mesh.faces).astype("<f4"), 5126, "VEC3", 34962)}
    if mesh.colors is not None:
        attrs["COLOR_0"] = add(np.asarray(mesh.colors, dtype="<f4"), 5126, "VEC3", 34962)
    attrs["JOINTS_0"] = add(skin_idx.astype("<u2"), 5123, "VEC4", 34962)
    attrs["WEIGHTS_0"] = add(skin_w.astype("<f4"), 5126, "VEC4", 34962)
    indices = add(np.asarray(mesh.faces, dtype="<u4").reshape(-1), 5125, "SCALAR", 34963)
    ibm = np.tile(np.eye(4, dtype="<f4"), (j, 1, 1))
    ibm[:, 3, :3] = -joints  # column-major: the translation sits in elements 12 to 14
    ibm_acc = add(ibm.reshape(j, 16), 5126, "MAT4")

    children = [[] for _ in range(j)]
    for i, p in enumerate(parents):
        if p >= 0:
            children[p].append(i)
    nodes = []
    for i in range(j):
        local = joints[i] - (joints[parents[i]] if parents[i] >= 0 else 0)
        node = {"name": names[i], "translation": [round(float(x), 7) for x in local]}
        if children[i]:
            node["children"] = children[i]
        nodes.append(node)
    roots = [i for i in range(j) if parents[i] < 0]
    nodes.append({"name": "body", "mesh": 0, "skin": 0})
    doc = {
        "asset": {"version": "2.0", "generator": "simon-part-2 autorig", "copyright": notice["copyright"],
                  "extras": {"licence": notice["licence"]}},
        "scene": 0, "scenes": [{"nodes": roots + [j]}], "nodes": nodes,
        "meshes": [{"name": "body", "primitives": [{"attributes": attrs, "indices": indices, "material": 0}]}],
        "skins": [{"joints": list(range(j)), "inverseBindMatrices": ibm_acc, "skeleton": roots[0]}],
        "materials": [{"name": "body", "doubleSided": True,
                       "pbrMetallicRoughness": {"baseColorFactor": [1, 1, 1, 1] if mesh.colors is not None else DEFAULT_RGBA,
                                                "metallicFactor": 0.0, "roughnessFactor": 0.9}}],
        "accessors": accessors, "bufferViews": views, "buffers": [{"byteLength": sum(len(c) for c in chunks)}],
    }
    return _pack(doc, b"".join(chunks))


def vertex_normals(v: np.ndarray, faces: np.ndarray) -> np.ndarray:
    v = np.asarray(v, dtype=float)
    fn = np.cross(v[faces[:, 1]] - v[faces[:, 0]], v[faces[:, 2]] - v[faces[:, 0]])
    out = np.zeros_like(v)
    for k in range(3):
        np.add.at(out, faces[:, k], fn)
    length = np.linalg.norm(out, axis=1, keepdims=True)
    out = np.where(length > 1e-12, out / np.maximum(length, 1e-12), np.array([0.0, 0.0, 1.0]))
    return out


def _pack(doc: dict, blob: bytes) -> bytes:
    js = json.dumps(doc, separators=(",", ":"), sort_keys=True).encode()
    js += b" " * (-len(js) % 4)
    body = struct.pack("<I4s", len(js), b"JSON") + js + struct.pack("<I4s", len(blob), b"BIN\x00") + blob
    return struct.pack("<4sII", b"glTF", 2, 12 + len(body)) + body


def read(glb: bytes):
    """(json, accessor reader): reader(name_or_index) -> numpy array. Enough for tests, not a general loader."""
    if glb[:4] != b"glTF":
        raise GlbError("not a GLB")
    pos, doc, blob = 12, None, b""
    while pos < len(glb):
        length, kind = struct.unpack_from("<I4s", glb, pos)
        body = glb[pos + 8:pos + 8 + length]
        if kind == b"JSON":
            doc = json.loads(body)
        elif kind == b"BIN\x00":
            blob = body
        pos += 8 + length
    types = {5123: "<u2", 5125: "<u4", 5126: "<f4"}
    width = {"SCALAR": 1, "VEC3": 3, "VEC4": 4, "MAT4": 16}

    def reader(index: int) -> np.ndarray:
        acc = doc["accessors"][index]
        view = doc["bufferViews"][acc["bufferView"]]
        w = width[acc["type"]]
        arr = np.frombuffer(blob, dtype=types[acc["componentType"]], count=acc["count"] * w, offset=view["byteOffset"])
        return arr.reshape(acc["count"], w) if w > 1 else arr

    return doc, reader
