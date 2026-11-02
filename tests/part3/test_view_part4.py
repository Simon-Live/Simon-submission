"""The part4 view on the real Part 2 squat (AC-P02, AC-P03, AC-P04, AC-NFR-001, TICKET-025)."""

import copy
import json
import math
import re
import time

import numpy as np
import pytest

import part4rules as p4
from clipkit import real_skeleton
from part3 import cli, rig
from part3.joints import JOINTS
from part3.schema import ContractError, FrameCapError, LongWayError, OptionError, ViewError
from part3.views import part4
from runapikit import TAKE_1, across_the_body, take1_with_arms

NATIVE_KEYS_TO_CHECK = ("schema", "units", "frame", "joints", "bones", "standard", "bone_lengths_m",
                        "person", "mirror", "input", "frames")


def part1_for(skeleton, fps=60.0):
    """A Part 1 style file on the video clock: one person, two squat repetitions over the clip's time range."""
    t0, t_last = skeleton["frames"][0]["t_ms"], skeleton["frames"][-1]["t_ms"]

    def key(name, share):
        t_ms = round(t0 + share * (t_last - t0), 3)
        return {"name": name, "frame": round(t_ms * fps / 1000), "t_ms": t_ms}

    rep1 = [key("stand", 0.0), key("descend", 0.12), key("bottom", 0.25), key("ascend", 0.38), key("stand", 0.49)]
    rep2 = [key("stand", 0.51), key("descend", 0.62), key("bottom", 0.75), key("ascend", 0.88), key("stand", 1.0)]
    return {"video": "squat.mp4", "fps": fps, "analysis_fps": 15.0, "quality": {"ok": True},
            "people": [{"id": 0, "repetitions": [{"rep": 1, "movement": "squat", "keyframes": rep1},
                                                 {"rep": 2, "movement": "squat", "keyframes": rep2}]}]}


@pytest.fixture(scope="module")
def skeleton():
    return real_skeleton()


@pytest.fixture(scope="module")
def keyed(skeleton):
    keyframes = part1_for(skeleton)
    return part4.render(copy.deepcopy(skeleton), keyframes=keyframes), keyframes


@pytest.fixture(scope="module")
def rendered(keyed):
    return keyed[0]


def native_joints(frame):
    person = frame["people"][0]["joints"]
    return {j: [person[j]["x"], person[j]["y"], person[j]["z"]] for j in JOINTS}


def frame_by_number(skeleton, number):
    return next(f for f in skeleton["frames"] if f["frame"] == number)


# --- the module's face -------------------------------------------------------------------------

def test_module_constants_and_signature():
    assert part4.NAME == "part4"
    assert part4.SCHEMA == "skeleton-part4.schema.json"
    assert isinstance(part4.DESCRIPTION, str) and part4.DESCRIPTION


def test_render_ignores_options_it_does_not_know(skeleton):
    out = part4.render(skeleton, keyframes="every:50", keyframes_person=None, fps=None, unknown=1)
    assert out["format"] == "simon.skeleton.v1"


# --- AC-P02: the squat with Part 1 style keyframes ----------------------------------------------

def test_p02_the_file_meets_part4s_input_rules(rendered):
    assert p4.violations(rendered, part4.keyframes_doc(rendered)) == []


def test_p02_each_key_joints_equal_the_forward_kinematics_of_its_rotations_within_1_mm(rendered):
    offsets = rendered["rest_offsets_m"]
    assert rendered["keyframes"]
    for key in rendered["keyframes"]:
        ours = rig.forward(key["local_rotations"], offsets)
        for joint in JOINTS:
            assert np.linalg.norm(ours[joint] - key["joints"][joint]) < 1e-3, (key["index"], joint)
        assert p4.key_fk_error(key, offsets) < 1e-3
        assert p4.key_fk_error(key, offsets) < 5e-6  # only the 6 decimal rounding is left


