"""Shared vector maths on joint arrays of shape (..., 17, 3) in canonical joint order."""

import os

import numpy as np

from part3.joints import INDEX, NECK, ROOT

HIP_EPS_M = 1e-6
STANDING_KNEE_DEG = 160.0
MIN_STANDING_FRAMES = 5
UP_FALLBACK_ENV = "PART3_UP_FALLBACK"   # "all_frames" restores the pre-stitching fallback (ASM-019)


def normalize(v, axis=-1):
    """Unit vectors along `axis`; zero vectors stay zero."""
    v = np.asarray(v, dtype=float)
    n = np.linalg.norm(v, axis=axis, keepdims=True)
    return np.divide(v, n, out=np.zeros_like(v), where=n > 0)


def point(J, name):
    """Position of a joint or of the virtual `root` (hip midpoint) / `neck` (shoulder midpoint)."""
    if name == ROOT:
        return 0.5 * (J[..., INDEX["left_hip"], :] + J[..., INDEX["right_hip"], :])
    if name == NECK:
        return 0.5 * (J[..., INDEX["left_shoulder"], :] + J[..., INDEX["right_shoulder"], :])
    return J[..., INDEX[name], :]


def interior_angle(a, b, c):
    """Angle at b of (a, b, c) in degrees, 0 to 180; NaN where a side has zero length."""
    u = np.asarray(a, dtype=float) - b
    v = np.asarray(c, dtype=float) - b
    nu = np.linalg.norm(u, axis=-1)
    nv = np.linalg.norm(v, axis=-1)
    with np.errstate(invalid="ignore", divide="ignore"):
        cos = np.sum(u * v, axis=-1) / (nu * nv)
    return np.degrees(np.arccos(np.clip(cos, -1.0, 1.0)))


def knee_angles(J):
    """(..., 2) left and right knee interior angles in degrees."""
    left = interior_angle(point(J, "left_hip"), point(J, "left_knee"), point(J, "left_ankle"))
    right = interior_angle(point(J, "right_hip"), point(J, "right_knee"), point(J, "right_ankle"))
    return np.stack([left, right], axis=-1)


def body_up(J):
    """Clip body up (spec step 5 item 1) from frames J (n, 17, 3).

    Returns (unit up vector, "standing_frames", "input_up" or "all_frames"). Standing = both knees
    above 160 degrees. With fewer than 5 standing frames the input's +y (Part 2's world up) is used
    (ASM-019); PART3_UP_FALLBACK=all_frames uses the mean over every frame instead.
    """
    J = np.asarray(J, dtype=float)
    ankle_mid = 0.5 * (point(J, "left_ankle") + point(J, "right_ankle"))
    vec = point(J, NECK) - ankle_mid
    knees = knee_angles(J)
    standing = np.all(knees > STANDING_KNEE_DEG, axis=-1)
    if int(standing.sum()) >= MIN_STANDING_FRAMES:
        return normalize(vec[standing].mean(axis=0)), "standing_frames"
    if os.environ.get(UP_FALLBACK_ENV, "input_up") == "all_frames":
        return normalize(vec.mean(axis=0)), "all_frames"
    return np.array([0.0, 1.0, 0.0]), "input_up"


def pelvis_frame(J, up):
    """Re-express frames J (n, 17, 3) in per-frame pelvis axes with a fixed `up`.

    y = up; x = left hip minus right hip with its up component removed; z = x cross y; origin at
    the hip midpoint. Returns (frames in the new axes, valid mask); frames whose horizontal hip
    line is shorter than HIP_EPS_M (1e-6 m) are invalid and returned as zeros.
    """
    J = np.asarray(J, dtype=float)
    R, valid = pelvis_axes(J, up)
    rel = J - point(J, ROOT)[..., None, :]
    out = np.einsum("nij,nkj->nki", R, rel)
    out[~valid] = 0.0
    return out, valid


def pelvis_axes(J, up):
    """Per-frame rotation matrices (n, 3, 3) whose rows are the pelvis x, y, z axes, and a valid mask.

    Input coordinates v map to pelvis coordinates as R[n] @ v (see `pelvis_frame`).
    """
    J = np.asarray(J, dtype=float)
    y = normalize(np.asarray(up, dtype=float))
    hip = point(J, "left_hip") - point(J, "right_hip")
    x = hip - np.sum(hip * y, axis=-1, keepdims=True) * y
    valid = np.linalg.norm(x, axis=-1) >= HIP_EPS_M
    x = normalize(x)
    yb = np.broadcast_to(y, x.shape)
    z = np.cross(x, yb)
    return np.stack([x, yb, z], axis=-2), valid


def rotation(axis, angle_deg):
    """3x3 rotation matrix about `axis` by `angle_deg` (right-handed)."""
    k = normalize(np.asarray(axis, dtype=float))
    a = np.radians(angle_deg)
    K = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    return np.eye(3) + np.sin(a) * K + (1 - np.cos(a)) * (K @ K)


def angle_between(u, v):
    """Angle in degrees between vectors u and v (broadcasting)."""
    return interior_angle(u, np.zeros(3), v)
