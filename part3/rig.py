"""Part 4's rig: hierarchy, rest offsets, forward kinematics and rotation fitting.

Spec: docs/specs/integration-contract.md "Part 4 rig and rotations" (TICKET-025). Numpy only; written
from Part 4's documented convention, never imported from it.

Convention. Quaternions are `(x, y, z, w)`, Hamilton product, active rotation. For every joint `j`
with parent `p`: `global[j] = global[p] * local[j]` and
`position[j] = position[p] + rotate(global[p], offset[j])`. `pelvis` is the root at the origin. A joint's
local rotation orients the bones that leave it; it never moves the joint itself. Output positions
are taken relative to the hip midpoint.
"""

import functools
import json

import numpy as np

from part3 import standard
from part3.joints import JOINTS

ROOT_JOINT = "pelvis"

# child -> parent, exactly Part 4's rig. The insertion order is Part 4's FK order (parents first).
HIERARCHY = {
    "left_hip": "pelvis", "left_knee": "left_hip", "left_ankle": "left_knee",
    "right_hip": "pelvis", "right_knee": "right_hip", "right_ankle": "right_knee",
    "neck": "pelvis",
    "left_shoulder": "neck", "left_elbow": "left_shoulder", "left_wrist": "left_elbow",
    "right_shoulder": "neck", "right_elbow": "right_shoulder", "right_wrist": "right_elbow",
    "nose": "neck", "left_eye": "nose", "left_ear": "left_eye",
    "right_eye": "nose", "right_ear": "right_eye",
}
FK_ORDER = tuple(HIERARCHY)
ROTATED = (ROOT_JOINT,) + FK_ORDER  # the 19 joints that carry a local rotation
CHILDREN = {joint: tuple(c for c in FK_ORDER if HIERARCHY[c] == joint) for joint in ROTATED}

CONVENTION = (
    "quaternions (x, y, z, w), Hamilton product, active rotation; global[j] = global[parent] * local[j]; "
    "position[j] = position[parent] + rotate(global[parent], offset[j]); pelvis at the origin; "
    "positions relative to the hip midpoint. Fit: weighted Kabsch where a joint has several children "
    "(pelvis, neck, nose), shortest arc in the parent frame where it has one, identity at the leaves; "
    "shoulders and hips add the twist about their bone that keeps their own and the elbow's or knee's "
    "rotation closest to the previous key (the first key: closest to rest)."
)
# A twist about a shoulder's or hip's own bone moves no joint; it only changes how the elbow's or
# knee's bend is split between the two rotations. Chosen per key for continuity (ASM-020).
TWIST_CHILD = {"left_shoulder": "left_elbow", "right_shoulder": "right_elbow",
               "left_hip": "left_knee", "right_hip": "right_knee"}
TWIST_COARSE_DEG = 5.0
TWIST_FINE_DEG = 0.5
TWIST_TIE = 1e-3  # radians of score per radian of twist: with no gain, no twist

_ANTIPARALLEL = 1e-12  # 1 + cos(angle) below this counts as a 180 degree turn
_TINY = 1e-12


# --- quaternion and matrix helpers -------------------------------------------------------------

def quat_to_matrix(q):
    """3x3 rotation matrix of the quaternion (x, y, z, w); the quaternion is normalised first."""
    x, y, z, w = _unit(q)
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])


def matrix_to_quat(R):
    """Unit quaternion (x, y, z, w) of a rotation matrix with w >= 0 (first non-zero part positive at w = 0)."""
    t = R[0, 0] + R[1, 1] + R[2, 2]
    if t > 0:
        s = 2 * np.sqrt(t + 1)
        q = [(R[2, 1] - R[1, 2]) / s, (R[0, 2] - R[2, 0]) / s, (R[1, 0] - R[0, 1]) / s, s / 4]
    elif R[0, 0] > R[1, 1] and R[0, 0] > R[2, 2]:
        s = 2 * np.sqrt(1 + R[0, 0] - R[1, 1] - R[2, 2])
        q = [s / 4, (R[0, 1] + R[1, 0]) / s, (R[0, 2] + R[2, 0]) / s, (R[2, 1] - R[1, 2]) / s]
    elif R[1, 1] > R[2, 2]:
        s = 2 * np.sqrt(1 + R[1, 1] - R[0, 0] - R[2, 2])
        q = [(R[0, 1] + R[1, 0]) / s, s / 4, (R[1, 2] + R[2, 1]) / s, (R[0, 2] - R[2, 0]) / s]
    else:
        s = 2 * np.sqrt(1 + R[2, 2] - R[0, 0] - R[1, 1])
        q = [(R[0, 2] + R[2, 0]) / s, (R[1, 2] + R[2, 1]) / s, s / 4, (R[1, 0] - R[0, 1]) / s]
    return canonical_quat(q)