def test_p02_timeline_and_key_times(rendered):
    timeline = rendered["timeline"]
    assert (timeline["fps"], timeline["frame_count"], timeline["t0_ms"]) == (30, 213, 0.0)
    assert timeline["frame_count"] == round(timeline["duration_s"] * 30) + 1
    assert (timeline["source_kind"], timeline["person"], timeline["dropped"]) == ("part1", 0, [])
    indices = [k["index"] for k in rendered["keyframes"]]
    assert indices == sorted(set(indices)) and 0 <= indices[0] and indices[-1] <= 212
    shares = (0.0, 0.12, 0.25, 0.38, 0.49, 0.51, 0.62, 0.75, 0.88, 1.0)
    assert indices == [round(round(s * 7066.667, 3) * 30 / 1000) for s in shares]
    assert indices[:4] == [0, 25, 53, 81] and indices[-1] == 212
    for key in rendered["keyframes"]:
        assert abs(key["t"] - key["index"] / 30) <= 1e-6
    assert [k["name"] for k in rendered["keyframes"]][:3] == ["stand", "descend", "bottom"]


def test_p02_rest_offsets_parents_match_the_hierarchy_and_use_the_skeletons_lengths(rendered):
    offsets = rendered["rest_offsets_m"]
    assert list(offsets) == list(rig.FK_ORDER)
    for joint, entry in offsets.items():
        assert entry["parent"] == rig.HIERARCHY[joint]
        assert all(round(v, 6) == v for v in entry["offset"])
    lengths = rendered["bone_lengths_m"]
    assert offsets["left_knee"]["offset"] == [0.0, -lengths["left_thigh"], 0.0]
    assert offsets["neck"]["offset"] == [0.0, lengths["spine"], 0.0]
    assert np.linalg.norm(offsets["nose"]["offset"]) == pytest.approx(lengths["head"], abs=1e-6)


def test_p02_the_part4_fields_and_the_canonical_joints_list(rendered):
    assert rendered["format"] == "simon.skeleton.v1"
    assert rendered["root_joint"] == "pelvis" and rendered["virtual_joints"] == ["pelvis", "neck"]
    assert rendered["coordinate_frame"] == {"origin": "hip_midpoint", "x": "subject_left", "y": "world_up",
                                            "z": "anterior", "position_unit": "metres", "angle_unit": "degrees"}
    assert rendered["joints"] == list(JOINTS) == list(p4.CANONICAL)
    assert rendered["rig"]["convention"] == rig.CONVENTION
    for key in rendered["keyframes"]:
        assert list(key) == ["index", "t", "name", "source_frame", "source_t_ms", "joints", "conf",
                             "local_rotations"]
        assert list(key["joints"]) == list(JOINTS) and list(key["conf"]) == list(JOINTS)
        assert list(key["local_rotations"]) == list(rig.ROTATED)
        assert key["t"] == round(key["index"] / 30, 6)


def test_p02_rotations_are_unit_quaternions_with_w_not_negative_at_6_decimals(rendered):
    for key in rendered["keyframes"]:
        for joint, q in key["local_rotations"].items():
            assert len(q) == 4 and q[3] >= 0, joint
            assert all(round(v, 6) == v for v in q)
            assert math.sqrt(sum(v * v for v in q)) == pytest.approx(1.0, abs=2e-6)
        for joint, p in key["joints"].items():
            assert len(p) == 3 and all(round(v, 6) == v for v in p)


def test_p02_key_joints_keep_the_rig_bone_lengths_and_the_hip_midpoint_at_the_origin(rendered):
    offsets = rendered["rest_offsets_m"]
    edges = [("left_knee", "left_hip"), ("left_ankle", "left_knee"), ("right_knee", "right_hip"),
             ("right_ankle", "right_knee"), ("left_elbow", "left_shoulder"), ("left_wrist", "left_elbow"),
             ("right_elbow", "right_shoulder"), ("right_wrist", "right_elbow"), ("left_eye", "nose"),
             ("right_eye", "nose"), ("left_ear", "left_eye"), ("right_ear", "right_eye")]
    for key in rendered["keyframes"]:
        joints = {j: np.array(p) for j, p in key["joints"].items()}
        for child, parent in edges:
            length = np.linalg.norm(joints[child] - joints[parent])
            assert length == pytest.approx(np.linalg.norm(offsets[child]["offset"]), abs=1e-4)
        assert np.linalg.norm(0.5 * (joints["left_hip"] + joints["right_hip"])) < 1e-5


