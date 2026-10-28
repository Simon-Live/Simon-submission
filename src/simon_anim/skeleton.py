"""Canonical 17-joint body and the rigid kinematic tree around it.

Positions are in the Simon body frame: origin at the hip midpoint, x is the
subject's left (horizontal), y is world up, z is anterior (x cross y).
Metres. Joint rotations are local quaternions (x, y, z, w), degrees only
appear when a metric is reported.

Virtual joints are the Part 3 root, stored here as pelvis, and the neck.
Collarbones and the head leave the neck. They are not part of the 17-joint output.
"""

from __future__ import annotations

import math
from typing import Mapping, Sequence

from .math3d import (
    Quat,
    Vec3,
    as_quat,
    quat_mul,
    quat_rotate,
    v_add,
    v_norm,
    v_scale,
    v_sub,
)

CANONICAL_JOINTS: tuple[str, ...] = (
    "nose",
    "left_eye",
    "right_eye",
    "left_ear",
    "right_ear",
    "left_shoulder",
    "right_shoulder",
    "left_elbow",
    "right_elbow",
    "left_wrist",
    "right_wrist",
    "left_hip",
    "right_hip",
    "left_knee",
    "right_knee",
    "left_ankle",
    "right_ankle",
)

def _fit(direction: Vec3, length: float) -> Vec3:
    """Point the vector the same way, at a chosen length in metres."""
    norm = v_norm(direction)
    scale = length / norm
    return (direction[0] * scale, direction[1] * scale, direction[2] * scale)


# Standard lengths from a Part 3 skeleton (simon.skeleton/1, stature 1.7 m).
# Directions of the head and face keep the synthetic rest pose; the lengths do not.
STANDARD_BONE_LENGTHS_M: dict[str, float] = {
    "left_pelvis": 0.125,
    "right_pelvis": 0.125,
    "left_thigh": 0.4165,
    "right_thigh": 0.4165,
    "left_shank": 0.4182,
    "right_shank": 0.4182,
    "spine": 0.4896,
    "left_clavicle": 0.1979,
    "right_clavicle": 0.1979,
    "left_upper_arm": 0.3162,
    "right_upper_arm": 0.3162,
    "left_forearm": 0.2482,
    "right_forearm": 0.2482,
    "head": 0.1907,
    "left_eye_link": 0.0618,
    "right_eye_link": 0.0618,
    "left_ear_link": 0.0774,
    "right_ear_link": 0.0774,
}

# parent, rest offset of this joint in the parent frame (metres).
# The joint's own local rotation does not move it; it orients outgoing bones.
# pelvis is the Part 3 root. There is no chest bone: the collarbones leave the neck.
REST_OFFSETS: dict[str, tuple[str, Vec3]] = {
    "left_hip": ("pelvis", (STANDARD_BONE_LENGTHS_M["left_pelvis"], 0.0, 0.0)),
    "left_knee": ("left_hip", (0.0, -STANDARD_BONE_LENGTHS_M["left_thigh"], 0.0)),
    "left_ankle": ("left_knee", (0.0, -STANDARD_BONE_LENGTHS_M["left_shank"], 0.0)),
    "right_hip": ("pelvis", (-STANDARD_BONE_LENGTHS_M["right_pelvis"], 0.0, 0.0)),
    "right_knee": ("right_hip", (0.0, -STANDARD_BONE_LENGTHS_M["right_thigh"], 0.0)),
    "right_ankle": ("right_knee", (0.0, -STANDARD_BONE_LENGTHS_M["right_shank"], 0.0)),
    "neck": ("pelvis", (0.0, STANDARD_BONE_LENGTHS_M["spine"], 0.0)),
    "left_shoulder": ("neck", (STANDARD_BONE_LENGTHS_M["left_clavicle"], 0.0, 0.0)),
    "left_elbow": ("left_shoulder", (0.0, -STANDARD_BONE_LENGTHS_M["left_upper_arm"], 0.0)),
    "left_wrist": ("left_elbow", (0.0, -STANDARD_BONE_LENGTHS_M["left_forearm"], 0.0)),
    "right_shoulder": ("neck", (-STANDARD_BONE_LENGTHS_M["right_clavicle"], 0.0, 0.0)),
    "right_elbow": ("right_shoulder", (0.0, -STANDARD_BONE_LENGTHS_M["right_upper_arm"], 0.0)),
    "right_wrist": ("right_elbow", (0.0, -STANDARD_BONE_LENGTHS_M["right_forearm"], 0.0)),
    "nose": ("neck", _fit((0.0, 0.13, 0.03), STANDARD_BONE_LENGTHS_M["head"])),
    "left_eye": ("nose", _fit((0.032, 0.025, 0.012), STANDARD_BONE_LENGTHS_M["left_eye_link"])),
    "left_ear": ("left_eye", _fit((0.055, -0.012, -0.025), STANDARD_BONE_LENGTHS_M["left_ear_link"])),
    "right_eye": ("nose", _fit((-0.032, 0.025, 0.012), STANDARD_BONE_LENGTHS_M["right_eye_link"])),
    "right_ear": ("right_eye", _fit((-0.055, -0.012, -0.025), STANDARD_BONE_LENGTHS_M["right_ear_link"])),
}

