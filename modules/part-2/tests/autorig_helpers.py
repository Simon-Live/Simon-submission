"""Shared fixtures for the autorig tests: a box humanoid, a GLB builder, an MHR-like skin and a fake SAM fit.

No GPU, no torch, no scipy. Spec: docs/specs/autorig.md."""
import json
import struct

import numpy as np

from part2 import autorig, autorig_mesh
from part2.autorig import MHR_INDEX, UNDER, Fit, Skin

# (name, centre, size) of the boxes of a T-pose figure 1.7 m tall, facing +Z, subject's left on +X, soles on y = 0
BOXES = [
    ("hips", (0, 0.95, 0), (0.30, 0.18, 0.16)), ("spine", (0, 1.15, 0), (0.30, 0.22, 0.16)),
    ("chest", (0, 1.38, 0), (0.34, 0.24, 0.18)), ("head", (0, 1.60, 0.01), (0.16, 0.20, 0.18)),
    ("leftUpperArm", (0.30, 1.45, 0), (0.22, 0.07, 0.07)), ("leftLowerArm", (0.52, 1.45, 0), (0.22, 0.06, 0.06)),
    ("leftHand", (0.70, 1.45, 0), (0.14, 0.05, 0.04)),
    ("rightUpperArm", (-0.30, 1.45, 0), (0.22, 0.07, 0.07)), ("rightLowerArm", (-0.52, 1.45, 0), (0.22, 0.06, 0.06)),
    ("rightHand", (-0.70, 1.45, 0), (0.14, 0.05, 0.04)),
    ("leftUpperLeg", (0.10, 0.70, 0), (0.11, 0.40, 0.11)), ("leftLowerLeg", (0.10, 0.30, 0), (0.09, 0.40, 0.09)),
    ("leftFoot", (0.10, 0.04, 0.05), (0.09, 0.08, 0.22)),
    ("rightUpperLeg", (-0.10, 0.70, 0), (0.11, 0.40, 0.11)), ("rightLowerLeg", (-0.10, 0.30, 0), (0.09, 0.40, 0.09)),
    ("rightFoot", (-0.10, 0.04, 0.05), (0.09, 0.08, 0.22)),
]
# the joint of each canonical bone: the box centre, except these (the box's end that the bone starts at)
JOINT_AT = {"hips": (0, 0.95, 0), "spine": (0, 1.1, 0), "chest": (0, 1.3, 0), "upperChest": (0, 1.4, 0),
            "neck": (0, 1.5, 0), "head": (0, 1.55, 0),
            "leftShoulder": (0.12, 1.45, 0), "leftUpperArm": (0.19, 1.45, 0), "leftLowerArm": (0.41, 1.45, 0),
            "leftHand": (0.63, 1.45, 0), "rightShoulder": (-0.12, 1.45, 0), "rightUpperArm": (-0.19, 1.45, 0),
            "rightLowerArm": (-0.41, 1.45, 0), "rightHand": (-0.63, 1.45, 0),
            "leftUpperLeg": (0.10, 0.90, 0), "leftLowerLeg": (0.10, 0.50, 0), "leftFoot": (0.10, 0.09, 0),
            "leftToes": (0.10, 0.03, 0.14), "rightUpperLeg": (-0.10, 0.90, 0), "rightLowerLeg": (-0.10, 0.50, 0),
            "rightFoot": (-0.10, 0.09, 0), "rightToes": (-0.10, 0.03, 0.14)}


def box(centre, size):
    c, s = np.array(centre, float), np.array(size, float) / 2
    v = np.array([c + s * [x, y, z] for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)])
    f = [(0, 1, 3), (0, 3, 2), (4, 6, 7), (4, 7, 5), (0, 4, 5), (0, 5, 1), (2, 3, 7), (2, 7, 6), (0, 2, 6), (0, 6, 4),
         (1, 5, 7), (1, 7, 3)]
    return v, np.array(f)