def test_p02_rig_fit_reports_the_residual_against_the_native_frames(skeleton, rendered):
    distances, worst = [], (-1.0, None, None)
    for key in rendered["keyframes"]:
        native = np.array(list(native_joints(frame_by_number(skeleton, key["source_frame"])).values()))
        native = native - 0.5 * (native[JOINTS.index("left_hip")] + native[JOINTS.index("right_hip")])
        for i, joint in enumerate(JOINTS):
            gap = float(np.linalg.norm(np.array(key["joints"][joint]) - native[i]))
            distances.append(gap)
            if gap > worst[0]:
                worst = (gap, joint, key["index"])
    fit = rendered["rig"]["fit"]
    assert set(fit) == {"max_m", "mean_m", "worst_joint", "worst_index"}
    assert fit["max_m"] == pytest.approx(max(distances), abs=2e-6)
    assert fit["mean_m"] == pytest.approx(sum(distances) / len(distances), abs=2e-6)
    assert (fit["worst_joint"], fit["worst_index"]) == worst[1:]
    assert 0 < fit["max_m"] < 0.01  # the rig keeps the hip line, spine and head rigid; the squat fits within 1 cm


def test_p02_each_key_pose_comes_from_the_native_frame_nearest_in_time(skeleton, rendered):
    present = [(f["t_ms"], f) for f in skeleton["frames"] if f["people"]]
    for key in rendered["keyframes"]:
        target = key["index"] * 1000 / 30
        gaps = [abs(t - target) for t, _ in present]
        nearest = present[gaps.index(min(gaps))][1]  # index() returns the earlier frame on a tie
        assert key["source_frame"] == nearest["frame"] and key["source_t_ms"] == nearest["t_ms"]
        assert key["conf"] == {j: nearest["people"][0]["joints"][j]["conf"] for j in JOINTS}


def test_p02_a_tie_in_time_goes_to_the_earlier_frame(skeleton):
    three = copy.deepcopy(skeleton)
    three["frames"] = three["frames"][:3]
    for frame, t_ms in zip(three["frames"], (0.0, 50.0, 150.0)):
        frame["t_ms"] = t_ms
    # tick 3 is at 100 ms: 50 ms from the second frame and 50 ms from the third
    out = part4.render(three, keyframes={"format": "simon.keyframes.v1", "fps": 30, "keyframes": [
        {"index": 3, "t": 0.1, "name": "mid"}]})
    assert out["keyframes"][0]["source_frame"] == three["frames"][1]["frame"]
    assert out["keyframes"][0]["source_t_ms"] == 50.0


def test_p02_the_native_document_is_unchanged_and_the_render_is_a_new_object(skeleton):
    before = copy.deepcopy(skeleton)
    out = part4.render(skeleton, keyframes="every:20")
    assert skeleton == before and out is not skeleton
    for name in NATIVE_KEYS_TO_CHECK:
        assert out[name] == before[name], name
    out["frames"][0]["people"][0]["joints"]["nose"]["x"] = 99.0
    out["bone_lengths_m"]["head"] = 9.0
    assert skeleton == before


def test_p02_the_render_is_deterministic_and_plain_json(skeleton):
    first = json.dumps(part4.render(skeleton, keyframes="every:10"), allow_nan=False)
    second = json.dumps(part4.render(skeleton, keyframes="every:10"), allow_nan=False)
    assert first == second


