"""Geometry for "You, doing it right" (docs/specs/muse-fix.md, TICKET-280). Pure functions, no I/O, no dependency.

A joint's angle is the angle at the joint between the segment to its parent and the segment to its child (the knee:
hip, knee, ankle). The target of a fault is the trainer's angle at the matched moment. `bend_limb` turns the follower's
mesh so that angle reaches the target; `project` puts a canonical point on the original video frame.
"""

from __future__ import annotations

import math
from typing import Any, Sequence

Vec = tuple[float, float, float]

_SIDES = ("left", "right")
# joint -> (parent, child); the three points whose angle is the joint's angle
_CHAIN = {"elbow": ("shoulder", "elbow", "wrist"), "knee": ("hip", "knee", "ankle"),
          "shoulder": ("hip", "shoulder", "elbow"), "hip": ("shoulder", "hip", "knee")}
# joint -> the mesh labels that move with it (its own label moves by weight)
_MOVES = {"elbow": ("wrist",), "knee": ("ankle",), "shoulder": ("elbow", "wrist"), "hip": ("knee", "ankle")}
SUPPORTED = tuple(f"{s}_{j}" for s in _SIDES for j in _CHAIN)


def chain(joint: str) -> tuple[str, str, str] | None:
    """The (parent, joint, child) names for a supported joint such as `right_knee`, else None."""
    side, _, part = str(joint).partition("_")
    return tuple(f"{side}_{p}" for p in _CHAIN[part]) if side in _SIDES and part in _CHAIN else None  # type: ignore[return-value]


def moving_labels(joint: str) -> tuple[str, ...]:
    side, _, part = str(joint).partition("_")
    return tuple(f"{side}_{p}" for p in _MOVES.get(part, ())) if side in _SIDES else ()