def canonical_quat(q):
    """The unit quaternion with w >= 0; at w = 0 the first non-zero part is made positive."""
    q = _unit(q)
    if q[3] < -_TINY:
        return -q
    if abs(q[3]) <= _TINY:
        first = next((v for v in q[:3] if abs(v) > _TINY), 0.0)
        return -q if first < 0 else q
    return q


def _unit(q):
    q = np.asarray(q, dtype=float)
    norm = np.linalg.norm(q)
    return q / norm if norm > _TINY else np.array([0.0, 0.0, 0.0, 1.0])


# --- Part 4's long-way rule ----------------------------------------------------------------------

MAX_ROTVEC_STEP_DEG = 180.0  # Part 4 README "The file is rejected": more than this between neighbouring keys
# The one next step for a long-way turn, worded for the part4 view's refusal and for `doctor` (review residual 9).
LONG_WAY_FIX = "add keys between them (a smaller every:<n>) or use another view"


def rotation_vector(q):
    """Axis times angle in radians of (x, y, z, w), taken with w >= 0 so the angle is 0 to 180 degrees."""
    q = _unit(q)
    if q[3] < 0:
        q = -q
    angle = 2.0 * np.arccos(np.clip(q[3], -1.0, 1.0))
    s = np.sqrt(max(0.0, 1.0 - q[3] * q[3]))
    return np.zeros(3) if s < 1e-8 or angle < 1e-8 else q[:3] * (angle / s)


def long_way(keyframes):
    """Steps Part 4 rejects: [{joint, from_index, to_index, deg}] over every rotated joint, in key order.

    Part 4 aligns each key's quaternion to the hemisphere of the previous key (the first to identity),
    turns it into a rotation vector with the angle in 0 to 180 degrees, and rejects any step between
    neighbouring keys longer than 180 degrees in that space. `keyframes` is a list of dicts with
    `index` and `local_rotations`.
    """
    steps = []
    for joint in ROTATED:
        previous_q, previous_v, previous_index = np.array([0.0, 0.0, 0.0, 1.0]), None, None
        for key in keyframes:
            q = _unit(key["local_rotations"][joint])
            if float(np.dot(q, previous_q)) < 0.0:
                q = -q
            v = rotation_vector(q)
            if previous_v is not None:
                deg = float(np.degrees(np.linalg.norm(v - previous_v)))
                if deg > MAX_ROTVEC_STEP_DEG:
                    steps.append({"joint": joint, "from_index": previous_index, "to_index": key["index"],
                                  "deg": round(deg, 1)})
            previous_q, previous_v, previous_index = q, v, key["index"]
    return steps


# --- rest offsets ------------------------------------------------------------------------------

@functools.lru_cache(maxsize=1)
def _head_directions():
    """Unit directions of nose (from neck), eyes (from nose) and ears (from eye) in the neutral head model."""
    with open(standard.STANDARD_BODY_PATH, encoding="utf-8") as handle:
        head = json.load(handle)["neutral_head_m"]
    point = {name: np.array(value, dtype=float) for name, value in head.items()}
    links = {"nose": "neck", "left_eye": "nose", "right_eye": "nose", "left_ear": "left_eye",
             "right_ear": "right_eye"}
    return {child: _direction(point[child] - point[parent]) for child, parent in links.items()}


def _direction(vector):
    return vector / np.linalg.norm(vector)


