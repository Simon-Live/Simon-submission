"""Canonical 17-joint body and the rigid kinematic tree around it.

Positions are in the Simon body frame: origin at the hip midpoint, x is the
subject's left (horizontal), y is world up, z is anterior (x cross y).
Metres. Joint rotations are local quaternions (x, y, z, w), degrees only
appear when a metric is reported.

Virtual joints (pelvis, chest, neck) exist so limb and head bones have a
parent. They are not part of the 17-joint output.
"""

from __future__ import annotations

from typing import Mapping, Sequence

from .math3d import (
    IDENT_QUAT,
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

# parent, rest offset of this joint in the parent frame (metres).
# The joint's own local rotation does not move it; it orients outgoing bones.
REST_OFFSETS: dict[str, tuple[str, Vec3]] = {
    "left_hip": ("pelvis", (0.095, 0.0, 0.0)),
    "left_knee": ("left_hip", (0.0, -0.42, 0.0)),
    "left_ankle": ("left_knee", (0.0, -0.40, 0.0)),
    "right_hip": ("pelvis", (-0.095, 0.0, 0.0)),
    "right_knee": ("right_hip", (0.0, -0.42, 0.0)),
    "right_ankle": ("right_knee", (0.0, -0.40, 0.0)),
    "chest": ("pelvis", (0.0, 0.50, 0.0)),
    "left_shoulder": ("chest", (0.20, 0.0, 0.0)),
    "left_elbow": ("left_shoulder", (0.0, -0.28, 0.0)),
    "left_wrist": ("left_elbow", (0.0, -0.25, 0.0)),
    "right_shoulder": ("chest", (-0.20, 0.0, 0.0)),
    "right_elbow": ("right_shoulder", (0.0, -0.28, 0.0)),
    "right_wrist": ("right_elbow", (0.0, -0.25, 0.0)),
    "neck": ("chest", (0.0, 0.14, 0.01)),
    "nose": ("neck", (0.0, 0.13, 0.03)),
    "left_eye": ("nose", (0.032, 0.025, 0.012)),
    "left_ear": ("left_eye", (0.055, -0.012, -0.025)),
    "right_eye": ("nose", (-0.032, 0.025, 0.012)),
    "right_ear": ("right_eye", (-0.055, -0.012, -0.025)),
}

FK_ORDER: tuple[str, ...] = (
    "left_hip",
    "left_knee",
    "left_ankle",
    "right_hip",
    "right_knee",
    "right_ankle",
    "chest",
    "left_shoulder",
    "left_elbow",
    "left_wrist",
    "right_shoulder",
    "right_elbow",
    "right_wrist",
    "neck",
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
    "chest",
    "left_shoulder",
    "left_elbow",
    "left_wrist",
    "right_shoulder",
    "right_elbow",
    "right_wrist",
    "neck",
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
    {"name": "left_shin", "parent": "left_knee", "child": "left_ankle"},
    {"name": "right_thigh", "parent": "right_hip", "child": "right_knee"},
    {"name": "right_shin", "parent": "right_knee", "child": "right_ankle"},
    {"name": "left_upper_arm", "parent": "left_shoulder", "child": "left_elbow"},
    {"name": "left_forearm", "parent": "left_elbow", "child": "left_wrist"},
    {"name": "right_upper_arm", "parent": "right_shoulder", "child": "right_elbow"},
    {"name": "right_forearm", "parent": "right_elbow", "child": "right_wrist"},
    {"name": "left_eye_offset", "parent": "nose", "child": "left_eye"},
    {"name": "right_eye_offset", "parent": "nose", "child": "right_eye"},
    {"name": "left_ear_offset", "parent": "left_eye", "child": "left_ear"},
    {"name": "right_ear_offset", "parent": "right_eye", "child": "right_ear"},
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


def rest_length(parent: str, child: str) -> float:
    """Length of a declared bone from the rest rig, including derived mids."""
    if parent == "hip_mid" and child == "shoulder_mid":
        return v_norm(REST_OFFSETS["chest"][1])
    if parent == "hip_mid" and child in REST_OFFSETS and REST_OFFSETS[child][0] == "pelvis":
        return v_norm(REST_OFFSETS[child][1])
    if parent == "shoulder_mid" and child == "nose":
        # Not a single rigid bone (neck + head). Callers must not use this as a length.
        raise KeyError("nose is not a fixed-length child of shoulder_mid")
    if child in REST_OFFSETS and REST_OFFSETS[child][0] == parent:
        return v_norm(REST_OFFSETS[child][1])
    # Symmetric girdle / pelvis: distance between two children of the same parent.
    if parent in REST_OFFSETS and child in REST_OFFSETS:
        if REST_OFFSETS[parent][0] == REST_OFFSETS[child][0]:
            return v_norm(v_sub(REST_OFFSETS[parent][1], REST_OFFSETS[child][1]))
    raise KeyError(f"no rest length for {parent} -> {child}")


def length_bones_with_rest() -> list[dict]:
    bones = []
    for bone in LENGTH_BONES:
        item = dict(bone)
        item["length_m"] = rest_length(bone["parent"], bone["child"])
        bones.append(item)
    return bones


def forward_kinematics(local_rotations: Mapping[str, Sequence[float]]) -> dict[str, Vec3]:
    """Joint positions in the body frame. Pelvis starts at the origin.

    Each joint's incoming offset is expressed in its parent's frame. The
    joint's local rotation orients bones that leave it, so bone lengths stay
    equal to the rest offsets.
    """
    rot: dict[str, Quat] = {"pelvis": as_quat(local_rotations.get("pelvis", IDENT_QUAT))}
    pos: dict[str, Vec3] = {"pelvis": (0.0, 0.0, 0.0)}
    for joint in FK_ORDER:
        parent, offset = REST_OFFSETS[joint]
        parent_rot = rot[parent]
        local = as_quat(local_rotations.get(joint, IDENT_QUAT))
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
