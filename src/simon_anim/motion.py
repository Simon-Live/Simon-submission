"""Analytic expected movements used only to author fixtures.

The interpolator never imports this module. Ground-truth in-between frames are
sampled from these curves; the animation is rebuilt from keyframe rotations.
"""

from __future__ import annotations

import math

from .math3d import IDENT_QUAT, Quat, quat_from_axis_angle, quat_mul
from .skeleton import ROTATED_JOINTS


def _blank() -> dict[str, Quat]:
    return {joint: IDENT_QUAT for joint in ROTATED_JOINTS}


def _rx(angle_rad: float) -> Quat:
    return quat_from_axis_angle((1.0, 0.0, 0.0), angle_rad)


def _ry(angle_rad: float) -> Quat:
    return quat_from_axis_angle((0.0, 1.0, 0.0), angle_rad)


def _rz(angle_rad: float) -> Quat:
    return quat_from_axis_angle((0.0, 0.0, 1.0), angle_rad)


def _deg(degrees: float) -> float:
    return math.radians(degrees)


def squat_rotations(t: float, duration: float = 3.0) -> dict[str, Quat]:
    """One bodyweight squat. Raised cosine: stand, bottom, stand, zero end velocity."""
    s = 0.5 - 0.5 * math.cos(2.0 * math.pi * t / duration)
    rots = _blank()
    # Pelvis pitch carries the trunk forward. Hip offsets lie on X, so the
    # hips stay put while the spine leans. Hip flexion is in the pelvis frame.
    # Positive Rx pitches the trunk toward anterior (+z).
    rots["pelvis"] = _rx(_deg(18.0 * s))
    rots["left_hip"] = _rx(_deg(-78.0 * s))
    rots["right_hip"] = _rx(_deg(-78.0 * s))
    rots["left_knee"] = _rx(_deg(112.0 * s))
    rots["right_knee"] = _rx(_deg(112.0 * s))
    rots["left_ankle"] = _rx(_deg(20.0 * s))
    rots["right_ankle"] = _rx(_deg(20.0 * s))
    rots["neck"] = _rx(_deg(-14.0 * s))
    rots["left_shoulder"] = _rx(_deg(-36.0 * s))
    rots["right_shoulder"] = _rx(_deg(-36.0 * s))
    rots["left_elbow"] = _rx(_deg(-20.0 * s))
    rots["right_elbow"] = _rx(_deg(-20.0 * s))
    return rots


def dance_rotations(t: float, duration: float = 4.0) -> dict[str, Quat]:
    """Two cycles of a step-touch: opposite knee lifts, arm waves, torso twist.

    Every channel is a sinusoid, so the clip loops and stays easy to rebuild
    from sparse keyframes.
    """
    w = 2.0 * math.pi * 2.0 * t / duration
    lift_l = 0.5 * (1.0 + math.sin(w))
    lift_r = 0.5 * (1.0 - math.sin(w))
    wave_l = math.sin(w)
    wave_r = -math.sin(w)
    rots = _blank()
    rots["pelvis"] = _rz(_deg(7.0 * math.sin(w)))
    rots["chest"] = quat_mul(_ry(_deg(24.0 * math.sin(w))), _rz(_deg(10.0 * math.sin(w + 0.7))))
    rots["neck"] = quat_mul(_ry(_deg(-10.0 * math.sin(w))), _rx(_deg(8.0 * math.sin(2.0 * w))))
    rots["left_hip"] = _rx(_deg(-32.0 * lift_l))
    rots["right_hip"] = _rx(_deg(-32.0 * lift_r))
    rots["left_knee"] = _rx(_deg(62.0 * lift_l))
    rots["right_knee"] = _rx(_deg(62.0 * lift_r))
    rots["left_shoulder"] = quat_mul(_rz(_deg(28.0 * wave_l)), _rx(_deg(-18.0 + -36.0 * wave_l)))
    rots["right_shoulder"] = quat_mul(_rz(_deg(28.0 * wave_r)), _rx(_deg(-18.0 + -36.0 * wave_r)))
    rots["left_elbow"] = _rx(_deg(-16.0 - 14.0 * lift_l))
    rots["right_elbow"] = _rx(_deg(-16.0 - 14.0 * lift_r))
    return rots


MOTIONS = {
    "exercise": {
        "movement": "squat",
        "duration_s": 3.0,
        "fps": 30,
        "key_stride": 10,
        "rotations": squat_rotations,
        "coaching_note": (
            "Squat down and stand back up over three seconds. "
            "Keep the chest lifted and reach the arms forward for balance."
        ),
    },
    "dance": {
        "movement": "step_touch",
        "duration_s": 4.0,
        "fps": 30,
        "key_stride": 10,
        "rotations": dance_rotations,
        "coaching_note": (
            "Step touch for four seconds, two cycles. "
            "Lift one knee while the other arm reaches, and let the torso twist."
        ),
    },
}


def frame_count(duration_s: float, fps: int) -> int:
    """Inclusive endpoints so t=0 and t=duration are both frames."""
    return int(round(duration_s * fps)) + 1


def keyframe_indices(count: int, stride: int) -> list[int]:
    indices = list(range(0, count, stride))
    last = count - 1
    if indices[-1] != last:
        indices.append(last)
    return indices
