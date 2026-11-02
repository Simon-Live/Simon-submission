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

An arm joins the body at the shoulder only. Where a generated mesh has a hand fused to a thigh or a forearm against the
waist (a picture of someone standing with the arms down), the surface between them is contact, not a joint: no weight
ramps across it, no vertex away from the shoulder keeps an arm's weight unless it is that arm's own, and an arm vertex
never keeps a leg's or the other arm's weight (TICKET-058, AC-24). Without this the hands of a generated model stayed
glued to the thighs: the ramp smeared the arm's weight over the thigh and the leg's over the hand.

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
# Off since re-review round 4 (B1-r4, TICKET-058): every shard rule tried also matched part of a prop held in the hand
# (a staff crossing the thigh lost 128 faces no contact touched). The cut keeps only the contact triangles; a small
# piece of inner hand or thigh surface can stay with the hand. `contact_shards` is kept for a later, proven rule.
DROP_SHARDS = False
SHARD_M = 0.05               # cut_bridges: an arm piece cut loose at a contact whose middle lies this far off its arm's bones is a shard
SHARD_SHARE = 0.5           # ... or when that arm held under half of the surface the piece was cut from
SHOULDER_REACH = 0.6         # a vertex not of an arm may keep that arm's weight only this share of the upper arm's length from its joint
BLEND_PER_HOP2 = 0.75        # smoothing steps per hop squared (diffusion spreads as the square root of the steps)
TORSO, LEFT_LEG, RIGHT_LEG, LEFT_ARM, RIGHT_ARM = range(5)
ARMS = {LEFT_ARM: "left", RIGHT_ARM: "right"}
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


def arm_reach(vertices: np.ndarray, joints: np.ndarray, mapping: dict) -> np.ndarray:
    """(n, 5) bool: column LEFT_ARM (RIGHT_ARM) is True for the vertices within SHOULDER_REACH of that upper arm's length
    of its joint, the shoulder where the arm joins the torso; the other columns are True."""
    near = np.ones((len(vertices), 5), dtype=bool)
    for which, side in ARMS.items():
        a, b = joints[mapping[f"{side}UpperArm"]], joints[mapping[f"{side}LowerArm"]]
        near[:, which] = np.linalg.norm(vertices - a, axis=1) <= SHOULDER_REACH * np.linalg.norm(b - a)
    return near


def contact_edges(edges: np.ndarray, vertex_limb: np.ndarray, reach: np.ndarray) -> np.ndarray:
    """(e,) bool: the edges that join an arm vertex to a vertex of another class away from that arm's shoulder (an end
    outside its reach): a hand fused to a thigh, a forearm against the waist, one hand on the other. Edges between the
    legs and the torso are not contact (AC-20 lets a web between the legs ramp)."""
    out = np.zeros(len(edges), dtype=bool)
    a, b = vertex_limb[edges[:, 0]], vertex_limb[edges[:, 1]]
    for which in ARMS:
        crosses = (a == which) != (b == which)
        out |= crosses & ~(reach[edges[:, 0], which] & reach[edges[:, 1], which])
    return out


def arm_allowed(limb: np.ndarray, vertex_limb: np.ndarray, reach: np.ndarray) -> np.ndarray:
    """(n, j) bool: the hard limit no smoothing step may cross. An arm's joints only on that arm's vertices and the
    vertices near its shoulder; an arm vertex never on a leg's or the other arm's joints, and away from its shoulder not
    on the torso's either (a hand by the hip that kept spine weight was dragged into a shard between hip and hand)."""
    ok = np.ones((len(vertex_limb), len(limb)), dtype=bool)
    for which in ARMS:
        ok[np.ix_(~((vertex_limb == which) | reach[:, which]), limb == which)] = False
        ok[np.ix_(vertex_limb == which, (limb != which) & (limb != TORSO))] = False
        ok[np.ix_((vertex_limb == which) & ~reach[:, which], limb == TORSO)] = False
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
    hard = arm_allowed(limb, vertex_limb, arm_reach(vertices, joints, mapping))[:, columns]
    allow = allowed_joints(limb, vertex_limb, partner)[:, columns] & hard
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
    contact = contact_edges(edges, vertex_limb, arm_reach(vertices, joints, mapping))
    same = ((vertex_limb[edges[:, 0]] == vertex_limb[edges[:, 1]]) | (vertex_limb[edges] == TORSO).any(1)) & ~contact
    own = np.searchsorted(columns, bone)

    def run(count, use, mask):
        nonlocal dense
        for _ in range(count):
            dense = _smooth(dense, edges, use, mask)
            empty = dense.sum(1) <= 1e-6
            dense[empty, own[empty]] = 1.0

    run(steps, same, mask)
    joined = edges[~contact]  # a contact is not where a limb changes: nothing ramps across it or reaches over it
    differ = vertex_limb[joined[:, 0]] != vertex_limb[joined[:, 1]]
    band = _near(joined, differ, len(vertices), hops)  # the surface where the limb changes (two limbs, a limb and the torso) ramps
    run(blend, ~contact, np.where(band[:, None], hard.astype(np.float32), mask))
    order = np.argsort(-dense, axis=1, kind="stable")[:, :MAX_INFLUENCES]
    top = np.take_along_axis(dense, order, 1).astype(float)
    return columns[order], top / top.sum(1, keepdims=True)


