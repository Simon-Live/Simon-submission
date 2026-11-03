"""Bone mapping: names, presets, VRM, topology and the chain rule (docs/specs/model-import.md; AC-MI7 to AC-MI10)."""

from __future__ import annotations

import os
from pathlib import Path
import sys

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "fixtures" / "models"))

import glbmaker  # noqa: E402
from part7 import bone_map, glb_inspect  # noqa: E402

SCRATCH = os.environ.get("MODEL_FIXTURES_DIR")
REQUIRED = set(bone_map.REQUIRED)


def mapped(blob: bytes) -> bone_map.MapResult:
    report = glb_inspect.inspect_bytes(blob)
    return bone_map.map_result(report.gltf, report.positions())


@pytest.mark.parametrize("raw, expected", [
    ("mixamorig:LeftUpLeg", ("upleg", "left")), ("mixamorig9:RightForeArm", ("forearm", "right")),
    ("DEF-thigh.L", ("thigh", "left")), ("ORG-upper_arm.R", ("upperarm", "right")), ("Armature|Hips", ("hips", None)),
    ("J_Bip_L_UpperArm", ("upperarm", "left")), ("J_Bip_C_Spine", ("spine", None)), ("Bip01 L Thigh", ("thigh", "left")),
    ("CC_Base_R_Calf", ("calf", "right")), ("calf_l", ("calf", "left")), ("Foot.R", ("foot", "right")),
    ("Left_Arm", ("arm", "left")), ("spine_02", ("spine02", None)), ("Hips", ("hips", None)), ("L_Hand", ("hand", "left")),
])
def test_split_name(raw: str, expected: tuple[str, str | None]) -> None:
    assert bone_map.split_name(raw) == expected


@pytest.mark.parametrize("names, method", [
    (glbmaker.MIXAMO, "preset:mixamo"), (glbmaker.UE5, "preset:ue5"), (glbmaker.RIGIFY, "preset:rigify"),
    (glbmaker.BLENDER_LR, "preset:blender_lr"), (glbmaker.UNITY, "preset:unity"), (None, "preset:simon-avatar"),
])
def test_presets_map_all_required_bones(names: dict | None, method: str) -> None:
    res = mapped(glbmaker.humanoid(names))
    assert res.method == method and res.missing == [] and REQUIRED <= set(res.bones)
    assert res.bones["hips"] == 0 and res.bones["leftUpperArm"] != res.bones["rightUpperArm"]


def test_left_and_right_follow_the_names_not_the_position() -> None:
    swapped = {**glbmaker.MIXAMO}
    for part, name in (("UpperArm", "Arm"), ("LowerArm", "ForeArm"), ("Hand", "Hand")):  # the +X arm is called Right
        swapped[f"left{part}"], swapped[f"right{part}"] = f"mixamorig:Right{name}", f"mixamorig:Left{name}"
    res = mapped(glbmaker.humanoid(swapped))
    report = glb_inspect.inspect_bytes(glbmaker.humanoid(swapped))
    assert report.names[res.bones["rightUpperArm"]] == "mixamorig:RightArm"  # the name wins although that node sits at +X
    assert report.position(res.bones["rightUpperArm"])[0] > 0


def test_topology_maps_unnamed_rigs() -> None:
    names = {c: f"joint_{i}" for i, c in enumerate(glbmaker.ORDER)}
    res = mapped(glbmaker.humanoid(names))
    assert res.method == "topology" and res.missing == []
    expect = {c: i for i, c in enumerate(glbmaker.ORDER)}
    for c in REQUIRED:
        assert res.bones[c] == expect[c], c


def test_topology_sides_follow_rest_x_and_works_when_rotated() -> None:
    names = {c: f"joint_{i}" for i, c in enumerate(glbmaker.ORDER)}
    res = mapped(glbmaker.humanoid(names, up="z"))
    assert res.method == "topology" and res.bones["leftHand"] == glbmaker.ORDER.index("leftHand")


def test_topology_without_a_three_way_split_finds_nothing() -> None:
    names = {c: f"joint_{i}" for i, c in enumerate(glbmaker.ORDER)}
    res = mapped(glbmaker.humanoid(names, skip=("leftUpperLeg", "leftLowerLeg", "leftFoot")))
    assert res.missing and "leftFoot" in res.missing


def test_vrm_1_table_wins_over_names() -> None:
    blob = glbmaker.humanoid(glbmaker.MIXAMO)
    report = glb_inspect.inspect_bytes(blob)
    table = {c: {"node": i} for i, c in enumerate(glbmaker.ORDER)}
    res = bone_map.map_result({**report.gltf, "extensions": {"VRMC_vrm": {"humanoid": {"humanBones": table}}}}, report.positions())
    assert res.method == "vrm" and res.bones["head"] == glbmaker.ORDER.index("head")
    assert bone_map.vrm_version({"extensions": {"VRMC_vrm": {}}}) == "1"


