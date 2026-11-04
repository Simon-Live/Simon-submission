"""Write the Part 6 input fixtures: keyframes.json, skeleton.json, animation.json.

A procedural 10 s squat (3 repetitions) of one person, built with fixed bone lengths so the
files look like what Parts 1, 3 and 4 publish. Synthetic: no recording or model produced it.
skeleton.json follows Part 3's published output contract (schema simon.skeleton/1); animation.json
is the provisional Part 4 shape Part 6 defines (schema simon.animation/1). Shapes and frame are
specified in docs/specs/shared-files.md (firm layer) and README.md here.

Run: python3 fixtures/input/make_fixtures.py   (deterministic; rewrites the three files)
"""
import hashlib
import json
import math
from pathlib import Path

OUT = Path(__file__).resolve().parent
VIDEO_FPS = 30.0
SKELETON_FPS = 15.0
ANIMATION_FPS = 30.0
DURATION_S = 10.0
REP_STARTS_S = (0.5, 3.5, 6.5)
REP_PERIOD_S = 3.0

JOINTS = [
    "nose", "left_eye", "right_eye", "left_ear", "right_ear",
    "left_shoulder", "right_shoulder", "left_elbow", "right_elbow", "left_wrist", "right_wrist",
    "left_hip", "right_hip", "left_knee", "right_knee", "left_ankle", "right_ankle",
]
# Part 3's 18-bone tree: `root` (hip midpoint) and `neck` (shoulder midpoint) are virtual joints.
# Names and order match Part 3's contract; lengths are this fixture's synthetic body.
# Readers key on `bones[].from/to`, never on the names.
TREE_BONES = [
    ("left_pelvis", "root", "left_hip"), ("right_pelvis", "root", "right_hip"),
    ("left_thigh", "left_hip", "left_knee"), ("right_thigh", "right_hip", "right_knee"),
    ("left_shank", "left_knee", "left_ankle"), ("right_shank", "right_knee", "right_ankle"),
    ("spine", "root", "neck"),
    ("left_clavicle", "neck", "left_shoulder"), ("right_clavicle", "neck", "right_shoulder"),
    ("left_upper_arm", "left_shoulder", "left_elbow"), ("right_upper_arm", "right_shoulder", "right_elbow"),
    ("left_forearm", "left_elbow", "left_wrist"), ("right_forearm", "right_elbow", "right_wrist"),
    ("head", "neck", "nose"),
    ("left_eye_link", "nose", "left_eye"), ("right_eye_link", "nose", "right_eye"),
    ("left_ear_link", "left_eye", "left_ear"), ("right_ear_link", "right_eye", "right_ear"),
]
UNITS = {"length": "m", "angle": "deg", "time": "ms"}
FRAME = {"origin": "hip_midpoint", "x": "subject_left", "y": "body_up", "z": "anterior",
         "up_source": "standing_frames"}
HIP_HALF, SHOULDER_HALF = 0.09, 0.19
THIGH, SHANK, TRUNK, UPPER_ARM, FOREARM = 0.43, 0.42, 0.50, 0.29, 0.26


def depth(t):
    """Squat depth 0 (standing) to 1 (bottom) at time t seconds."""
    for t0 in REP_STARTS_S:
        if t0 <= t <= t0 + REP_PERIOD_S:
            return 0.5 * (1 - math.cos(2 * math.pi * (t - t0) / REP_PERIOD_S))
    return 0.0


def add(a, b, k=1.0):
    return tuple(a[i] + k * b[i] for i in range(3))


def pose(t):
    """17 joints in the shared frame: origin hip midpoint, x subject's left, y up, z anterior."""
    s = depth(t)
    hip_flex, shank_lean, trunk_lean, arm_raise = 1.35 * s, 0.6 * s, 0.7 * s, 0.1 + 1.4 * s
    j = {}
    for side, sx in (("left", 1.0), ("right", -1.0)):
        hip = (sx * HIP_HALF, 0.0, 0.0)
        knee = add(hip, (0.0, -math.cos(hip_flex), math.sin(hip_flex)), THIGH)
        ankle = add(knee, (0.0, -math.cos(shank_lean), -math.sin(shank_lean)), SHANK)
        up = (0.0, math.cos(trunk_lean), math.sin(trunk_lean))
        shoulder = add((sx * SHOULDER_HALF, 0.0, 0.0), up, TRUNK)
        arm_dir = (0.0, -math.cos(arm_raise), math.sin(arm_raise))
        elbow = add(shoulder, arm_dir, UPPER_ARM)
        wrist = add(elbow, arm_dir, FOREARM)
        j.update({f"{side}_hip": hip, f"{side}_knee": knee, f"{side}_ankle": ankle,
                  f"{side}_shoulder": shoulder, f"{side}_elbow": elbow, f"{side}_wrist": wrist})
    up = (0.0, math.cos(trunk_lean), math.sin(trunk_lean))
    fwd = (0.0, -math.sin(trunk_lean), math.cos(trunk_lean))
    head = add((0.0, 0.0, 0.0), up, TRUNK + 0.25)
    j["nose"] = add(head, fwd, 0.10)
    for side, sx in (("left", 1.0), ("right", -1.0)):
        eye = add(add(head, up, 0.04), fwd, 0.08)
        j[f"{side}_eye"] = (eye[0] + sx * 0.03, eye[1], eye[2])
        ear = add(head, up, 0.02)
        j[f"{side}_ear"] = (ear[0] + sx * 0.075, ear[1], ear[2])
    return {name: {"x": round(j[name][0], 4), "y": round(j[name][1], 4),
                   "z": round(j[name][2], 4), "conf": 1.0} for name in JOINTS}