def rest_offsets(bone_lengths_m):
    """{joint: {"parent": parent, "offset": [x, y, z]}} for the 18 non-root joints, in FK order (metres).

    Hips and shoulders sit on the x axis, legs hang down y, the spine rises along y and the arms rest
    in a T-pose along the x axis (left +x, right -x). A T-pose arm is 90 degrees from both hanging
    and overhead, so a fitted arm stays clear of the 180 degree turn that Part 4 rejects between
    keys (review B2). Nose, eyes and ears point as in the neutral head model of `standard_body.json`,
    at the profile's head, eye link and ear link lengths.
    """
    L = bone_lengths_m
    head = _head_directions()
    offsets = {
        "left_hip": [L["left_pelvis"], 0.0, 0.0], "right_hip": [-L["right_pelvis"], 0.0, 0.0],
        "left_knee": [0.0, -L["left_thigh"], 0.0], "right_knee": [0.0, -L["right_thigh"], 0.0],
        "left_ankle": [0.0, -L["left_shank"], 0.0], "right_ankle": [0.0, -L["right_shank"], 0.0],
        "neck": [0.0, L["spine"], 0.0],
        "left_shoulder": [L["left_clavicle"], 0.0, 0.0], "right_shoulder": [-L["right_clavicle"], 0.0, 0.0],
        "left_elbow": [L["left_upper_arm"], 0.0, 0.0], "right_elbow": [-L["right_upper_arm"], 0.0, 0.0],
        "left_wrist": [L["left_forearm"], 0.0, 0.0], "right_wrist": [-L["right_forearm"], 0.0, 0.0],
        "nose": _scaled(head["nose"], L["head"]),
        "left_eye": _scaled(head["left_eye"], L["left_eye_link"]),
        "right_eye": _scaled(head["right_eye"], L["right_eye_link"]),
        "left_ear": _scaled(head["left_ear"], L["left_ear_link"]),
        "right_ear": _scaled(head["right_ear"], L["right_ear_link"]),
    }
    return {joint: {"parent": HIERARCHY[joint], "offset": offsets[joint]} for joint in FK_ORDER}


def _scaled(direction, length):
    return [float(v) for v in direction * length]


# --- forward kinematics ------------------------------------------------------------------------

def _local_matrix(local_rotations, joint):
    if joint not in local_rotations:
        raise ValueError(f"missing a rotation for {joint}")
    raw = np.asarray(local_rotations[joint], dtype=float)
    if raw.shape != (4,):
        raise ValueError(f"{joint} rotation must be a quaternion (x, y, z, w)")
    if np.linalg.norm(raw) < 1e-8:
        raise ValueError(f"{joint} rotation is zero")
    return quat_to_matrix(raw)


def forward(local_rotations, rest_offsets):
    """Joint positions {name: array(3)} of the 17 canonical joints, relative to the hip midpoint.

    `local_rotations` holds a quaternion per `ROTATED` joint; `rest_offsets` is the `rest_offsets`
    shape. Raises ValueError for a missing or zero rotation (Part 4's own messages).
    """
    glob = {ROOT_JOINT: _local_matrix(local_rotations, ROOT_JOINT)}
    pos = {ROOT_JOINT: np.zeros(3)}
    for joint in FK_ORDER:
        entry = rest_offsets[joint]
        parent = entry["parent"]
        pos[joint] = pos[parent] + glob[parent] @ np.asarray(entry["offset"], dtype=float)
        glob[joint] = glob[parent] @ _local_matrix(local_rotations, joint)
    middle = 0.5 * (pos["left_hip"] + pos["right_hip"])
    return {name: pos[name] - middle for name in JOINTS}


# --- fitting -----------------------------------------------------------------------------------

def _subtree_weight(joint):
    """Canonical joints in the subtree rooted at `joint` (the virtual neck counts none itself)."""
    own = 1 if joint in JOINTS else 0
    return own + sum(_subtree_weight(child) for child in CHILDREN.get(joint, ()))


WEIGHTS = {joint: _subtree_weight(joint) for joint in FK_ORDER}


def _vector(value):
    if isinstance(value, dict):
        return np.array([value["x"], value["y"], value["z"]], dtype=float)
    return np.asarray(value, dtype=float)


def _targets(joints):
    """Target positions {name: array(3)} relative to the hip midpoint, plus `pelvis` (origin) and `neck`."""
    if isinstance(joints, dict):
        points = {name: _vector(joints[name]) for name in JOINTS}
    else:
        array = np.asarray(joints, dtype=float)
        if array.shape != (len(JOINTS), 3):
            raise ValueError(f"joints must be a {{name: [x, y, z]}} dict or a ({len(JOINTS)}, 3) array")
        points = {name: array[i] for i, name in enumerate(JOINTS)}
    middle = 0.5 * (points["left_hip"] + points["right_hip"])
    target = {name: point - middle for name, point in points.items()}
    target[ROOT_JOINT] = np.zeros(3)
    target["neck"] = 0.5 * (target["left_shoulder"] + target["right_shoulder"])
    return target


def residuals(fk_joints, joints):
    """{joint: metres} distance of each FK joint to its target (`joints` made relative to the hip midpoint)."""
    target = _targets(joints)
    return {name: float(np.linalg.norm(np.asarray(fk_joints[name], dtype=float) - target[name]))
            for name in JOINTS}


