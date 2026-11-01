"""Per-frame measurements: joint angles and segment directions that don't depend on body size.

Every measure is a scalar in degrees, named for the subject's own left/right, with NaN where
a joint it needs is masked. MEASURES describes each one (joint, side, body part), so fault
detection and plain words can refer to it without special cases.
"""
from dataclasses import dataclass

import numpy as np

from .io import JOINTS

J = {name: i for i, name in enumerate(JOINTS)}
SIDES = ("left", "right")
OUT = {"left": np.array([1.0, 0, 0]), "right": np.array([-1.0, 0, 0])}  # away from the midline

# ADR-0015: foot geometry, pure maths on arrays of 3-vectors (docs/specs/foot-keypoints.md). The foot measures are a
# separate registry (FOOT_MEASURES, below), not part of MEASURES or compute(): their points come from Part 2's
# pose3d.json as an optional side input (part5.feet), so a pair without it is untouched. The three limits below are
# geometry guards, not detection thresholds: where the points cannot give a number the result is NaN, never a guess.
# ASM-013: the synthetic feet the calibration will use are a proxy for Part 2's estimated feet.
MIN_GROUND_SHARE = 0.25  # a hip line or foot axis needs this share of its length in the ground plane to have a heading
MIN_CROSS_SHARE = 0.25   # world up needs this share of its length across the foot's long axis for a roll
MIN_TOE_SPREAD = 0.1     # sine of the angle at the heel between the two toes; below it the toes and heel are collinear


@dataclass(frozen=True)
class MeasureSpec:
    name: str
    joint: str        # joint the measure is reported at, e.g. "left_elbow" or "spine"
    side: str         # left / right / center
    body_part: str    # arms / legs / torso / head
    kind: str         # angle / direction
    description: str


def _unit(v):
    n = np.linalg.norm(v, axis=-1, keepdims=True)
    with np.errstate(invalid="ignore", divide="ignore"):
        return v / n


def _angle(u, v):
    """Angle between vectors, degrees, per frame."""
    c = np.sum(_unit(u) * _unit(v), axis=-1)
    return np.degrees(np.arccos(np.clip(c, -1, 1)))


def _flexion(p, a, b, c):
    """180 − interior angle at b: 0 = straight, grows as the joint bends."""
    return 180 - _angle(p[:, J[a]] - p[:, J[b]], p[:, J[c]] - p[:, J[b]])


def _out_angle(seg, side):
    """Signed angle of a segment out of the sagittal plane, positive = away from the midline."""
    return np.degrees(np.arcsin(np.clip(_unit(seg) @ OUT[side], -1, 1)))


def _sagittal(seg):
    """Lean of a segment from vertical in the sagittal plane, positive = forward (anterior)."""
    return np.degrees(np.arctan2(seg[:, 2], seg[:, 1]))


def _forward_from_down(seg):
    """Raise of a hanging segment toward the front: 0 = straight down, 90 = pointing forward."""
    return np.degrees(np.arctan2(seg[:, 2], -seg[:, 1]))


def _lateral(seg):
    """Lean of a segment from vertical in the frontal plane, positive = toward the subject's left.

    The angle of its frontal projection, so it wraps once the segment passes horizontal in the sagittal plane (a
    trunk hinged 90 degrees forward has no height left to lean from). Used for the neck of the head-and-shoulder view
    measures only; the trunk uses `_sideways`."""
    return np.degrees(np.arctan2(seg[:, 0], seg[:, 1]))


def _sideways(seg):
    """Lean of a segment out of the sagittal plane, positive = toward the subject's left (ADR-0017).

    `asin` of the segment's sideways component over its length, written as an `arctan2` against the rest of the
    vector so a zero length is not a division. It stays in -90..90 degrees, is continuous, and does not depend on how
    far the segment has hinged forward: a trunk bent 0 to 180 degrees forward with no side lean reads 0, where the
    angle of the frontal projection (`_lateral`) wraps to 180 degrees past 90 (moalborati/simon#59: 155 degrees on a real
    Romanian deadlift)."""
    return np.degrees(np.arctan2(seg[:, 0], np.hypot(seg[:, 1], seg[:, 2])))


def _knee_valgus(hip, knee, ankle, side):
    """How far the knee sits inside the hip to ankle line, degrees, positive = caving in.

    d is the knee's offset from that line toward the midline; dividing by the thigh length
    keeps it independent of body size, and a straight leg in the frontal plane reads 0.
    """
    thigh = knee - hip
    axis = _unit(ankle - hip)
    off = thigh - np.sum(thigh * axis, axis=-1, keepdims=True) * axis
    return np.degrees(np.arctan2(off @ -OUT[side], np.linalg.norm(thigh, axis=-1)))


