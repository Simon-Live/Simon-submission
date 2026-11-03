"""Pose transfer on the follower's own body for the heat view (docs/specs/heat.md, TICKET-274).

`retarget(follower, trainer)` takes two `{joint: (x, y, z)}` skeletons in the pose3d canonical frame and answers the
rigid transform of each body segment that moves the follower's body into the trainer's bone directions while keeping
the follower's own bone lengths (body shape is normalised away). Same directions give the identity for every segment.
Pure functions over tuples; no I/O. TICKET-265 landed no server-side transfer, so this is the minimal shared one.
"""

from __future__ import annotations

import math
from typing import Dict, Tuple

Vec = Tuple[float, float, float]
Mat = Tuple[Vec, Vec, Vec]
Skeleton = Dict[str, Vec]
IDENTITY: Mat = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
EPS = 1e-9
SIDES = ("left", "right")
LIMBS = {"arm": ("shoulder", "elbow", "wrist"), "leg": ("hip", "knee", "ankle")}


def sub(a: Vec, b: Vec) -> Vec:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def add(a: Vec, b: Vec) -> Vec:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def scale(a: Vec, k: float) -> Vec:
    return (a[0] * k, a[1] * k, a[2] * k)


def dot(a: Vec, b: Vec) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cross(a: Vec, b: Vec) -> Vec:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def norm(a: Vec) -> float:
    return math.sqrt(dot(a, a))


def unit(a: Vec) -> Vec | None:
    n = norm(a)
    return scale(a, 1.0 / n) if n > EPS else None


def mid(a: Vec, b: Vec) -> Vec:
    return scale(add(a, b), 0.5)


def apply(m: Mat, v: Vec) -> Vec:
    return (dot(m[0], v), dot(m[1], v), dot(m[2], v))


def transpose(m: Mat) -> Mat:
    return ((m[0][0], m[1][0], m[2][0]), (m[0][1], m[1][1], m[2][1]), (m[0][2], m[1][2], m[2][2]))


def matmul(a: Mat, b: Mat) -> Mat:
    bt = transpose(b)
    return tuple(tuple(dot(row, col) for col in bt) for row in a)  # type: ignore[return-value]


def arc(a: Vec, b: Vec) -> Mat:
    """The smallest rotation taking direction `a` onto direction `b` (identity when either has no length)."""
    ua, ub = unit(a), unit(b)
    if ua is None or ub is None:
        return IDENTITY
    c = dot(ua, ub)
    if c < -1 + 1e-9:  # opposite: half turn about any axis perpendicular to a
        axis = unit(cross(ua, (1.0, 0.0, 0.0) if abs(ua[0]) < 0.9 else (0.0, 1.0, 0.0)))
        assert axis is not None
        return _axis_angle(axis, math.pi)
    v = cross(ua, ub)
    k = 1.0 / (1.0 + c)
    return ((1 - k * (v[1] ** 2 + v[2] ** 2), k * v[0] * v[1] - v[2], k * v[0] * v[2] + v[1]),
            (k * v[0] * v[1] + v[2], 1 - k * (v[0] ** 2 + v[2] ** 2), k * v[1] * v[2] - v[0]),
            (k * v[0] * v[2] - v[1], k * v[1] * v[2] + v[0], 1 - k * (v[0] ** 2 + v[1] ** 2)))


def _axis_angle(axis: Vec, angle: float) -> Mat:
    c, s, t = math.cos(angle), math.sin(angle), 1 - math.cos(angle)
    x, y, z = axis
    return ((t * x * x + c, t * x * y - s * z, t * x * z + s * y),
            (t * x * y + s * z, t * y * y + c, t * y * z - s * x),
            (t * x * z - s * y, t * y * z + s * x, t * z * z + c))


def frame(x_hint: Vec, y_hint: Vec) -> Mat | None:
    """Orthonormal frame (as columns) with axis 0 along `x_hint` and axis 1 as near `y_hint` as possible; None if degenerate."""
    x = unit(x_hint)
    if x is None:
        return None
    z = unit(cross(x, y_hint))
    if z is None:
        return None
    y = cross(z, x)
    return ((x[0], y[0], z[0]), (x[1], y[1], z[1]), (x[2], y[2], z[2]))


def frame_turn(follower: Mat | None, trainer: Mat | None) -> Mat:
    """The rotation taking the follower's frame onto the trainer's (identity when either frame is degenerate)."""
    return matmul(trainer, transpose(follower)) if follower is not None and trainer is not None else IDENTITY


def torso_frame(s: Skeleton) -> Mat | None:
    return frame(sub(s["left_hip"], s["right_hip"]), sub(mid(s["left_shoulder"], s["right_shoulder"]), mid(s["left_hip"], s["right_hip"])))


def head_frame(s: Skeleton) -> Mat | None:
    return frame(sub(s["left_ear"], s["right_ear"]), sub(s["nose"], mid(s["left_ear"], s["right_ear"])))


Transform = Tuple[Vec, Mat, Vec]  # (follower pivot, rotation, new pivot): v -> new + R (v - pivot)


def move(t: Transform, v: Vec) -> Vec:
    return add(t[2], apply(t[1], sub(v, t[0])))


def retarget(f: Skeleton, t: Skeleton) -> Dict[str, Transform]:
    """`{segment: (pivot, rotation, new pivot)}` that moves the follower's body into the trainer's bone directions.

    Segments: torso, head, and for each side upper_arm, forearm, thigh, shin. Bone lengths and the pelvis position are
    the follower's own, so a different body shape with the same directions moves nothing.
    """
    pelvis = mid(f["left_hip"], f["right_hip"])
    r_torso = frame_turn(torso_frame(f), torso_frame(t))
    out: Dict[str, Transform] = {"torso": (pelvis, r_torso, pelvis)}
    neck_f = mid(f["left_shoulder"], f["right_shoulder"])
    neck_new = add(pelvis, apply(r_torso, sub(neck_f, pelvis)))
    out["head"] = (neck_f, frame_turn(head_frame(f), head_frame(t)), neck_new)
    for side in SIDES:
        for kind, names in (("arm", ("upper_arm", "forearm")), ("leg", ("thigh", "shin"))):
            joints = [f"{side}_{n}" for n in LIMBS[kind]]
            root_new = add(pelvis, apply(r_torso, sub(f[joints[0]], pelvis)))
            for i in range(2):
                df, dt = sub(f[joints[i + 1]], f[joints[i]]), sub(t[joints[i + 1]], t[joints[i]])
                rot = arc(df, dt)
                out[f"{side}_{names[i]}"] = (f[joints[i]], rot, root_new)
                root_new = add(root_new, apply(rot, df))
    return out
