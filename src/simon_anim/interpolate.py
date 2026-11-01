"""Fixed-length animation by cubic interpolation of joint rotations.

Linear blending of joint positions changes bone lengths. This path converts
each keyframe's local quaternion to a rotation vector once, fits a cubic Hermite
segment between keyframes (Catmull-Rom tangents), and runs forward kinematics
on the body in skeleton.json. Keyframe frames are copied from the input
rotations so the clip passes through every authored pose.
"""

from __future__ import annotations

import math
from typing import Sequence

from . import contract
from .math3d import (
    IDENT_QUAT,
    Quat,
    Vec3,
    as_quat,
    quat_align_hemisphere,
    quat_mul,
    quat_normalize,
    rotvec_to_quat,
    v_dot,
    v_norm,
    v_normalize,
    v_sub,
)
from .skeleton import (
    CANONICAL_JOINTS,
    COORDINATE_FRAME,
    ROTATED_JOINTS,
    forward_kinematics,
    length_bones_with_rest,
    rest_offsets_from_skeleton,
)

# One microsecond. Shipped JSON times are rounded to 6 decimals, which can
# differ from index/30 by a few ten-millionths of a second.
TIME_TOLERANCE_S = 1e-6
# Keys are first put on the shortest arc (same quaternion hemisphere, twist
# about a leaf bone removed), so a step this large in rotation-vector space
# is a real half turn or more inside one gap: two poses cannot say which way.
MAX_ROTVEC_STEP_DEG = 180.0


def _rotvec_unwrapped(q: Sequence[float]) -> Vec3:
    """Rotation vector of q as given, angle 0 to 360 degrees (A-P4-07).

    A negative w is kept, so a key already flipped into the previous key's
    hemisphere stays next to that key's vector when the joint turns through
    180 degrees, for example a folded elbow.
    """
    x, y, z, w = quat_normalize(q)
    s = math.sqrt(x * x + y * y + z * z)
    if s < 1e-12:
        return (0.0, 0.0, 0.0)
    scale = 2.0 * math.atan2(s, w) / s
    return (x * scale, y * scale, z * scale)


def _drop_twist(q: Quat, reference: Quat, axis: Sequence[float]) -> Quat:
    """q turned about `axis` (in q's own frame) to sit as close to `reference` as it can (A-P4-08).

    The turn moves nothing when the bone along `axis` ends in a leaf joint, so
    only the swing that moves that leaf is left between the keys.
    """
    u = v_normalize(axis)
    d = quat_mul((-reference[0], -reference[1], -reference[2], reference[3]), q)
    half = math.atan2(-v_dot(d[:3], u), d[3])
    s = math.sin(half)
    return quat_mul(q, (u[0] * s, u[1] * s, u[2] * s, math.cos(half)))


def _free_rotations(rest_offsets: dict) -> tuple[dict[str, Vec3], set[str]]:
    """Joints whose rotation is partly or wholly invisible in the 17 output joints.

    Returns ({joint: offset of its only child, when that child is a leaf},
    {joints with no child}). Elbows, knees and eyes are in the first; wrists,
    ankles and ears in the second.
    """
    children: dict[str, list[str]] = {joint: [] for joint in ROTATED_JOINTS}
    for child, (parent, _offset) in rest_offsets.items():
        children.setdefault(parent, []).append(child)
    twist_axes = {}
    leaves = set()
    for joint in ROTATED_JOINTS:
        kids = children.get(joint, [])
        if not kids:
            leaves.add(joint)
        elif len(kids) == 1 and not children.get(kids[0]) and v_norm(rest_offsets[kids[0]][1]) > 1e-9:
            twist_axes[joint] = rest_offsets[kids[0]][1]
    return twist_axes, leaves


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