def _side_sign(side):
    """+1 for the subject's left, -1 for the right: the sign of `OUT[side]` along x."""
    if side not in ("left", "right"):
        raise ValueError(f"side must be 'left' or 'right', got {side!r}")
    return float(OUT[side][0])


def _foot_rotation(hip_l, hip_r, heel, big_toe, side):
    """Toe-out of one foot against the pelvis, degrees, positive = the toes point away from the midline.

    All arguments are (F, 3) points (or one (3,) point) in the canonical frame: x subject-left, y up, z anterior,
    so the ground plane is x-z. The foot axis is the heel to big toe vector and the reference is the pelvis's
    forward, the hip line (left minus right hip) turned a quarter turn in the ground plane, so a pelvis that
    twists with the feet reads 0. Height is ignored: a heel raised off the floor does not change the heading.
    The angle is signed per side by `OUT`, so a left foot turned out and a right foot turned out both read positive.

    NaN where it has no meaning: a hip line or foot axis with under MIN_GROUND_SHARE of its length in the ground
    plane (no heading), a foot 90 degrees or more from the pelvis's forward (heel and toe swapped, not a stance),
    and any NaN input.
    """
    sign = _side_sign(side)
    hip = np.asarray(hip_l, float) - np.asarray(hip_r, float)
    foot = np.asarray(big_toe, float) - np.asarray(heel, float)
    hx, hz, fx, fz = hip[..., 0], hip[..., 2], foot[..., 0], foot[..., 2]
    with np.errstate(invalid="ignore", divide="ignore"):
        hip_ground, foot_ground = np.hypot(hx, hz), np.hypot(fx, fz)
        across = (fx * hx + fz * hz) / hip_ground     # along the hip line, toward the subject's left
        ahead = (fz * hx - fx * hz) / hip_ground      # along the pelvis's forward
        ok = ((hip_ground >= MIN_GROUND_SHARE * np.linalg.norm(hip, axis=-1))
              & (foot_ground >= MIN_GROUND_SHARE * np.linalg.norm(foot, axis=-1)) & (ahead > 0))
        return np.where(ok, np.degrees(np.arctan2(sign * across, ahead)), np.nan)


def _ankle_inversion(heel, big_toe, small_toe, side):
    """Roll of the foot against the vertical, degrees, positive = the sole turns toward the midline (inversion).

    Arguments are (F, 3) points (or one (3,) point) in the canonical frame (y up). The foot has a frame of its own:
    its long axis runs from the heel to the middle of the two toes, its up is the normal of the plane through heel,
    big toe and small toe (pointing out of the sole), and its outer edge is up crossed with the long axis, signed per
    side. World up (0, 1, 0) seen down the long axis has a component along the foot's up and one along its outer edge:
    the roll is atan2(-outer, up). A foot flat on the floor reads 0 whatever its heading or its pitch (a raised
    heel); the outer edge going down reads positive on both sides, which is the sole turning toward the midline.
    It does not read the shin: a knee travelling over the toes or caving in moves nothing (spec "ankle_inversion",
    the seed 5 result of the first, shin-relative definition).

    NaN where it has no meaning: the two toes and the heel nearly collinear (sine of the angle at the heel under
    MIN_TOE_SPREAD, so no foot plane), a foot pitched so steeply that under MIN_CROSS_SHARE of world up lies across
    its long axis (standing on the toes, no roll), world up on the sole's side of the foot plane (toes swapped, or a
    foot rolled 90 degrees or more), and any NaN input.
    """
    sign = _side_sign(side)
    heel, big, small = (np.asarray(x, float) for x in (heel, big_toe, small_toe))
    to_big, to_small = big - heel, small - heel
    with np.errstate(invalid="ignore", divide="ignore"):
        plane = np.cross(to_big, to_small)
        spread = np.linalg.norm(plane, axis=-1) / (np.linalg.norm(to_big, axis=-1) * np.linalg.norm(to_small, axis=-1))
        up = _unit(plane * sign)
        axis = _unit((big + small) / 2 - heel)
        outer = _unit(np.cross(up, axis) * sign)
        u_up, u_outer = up[..., 1], outer[..., 1]   # the y component is the dot product with world up
        ok = (spread >= MIN_TOE_SPREAD) & (np.hypot(u_up, u_outer) >= MIN_CROSS_SHARE) & (u_up > 0)
        return np.where(ok, np.degrees(np.arctan2(-u_outer, u_up)), np.nan)


def _mid(p, a, b):
    return (p[:, J[a]] + p[:, J[b]]) / 2