def test_p02_a_scaled_body_still_meets_part4s_rules_and_the_residual_scales_with_it(skeleton):
    scale = 1.85 / 1.70
    big = copy.deepcopy(skeleton)
    big["bone_lengths_m"] = {k: round(v * scale, 4) for k, v in big["bone_lengths_m"].items()}
    for frame in big["frames"]:
        for person in frame["people"]:
            for point in person["joints"].values():
                for axis in "xyz":
                    point[axis] = round(point[axis] * scale, 4)
    small = part4.render(skeleton, keyframes="every:10")
    large = part4.render(big, keyframes="every:10")
    assert p4.violations(large, part4.keyframes_doc(large)) == []
    assert large["rig"]["fit"]["max_m"] == pytest.approx(small["rig"]["fit"]["max_m"] * scale, rel=0.05)


def test_p02_absent_person_frames_are_never_a_key_source(skeleton):
    gappy = copy.deepcopy(skeleton)
    for frame in gappy["frames"][40:60]:
        frame["people"] = []
    out = part4.render(gappy, keyframes="every:5")
    sources = {k["source_frame"] for k in out["keyframes"]}
    absent = {f["frame"] for f in gappy["frames"] if not f["people"]}
    assert sources and not sources & absent


def test_p02_a_one_frame_clip_has_one_key_at_index_0(skeleton):
    one = copy.deepcopy(skeleton)
    one["frames"] = one["frames"][:1]
    out = part4.render(one, keyframes="every:10")
    assert [k["index"] for k in out["keyframes"]] == [0]
    assert (out["timeline"]["frame_count"], out["timeline"]["duration_s"]) == (1, 0.0)
    assert p4.violations(out, part4.keyframes_doc(out)) == []


# --- AC-P03: sources and the companion ---------------------------------------------------------

def test_p03_every_10_keys_every_tenth_tick_and_the_last(skeleton):
    out = part4.render(skeleton, keyframes="every:10")
    assert [k["index"] for k in out["keyframes"]] == list(range(0, 211, 10)) + [212]
    assert out["timeline"]["source_kind"] == "every" and out["timeline"]["person"] is None
    assert p4.violations(out, part4.keyframes_doc(out)) == []


def test_p03_part4_keyframes_keep_their_index_and_name(skeleton):
    doc = {"format": "simon.keyframes.v1", "fps": 30, "duration_s": 7.066667, "frame_count": 213,
           "keyframes": [{"index": i, "t": round(i / 30, 6), "name": n}
                         for i, n in ((0, "stand"), (60, "bottom"), (212, "stand"))]}
    out = part4.render(skeleton, keyframes=doc)
    assert [(k["index"], k["name"]) for k in out["keyframes"]] == [(0, "stand"), (60, "bottom"), (212, "stand")]
    assert out["timeline"]["source_kind"] == "part4"
    assert p4.violations(out, part4.keyframes_doc(out)) == []


def test_p03_dropped_keys_are_listed_with_reasons_and_leave_the_keyframes_list(skeleton):
    part1 = part1_for(skeleton)
    reps = part1["people"][0]["repetitions"]
    reps[0]["keyframes"] += [{"name": "ghost", "frame": 9000, "t_ms": 150000.0},
                             {"name": "twin", "frame": 1, "t_ms": 1.0}]
    out = part4.render(skeleton, keyframes=part1)
    dropped = out["timeline"]["dropped"]
    assert [d["name"] for d in dropped] == ["twin", "ghost"]
    assert all(d["reason"] and set(d) == {"name", "t_ms", "reason"} for d in dropped)
    assert "ghost" not in [k["name"] for k in out["keyframes"]]
    assert len(out["keyframes"]) == 10


def test_p03_keyframes_doc_lists_the_same_indices_as_keyframes(keyed):
    rendered, _ = keyed
    doc = part4.keyframes_doc(rendered)
    assert doc["format"] == "simon.keyframes.v1" and doc["producer"] == "part3"
    assert (doc["fps"], doc["frame_count"], doc["duration_s"]) == (30, 213, rendered["timeline"]["duration_s"])
    assert [k["index"] for k in doc["keyframes"]] == [k["index"] for k in rendered["keyframes"]]
    assert doc["keyframes"] == [{"index": k["index"], "t": k["t"], "name": k["name"]}
                                for k in rendered["keyframes"]]
    assert set(doc) == {"format", "producer", "fps", "duration_s", "frame_count", "keyframes"}
    json.dumps(doc, allow_nan=False)


