"""Bone lengths and retargeting on the 18-bone tree (spec step 6)."""

import numpy as np

from part3.geometry import normalize, point
from part3.joints import BONE_NAMES, BONES, INDEX, NECK, ROOT


def measure(J):
    """(..., 18) bone lengths in contract order for frames J (..., 17, 3)."""
    J = np.asarray(J, dtype=float)
    return np.stack([np.linalg.norm(point(J, b) - point(J, a), axis=-1) for _, a, b in BONES], axis=-1)


def lengths_array(lengths):
    """A {bone: metres} dict, (18,) or (n, 18) array as an array in contract order."""
    if isinstance(lengths, dict):
        return np.array([lengths[name] for name in BONE_NAMES], dtype=float)
    return np.asarray(lengths, dtype=float)


def retarget(J, lengths):
    """Rebuild frames J (n, 17, 3) from the hip midpoint outward with the given bone lengths.

    Every bone keeps its input unit direction and takes its new length. `lengths` is a dict, an
    (18,) array or an (n, 18) array (per-frame lengths). The hip midpoint stays where it is; since
    the pelvis and clavicle pairs point in opposite directions from their midpoint, `root` and `neck`
    stay the midpoints of the rebuilt hips and shoulders.

    A bone whose two input joints coincide has no direction (`normalize` gives the zero vector), so
    that bone is rebuilt with length 0 and its child sits on its parent in that frame; the length is
    not kept. Coincident hips cannot reach this (`person.hips_apart` drops those frames); any other
    joint exactly on its parent is not guarded.
    """
    J = np.asarray(J, dtype=float)
    L = np.broadcast_to(lengths_array(lengths), J.shape[:-2] + (len(BONES),))
    old = {ROOT: point(J, ROOT), NECK: point(J, NECK)}
    new = {ROOT: old[ROOT]}
    out = np.array(J, copy=True)
    for k, (_, a, b) in enumerate(BONES):
        src_old = old[a] if a in old else J[..., INDEX[a], :]
        dst_old = old[b] if b in old else J[..., INDEX[b], :]
        new[b] = new[a] + L[..., k, None] * normalize(dst_old - src_old)
        if b != NECK:
            out[..., INDEX[b], :] = new[b]
    return out
