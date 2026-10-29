"""Canonical joints to highlight for one fault (`faults[].joints`).

ADR-0006: a fault names its joint three ways, a sided canonical joint (`left_elbow`), a side-stripped
one for side `both` (`elbow`), or a virtual one for a centre measure (`spine`, `shoulders`, `neck`).
`fault_joints` turns any of them into names from the 17 in `part5.io.JOINTS`, so a viewer or Part 7
highlights without knowing the measure names. The result is never empty.
"""
from .io import JOINTS

SIDES = ("left", "right")
# Side-stripped names of the paired joints: shoulder, elbow, wrist, hip, knee, ankle, eye, ear.
PAIRED = tuple(j[len("left_"):] for j in JOINTS if j.startswith("left_"))

# Virtual joints and what they stand for (ADR-0006). `shoulder_mid`, `hip_mid` and `head` are the
# same ideas under the names the integration contract uses for the body centre.
_SHOULDERS = ("left_shoulder", "right_shoulder")
_HIPS = ("left_hip", "right_hip")
VIRTUAL = {
    "spine": _SHOULDERS + _HIPS,
    "shoulders": _SHOULDERS,
    "shoulder_mid": _SHOULDERS,
    "hip_mid": _HIPS,
    "neck": ("nose",) + _SHOULDERS,
    "head": ("nose",) + _SHOULDERS,
}


def _paired(base, side):
    if side == "both":
        return [f"left_{base}", f"right_{base}"]
    return [f"{side}_{base}"]


def fault_joints(fault):
    """The canonical joint names to highlight for `fault` (a dict with `joint` and `side`).

    A sided joint is itself, except that side `both` gives its left and right pair. A side-stripped
    joint takes the fault's side. A virtual joint expands as in `VIRTUAL`. A joint the mapping does
    not know raises ValueError, so an unmapped fault is loud rather than highlighting nothing.
    """
    joint, side = fault.get("joint"), fault.get("side")
    if joint in VIRTUAL:
        return list(VIRTUAL[joint])
    if joint in JOINTS:
        sided = joint.startswith(("left_", "right_"))
        if sided and side == "both":
            return _paired(joint.split("_", 1)[1], "both")
        return [joint]
    if joint in PAIRED and side in SIDES + ("both",):
        return _paired(joint, side)
    raise ValueError(f"no canonical joints for joint {joint!r} with side {side!r} "
                     f"(measure {fault.get('measure')!r})")
