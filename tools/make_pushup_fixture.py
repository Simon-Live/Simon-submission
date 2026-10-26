#!/usr/bin/env python3
"""Generate fixtures/pushup.movement.json: synthetic push-up, 2 reps (tucked, then flared).

Physically plausible on purpose: hands and feet stay on the floor, the body
pivots at the ankles as a rigid plank, and the elbows bend. Rep 1 keeps the
elbows tucked; rep 2 flares them, so the elbow_flare rule can be checked
against the fixture (fires on rep 2 only).

    python3 tools/make_pushup_fixture.py
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from measures import add, frontal_angle, norm, scale, sub, unit, dot  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "fixtures/pushup.movement.json"

FPS = 30
PHASE_FRAMES = [("descend", 30), ("bottom_pause", 15), ("ascend", 30), ("top", 15)]
REP_ELBOW_DIRECTION_DEG = [25, 80]  # bend direction: 0 = toward the hips (tucked), 90 = straight out (flared)

# World frame = schema frame before re-centring: x = subject's left, y = up, z = toward the head (prone).
ANKLE_HEIGHT, ANKLE_TO_HIP, ANKLE_TO_SHOULDER = 0.08, 0.88, 1.40
SHOULDER_TOP, SHOULDER_BOTTOM = 0.55, 0.14
HALF_SHOULDER, HALF_HIP, HALF_ANKLE, HALF_HANDS = 0.19, 0.10, 0.11, 0.24
UPPER_ARM, FOREARM = 0.30, 0.27


def shoulder_mid(height: float) -> tuple:
    return (0.0, height, math.sqrt(ANKLE_TO_SHOULDER**2 - (height - ANKLE_HEIGHT) ** 2))


def elbow(shoulder: tuple, wrist: tuple, side: float, direction_deg: float) -> tuple:
    """Two-link IK: elbow on the circle of solutions, bent toward caudal/lateral per direction_deg."""
    sw = sub(wrist, shoulder)
    d = norm(sw)
    axis = unit(sw)
    along = (UPPER_ARM**2 - FOREARM**2 + d**2) / (2 * d)
    radius = math.sqrt(max(UPPER_ARM**2 - along**2, 0.0))
    phi = math.radians(direction_deg)
    want = (side * math.sin(phi), 0.0, -math.cos(phi))  # lateral (outward) + caudal (toward feet)
    bend = unit(sub(want, scale(axis, dot(want, axis))))
    return add(add(shoulder, scale(axis, along)), scale(bend, radius))


def pose(height: float, direction_deg: float, wrist_z: float) -> dict:
    s_mid = shoulder_mid(height)
    body = unit(sub(s_mid, (0.0, ANKLE_HEIGHT, 0.0)))  # ankles -> shoulders
    ankle_mid = (0.0, ANKLE_HEIGHT, 0.0)
    hip_mid = add(ankle_mid, scale(body, ANKLE_TO_HIP))
    knee_mid = add(ankle_mid, scale(body, 0.45))
    face_down = unit(sub((0.0, -1.0, 0.0), scale(body, dot((0.0, -1.0, 0.0), body))))
    nose = add(add(s_mid, scale(body, 0.24)), scale(face_down, 0.10))
    p = {"nose": nose}
    for side, name in ((1.0, "left"), (-1.0, "right")):
        lat = (side, 0.0, 0.0)
        shoulder = add(s_mid, scale(lat, HALF_SHOULDER))
        wrist = (side * HALF_HANDS, 0.02, wrist_z)
        p[f"{name}_eye"] = add(add(nose, scale(lat, 0.03)), scale(body, -0.02))
        p[f"{name}_ear"] = add(add(add(nose, scale(lat, 0.07)), scale(body, -0.06)), scale(face_down, -0.04))
        p[f"{name}_shoulder"] = shoulder
        p[f"{name}_elbow"] = elbow(shoulder, wrist, side, direction_deg)
        p[f"{name}_wrist"] = wrist
        p[f"{name}_hip"] = add(hip_mid, scale(lat, HALF_HIP))
        p[f"{name}_knee"] = add(knee_mid, scale(lat, HALF_ANKLE))
        p[f"{name}_ankle"] = add(ankle_mid, scale(lat, HALF_ANKLE))
    return {k: add(v, scale(hip_mid, -1.0)) for k, v in p.items()}  # re-centre on the hip midpoint


def height_at(phase: str, i: int, n: int) -> float:
    ease = (1 - math.cos(math.pi * i / (n - 1))) / 2
    return {
        "descend": SHOULDER_TOP + (SHOULDER_BOTTOM - SHOULDER_TOP) * ease,
        "bottom_pause": SHOULDER_BOTTOM,
        "ascend": SHOULDER_BOTTOM + (SHOULDER_TOP - SHOULDER_BOTTOM) * ease,
        "top": SHOULDER_TOP,
    }[phase]


JOINT_NAMES = ["nose", "left_eye", "right_eye", "left_ear", "right_ear",
               "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
               "left_wrist", "right_wrist", "left_hip", "right_hip",
               "left_knee", "right_knee", "left_ankle", "right_ankle"]

BASELINE_RULE = {
    "id": "shape_match",
    "cue_text": "match the reference shape",
    "phases": ["descend", "bottom_pause", "ascend", "top"],
    "side": "as_written",
    "measure": {"type": "pose_similarity", "joints": ["nose", "left_eye", "right_eye", "left_ear", "right_ear",
                "left_shoulder", "right_shoulder", "left_elbow", "right_elbow", "left_wrist", "right_wrist",
                "left_hip", "right_hip", "left_knee", "right_knee", "left_ankle", "right_ankle"]},
    "normal_range": [0, 6],
    "fault_when": {"operator": ">", "threshold": 8},
    "min_frames": 6,
    "joint_highlight": "right_elbow",
}

RULE = {
    "id": "elbow_flare",
    "cue_text": "elbows tucked",
    "phases": ["descend", "bottom_pause"],
    "side": "visible",
    "measure": {"type": "angle", "joints": ["right_shoulder", "right_elbow"],
                "plane": "frontal", "reference": "torso_caudal", "min_projected_ratio": 0.5},
    "normal_range": [15, 50],
    "fault_when": {"operator": ">", "threshold": 65},
    "min_frames": 6,
    "joint_highlight": "right_elbow",
}


def main() -> None:
    wrist_z = shoulder_mid(SHOULDER_TOP)[2]  # hands planted under the shoulders at the top
    frames, phases, frame = [], [], 0
    for rep, direction in enumerate(REP_ELBOW_DIRECTION_DEG, start=1):
        for name, n in PHASE_FRAMES:
            phases.append({"name": name, "rep": rep, "start_frame": frame, "end_frame": frame + n - 1,
                           "keyframe_frame": frame + (n - 1 if name in ("descend", "ascend") else n // 2)})
            for i in range(n):
                joints = pose(height_at(name, i, n), direction, wrist_z)
                frames.append({
                    "frame": frame, "t_ms": round(frame * 1000 / FPS), "interpolated": False,
                    "joints": {j: {"x": round(joints[j][0], 4), "y": round(joints[j][1], 4),
                                   "z": round(joints[j][2], 4), "conf": 0.95} for j in JOINT_NAMES},
                })
                frame += 1
    rep2_start = phases[len(PHASE_FRAMES)]["start_frame"]
    pkg = {
        "schema_version": "0.2.0",
        "movement": {"id": "pushup", "name": "Push-up", "primary_joint": "right_elbow",
                     "structure": "reps", "follower_mirrors": False},
        "coordinate_system": {
            "origin": "pelvis_midpoint_per_frame", "x_axis": "subject_left_horizontal", "y_axis": "world_up",
            "z_axis": "x_cross_y", "handedness": "right", "up_source": "synthetic",
            "length_unit": "m", "angle_unit": "deg",
        },
        "timing": {"fps": FPS, "time_base": "frame_index", "frame_count": len(frames)},
        "joint_names": JOINT_NAMES,
        "reference_motion": {"frames": frames, "bone_lengths_m": {"upper_arm": UPPER_ARM, "forearm": FOREARM}},
        "phases": phases,
        "instructions": [
            {"phase": "descend", "text": "Lower with elbows tucked."},
            {"phase": "bottom_pause", "text": "Pause at the bottom."},
            {"phase": "ascend", "text": "Press back up."},
            {"phase": "top", "text": "Reset at the top."},
        ],
        "cues": [
            {"id": "elbows_tucked", "text": "elbows tucked", "type": "cue", "phase": "descend", "t_ms": 0},
            {"id": "pause_bottom", "text": "pause at the bottom", "type": "cue", "phase": "bottom_pause", "t_ms": 1000},
            {"id": "elbow_flare", "text": "this is what flaring looks like", "type": "fault", "phase": "descend",
             "t_ms": round(rep2_start * 1000 / FPS), "demo_frames": [rep2_start, len(frames) - 1]},
        ],
        "rules": [RULE, BASELINE_RULE],
        "provenance": {
            "source": "synthetic push-up, rep 1 tucked, rep 2 flared (no video)",
            "generated_by": "tools/make_pushup_fixture.py",
            "created_at": "2026-10-26T09:00:00-07:00",
        },
        "quality": {"coverage": 1.0, "mean_confidence": 0.95, "flags": []},
    }
    OUT.write_text(json.dumps(pkg, indent=2) + "\n")
    print(f"wrote {OUT.relative_to(ROOT)}: {len(frames)} frames, {len(phases)} phase segments")
    for rep in (1, 2):
        values = [frontal_angle(f["joints"], "right_shoulder", "right_elbow", 0.5)
                  for f in frames for p in phases
                  if p["rep"] == rep and p["name"] in RULE["phases"] and p["start_frame"] <= f["frame"] <= p["end_frame"]]
        measured = [round(v) for v in values if v is not None]
        print(f"  rep {rep}: flare angle {min(measured)}-{max(measured)} deg over {len(measured)}/{len(values)} measurable frames")


if __name__ == "__main__":
    main()
