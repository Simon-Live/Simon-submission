"""The rigged, animated figure of one person's take: skeleton, skin weights and per-frame bone rotations.

Pure Python, no I/O and no third-party package (docs/specs/take-ar.md). Input is what Part 2 measured (the SAM 3D
Body mesh in the pose3d frame and the 17 pose3d joints, per frame); output is a `Figure`: 17 bones in parent-first
order, two-bone skin weights, and for each kept frame the bone rotations and the hips position. The rig has the same
bones and the same weights rule as the browser's person skin (web/skin/person-skin.js), so the AR figure moves as the
result page's skin does. Bind is the first frame with straight arms; every bone has an identity world rotation there.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

Vec = tuple[float, float, float]
Quat = tuple[float, float, float, float]  # x, y, z, w

COCO = ("nose", "left_eye", "right_eye", "left_ear", "right_ear", "left_shoulder", "right_shoulder", "left_elbow",
        "right_elbow", "left_wrist", "right_wrist", "left_hip", "right_hip", "left_knee", "right_knee", "left_ankle",
        "right_ankle")
# name, parent, head joint, tail joint (derived names pelvis, mid, neck, headC, headTop are made by `derive`)
BONES = (
    ("hips", None, "pelvis", "mid"), ("spine", "hips", "pelvis", "mid"), ("chest", "spine", "mid", "neck"),
    ("neck", "chest", "neck", "headC"), ("head", "neck", "headC", "headTop"),
    ("leftUpperArm", "chest", "left_shoulder", "left_elbow"),
    ("leftLowerArm", "leftUpperArm", "left_elbow", "left_wrist"), ("leftHand", "leftLowerArm", "left_wrist", None),
    ("rightUpperArm", "chest", "right_shoulder", "right_elbow"),
    ("rightLowerArm", "rightUpperArm", "right_elbow", "right_wrist"),
    ("rightHand", "rightLowerArm", "right_wrist", None),
    ("leftUpperLeg", "hips", "left_hip", "left_knee"), ("leftLowerLeg", "leftUpperLeg", "left_knee", "left_ankle"),
    ("leftFoot", "leftLowerLeg", "left_ankle", None), ("rightUpperLeg", "hips", "right_hip", "right_knee"),
    ("rightLowerLeg", "rightUpperLeg", "right_knee", "right_ankle"),
    ("rightFoot", "rightLowerLeg", "right_ankle", None),
)
NAMES = tuple(b[0] for b in BONES)
INDEX = {n: i for i, n in enumerate(NAMES)}
PARENT = tuple(INDEX[b[1]] if b[1] else -1 for b in BONES)


SEGMENTS = (
    ("hips", "pelvis", "left_hip"), ("hips", "pelvis", "right_hip"), ("spine", "pelvis", "mid"),
    ("chest", "mid", "neck"), ("chest", "neck", "left_shoulder"), ("chest", "neck", "right_shoulder"),
    ("neck", "neck", "headC"), ("head", "headC", "headTop"), ("head", "headC", "nose"),
    ("leftUpperArm", "left_shoulder", "left_elbow"), ("leftLowerArm", "left_elbow", "left_wrist"),
    ("rightUpperArm", "right_shoulder", "right_elbow"), ("rightLowerArm", "right_elbow", "right_wrist"),
    ("leftUpperLeg", "left_hip", "left_knee"), ("leftLowerLeg", "left_knee", "left_ankle"),
    ("rightUpperLeg", "right_hip", "right_knee"), ("rightLowerLeg", "right_knee", "right_ankle"),
)
EPS = 0.005  # metres; keeps 1/d^2 finite for a vertex lying on a segment
GROUND_RANK = 0.004  # the sole is the vertex at this share from the bottom, so a stray vertex does not set the floor
GROUND_WINDOW = 5  # frames in the median that smooths the floor
IDENTITY: Quat = (0.0, 0.0, 0.0, 1.0)


class RigError(ValueError):
    """The take cannot be rigged; the message is one plain line."""


# ---- vector and quaternion arithmetic ------------------------------------------------------------------------


def sub(a: Vec, b: Vec) -> Vec:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def add(a: Vec, b: Vec) -> Vec:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def mul(a: Vec, k: float) -> Vec:
    return (a[0] * k, a[1] * k, a[2] * k)


def dot(a: Vec, b: Vec) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cross(a: Vec, b: Vec) -> Vec:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def norm(a: Vec) -> float:
    return math.sqrt(dot(a, a))


def unit(a: Vec) -> Vec | None:
    n = norm(a)
    return mul(a, 1.0 / n) if n > 1e-9 else None


def midpoint(a: Vec, b: Vec) -> Vec:
    return mul(add(a, b), 0.5)


def qmul(a: Quat, b: Quat) -> Quat:
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (aw * bx + ax * bw + ay * bz - az * by, aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw, aw * bw - ax * bx - ay * by - az * bz)


def qinv(q: Quat) -> Quat:
    return (-q[0], -q[1], -q[2], q[3])


def qnorm(q: Quat) -> Quat:
    n = math.sqrt(sum(c * c for c in q)) or 1.0
    return (q[0] / n, q[1] / n, q[2] / n, q[3] / n)


def qrotate(q: Quat, v: Vec) -> Vec:
    x, y, z, w = q
    tx, ty, tz = 2 * (y * v[2] - z * v[1]), 2 * (z * v[0] - x * v[2]), 2 * (x * v[1] - y * v[0])
    return (v[0] + w * tx + (y * tz - z * ty), v[1] + w * ty + (z * tx - x * tz), v[2] + w * tz + (x * ty - y * tx))


def qslerp(a: Quat, b: Quat, t: float) -> Quat:
    d = sum(x * y for x, y in zip(a, b))
    if d < 0:
        b, d = (-b[0], -b[1], -b[2], -b[3]), -d
    if d > 0.9995:
        return qnorm(tuple(x + t * (y - x) for x, y in zip(a, b)))  # type: ignore[arg-type]
    th = math.acos(min(1.0, d))
    s = math.sin(th)
    ka, kb = math.sin((1 - t) * th) / s, math.sin(t * th) / s
    return qnorm(tuple(ka * x + kb * y for x, y in zip(a, b)))  # type: ignore[arg-type]


def swing(a: Vec, b: Vec) -> Quat:
    """The shortest rotation taking direction `a` onto direction `b` (unit vectors)."""
    d = dot(a, b)
    if d < -0.999999:  # opposite: any axis perpendicular to a
        axis = unit(cross(a, (1.0, 0.0, 0.0))) or unit(cross(a, (0.0, 1.0, 0.0))) or (0.0, 0.0, 1.0)
        return (axis[0], axis[1], axis[2], 0.0)
    c = cross(a, b)
    return qnorm((c[0], c[1], c[2], 1.0 + d))


def from_basis(x: Vec, y: Vec, z: Vec) -> Quat:
    """The unit quaternion of the rotation whose columns are the orthonormal x, y, z."""
    m00, m10, m20, m01, m11, m21, m02, m12, m22 = x[0], x[1], x[2], y[0], y[1], y[2], z[0], z[1], z[2]
    tr = m00 + m11 + m22
    if tr > 0:
        s = math.sqrt(tr + 1.0) * 2
        q = ((m21 - m12) / s, (m02 - m20) / s, (m10 - m01) / s, 0.25 * s)
    elif m00 > m11 and m00 > m22:
        s = math.sqrt(1.0 + m00 - m11 - m22) * 2
        q = (0.25 * s, (m01 + m10) / s, (m02 + m20) / s, (m21 - m12) / s)
    elif m11 > m22:
        s = math.sqrt(1.0 + m11 - m00 - m22) * 2
        q = ((m01 + m10) / s, 0.25 * s, (m12 + m21) / s, (m02 - m20) / s)
    else:
        s = math.sqrt(1.0 + m22 - m00 - m11) * 2
        q = ((m02 + m20) / s, (m12 + m21) / s, 0.25 * s, (m10 - m01) / s)
    return qnorm(q)


def facing(side: Vec, up: Vec) -> Quat | None:
    """The orientation of a body part from its left-pointing axis `side` and its up axis; None when they are parallel."""
    x = unit(side)
    z = unit(cross(side, up)) if x else None
    if x is None or z is None:
        return None
    return from_basis(x, cross(z, x), z)


# ---- joints ---------------------------------------------------------------------------------------------------


def derive(joints: dict[str, Vec]) -> dict[str, Vec]:
    """The 17 keypoints plus pelvis, mid, neck, headC and headTop."""
    j = dict(joints)
    j["pelvis"] = midpoint(j["left_hip"], j["right_hip"])
    j["neck"] = midpoint(j["left_shoulder"], j["right_shoulder"])
    j["mid"] = midpoint(j["pelvis"], j["neck"])
    j["headC"] = midpoint(j["left_ear"], j["right_ear"])
    j["headTop"] = add(j["headC"], mul(sub(j["headC"], j["neck"]), 0.6))
    return j


def _world_rotations(j: dict[str, Vec], rest: dict[str, Vec]) -> list[Quat]:
    """World rotation of each bone, relative to bind, from this frame's derived joints `j` and the bind joints `rest`."""
    def part(side_a: str, side_b: str, up_a: str, up_b: str) -> Quat:
        now = facing(sub(j[side_a], j[side_b]), sub(j[up_b], j[up_a]))
        then = facing(sub(rest[side_a], rest[side_b]), sub(rest[up_b], rest[up_a]))
        return qmul(now, qinv(then)) if now and then else IDENTITY

    def limb(name: str) -> Quat:
        _, _, head, tail = BONES[INDEX[name]]
        a, b = unit(sub(rest[tail], rest[head])), unit(sub(j[tail], j[head]))
        return swing(a, b) if a and b else IDENTITY

    q: dict[str, Quat] = {"hips": part("left_hip", "right_hip", "pelvis", "neck")}
    q["chest"] = part("left_shoulder", "right_shoulder", "mid", "neck")
    q["spine"] = qslerp(q["hips"], q["chest"], 0.5)
    q["neck"] = limb("neck")
    q["head"] = part("left_ear", "right_ear", "headC", "headTop")
    for s in ("left", "right"):
        for n in ("UpperArm", "LowerArm", "UpperLeg", "LowerLeg"):
            q[s + n] = limb(s + n)
        q[s + "Hand"], q[s + "Foot"] = q[s + "LowerArm"], q[s + "LowerLeg"]
    return [q[n] for n in NAMES]