def test_p03_keyframes_may_be_a_path_or_a_string_path(tmp_path, skeleton):
    path = tmp_path / "keyframes.json"
    path.write_text(json.dumps(part1_for(skeleton)))
    as_path, as_text = part4.render(skeleton, keyframes=path), part4.render(skeleton, keyframes=str(path))
    assert [k["index"] for k in as_path["keyframes"]] == [k["index"] for k in as_text["keyframes"]]
    assert len(as_path["keyframes"]) == 10


def test_p03_keyframes_person_selects_the_part1_person(skeleton):
    part1 = part1_for(skeleton)
    second = copy.deepcopy(part1["people"][0])
    second["id"] = "b"
    second["repetitions"] = second["repetitions"][:1]
    part1["people"].append(second)
    assert len(part4.render(skeleton, keyframes=part1)["keyframes"]) == 10
    out = part4.render(skeleton, keyframes=part1, keyframes_person="b")
    assert len(out["keyframes"]) == 5 and out["timeline"]["person"] == "b"


# --- AC-P04: errors ----------------------------------------------------------------------------

def test_p04_without_keyframes_the_error_names_the_option(skeleton):
    for missing in ({}, {"keyframes": None}):
        with pytest.raises(ContractError) as caught:
            part4.render(skeleton, **missing)
        assert isinstance(caught.value, ViewError) and not isinstance(caught.value, OptionError)
        assert str(caught.value) == "--view part4 needs --keyframes <keyframes.json> or every:<n>"
        assert caught.value.page_text == "This clip cannot be written as Part 4 keys. Choose another View."


def test_p04_an_unreadable_unknown_or_empty_keyframes_file_names_the_path(tmp_path, skeleton):
    gone = tmp_path / "gone.json"
    with pytest.raises(ContractError, match=f"{gone}: cannot read"):
        part4.render(skeleton, keyframes=str(gone))
    odd = tmp_path / "odd.json"
    odd.write_text(json.dumps({"hello": 1}))
    with pytest.raises(ContractError) as unknown:
        part4.render(skeleton, keyframes=odd)
    assert str(unknown.value) == f"{odd}: not a Part 1 or Part 4 keyframes file"
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps({"format": "simon.keyframes.v1", "fps": 30,
                                   "keyframes": [{"index": 9999, "t": 333.3, "name": "far"}]}))
    with pytest.raises(ContractError) as empty:
        part4.render(skeleton, keyframes=outside)
    assert str(empty.value) == f"{outside}: no keyframe falls inside the clip (0 to 7066.667 ms)"


def test_p04_a_bad_every_value_and_an_absent_person_exit_with_a_message(skeleton):
    with pytest.raises(ContractError, match="--keyframes every:0: n must be a whole number from 1 to 300"):
        part4.render(skeleton, keyframes="every:0")
    with pytest.raises(ContractError, match=r"--keyframes-person 5: not in keyframes \(ids: 0\)"):
        part4.render(skeleton, keyframes=part1_for(skeleton), keyframes_person=5)


# --- AC-NFR-001 ---------------------------------------------------------------------------------

def test_nfr001_process_and_render_every_tick_stay_under_two_seconds():
    from conftest import REAL_CLIP
    doc = json.loads(REAL_CLIP.read_text())
    start = time.perf_counter()
    out = part4.render(cli.process(doc), keyframes="every:1")
    elapsed = time.perf_counter() - start
    assert len(out["keyframes"]) == 213
    assert elapsed < 2.0, f"{elapsed:.2f} s"


# --- review B2: Part 4's long-way rule ---------------------------------------------------------------------------
#
# Part 3 fits every key on its own, so an arm passing overhead used to flip its rotation axis between two keys and
# Part 4 refused the file (the old rest pose had the arms hanging). The T-pose rest keeps those arms clear of the
# 180 degree turn, and the view checks its own keys against Part 4's rule instead of writing a file Part 4 rejects.

