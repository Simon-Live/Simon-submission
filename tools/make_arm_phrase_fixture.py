#!/usr/bin/env python3
"""Generate fixtures/arm_phrase.movement.json: synthetic 8-count arm choreography at 120 bpm.

The non-exercise counterpart to the push-up fixture: structure "sequence",
timed to music, mirrored for the follower, with an asymmetric count (5) so a
wrong left/right mirror shows up. Pass 1 is clean; pass 2 bends the elbows on
counts 3-4, so the arms_straight rule fires on pass 2 only.

    python3 tools/make_arm_phrase_fixture.py
"""
from __future__ import annotations

import json
import math
import struct
import sys
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_pushup_fixture import JOINT_NAMES  # noqa: E402
from measures import add, scale, unit  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "fixtures/arm_phrase.movement.json"

FPS, BPM, COUNTS = 30, 120, 8
FRAMES_PER_COUNT = round(FPS * 60 / BPM)  # 15
UPPER_ARM, FOREARM = 0.30, 0.27

# Schema frame for a standing subject: x = subject's left, y = up, z = anterior.
DOWN, UP, FORWARD, OUT_R = (0, -1, 0), (0, 1, 0), (0, 0, 1), (-1, 0, 0)

# Per count: right arm (upper arm direction, forearm direction), left arm, both in the schema frame.
def sym(upper, fore):
    """Right-arm directions -> (right, left) with the left arm mirrored across the body."""
    flip = lambda v: (-v[0], v[1], v[2])
    return (upper, fore), (flip(upper), flip(fore))


KEY_POSES = {
    1: sym(DOWN, DOWN),
    2: sym(FORWARD, FORWARD),
    3: sym(OUT_R, OUT_R),
    4: sym(UP, UP),
    5: ((UP, UP), ((1, 0, 0), (1, 0, 0))),  # asymmetric: right arm up, left arm out
    6: sym(OUT_R, OUT_R),
    7: sym(FORWARD, UP),  # goalposts forward (bent elbows on purpose)
    8: sym(DOWN, DOWN),
}
# The demonstrated fault: forearms bent ~50 deg on counts 3-4 instead of long arms.
SOFT_ARMS = {
    3: sym(OUT_R, unit((-0.64, 0.77, 0.0))),  # out to the side, forearm lifting
    4: sym(UP, unit((0.0, 0.77, 0.64))),  # overhead, forearm tipping forward
}


def key_pose(count: int, soft_arms: bool):
    return SOFT_ARMS[count] if soft_arms and count in SOFT_ARMS else KEY_POSES[count]


def lerp_dir(a, b, t):
    return unit(add(scale(a, 1 - t), scale(b, t)))


def body(arms) -> dict:
    p = {"nose": (0.0, 0.70, 0.10)}
    for side, name, (upper, fore) in ((-1.0, "right", arms[0]), (1.0, "left", arms[1])):
        shoulder = (side * 0.19, 0.52, 0.0)
        elbow = add(shoulder, scale(upper, UPPER_ARM))
        p[f"{name}_eye"] = (side * 0.03, 0.74, 0.08)
        p[f"{name}_ear"] = (side * 0.07, 0.71, 0.0)
        p[f"{name}_shoulder"] = shoulder
        p[f"{name}_elbow"] = elbow
        p[f"{name}_wrist"] = add(elbow, scale(fore, FOREARM))
        p[f"{name}_hip"] = (side * 0.10, 0.0, 0.0)
        p[f"{name}_knee"] = (side * 0.10, -0.45, 0.02)
        p[f"{name}_ankle"] = (side * 0.10, -0.88, 0.0)
    return p


ARMS_STRAIGHT = {
    "id": "arms_straight",
    "cue_text": "long arms",
    "phases": ["count_3", "count_4"],
    "side": "either",
    "measure": {"type": "angle", "joints": ["right_shoulder", "right_elbow", "right_wrist"]},
    "normal_range": [165, 180],
    "fault_when": {"operator": "<", "threshold": 150},
    "min_frames": 6,
    "joint_highlight": "right_elbow",
}
BASELINE_RULE = {
    "id": "shape_match",
    "cue_text": "match the reference shape",
    "phases": [f"count_{c}" for c in range(1, COUNTS + 1)],
    "side": "as_written",
    "measure": {"type": "pose_similarity", "joints": ["nose", "left_eye", "right_eye", "left_ear", "right_ear",
                "left_shoulder", "right_shoulder", "left_elbow", "right_elbow", "left_wrist", "right_wrist",
                "left_hip", "right_hip", "left_knee", "right_knee", "left_ankle", "right_ankle"]},
    "normal_range": [0, 3],
    "fault_when": {"operator": ">", "threshold": 5},
    "min_frames": 6,
    "joint_highlight": "right_elbow",
}
ON_THE_BEAT = {
    "id": "on_the_beat",
    "cue_text": "hit it on the count",
    "phases": [f"count_{c}" for c in range(1, COUNTS + 1)],
    "side": "both",
    "measure": {"type": "timing", "joints": ["left_wrist", "right_wrist"]},
    "normal_range": [-80, 80],
    "fault_when": {"operator": "outside", "threshold": -150, "threshold_high": 150},
    "min_frames": 1,
    "joint_highlight": "right_wrist",
}