def _arc(rest, goal):
    """Shortest-arc rotation matrix taking the direction of `rest` onto the direction of `goal`.

    A zero `goal` leaves the joint at rest. An exactly opposite direction turns 180 degrees about the
    perpendicular `rest x e`, where `e` is the coordinate axis least aligned with `rest` (lowest index
    on ties), so the answer is deterministic.
    """
    norm = np.linalg.norm(goal)
    if norm < _TINY:
        return np.eye(3)
    a, b = rest / np.linalg.norm(rest), goal / norm
    cosine = float(a @ b)
    if 1 + cosine < _ANTIPARALLEL:
        axis = np.cross(a, np.eye(3)[int(np.argmin(np.abs(a)))])
        return quat_to_matrix(np.append(_direction(axis), 0.0))
    return quat_to_matrix(np.append(np.cross(a, b), 1 + cosine))


def _kabsch(rests, goals, weights):
    """Rotation matrix R minimising sum(w * |R rest - goal|^2) (weighted Kabsch, proper rotation)."""
    H = sum(w * np.outer(a, b) for w, a, b in zip(weights, rests, goals))
    U, _, Vt = np.linalg.svd(H)
    sign = 1.0 if np.linalg.det(Vt.T @ U.T) >= 0 else -1.0
    return Vt.T @ np.diag([1.0, 1.0, sign]) @ U.T


def _fit_joint(joint, parent_global, origin, target, offsets):
    """Local rotation matrix of `joint` that points its child offsets at their targets."""
    children = CHILDREN[joint]
    if not children:
        return np.eye(3)
    rests = [np.asarray(offsets[c]["offset"], dtype=float) for c in children]
    goals = [parent_global.T @ (target[c] - origin) for c in children]
    if len(children) == 1:
        return _arc(rests[0], goals[0])
    return _kabsch(rests, goals, [WEIGHTS[c] for c in children])


def _axis_angle(axis, theta):
    """Rotation matrix of `theta` radians about the unit direction of `axis`."""
    a = _direction(np.asarray(axis, dtype=float))
    K = np.array([[0.0, -a[2], a[1]], [a[2], 0.0, -a[0]], [-a[1], a[0], 0.0]])
    return np.eye(3) + np.sin(theta) * K + (1 - np.cos(theta)) * (K @ K)


def _rotvecs_of_quats(q):
    """Rotation vectors (n, 3) of quaternions (n, 4) taken with w >= 0, as `rotation_vector`."""
    q = q / np.linalg.norm(q, axis=1, keepdims=True)
    q = np.where(q[:, 3:4] < 0, -q, q)
    angle = 2.0 * np.arccos(np.clip(q[:, 3], -1.0, 1.0))
    s = np.sqrt(np.maximum(0.0, 1.0 - q[:, 3] ** 2))
    scale = np.where((s < 1e-8) | (angle < 1e-8), 0.0, angle / np.where(s < 1e-8, 1.0, s))
    return q[:, :3] * scale[:, None]


def _arc_rotvecs(rest, goals):
    """Rotation vectors (n, 3) of the shortest arcs from `rest` onto each of `goals` (n, 3)."""
    a = _direction(np.asarray(rest, dtype=float))
    b = goals / np.maximum(np.linalg.norm(goals, axis=1, keepdims=True), _TINY)
    axis = np.cross(a, b)
    sin = np.linalg.norm(axis, axis=1)
    angle = np.arctan2(sin, b @ a)
    return np.where(sin[:, None] > 1e-12, axis / np.maximum(sin, 1e-12)[:, None] * angle[:, None], 0.0)


def _steps(rotvecs, previous):
    """Part 4's step (radians) from `previous` to each rotation vector; without one, the angle from
    rest. Part 4 aligns hemispheres and then takes the angle in 0 to 180 degrees, so the step is the
    distance between the w >= 0 rotation vectors (`long_way`)."""
    if previous is None:
        return np.linalg.norm(rotvecs, axis=1)
    return np.linalg.norm(rotvecs - rotation_vector(previous), axis=1)


