"""Canonical joints, left/right pairs, flip groups and the bone tree (spec part3-skeleton.md)."""

JOINTS = (
    "nose", "left_eye", "right_eye", "left_ear", "right_ear",
    "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
    "left_wrist", "right_wrist", "left_hip", "right_hip",
    "left_knee", "right_knee", "left_ankle", "right_ankle",
)
INDEX = {name: i for i, name in enumerate(JOINTS)}
N_JOINTS = len(JOINTS)

# Left/right pairs as (left, right) joint names.
PAIRS = (
    ("left_eye", "right_eye"), ("left_ear", "right_ear"),
    ("left_shoulder", "right_shoulder"), ("left_elbow", "right_elbow"),
    ("left_wrist", "right_wrist"), ("left_hip", "right_hip"),
    ("left_knee", "right_knee"), ("left_ankle", "right_ankle"),
)

# Flip-repair groups (spec step 4, locked): the pairs each group swaps.
GROUPS = {
    "legs": (("left_knee", "right_knee"), ("left_ankle", "right_ankle")),
    "arms": (("left_elbow", "right_elbow"), ("left_wrist", "right_wrist")),
    "face": (("left_eye", "right_eye"), ("left_ear", "right_ear")),
    "body": PAIRS,
}
GROUP_ORDER = ("body", "legs", "arms", "face")

# The coordinate_frame block Part 4 and Part 5 read (the part4 and part5 views write it; doctor checks it).
COORDINATE_FRAME = {"origin": "hip_midpoint", "x": "subject_left", "y": "world_up", "z": "anterior",
                    "position_unit": "metres", "angle_unit": "degrees"}

# Virtual joints: root = hip midpoint, neck = shoulder midpoint.
ROOT = "root"
NECK = "neck"

# The 18 bones in contract order: (name, from, to).
BONES = (
    ("left_pelvis", ROOT, "left_hip"),
    ("right_pelvis", ROOT, "right_hip"),
    ("left_thigh", "left_hip", "left_knee"),
    ("right_thigh", "right_hip", "right_knee"),
    ("left_shank", "left_knee", "left_ankle"),
    ("right_shank", "right_knee", "right_ankle"),
    ("spine", ROOT, NECK),
    ("left_clavicle", NECK, "left_shoulder"),
    ("right_clavicle", NECK, "right_shoulder"),
    ("left_upper_arm", "left_shoulder", "left_elbow"),
    ("right_upper_arm", "right_shoulder", "right_elbow"),
    ("left_forearm", "left_elbow", "left_wrist"),
    ("right_forearm", "right_elbow", "right_wrist"),
    ("head", NECK, "nose"),
    ("left_eye_link", "nose", "left_eye"),
    ("right_eye_link", "nose", "right_eye"),
    ("left_ear_link", "left_eye", "left_ear"),
    ("right_ear_link", "right_eye", "right_ear"),
)
BONE_NAMES = tuple(b[0] for b in BONES)


def swap_index(pairs=PAIRS):
    """Joint index permutation that swaps the given left/right pairs."""
    perm = list(range(N_JOINTS))
    for left, right in pairs:
        a, b = INDEX[left], INDEX[right]
        perm[a], perm[b] = b, a
    return perm


def bone_index(name):
    """Joint index for a bone endpoint; -1 for root, -2 for neck."""
    if name == ROOT:
        return -1
    if name == NECK:
        return -2
    return INDEX[name]