def _local(world: list[Quat]) -> list[Quat]:
    out: list[Quat] = []
    for i, w in enumerate(world):
        out.append(w if PARENT[i] < 0 else qnorm(qmul(qinv(world[PARENT[i]]), w)))
    return out


# ---- skin -----------------------------------------------------------------------------------------------------


TORSO = frozenset(INDEX[b] for b in ("hips", "spine", "chest", "neck"))  # may share a vertex with any bone
MOTION_MAX = 64  # frames weighed for the skin, as part7.mesh_files serves them to the browser


def motion_sample(count: int, rest_index: int) -> list[int]:
    """The frame positions the skin is weighed over: up to MOTION_MAX spread evenly, plus the bind frame."""
    step = max(1, math.ceil(count / MOTION_MAX))
    picked = list(range(0, count, step))
    return picked if rest_index in picked else [rest_index, *picked]


Segment = tuple[float, float, float, float, float, float, float]  # head x, y, z, head-to-tail x, y, z, squared length


def segment(a: Vec, b: Vec) -> Segment:
    """A bone segment from head `a` to tail `b`, in the form `seg_d2` reads."""
    dx, dy, dz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
    return (a[0], a[1], a[2], dx, dy, dz, dx * dx + dy * dy + dz * dz)


def seg_d2(px: float, py: float, pz: float, s: Segment) -> float:
    """Squared distance from a point to a segment: the one point-to-segment helper of Part 7's Python (heat.py uses it
    too). web/skin/motion-weights.js `segD2` is the same arithmetic, operation for operation, so both give equal bits."""
    ax, ay, az, dx, dy, dz, l2 = s
    qx, qy, qz = px - ax, py - ay, pz - az
    t = (qx * dx + qy * dy + qz * dz) / l2 if l2 else 0.0
    t = 0.0 if t < 0.0 else 1.0 if t > 1.0 else t
    ex, ey, ez = qx - dx * t, qy - dy * t, qz - dz * t
    return ex * ex + ey * ey + ez * ez


