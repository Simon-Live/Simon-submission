"""Author the exercise and dance fixtures from analytic motions.

Writes input keyframes, held-out ground truth, and animation.json.
The animation file is produced by the same interpolator `make check-4` runs.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from simon_anim.animate import dump_json  # noqa: E402
from simon_anim.interpolate import build_animation  # noqa: E402
from simon_anim.math3d import quat_geodesic_deg  # noqa: E402
from simon_anim.motion import MOTIONS, frame_count, keyframe_indices  # noqa: E402
from simon_anim.skeleton import (  # noqa: E402
    CANONICAL_JOINTS,
    COORDINATE_FRAME,
    REST_OFFSETS,
    ROTATED_JOINTS,
    forward_kinematics,
    length_bones_with_rest,
)


def _quat_list(q) -> list[float]:
    return [q[0], q[1], q[2], q[3]]


def _exercise_name(t: float, duration: float) -> str:
    if t <= 1e-8 or abs(t - duration) <= 1e-8:
        return "stand"
    s = 0.5 - 0.5 * math.cos(2.0 * math.pi * t / duration)
    if s >= 0.97:
        return "bottom"
    if t < duration * 0.5:
        return "descend"
    return "ascend"


def _dance_name(t: float, duration: float) -> str:
    if t <= 1e-8 or abs(t - duration) <= 1e-8:
        return "together"
    w = 2.0 * math.pi * 2.0 * t / duration
    s = math.sin(w)
    if s > 0.85:
        return "lift_left"
    if s < -0.85:
        return "lift_right"
    return "crossing"


def _name(set_name: str, t: float, duration: float) -> str:
    if set_name == "exercise":
        return _exercise_name(t, duration)
    return _dance_name(t, duration)


def _sample(set_name: str) -> tuple[dict, dict, dict]:
    spec = MOTIONS[set_name]
    fps = spec["fps"]
    duration = spec["duration_s"]
    count = frame_count(duration, fps)
    indices = keyframe_indices(count, spec["key_stride"])
    samples = []
    for index in range(count):
        t = index / fps
        local = spec["rotations"](t, duration)
        positions = forward_kinematics(local)
        samples.append({"index": index, "t": t, "local": local, "positions": positions})

    for left, right in zip(indices, indices[1:]):
        for joint in ROTATED_JOINTS:
            step = quat_geodesic_deg(samples[left]["local"][joint], samples[right]["local"][joint])
            if step > 120.0:
                raise RuntimeError(f"{set_name} {joint} steps {step:.1f}° between frames {left} and {right}")

    keyframes_doc = {
        "format": "simon.keyframes.v1",
        "set": set_name,
        "movement": spec["movement"],
        "fps": fps,
        "duration_s": duration,
        "frame_count": count,
        "keyframes": [
            {"index": samples[i]["index"], "t": samples[i]["t"], "name": _name(set_name, samples[i]["t"], duration)}
            for i in indices
        ],
    }
    skeleton = {
        "format": "simon.skeleton.v1",
        "set": set_name,
        "movement": spec["movement"],
        "coordinate_frame": COORDINATE_FRAME,
        "joints": list(CANONICAL_JOINTS),
        "virtual_joints": ["pelvis", "chest", "neck"],
        "rest_offsets_m": {
            joint: {"parent": parent, "offset": list(offset)}
            for joint, (parent, offset) in REST_OFFSETS.items()
        },
        "bones": length_bones_with_rest(),
        "keyframes": [],
    }
    for i in indices:
        sample = samples[i]
        skeleton["keyframes"].append(
            {
                "index": sample["index"],
                "t": sample["t"],
                "name": _name(set_name, sample["t"], duration),
                "joints": {name: list(sample["positions"][name]) for name in CANONICAL_JOINTS},
                "local_rotations": {joint: _quat_list(sample["local"][joint]) for joint in ROTATED_JOINTS},
            }
        )
    held_out = {
        "format": "simon.held_out.v1",
        "set": set_name,
        "movement": spec["movement"],
        "fps": fps,
        "frame_count": count,
        "keyframe_indices": indices,
        "note": (
            "Ground truth at frames that are not keyframes. "
            "The animator does not read this file. Angles are scored per joint against it."
        ),
        "frames": [
            {
                "index": sample["index"],
                "t": sample["t"],
                "joints": {name: list(sample["positions"][name]) for name in CANONICAL_JOINTS},
            }
            for sample in samples
            if sample["index"] not in set(indices)
        ],
    }
    return keyframes_doc, skeleton, held_out


def _print_pose(set_name: str, skeleton: dict) -> None:
    # Show the keyframe nearest the middle so a squat bottom / dance lift is visible.
    frame = skeleton["keyframes"][len(skeleton["keyframes"]) // 2]
    joints = frame["joints"]
    print(
        f"  {set_name} key {frame['index']} {frame['name']}: "
        f"knee_z={joints['left_knee'][2]:+.3f} ankle_y={joints['left_ankle'][1]:+.3f} "
        f"wrist_z={joints['left_wrist'][2]:+.3f} nose_y={joints['nose'][1]:+.3f}"
    )


def main() -> None:
    for set_name, spec in MOTIONS.items():
        keyframes_doc, skeleton, held_out = _sample(set_name)
        input_dir = ROOT / "fixtures" / "input" / set_name
        dump_json(input_dir / "keyframes.json", keyframes_doc)
        dump_json(input_dir / "skeleton.json", skeleton)
        (input_dir / "coaching_note.txt").write_text(spec["coaching_note"] + "\n", encoding="utf-8")
        dump_json(ROOT / "fixtures" / "expected" / set_name / "held_out.json", held_out)
        # Reload through the public animator path so the shipped file matches check-4.
        from simon_anim.animate import load_json

        animation = build_animation(
            load_json(input_dir / "skeleton.json"),
            load_json(input_dir / "keyframes.json"),
        )
        dump_json(ROOT / "fixtures" / "output" / set_name / "animation.json", animation)
        _print_pose(set_name, skeleton)
        print(
            f"  wrote {set_name}: {keyframes_doc['frame_count']} frames, "
            f"{len(keyframes_doc['keyframes'])} keys, {len(held_out['frames'])} held out"
        )


if __name__ == "__main__":
    main()