def test_vrm_0_table() -> None:
    report = glb_inspect.inspect_bytes(glbmaker.humanoid())
    table = [{"bone": c, "node": i} for i, c in enumerate(glbmaker.ORDER)]
    res = bone_map.map_result({**report.gltf, "extensions": {"VRM": {"humanoid": {"humanBones": table}}}}, report.positions())
    assert res.method == "vrm" and bone_map.vrm_version({"extensions": {"VRM": {}}}) == "0"
    assert bone_map.vrm_version({}) is None


def test_foot_not_under_lower_leg_is_refused_with_a_named_reason() -> None:
    # the RobotExpressive case: the foot is a sibling of the body, not a child of the lower leg
    res = mapped(glbmaker.humanoid(glbmaker.BLENDER_LR, parents={"leftFoot": "hips"}))
    assert "leftFoot" in res.missing
    assert res.problems == ["leftFoot is not under leftLowerLeg"]


def test_hand_not_under_lower_arm_and_lower_leg_not_under_upper_leg() -> None:
    res = mapped(glbmaker.humanoid(glbmaker.UE5, parents={"rightHand": "chest", "rightLowerLeg": "hips"}))
    assert {"rightHand", "rightLowerLeg", "rightFoot"} <= set(res.missing)
    assert "rightHand is not under rightLowerArm" in res.problems and "rightLowerLeg is not under rightUpperLeg" in res.problems


def test_only_skin_joints_are_candidates() -> None:
    # plain nodes named like bones (RobotExpressive nodes 4, 7, 13) are never picked
    decoys = [{"name": "mixamorig:Hips"}, {"name": "mixamorig:LeftFoot"}]
    res = mapped(glbmaker.humanoid(glbmaker.MIXAMO, extra_nodes=decoys))
    assert res.method == "preset:mixamo" and res.bones["hips"] == 0
    assert all(node < len(glbmaker.ORDER) for node in res.bones.values())


def test_duplicate_names_pick_the_shallowest_joint() -> None:
    names = {**glbmaker.UE5, "chest": "pelvis"}  # a second 'pelvis' deeper in the tree
    assert mapped(glbmaker.humanoid(names)).bones["hips"] == 0


def test_missing_bones_are_listed_and_map_bones_returns_a_triple() -> None:
    blob = glbmaker.humanoid(glbmaker.MIXAMO, skip=("leftHand", "rightHand"))
    report = glb_inspect.inspect_bytes(blob)
    bones, method, missing = bone_map.map_bones(report.gltf, report.positions())
    assert set(missing) == {"leftHand", "rightHand"} and "hips" in bones and method.startswith("preset:")


def test_no_skeleton_at_all() -> None:
    res = bone_map.map_result({"nodes": [{"name": "Cube"}]}, [(0, 0, 0)])
    assert res.method == "none" or res.missing == list(bone_map.REQUIRED)
    assert set(res.missing) == REQUIRED


@pytest.mark.skipif(not SCRATCH, reason="MODEL_FIXTURES_DIR not set")
@pytest.mark.parametrize("rel, method, vrm", [
    ("threejs-xbot/Xbot.glb", "preset:mixamo", None), ("threejs-michelle/Michelle.glb", "preset:mixamo", None),
    ("threejs-soldier/Soldier.glb", "preset:mixamo", None), ("khronos-cesiumman/CesiumMan.glb", "topology", None),
    ("khronos-riggedfigure/RiggedFigure.glb", "topology", None), ("vrm-seed-san/Seed-san.vrm", "vrm", "1"),
])
def test_real_models(rel: str, method: str, vrm: str | None) -> None:
    report = glb_inspect.inspect(Path(SCRATCH) / rel)
    res = bone_map.map_result(report.gltf, report.positions())
    assert res.method == method and res.missing == [] and bone_map.vrm_version(report.gltf) == vrm


@pytest.mark.skipif(not SCRATCH, reason="MODEL_FIXTURES_DIR not set")
@pytest.mark.parametrize("pattern, method", [("quaternius-ual1/extracted/*/Godot/*.glb", "preset:rigify"),
                                             ("quaternius-ual2/extracted/*/Female*/Unreal-Godot/Mannequin_F.glb", "preset:ue5")])
def test_real_quaternius_models(pattern: str, method: str) -> None:
    path = next((Path(SCRATCH)).glob(pattern))
    report = glb_inspect.inspect(path)
    res = bone_map.map_result(report.gltf, report.positions())
    assert res.method == method and res.missing == []


@pytest.mark.skipif(not SCRATCH, reason="MODEL_FIXTURES_DIR not set")
def test_robot_expressive_is_the_negative_fixture() -> None:
    report = glb_inspect.inspect(Path(SCRATCH) / "quaternius-robotexpressive" / "RobotExpressive.glb")
    res = bone_map.map_result(report.gltf, report.positions())
    assert "leftFoot is not under leftLowerLeg" in res.problems and "leftFoot" in res.missing