def _twist_scores(thetas, joint, local, parent_global, origin, target, offsets, previous):
    """Score per twist: the larger Part 4 step of the twisted joint and its child, plus the tie-break."""
    child = TWIST_CHILD[joint]
    offset = np.asarray(offsets[child]["offset"], dtype=float)
    grand = CHILDREN[child][0]
    bone = _direction(local @ offset)
    half = thetas / 2.0
    twist = np.column_stack([np.outer(np.sin(half), bone), np.cos(half)])
    base = matrix_to_quat(local)
    # Hamilton product twist * base, vectorised over the twists.
    x1, y1, z1, w1 = twist.T
    x2, y2, z2, w2 = base
    quats = np.column_stack([w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2, w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
                             w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2, w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2])
    child_pos = origin + parent_global @ local @ offset
    u = parent_global.T @ (target[grand] - child_pos)  # the grandchild in the joint's parent frame
    c, s = np.cos(-thetas)[:, None], np.sin(-thetas)[:, None]
    turned = u * c + np.cross(bone, u) * s + np.outer(1 - c[:, 0], bone) * (bone @ u)  # twist^T u
    goals = turned @ local  # local^T (twist^T u), row by row
    prev = (None, None) if previous is None else (previous.get(joint), previous.get(child))
    own = _steps(_rotvecs_of_quats(quats), prev[0])
    kid = _steps(_arc_rotvecs(offsets[grand]["offset"], goals), prev[1])
    return np.maximum(own, kid) + TWIST_TIE * np.abs(thetas)


def _twisted(joint, local, parent_global, origin, target, offsets, previous):
    """`local` turned about its own bone by the twist that minimises the larger Part 4 step of the
    joint and its child (TWIST_CHILD), searched every TWIST_COARSE_DEG then TWIST_FINE_DEG, and kept
    only when it scores below no twist."""
    child = TWIST_CHILD[joint]
    bone = local @ np.asarray(offsets[child]["offset"], dtype=float)
    if np.linalg.norm(bone) < _TINY or not CHILDREN[child]:
        return local

    def scores(thetas):
        return _twist_scores(thetas, joint, local, parent_global, origin, target, offsets, previous)

    coarse = np.radians(np.arange(-180.0, 180.0, TWIST_COARSE_DEG))
    best = coarse[int(np.argmin(scores(coarse)))]
    fine = best + np.radians(np.arange(-TWIST_COARSE_DEG, TWIST_COARSE_DEG + 1e-9, TWIST_FINE_DEG))
    fine_scores = scores(fine)
    best = fine[int(np.argmin(fine_scores))]
    if float(fine_scores.min()) >= float(scores(np.array([0.0]))[0]):
        return local
    return _axis_angle(bone, best) @ local


def fit(joints, rest_offsets, previous=None):
    """Local rotations that pose the rig closest to `joints`.

    `joints` is a {name: [x, y, z]} dict (a {x, y, z} object works too) or a (17, 3) array in canonical
    order; positions are taken relative to their hip midpoint. A joint with several children takes the
    weighted Kabsch rotation of its rest offsets onto the target child vectors (weights are the
    canonical joints in each child's subtree); a joint with one child takes the shortest arc in its
    parent's frame (no twist); leaves carry identity. Every target vector is measured from the
    already fitted position of the joint.

    Returns `(local_rotations, fk_joints, residual_m)`: {joint: [x, y, z, w]} with w >= 0 for the 19
    `ROTATED` joints, the `forward` result of those rotations, and the distance in metres of each of
    the 17 FK joints to its target. A pose the rig can reproduce comes back exactly (the rotations of
    single-child joints may differ from the original by a twist, the positions do not).

    `previous` is the previous key's local rotations (None for the first key). Shoulders and hips
    (TWIST_CHILD) then take the twist about their own bone that keeps their rotation and the elbow's
    or knee's closest to `previous` in Part 4's rotation-vector space, so a bent elbow that swings
    behind the head stays under Part 4's 180 degree step (ASM-020). The twist moves no joint.
    """
    target = _targets(joints)
    rotations, glob, pos = {}, {}, {ROOT_JOINT: np.zeros(3)}
    for joint in ROTATED:
        parent_global = np.eye(3) if joint == ROOT_JOINT else glob[HIERARCHY[joint]]
        local = _fit_joint(joint, parent_global, pos[joint], target, rest_offsets)
        if joint in TWIST_CHILD:
            local = _twisted(joint, local, parent_global, pos[joint], target, rest_offsets, previous)
        rotations[joint] = matrix_to_quat(local)
        glob[joint] = parent_global @ local
        for child in CHILDREN[joint]:
            pos[child] = pos[joint] + glob[joint] @ np.asarray(rest_offsets[child]["offset"], dtype=float)
    fk = forward(rotations, rest_offsets)
    return {j: [float(v) for v in q] for j, q in rotations.items()}, fk, residuals(fk, joints)
