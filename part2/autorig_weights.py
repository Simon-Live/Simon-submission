"""Skin weights that do not bleed between limbs, for `part2 autorig` and `part2 image3d`. numpy only, no GPU.

    idx, w = refine(vertices, faces, joints, parents, mapping, idx, w)

`autorig.transfer_weights` gives each mesh vertex the skin of its nearest fitted-body vertices. On a figure whose legs
stand close (an inner thigh is nearer the other leg's body vertices than its own, a belt or a pouch hangs between the
legs), that bleeds weight across the limbs and an extreme leg swing drags a sheet of surface between them. `refine`
takes those weights and does three things:

1. Each vertex gets a limb: a leg or an arm when most of its weight sits there (the left or right one by the nearer
   bone segment of that pair), else the torso. A limb is the MHR skeleton's own subtree of its upper bone.
2. A limb vertex keeps weight only on its own limb and the torso joints; a torso vertex keeps the nearer leg and the
   nearer arm (by the bone segments), never both legs. A vertex left with no weight follows its nearest bone.
3. The weights are smoothed over the surface graph, along edges inside a limb and between a limb and the torso, never
   between two limbs; the limit of step 2 is applied again after each step.

Spec: docs/specs/autorig.md (AC-20).
"""
import numpy as np

from part2.autorig_pose import unique_edges
from part2.mhr_export import is_under

MAX_INFLUENCES = 4
SMOOTH_STEPS, SMOOTH_MIX = 4, 0.5
RAMP_M = 0.08                # how wide the surface joining two limbs ramps from one limb's weights to the other's
MIN_HOPS, MAX_HOPS = 4, 10   # the ramp in edges: RAMP_M over the median edge, kept between these
CUT_STRETCH, CUT_MAX_SHARE = 6.0, 0.03   # cut_bridges: a bridging triangle edge stretched past 6x; at most 3 percent cut
BLEND_PER_HOP2 = 0.75        # smoothing steps per hop squared (diffusion spreads as the square root of the steps)
TORSO, LEFT_LEG, RIGHT_LEG, LEFT_ARM, RIGHT_ARM = range(5)
_ROOTS = {LEFT_LEG: "leftUpperLeg", RIGHT_LEG: "rightUpperLeg", LEFT_ARM: "leftUpperArm", RIGHT_ARM: "rightUpperArm"}


def joint_limbs(parents, mapping: dict) -> np.ndarray:
    """(j,) limb of each joint: the subtree of an upper-leg or upper-arm bone (the bone included), else TORSO."""
    parents = np.asarray(parents)
    limb = np.zeros(len(parents), dtype=np.int64)
    for which, name in _ROOTS.items():
        root = mapping[name]
        for j in range(len(parents)):
            if j == root or is_under(parents, j, root):
                limb[j] = which
    return limb