def _require_quat(frame: dict, joint: str) -> Sequence[float]:
    index = frame.get("index")
    local = frame.get("local_rotations")
    if not isinstance(local, dict) or joint not in local:
        raise ValueError(f"frame {index} is missing a rotation for {joint}")
    raw = local[joint]
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        raise ValueError(f"frame {index} rotation for {joint} must be a quaternion (x, y, z, w)")
    norm = math.sqrt(sum(float(value) * float(value) for value in raw))
    if norm < 1e-8:
        raise ValueError(f"frame {index} has a zero rotation for {joint}")
    return raw


def _keyframe_quats(
    skeleton: dict, rest_offsets: dict | None = None
) -> tuple[list[int], list[float], dict[str, list[Quat]]]:
    """Key rotations per joint, each on the shortest arc from the key before.

    With `rest_offsets`, a turn that moves no output joint is taken out first:
    a joint with no child holds the identity, and an elbow, knee or eye loses
    its twist about the bone to its leaf child against the previous key. Key
    positions do not change.
    """
    frames = sorted(skeleton["keyframes"], key=lambda f: int(f["index"]))
    if not frames:
        raise ValueError("skeleton has no keyframes")
    indices = [int(frame["index"]) for frame in frames]
    times = [float(frame["t"]) for frame in frames]
    twist_axes, leaves = _free_rotations(rest_offsets) if rest_offsets else ({}, set())
    series: dict[str, list[Quat]] = {joint: [] for joint in ROTATED_JOINTS}
    previous = {joint: IDENT_QUAT for joint in ROTATED_JOINTS}
    for frame in frames:
        for joint in ROTATED_JOINTS:
            quat = as_quat(_require_quat(frame, joint))
            if joint in leaves:
                quat = IDENT_QUAT
            elif joint in twist_axes:
                quat = _drop_twist(quat, previous[joint], twist_axes[joint])
            aligned = quat_align_hemisphere(quat, previous[joint])
            series[joint].append(aligned)
            previous[joint] = aligned
    return indices, times, series


class _JointCurve:
    __slots__ = ("quats", "rotvecs", "slopes")

    def __init__(self, quats: list[Quat], rotvecs: list[Vec3], slopes: list[tuple[float, float, float]]) -> None:
        self.quats = quats
        self.rotvecs = rotvecs
        self.slopes = slopes


def _prepare_curves(
    indices: Sequence[int], times: Sequence[float], series: dict[str, list[Quat]]
) -> dict[str, _JointCurve]:
    """Rotation-vector curves and slopes, computed once for the whole clip."""
    curves: dict[str, _JointCurve] = {}
    for joint, quats in series.items():
        rotvecs = [_rotvec_unwrapped(quat) for quat in quats]
        for i in range(len(rotvecs) - 1):
            step = math.degrees(v_norm(v_sub(rotvecs[i + 1], rotvecs[i])))
            if step > MAX_ROTVEC_STEP_DEG:
                raise ValueError(
                    f"{joint} takes the long way between frames {indices[i]} and {indices[i + 1]} "
                    f"({step:.1f}°)"
                )
        slope_axes = []
        for axis in range(3):
            values = [rotvec[axis] for rotvec in rotvecs]
            slope_axes.append(_tangents(times, values))
        slopes = list(zip(*slope_axes))
        curves[joint] = _JointCurve(quats, rotvecs, slopes)
    return curves


def _segment(times: Sequence[float], t: float) -> int | None:
    """Index of the key at t, or None when t sits strictly between keys.

    The returned lo index is the left key when the result is None; callers
    that need the span use the search position instead.
    """
    hi = len(times) - 1
    if t <= times[0] or abs(t - times[0]) <= TIME_TOLERANCE_S:
        return 0
    if t >= times[-1] or abs(t - times[-1]) <= TIME_TOLERANCE_S:
        return hi
    left = 0
    right = hi
    while left + 1 < right:
        mid = (left + right) // 2
        if times[mid] <= t:
            left = mid
        else:
            right = mid
    if abs(t - times[left]) <= TIME_TOLERANCE_S:
        return left
    if abs(t - times[right]) <= TIME_TOLERANCE_S:
        return right
    return None


