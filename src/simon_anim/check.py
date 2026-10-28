"""Part 4 done-check.

Rebuilds each fixture from its keyframes, scores hidden in-between frames
against the stored ground truth, and checks that bone lengths stay fixed
at the body in skeleton.json. The Part 3 clip has no hidden frames; it is
held to the same key, bone and output rules. Every committed fixture is
validated against contracts/*.schema.json, and those files must match
`contract.py`.
Prints one metrics JSON object. Exits 0 only when every threshold passes.
Does not call Meta Model API.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from . import contract
from .interpolate import build_animation
from .math3d import as_joint, direction_angle_deg, round_floats, v_norm, v_sub
from .skeleton import (
    ANGLE_BONES,
    CANONICAL_JOINTS,
    THRESHOLDS,
    derived_points,
    forward_kinematics,
    length_bones_with_rest,
    rest_offsets_from_skeleton,
)

ROOT = Path(__file__).resolve().parents[2]
# Scored against fixtures/expected/<set>/held_out.json.
SETS = ("exercise", "dance", "long")
# Part 3's --view part4 output. No ground truth between keys, so keys, bones and output only.
PART3_SETS = ("part3-squat",)
SHIPPED_TOLERANCE_M = 5e-5


def _load(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _points(frame: dict) -> dict:
    return derived_points(frame["joints"])


def _max_abs_joint_delta(a: dict, b: dict) -> float:
    worst = 0.0
    for name in CANONICAL_JOINTS:
        worst = max(worst, v_norm(v_sub(as_joint(a[name]), as_joint(b[name]))))
    return worst


def _load_set(set_name: str) -> tuple[dict, dict, dict, dict]:
    input_dir = ROOT / "fixtures" / "input" / set_name
    output_path = ROOT / "fixtures" / "output" / set_name / "animation.json"
    keyframes_doc = _load(input_dir / "keyframes.json")
    skeleton = _load(input_dir / "skeleton.json")
    if not output_path.is_file():
        raise FileNotFoundError(f"missing shipped animation: {output_path}")
    shipped = _load(output_path)
    fresh = build_animation(skeleton, keyframes_doc, set_name=set_name)
    return keyframes_doc, skeleton, shipped, fresh


def _held_out_metrics(set_name: str, keyframes_doc: dict, fresh: dict) -> dict:
    expected = _load(ROOT / "fixtures" / "expected" / set_name / "held_out.json")
    key_set = {int(frame["index"]) for frame in keyframes_doc["keyframes"]}
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
    return {
        "held_out_frames": len(held_out),
        "max_joint_angle_error_deg": max(per_joint.values()) if per_joint else 0.0,
        "mean_joint_angle_error_deg": pair_sum / pair_count if pair_count else 0.0,
        "worst_joint": max(per_joint, key=per_joint.get) if per_joint else None,
        "worst_frame": worst_frame,
        "per_joint_max_angle_error_deg": per_joint,
    }


def _shipped_delta(fresh: dict, shipped: dict) -> tuple[float, bool]:
    """Largest joint gap between the shipped file and a rebuild, and whether the flags agree."""
    shipped_frames = {int(frame["index"]): frame for frame in shipped.get("frames", [])}
    if len(shipped_frames) != len(fresh["frames"]):
        return 1.0, True
    delta = 0.0
    flags_ok = True
    for frame in fresh["frames"]:
        index = int(frame["index"])
        if index not in shipped_frames:
            return 1.0, flags_ok
        delta = max(delta, _max_abs_joint_delta(frame["joints"], shipped_frames[index]["joints"]))
        if bool(shipped_frames[index].get("interpolated")) != bool(frame["interpolated"]):
            flags_ok = False
    return delta, flags_ok


def _integrity_metrics(keyframes_doc: dict, skeleton: dict, fresh: dict, shipped: dict) -> dict:
    """Bones, hip origin, key poses, flags and the shipped file. Shared by every set."""
    key_idx = [int(frame["index"]) for frame in keyframes_doc["keyframes"]]
    key_set = set(key_idx)
    by_index = {int(frame["index"]): frame for frame in fresh["frames"]}
    rest_offsets = rest_offsets_from_skeleton(skeleton)
    per_bone_dev: dict[str, float] = {}
    max_dev = 0.0
    max_hip = 0.0
    for frame in fresh["frames"]:
        pts = _points(frame)
        max_hip = max(max_hip, v_norm(pts["hip_mid"]))
        for bone in length_bones_with_rest(rest_offsets):
            length = v_norm(v_sub(pts[bone["child"]], pts[bone["parent"]]))
            dev = abs(length - float(bone["length_m"]))
            per_bone_dev[bone["name"]] = max(per_bone_dev.get(bone["name"], 0.0), dev)
            max_dev = max(max_dev, dev)

    # Input positions must agree with FK of the stored local rotations on the file's body.
    fk_residual = 0.0
    for sample in skeleton["keyframes"]:
        posed = forward_kinematics(sample["local_rotations"], rest_offsets)
        fk_residual = max(fk_residual, _max_abs_joint_delta(posed, sample["joints"]))

    samples = {int(sample["index"]): sample for sample in skeleton["keyframes"]}
    key_pos_err = 0.0
    for index in key_idx:
        key_pos_err = max(key_pos_err, _max_abs_joint_delta(by_index[index]["joints"], samples[index]["joints"]))

    flags_ok = all(bool(frame["interpolated"]) == (int(frame["index"]) not in key_set) for frame in fresh["frames"])
    shipped_delta, shipped_flags_ok = _shipped_delta(fresh, shipped)
    flags_ok = flags_ok and shipped_flags_ok
    shipped_schema_errors = contract.validate(shipped, contract.animation_schema())
    return {
        "max_bone_length_deviation_m": max_dev,
        "per_bone_max_length_deviation_m": per_bone_dev,
        "max_hip_midpoint_offset_m": max_hip,
        "max_keyframe_position_error_m": key_pos_err,
        "max_input_fk_residual_m": fk_residual,
        "max_shipped_output_delta_m": shipped_delta,
        "interpolated_flags_ok": flags_ok,
        "shipped_schema_errors": len(shipped_schema_errors),
        "_flags": {
            "bone_length": max_dev <= THRESHOLDS["max_bone_length_deviation_m"],
            "hip_origin": max_hip <= THRESHOLDS["max_hip_midpoint_offset_m"],
            "keyframe_positions": key_pos_err <= THRESHOLDS["max_keyframe_position_error_m"],
            "input_fk": fk_residual <= THRESHOLDS["max_input_fk_residual_m"],
            "interpolated_flags": flags_ok,
            "shipped_output": shipped_delta <= SHIPPED_TOLERANCE_M,
            "shipped_schema": not shipped_schema_errors,
            "fps": int(fresh["fps"]) == 30 and int(shipped.get("fps", 0)) == 30,
            "frame_count": int(fresh["frame_count"]) == int(keyframes_doc["frame_count"]),
        },
    }


def _score_set(set_name: str) -> dict:
    keyframes_doc, skeleton, shipped, fresh = _load_set(set_name)
    held = _held_out_metrics(set_name, keyframes_doc, fresh)
    integrity = _integrity_metrics(keyframes_doc, skeleton, fresh, shipped)
    flags = integrity.pop("_flags")
    pass_flags = {"angle": held["max_joint_angle_error_deg"] <= THRESHOLDS["max_joint_angle_error_deg"], **flags}
    return {
        "movement": keyframes_doc.get("movement"),
        "frames": int(fresh["frame_count"]),
        "keyframes": len(keyframes_doc["keyframes"]),
        **held,
        **integrity,
        "pass_flags": pass_flags,
        "pass": all(pass_flags.values()),
    }


def _native_frame_angles(skeleton: dict, fresh: dict, key_idx: list[int]) -> dict:
    """Information only: the clip against Part 3's own per-frame poses between the keys.

    Part 3's `frames[]` are not posed on this rig (see rig.fit), and Part 1's
    keys are far apart, so this is not held to 8 degrees.
    """
    by_index = {int(frame["index"]): frame for frame in fresh["frames"]}
    key_set = set(key_idx)
    worst = 0.0
    worst_at = None
    count = 0
    for frame in skeleton.get("frames") or []:
        people = frame.get("people") or []
        index = round(float(frame.get("t_ms", -1.0)) / 1000.0 * 30)
        if not people or index in key_set or not key_idx[0] < index < key_idx[-1]:
            continue
        got = _points(by_index[index])
        truth = derived_points({name: as_joint(value) for name, value in people[0]["joints"].items()})
        for bone in ANGLE_BONES:
            err = direction_angle_deg(
                v_sub(got[bone["child"]], got[bone["parent"]]),
                v_sub(truth[bone["child"]], truth[bone["parent"]]),
            )
            if err > worst:
                worst, worst_at = err, {"index": index, "joint": bone["joint"]}
        count += 1
    return {"part3_frames_compared": count, "part3_frames_max_angle_deg": worst, "part3_frames_worst": worst_at}


def _score_part3_set(set_name: str) -> dict:
    keyframes_doc, skeleton, shipped, fresh = _load_set(set_name)
    integrity = _integrity_metrics(keyframes_doc, skeleton, fresh, shipped)
    pass_flags = integrity.pop("_flags")
    rig = skeleton.get("rig") if isinstance(skeleton.get("rig"), dict) else {}
    key_idx = [int(frame["index"]) for frame in keyframes_doc["keyframes"]]
    return {
        "source": "Part 3 --view part4",
        "movement": fresh.get("movement"),
        "frames": int(fresh["frame_count"]),
        "keyframes": len(keyframes_doc["keyframes"]),
        "key_indices": key_idx,
        "held_out_frames": 0,
        "part3_rig_fit_max_m": (rig.get("fit") or {}).get("max_m"),
        **_native_frame_angles(skeleton, fresh, key_idx),
        **integrity,
        "pass_flags": pass_flags,
        "pass": all(pass_flags.values()),
    }


def fixture_files() -> list[tuple[str, Path]]:
    """Every committed fixture input and output, with the schema it must meet."""
    pairs = []
    for path in sorted((ROOT / "fixtures" / "input").glob("*/keyframes.json")):
        pairs.append(("keyframes", path))
    for path in sorted((ROOT / "fixtures" / "input").glob("*/skeleton.json")):
        pairs.append(("skeleton", path))
    for path in sorted((ROOT / "fixtures" / "output").glob("*/animation.json")):
        pairs.append(("animation", path))
    return pairs


def contracts_report() -> dict:
    stale = contract.stale_files()
    failures = {}
    pairs = fixture_files()
    for kind, path in pairs:
        errors = contract.validate(_load(path), contract.SCHEMAS[kind]())
        if errors:
            failures[str(path.relative_to(ROOT))] = errors[:3]
    pass_flags = {"schema_files_current": not stale, "fixtures_valid": not failures}
    return {
        "schemas": [f"contracts/{name}" for name in contract.FILES.values()],
        "stale_schema_files": stale,
        "fixture_files_checked": len(pairs),
        "fixture_failures": failures,
        "pass_flags": pass_flags,
        "pass": all(pass_flags.values()),
    }


def run() -> dict:
    sets = {}
    errors = []
    scorers = [(name, _score_set) for name in SETS] + [(name, _score_part3_set) for name in PART3_SETS]
    for name, scorer in scorers:
        try:
            sets[name] = scorer(name)
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
            sets[name] = {"pass": False, "error": str(exc)}
            errors.append(f"{name}: {exc}")
    contracts = contracts_report()
    overall = (
        all(item.get("pass") for item in sets.values())
        and len(sets) == len(scorers)
        and contracts["pass"]
    )
    report = {
        "check": "check-4",
        "meta_live_calls": 0,
        "thresholds": THRESHOLDS,
        "sets": sets,
        "contracts": contracts,
        "pass": overall,
    }
    if errors:
        report["error"] = "; ".join(errors)
    return report


def main() -> None:
    try:
        report = run()
    except Exception as exc:  # noqa: BLE001: the done-check must still print JSON
        report = {"check": "check-4", "meta_live_calls": 0, "pass": False, "error": str(exc)}
    json.dump(round_floats(report, 6), sys.stdout, indent=2)
    sys.stdout.write("\n")
    sys.exit(0 if report.get("pass") else 1)


if __name__ == "__main__":
    main()