def _sub(a: Sequence[float], b: Sequence[float]) -> Vec:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _dot(a: Sequence[float], b: Sequence[float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: Sequence[float], b: Sequence[float]) -> Vec:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _norm(a: Sequence[float]) -> float:
    return math.sqrt(_dot(a, a))


def angle_deg(parent: Sequence[float], joint: Sequence[float], child: Sequence[float]) -> float | None:
    """The angle at `joint`, 0 to 180 degrees; None when a segment has no length."""
    u, v = _sub(parent, joint), _sub(child, joint)
    lu, lv = _norm(u), _norm(v)
    if lu < 1e-9 or lv < 1e-9:
        return None
    return math.degrees(math.acos(max(-1.0, min(1.0, _dot(u, v) / (lu * lv)))))


def joint_angle(points: dict[str, Any], joint: str) -> float | None:
    """The angle of `joint` from a dict of name -> [x, y, z] or {x, y, z}; None when a point is missing."""
    names = chain(joint)
    if names is None:
        return None
    xyz = [_xyz(points.get(n)) for n in names]
    return None if any(p is None for p in xyz) else angle_deg(*xyz)  # type: ignore[arg-type]


def _xyz(p: Any) -> Vec | None:
    if isinstance(p, dict):
        p = [p.get("x"), p.get("y"), p.get("z")]
    if isinstance(p, (list, tuple)) and len(p) >= 3 and all(isinstance(c, (int, float)) and not isinstance(c, bool) and math.isfinite(c) for c in p[:3]):
        return (float(p[0]), float(p[1]), float(p[2]))
    return None


def _rows(replay: dict[str, Any], who: str, frame: int) -> dict[str, Vec] | None:
    track, names = replay.get(who), replay.get("joints")
    if not isinstance(track, list) or not isinstance(names, list) or not 0 <= frame < len(track):
        return None
    row = track[frame]
    if not isinstance(row, list) or len(row) != len(names):
        return None
    pts = {n: _xyz(p) for n, p in zip(names, row)}
    return {n: p for n, p in pts.items() if p is not None}


# Part 5 measure -> how its fault grows with the drawn joint's angle: +1 the angle grows with the fault, -1 it shrinks.
# Flexion measures grow as the joint closes; the shoulder's "out" grows as it opens. A measure not listed has no known direction.
FAULT_GROWS_WITH_ANGLE = {"elbow_flexion": -1, "knee_flexion": -1, "thigh_forward": -1, "upper_arm_out": 1}


def wanted_move(measure: Any, direction: Any) -> int | None:
    """Which way the cue asks the joint's angle to go: +1 opens it, -1 closes it. `direction` is Part 5's: "more" is a follower
    with more of the fault than the example, so the cue takes some away. None when the measure's relation to the angle is unknown."""
    grows = FAULT_GROWS_WITH_ANGLE.get(measure)
    if grows is None or direction not in ("more", "less"):
        return None
    return -grows if direction == "more" else grows


def choose_moment(replay: dict[str, Any], joint: str, follower_frames: Sequence[int], want: int | None = None) -> dict[str, Any] | None:
    """The follower frame inside `follower_frames` where the joint is furthest from the trainer's matched frame, on the
    side the cue asks for: with `want` (+1 opens the joint, -1 closes it) a frame whose target lies the other way is no moment.

    `replay` is `simon.replay.v1`; `exp_to_fol[e]` is the follower frame matched to expected frame `e`. Returns
    `{follower_frame, expected_frame, follower_deg, target_deg, t_s}` or None when no frame has both angles."""
    if chain(joint) is None or len(follower_frames) != 2:
        return None
    lo, hi = int(follower_frames[0]), int(follower_frames[1])
    match = replay.get("exp_to_fol")
    times = replay.get("follower_t")
    if not isinstance(match, list):
        return None
    best: dict[str, Any] | None = None
    first: dict[int, int] = {}
    for e, f in enumerate(match):
        if isinstance(f, int) and not isinstance(f, bool):
            first.setdefault(f, e)
    for f in range(min(lo, hi), max(lo, hi) + 1):
        e = first.get(f)
        if e is None:
            continue
        mine, theirs = _rows(replay, "follower", f), _rows(replay, "expected", e)
        if mine is None or theirs is None:
            continue
        a, b = joint_angle(mine, joint), joint_angle(theirs, joint)
        if a is None or b is None:
            continue
        if want in (1, -1) and (b - a) * want <= 0:
            continue  # the trainer's angle is on the wrong side of the cue: drawing it would ask for the opposite of what the page says
        if best is None or abs(a - b) > abs(best["follower_deg"] - best["target_deg"]):
            t = times[f] if isinstance(times, list) and f < len(times) and isinstance(times[f], (int, float)) else None
            best = {"follower_frame": f, "expected_frame": e, "follower_deg": a, "target_deg": b, "t_s": t}
    return best


def _rodrigues(v: Vec, axis: Vec, phi: float) -> Vec:
    c, s = math.cos(phi), math.sin(phi)
    k = _cross(axis, v)
    d = _dot(axis, v) * (1 - c)
    return (v[0] * c + k[0] * s + axis[0] * d, v[1] * c + k[1] * s + axis[1] * d, v[2] * c + k[2] * s + axis[2] * d)


def _smooth(x: float) -> float:
    k = max(0.0, min(1.0, x))
    return k * k * (3 - 2 * k)


def bend_limb(vertices: Sequence[Vec], labels: Sequence[str], joints: dict[str, Any], joint: str,
              target_deg: float) -> list[Vec] | None:
    """The mesh with the limb beyond `joint` turned about the joint so its angle becomes `target_deg`.

    Vertices labelled with the limb's lower joints turn whole; vertices labelled with the joint itself turn by a
    smooth weight over how far past the joint they lie along the parent segment; the rest stay. A rigid turn of the
    limb about one joint is an approximation of the person, so the render is a control image, never a measurement.
    None when the joint's points are missing or a segment has no length."""
    names = chain(joint)
    pts = [_xyz(joints.get(n)) for n in names] if names else []
    if names is None or any(p is None for p in pts):
        return None
    parent, centre, child = pts  # type: ignore[misc]
    now = angle_deg(parent, centre, child)
    if now is None:
        return None
    u, v = _sub(parent, centre), _sub(child, centre)
    axis = _cross(u, v)
    if _norm(axis) < 1e-9:
        axis = _cross(u, (1.0, 0.0, 0.0) if abs(u[0]) < 0.9 * _norm(u) else (0.0, 1.0, 0.0))
    la = _norm(axis)
    axis = (axis[0] / la, axis[1] / la, axis[2] / la)
    phi = math.radians(float(target_deg) - now)
    lu = _norm(u)
    unit_u = (u[0] / lu, u[1] / lu, u[2] / lu)
    moves, own = set(moving_labels(joint)), names[1]
    out: list[Vec] = []
    for p, label in zip(vertices, labels):
        w = 1.0 if label in moves else 0.0
        if label == own:
            w = _smooth(0.5 - _dot(_sub(p, centre), unit_u) / 0.12)  # about 6 cm either side of the joint centre
        if w <= 0.0:
            out.append(p)
            continue
        r = _rodrigues(_sub(p, centre), axis, phi * w)
        out.append((centre[0] + r[0], centre[1] + r[1], centre[2] + r[2]))
    return out


def project(point: Vec, rot: Sequence[Sequence[float]], trans: Sequence[float], k: Sequence[Sequence[float]]) -> tuple[float, float, float] | None:
    """A canonical point to (x px, y px, depth) with the frame's OpenCV camera; None behind the camera."""
    x = [sum(rot[i][j] * point[j] for j in range(3)) + trans[i] for i in range(3)]
    if x[2] <= 1e-6:
        return None
    return (k[0][0] * x[0] / x[2] + k[0][2], k[1][1] * x[1] / x[2] + k[1][2], x[2])


def direction_words(joint_xy: Sequence[float], child_xy: Sequence[float]) -> str | None:
    """Where the segment from `joint_xy` to `child_xy` (pixels, y down) points, in plain words about the picture: "pointing
    down and to the left of the picture, about 50 degrees below level". None when the two points coincide."""
    dx, dy = float(child_xy[0]) - float(joint_xy[0]), float(child_xy[1]) - float(joint_xy[1])
    if math.hypot(dx, dy) < 1e-6:
        return None
    tilt = round(math.degrees(math.atan2(abs(dy), abs(dx))))
    side, vert = ("right" if dx > 0 else "left"), ("down" if dy > 0 else "up")
    if tilt >= 80:
        return f"pointing straight {vert}"
    if tilt <= 10:
        return f"held level, pointing to the {side} of the picture"
    return f"pointing {vert} and to the {side} of the picture, about {tilt} degrees {'below' if dy > 0 else 'above'} level"