def _specs():
    s = []
    for side in SIDES:
        s += [
            MeasureSpec(f"{side}_elbow_flexion", f"{side}_elbow", side, "arms", "angle", "elbow bend"),
            MeasureSpec(f"{side}_knee_flexion", f"{side}_knee", side, "legs", "angle", "knee bend"),
            MeasureSpec(f"{side}_upper_arm_out", f"{side}_shoulder", side, "arms", "direction",
                        "upper arm out from the body (frontal)"),
            MeasureSpec(f"{side}_upper_arm_forward", f"{side}_shoulder", side, "arms", "direction",
                        "upper arm raised forward relative to the trunk (0 = along the trunk, hanging)"),
            MeasureSpec(f"{side}_forearm_out", f"{side}_elbow", side, "arms", "direction", "forearm out from the body"),
            MeasureSpec(f"{side}_thigh_out", f"{side}_hip", side, "legs", "direction", "thigh out from the body"),
            MeasureSpec(f"{side}_thigh_forward", f"{side}_hip", side, "legs", "direction",
                        "thigh raised forward (0 = straight down)"),
            MeasureSpec(f"{side}_foot_out", f"{side}_ankle", side, "legs", "direction",
                        "foot out from under the hip (hip→ankle, frontal)"),
        ]
    s += [
        MeasureSpec("trunk_lean_forward", "spine", "center", "torso", "direction", "trunk lean forward"),
        MeasureSpec("trunk_lean_side", "spine", "center", "torso", "direction", "trunk lean to the subject's left"),
        MeasureSpec("shoulder_tilt", "shoulders", "center", "torso", "direction", "left shoulder higher than right"),
        MeasureSpec("head_forward", "neck", "center", "head", "direction", "head forward of the shoulders"),
    ]
    # Last, so the order of the original measures (and the alignment built on it) is unchanged.
    s += [MeasureSpec(f"{side}_knee_valgus", f"{side}_knee", side, "legs", "direction",
                      "knee caving in, inside the hip to ankle line") for side in SIDES]
    return {m.name: m for m in s}


MEASURES = _specs()


def _foot_specs():
    """The foot measures (ADR-0015): left then right of each, reported at the ankle, body part "feet"."""
    kinds = (("foot_rotation", "foot turned out from the pelvis's forward (heel to big toe, ground plane)"),
             ("ankle_inversion", "foot rolled onto its outer edge, the ankle rolling out (roll about the foot's long axis)"))
    return {f"{side}_{name}": MeasureSpec(f"{side}_{name}", f"{side}_ankle", side, "feet", "direction", text)
            for name, text in kinds for side in SIDES}


FOOT_MEASURES = _foot_specs()
ALL_SPECS = {**MEASURES, **FOOT_MEASURES}   # every measure a fault may name, body and foot


def compute_feet(points):
    """The four foot series from `points`, {name: (F, 3)} with NaN where a point is not seen.

    Names: left_hip, right_hip and `{side}_big_toe`, `{side}_small_toe`, `{side}_heel` (`foot_rotation` reads the
    hips, the heel and the big toe; `ankle_inversion` the three foot points of its side). The points are read in
    one frame (the side file's own), so no body clip is needed. NaN propagates: a frame with any point a measure
    reads missing is NaN for that measure.
    """
    out = {}
    for side in SIDES:
        out[f"{side}_foot_rotation"] = _foot_rotation(points["left_hip"], points["right_hip"], points[f"{side}_heel"],
                                                      points[f"{side}_big_toe"], side)
    for side in SIDES:
        out[f"{side}_ankle_inversion"] = _ankle_inversion(points[f"{side}_heel"], points[f"{side}_big_toe"],
                                                          points[f"{side}_small_toe"], side)
    return out


def _measure_joints():
    """The joints each measure reads (ADR-0011), by measure name."""
    def of(side, *parts):
        return [f"{side}_{x}" for x in parts]

    trunk = ["left_shoulder", "right_shoulder", "left_hip", "right_hip"]
    out = {}
    for side in SIDES:
        out[f"{side}_elbow_flexion"] = of(side, "shoulder", "elbow", "wrist")
        out[f"{side}_knee_flexion"] = out[f"{side}_knee_valgus"] = of(side, "hip", "knee", "ankle")
        out[f"{side}_upper_arm_out"] = of(side, "shoulder", "elbow")
        out[f"{side}_forearm_out"] = of(side, "elbow", "wrist")
        out[f"{side}_thigh_out"] = out[f"{side}_thigh_forward"] = of(side, "hip", "knee")
        out[f"{side}_foot_out"] = of(side, "hip", "ankle")
        out[f"{side}_upper_arm_forward"] = of(side, "shoulder", "elbow") + trunk  # relative to the trunk
    out["trunk_lean_forward"] = out["trunk_lean_side"] = trunk
    out["shoulder_tilt"] = ["left_shoulder", "right_shoulder"]
    out["head_forward"] = ["nose"] + trunk
    return out


MEASURE_JOINTS = _measure_joints()


