"""Canonical 17 joints (subject's left/right, README order) and where they sit in model outputs."""

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
