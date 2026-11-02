"""Compare only what the camera sees (ADR-0011, AC-VIS-1 to AC-VIS-5)."""
import json
from pathlib import Path

import numpy as np
import pytest

from part5 import cli
from part5.io import JOINTS
from part5.measures import MEASURES, VIEW_MEASURES
from part5.pipeline import run
from part5.score_report import score_block
from part5.visibility import (MIN_USABLE_MEASURES, MOVING_RANGE_DEG, UNSEEN_CONF, load_conf, moving_text,
                              resolve, seen_mask, usable_from_conf)

ROOT = Path(__file__).resolve().parent.parent
EXPECTED = ROOT / "fixtures/input/expected/exercise/animation.json"
FOLLOWERS = ROOT / "fixtures/input/followers/exercise"
SALUTE = ROOT / "tests/local/selfie-salute"
RAISE = ROOT / "fixtures/input/real/lateral-raise/pexels-40297504/animation.json"
HIPS_AND_LEGS = ["left_hip", "right_hip", "left_knee", "right_knee", "left_ankle", "right_ankle"]
HEAD_ONLY = [j for j in JOINTS if j not in ("nose", "left_eye", "right_eye")]
needs_salute = pytest.mark.skipif(not (SALUTE / "follower.json").exists(),
                                  reason="the operator's own recording is local only (tests/local, never published)")


def follower(name):
    return next(FOLLOWERS.glob(f"{name}*/skeleton.json"))


def with_unseen(path, joints):
    """A ref carrying the clip's JSON with `joints` marked outside the image (conf 0.3) in every frame."""
    doc = json.loads(Path(path).read_text())
    for fr in doc.get("frames") or doc["keyframes"]:
        fr["conf"] = {j: (UNSEEN_CONF if j in joints else 1.0) for j in JOINTS}
    return {"path": str(path), "doc": doc}


def conf_with(unseen, frames=10):
    c = np.ones((frames, len(JOINTS)))
    for j in unseen:
        c[:, JOINTS.index(j)] = UNSEEN_CONF
    return c


# --- the rule ---------------------------------------------------------------------------------

def test_a_clip_without_conf_has_unknown_visibility():
    assert usable_from_conf(None) is None
    vis = resolve(None, None)
    assert vis.full and vis.excluded == [] and vis.enough


def test_every_joint_seen_leaves_every_measure_usable():
    vis = resolve(usable_from_conf(np.ones((5, 17))))
    assert vis.full and set(vis.usable) == set(MEASURES) | set(VIEW_MEASURES)


def test_the_far_side_of_a_side_view_is_still_compared():
    """Only one of a left/right pair is marked 0.3 (occluded, not cropped): the old behaviour stays."""
    far = ["right_elbow", "right_wrist", "right_knee", "right_ankle"]
    assert seen_mask(conf_with(far)).all()
    assert resolve(usable_from_conf(conf_with(far))).full


def test_both_sides_outside_the_image_exclude_the_measures_that_read_them():
    vis = resolve(usable_from_conf(conf_with(HIPS_AND_LEGS)))
    assert not vis.full and vis.enough
    assert "left_knee_flexion" in vis.excluded and "trunk_lean_forward" in vis.excluded
    assert {"left_elbow_flexion", "right_forearm_out", "shoulder_tilt"} <= set(vis.usable)


def test_a_measure_needs_its_joints_in_80_percent_of_the_frames():
    conf = conf_with(["left_wrist", "right_wrist"], frames=10)
    conf[:3, JOINTS.index("left_wrist")] = 1.0      # seen in 3 of 10 frames
    assert "left_elbow_flexion" not in usable_from_conf(conf)
    conf = conf_with(["left_wrist", "right_wrist"], frames=10)
    conf[:8, JOINTS.index("left_wrist")] = 1.0      # seen in 8 of 10 frames
    assert "left_elbow_flexion" in usable_from_conf(conf)


def test_the_two_clips_intersect_and_an_unknown_one_defers():
    arms = usable_from_conf(conf_with(HIPS_AND_LEGS))
    head = usable_from_conf(conf_with([j for j in JOINTS if "ear" not in j and j != "nose"]))
    both = resolve(arms, head)
    assert set(both.usable) == set(arms) & set(head)
    assert resolve(arms, None).usable == resolve(arms).usable