def frames(fps, interpolated_every=None):
    out = []
    for i in range(int(DURATION_S * fps)):
        t = i / fps
        frame = {"frame": i, "t_ms": round(t * 1000, 3)}
        if interpolated_every:
            frame["interpolated"] = i % interpolated_every != 0
        frame["people"] = [{"id": 0, "joints": pose(t)}]
        out.append(frame)
    return out


def point(joints, name):
    """A joint or one of Part 3's virtual joints (root: hip midpoint, neck: shoulder midpoint)."""
    if name in ("root", "neck"):
        a, b = ("left_hip", "right_hip") if name == "root" else ("left_shoulder", "right_shoulder")
        return tuple((joints[a][k] + joints[b][k]) / 2 for k in "xyz")
    return tuple(joints[name][k] for k in "xyz")


def bone_lengths(frame):
    joints = frame["people"][0]["joints"]
    return {name: round(math.dist(point(joints, a), point(joints, b)), 4) for name, a, b in TREE_BONES}


def skeleton(raw_frames):
    """Part 3's skeleton.json contract (simon.skeleton/1) around the synthetic frames."""
    lengths = bone_lengths(raw_frames[0])
    pose3d_bytes = (json.dumps({"frames": raw_frames}, separators=(",", ":")) + "\n").encode()
    frames_out = [{"frame": f["frame"], "t_ms": f["t_ms"],
                   "people": [dict(p, flips_repaired=[]) for p in f["people"]]} for f in raw_frames]
    return {
        "schema": "simon.skeleton/1",
        "units": UNITS,
        "frame": FRAME,
        "joints": JOINTS,
        "bones": [{"name": n, "from": a, "to": b} for n, a, b in TREE_BONES],
        "standard": {"stature_m": 1.70,
                     "sources": ["synthetic Part 6 fixture body; not a measured standard"]},
        "bone_lengths_m": lengths,
        "person": {"id": 0, "rule": "most_frames", "candidates": {"0": len(raw_frames)},
                   "frames_present": len(raw_frames), "frames_dropped": 0, "few_frames": False,
                   "measured_bone_lengths_m": lengths,
                   "flips_repaired_total": {"body": 0, "legs": 0, "arms": 0, "face": 0}},
        "mirror": {"setting": "auto", "applied": False, "reason": "no mirrored hint in input"},
        "input": {"sha256": hashlib.sha256(pose3d_bytes).hexdigest()},
        "frames": frames_out,
    }


def animation(raw_frames, fps):
    """Provisional Part 4 shape (simon.animation/1): the skeleton's conventions, frames at fps."""
    return {"schema": "simon.animation/1", "units": UNITS, "frame": FRAME, "joints": JOINTS,
            "fps": fps, "frames": raw_frames}


def keyframes():
    reps = []
    for n, t0 in enumerate(REP_STARTS_S, start=1):
        marks = (("start", t0), ("bottom", t0 + REP_PERIOD_S / 2), ("top", t0 + REP_PERIOD_S))
        reps.append({"rep": n, "movement": "squat", "keyframes": [
            {"name": name, "frame": round(t * VIDEO_FPS), "t_ms": round(t * 1000)} for name, t in marks]})
    return {
        "video": "video.webm", "fps": VIDEO_FPS, "analysis_fps": 8.0,
        "quality": {"verdict": "fine", "brightness": 150.0, "spread": 220.0, "blur": 5.0,
                    "motion": 3.0, "near_black": 0.0, "noise": 0.4, "flicker": 1.0,
                    "analysis_width": 640, "filters": []},
        "people": [{"id": 0, "repetitions": reps}],
    }


def main():
    skel = skeleton(frames(SKELETON_FPS))
    anim = animation(frames(ANIMATION_FPS, interpolated_every=2), ANIMATION_FPS)
    for name, data in (("keyframes.json", keyframes()), ("skeleton.json", skel),
                       ("animation.json", anim)):
        (OUT / name).write_text(json.dumps(data, separators=(",", ":")) + "\n")


if __name__ == "__main__":
    main()
