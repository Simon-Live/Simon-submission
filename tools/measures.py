"""Reference implementation of movement.schema.json rule measures (v0.1.0).

Used by the fixture generator and validate_fixtures.py so the hand-written
rules are checked against the fixture motion. Track B's live evaluator must
produce the same numbers for the same frames.
"""
from __future__ import annotations

import math

Vec = tuple[float, float, float]
# Need the user's motion time-aligned to the reference (P10), so only the live evaluator computes them.
LIVE_ONLY_MEASURES = {"pose_similarity", "timing"}
OPS = {
    ">": lambda v, t, h: v > t,
    ">=": lambda v, t, h: v >= t,
    "<": lambda v, t, h: v < t,
    "<=": lambda v, t, h: v <= t,
    "outside": lambda v, t, h: v < t or v > h,
    "inside": lambda v, t, h: t <= v <= h,
}


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


def unit(a: Vec) -> Vec:
    n = norm(a)
    return (a[0] / n, a[1] / n, a[2] / n)


def mid(a: Vec, b: Vec) -> Vec:
    return ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, (a[2] + b[2]) / 2)


def mirror(joint: str) -> str:
    if joint.startswith("left_"):
        return "right_" + joint[5:]
    if joint.startswith("right_"):
        return "left_" + joint[6:]
    return joint


def _p(joints: dict, name: str) -> Vec:
    j = joints[name]
    return (j["x"], j["y"], j["z"])


def angle_3d(joints: dict, a: str, b: str, c: str) -> float:
    u, w = sub(_p(joints, a), _p(joints, b)), sub(_p(joints, c), _p(joints, b))
    return math.degrees(math.acos(max(-1.0, min(1.0, dot(u, w) / (norm(u) * norm(w))))))


def frontal_angle(joints: dict, a: str, b: str, min_projected_ratio: float) -> float | None:
    """Angle of segment a->b in the body's frontal plane, from torso_caudal. None if too foreshortened."""
    shoulder_mid = mid(_p(joints, "left_shoulder"), _p(joints, "right_shoulder"))
    hip_mid = mid(_p(joints, "left_hip"), _p(joints, "right_hip"))
    caudal = unit(sub(hip_mid, shoulder_mid))
    normal = unit(cross(sub(_p(joints, "left_shoulder"), _p(joints, "right_shoulder")), caudal))
    lateral = cross(caudal, normal)  # in-plane, perpendicular to caudal
    seg = sub(_p(joints, b), _p(joints, a))
    along_normal = dot(seg, normal)
    projected = sub(seg, (normal[0] * along_normal, normal[1] * along_normal, normal[2] * along_normal))
    if norm(projected) < min_projected_ratio * norm(seg):
        return None
    return math.degrees(math.atan2(abs(dot(projected, lateral)), dot(projected, caudal)))


def measure_value(joints: dict, measure: dict, flip: bool = False) -> float | None:
    names = [mirror(j) if flip else j for j in measure["joints"]]
    if measure["type"] != "angle":
        raise NotImplementedError(f"measure type {measure['type']!r} not implemented yet")
    if "plane" in measure:
        return frontal_angle(joints, names[0], names[1], measure["min_projected_ratio"])
    return angle_3d(joints, *names)


def _side_faults(joints: dict, rule: dict) -> bool | None:
    """Whether this frame faults under the rule's side policy; None if not measurable."""
    m, fw = rule["measure"], rule["fault_when"]
    check = lambda v: OPS[fw["operator"]](v, fw["threshold"], fw.get("threshold_high"))
    written = measure_value(joints, m)
    if rule["side"] == "as_written":
        return None if written is None else check(written)
    mirrored = measure_value(joints, m, flip=True)
    if rule["side"] == "visible":
        conf = lambda names: sum(joints[n]["conf"] for n in names) / len(names)
        use_mirror = conf([mirror(j) for j in m["joints"]]) > conf(m["joints"])
        value = mirrored if use_mirror else written
        return None if value is None else check(value)
    results = [check(v) for v in (written, mirrored) if v is not None]
    if not results:
        return None
    return any(results) if rule["side"] == "either" else (len(results) == 2 and all(results))


def rule_fires_per_rep(pkg: dict, rule: dict) -> dict[int, bool]:
    """rep number -> whether the rule fires (>= min_frames consecutive faulting frames in its phases)."""
    frames = {f["frame"]: f for f in pkg["reference_motion"]["frames"]}
    fired: dict[int, bool] = {}
    for rep in sorted({p["rep"] for p in pkg["phases"]}):
        run = best = 0
        segments = sorted((p for p in pkg["phases"] if p["rep"] == rep), key=lambda p: p["start_frame"])
        for seg in segments:
            for i in range(seg["start_frame"], seg["end_frame"] + 1):
                fault = seg["name"] in rule["phases"] and _side_faults(frames[i]["joints"], rule)
                run = run + 1 if fault else 0
                best = max(best, run)
        fired[rep] = best >= rule["min_frames"]
    return fired