FK_ORDER: tuple[str, ...] = (
    "left_hip",
    "left_knee",
    "left_ankle",
    "right_hip",
    "right_knee",
    "right_ankle",
    "neck",
    "left_shoulder",
    "left_elbow",
    "left_wrist",
    "right_shoulder",
    "right_elbow",
    "right_wrist",
    "nose",
    "left_eye",
    "left_ear",
    "right_eye",
    "right_ear",
)

ROTATED_JOINTS: tuple[str, ...] = (
    "pelvis",
    "left_hip",
    "left_knee",
    "left_ankle",
    "right_hip",
    "right_knee",
    "right_ankle",
    "neck",
    "left_shoulder",
    "left_elbow",
    "left_wrist",
    "right_shoulder",
    "right_elbow",
    "right_wrist",
    "nose",
    "left_eye",
    "left_ear",
    "right_eye",
    "right_ear",
)

# Bones whose endpoints are both recoverable from the 17 joints (or the two
# derived midpoints) and whose length is invariant under this rig.
LENGTH_BONES: tuple[dict, ...] = (
    {"name": "pelvis", "parent": "left_hip", "child": "right_hip"},
    {"name": "spine", "parent": "hip_mid", "child": "shoulder_mid"},
    {"name": "shoulder_girdle", "parent": "left_shoulder", "child": "right_shoulder"},
    {"name": "left_thigh", "parent": "left_hip", "child": "left_knee"},
    {"name": "left_shank", "parent": "left_knee", "child": "left_ankle"},
    {"name": "right_thigh", "parent": "right_hip", "child": "right_knee"},
    {"name": "right_shank", "parent": "right_knee", "child": "right_ankle"},
    {"name": "left_upper_arm", "parent": "left_shoulder", "child": "left_elbow"},
    {"name": "left_forearm", "parent": "left_elbow", "child": "left_wrist"},
    {"name": "right_upper_arm", "parent": "right_shoulder", "child": "right_elbow"},
    {"name": "right_forearm", "parent": "right_elbow", "child": "right_wrist"},
    {"name": "left_eye_link", "parent": "nose", "child": "left_eye"},
    {"name": "right_eye_link", "parent": "nose", "child": "right_eye"},
    {"name": "left_ear_link", "parent": "left_eye", "child": "left_ear"},
    {"name": "right_ear_link", "parent": "right_eye", "child": "right_ear"},
)

# One incoming direction per canonical joint. Angle error is measured here.
ANGLE_BONES: tuple[dict, ...] = (
    {"joint": "left_hip", "parent": "hip_mid", "child": "left_hip"},
    {"joint": "right_hip", "parent": "hip_mid", "child": "right_hip"},
    {"joint": "left_knee", "parent": "left_hip", "child": "left_knee"},
    {"joint": "right_knee", "parent": "right_hip", "child": "right_knee"},
    {"joint": "left_ankle", "parent": "left_knee", "child": "left_ankle"},
    {"joint": "right_ankle", "parent": "right_knee", "child": "right_ankle"},
    {"joint": "left_shoulder", "parent": "shoulder_mid", "child": "left_shoulder"},
    {"joint": "right_shoulder", "parent": "shoulder_mid", "child": "right_shoulder"},
    {"joint": "left_elbow", "parent": "left_shoulder", "child": "left_elbow"},
    {"joint": "right_elbow", "parent": "right_shoulder", "child": "right_elbow"},
    {"joint": "left_wrist", "parent": "left_elbow", "child": "left_wrist"},
    {"joint": "right_wrist", "parent": "right_elbow", "child": "right_wrist"},
    {"joint": "nose", "parent": "shoulder_mid", "child": "nose"},
    {"joint": "left_eye", "parent": "nose", "child": "left_eye"},
    {"joint": "right_eye", "parent": "nose", "child": "right_eye"},
    {"joint": "left_ear", "parent": "left_eye", "child": "left_ear"},
    {"joint": "right_ear", "parent": "right_eye", "child": "right_ear"},
)

