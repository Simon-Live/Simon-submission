"""Six pure pose functions, one per catalog movement, on one fixed synthetic body.

Every function maps a time in seconds and a `MotionParams` to the 17 canonical joints in the
shared frame (origin at the hip midpoint, x subject's left, y up, z anterior, metres). Joints come
from forward kinematics with the segment lengths and face offsets of `fixtures/input`, so bone
lengths are fixed by construction. The squat reproduces `fixtures/input` frame for frame.

Legs reach their ankle targets through two-bone IK, which keeps both bone lengths exact and puts
the lowest foot on the floor of that frame (the frame has no translation, so the floor is the
lowest ankle). The IK knee always bends toward the front.

`MotionParams.period_s` is the tempo (seconds per repetition). `depth`, `arm` and `step` are
factors of the family maximum (1.0 is the maximum): knee bend, arm travel and foot or hip travel.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable

JOINTS = (
    "nose", "left_eye", "right_eye", "left_ear", "right_ear",
    "left_shoulder", "right_shoulder", "left_elbow", "right_elbow", "left_wrist", "right_wrist",
    "left_hip", "right_hip", "left_knee", "right_knee", "left_ankle", "right_ankle",
)
CATEGORIES = ("exercise", "dance")

# The input fixture's body (fixtures/input/make_fixtures.py).
HIP_HALF, SHOULDER_HALF = 0.09, 0.19
THIGH, SHANK, TRUNK, UPPER_ARM, FOREARM = 0.43, 0.42, 0.50, 0.29, 0.26
HEAD_UP, NOSE_FWD = TRUNK + 0.25, 0.10
EYE_UP, EYE_FWD, EYE_SIDE = 0.04, 0.08, 0.03
EAR_UP, EAR_SIDE = 0.02, 0.075

SIDES = (("left", 1.0), ("right", -1.0))
STAND_H = 0.849          # hip height with nearly straight legs (full reach is 0.85)
FOOT_HALF = 0.11         # standing foot offset from the midline
KNEE_OUT = 0.25          # knees point forward and a little outward
REST_ARMS = {"left": ((0.05, 0.12), (0.05, 0.12)), "right": ((0.05, 0.12), (0.05, 0.12))}
LUNGE_STEP, LUNGE_HIP_MIN, LUNGE_LIFT = 0.70, 0.50, 0.10
JACK_SPREAD, JACK_ARM = 0.32, 2.6
SIDE_REACH, SIDE_SWAY, SIDE_LIFT, SIDE_SWING = 0.36, 0.45, 0.07, 0.7
WAVE_ARM, WAVE_RIPPLE, WAVE_SWAY = 2.45, 0.5, 0.04
TWIST_YAW = 0.55


@dataclass(frozen=True)
class MotionParams:
    """period_s: seconds per repetition; start_s: rest time before the first repetition."""
    period_s: float
    reps: int
    start_s: float = 0.0
    depth: float = 1.0
    arm: float = 1.0
    step: float = 1.0


def _add(a, b, k=1.0):
    return tuple(a[i] + k * b[i] for i in range(3))


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _norm(a):
    return math.sqrt(_dot(a, a))


def _wave(t, t0, period):
    """0 at the start of a repetition, 1 in the middle, 0 at the end."""
    return 0.5 * (1 - math.cos(2 * math.pi * (t - t0) / period))


def _cycle(t, p):
    """(repetition index, phase 0..1, wave 0..1..0); rest (0, 0, 0) outside the repetitions."""
    local = t - p.start_s
    if local < 0 or local > p.reps * p.period_s:
        return 0, 0.0, 0.0
    k = min(int(local // p.period_s), p.reps - 1)
    t0 = p.start_s + k * p.period_s
    return k, (t - t0) / p.period_s, _wave(t, t0, p.period_s)


def _alternate(k):
    """+1.0 (subject's left) on even repetitions, -1.0 on odd ones."""
    return 1.0 if k % 2 == 0 else -1.0


def _arm_dir(sx, raise_, abduct):
    """Unit direction of an arm segment: raise swings it forward, abduct swings it outward."""
    return (sx * math.sin(abduct), -math.cos(raise_) * math.cos(abduct),
            math.sin(raise_) * math.cos(abduct))


def _leg_fk(hip, flex, lean):
    knee = _add(hip, (0.0, -math.cos(flex), math.sin(flex)), THIGH)
    ankle = _add(knee, (0.0, -math.cos(lean), -math.sin(lean)), SHANK)
    return knee, ankle


def _perp(pole, axis):
    """Unit vector perpendicular to axis, as close to pole as possible."""
    for cand in (pole, (0.0, 0.0, 1.0), (1.0, 0.0, 0.0)):
        v = _add(cand, axis, -_dot(cand, axis))
        n = _norm(v)
        if n > 1e-9:
            return tuple(c / n for c in v)
    raise ValueError("no perpendicular")


def _leg_ik(hip, target, pole):
    """Knee and ankle of a two-bone leg reaching target; the ankle stops at full reach."""
    d = _add(target, hip, -1.0)
    raw = _norm(d)
    axis = tuple(c / raw for c in d) if raw > 1e-9 else (0.0, -1.0, 0.0)
    dist = min(max(raw, abs(THIGH - SHANK) + 1e-6), THIGH + SHANK - 1e-6)
    along = (THIGH ** 2 - SHANK ** 2 + dist ** 2) / (2 * dist)
    bulge = math.sqrt(max(THIGH ** 2 - along ** 2, 0.0))
    knee = _add(_add(hip, axis, along), _perp(pole, axis), bulge)
    return knee, _add(hip, axis, dist)


def _hip(sx, pelvis_yaw):
    return (sx * HIP_HALF * math.cos(pelvis_yaw), 0.0, -sx * HIP_HALF * math.sin(pelvis_yaw))


def _planted(feet, leg_len, pelvis_yaw=0.0, lifts=None):
    """Ankle targets for feet planted at (x, z) in the frame, hips low enough for both legs."""
    reach = 0.0
    for name, sx in SIDES:
        hip = _hip(sx, pelvis_yaw)
        reach = max(reach, (feet[name][0] - hip[0]) ** 2 + (feet[name][1] - hip[2]) ** 2)
    height = math.sqrt(max(leg_len ** 2 - reach, 0.0))
    lifts = lifts or {}
    return {name: (feet[name][0], -height + lifts.get(name, 0.0), feet[name][1])
            for name, _ in SIDES}


def _rig(arms, *, fk=None, ankles=None, lean=0.0, pelvis_yaw=0.0, shoulder_yaw=0.0, head_yaw=0.0):
    """All 17 joints: legs by FK (fk=(flex, lean)) or IK (ankles), arms by direction angles."""
    up = (0.0, math.cos(lean), math.sin(lean))
    fwd = (0.0, -math.sin(lean), math.cos(lean))
    j = {}
    for name, sx in SIDES:
        hip = _hip(sx, pelvis_yaw)
        if fk is not None:
            knee, ankle = _leg_fk(hip, *fk)
        else:
            knee, ankle = _leg_ik(hip, ankles[name], (sx * KNEE_OUT, 0.0, 1.0))
        base = (sx * SHOULDER_HALF * math.cos(shoulder_yaw), 0.0,
                -sx * SHOULDER_HALF * math.sin(shoulder_yaw))
        shoulder = _add(base, up, TRUNK)
        (up_r, up_a), (fo_r, fo_a) = arms[name]
        elbow = _add(shoulder, _arm_dir(sx, up_r, up_a), UPPER_ARM)
        wrist = _add(elbow, _arm_dir(sx, fo_r, fo_a), FOREARM)
        j.update({f"{name}_hip": hip, f"{name}_knee": knee, f"{name}_ankle": ankle,
                  f"{name}_shoulder": shoulder, f"{name}_elbow": elbow, f"{name}_wrist": wrist})
    j.update(_face(up, fwd, head_yaw))
    return j


def _face(up, fwd, head_yaw):
    head = _add((0.0, 0.0, 0.0), up, HEAD_UP)
    c, s = math.cos(head_yaw), math.sin(head_yaw)
    face = (fwd[0] * c + s, fwd[1] * c, fwd[2] * c)
    side = (c, -fwd[1] * s, -fwd[2] * s)
    out = {"nose": _add(head, face, NOSE_FWD)}
    for name, sx in SIDES:
        eye = _add(_add(_add(head, up, EYE_UP), face, EYE_FWD), side, sx * EYE_SIDE)
        out[f"{name}_eye"] = eye
        out[f"{name}_ear"] = _add(_add(head, up, EAR_UP), side, sx * EAR_SIDE)
    return out


def _finish(j):
    """Joint dict in canonical order, 4 decimals, no negative zero, conf 1.0."""
    return {n: {"x": round(j[n][0], 4) + 0.0, "y": round(j[n][1], 4) + 0.0,
                "z": round(j[n][2], 4) + 0.0, "conf": 1.0} for n in JOINTS}


def squat(t, p):
    """Bodyweight squat: hips back and down, trunk leans, arms rise for balance."""
    _, _, s = _cycle(t, p)
    s = s * p.depth
    arm = _arm_pair((0.1 + 1.4 * s * p.arm, 0.0), (0.1 + 1.4 * s * p.arm, 0.0))
    return _finish(_rig(arm, fk=(1.35 * s, 0.6 * s), lean=0.7 * s))


def _arm_pair(left, right=None):
    """The same (raise, abduct) for the upper arm and forearm of each side."""
    right = left if right is None else right
    return {"left": (left, left), "right": (right, right)}


def forward_lunge(t, p):
    """Alternating forward lunge: the stepping foot slides out and lifts, the hips drop."""
    k, u, s = _cycle(t, p)
    side = _alternate(k)
    length = LUNGE_STEP * p.step
    height = STAND_H - p.depth * s * (STAND_H - LUNGE_HIP_MIN)
    hip_z = 0.5 * length * s
    lift = LUNGE_LIFT * abs(math.sin(2 * math.pi * u))
    ankles = {}
    for name, sx in SIDES:
        stepping = sx == side
        z = (length * s if stepping else 0.0) - hip_z
        ankles[name] = (sx * FOOT_HALF, -height + (lift if stepping else 0.0), z)
    swing = 0.6 * p.arm * s
    arms = _arm_pair((0.1 + (swing if side < 0 else -0.5 * swing), 0.15),
                     (0.1 + (swing if side > 0 else -0.5 * swing), 0.15))
    return _finish(_rig(arms, ankles=ankles, lean=0.12 * s))


def jumping_jack(t, p):
    """Arms sweep overhead while the feet jump apart, then both close again."""
    _, _, s = _cycle(t, p)
    foot = FOOT_HALF + JACK_SPREAD * p.step * s
    ankles = _planted({n: (sx * foot, 0.0) for n, sx in SIDES}, STAND_H)
    reach = 0.12 + JACK_ARM * p.arm * s
    return _finish(_rig(_arm_pair((0.0, reach)), ankles=ankles))


def side_step(t, p):
    """Step-touch to each side in turn, hips following, arms swinging in opposition."""
    k, u, s = _cycle(t, p)
    side = _alternate(k)
    out = SIDE_REACH * p.step * s
    sway = SIDE_SWAY * out * side
    feet = {n: (sx * FOOT_HALF + (side * out if sx == side else 0.0) - sway, 0.0)
            for n, sx in SIDES}
    lifts = {n: SIDE_LIFT * abs(math.sin(2 * math.pi * u)) for n, sx in SIDES if sx == side}
    bounce = 0.05 * p.depth * 0.5 * (1 - math.cos(4 * math.pi * u))
    ankles = _planted(feet, STAND_H - bounce, lifts=lifts)
    swing = SIDE_SWING * p.arm * math.sin(math.pi * (k + u))
    left, right = (0.1 + swing, 0.2), (0.1 - swing, 0.2)
    arms = {"left": (left, (left[0] + 0.6, 0.2)), "right": (right, (right[0] + 0.6, 0.2))}
    return _finish(_rig(arms, ankles=ankles))


def arm_wave(t, p):
    """Both arms rise overhead and the forearms ripple from side to side, then lower."""
    _, u, s = _cycle(t, p)
    upper = 0.15 + WAVE_ARM * p.arm * s
    fore = upper + WAVE_RIPPLE * s * math.sin(2 * math.pi * 3 * u)
    sway = WAVE_SWAY * p.step * s * math.sin(4 * math.pi * u)
    feet = {n: (sx * FOOT_HALF - sway, 0.0) for n, sx in SIDES}
    ankles = _planted(feet, STAND_H - 0.06 * p.depth * s)
    arms = {"left": ((0.0, upper), (0.0, fore)), "right": ((0.0, upper), (0.0, fore))}
    return _finish(_rig(arms, ankles=ankles, lean=-0.05 * s))


def hip_twist(t, p):
    """Bent knees, feet planted: the pelvis twists one way and back, shoulders counter-rotate."""
    k, _, s = _cycle(t, p)
    side = _alternate(k)
    yaw = side * TWIST_YAW * p.step * s
    feet = {n: (sx * 0.12, 0.0) for n, sx in SIDES}
    ankles = _planted(feet, STAND_H - 0.07 - 0.08 * p.depth, pelvis_yaw=yaw)
    swing = 0.5 * p.arm * side * s
    arms = {"left": ((0.4 + swing, 0.45), (1.5 + swing, -0.15)),
            "right": ((0.4 - swing, 0.45), (1.5 - swing, -0.15))}
    return _finish(_rig(arms, ankles=ankles, pelvis_yaw=yaw, shoulder_yaw=-0.5 * yaw,
                        head_yaw=-0.3 * yaw))


@dataclass(frozen=True)
class Family:
    id: str
    category: str
    base_period_s: float
    marks: tuple[str, str, str]
    pose: Callable


FAMILIES = {f.id: f for f in (
    Family("squat", "exercise", 3.0, ("start", "bottom", "top"), squat),
    Family("forward-lunge", "exercise", 3.0, ("start", "bottom", "end"), forward_lunge),
    Family("jumping-jack", "exercise", 1.0, ("start", "open", "end"), jumping_jack),
    Family("side-step", "dance", 1.0, ("start", "out", "end"), side_step),
    Family("arm-wave", "dance", 2.0, ("start", "peak", "end"), arm_wave),
    Family("hip-twist", "dance", 1.0, ("start", "twist", "end"), hip_twist),
)}


def by_category(category):
    return [f for f in FAMILIES.values() if f.category == category]


def pose(family_id, t, params):
    return FAMILIES[family_id].pose(t, params)
