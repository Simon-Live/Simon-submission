"""Which way a fault points in the subject's own frame, and how far the foot moved (ADR-0009).

`lateral_for` is the table of docs/specs/journey-followup.md J-2; `lateral_m` is the foot offset
in metres. Both read the subject's left and right, the same frame as `side`.
"""
import numpy as np

from .io import JOINTS

OUT_MEASURES = ("foot_out", "thigh_out", "upper_arm_out", "forearm_out")
OTHER = {"left": "right", "right": "left"}


def lateral_for(measure, direction, side):
    """`"left"`, `"right"` or None for one fault."""
    if measure == "trunk_lean_side":
        return {"more": "left", "less": "right"}.get(direction) if side == "center" else None
    if side not in OTHER:
        return None
    if measure in OUT_MEASURES:
        return side if direction == "more" else OTHER[side]
    if measure == "knee_valgus":
        return OTHER[side] if direction == "more" else side
    return None


def lateral_m(fault, exp_positions, fol_positions, exp_to_fol):
    """Median over the counted runs of |x_follower| - |x_expected| at the fault's ankle, in metres
    (2 decimals; positive is further out). None unless a `foot_out` fault on one side."""
    if fault.measure != "foot_out" or fault.side not in OTHER:
        return None
    j = JOINTS.index(f"{fault.side}_ankle")
    diffs = []
    for s, e in fault.runs:
        idx = np.arange(s, e + 1)
        fol = np.asarray(fol_positions)[np.asarray(exp_to_fol)[idx], j, 0]
        exp = np.asarray(exp_positions)[idx, j, 0]
        diffs.append(np.abs(fol) - np.abs(exp))
    d = np.concatenate(diffs)
    d = d[np.isfinite(d)]
    return round(float(np.median(d)), 2) if len(d) else None