def motion_weights(frames: list[tuple[list[Vec], dict[str, Vec]]]) -> tuple[list[tuple[int, int]], list[tuple[float, float]]]:
    """Two bones per vertex: the one it stays nearest over `frames` (verts, derived joints), by the power mean (p = 8) of
    its distance to each bone, and the nearest bone joined to it (any bone when either is a torso bone); weights 1/c^2,
    sum 1. A vertex beside a hanging forearm in one frame is ruled out of that arm by any frame where the arm is away
    (docs/specs/person-skin.md AC-PS17). web/skin/motion-weights.js is the same arithmetic in the same order (powers by
    multiplication, roots by sqrt), so the two agree bit for bit on the shared test vector (AC-PS18)."""
    n = len(frames[0][0])
    nb = len(NAMES)
    acc = [0.0] * (n * nb)
    for verts, j in frames:
        segs = [(INDEX[b], segment(j[f], j[t])) for b, f, t in SEGMENTS]
        for i, (px, py, pz) in enumerate(verts):
            near: dict[int, float] = {}
            for b, s in segs:
                d2 = seg_d2(px, py, pz, s)
                if d2 < near.get(b, math.inf):
                    near[b] = d2
            base = i * nb
            for b, d2 in near.items():
                d4 = d2 * d2
                acc[base + b] += d4 * d4
    owned = sorted({INDEX[b] for b, _, _ in SEGMENTS})
    bones: list[tuple[int, int]] = []
    weights: list[tuple[float, float]] = []
    for i in range(n):
        cost = {b: math.sqrt(math.sqrt(math.sqrt(acc[i * nb + b] / len(frames)))) for b in owned}
        b0 = min(cost, key=lambda b: (cost[b], b))
        joined = [b for b in cost if b != b0 and (PARENT[b] == b0 or PARENT[b0] == b or b in TORSO or b0 in TORSO)]
        b1 = min(joined, key=lambda b: (cost[b], b)) if joined else b0
        c0, c1 = cost[b0] + EPS, cost[b1] + EPS
        w0 = 1.0 / (c0 * c0)
        w1 = 1.0 / (c1 * c1) if b1 != b0 else 0.0
        bones.append((b0, b1))
        weights.append((w0 / (w0 + w1), w1 / (w0 + w1)))
    return bones, weights