def test_the_trainers_skeleton_gives_the_expected_clips_visibility(tmp_path):
    doc = {"frames": [{"frame": i, "people": [{"id": 0, "joints": {
        j: {"x": 0, "y": 0, "z": 0, "conf": UNSEEN_CONF if j in HIPS_AND_LEGS else 1.0} for j in JOINTS}}]}
        for i in range(4)]}
    path = tmp_path / "pose3d.json"
    path.write_text(json.dumps(doc))
    usable = usable_from_conf(load_conf(path))
    assert "left_knee_flexion" not in usable and "left_elbow_flexion" in usable


def test_a_skeleton_without_conf_gives_no_visibility(tmp_path):
    path = tmp_path / "s.json"
    path.write_text(json.dumps({"frames": [{"joints": {}}]}))
    assert load_conf(path) is None and usable_from_conf(load_conf(path)) is None


# --- the pipeline -----------------------------------------------------------------------------

def test_a_full_body_pair_is_unchanged_and_carries_no_visibility():
    plain = run(str(EXPECTED), str(follower("exercise_45_good_02"))).analysis
    marked = run(str(EXPECTED), with_unseen(follower("exercise_45_good_02"), [])).analysis
    assert "visibility" not in plain["diagnostics"] and plain["schema_version"] == "1.13.0"
    assert marked["faults"] == plain["faults"] and marked["diagnostics"] == plain["diagnostics"]


def test_an_upper_body_take_of_the_squat_is_accepted_with_its_arm_faults_only():
    take = follower("exercise_45_good_02")    # arms wider on one side
    full = run(str(EXPECTED), str(take)).analysis
    cut = run(str(EXPECTED), with_unseen(take, HIPS_AND_LEGS), score=lambda r: {"value": 1}).analysis
    assert cut["status"]["code"] == "ok" and cut["schema_version"] == "1.13.0"
    vis = cut["diagnostics"]["visibility"]
    assert "left_knee_flexion" in vis["excluded"] and "rule" in vis
    assert vis["usable_measures"] >= MIN_USABLE_MEASURES
    assert {f["body_part"] for f in cut["faults"]} <= {"arms", "torso", "head"}
    assert any(f["measure"] == "upper_arm_out" for f in full["faults"])
    assert any(f["measure"] == "upper_arm_out" for f in cut["faults"])
    assert cut["score"] == {"value": 1}


def test_invented_legs_are_not_faults():
    take = follower("exercise_45_good_04")    # knees shallow
    assert any(f["body_part"] == "legs" for f in run(str(EXPECTED), str(take)).analysis["faults"])
    cut = run(str(EXPECTED), with_unseen(take, HIPS_AND_LEGS)).analysis
    assert cut["status"]["code"] == "ok"
    assert not [f for f in cut["faults"] if f["body_part"] == "legs"]


def test_the_expected_clips_own_visibility_narrows_the_pair(tmp_path):
    doc = {"frames": [{"people": [{"joints": {j: {"conf": UNSEEN_CONF if j in HIPS_AND_LEGS else 1.0}
                                              for j in JOINTS}}]} for _ in range(3)]}
    path = tmp_path / "skeleton.json"
    path.write_text(json.dumps(doc))
    take = follower("exercise_45_good_00")
    a = run(str(EXPECTED), str(take), expected_visibility=str(path)).analysis
    assert a["status"]["code"] == "ok" and "left_knee_flexion" in a["diagnostics"]["visibility"]["excluded"]


def test_a_head_only_clip_is_not_enough_visible(tmp_path):
    ref = with_unseen(follower("exercise_45_good_00"), HEAD_ONLY + ["left_ear", "right_ear"])
    res = run(str(EXPECTED), ref, score=score_block)
    a = res.analysis
    assert a["status"]["code"] == "ok" and a["score"]["grade"] == "F" and a["score"]["value"] <= 59
    assert "not_enough_visible" in a["score"]["capped_by"] and a["schema_version"] == "1.13.0"
    assert "not_enough_visible" in [w["code"] for w in a["warnings"]]
    assert "more of the body" in next(w["text"] for w in a["warnings"] if w["code"] == "not_enough_visible")
    assert a["diagnostics"]["visibility"]["usable_measures"] < MIN_USABLE_MEASURES
    assert res.alignment is not None   # ADR-0012: a replay still plays