def humanoid(colors=False) -> "autorig_mesh.Mesh":
    verts, faces, owner, base = [], [], [], 0
    for k, (name, c, s) in enumerate(BOXES):
        v, f = box(c, s)
        verts.append(v)
        faces.append(f + base)
        owner += [name] * len(v)
        base += len(v)
    v = np.concatenate(verts)
    col = np.tile(np.array([0.8, 0.5, 0.4]), (len(v), 1)) if colors else None
    m = autorig_mesh.Mesh(v, np.concatenate(faces), col)
    m.owner = owner  # which box each vertex belongs to (tests only)
    return m


def obj_text(mesh) -> str:
    lines = [f"v {x} {y} {z}" for x, y, z in mesh.vertices]
    lines += [f"f {a + 1} {b + 1} {c + 1}" for a, b, c in mesh.faces]
    return "\n".join(lines) + "\n"


def glb_bytes(positions, indices=None, nodes=None, scene_nodes=None, colors=None, skin=False, material=None,
              texcoords=None, image=None, extensions_required=None) -> bytes:
    """A GLB with one mesh (triangles) and no skin unless `skin`. `nodes` replaces the one default node."""
    pos = np.asarray(positions, dtype="<f4")
    chunks, views, accs, attrs = [], [], [], {}

    def add(arr, ctype, kind, target=None):
        data = np.ascontiguousarray(arr).tobytes()
        off = sum(len(c) for c in chunks)
        chunks.append(data + b"\0" * (-len(data) % 4))
        views.append({"buffer": 0, "byteOffset": off, "byteLength": len(data)})
        accs.append({"bufferView": len(views) - 1, "componentType": ctype, "count": len(arr), "type": kind})
        return len(accs) - 1

    attrs["POSITION"] = add(pos, 5126, "VEC3")
    if colors is not None:
        attrs["COLOR_0"] = add(np.asarray(colors, dtype="<f4"), 5126, "VEC3")
    if texcoords is not None:
        attrs["TEXCOORD_0"] = add(np.asarray(texcoords, dtype="<f4"), 5126, "VEC2")
    prim = {"attributes": attrs}
    if indices is not None:
        prim["indices"] = add(np.asarray(indices, dtype="<u2").reshape(-1), 5123, "SCALAR")
    doc = {"asset": {"version": "2.0"}, "scene": 0, "meshes": [{"primitives": [prim]}],
           "nodes": nodes or [{"mesh": 0}], "scenes": [{"nodes": scene_nodes if scene_nodes is not None else [0]}],
           "accessors": accs, "bufferViews": views}
    if material is not None:
        doc["materials"] = [material]
        prim["material"] = 0
    if image is not None:
        views.append({"buffer": 0, "byteOffset": sum(len(c) for c in chunks), "byteLength": len(image)})
        chunks.append(image + b"\0" * (-len(image) % 4))
        doc["images"] = [{"bufferView": len(views) - 1, "mimeType": "image/png"}]
        doc["textures"] = [{"source": 0}]
    if skin:
        doc["skins"] = [{"joints": [0]}]
        doc["nodes"][0]["skin"] = 0
    if extensions_required:
        doc["extensionsRequired"] = extensions_required
    doc["buffers"] = [{"byteLength": sum(len(c) for c in chunks)}]
    return pack(doc, b"".join(chunks))


def pack(doc, blob) -> bytes:
    js = json.dumps(doc).encode()
    js += b" " * (-len(js) % 4)
    body = struct.pack("<I4s", len(js), b"JSON") + js + struct.pack("<I4s", len(blob), b"BIN\0") + blob
    return struct.pack("<4sII", b"glTF", 2, 12 + len(body)) + body