def write_metronome() -> None:
    """8 s of 120 bpm clicks at 8 kHz mono, referenced by the package's audio.uri."""
    sr, duration = 8000, 8.0
    out = ROOT / "fixtures/audio/metronome_120bpm.wav"
    out.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        data = bytearray()
        for i in range(int(sr * duration)):
            beat = (i / sr) * BPM / 60
            v = int(12000 * math.exp(-30 * (beat % 1)) * math.sin(2 * math.pi * 880 * (beat % 1))) if (beat % 1) < 0.1 else 0
            data += struct.pack("<h", v)
        w.writeframes(bytes(data))


def main() -> None:
    write_metronome()
    frames, phases, frame = [], [], 0
    previous = key_pose(8, soft_arms=False)  # the phrase starts from arms down
    for rep, soft in ((1, False), (2, True)):
        for count in range(1, COUNTS + 1):
            target = key_pose(count, soft)
            n = FRAMES_PER_COUNT
            phases.append({"name": f"count_{count}", "rep": rep, "count": count, "start_frame": frame,
                           "end_frame": frame + n - 1, "keyframe_frame": frame + n // 2})
            for i in range(n):
                t = min(1.0, i / (n // 2))  # move in the first half of the count, hit and hold on the beat
                arms = tuple((lerp_dir(p[0], q[0], t), lerp_dir(p[1], q[1], t)) for p, q in zip(previous, target))
                joints = body(arms)
                frames.append({
                    "frame": frame, "t_ms": round(frame * 1000 / FPS), "interpolated": False,
                    "joints": {j: {"x": round(joints[j][0], 4), "y": round(joints[j][1], 4),
                                   "z": round(joints[j][2], 4), "conf": 0.95} for j in JOINT_NAMES},
                })
                frame += 1
            previous = target
    pass2 = [p for p in phases if p["rep"] == 2]
    pkg = {
        "schema_version": "0.2.0",
        "audio": {"uri": "fixtures/audio/metronome_120bpm.wav", "offset_ms": 0},
        "movement": {"id": "arm_phrase", "name": "8-count arm phrase", "primary_joint": "right_elbow",
                     "structure": "sequence", "follower_mirrors": True},
        "coordinate_system": {
            "origin": "pelvis_midpoint_per_frame", "x_axis": "subject_left_horizontal", "y_axis": "world_up",
            "z_axis": "x_cross_y", "handedness": "right", "up_source": "synthetic",
            "length_unit": "m", "angle_unit": "deg",
        },
        "timing": {"fps": FPS, "time_base": "frame_index", "frame_count": len(frames)},
        "music": {"bpm": BPM, "first_beat_ms": 0, "counts_per_phrase": COUNTS},
        "joint_names": JOINT_NAMES,
        "reference_motion": {"frames": frames, "bone_lengths_m": {"upper_arm": UPPER_ARM, "forearm": FOREARM}},
        "phases": phases,
        "instructions": [
            {"phase": "count_1", "text": "Arms down."}, {"phase": "count_2", "text": "Reach forward."},
            {"phase": "count_3", "text": "Open to the sides."}, {"phase": "count_4", "text": "Arms overhead."},
            {"phase": "count_5", "text": "Right arm up, left arm out."}, {"phase": "count_6", "text": "Both out."},
            {"phase": "count_7", "text": "Goalposts forward."}, {"phase": "count_8", "text": "Arms down."},
        ],
        "cues": [
            {"id": "long_arms", "text": "long arms", "type": "cue", "phase": "count_3", "t_ms": 1000},
            {"id": "arms_straight", "text": "don't let the arms go soft like this", "type": "fault",
             "phase": "count_3", "t_ms": round(pass2[2]["start_frame"] * 1000 / FPS),
             "demo_frames": [pass2[2]["start_frame"], pass2[3]["end_frame"]]},
        ],
        "rules": [ARMS_STRAIGHT, ON_THE_BEAT, BASELINE_RULE],
        "provenance": {
            "source": "synthetic 8-count arm phrase, pass 1 clean, pass 2 soft arms on counts 3-4 (no video)",
            "generated_by": "tools/make_arm_phrase_fixture.py",
            "created_at": "2026-10-26T12:00:00-07:00",
        },
        "quality": {"coverage": 1.0, "mean_confidence": 0.95, "flags": []},
    }
    OUT.write_text(json.dumps(pkg, indent=2) + "\n")
    print(f"wrote {OUT.relative_to(ROOT)}: {len(frames)} frames, {len(phases)} phase segments")


if __name__ == "__main__":
    main()