CLEAN = {"env": {}, "config": False}
LONG_WAY = re.compile(r"^--view part4: Part 4 would reject this clip: (\w+) turns (\d+\.\d) degrees between keys "
                      r"(\d+) and (\d+) \(Part 4 allows 180\); add keys between them \(a smaller every:<n>\) "
                      r"or use another view$")


def overhead(side, u):
    """Both arms swept in the sagittal plane from 120 to 240 degrees from hanging, through overhead (180)."""
    angle = math.radians(120.0 + 120.0 * u)
    return (0.0, -math.cos(angle), math.sin(angle))


@pytest.fixture(scope="module")
def overhead_skeleton():
    return cli.process(take1_with_arms(overhead), **CLEAN)


@pytest.mark.parametrize("every", ["every:10", "every:3", "every:1"])
def test_b2_an_arm_swept_overhead_renders_and_meets_part4s_long_way_rule(overhead_skeleton, every):
    out = part4.render(overhead_skeleton, keyframes=every)
    assert rig.long_way(out["keyframes"], out["rest_offsets_m"]) == []
    assert p4.long_way_steps(out["keyframes"], out["rest_offsets_m"]) == []
    assert p4.violations(out, part4.keyframes_doc(out)) == []
    assert out["rig"]["fit"]["max_m"] < 0.01  # the sweep is also followed within 1 cm


def test_b2_the_old_hanging_rest_pose_is_what_made_this_sweep_fail(overhead_skeleton, monkeypatch):
    real = rig.rest_offsets

    def hanging(lengths):
        offsets = real(lengths)
        for side in ("left", "right"):
            offsets[f"{side}_elbow"]["offset"] = [0.0, -lengths[f"{side}_upper_arm"], 0.0]
            offsets[f"{side}_wrist"]["offset"] = [0.0, -lengths[f"{side}_forearm"], 0.0]
        return offsets

    monkeypatch.setattr(rig, "rest_offsets", hanging)
    with pytest.raises(ContractError) as caught:
        part4.render(overhead_skeleton, keyframes="every:10")
    match = LONG_WAY.match(str(caught.value))
    assert match and match.group(1) in ("left_shoulder", "right_shoulder") and float(match.group(2)) > 180.0


def test_b2_an_arm_swept_across_the_body_is_refused_with_the_joint_and_both_keys():
    skeleton = cli.process(take1_with_arms(across_the_body), **CLEAN)
    with pytest.raises(LongWayError) as caught:
        part4.render(skeleton, keyframes="every:10")
    match = LONG_WAY.match(str(caught.value))
    assert match, str(caught.value)
    assert (caught.value.joint, caught.value.from_index, caught.value.to_index) == ("left_shoulder", 110, 120)
    joint, degrees, first, second = match.groups()
    assert (joint, int(first), int(second)) == ("left_shoulder", 110, 120) and float(degrees) > 180.0
    assert caught.value.path == "--view part4"
    assert caught.value.msg.endswith("; add keys between them (a smaller every:<n>) or use another view")


def static_clip(skeleton, ticks=31):
    """The squat's first frame repeated once per 30 fps tick: the same body at ticks 0 to `ticks - 1`."""
    clip = copy.deepcopy(skeleton)
    first = clip["frames"][0]
    clip["frames"] = []
    for tick in range(ticks):
        frame = copy.deepcopy(first)
        frame["frame"], frame["t_ms"] = tick, round(tick * 1000.0 / 30, 3)
        clip["frames"].append(frame)
    return clip


def put_left_arm(frame, upper, forearm, lengths):
    joints = frame["people"][0]["joints"]
    shoulder = np.array([joints["left_shoulder"][a] for a in "xyz"])
    elbow = shoulder + lengths["left_upper_arm"] * np.asarray(upper)
    wrist = elbow + lengths["left_forearm"] * np.asarray(forearm)
    for name, point in (("left_elbow", elbow), ("left_wrist", wrist)):
        joints[name].update(dict(zip("xyz", map(float, point))))


