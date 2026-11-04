"""A small synthetic MHR-like rig for the avatar tests: 127 joints in MHR's index order, a person-shaped skeleton in
metres (Y up, +Z forward, left on +X), a few vertices per joint, and skin weights with up to five influences."""
import numpy as np

from part2 import mhr_export as mx

# parent index and rest position (x, y, z) of the mapped joints, MHR index order
_TREE = {
    1: (0, (0, .92, 0)), 34: (1, (0, .94, -.03)), 36: (34, (0, 1.16, -.05)), 37: (36, (0, 1.35, -.04)),
    110: (37, (0, 1.44, 0)), 113: (110, (0, 1.54, .03)),
    74: (37, (.03, 1.41, .06)), 75: (74, (.18, 1.42, -.03)), 76: (75, (.35, 1.23, -.02)), 77: (76, (.54, 1.11, .13)),
    38: (37, (-.03, 1.41, .06)), 39: (38, (-.18, 1.42, -.03)), 40: (39, (-.35, 1.23, -.02)), 41: (40, (-.54, 1.11, .13)),
    2: (1, (.08, .91, 0)), 3: (2, (.13, .49, -.02)), 4: (3, (.18, .07, -.06)), 7: (4, (.19, .05, 0)),
    18: (1, (-.08, .91, 0)), 19: (18, (-.13, .49, -.02)), 20: (19, (-.18, .07, -.06)), 23: (20, (-.19, .05, 0)),
}


def joints_and_parents():
    parents = np.full(mx.JOINTS, 1, dtype=np.int64)
    parents[0] = -1
    joints = np.tile(np.array([0, .92, 0.0]), (mx.JOINTS, 1))
    joints[0] = 0
    for i, (p, pos) in _TREE.items():
        parents[i] = p
        joints[i] = pos
    for k, i in enumerate(i for i in range(mx.JOINTS) if i not in _TREE and i != 0):  # helper joints near the pelvis
        joints[i] = joints[1] + [0.001 * (k % 7), 0.001 * (k % 5), 0.001 * (k % 3)]
    return parents, joints


def body(seed=0, scale=1.0):
    """(MhrStatic, vertices, joints): 4 vertices around every joint, each skinned to its joint, its parent and noise."""
    rng = np.random.default_rng(seed)
    parents, joints = joints_and_parents()
    joints = joints * scale
    n = mx.JOINTS * 4
    verts = np.repeat(joints, 4, axis=0) + rng.normal(0, 0.01, (n, 3))
    verts[:, 1] -= 0.05  # soles below the lowest joint, so the ground shift is not zero
    vert_i, joint_i, weight = [], [], []
    for v in range(n):
        j = v // 4
        ids = [j, max(int(parents[j]), 0), 1, 0, 2][: 2 + v % 4]  # 2 to 5 influences, duplicates are fine to the sort
        ids = list(dict.fromkeys(ids))
        w = rng.uniform(0.2, 1.0, len(ids))
        w = w / w.sum() * (1 + (0.02 if v % 9 == 0 else 0))  # some sums are off by 2 percent
        vert_i += [v] * len(ids)
        joint_i += ids
        weight += list(w)
    faces = np.array([[3 * k % n, (3 * k + 1) % n, (3 * k + 2) % n] for k in range(n // 2)])
    static = mx.skin_arrays(faces, parents, np.array(vert_i), np.array(joint_i), np.array(weight), n)
    return static, verts, joints
