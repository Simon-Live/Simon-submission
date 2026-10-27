"""Part 4 done-check.

Rebuilds each fixture from its keyframes, scores hidden in-between frames
against the stored ground truth, and checks that bone lengths stay fixed.
Prints one metrics JSON object. Exits 0 only when every threshold passes.
Does not call Meta Model API.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .interpolate import build_animation
from .math3d import as_vec3, direction_angle_deg, round_floats, v_norm, v_sub
from .skeleton import (
    ANGLE_BONES,
    CANONICAL_JOINTS,
    THRESHOLDS,
    derived_points,
    forward_kinematics,
    length_bones_with_rest,
)

ROOT = Path(__file__).resolve().parents[2]
SETS = ("exercise", "dance")


def _load(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _points(frame: dict) -> dict:
    return derived_points(frame["joints"])


def _max_abs_joint_delta(a: dict, b: dict) -> float:
    worst = 0.0
    for name in CANONICAL_JOINTS:
        worst = max(worst, v_norm(v_sub(as_vec3(a[name]), as_vec3(b[name]))))
    return worst


def _score_set(set_name: str) -> dict:
    input_dir = ROOT / "fixtures" / "input" / set_name
    expected_path = ROOT / "fixtures" / "expected" / set_name / "held_out.json"
    output_path = ROOT / "fixtures" / "output" / set_name / "animation.json"
    keyframes_doc = _load(input_dir / "keyframes.json")
    skeleton = _load(input_dir / "skeleton.json")
    expected = _load(expected_path)
    if not output_path.is_file():
        raise FileNotFoundError(f"missing shipped animation: {output_path}")
    shipped = _load(output_path)
    fresh = build_animation(skeleton, keyframes_doc)

    thresholds = dict(THRESHOLDS)
    key_idx = [int(frame["index"]) for frame in keyframes_doc["keyframes"]]
    key_set = set(key_idx)
    held_out = [frame for frame in expected["frames"] if int(frame["index"]) not in key_set]
    if not held_out:
        raise ValueError(f"{set_name}: expected file has no held-out frames")

    by_index = {int(frame["index"]): frame for frame in fresh["frames"]}
    per_joint = {bone["joint"]: 0.0 for bone in ANGLE_BONES}
    pair_sum = 0.0
    pair_count = 0
    worst_frame = None
    worst_frame_err = -1.0
    for frame in held_out:
        index = int(frame["index"])
        if index not in by_index:
            raise ValueError(f"{set_name}: animation missing held-out frame {index}")
        got = _points(by_index[index])
        truth = _points(frame)
        frame_worst = 0.0
        for bone in ANGLE_BONES:
            err = direction_angle_deg(
                v_sub(got[bone["child"]], got[bone["parent"]]),
                v_sub(truth[bone["child"]], truth[bone["parent"]]),
            )
            per_joint[bone["joint"]] = max(per_joint[bone["joint"]], err)
            frame_worst = max(frame_worst, err)
            pair_sum += err
            pair_count += 1
        if frame_worst > worst_frame_err:
            worst_frame_err = frame_worst
            worst_frame = index

    bones = length_bones_with_rest()
    per_bone_dev = {}
    max_dev = 0.0
    max_hip = 0.0
    for frame in fresh["frames"]:
        pts = _points(frame)
        max_hip = max(max_hip, v_norm(pts["hip_mid"]))
        for bone in bones:
            length = v_norm(v_sub(pts[bone["child"]], pts[bone["parent"]]))
            dev = abs(length - float(bone["length_m"]))
            per_bone_dev[bone["name"]] = max(per_bone_dev.get(bone["name"], 0.0), dev)
            max_dev = max(max_dev, dev)

    # Input positions must agree with FK of the stored local rotations.
    fk_residual = 0.0
    for sample in skeleton["keyframes"]:
        posed = forward_kinematics(sample["local_rotations"])
        fk_residual = max(fk_residual, _max_abs_joint_delta(posed, sample["joints"]))

    key_pos_err = 0.0
    samples = {int(sample["index"]): sample for sample in skeleton["keyframes"]}
    for index in key_idx:
        key_pos_err = max(key_pos_err, _max_abs_joint_delta(by_index[index]["joints"], samples[index]["joints"]))

    flags_ok = True
    for frame in fresh["frames"]:
        want = int(frame["index"]) not in key_set
        if bool(frame["interpolated"]) != want:
            flags_ok = False
            break
    shipped_delta = 0.0
    shipped_frames = {int(frame["index"]): frame for frame in shipped.get("frames", [])}
    if len(shipped_frames) != len(fresh["frames"]):
        shipped_delta = 1.0
    else:
        for index, frame in by_index.items():
            if index not in shipped_frames:
                shipped_delta = 1.0
                break
            shipped_delta = max(
                shipped_delta,
                _max_abs_joint_delta(frame["joints"], shipped_frames[index]["joints"]),
            )
            if bool(shipped_frames[index].get("interpolated")) != bool(frame["interpolated"]):
                flags_ok = False

    max_angle = max(per_joint.values()) if per_joint else 0.0
    mean_angle = pair_sum / pair_count if pair_count else 0.0
    worst_joint = max(per_joint, key=per_joint.get) if per_joint else None
    pass_flags = {
        "angle": max_angle <= thresholds["max_joint_angle_error_deg"],
        "bone_length": max_dev <= thresholds["max_bone_length_deviation_m"],
        "hip_origin": max_hip <= thresholds["max_hip_midpoint_offset_m"],
        "keyframe_positions": key_pos_err <= thresholds["max_keyframe_position_error_m"],
        "input_fk": fk_residual <= thresholds["max_input_fk_residual_m"],
        "interpolated_flags": flags_ok,
        "shipped_output": shipped_delta <= 5e-5,
        "fps": int(fresh["fps"]) == 30 and int(shipped.get("fps", 0)) == 30,
        "frame_count": int(fresh["frame_count"]) == int(keyframes_doc["frame_count"]),
    }
    return {
        "movement": keyframes_doc.get("movement"),
        "frames": int(fresh["frame_count"]),
        "keyframes": len(key_idx),
        "held_out_frames": len(held_out),
        "max_joint_angle_error_deg": max_angle,
        "mean_joint_angle_error_deg": mean_angle,
        "worst_joint": worst_joint,
        "worst_frame": worst_frame,
        "per_joint_max_angle_error_deg": per_joint,
        "max_bone_length_deviation_m": max_dev,
        "per_bone_max_length_deviation_m": per_bone_dev,
        "max_hip_midpoint_offset_m": max_hip,
        "max_keyframe_position_error_m": key_pos_err,
        "max_input_fk_residual_m": fk_residual,
        "max_shipped_output_delta_m": shipped_delta,
        "interpolated_flags_ok": flags_ok,
        "pass_flags": pass_flags,
        "pass": all(pass_flags.values()),
    }


def run() -> dict:
    sets = {}
    errors = []
    for name in SETS:
        try:
            sets[name] = _score_set(name)
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
            sets[name] = {"pass": False, "error": str(exc)}
            errors.append(f"{name}: {exc}")
    overall = all(item.get("pass") for item in sets.values()) and len(sets) == len(SETS)
    report = {
        "check": "check-4",
        "meta_live_calls": 0,
        "thresholds": THRESHOLDS,
        "sets": sets,
        "pass": overall,
    }
    if errors:
        report["error"] = "; ".join(errors)
    return report


def main() -> None:
    try:
        report = run()
    except Exception as exc:  # noqa: BLE001 — the done-check must still print JSON
        report = {"check": "check-4", "meta_live_calls": 0, "pass": False, "error": str(exc)}
    json.dump(round_floats(report, 6), sys.stdout, indent=2)
    sys.stdout.write("\n")
    sys.exit(0 if report.get("pass") else 1)


if __name__ == "__main__":
    main()