def spun_forearm_clip(skeleton, spin_degrees):
    """The left arm out to the side, the elbow bent 120 degrees; the forearm is spun about the upper arm by
    `spin_degrees` between tick 0 and tick 30 (a curl with a twist)."""
    clip = static_clip(skeleton)
    bent = np.array([math.cos(math.radians(120)), 0.0, math.sin(math.radians(120))])
    angle = math.radians(spin_degrees)
    about_x = np.array([[1, 0, 0], [0, math.cos(angle), -math.sin(angle)], [0, math.sin(angle), math.cos(angle)]])
    for frame, forearm in ((clip["frames"][0], bent), (clip["frames"][30], about_x @ bent)):
        put_left_arm(frame, (1.0, 0.0, 0.0), forearm, clip["bone_lengths_m"])
    return clip


TICKS_0_AND_30 = {"format": "simon.keyframes.v1", "fps": 30, "keyframes": [
    {"index": 0, "t": 0.0, "name": "start"}, {"index": 30, "t": 1.0, "name": "end"}]}


def test_b2_a_forearm_spun_past_180_degrees_about_the_upper_arm_is_taken_by_the_shoulder_twist(skeleton):
    """Twist continuity (ASM-020): the shoulder turns about the upper arm, so the elbow keeps its axis
    and Part 4's rule holds; before stitching this clip was refused (left_elbow, keys 0 and 30)."""
    out = part4.render(spun_forearm_clip(skeleton, 190.0), keyframes=TICKS_0_AND_30)
    assert rig.long_way(out["keyframes"], out["rest_offsets_m"]) == [] and p4.violations(out, part4.keyframes_doc(out)) == []


def test_b2_a_small_spin_of_the_same_forearm_is_not_over_the_limit(skeleton):
    out = part4.render(spun_forearm_clip(skeleton, 20.0), keyframes=TICKS_0_AND_30)
    assert rig.long_way(out["keyframes"], out["rest_offsets_m"]) == [] and p4.violations(out, part4.keyframes_doc(out)) == []


@pytest.mark.parametrize("build", ["across"])
def test_b2_the_independent_part4_rules_flag_the_step_the_view_refuses(skeleton, monkeypatch, build):
    """Switch the view's own check off and run the rendered file through part4rules (separate code)."""
    if build == "spun":
        clip, keys, joint, span = spun_forearm_clip(skeleton, 190.0), TICKS_0_AND_30, "left_elbow", (0, 30)
    else:
        clip, keys, joint, span = (cli.process(take1_with_arms(across_the_body), **CLEAN), "every:10",
                                   "left_shoulder", (110, 120))
    monkeypatch.setattr(part4, "_check_long_way", lambda keys, offsets=None: None)
    out = part4.render(clip, keyframes=keys)
    found = [step for step in p4.long_way_steps(out["keyframes"], out["rest_offsets_m"]) if step[0] == joint]
    assert [(a, b) for _, a, b, _ in found] == [span]
    assert any(v.startswith(f"{joint} takes the long way between keys {span[0]} and {span[1]}")
               for v in p4.violations(out, part4.keyframes_doc(out)))
    ours = [s for s in rig.long_way(out["keyframes"], out["rest_offsets_m"]) if s["joint"] == joint]
    assert [(s["from_index"], s["to_index"]) for s in ours] == [span]
    assert found[0][3] == pytest.approx(ours[0]["deg"], abs=0.1)


def test_b2_the_cli_refuses_the_clip_with_exit_2_and_writes_neither_file(tmp_path, capsys):
    source = tmp_path / "pose3d.json"
    source.write_text(json.dumps(take1_with_arms(across_the_body)))
    out, companion = tmp_path / "skeleton.json", tmp_path / "keyframes.json"
    code = cli.main(["run", "--in", str(source), "--out", str(out), "--view", "part4", "--keyframes", "every:10",
                     "--keyframes-out", str(companion)])
    err = capsys.readouterr().err.strip()
    assert code == 2 and LONG_WAY.match(err) and "left_shoulder" in err and "between keys 110 and 120" in err
    assert not out.exists() and not companion.exists()