def _left_key(times: Sequence[float], t: float) -> int:
    left = 0
    right = len(times) - 1
    while left + 1 < right:
        mid = (left + right) // 2
        if times[mid] <= t:
            left = mid
        else:
            right = mid
    return left


def _eval_curves(times: Sequence[float], curves: dict[str, _JointCurve], t: float) -> dict[str, Quat]:
    """Local quaternions at time t. Exact at keyframe samples."""
    if t <= times[0] or abs(t - times[0]) <= TIME_TOLERANCE_S:
        return {joint: curve.quats[0] for joint, curve in curves.items()}
    if t >= times[-1] or abs(t - times[-1]) <= TIME_TOLERANCE_S:
        return {joint: curve.quats[-1] for joint, curve in curves.items()}
    exact = _segment(times, t)
    if exact is not None:
        return {joint: curve.quats[exact] for joint, curve in curves.items()}
    lo = _left_key(times, t)
    hi = lo + 1
    out: dict[str, Quat] = {}
    for joint, curve in curves.items():
        components = [
            _hermite(
                curve.rotvecs[lo][axis],
                curve.rotvecs[hi][axis],
                curve.slopes[lo][axis],
                curve.slopes[hi][axis],
                times[lo],
                times[hi],
                t,
            )
            for axis in range(3)
        ]
        out[joint] = rotvec_to_quat(components)
    return out


def rotations_at_time(times: Sequence[float], series: dict[str, list[Quat]], t: float) -> dict[str, Quat]:
    """Local quaternions at time t. Exact at keyframe samples."""
    indices = list(range(len(times)))
    return _eval_curves(times, _prepare_curves(indices, times, series), t)


def _require_timeline(keyframes_doc: dict) -> tuple[int, float, int, list[int]]:
    if int(keyframes_doc["fps"]) != 30:
        raise ValueError(f"expected 30 fps, got {keyframes_doc['fps']}")
    fps = 30
    frame_count = int(keyframes_doc["frame_count"])
    duration_s = float(keyframes_doc["duration_s"])
    expected_count = int(round(duration_s * fps)) + 1
    if frame_count != expected_count:
        raise ValueError(
            f"frame_count is {frame_count}, expected {expected_count} for {duration_s}s at {fps} fps"
        )
    if frame_count < 1:
        raise ValueError("frame_count must be at least 1")
    key_idx = [int(frame["index"]) for frame in keyframes_doc["keyframes"]]
    if not key_idx:
        raise ValueError("keyframes.json has no keyframes")
    previous = None
    for index in key_idx:
        if index < 0 or index >= frame_count:
            raise ValueError(f"key frame {index} is outside 0..{frame_count - 1}")
        if previous is not None and index <= previous:
            raise ValueError(f"key frame {index} is not after frame {previous}")
        previous = index
    return fps, duration_s, frame_count, key_idx


def _require_key_time(index: int, t: float, fps: int, source: str) -> None:
    expected = index / fps
    if abs(float(t) - expected) > TIME_TOLERANCE_S:
        raise ValueError(f"{source} frame {index} has t={t}, expected {expected:.6f}")


# Part 3's mark for a joint outside the image; Part 5 reads the same value as "unseen".
UNSEEN_CONF = 0.3


def _key_confidences(skeleton: dict) -> list[dict[str, float]] | None:
    """Per-key {joint: conf} in key-index order, or None when every joint at every key is fully seen.

    A key's value comes from `keyframes[].conf` (joint -> number), else the `conf` of a
    `{x, y, z, conf}` joint, else 1.0. Full confidence everywhere (or none given) is the
    same as no data: the output then gets no `conf` and no `unseen_joints`, and the file is
    what it was before those fields existed.
    """
    found = False
    rows: list[dict[str, float]] = []
    for frame in sorted(skeleton["keyframes"], key=lambda f: int(f["index"])):
        explicit = frame.get("conf")
        explicit = explicit if isinstance(explicit, dict) else {}
        row: dict[str, float] = {}
        for name in CANONICAL_JOINTS:
            raw = explicit.get(name)
            if raw is None and isinstance(frame["joints"].get(name), dict):
                raw = frame["joints"][name].get("conf")
            if raw is None:
                row[name] = 1.0
                continue
            if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not 0.0 <= raw <= 1.0:
                raise ValueError(f"skeleton.json frame {frame['index']} conf for {name} must be a number in 0..1")
            row[name] = float(raw)
            found = found or row[name] != 1.0
        rows.append(row)
    return rows if found else None


