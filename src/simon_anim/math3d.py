"""Small vector and quaternion helpers. No third-party dependencies."""

from __future__ import annotations

import math
from typing import Iterable, Sequence

Vec3 = tuple[float, float, float]
Quat = tuple[float, float, float, float]  # x, y, z, w

IDENT_QUAT: Quat = (0.0, 0.0, 0.0, 1.0)


def v_add(a: Sequence[float], b: Sequence[float]) -> Vec3:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def v_sub(a: Sequence[float], b: Sequence[float]) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def v_scale(a: Sequence[float], s: float) -> Vec3:
    return (a[0] * s, a[1] * s, a[2] * s)


def v_dot(a: Sequence[float], b: Sequence[float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def v_cross(a: Sequence[float], b: Sequence[float]) -> Vec3:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def v_norm(a: Sequence[float]) -> float:
    return math.sqrt(v_dot(a, a))


def v_normalize(a: Sequence[float]) -> Vec3:
    n = v_norm(a)
    if n < 1e-12:
        raise ValueError("cannot normalize a near-zero vector")
    return (a[0] / n, a[1] / n, a[2] / n)


def v_lerp(a: Sequence[float], b: Sequence[float], u: float) -> Vec3:
    return (
        a[0] + (b[0] - a[0]) * u,
        a[1] + (b[1] - a[1]) * u,
        a[2] + (b[2] - a[2]) * u,
    )


def clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


def quat_normalize(q: Sequence[float]) -> Quat:
    n = math.sqrt(q[0] * q[0] + q[1] * q[1] + q[2] * q[2] + q[3] * q[3])
    if n < 1e-12:
        return IDENT_QUAT
    return (q[0] / n, q[1] / n, q[2] / n, q[3] / n)


def quat_mul(a: Sequence[float], b: Sequence[float]) -> Quat:
    """Hamilton product. `quat_rotate(quat_mul(a, b), v)` applies b, then a."""
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return quat_normalize(
        (
            aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw,
            aw * bw - ax * bx - ay * by - az * bz,
        )
    )


def quat_dot(a: Sequence[float], b: Sequence[float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2] + a[3] * b[3]


def quat_rotate(q: Sequence[float], v: Sequence[float]) -> Vec3:
    x, y, z, w = quat_normalize(q)
    vx, vy, vz = v
    tx = 2.0 * (y * vz - z * vy)
    ty = 2.0 * (z * vx - x * vz)
    tz = 2.0 * (x * vy - y * vx)
    return (
        vx + w * tx + (y * tz - z * ty),
        vy + w * ty + (z * tx - x * tz),
        vz + w * tz + (x * ty - y * tx),
    )


def quat_from_axis_angle(axis: Sequence[float], angle_rad: float) -> Quat:
    n = v_normalize(axis) if v_norm(axis) > 1e-12 else (1.0, 0.0, 0.0)
    half = angle_rad * 0.5
    s = math.sin(half)
    return (n[0] * s, n[1] * s, n[2] * s, math.cos(half))


def quat_from_euler_xyz(rx: float, ry: float, rz: float) -> Quat:
    """Intrinsic X then Y then Z, expressed as Rx * Ry * Rz (Rz applied first)."""
    qx = quat_from_axis_angle((1.0, 0.0, 0.0), rx)
    qy = quat_from_axis_angle((0.0, 1.0, 0.0), ry)
    qz = quat_from_axis_angle((0.0, 0.0, 1.0), rz)
    return quat_mul(quat_mul(qx, qy), qz)


def quat_align_hemisphere(q: Sequence[float], reference: Sequence[float]) -> Quat:
    qn = quat_normalize(q)
    if quat_dot(qn, reference) < 0.0:
        return (-qn[0], -qn[1], -qn[2], -qn[3])
    return qn


def quat_geodesic_deg(a: Sequence[float], b: Sequence[float]) -> float:
    d = abs(quat_dot(quat_normalize(a), quat_normalize(b)))
    d = clamp(d, 0.0, 1.0)
    return math.degrees(2.0 * math.acos(d))


def quat_to_rotvec(q: Sequence[float]) -> Vec3:
    x, y, z, w = quat_normalize(q)
    if w < 0.0:
        x, y, z, w = -x, -y, -z, -w
    w = clamp(w, -1.0, 1.0)
    angle = 2.0 * math.acos(w)
    s = math.sqrt(max(0.0, 1.0 - w * w))
    if s < 1e-8 or angle < 1e-8:
        return (0.0, 0.0, 0.0)
    scale = angle / s
    return (x * scale, y * scale, z * scale)


def rotvec_to_quat(rv: Sequence[float]) -> Quat:
    angle = v_norm(rv)
    if angle < 1e-12:
        return IDENT_QUAT
    return quat_from_axis_angle((rv[0] / angle, rv[1] / angle, rv[2] / angle), angle)


def direction_angle_deg(a: Sequence[float], b: Sequence[float]) -> float:
    """Angle in degrees between two direction vectors. Zero-length yields 0."""
    na = v_norm(a)
    nb = v_norm(b)
    if na < 1e-10 or nb < 1e-10:
        return 0.0
    cross = v_cross(a, b)
    sin_term = v_norm(cross) / (na * nb)
    cos_term = v_dot(a, b) / (na * nb)
    return math.degrees(math.atan2(sin_term, clamp(cos_term, -1.0, 1.0)))


def round_floats(value, places: int = 6):
    if isinstance(value, float):
        return round(value, places)
    if isinstance(value, (list, tuple)):
        return [round_floats(v, places) for v in value]
    if isinstance(value, dict):
        return {k: round_floats(v, places) for k, v in value.items()}
    return value


def as_vec3(seq: Iterable[float]) -> Vec3:
    x, y, z = seq
    return (float(x), float(y), float(z))


def as_quat(seq: Iterable[float]) -> Quat:
    x, y, z, w = seq
    return quat_normalize((float(x), float(y), float(z), float(w)))
