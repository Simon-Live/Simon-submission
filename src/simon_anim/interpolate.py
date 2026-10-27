"""Fixed-length animation by cubic interpolation of joint rotations.

Linear blending of joint positions changes bone lengths. This path converts
each keyframe's local quaternion to a rotation vector, fits a cubic Hermite
segment between keyframes (Catmull-Rom tangents), and runs forward kinematics.
Keyframe frames are copied from the input rotations so the clip passes through
every authored pose.
"""

from __future__ import annotations

from typing import Sequence

from .math3d import (
    IDENT_QUAT,
    Quat,
    as_quat,
    quat_align_hemisphere,
    quat_to_rotvec,
    rotvec_to_quat,
)
from .skeleton import CANONICAL_JOINTS, COORDINATE_FRAME, ROTATED_JOINTS, forward_kinematics, length_bones_with_rest


def _hermite(p0: float, p1: float, m0: float, m1: float, t0: float, t1: float, t: float) -> float:
    h = t1 - t0
    if h <= 1e-12:
        return p0
    u = (t - t0) / h
    if u <= 0.0:
        return p0
    if u >= 1.0:
        return p1
    u2 = u * u
    u3 = u2 * u
    h00 = 2.0 * u3 - 3.0 * u2 + 1.0
    h10 = u3 - 2.0 * u2 + u
    h01 = -2.0 * u3 + 3.0 * u2
    h11 = u3 - u2
    return h00 * p0 + h10 * h * m0 + h01 * p1 + h11 * h * m1


def _tangents(times: Sequence[float], values: Sequence[float]) -> list[float]:
    n = len(times)
    if n == 1:
        return [0.0]
    slopes = []
    for i in range(n):
        if i == 0:
            dt = times[1] - times[0]
            slopes.append(0.0 if dt == 0 else (values[1] - values[0]) / dt)
        elif i == n - 1:
            dt = times[-1] - times[-2]
            slopes.append(0.0 if dt == 0 else (values[-1] - values[-2]) / dt)
        else:
            dt = times[i + 1] - times[i - 1]
            slopes.append(0.0 if dt == 0 else (values[i + 1] - values[i - 1]) / dt)
    return slopes


def _keyframe_quats(skeleton: dict) -> tuple[list[float], dict[str, list[Quat]]]:
    frames = sorted(skeleton["keyframes"], key=lambda f: f["index"])
    if not frames:
        raise ValueError("skeleton has no keyframes")
    times = [float(frame["t"]) for frame in frames]
    series: dict[str, list[Quat]] = {joint: [] for joint in ROTATED_JOINTS}
    previous = {joint: IDENT_QUAT for joint in ROTATED_JOINTS}
    for frame in frames:
        local = frame.get("local_rotations") or {}
        for joint in ROTATED_JOINTS:
            raw = local.get(joint, IDENT_QUAT)
            aligned = quat_align_hemisphere(as_quat(raw), previous[joint])
            series[joint].append(aligned)
            previous[joint] = aligned
    return times, series


def rotations_at_time(times: Sequence[float], series: dict[str, list[Quat]], t: float) -> dict[str, Quat]:
    """Local quaternions at time t. Exact at keyframe samples."""
    if t <= times[0]:
        return {joint: series[joint][0] for joint in series}
    if t >= times[-1]:
        return {joint: series[joint][-1] for joint in series}
    # Exact keyframe hit (within a microsecond).
    for i, tk in enumerate(times):
        if abs(t - tk) <= 1e-8:
            return {joint: series[joint][i] for joint in series}
    hi = 1
    while hi < len(times) and times[hi] < t:
        hi += 1
    lo = hi - 1
    out: dict[str, Quat] = {}
    for joint, quats in series.items():
        rotvecs = [quat_to_rotvec(q) for q in quats]
        components = []
        for axis in range(3):
            values = [rv[axis] for rv in rotvecs]
            slopes = _tangents(times, values)
            components.append(
                _hermite(values[lo], values[hi], slopes[lo], slopes[hi], times[lo], times[hi], t)
            )
        out[joint] = rotvec_to_quat(components)
    return out


def build_animation(skeleton: dict, keyframes_doc: dict) -> dict:
    """30 fps animation.json document from a keyframe skeleton."""
    fps = int(keyframes_doc["fps"])
    if fps != 30:
        raise ValueError(f"expected 30 fps, got {fps}")
    frame_count = int(keyframes_doc["frame_count"])
    duration_s = float(keyframes_doc["duration_s"])
    key_idx = [int(k["index"]) for k in keyframes_doc["keyframes"]]
    sk_idx = [int(f["index"]) for f in skeleton["keyframes"]]
    if key_idx != sk_idx:
        raise ValueError("keyframes.json indices do not match skeleton.json samples")
    if "joints" in skeleton and list(skeleton["joints"]) != list(CANONICAL_JOINTS):
        raise ValueError("skeleton joints must be the canonical 17, in canonical order")
    times, series = _keyframe_quats(skeleton)
    key_set = set(key_idx)
    frames = []
    for index in range(frame_count):
        t = index / fps
        local = rotations_at_time(times, series, t)
        positions = forward_kinematics(local)
        frames.append(
            {
                "index": index,
                "t": t,
                "interpolated": index not in key_set,
                "joints": {name: [positions[name][0], positions[name][1], positions[name][2]] for name in CANONICAL_JOINTS},
            }
        )
    return {
        "format": "simon.animation.v1",
        "fps": fps,
        "duration_s": duration_s,
        "frame_count": frame_count,
        "movement": keyframes_doc.get("movement"),
        "set": keyframes_doc.get("set"),
        "coordinate_frame": COORDINATE_FRAME,
        "joints": list(CANONICAL_JOINTS),
        "bones": length_bones_with_rest(),
        "frames": frames,
    }
