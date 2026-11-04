"""Follower takes for Part 5 and the measures that find their faults again in Part 3's output.

Spec integration-contract.md "Conformance kit". A take is the real Part 2 squat (`synth.load_source`) with
at most one deliberate fault applied in the body frame (x subject's left, y up, z anterior, origin the hip
midpoint), then rendered like the synthetic set: a camera at front 0, 45 or side 90 degrees, Part 2-like
errors from the synth module, Part 2's per-frame pelvis frame. Every fault keeps every bone length exact.

Random draws: `synth.draw(k, n)` with stream k = STREAM_BASE + the take's position in `take_defs()`, so each
take has its own noise and the streams cannot meet the synthetic set's (k = 1 to 4 and 6).

The faults and what a measure reads on a skeleton (all increase with the fault, per side):
- feet_wide: lateral ankle position, metres, outward positive; constant over the clip.
- elbows_out: upper-arm abduction in the frontal plane, degrees; constant over the clip.
- shallow_squat: knee interior angle, degrees; the fault is added in proportion to squat depth.
- knee_caving: inward turn of the thigh about the vertical axis, degrees; in proportion to squat depth.
Depth is `depth_weight` of the mean knee angle: 0 standing, 1 at the bottom of a repetition.
"""

from dataclasses import dataclass

import numpy as np

from part3 import io, synth
from part3.angles import joints_array
from part3.geometry import interior_angle, knee_angles, normalize, point
from part3.joints import BONE_NAMES, INDEX

LABELS_FORMAT = "simon.part3.follower_labels/1"
MOVEMENT = "squat"
SET_NAME = "followers"
STREAM_BASE = 20
# (angle name, azimuth, pitch, roll): the cameras of synthetic takes 1 to 3.
ANGLES = (("front", 0.0, 12.0, -5.0), ("45", 45.0, -8.0, 6.0), ("side", 90.0, 20.0, 3.0))
SIDES = (("left", 1.0), ("right", -1.0))
W_MIN = 0.5      # a bottom-of-squat measure uses the frames at least half way down
DEPTH_PERCENTILES = (2, 98)
DECIMALS = 4


@dataclass(frozen=True)
class Kind:
    """One fault type: its label text, its unit and its applied size."""
    measure: str
    body_part: str
    direction: str
    unit: str            # "m" or "deg"
    text: str            # label text, {side} is "left", "right" or "both"
    size: float          # applied size
    by_depth: bool       # True: the fault grows with squat depth

    @property
    def threshold(self):
        """A correct take stays under this on every side: half the applied size, as AC-K03 reads visibility."""
        return 0.5 * self.size


KINDS = {
    "feet_wide": Kind("ankle_lateral_offset", "legs", "more", "m", "feet too wide", 0.10, False),
    "elbows_out": Kind("upper_arm_abduction", "arms", "more", "deg", "elbows too far out", 20.0, False),
    "shallow_squat": Kind("knee_angle_at_bottom", "legs", "less", "deg",
                          "knees not bent enough at the bottom", 25.0, True),
    "knee_caving": Kind("thigh_inward_turn_at_bottom", "legs", "more", "deg",
                        "{side} knee caves in at the bottom", 12.0, True),
}
FAULT_ORDER = tuple(KINDS)
# The fault takes that touch one side only, by angle: it keeps left and right apart in the kit.
ONE_SIDED = {"knee_caving": {"front": "left", "45": "right", "side": "left"}}
JOINTS_OF = {"feet_wide": "ankle", "elbows_out": "shoulder", "shallow_squat": "knee", "knee_caving": "knee"}


@dataclass(frozen=True)
class TakeDef:
    take_id: str
    angle: str
    azimuth: float
    pitch: float
    roll: float
    stream: int
    fault: str | None     # a key of KINDS, None for the correct take
    side: str | None      # "left", "right" or "both"; None for the correct take

    @property
    def spec(self):
        return synth.Spec(self.stream, self.azimuth, self.pitch, self.roll, 0.0, 1.0)

    @property
    def size(self):
        return KINDS[self.fault].size if self.fault else None


def take_defs():
    """The 15 takes: per angle the correct take, then the four faults, in a fixed order."""
    defs = []
    for angle, azimuth, pitch, roll in ANGLES:
        for fault in (None,) + FAULT_ORDER:
            side = None if fault is None else ONE_SIDED.get(fault, {}).get(angle, "both")
            tail = "correct" if fault is None else fault + ("" if side == "both" else f"-{side}")
            defs.append(TakeDef(f"{MOVEMENT}_{angle}_{tail}", angle, azimuth, pitch, roll,
                                STREAM_BASE + len(defs), fault, side))
    return defs