def test_cli_exits_0_for_not_enough_visible_and_takes_expected_visibility(tmp_path, capsys):
    path = tmp_path / "head.json"
    doc = with_unseen(follower("exercise_45_good_00"), HEAD_ONLY + ["left_ear", "right_ear"])["doc"]
    path.write_text(json.dumps(doc))
    out = tmp_path / "a.json"
    assert cli.main(["analyse", "--expected", str(EXPECTED), "--follower", str(path), "--out", str(out)]) == 0
    assert "not_enough_visible" in [w["code"] for w in json.loads(out.read_text())["warnings"]]
    assert "more of the body" in capsys.readouterr().out
    out2 = tmp_path / "b.json"
    assert cli.main(["analyse", "--expected", str(EXPECTED), "--follower", str(follower("exercise_45_good_00")),
                     "--expected-visibility", str(tmp_path / "missing.json"), "--out", str(out2)]) == 1


# --- the operator's own selfie salute (local only) ---------------------------------------------

@needs_salute
def test_the_salute_trainer_shows_head_shoulders_and_the_raised_wrist():
    usable = usable_from_conf(load_conf(SALUTE / "trainer-skeleton.json"))
    assert "left_knee_flexion" not in usable and "shoulder_tilt" in usable


@needs_salute
def test_the_salute_against_a_different_upper_body_movement_is_a_low_match():
    """The real lateral raise cut to the upper body (hips and legs at conf 0.3) is not a salute."""
    ref = with_unseen(RAISE, HIPS_AND_LEGS)
    a = run(str(SALUTE / "expected.json"), ref,
            expected_visibility=str(SALUTE / "trainer-skeleton.json")).analysis
    assert a["status"]["code"] == "ok" and "low_match" in [w["code"] for w in a["warnings"]]


@needs_salute
def test_the_salute_no_longer_compares_invented_legs():
    a = run(str(SALUTE / "expected.json"), str(SALUTE / "follower.json"),
            expected_visibility=str(SALUTE / "trainer-skeleton.json")).analysis
    vis = a["diagnostics"]["visibility"]
    assert "right_thigh_forward" in vis["excluded"] and "right_foot_out" in vis["excluded"]


@needs_salute
def test_the_salute_pair_names_the_right_arm_as_out_of_frame():
    """AC-VIS-5: the arm the example moves is not in the take: a `moving_part_out_of_frame` warning, grade F (ADR-0012)."""
    res = run(str(SALUTE / "expected.json"), str(SALUTE / "follower.json"),
              expected_visibility=str(SALUTE / "trainer-skeleton.json"), score=score_block)
    a = res.analysis
    assert a["status"]["code"] == "ok" and a["score"]["grade"] == "F" and a["score"]["value"] <= 59
    text = next(w["text"] for w in a["warnings"] if w["code"] == "moving_part_out_of_frame")
    assert text.startswith("Your right arm is mostly out of frame, so it can't be compared.")
    assert "left" not in text and "leg" not in text
    vis = a["diagnostics"]["visibility"]
    assert vis["moving_measures"] and vis["moving_usable"] == [] and a["schema_version"] == "1.13.0"
    assert all(m.startswith("right_") for m in vis["moving_measures"])


@needs_salute
def test_the_salute_cli_exits_0_with_the_warning_text(tmp_path, capsys):
    out = tmp_path / "a.json"
    assert cli.main(["analyse", "--expected", str(SALUTE / "expected.json"), "--follower", str(SALUTE / "follower.json"),
                     "--expected-visibility", str(SALUTE / "trainer-skeleton.json"), "--out", str(out)]) == 0
    assert "right arm" in capsys.readouterr().out


def test_the_text_names_the_part_the_example_moves():
    assert moving_text(["right_wrist_height"]).startswith("Your right arm is mostly out of frame, so it can't")
    assert "Your arms are mostly out of frame, so they can't" in moving_text(["left_elbow_flexion", "right_wrist_out"])
    assert "legs" in moving_text(["left_knee_flexion", "right_knee_flexion"])
    assert moving_text(["head_roll"]).startswith("Your head and shoulders are mostly out of frame")
    assert MOVING_RANGE_DEG == 20.0


def test_a_take_that_shows_some_moving_part_is_still_compared():
    """The squat moves arms and legs; with the legs unseen the arms still carry it (no moving-part refusal)."""
    a = run(str(EXPECTED), with_unseen(follower("exercise_45_good_00"), HIPS_AND_LEGS)).analysis
    assert a["status"]["code"] == "ok"
    vis = a["diagnostics"]["visibility"]
    assert vis["moving_usable"] and set(vis["moving_usable"]) <= set(vis["moving_measures"])
