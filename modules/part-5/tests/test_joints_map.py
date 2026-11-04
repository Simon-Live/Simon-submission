"""AC-009: canonical joints per fault (ADR-0006)."""
from types import SimpleNamespace

import pytest

from part5.detect import generic
from part5.io import JOINTS
from part5.joints_map import PAIRED, VIRTUAL, fault_joints
from part5.measures import MEASURES
from part5.output import fault_to_dict

SHOULDERS = ["left_shoulder", "right_shoulder"]
HIPS = ["left_hip", "right_hip"]


def strip_side(joint):
    return joint.split("_", 1)[1] if joint.startswith(("left_", "right_")) else joint


def fault(measure, side, joint, body_part="legs"):
    return {"measure": measure, "side": side, "joint": joint, "body_part": body_part}


def every_measure_and_side():
    """(measure, side, joint as `output` names it, body part) for every measure and valid side."""
    cases = []
    for name, spec in MEASURES.items():
        measure, side = generic(name)
        if side == "center":
            cases.append((measure, "center", spec.joint, spec.body_part))
            continue
        cases.append((measure, side, spec.joint, spec.body_part))
        if side == "left":
            cases.append((measure, "right", spec.joint.replace("left_", "right_"), spec.body_part))
            cases.append((measure, "both", strip_side(spec.joint), spec.body_part))
    # knee_valgus is added to MEASURES by the movement guard work; it must map the day it lands.
    cases += [("knee_valgus", "left", "left_knee", "legs"), ("knee_valgus", "right", "right_knee", "legs"),
              ("knee_valgus", "both", "knee", "legs")]
    return cases


CASES = every_measure_and_side()


@pytest.mark.parametrize("measure,side,joint,body_part", CASES)
def test_ac009_every_measure_and_side_maps_to_canonical_joints(measure, side, joint, body_part):
    joints = fault_joints(fault(measure, side, joint, body_part))
    assert joints, "never empty"
    assert set(joints) <= set(JOINTS), "every name is one of the 17"
    assert len(joints) == len(set(joints)), "no duplicates"


@pytest.mark.parametrize("measure,side,joint,body_part", [c for c in CASES if c[1] in ("left", "right")])
def test_ac009_a_sided_joint_is_itself(measure, side, joint, body_part):
    assert fault_joints(fault(measure, side, joint)) == [joint]


@pytest.mark.parametrize("measure,side,joint,body_part", [c for c in CASES if c[1] == "both"])
def test_ac009_side_both_gives_left_and_right(measure, side, joint, body_part):
    assert fault_joints(fault(measure, side, joint)) == [f"left_{joint}", f"right_{joint}"]


def test_ac009_the_cases_cover_the_measures_the_pipeline_reports():
    measures = {c[0] for c in CASES}
    assert {generic(n)[0] for n in MEASURES} <= measures
    assert {"knee_valgus", "foot_out", "upper_arm_out", "trunk_lean_forward", "head_forward"} <= measures


@pytest.mark.parametrize("joint,expected", [
    ("spine", SHOULDERS + HIPS),
    ("shoulders", SHOULDERS),
    ("neck", ["nose"] + SHOULDERS),
    ("shoulder_mid", SHOULDERS),
    ("hip_mid", HIPS),
    ("head", ["nose"] + SHOULDERS),
])
def test_ac009_virtual_joints_follow_adr_0006(joint, expected):
    assert fault_joints(fault("trunk_lean_forward", "center", joint, "torso")) == expected


def test_ac009_centre_measures_map_through_output_too():
    # The real fault objects `output` builds, not hand-made dicts.
    for measure in ("trunk_lean_forward", "trunk_lean_side", "shoulder_tilt", "head_forward"):
        built = fault_to_dict(SimpleNamespace(
            measure=measure, side="center", joint=MEASURES[measure].joint, body_part=MEASURES[measure].body_part,
            direction="more", magnitude_deg=20.0, peak_deg=25.0, threshold_deg=10.0,
            expected_frames=(1, 9), follower_frames=(1, 9), runs=((1, 9),), phase=(0.1, 0.5), coverage=1.0,
            confidence=0.9))
        assert set(fault_joints(built)) <= set(JOINTS)


def test_ac009_every_virtual_name_and_paired_joint_resolves():
    assert all(set(names) <= set(JOINTS) for names in VIRTUAL.values())
    assert set(PAIRED) == {"eye", "ear", "shoulder", "elbow", "wrist", "hip", "knee", "ankle"}
    assert fault_joints(fault("foot_out", "left", "ankle")) == ["left_ankle"]
    assert fault_joints(fault("foot_out", "right", "ankle")) == ["right_ankle"]


def test_a_sided_joint_with_side_both_still_gives_the_pair():
    assert fault_joints(fault("knee_valgus", "both", "left_knee")) == ["left_knee", "right_knee"]


def test_the_nose_is_itself():
    assert fault_joints(fault("head_forward", "center", "nose")) == ["nose"]


@pytest.mark.parametrize("joint,side", [("elbow", "center"), ("elbow", "centre"), ("toe", "left"), (None, "left"),
                                        ("", "both")])
def test_an_unmapped_joint_is_loud_not_empty(joint, side):
    with pytest.raises(ValueError, match="no canonical joints"):
        fault_joints(fault("upper_arm_out", side, joint))


def test_the_result_is_a_fresh_list_each_call():
    first = fault_joints(fault("trunk_lean_forward", "center", "spine"))
    first.append("nose")
    assert fault_joints(fault("trunk_lean_forward", "center", "spine")) == SHOULDERS + HIPS