COORDINATE_FRAME = {
    "origin": "hip_midpoint",
    "x": "subject_left",
    "y": "world_up",
    "z": "anterior",
    "position_unit": "metres",
    "angle_unit": "degrees",
    "notes": "z = x cross y. Hip midpoint is subtracted per frame.",
}

# Done-check thresholds from the Part 4 contract, plus frame-integrity bounds.
THRESHOLDS = {
    "max_joint_angle_error_deg": 8.0,
    "max_bone_length_deviation_m": 0.001,
    "max_hip_midpoint_offset_m": 0.001,
    "max_keyframe_position_error_m": 0.001,
    "max_input_fk_residual_m": 0.001,
}


def rest_offsets_from_skeleton(skeleton: Mapping[str, object]) -> dict[str, tuple[str, Vec3]]:
    """Body dimensions from skeleton.json. Topology stays the standard rig.

    Part 3 writes `rest_offsets_m` for the standard body. The parent of each
    joint must match that rig. The offset vector is the length and direction
    Part 3 measured.
    """
    raw = skeleton.get("rest_offsets_m")
    if not isinstance(raw, dict) or not raw:
        raise ValueError("skeleton.json is missing rest_offsets_m")
    offsets: dict[str, tuple[str, Vec3]] = {}
    for joint in FK_ORDER:
        item = raw.get(joint)
        if not isinstance(item, dict) or "parent" not in item or "offset" not in item:
            raise ValueError(f"skeleton.json rest_offsets_m is missing {joint}")
        parent = str(item["parent"])
        expected_parent = REST_OFFSETS[joint][0]
        if parent != expected_parent:
            raise ValueError(f"{joint} parent is {parent}, the standard rig uses {expected_parent}")
        offset_raw = item["offset"]
        if not isinstance(offset_raw, (list, tuple)) or len(offset_raw) != 3:
            raise ValueError(f"{joint} rest offset must be three metres")
        offset = (float(offset_raw[0]), float(offset_raw[1]), float(offset_raw[2]))
        if v_norm(offset) < 1e-8:
            raise ValueError(f"{joint} rest offset has zero length")
        offsets[joint] = (parent, offset)
    return offsets


def rest_length(parent: str, child: str, rest_offsets: Mapping[str, tuple[str, Vec3]]) -> float:
    """Length of a declared bone from a rest rig, including derived mids."""
    if parent == "hip_mid" and child == "shoulder_mid":
        neck = rest_offsets["neck"][1]
        left = rest_offsets["left_shoulder"][1]
        right = rest_offsets["right_shoulder"][1]
        mid = (
            neck[0] + (left[0] + right[0]) * 0.5,
            neck[1] + (left[1] + right[1]) * 0.5,
            neck[2] + (left[2] + right[2]) * 0.5,
        )
        return v_norm(mid)
    if parent == "hip_mid" and child in rest_offsets and rest_offsets[child][0] == "pelvis":
        return v_norm(rest_offsets[child][1])
    if parent == "shoulder_mid" and child == "nose":
        # Not a single rigid bone (neck + head). Callers must not use this as a length.
        raise KeyError("nose is not a fixed-length child of shoulder_mid")
    if child in rest_offsets and rest_offsets[child][0] == parent:
        return v_norm(rest_offsets[child][1])
    # Symmetric girdle / pelvis: distance between two children of the same parent.
    if parent in rest_offsets and child in rest_offsets:
        if rest_offsets[parent][0] == rest_offsets[child][0]:
            return v_norm(v_sub(rest_offsets[parent][1], rest_offsets[child][1]))
    raise KeyError(f"no rest length for {parent} -> {child}")


# Part 3 bone names. `root` is this rig's pelvis.
PART3_BONES: tuple[tuple[str, str, str], ...] = (
    ("left_pelvis", "root", "left_hip"),
    ("right_pelvis", "root", "right_hip"),
    ("left_thigh", "left_hip", "left_knee"),
    ("right_thigh", "right_hip", "right_knee"),
    ("left_shank", "left_knee", "left_ankle"),
    ("right_shank", "right_knee", "right_ankle"),
    ("spine", "root", "neck"),
    ("left_clavicle", "neck", "left_shoulder"),
    ("right_clavicle", "neck", "right_shoulder"),
    ("left_upper_arm", "left_shoulder", "left_elbow"),
    ("right_upper_arm", "right_shoulder", "right_elbow"),
    ("left_forearm", "left_elbow", "left_wrist"),
    ("right_forearm", "right_elbow", "right_wrist"),
    ("head", "neck", "nose"),
    ("left_eye_link", "nose", "left_eye"),
    ("right_eye_link", "nose", "right_eye"),
    ("left_ear_link", "left_eye", "left_ear"),
    ("right_ear_link", "right_eye", "right_ear"),
)