def test_the_cli_says_what_it_said_for_a_part4_view_with_no_keys_and_for_keys_on_another_view(tmp_path, capsys):
    """TICKET-033: the refusals became typed (ViewError); the command line's stderr text and exit code did not."""
    source = tmp_path / "pose3d.json"
    source.write_text(TAKE_1.read_text())
    for args, message in ((["--view", "part4"], "--view part4 needs --keyframes <keyframes.json> or every:<n>"),
                          (["--view", "part5", "--keyframes", "every:10"],
                           "--keyframes: only applies to --view part4 (the view is part5)")):
        code = cli.main(["run", "--in", str(source), "--out", str(tmp_path / "skeleton.json"), *args])
        captured = capsys.readouterr()
        assert (code, captured.out, captured.err) == (2, "", message + "\n")
    assert not (tmp_path / "skeleton.json").exists()


# --- review B1: the part4 timeline is capped -----------------------------------------------------------------------

def test_b1_a_clip_whose_span_would_make_too_long_a_timeline_is_refused(skeleton):
    long_clip = copy.deepcopy(skeleton)
    long_clip["frames"][-1]["t_ms"] = 10_000_000.0
    with pytest.raises(FrameCapError) as caught:
        part4.render(long_clip, keyframes="every:10")
    assert str(caught.value) == "--keyframes: the 30 fps timeline would have 300001 ticks; the limit is 100000"
    assert (caught.value.path, isinstance(caught.value, OptionError)) == ("--keyframes", True)
    assert caught.value.timeline is True  # the attribute the run app tells the key timeline's cap by
    with pytest.raises(ContractError, match=r"the limit is 20000$"):
        part4.render(long_clip, keyframes="every:10", max_frames=20_000)
    long_clip["frames"][-1]["t_ms"] = 1e300
    with pytest.raises(ContractError, match=r"would have 3e\+298 ticks"):
        part4.render(long_clip, keyframes="every:10")


# --- keys where the person is missing (stitching 2026-10-28, ASM-021) ----------------------------

def test_a_key_inside_a_gap_without_the_person_is_dropped_with_the_reason(skeleton):
    gapped = copy.deepcopy(skeleton)
    for frame in gapped["frames"][20:40]:
        frame["people"] = []
    rendered = part4.render(gapped, keyframes="every:10")
    gap_from, gap_to = gapped["frames"][20]["t_ms"], gapped["frames"][39]["t_ms"]
    t0 = gapped["frames"][0]["t_ms"]
    dropped = [d for d in rendered["timeline"]["dropped"] if d["reason"] == part4.GAP_REASON]
    assert dropped and all(gap_from - 1 <= d["t_ms"] <= gap_to + 1 for d in dropped)
    for key in rendered["keyframes"]:
        assert abs(key["source_t_ms"] - (t0 + key["index"] * 1000 / 30)) <= 1000 / 15 / 2 + 1


def test_every_key_in_a_gap_exits_with_a_contract_error(skeleton):
    gapped = copy.deepcopy(skeleton)
    for frame in gapped["frames"][1:-1]:
        frame["people"] = []
    with pytest.raises(ContractError):
        part4.render(gapped, keyframes={"format": "simon.keyframes.v1", "fps": 30,
                                        "keyframes": [{"index": 100, "t": 100 / 30, "name": "mid"}]})


def test_the_part4_view_writes_fps_30_at_the_top(rendered):
    """Part 5 reads a top-level fps (found by the Part 5 contract helper, 2026-10-28)."""
    assert rendered["fps"] == 30
    assert all(abs(k["t"] - k["index"] / rendered["fps"]) <= 1e-6 for k in rendered["keyframes"])