def synthetic_parents() -> np.ndarray:
    """127 joints that satisfy the chain rule: root 0, hips 1 under it, every bone under the one UNDER names, the rest
    hang off the hips."""
    parents = np.full(autorig.JOINTS, 1)
    parents[0] = -1
    for bone, above in UNDER.items():
        parents[MHR_INDEX[bone]] = MHR_INDEX[above]
    parents[MHR_INDEX["hips"]] = 0
    parents[MHR_INDEX["upperChest"]] = MHR_INDEX["chest"]
    return parents


def synthetic_joints() -> np.ndarray:
    j = np.tile(np.array(JOINT_AT["hips"], float), (autorig.JOINTS, 1))
    for bone, i in MHR_INDEX.items():
        j[i] = JOINT_AT[bone]
    return j


def synthetic_skin(body: np.ndarray, joints=None) -> Skin:
    """Each body vertex follows its nearest canonical joint with weight 0.7 and the second nearest with 0.3."""
    idx = np.array(sorted(MHR_INDEX.values()))
    pos = (synthetic_joints() if joints is None else joints)[idx]
    d = np.linalg.norm(body[:, None, :] - pos[None], axis=2)
    order = np.argsort(d, axis=1)[:, :2]
    out_i = np.zeros((len(body), 4), dtype=np.int64)
    out_w = np.zeros((len(body), 4))
    out_i[:, 0], out_i[:, 1] = idx[order[:, 0]], idx[order[:, 1]]
    out_w[:, 0], out_w[:, 1] = 0.7, 0.3
    return Skin(synthetic_parents(), out_i, out_w)


def fake_fit_body(scale=1.25, hip_sign=(1, -1), calls=None, squash=False):
    """A `fit_body` that returns the humanoid the mesh already is, in camera space and `scale` times too far away (the
    picture would not change). hip_sign gives the (left, right) hip x sign of each call, last one repeated."""
    def fit_body(mesh):
        cam = autorig_mesh.render_front(mesh, size=96)[1]
        n = len(calls) if calls is not None else 0
        if calls is not None:
            calls.append(mesh)
        body = cam.to_cam(mesh.vertices)
        joints = cam.to_cam(synthetic_joints_for(mesh))
        kp = np.zeros((70, 3))
        kp[autorig.LEFT_HIP] = cam.to_cam(np.array(JOINT_AT["leftUpperLeg"]))
        kp[autorig.RIGHT_HIP] = cam.to_cam(np.array(JOINT_AT["rightUpperLeg"]))
        sign = hip_sign[min(n, len(hip_sign) - 1)] if isinstance(hip_sign[0], tuple) else hip_sign
        if sign[0] < 0:
            kp[[autorig.LEFT_HIP, autorig.RIGHT_HIP]] = kp[[autorig.RIGHT_HIP, autorig.LEFT_HIP]]
        if squash:
            body = body[np.random.default_rng(0).permutation(len(body))]
            body = body + np.random.default_rng(1).normal(0, 0.3, body.shape)
        return Fit(body * scale, joints * scale, kp * scale), cam

    return fit_body


def synthetic_joints_for(mesh) -> np.ndarray:
    """The joints in the frame of `mesh`: turned with it when the feet point to -Z (the mesh was turned half a turn)."""
    j = synthetic_joints()
    if mesh.vertices[mesh.vertices[:, 1] < 0.1][:, 2].mean() < 0:
        j = j * np.array([-1.0, 1.0, -1.0])
    return j


def surface_points(mesh, n=20000, seed=0) -> np.ndarray:
    """n points spread over the triangles of `mesh` (a dense stand-in for a body mesh)."""
    rng = np.random.default_rng(seed)
    tri = mesh.vertices[mesh.faces]
    area = np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]), axis=1)
    pick = rng.choice(len(tri), n, p=area / area.sum())
    u, v = rng.random((2, n))
    flip = u + v > 1
    u[flip], v[flip] = 1 - u[flip], 1 - v[flip]
    t = tri[pick]
    return t[:, 0] + u[:, None] * (t[:, 1] - t[:, 0]) + v[:, None] * (t[:, 2] - t[:, 0])
