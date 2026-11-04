"""Canonical 17 joints (subject's left/right, README order), the optional foot points (TICKET-043) and where they
sit in model outputs."""

CANONICAL = [
    "nose", "left_eye", "right_eye", "left_ear", "right_ear",
    "left_shoulder", "right_shoulder", "left_elbow", "right_elbow", "left_wrist", "right_wrist",
    "left_hip", "right_hip", "left_knee", "right_knee", "left_ankle", "right_ankle",
]

# SAM 3D Body's 70 keypoints (sam_3d_body/metadata/mhr70.py): 0-14 are COCO-like but without
# wrists, which come from the hand chains.
MHR70 = {
    "nose": 0, "left_eye": 1, "right_eye": 2, "left_ear": 3, "right_ear": 4,
    "left_shoulder": 5, "right_shoulder": 6, "left_elbow": 7, "right_elbow": 8,
    "left_hip": 9, "right_hip": 10, "left_knee": 11, "right_knee": 12,
    "left_ankle": 13, "right_ankle": 14, "right_wrist": 41, "left_wrist": 62,
}
MHR70_INDEX = [MHR70[name] for name in CANONICAL]

# TICKET-043: the six foot points of pose3d.json's optional per-person `extra_joints` object (never inside
# `joints`, whose 17 names Part 3's schema fixes), in the order a writer emits them.
EXTRA = ["left_big_toe", "left_small_toe", "left_heel", "right_big_toe", "right_small_toe", "right_heel"]
# MHR70 15 to 20: left-big-toe-tip, left-small-toe-tip, left-heel, right-big-toe-tip, right-small-toe-tip, right-heel.
MHR70_EXTRA = {"left_big_toe": 15, "left_small_toe": 16, "left_heel": 17,
               "right_big_toe": 18, "right_small_toe": 19, "right_heel": 20}
MHR70_EXTRA_INDEX = [MHR70_EXTRA[name] for name in EXTRA]
# The ankle each foot point belongs to: a step that moves the ankles moves the foot points with them.
EXTRA_ANKLE = {name: name.split("_")[0] + "_ankle" for name in EXTRA}

# Skeleton edges for drawing.
BONES = [
    ("left_ear", "left_eye"), ("left_eye", "nose"), ("nose", "right_eye"), ("right_eye", "right_ear"),
    ("left_shoulder", "right_shoulder"), ("left_shoulder", "left_elbow"), ("left_elbow", "left_wrist"),
    ("right_shoulder", "right_elbow"), ("right_elbow", "right_wrist"),
    ("left_shoulder", "left_hip"), ("right_shoulder", "right_hip"), ("left_hip", "right_hip"),
    ("left_hip", "left_knee"), ("left_knee", "left_ankle"), ("right_hip", "right_knee"), ("right_knee", "right_ankle"),
]


def follow_ankles(extra: dict, before: dict, after: dict) -> dict:
    """Foot points {name: [x, y, z]} moved rigidly with their ankles: each point shifts by its own ankle's
    displacement from `before` to `after` ({joint: [x, y, z]}, all in one space). TICKET-043."""
    return {name: [p + a - b for p, a, b in zip(xyz, after[EXTRA_ANKLE[name]], before[EXTRA_ANKLE[name]])]
            for name, xyz in extra.items()}
