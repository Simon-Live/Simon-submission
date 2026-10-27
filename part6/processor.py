"""The processor seam: the only module that produces keyframes, skeleton and animation.

`process(recording)` is the one function the server calls. This mock implementation generates
valid synthetic shared files (docs/specs/shared-files.md sections 1 to 3), varied by a seed taken
from the recording id. The real video to frames to 3D to animation processor replaces this module
and touches nothing else. `generate` is the shared core that `fixtures/make_catalog.py` also uses
with fixed parameters.
"""
from __future__ import annotations

import hashlib
import json
import math
import random

from . import motion

ANIMATION_FPS = 30.0
SKELETON_FPS = 15.0
UNITS = {"length": "m", "angle": "deg", "time": "ms"}
FRAME = {"origin": "hip_midpoint", "x": "subject_left", "y": "body_up", "z": "anterior",
         "up_source": "standing_frames"}
# Part 3's 18-bone tree; `root` (hip midpoint) and `neck` (shoulder midpoint) are virtual joints.
TREE_BONES = (
    ("left_pelvis", "root", "left_hip"), ("right_pelvis", "root", "right_hip"),
    ("left_thigh", "left_hip", "left_knee"), ("right_thigh", "right_hip", "right_knee"),
    ("left_shank", "left_knee", "left_ankle"), ("right_shank", "right_knee", "right_ankle"),
    ("spine", "root", "neck"),
    ("left_clavicle", "neck", "left_shoulder"), ("right_clavicle", "neck", "right_shoulder"),
    ("left_upper_arm", "left_shoulder", "left_elbow"),
    ("right_upper_arm", "right_shoulder", "right_elbow"),
    ("left_forearm", "left_elbow", "left_wrist"), ("right_forearm", "right_elbow", "right_wrist"),
    ("head", "neck", "nose"),
    ("left_eye_link", "nose", "left_eye"), ("right_eye_link", "nose", "right_eye"),
    ("left_ear_link", "left_eye", "left_ear"), ("right_ear_link", "right_eye", "right_ear"),
)


def seed_from_id(entry_id):
    return int(hashlib.sha256(entry_id.encode("utf-8")).hexdigest()[:8], 16)


def frame_counts(duration_ms):
    """(animation frames, skeleton frames): 30 fps and half that rounded up."""
    animation = max(30, round(duration_ms * 30 / 1000))
    return animation, math.ceil(animation / 2)


def mock_params(seed, category, duration_ms):
    """(family id, MotionParams) drawn from the seed; repetitions split the duration equally."""
    rng = random.Random(seed)
    family = rng.choice(motion.by_category(category))
    tempo = rng.uniform(0.8, 1.25)
    depth, arm, step = (rng.uniform(0.7, 1.0) for _ in range(3))
    seconds = duration_ms / 1000
    period = min(family.base_period_s * tempo, seconds)
    reps = max(1, math.floor(seconds / period))
    return family.id, motion.MotionParams(seconds / reps, reps, 0.0, depth, arm, step)


def _animation_frames(family_id, params, count):
    frames = []
    for i in range(count):
        t = i / ANIMATION_FPS
        frames.append({"frame": i, "t_ms": round(t * 1000, 3), "interpolated": i % 2 != 0,
                       "people": [{"id": 0, "joints": motion.pose(family_id, t, params)}]})
    return frames


def _virtual_point(joints, name):
    if name in ("root", "neck"):
        a, b = (("left_hip", "right_hip") if name == "root"
                else ("left_shoulder", "right_shoulder"))
        return tuple((joints[a][k] + joints[b][k]) / 2 for k in "xyz")
    return tuple(joints[name][k] for k in "xyz")


def _bone_lengths(joints):
    return {name: round(math.dist(_virtual_point(joints, a), _virtual_point(joints, b)), 4)
            for name, a, b in TREE_BONES}


def _skeleton(animation_frames, count):
    raw = []
    for j in range(count):
        joints = animation_frames[2 * j]["people"][0]["joints"]
        raw.append({"frame": j, "t_ms": round(j / SKELETON_FPS * 1000, 3),
                    "people": [{"id": 0, "joints": joints}]})
    lengths = _bone_lengths(raw[0]["people"][0]["joints"])
    digest = hashlib.sha256((json.dumps({"frames": raw}, separators=(",", ":")) + "\n").encode())
    frames = [{"frame": f["frame"], "t_ms": f["t_ms"],
               "people": [dict(p, flips_repaired=[]) for p in f["people"]]} for f in raw]
    return {
        "schema": "simon.skeleton/1", "units": UNITS, "frame": FRAME,
        "joints": list(motion.JOINTS),
        "bones": [{"name": n, "from": a, "to": b} for n, a, b in TREE_BONES],
        "standard": {"stature_m": 1.70,
                     "sources": ["synthetic Part 6 fixture body; not a measured standard"]},
        "bone_lengths_m": lengths,
        "person": {"id": 0, "rule": "most_frames", "candidates": {"0": len(raw)},
                   "frames_present": len(raw), "frames_dropped": 0, "few_frames": False,
                   "measured_bone_lengths_m": lengths,
                   "flips_repaired_total": {"body": 0, "legs": 0, "arms": 0, "face": 0}},
        "mirror": {"setting": "auto", "applied": False, "reason": "no mirrored hint in input"},
        "input": {"sha256": digest.hexdigest()},
        "frames": frames,
    }


def _keyframes(family_id, params, frame_count):
    """Marks at the start, middle and end of each repetition (docs/specs "Key frame marks")."""
    names = motion.FAMILIES[family_id].marks
    reps = []
    for k in range(params.reps):
        marks = []
        for name, share in zip(names, (0.0, 0.5, 1.0)):
            t_ms = round((params.start_s + (k + share) * params.period_s) * 1000)
            marks.append({"name": name, "frame": min(round(t_ms * 30 / 1000), frame_count - 1),
                          "t_ms": t_ms})
        reps.append({"rep": k + 1, "movement": family_id, "keyframes": marks})
    return {"video": None, "fps": ANIMATION_FPS, "analysis_fps": ANIMATION_FPS,
            "quality": {"verdict": "fine"}, "people": [{"id": 0, "repetitions": reps}]}


def generate(family_id, duration_ms, params):
    """keyframes, skeleton and animation of one synthetic movement."""
    count, skeleton_count = frame_counts(duration_ms)
    frames = _animation_frames(family_id, params, count)
    animation = {"schema": "simon.animation/1", "units": UNITS, "frame": FRAME,
                 "joints": list(motion.JOINTS), "fps": ANIMATION_FPS, "frames": frames}
    return {"keyframes": _keyframes(family_id, params, count),
            "skeleton": _skeleton(frames, skeleton_count), "animation": animation}


def process(recording):
    """Mock processor: `recording` is {id, name, category, duration_ms, video_path}.

    `video_path` is None while capture is mocked and is never read. Returns
    {"keyframes": ..., "skeleton": ..., "animation": ...}.
    """
    category, duration_ms = recording["category"], recording["duration_ms"]
    if category not in motion.CATEGORIES:
        raise ValueError(f"unknown category: {category!r}")
    if isinstance(duration_ms, bool) or not isinstance(duration_ms, int) or duration_ms <= 0:
        raise ValueError(f"duration_ms must be a positive integer: {duration_ms!r}")
    family_id, params = mock_params(seed_from_id(recording["id"]), category, duration_ms)
    return generate(family_id, duration_ms, params)