def cut_bridges(vertices, faces, joints, parents, mapping: dict, idx, w, report: dict | None = None):
    """(faces without the bridging triangles, number cut). A bridge is a triangle that has two vertices of different limb
    classes (torso counts as one) and an edge stretched past CUT_STRETCH under either test pose: a sheet that a hand
    resting on a hip, or one leg against the other, would drag along, and every triangle across an arm contact
    (`contact_edges`) whatever the stretch. Where a model touches itself that surface is mostly
    hidden, so the cut leaves at most a small hole at the contact; nothing is cut when it would remove more than
    CUT_MAX_SHARE of the triangles, and vertices are never removed, so UVs and weights keep their order. `report`, when
    given, gets "shard_faces": the faces `contact_shards` finds, dropped only when DROP_SHARDS (off: kept)."""
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
    reach = arm_reach(vertices, np.asarray(joints, dtype=float), mapping)
    contact = np.zeros(len(faces), dtype=bool)
    for a, b in ((0, 1), (1, 2), (2, 0)):
        contact |= contact_edges(faces[:, [a, b]], vertex_limb, reach)
    torn |= contact  # a hand fused to a thigh is cut whether or not the test poses stretch it (AC-24)
    if torn.sum() > CUT_MAX_SHARE * len(faces):
        torn = contact if contact.sum() <= CUT_MAX_SHARE * len(faces) else np.zeros(len(faces), dtype=bool)
    shards = contact_shards(faces, torn, vertex_limb, reach, dist)
    if report is not None:
        report["shard_faces"], report["shards_dropped"] = int(shards.sum()), DROP_SHARDS
    if DROP_SHARDS:
        torn |= shards
    if torn.sum() > CUT_MAX_SHARE * len(faces):
        torn = contact if contact.sum() <= CUT_MAX_SHARE * len(faces) else np.zeros(len(faces), dtype=bool)
    return faces[~torn], int(torn.sum())


def _components(faces: np.ndarray, n: int) -> np.ndarray:
    """(n,) the connected piece of each vertex over `faces` (a vertex in no face is its own piece)."""
    parent = np.arange(n)

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]]]):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)
    return np.array([find(i) for i in range(n)])


def contact_shards(faces, torn, vertex_limb, reach, dist) -> np.ndarray:
    """(m,) bool: the faces of the pieces left after the cut that are all one arm's vertices away from its shoulder, lie
    more than SHARD_M (median) off that arm's bones, and were cut from a surface that either held that arm's own skin
    (its vertices within SHARD_M of its bones) in another piece, or was mostly not that arm (under SHARD_SHARE of its
    vertices): thigh or hip surface the contact gave to the hand, which would otherwise fly beside the hand as a shard
    (AC-24). A piece that was never joined to anything, or was cut from a surface mostly of the arm (a staff, a sword or
    a shield held in the hand, even one whose tip rests on a thigh), is kept; only its contact triangles go."""
    out = np.zeros(len(faces), dtype=bool)
    kept = faces[~torn]
    if not len(kept) or not torn.any():
        return out
    n = len(vertex_limb)
    before, after = _components(faces, n), _components(kept, n)
    used = np.zeros(n, dtype=bool)
    used[kept.ravel()] = True
    drop = np.zeros(n, dtype=bool)
    for p in np.unique(after[used]):
        members = used & (after == p)
        arms = np.unique(vertex_limb[members])
        if len(arms) != 1 or arms[0] not in ARMS or reach[members, arms[0]].any():
            continue
        arm = arms[0]
        if np.median(dist[members, arm]) <= SHARD_M:
            continue
        whole = before == before[members][0]
        skin = whole & (vertex_limb == arm) & (dist[:, arm] <= SHARD_M) & ~members
        if skin.any() or (vertex_limb[whole] == arm).mean() < SHARD_SHARE:
            drop |= members
    out[~torn] = drop[kept].all(1)
    return out
