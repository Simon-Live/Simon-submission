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
from simon_anim.motion import MOTIONS, frame_count, keyframe_indices, uneven_keyframe_indices  # noqa: E402
from simon_anim.skeleton import (  # noqa: E402
    CANONICAL_JOINTS,
    COORDINATE_FRAME,
    PART3_BONES,
    REST_OFFSETS,
    ROTATED_JOINTS,
    Vec3,
    bone_lengths_from_offsets,
    forward_kinematics,
    length_bones_with_rest,
)


def _quat_list(q) -> list[float]:
    return [q[0], q[1], q[2], q[3]]


def _point(xyz) -> dict:
    return {"x": xyz[0], "y": xyz[1], "z": xyz[2], "conf": 1.0}


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


def _scaled_offsets(scale: float) -> dict[str, tuple[str, Vec3]]:
    offsets = {}
    for joint, (parent, offset) in REST_OFFSETS.items():
        offsets[joint] = (parent, (offset[0] * scale, offset[1] * scale, offset[2] * scale))
    return offsets


def _name(set_name: str, t: float, duration: float) -> str:
    if set_name == "dance":
        return _dance_name(t, duration)
    if set_name in {"long", "minute"}:
        cycle = 3.0
        local_t = 0.0 if abs(t - duration) <= 1e-8 else t % cycle
        return _exercise_name(local_t, cycle)
    return _exercise_name(t, duration)


def _sample(set_name: str) -> tuple[dict, dict, dict]:
    spec = MOTIONS[set_name]
    fps = spec["fps"]
    duration = spec["duration_s"]
    count = frame_count(duration, fps)
    if "key_pattern" in spec:
        indices = uneven_keyframe_indices(count, int(spec["cycle_frames"]), tuple(spec["key_pattern"]))
    else:
        indices = keyframe_indices(count, spec["key_stride"])
    offsets = _scaled_offsets(float(spec.get("scale", 1.0)))
    samples = []
    for index in range(count):
        t = index / fps
        local = spec["rotations"](t, duration)
        positions = forward_kinematics(local, offsets)
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
    lengths = bone_lengths_from_offsets(offsets)
    skeleton = {
        "format": "simon.skeleton.v1",
        "schema": "simon.skeleton/1",
        "set": set_name,
        "movement": spec["movement"],
        "units": {"length": "m", "angle": "deg", "time": "s", "rotation": "quaternion"},
        "coordinate_frame": COORDINATE_FRAME,
        "frame": {
            "origin": "hip_midpoint",
            "x": "subject_left",
            "y": "world_up",
            "z": "anterior",
            "up_source": "authored",
        },
        "joints": list(CANONICAL_JOINTS),
        "root_joint": "pelvis",
        "virtual_joints": ["pelvis", "neck"],
        "standard": {
            "stature_m": 1.7,
            "scale": float(spec.get("scale", 1.0)),
            "sources": [
                "Winter DA. Biomechanics and Motor Control of Human Movement, 4th ed. Wiley, 2009, Fig. 4.1 (after Drillis and Contini 1966)",
                "Gordon CC et al. 2012 Anthropometric Survey of US Army Personnel (ANSUR II), public data, NATICK/TR-15/007; pooled 4,082 men and 1,986 women",
                "Human3.6M skeleton offsets (Ionescu et al. 2014) as published in facebookresearch/QuaterNet short_term/dataset_h36m.py",
                "Google MediaPipe face_geometry canonical_face_model.obj (Apache-2.0)",
                "Kendall FP et al. Muscles: Testing and Function with Posture and Pain, 5th ed. 2005: ideal plumb line through the ear lobe and the acromion",
            ],
        },
        "bone_lengths_m": lengths,
        "bones": [
            {"name": name, "from": parent, "to": child, "length_m": lengths[name]}
            for name, parent, child in PART3_BONES
        ],
        "rest_offsets_m": {
            joint: {"parent": parent, "offset": list(offset)}
            for joint, (parent, offset) in offsets.items()
        },
        "check_bones": length_bones_with_rest(offsets),
        "person": {
            "id": "synthetic",
            "rule": "authored",
            "frames_present": len(indices),
            "frames_dropped": 0,
            "few_frames": False,
            "measured_bone_lengths_m": lengths,
            "flips_repaired_total": {"body": 0, "legs": 0, "arms": 0, "face": 0},
        },
        "mirror": {
            "setting": "none",
            "applied": False,
            "reason": "Synthetic fixture. There is no image to mirror.",
        },
        "keyframes": [],
    }
    for i in indices:
        sample = samples[i]
        skeleton["keyframes"].append(
            {
                "index": sample["index"],
                "t": sample["t"],
                "name": _name(set_name, sample["t"], duration),
                "joints": {name: _point(sample["positions"][name]) for name in CANONICAL_JOINTS},
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
        f"knee_z={joints['left_knee']['z']:+.3f} ankle_y={joints['left_ankle']['y']:+.3f} "
        f"wrist_z={joints['left_wrist']['z']:+.3f} nose_y={joints['nose']['y']:+.3f}"
    )


def main() -> None:
    names = sys.argv[1:] or list(MOTIONS)
    for set_name in names:
        spec = MOTIONS[set_name]
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
