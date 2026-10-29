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
    """Lean of a segment from vertical in the frontal plane, positive = toward the subject's left."""
    return np.degrees(np.arctan2(seg[:, 0], seg[:, 1]))


def _knee_valgus(hip, knee, ankle, side):
    """How far the knee sits inside the hip to ankle line, degrees, positive = caving in.

    d is the knee's offset from that line toward the midline; dividing by the thigh length
    keeps it independent of body size, and a straight leg in the frontal plane reads 0.
    """
    thigh = knee - hip
    axis = _unit(ankle - hip)
    off = thigh - np.sum(thigh * axis, axis=-1, keepdims=True) * axis
    return np.degrees(np.arctan2(off @ -OUT[side], np.linalg.norm(thigh, axis=-1)))


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
    out["trunk_lean_side"] = _lateral(spine)
    sl = p[:, J["left_shoulder"]] - p[:, J["right_shoulder"]]
    out["shoulder_tilt"] = np.degrees(np.arctan2(sl[:, 1], np.hypot(sl[:, 0], sl[:, 2])))
    head = p[:, J["nose"]] - _mid(p, "left_shoulder", "right_shoulder")
    out["head_forward"] = _sagittal(head) - out["trunk_lean_forward"]
    return out


def feature_matrix(measures, names=None):
    """Stack measures into (F, M) for alignment; NaNs are left for the caller to handle."""
    names = names or list(MEASURES)
    return np.stack([measures[n] for n in names], axis=1), names