# ---- measures ---------------------------------------------------------------------------------

def depth_weight(knee_deg):
    """Squat depth in [0, 1] from the mean knee angle per frame: 0 standing, 1 at the bottom; NaN stays NaN."""
    knee_deg = np.asarray(knee_deg, dtype=float)
    low, high = np.nanpercentile(knee_deg, DEPTH_PERCENTILES)
    return np.clip((high - knee_deg) / (high - low), 0.0, 1.0)


def _series(fault, J, name, sign):
    """(n,) value of the fault's quantity for one side of frames J (n, 17, 3)."""
    ix = lambda joint: J[:, INDEX[f"{name}_{joint}"]]  # noqa: E731
    if fault == "feet_wide":
        return sign * (ix("ankle")[:, 0] - point(J, "root")[:, 0])
    if fault == "elbows_out":
        v = ix("elbow") - ix("shoulder")
        return np.degrees(np.arctan2(sign * v[:, 0], -v[:, 1]))
    if fault == "shallow_squat":
        return interior_angle(ix("hip"), ix("knee"), ix("ankle"))
    v = ix("knee") - ix("hip")
    return -np.degrees(np.arctan2(sign * v[:, 0], v[:, 2]))


def sizes(fault, skeleton, reference):
    """{"left": size, "right": size}: how much more of `fault` `skeleton` shows than `reference`.

    Both are skeleton dicts with the same frames. The per-frame difference of the fault's quantity is
    fitted as `size * w` (w is the reference's depth for bottom-of-squat faults, 1 for the others), so the
    size is the one at the bottom of a repetition. Units are metres for feet_wide, else degrees.
    """
    J, R = joints_array(skeleton), joints_array(reference)
    kind = KINDS[fault]
    w = depth_weight(knee_angles(R).mean(axis=-1)) if kind.by_depth else np.ones(len(R))
    out = {}
    for name, sign in SIDES:
        diff = _series(fault, J, name, sign) - _series(fault, R, name, sign)
        use = np.isfinite(diff) & np.isfinite(w) & (w >= (W_MIN if kind.by_depth else 0.0))
        out[name] = float(np.sum(w[use] * diff[use]) / np.sum(w[use] ** 2))
    return out


# ---- applying a fault in the body frame ---------------------------------------------------------

def _rodrigues(vectors, axes, degrees):
    """Rotate vectors (n, 3) about unit axes (n, 3) by degrees (n,); the axes are perpendicular to them."""
    a = np.radians(degrees)[:, None]
    return vectors * np.cos(a) + np.cross(axes, vectors) * np.sin(a)


def sides(side):
    """[(name, sign)] of the sides a label's `side` (left, right or both) names."""
    return [(name, sign) for name, sign in SIDES if side in ("both", name)]


def _feet_wide(J, size, side, lengths, weight):
    """Both ankles `size` metres further out (x), the shank turned about the knee at its own length."""
    out = np.array(J, copy=True)
    for name, sign in sides(side):
        knee, ankle = J[:, INDEX[f"{name}_knee"]], J[:, INDEX[f"{name}_ankle"]]
        shank = ankle - knee
        shank[:, 0] += sign * size
        rest = np.sqrt(lengths[BONE_NAMES.index(f"{name}_shank")] ** 2 - shank[:, 0] ** 2)
        shank[:, 1:] *= (rest / np.linalg.norm(shank[:, 1:], axis=-1))[:, None]
        out[:, INDEX[f"{name}_ankle"]] = knee + shank
    return out


def _elbows_out(J, size, side, lengths, weight):
    """Each upper arm turned `size` degrees outward about the anterior axis at the shoulder; the forearm follows."""
    out = np.array(J, copy=True)
    for name, sign in sides(side):
        shoulder, elbow = J[:, INDEX[f"{name}_shoulder"]], J[:, INDEX[f"{name}_elbow"]]
        v = elbow - shoulder
        c, s = np.cos(np.radians(sign * size)), np.sin(np.radians(sign * size))
        turned = np.stack([c * v[:, 0] - s * v[:, 1], s * v[:, 0] + c * v[:, 1], v[:, 2]], axis=-1)
        out[:, INDEX[f"{name}_elbow"]] = shoulder + turned
        out[:, INDEX[f"{name}_wrist"]] = J[:, INDEX[f"{name}_wrist"]] + (shoulder + turned - elbow)
    return out