def _segment_distance(points: np.ndarray, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """(n, s): distance of each point to each segment a[s]-b[s]."""
    ab = b - a
    t = ((points[:, None, :] - a[None]) * ab[None]).sum(2) / np.maximum((ab ** 2).sum(1), 1e-12)[None]
    nearest = a[None] + np.clip(t, 0, 1)[:, :, None] * ab[None]
    return np.linalg.norm(points[:, None, :] - nearest, axis=2)


def limb_distances(vertices: np.ndarray, joints: np.ndarray, parents, limb: np.ndarray, block: int = 4000):
    """(dist (n,5), bone (n,5)): per limb, the distance from each vertex to the nearest parent-child segment of that limb
    and that segment's child joint. A segment belongs to the limb of its child; the link from the torso to a limb's upper
    joint lies inside the pelvis or the chest, so it counts as the joint itself (a point), not a bone."""
    parents = np.asarray(parents)
    child = np.array([j for j in range(len(parents)) if parents[j] >= 0
                      and np.linalg.norm(joints[j] - joints[parents[j]]) > 1e-6], dtype=np.int64)
    root = limb[parents[child]] != limb[child]  # a limb's upper bone: the link to the torso is left out, the joint stays
    a, b, seg = np.where(root[:, None], joints[child], joints[parents[child]]), joints[child], limb[child]
    dist, bone = np.full((len(vertices), 5), np.inf), np.zeros((len(vertices), 5), dtype=np.int64)
    for s in range(0, len(vertices), block):
        d = _segment_distance(vertices[s:s + block], a, b)
        for which in range(5):
            cols = np.where(seg == which)[0]
            if len(cols):
                k = d[:, cols].argmin(1)
                dist[s:s + block, which], bone[s:s + block, which] = d[np.arange(len(d)), cols[k]], child[cols[k]]
    return dist, bone


def vertex_limbs(idx: np.ndarray, w: np.ndarray, limb: np.ndarray, dist: np.ndarray):
    """(limb (n,), partner (n,)): the group with the most of a vertex's weight (torso, the legs, the arms) decides. A leg or
    arm group makes the vertex that limb, the left or right one by the nearer bone segment of the pair, and partner is
    TORSO. When the torso group wins the vertex is TORSO and its partner is the nearer leg or arm of the heavier of those two
    groups (TORSO again when it has neither): a hand resting on a hip thus follows one limb, not the hand, the hips and the
    leg all at once."""
    mass = np.zeros((len(idx), 5))
    np.add.at(mass, (np.repeat(np.arange(len(idx)), idx.shape[1]), limb[idx].ravel()), w.ravel())
    groups = np.stack([mass[:, TORSO], mass[:, LEFT_LEG] + mass[:, RIGHT_LEG], mass[:, LEFT_ARM] + mass[:, RIGHT_ARM]], 1)
    win = groups.argmax(1)
    leg_side = np.where(dist[:, LEFT_LEG] <= dist[:, RIGHT_LEG], LEFT_LEG, RIGHT_LEG)
    arm_side = np.where(dist[:, LEFT_ARM] <= dist[:, RIGHT_ARM], LEFT_ARM, RIGHT_ARM)
    out, partner = np.zeros(len(idx), dtype=np.int64), np.zeros(len(idx), dtype=np.int64)
    out[win == 1], out[win == 2] = leg_side[win == 1], arm_side[win == 2]
    torso = win == 0
    pick_arm = groups[:, 2] > groups[:, 1]
    partner[torso & (groups[:, 1] + groups[:, 2] > 0)] = np.where(pick_arm, arm_side, leg_side)[torso & (groups[:, 1] + groups[:, 2] > 0)]
    return out, partner


def allowed_joints(limb: np.ndarray, vertex_limb: np.ndarray, partner: np.ndarray) -> np.ndarray:
    """(n, j) bool: the joints each vertex may keep weight on: the torso's, its own limb's and its partner limb's."""
    ok = np.zeros((len(vertex_limb), len(limb)), dtype=bool)
    ok[:, limb == TORSO] = True
    for which in range(1, 5):
        ok[np.ix_((vertex_limb == which) | (partner == which), limb == which)] = True
    return ok


def _dense(idx: np.ndarray, w: np.ndarray, columns: np.ndarray) -> np.ndarray:
    col_of = np.full(int(columns.max()) + 1, -1, dtype=np.int64)
    col_of[columns] = np.arange(len(columns))
    dense = np.zeros((len(idx), len(columns)), dtype=np.float32)
    np.add.at(dense, (np.repeat(np.arange(len(idx)), idx.shape[1]), col_of[idx].ravel()), w.ravel().astype(np.float32))
    return dense


def _smooth(dense: np.ndarray, edges: np.ndarray, keep: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """One step: each row moves SMOOTH_MIX of the way to the mean of its neighbours along `edges[keep]`, then `mask`."""
    e = edges[keep]
    src, dst = np.concatenate([e[:, 0], e[:, 1]]), np.concatenate([e[:, 1], e[:, 0]])
    count = np.bincount(src, minlength=len(dense)).astype(np.float32)
    mean = np.empty_like(dense)
    for c in range(dense.shape[1]):
        mean[:, c] = np.bincount(src, weights=dense[dst, c], minlength=len(dense))
    lonely = count == 0
    mean = np.where(lonely[:, None], dense, mean / np.maximum(count, 1)[:, None])
    return (1 - SMOOTH_MIX) * dense + SMOOTH_MIX * mean * mask


def _near(edges: np.ndarray, seed_edges: np.ndarray, n: int, hops: int) -> np.ndarray:
    """(n,) bool: vertices within `hops` edges of an endpoint of the edges flagged in `seed_edges`."""
    reach = np.zeros(n, dtype=bool)
    reach[edges[seed_edges].ravel()] = True
    for _ in range(hops):
        step = reach.copy()
        step[edges[reach[edges[:, 0]], 1]] = True
        step[edges[reach[edges[:, 1]], 0]] = True
        reach = step
    return reach


def refine(vertices, faces, joints, parents, mapping: dict, idx, w, steps: int = SMOOTH_STEPS, blend: int | None = None, hops: int | None = None):
    """(idx (n,4), w (n,4)): the weights of `idx`, `w` with the limb split and the smoothing of the module doc. Every row
    keeps non-negative weights summing to 1 on at most four joints."""
    vertices, joints = np.asarray(vertices, dtype=float), np.asarray(joints, dtype=float)
    idx, w, faces = np.asarray(idx), np.asarray(w, dtype=float), np.asarray(faces)
    limb = joint_limbs(parents, mapping)
    dist, bones = limb_distances(vertices, joints, parents, limb)
    vertex_limb, partner = vertex_limbs(idx, w, limb, dist)
    bone = bones[np.arange(len(vertices)), vertex_limb]
    columns = np.unique(np.concatenate([idx.ravel(), bone]))
    allow = allowed_joints(limb, vertex_limb, partner)[:, columns]
    mask = allow.astype(np.float32)
    dense = _dense(idx, w, columns) * mask
    empty = dense.sum(1) <= 1e-6
    dense[empty, np.searchsorted(columns, bone[empty])] = 1.0
    mask[np.arange(len(mask)), np.searchsorted(columns, bone)] = 1.0  # the vertex's own bone is always allowed
    edges = unique_edges(faces)
    if hops is None:
        median_edge = float(np.median(np.linalg.norm(vertices[edges[:, 0]] - vertices[edges[:, 1]], axis=1)))
        hops = int(np.clip(round(RAMP_M / max(median_edge, 1e-6)), MIN_HOPS, MAX_HOPS))
    if blend is None:
        blend = round(BLEND_PER_HOP2 * hops * hops)
    same = (vertex_limb[edges[:, 0]] == vertex_limb[edges[:, 1]]) | (vertex_limb[edges] == TORSO).any(1)
    own = np.searchsorted(columns, bone)

    def run(count, use, mask):
        nonlocal dense
        for _ in range(count):
            dense = _smooth(dense, edges, use, mask)
            empty = dense.sum(1) <= 1e-6
            dense[empty, own[empty]] = 1.0

    run(steps, same, mask)
    differ = vertex_limb[edges[:, 0]] != vertex_limb[edges[:, 1]]
    band = _near(edges, differ, len(vertices), hops)  # the surface where the limb changes (two limbs, a limb and the torso) ramps
    run(blend, np.ones(len(edges), dtype=bool), np.where(band[:, None], np.float32(1), mask))
    order = np.argsort(-dense, axis=1, kind="stable")[:, :MAX_INFLUENCES]
    top = np.take_along_axis(dense, order, 1).astype(float)
    return columns[order], top / top.sum(1, keepdims=True)


def cut_bridges(vertices, faces, joints, parents, mapping: dict, idx, w):
    """(faces without the bridging triangles, number cut). A bridge is a triangle that has two vertices of different limb
    classes (torso counts as one) and an edge stretched past CUT_STRETCH under either test pose: a sheet that a hand
    resting on a hip, or one leg against the other, would drag along. Where a model touches itself that surface is mostly
    hidden, so the cut leaves at most a small hole at the contact; nothing is cut when it would remove more than
    CUT_MAX_SHARE of the triangles, and vertices are never removed, so UVs and weights keep their order."""
    from part2 import autorig_pose

    vertices, faces = np.asarray(vertices, dtype=float), np.asarray(faces)
    limb = joint_limbs(parents, mapping)
    dist, _ = limb_distances(vertices, np.asarray(joints, dtype=float), parents, limb)
    vertex_limb, _ = vertex_limbs(np.asarray(idx), np.asarray(w, dtype=float), limb, dist)
    torn = np.zeros(len(faces), dtype=bool)
    for name in autorig_pose.STRETCH_POSES_DEG:
        posed = autorig_pose.pose_vertices(vertices, joints, parents, idx, w, autorig_pose.pose_rotations(mapping, name))
        for a, b in ((0, 1), (1, 2), (2, 0)):
            l0 = np.linalg.norm(vertices[faces[:, a]] - vertices[faces[:, b]], axis=1)
            l1 = np.linalg.norm(posed[faces[:, a]] - posed[faces[:, b]], axis=1)
            torn |= l1 > CUT_STRETCH * np.maximum(l0, 0.25 * np.median(l0))
    classes = vertex_limb[faces]
    torn &= (classes != classes[:, :1]).any(1)
    if torn.sum() > CUT_MAX_SHARE * len(faces):
        return faces, 0
    return faces[~torn], int(torn.sum())