def bone_lengths_from_offsets(rest_offsets: Mapping[str, tuple[str, Vec3]]) -> dict[str, float]:
    """Scalar lengths keyed the way Part 3 writes bone_lengths_m."""
    return {
        "left_pelvis": v_norm(rest_offsets["left_hip"][1]),
        "right_pelvis": v_norm(rest_offsets["right_hip"][1]),
        "left_thigh": v_norm(rest_offsets["left_knee"][1]),
        "right_thigh": v_norm(rest_offsets["right_knee"][1]),
        "left_shank": v_norm(rest_offsets["left_ankle"][1]),
        "right_shank": v_norm(rest_offsets["right_ankle"][1]),
        "spine": v_norm(rest_offsets["neck"][1]),
        "left_clavicle": v_norm(rest_offsets["left_shoulder"][1]),
        "right_clavicle": v_norm(rest_offsets["right_shoulder"][1]),
        "left_upper_arm": v_norm(rest_offsets["left_elbow"][1]),
        "right_upper_arm": v_norm(rest_offsets["right_elbow"][1]),
        "left_forearm": v_norm(rest_offsets["left_wrist"][1]),
        "right_forearm": v_norm(rest_offsets["right_wrist"][1]),
        "head": v_norm(rest_offsets["nose"][1]),
        "left_eye_link": v_norm(rest_offsets["left_eye"][1]),
        "right_eye_link": v_norm(rest_offsets["right_eye"][1]),
        "left_ear_link": v_norm(rest_offsets["left_ear"][1]),
        "right_ear_link": v_norm(rest_offsets["right_ear"][1]),
    }


def length_bones_with_rest(rest_offsets: Mapping[str, tuple[str, Vec3]]) -> list[dict]:
    bones = []
    for bone in LENGTH_BONES:
        item = dict(bone)
        item["length_m"] = rest_length(bone["parent"], bone["child"], rest_offsets)
        bones.append(item)
    return bones


def _rotation_of(local_rotations: Mapping[str, Sequence[float]], joint: str) -> Quat:
    if joint not in local_rotations:
        raise ValueError(f"missing a rotation for {joint}")
    raw = local_rotations[joint]
    if len(tuple(raw)) != 4:
        raise ValueError(f"{joint} rotation must be a quaternion (x, y, z, w)")
    norm = math.sqrt(sum(float(value) * float(value) for value in raw))
    if norm < 1e-8:
        raise ValueError(f"{joint} rotation is zero")
    return as_quat(raw)


def forward_kinematics(
    local_rotations: Mapping[str, Sequence[float]],
    rest_offsets: Mapping[str, tuple[str, Vec3]],
) -> dict[str, Vec3]:
    """Joint positions in the body frame. Pelvis starts at the origin.

    Each joint's incoming offset is expressed in its parent's frame. The
    joint's local rotation orients bones that leave it, so bone lengths stay
    equal to the rest offsets from skeleton.json.
    """
    rot: dict[str, Quat] = {"pelvis": _rotation_of(local_rotations, "pelvis")}
    pos: dict[str, Vec3] = {"pelvis": (0.0, 0.0, 0.0)}
    for joint in FK_ORDER:
        parent, offset = rest_offsets[joint]
        parent_rot = rot[parent]
        local = _rotation_of(local_rotations, joint)
        rot[joint] = quat_mul(parent_rot, local)
        pos[joint] = v_add(pos[parent], quat_rotate(parent_rot, offset))
    hip_mid = v_scale(v_add(pos["left_hip"], pos["right_hip"]), 0.5)
    return {name: v_sub(pos[name], hip_mid) for name in CANONICAL_JOINTS}


def derived_points(joints: Mapping[str, Sequence[float]]) -> dict[str, Vec3]:
    from .math3d import as_vec3

    points = {name: as_vec3(joints[name]) for name in CANONICAL_JOINTS}
    points["hip_mid"] = v_scale(v_add(points["left_hip"], points["right_hip"]), 0.5)
    points["shoulder_mid"] = v_scale(
        v_add(points["left_shoulder"], points["right_shoulder"]), 0.5
    )
    return points