def _shallow_squat(J, size, side, lengths, weight):
    """The shank turned about the knee hinge so the knee angle grows by `size * depth` degrees."""
    out = np.array(J, copy=True)
    for name, _ in sides(side):
        hip, knee, ankle = (J[:, INDEX[f"{name}_{j}"]] for j in ("hip", "knee", "ankle"))
        axis = normalize(np.cross(hip - knee, ankle - knee))
        out[:, INDEX[f"{name}_ankle"]] = knee + _rodrigues(ankle - knee, axis, size * weight)
    return out


def _knee_caving(J, size, side, lengths, weight):
    """The thigh turned about the vertical axis at the hip so the knee moves inward by `size * depth` degrees.

    The ankle stays; the shank is pointed from the new knee to it at its own length.
    """
    out = np.array(J, copy=True)
    for name, sign in sides(side):
        hip, knee, ankle = (J[:, INDEX[f"{name}_{j}"]] for j in ("hip", "knee", "ankle"))
        phi = np.radians(-sign * size * weight)
        c, s = np.cos(phi), np.sin(phi)
        thigh = knee - hip
        turned = np.stack([c * thigh[:, 0] + s * thigh[:, 2], thigh[:, 1], -s * thigh[:, 0] + c * thigh[:, 2]],
                          axis=-1)
        new_knee = hip + turned
        length = lengths[BONE_NAMES.index(f"{name}_shank")]
        out[:, INDEX[f"{name}_knee"]] = new_knee
        out[:, INDEX[f"{name}_ankle"]] = new_knee + length * normalize(ankle - new_knee)
    return out


_APPLY = {"feet_wide": _feet_wide, "elbows_out": _elbows_out, "shallow_squat": _shallow_squat,
          "knee_caving": _knee_caving}


def apply_fault(J, fault, size, side, lengths):
    """Frames J (n, 17, 3) in the body frame with `fault` of `size` applied on `side`; bone lengths unchanged."""
    weight = depth_weight(knee_angles(J).mean(axis=-1))
    return _APPLY[fault](J, size, side, lengths, weight)


# ---- building a take --------------------------------------------------------------------------

def build_take(src, td):
    """The synth Take for a take definition (clean truth with the fault, then camera and errors)."""
    n = len(src.frames)
    times = np.arange(n) / synth.FPS
    clean = synth.truth_at(src, times)
    if td.fault:
        clean = apply_fault(clean, td.fault, td.size, td.side, src.lengths)
    return synth.finish(src, td.spec, times, clean, synth.draw(td.stream, n), far_side=td.angle == "side")


def pose3d_for(src, td):
    """The take's `pose3d.json` as a dict (Part 2's shape, 15 fps)."""
    take = build_take(src, td)
    return synth.pose3d_doc(take.canon, take.conf)


# ---- labels -----------------------------------------------------------------------------------

def fault_label(td, measured=None):
    """One `faults[]` entry in Part 5's field names; `measured` (size in the fault's unit) is added when known."""
    kind = KINDS[td.fault]
    joints = [f"{name}_{JOINTS_OF[td.fault]}" for name, _ in sides(td.side)]
    entry = {"type": td.fault, "measure": kind.measure, "body_part": kind.body_part, "joints": joints,
             "side": td.side, "direction": kind.direction,
             f"magnitude_{kind.unit}": td.size, "text": kind.text.format(side=td.side)}
    if measured is not None:
        entry["measured_in_output"] = measured
    return entry


def take_label(td, measured=None):
    """One `takes[]` entry; `measured` maps a fault type to its measured size, or is None before a build."""
    faults = [] if td.fault is None else [fault_label(td, None if measured is None else measured[td.take_id])]
    return {"take_id": td.take_id, "set": SET_NAME, "movement": MOVEMENT, "angle": td.angle,
            "camera_yaw_deg": int(td.azimuth), "correct": td.fault is None, "faults": faults,
            "follower": f"followers/{td.take_id}/skeleton.json",
            "input": f"followers/{td.take_id}/input/pose3d.json"}


def labels_doc(defs, measured=None):
    """The `labels.json` document; `measured` is {take_id: size in the fault's unit} once the kit is built."""
    return {"format": LABELS_FORMAT, "generator": "python3 -m part3.conformance build", "seed": synth.SEED,
            "angles": {name: int(azimuth) for name, azimuth, _, _ in ANGLES},
            "takes": [take_label(td, measured) for td in defs]}


def measured_sizes(td, skeleton, reference):
    """(size on the labelled side(s) as written to the label, {side: size}) of a fault take's native output."""
    by_side = sizes(td.fault, skeleton, reference)
    labelled = [by_side[name] for name, _ in sides(td.side)]
    return io.round_clean(float(np.mean(labelled)), DECIMALS), by_side