# ---- the figure -----------------------------------------------------------------------------------------------


@dataclass
class Figure:
    """One person: bind pose, skin and animation. Metres, Y up, facing +Z, the subject's left on +X."""

    name: str
    rest_joints: dict[str, Vec]
    bone_head: list[Vec]  # bind world position of each bone
    positions: list[Vec]  # bind mesh
    faces: list[int]
    bones: list[tuple[int, int]]
    weights: list[tuple[float, float]]
    times: list[float] = field(default_factory=list)  # seconds from the first kept frame
    rotations: list[list[Quat]] = field(default_factory=list)  # per frame, local rotation of each bone
    hips: list[Vec] = field(default_factory=list)  # per frame, world position of the hips bone, standing on y = 0
    measured: list[list[Vec]] = field(default_factory=list)  # per frame, the measured mesh (for the fit check only)
    ground: list[float] = field(default_factory=list)

    def local_offset(self, bone: int) -> Vec:
        p = PARENT[bone]
        return self.bone_head[bone] if p < 0 else sub(self.bone_head[bone], self.bone_head[p])

    @property
    def duration_s(self) -> float:
        return self.times[-1] if self.times else 0.0


def _sole(verts: list[Vec]) -> float:
    ys = sorted(v[1] for v in verts)
    return ys[min(len(ys) - 1, int(len(ys) * GROUND_RANK))]


