"""part6/motion.py: the squat equals the input fixtures; every family is plausible."""
import json
import math
from pathlib import Path

import pytest

from part6 import motion, processor

ROOT = Path(__file__).resolve().parents[2]
INPUT = ROOT / "fixtures" / "input"
PARAMS = motion.MotionParams(period_s=2.0, reps=2)
SAMPLES = [i / 30 for i in range(120)]


def test_six_families_two_categories():
    assert list(motion.FAMILIES) == ["squat", "forward-lunge", "jumping-jack", "side-step",
                                     "arm-wave", "hip-twist"]
    assert [f.id for f in motion.by_category("exercise")] == ["squat", "forward-lunge",
                                                              "jumping-jack"]
    assert [f.id for f in motion.by_category("dance")] == ["side-step", "arm-wave", "hip-twist"]


def test_body_constants_match_the_input_fixture_generator():
    import importlib.util
    spec = importlib.util.spec_from_file_location("make_fixtures", INPUT / "make_fixtures.py")
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    for name in ("HIP_HALF", "SHOULDER_HALF", "THIGH", "SHANK", "TRUNK", "UPPER_ARM", "FOREARM"):
        assert getattr(motion, name) == getattr(fixture, name), name
    assert list(motion.JOINTS) == fixture.JOINTS


def test_squat_reproduces_the_input_fixtures_frame_for_frame():
    out = processor.generate("squat", 10000, motion.MotionParams(3.0, 3, 0.5))
    animation = json.loads((INPUT / "animation.json").read_text())
    skeleton = json.loads((INPUT / "skeleton.json").read_text())
    keyframes = json.loads((INPUT / "keyframes.json").read_text())
    assert out["animation"]["frames"] == animation["frames"]
    assert out["skeleton"]["frames"] == skeleton["frames"]
    assert out["skeleton"]["bone_lengths_m"] == skeleton["bone_lengths_m"]
    assert out["keyframes"]["people"] == keyframes["people"]


@pytest.mark.parametrize("family", motion.FAMILIES)
def test_joint_shape_and_order(family):
    joints = motion.pose(family, 0.7, PARAMS)
    assert list(joints) == list(motion.JOINTS)
    for joint in joints.values():
        assert set(joint) == {"x", "y", "z", "conf"} and joint["conf"] == 1.0
        assert all(math.isfinite(joint[k]) for k in "xyz")


@pytest.mark.parametrize("family", motion.FAMILIES)
def test_bone_lengths_are_fixed(family):
    lengths = [processor._bone_lengths(motion.pose(family, t, PARAMS)) for t in SAMPLES]
    for bone in lengths[0]:
        values = [frame[bone] for frame in lengths]
        assert (max(values) - min(values)) / lengths[0][bone] < 0.01, bone


@pytest.mark.parametrize("family", motion.FAMILIES)
def test_feet_on_the_floor_and_nothing_below_it(family):
    """The frame has no translation, so the floor is the lowest ankle of each frame."""
    for t in SAMPLES:
        joints = motion.pose(family, t, PARAMS)
        floor = min(joints["left_ankle"]["y"], joints["right_ankle"]["y"])
        assert min(j["y"] for j in joints.values()) >= floor - 1e-9
        assert abs(joints["left_ankle"]["y"] - joints["right_ankle"]["y"]) <= 0.1 + 1e-9


@pytest.mark.parametrize("family", motion.FAMILIES)
def test_body_orientation_holds(family):
    for t in SAMPLES:
        j = motion.pose(family, t, PARAMS)
        assert j["left_hip"]["x"] > 0 > j["right_hip"]["x"]
        assert j["nose"]["z"] > j["left_ear"]["z"] - 1e-9
        assert j["nose"]["y"] > j["left_shoulder"]["y"] > j["left_hip"]["y"]


@pytest.mark.parametrize("family", motion.FAMILIES)
def test_the_movement_moves_and_rests_outside_its_repetitions(family):
    poses = [motion.pose(family, t, PARAMS) for t in SAMPLES]
    assert any(p != poses[0] for p in poses)
    late = motion.MotionParams(period_s=2.0, reps=1, start_s=1.0)
    assert motion.pose(family, 0.0, late) == motion.pose(family, 3.5, late)


def test_signature_of_each_movement():
    p = motion.MotionParams(period_s=2.0, reps=2)
    mid = {f: motion.pose(f, 1.0, p) for f in motion.FAMILIES}   # middle of repetition 1
    squat = mid["squat"]
    assert squat["left_knee"]["z"] > 0.3 and squat["left_ankle"]["y"] > -0.6
    lunge = mid["forward-lunge"]
    assert lunge["left_ankle"]["z"] - lunge["right_ankle"]["z"] > 0.5
    jack = mid["jumping-jack"]
    assert jack["left_wrist"]["y"] > jack["nose"]["y"] and jack["left_ankle"]["x"] > 0.3
    wave = mid["arm-wave"]
    assert wave["left_wrist"]["y"] > wave["nose"]["y"]
    step = motion.pose("side-step", 1.0, p)
    assert abs(step["left_ankle"]["x"] - step["right_ankle"]["x"]) > 0.4
    twist = mid["hip-twist"]
    assert abs(twist["left_hip"]["z"]) > 0.03


def test_amplitude_parameters_change_the_pose():
    base = dict(period_s=2.0, reps=2)
    for family, field in (("squat", "depth"), ("squat", "arm"), ("forward-lunge", "depth"),
                          ("forward-lunge", "step"), ("jumping-jack", "arm"),
                          ("jumping-jack", "step"), ("side-step", "step"), ("arm-wave", "arm"),
                          ("hip-twist", "step")):
        full = motion.pose(family, 1.0, motion.MotionParams(**base))
        less = motion.pose(family, 1.0, motion.MotionParams(**base, **{field: 0.7}))
        assert full != less, (family, field)


def test_tempo_changes_when_the_peak_happens():
    fast = motion.MotionParams(period_s=1.0, reps=4)
    slow = motion.MotionParams(period_s=2.0, reps=2)
    assert motion.pose("jumping-jack", 0.5, fast) == motion.pose("jumping-jack", 1.0, slow)