def compute(positions):
    """positions (F, 17, 3) → {measure name: (F,) degrees}. NaN propagates from masked joints."""
    p = np.asarray(positions, float)
    out = {}
    for side in SIDES:
        sh, el, wr = (p[:, J[f"{side}_{x}"]] for x in ("shoulder", "elbow", "wrist"))
        hp, kn, an = (p[:, J[f"{side}_{x}"]] for x in ("hip", "knee", "ankle"))
        out[f"{side}_elbow_flexion"] = _flexion(p, f"{side}_shoulder", f"{side}_elbow", f"{side}_wrist")
        out[f"{side}_knee_flexion"] = _flexion(p, f"{side}_hip", f"{side}_knee", f"{side}_ankle")
        out[f"{side}_upper_arm_out"] = _out_angle(el - sh, side)
        out[f"{side}_forearm_out"] = _out_angle(wr - el, side)
        out[f"{side}_thigh_out"] = _out_angle(kn - hp, side)
        out[f"{side}_thigh_forward"] = _forward_from_down(kn - hp)
        out[f"{side}_foot_out"] = _out_angle(an - hp, side)
        out[f"{side}_knee_valgus"] = _knee_valgus(hp, kn, an, side)
    spine = _mid(p, "left_shoulder", "right_shoulder") - _mid(p, "left_hip", "right_hip")
    out["trunk_lean_forward"] = _sagittal(spine)
    for side in SIDES:
        # Shoulder flexion is relative to the trunk: arms that keep their angle to a leaning
        # trunk aren't "raised" or "lowered", the trunk lean is the fault.
        sh, el = p[:, J[f"{side}_shoulder"]], p[:, J[f"{side}_elbow"]]
        out[f"{side}_upper_arm_forward"] = _forward_from_down(el - sh) + out["trunk_lean_forward"]
    out["trunk_lean_side"] = _sideways(spine)   # ADR-0017: bounded through a deep forward hinge
    sl = p[:, J["left_shoulder"]] - p[:, J["right_shoulder"]]
    out["shoulder_tilt"] = np.degrees(np.arctan2(sl[:, 1], np.hypot(sl[:, 0], sl[:, 2])))
    head = p[:, J["nose"]] - _mid(p, "left_shoulder", "right_shoulder")
    out["head_forward"] = _sagittal(head) - out["trunk_lean_forward"]
    return out


# Head-and-shoulder "view" measures (ADR-0011). They read only the joints a seated or close-up selfie
# shows (face, shoulders, a raised wrist) and take no hip. They are used only when a pair is compared on
# fewer measures than the full body: for timing and the guard's statistics, never as a reported fault.
VIEW_MEASURES = {
    "head_roll": ("left_ear", "right_ear"),
    "head_turn": ("left_ear", "right_ear"),
    "head_pitch": ("nose", "left_ear", "right_ear"),
    "shoulder_turn": ("left_shoulder", "right_shoulder"),
    "neck_lean_side": ("nose", "left_shoulder", "right_shoulder"),
    "neck_lean_forward": ("nose", "left_shoulder", "right_shoulder"),
    **{f"{side}_wrist_height": (f"{side}_shoulder", f"{side}_wrist") for side in SIDES},
    **{f"{side}_wrist_out": (f"{side}_shoulder", f"{side}_wrist") for side in SIDES},
}


def _yaw(v):
    return np.degrees(np.arctan2(v[:, 2], v[:, 0]))


def compute_view(positions):
    """positions (F, 17, 3) -> {view measure name: (F,) degrees}; NaN propagates from masked joints."""
    p = np.asarray(positions, float)
    ears = p[:, J["left_ear"]] - p[:, J["right_ear"]]
    neck = p[:, J["nose"]] - _mid(p, "left_shoulder", "right_shoulder")
    face = p[:, J["nose"]] - _mid(p, "left_ear", "right_ear")
    sl = p[:, J["left_shoulder"]] - p[:, J["right_shoulder"]]
    out = {"head_roll": np.degrees(np.arctan2(ears[:, 1], np.hypot(ears[:, 0], ears[:, 2]))),
           "head_turn": _yaw(ears),
           "head_pitch": np.degrees(np.arctan2(face[:, 1], face[:, 2])),
           "shoulder_turn": _yaw(sl),
           "neck_lean_side": _lateral(neck),
           "neck_lean_forward": _sagittal(neck)}
    for side in SIDES:
        arm = p[:, J[f"{side}_wrist"]] - p[:, J[f"{side}_shoulder"]]
        out[f"{side}_wrist_height"] = np.degrees(np.arctan2(arm[:, 1], np.hypot(arm[:, 0], arm[:, 2])))
        out[f"{side}_wrist_out"] = _out_angle(arm, side)
    return out


def feature_matrix(measures, names=None):
    """Stack measures into (F, M) for alignment; NaNs are left for the caller to handle."""
    names = names or list(MEASURES)
    return np.stack([measures[n] for n in names], axis=1), names