def _conf_at(times: Sequence[float], keys: list[dict[str, float]], t: float) -> dict[str, float]:
    """Confidences at time t: a key's own, else the minimum of the two keys around t.

    Minimum, so a joint unseen at either end of a gap stays unseen across it. Before the
    first key and after the last, the nearest key's values.
    """
    exact = _segment(times, t)
    if exact is not None:
        return dict(keys[exact])
    lo = _left_key(times, t)
    return {name: min(keys[lo][name], keys[lo + 1][name]) for name in CANONICAL_JOINTS}


def _unseen_joints(keys: list[dict[str, float]]) -> list[str]:
    """Joints at or below UNSEEN_CONF at every key, in canonical order."""
    return [name for name in CANONICAL_JOINTS if all(row[name] <= UNSEEN_CONF for row in keys)]


def build_animation(skeleton: dict, keyframes_doc: dict, set_name: str | None = None) -> dict:
    """30 fps animation.json document from a keyframe skeleton.

    Both inputs are checked against contracts/*.schema.json first, so a file
    the schema rejects is never animated. `set_name` names the clip when
    neither input does.
    """
    contract.require(keyframes_doc, "keyframes", "keyframes.json")
    contract.require(skeleton, "skeleton", "skeleton.json")
    fps, duration_s, frame_count, key_idx = _require_timeline(keyframes_doc)
    sk_idx = [int(frame["index"]) for frame in skeleton["keyframes"]]
    if key_idx != sk_idx:
        raise ValueError("keyframes.json indices do not match skeleton.json samples")
    if "joints" in skeleton and list(skeleton["joints"]) != list(CANONICAL_JOINTS):
        raise ValueError("skeleton joints must be the canonical 17, in canonical order")
    for frame in keyframes_doc["keyframes"]:
        _require_key_time(int(frame["index"]), float(frame["t"]), fps, "keyframes.json")
    for frame in skeleton["keyframes"]:
        _require_key_time(int(frame["index"]), float(frame["t"]), fps, "skeleton.json")
    rest_offsets = rest_offsets_from_skeleton(skeleton)
    indices, times, series = _keyframe_quats(skeleton, rest_offsets)
    curves = _prepare_curves(indices, times, series)
    key_set = set(key_idx)
    key_conf = _key_confidences(skeleton)
    frames = []
    for index in range(frame_count):
        t = index / fps
        local = _eval_curves(times, curves, t)
        positions = forward_kinematics(local, rest_offsets)
        frame = {
            "index": index,
            "t": t,
            "interpolated": index not in key_set,
            "joints": {
                name: [positions[name][0], positions[name][1], positions[name][2]]
                for name in CANONICAL_JOINTS
            },
        }
        if key_conf is not None:
            frame["conf"] = _conf_at(times, key_conf, t)
        frames.append(frame)
    animation = {
        "format": contract.ANIMATION_FORMAT,
        "producer": contract.ANIMATION_PRODUCER,
        "fps": fps,
        "duration_s": duration_s,
        "frame_count": frame_count,
        "movement": keyframes_doc.get("movement") or skeleton.get("movement"),
        "set": keyframes_doc.get("set") or skeleton.get("set") or set_name,
        "coordinate_frame": COORDINATE_FRAME,
        "joints": list(CANONICAL_JOINTS),
        "bones": length_bones_with_rest(rest_offsets),
    }
    if key_conf is not None:
        animation["unseen_joints"] = _unseen_joints(key_conf)
    animation["frames"] = frames
    return animation