def _median_filter(xs: list[float], width: int) -> list[float]:
    h = width // 2
    return [sorted(xs[max(0, i - h):i + h + 1])[len(xs[max(0, i - h):i + h + 1]) // 2] for i in range(len(xs))]


@dataclass
class Frame:
    t_s: float
    joints: dict[str, Vec]
    verts: list[Vec]


def build_figure(name: str, faces: list[int], frames: list[Frame],
                 rest_index: int) -> Figure:
    """Rig the person: bind at `frames[rest_index]`, then one pose of the bones for every frame."""
    if len(frames) < 2:
        raise RigError("The take has fewer than two frames with a measured body.")
    if not 0 <= rest_index < len(frames):
        raise RigError("The take has no frame to bind the figure to.")
    rest = derive(frames[rest_index].joints)
    heads = [rest[b[2]] for b in BONES]
    # the take's own frames say which bones each vertex moves with; the label rule binds the waist to a hanging forearm
    sample = motion_sample(len(frames), rest_index)
    bones, weights = motion_weights([(frames[k].verts, rest if k == rest_index else derive(frames[k].joints)) for k in sample])
    fig = Figure(name, rest, heads, frames[rest_index].verts, faces, bones, weights)
    t0 = frames[0].t_s
    ground = _median_filter([_sole(f.verts) for f in frames], GROUND_WINDOW)
    for f, g in zip(frames, ground):
        j = derive(f.joints)
        fig.times.append(f.t_s - t0)
        fig.rotations.append(_local(_world_rotations(j, rest)))
        fig.hips.append((j["pelvis"][0], j["pelvis"][1] - g, j["pelvis"][2]))
        fig.measured.append(f.verts)
        fig.ground.append(g)
    return fig


def pose_vertices(fig: Figure, frame: int) -> list[Vec]:
    """The skinned mesh at `frame`, in the figure's standing frame (linear blend of two bones per vertex)."""
    world: list[tuple[Quat, Vec]] = []
    for i, local in enumerate(fig.rotations[frame]):
        if PARENT[i] < 0:
            world.append((local, fig.hips[frame]))
        else:
            pq, pp = world[PARENT[i]]
            world.append((qnorm(qmul(pq, local)), add(pp, qrotate(pq, fig.local_offset(i)))))
    out: list[Vec] = []
    for p, (b0, b1), (w0, w1) in zip(fig.positions, fig.bones, fig.weights):
        acc = (0.0, 0.0, 0.0)
        for b, w in ((b0, w0), (b1, w1)):
            if w:
                q, pos = world[b]
                acc = add(acc, mul(add(pos, qrotate(q, sub(p, fig.bone_head[b]))), w))
        out.append(acc)
    return out


def fit_error_m(fig: Figure) -> dict[str, float]:
    """Mean and largest per-frame mean distance (metres) between the skinned mesh and the measured mesh, same vertices."""
    means = []
    for k in range(len(fig.times)):
        posed = pose_vertices(fig, k)
        shift = (0.0, -fig.ground[k], 0.0)
        means.append(sum(norm(sub(a, add(b, shift))) for a, b in zip(posed, fig.measured[k])) / len(posed))
    return {"mean": sum(means) / len(means), "worst_frame_mean": max(means)}
