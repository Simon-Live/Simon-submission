"""The 9 joint angles of a skeleton.json (spec part3-skeleton.md "Phase alignment", Angles)."""

import numpy as np

from part3.geometry import angle_between, interior_angle, point
from part3.joints import INDEX, JOINTS, N_JOINTS, NECK, ROOT

# (joint, A, C): the interior angle at `joint` of (A, joint, C), same side.
_TRIPLETS = (
    ("elbow", "shoulder", "wrist"),
    ("shoulder", "elbow", "hip"),
    ("hip", "shoulder", "knee"),
    ("knee", "hip", "ankle"),
)
ANGLE_NAMES = tuple(f"{side}_{joint}" for joint, _, _ in _TRIPLETS for side in ("left", "right")) + (
    "trunk_inclination",
)
N_ANGLES = len(ANGLE_NAMES)
_UP = np.array([0.0, 1.0, 0.0])


def joints_array(doc, person_index=0):
    """(n, 17, 3) joint positions of one person per frame; NaN for frames without that person."""
    frames = doc["frames"]
    out = np.full((len(frames), N_JOINTS, 3), np.nan)
    for i, frame in enumerate(frames):
        people = frame["people"]
        if person_index < len(people):
            joints = people[person_index]["joints"]
            out[i] = [[joints[name][axis] for axis in "xyz"] for name in JOINTS]
    return out


def joint_angles(skeleton):
    """(n_frames, 9) angles in degrees in `ANGLE_NAMES` order; NaN rows for frames without a person."""
    J = joints_array(skeleton)
    columns = []
    for joint, a, c in _TRIPLETS:
        for side in ("left", "right"):
            columns.append(interior_angle(
                J[:, INDEX[f"{side}_{a}"]], J[:, INDEX[f"{side}_{joint}"]], J[:, INDEX[f"{side}_{c}"]]))
    trunk = point(J, NECK) - point(J, ROOT)
    columns.append(angle_between(trunk, _UP))
    return np.stack(columns, axis=-1)
