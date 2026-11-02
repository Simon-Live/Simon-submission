"""Linear blend skinning of a rig in numpy, and the stretch metric of a skin under a standard test pose.

    posed = pose_vertices(vertices, joints, parents, idx, w, rotations)    # rotations: {joint index: 3x3}
    stretch = edge_stretch(vertices, posed, faces)                          # {"max", "p99", "edges", "over_3x"}
    stretch = pose_stretch(vertices, faces, joints, parents, idx, w, mapping)   # both steps for each STRETCH_POSES_DEG pose

The rig is bind-normalised as `part2.autorig_glb` writes it (identity joint rotations at bind), so a joint's rotation is
a world-aligned rotation about the joint's own position, carried by its children. The stretch of an edge is its posed
length over its bind length: a skin that bleeds between two legs stretches the edges that join them. numpy only, no GPU.
Spec: docs/specs/autorig.md (AC-20, AC-21).
"""
import numpy as np

from part2 import autorig_glb

MIN_EDGE_SHARE = 0.25        # an edge shorter than this share of the median bind edge is a sliver, not a measurement
# the standard test poses, degrees about the world X axis (Y up, the figure faces +Z). "legs": a stride with both knees
# bent; the two legs go opposite ways, so any weight shared between them tears the surface between them. "arms": both
# arms swung and the elbows bent.
STRETCH_POSES_DEG = {
    "legs": {"leftUpperLeg": -50, "leftLowerLeg": 60, "rightUpperLeg": 30, "rightLowerLeg": 25},
    "arms": {"leftUpperArm": -60, "leftLowerArm": -50, "rightUpperArm": 60, "rightLowerArm": -30},
}


def rot_x(deg: float) -> np.ndarray:
    a = np.deg2rad(deg)
    c, s = np.cos(a), np.sin(a)
    return np.array([[1.0, 0, 0], [0, c, -s], [0, s, c]])


def pose_rotations(mapping: dict, name: str) -> dict:
    """{joint index: rotation} of the STRETCH_POSES_DEG pose `name` for the canonical bones in `mapping`."""
    return {mapping[bone]: rot_x(deg) for bone, deg in STRETCH_POSES_DEG[name].items() if bone in mapping}


def skin_matrices(joints, parents, rotations: dict) -> np.ndarray:
    """(j,4,4): the posed world matrix of each joint times its inverse bind (a translation by minus the joint)."""
    joints, parents = np.asarray(joints, dtype=float), np.asarray(parents, dtype=np.int64)
    world: dict[int, np.ndarray] = {}

    def of(i: int) -> np.ndarray:
        if i not in world:
            m = np.eye(4)
            p = int(parents[i])
            m[:3, 3] = joints[i] - (joints[p] if p >= 0 else 0.0)
            if i in rotations:
                m[:3, :3] = rotations[i]
            world[i] = (of(p) if p >= 0 else np.eye(4)) @ m
        return world[i]

    skin = np.stack([of(i) for i in range(len(joints))])
    skin[:, :3, 3] -= np.einsum("jab,jb->ja", skin[:, :3, :3], joints)
    return skin


def pose_vertices(vertices, joints, parents, idx, w, rotations: dict) -> np.ndarray:
    """The vertices (n,3) skinned by joints (j,3), parents (j,), idx (n,k), w (n,k), with `rotations` on some joints."""
    skin = skin_matrices(joints, parents, rotations)
    v, idx, w = np.asarray(vertices, dtype=float), np.asarray(idx), np.asarray(w, dtype=float)
    out = np.zeros_like(v)
    for k in range(idx.shape[1]):
        m = skin[idx[:, k]]
        out += w[:, k:k + 1] * (np.einsum("nab,nb->na", m[:, :3, :3], v) + m[:, :3, 3])
    return out


def unique_edges(faces: np.ndarray) -> np.ndarray:
    faces = np.asarray(faces)
    e = np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]])
    return np.unique(np.sort(e, axis=1), axis=0)


def edge_stretch(bind: np.ndarray, posed: np.ndarray, faces: np.ndarray) -> dict:
    """Posed over bind length of the mesh edges: max, 99th percentile, edge count and edges stretched past 3x."""
    e = unique_edges(faces)
    l0 = np.linalg.norm(bind[e[:, 0]] - bind[e[:, 1]], axis=1)
    l1 = np.linalg.norm(posed[e[:, 0]] - posed[e[:, 1]], axis=1)
    keep = l0 >= MIN_EDGE_SHARE * np.median(l0)
    ratio = l1[keep] / l0[keep]
    return {"max": float(ratio.max()), "p99": float(np.percentile(ratio, 99)), "edges": int(keep.sum()),
            "over_3x": int((ratio > 3).sum())}


def pose_stretch(vertices, faces, joints, parents, idx, w, mapping: dict) -> dict:
    """{pose name: edge_stretch(...)} for each of the STRETCH_POSES_DEG."""
    vertices = np.asarray(vertices, dtype=float)
    return {name: edge_stretch(vertices, pose_vertices(vertices, joints, parents, idx, w, pose_rotations(mapping, name)), faces)
            for name in STRETCH_POSES_DEG}


def read_rig(glb: bytes) -> dict:
    """The arrays of a GLB that `autorig_glb.build` wrote: vertices, faces, joints (bind positions), parents, idx, w and
    mapping ({canonical name: joint index}, the joints whose node name is not `mhr_<n>`)."""
    doc, read = autorig_glb.read(glb)
    prim = doc["meshes"][0]["primitives"][0]
    at = prim["attributes"]
    skin = doc["skins"][0]
    order = skin["joints"]
    nodes = doc["nodes"]
    parents = np.full(len(order), -1, dtype=np.int64)
    slot = {n: k for k, n in enumerate(order)}
    for k, n in enumerate(order):
        for c in nodes[n].get("children", []):
            parents[slot[c]] = k
    names = [nodes[n]["name"] for n in order]
    return {"vertices": read(at["POSITION"]).astype(float), "faces": read(prim["indices"]).reshape(-1, 3).astype(np.int64),
            "joints": -read(skin["inverseBindMatrices"]).reshape(-1, 4, 4)[:, 3, :3].astype(float), "parents": parents,
            "idx": read(at["JOINTS_0"]).astype(np.int64), "w": read(at["WEIGHTS_0"]).astype(float),
            "mapping": {n: k for k, n in enumerate(names) if not n.startswith("mhr_")}, "doc": doc, "reader": read}
