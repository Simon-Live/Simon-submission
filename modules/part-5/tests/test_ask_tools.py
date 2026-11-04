"""Ask this take's tools (docs/specs/ask-this-take.md AC-ASK-01 and AC-ASK-02, the hub's AC-1; TICKET-081).

The fixture take is the shipped golden pair, `fixtures/output/analysis.example.json` and `replay.example.json` (one take,
written together). Every expected value here is computed from the file with plain numpy, not through `measures.compute`,
so a tool that read the wrong frame, joint or side would disagree with the file.
"""
import copy
import json
from pathlib import Path

import numpy as np
import pytest

from part5 import api, replay
from part5.ask import agent, tools
from part5.io import JOINTS
from part5.mask import parse_mask

ROOT = Path(__file__).resolve().parents[1]
ANALYSIS = json.loads((ROOT / "fixtures/output/analysis.example.json").read_text())
REPLAY = json.loads((ROOT / "fixtures/output/replay.example.json").read_text())


def golden_take():
    return agent.ask_take(copy.deepcopy(ANALYSIS), copy.deepcopy(REPLAY))


def cut(r, frames):
    """The fields of replay `r` cut to its first `frames` follower frames, a sound replay of another take (its 1.1.0
    `aligned_until` fields say where the cut `exp_to_fol` ends, TICKET-085)."""
    exp_to_fol, follower_t = [min(i, frames - 1) for i in r["exp_to_fol"]], r["follower_t"][:frames]
    return {"follower": r["follower"][:frames], "follower_t": follower_t, "exp_to_fol": exp_to_fol,
            **replay.aligned_until(exp_to_fol, follower_t)}


def call(take, name, **args):
    record, action = tools.run_tool(take, name, json.dumps(args))
    return record, action


def point(frames, f, joint):
    return np.array(frames[f][JOINTS.index(joint)], dtype=float)


def bend(frames, f, a, b, c):
    """180 minus the interior angle at `b`, from the file's points: the knee and elbow bends of the analysis."""
    u, v = point(frames, f, a) - point(frames, f, b), point(frames, f, c) - point(frames, f, b)
    cos = np.dot(u, v) / (np.linalg.norm(u) * np.linalg.norm(v))
    return 180 - np.degrees(np.arccos(np.clip(cos, -1, 1)))


# ---- AC-ASK-01: the tools equal the files (hub AC-1) ----------------------------------------------------------------
def test_ac_ask_01_get_faults_returns_each_field_as_the_analysis_file_holds_it():
    record, action = call(golden_take(), "get_faults")
    result = record["result"]
    assert record["ok"] and action is None and result["count"] == len(ANALYSIS["faults"]) == 2
    for i, (got, fault) in enumerate(zip(result["faults"], ANALYSIS["faults"])):
        assert got["index"] == i
        for key in tools.FAULT_FIELDS:
            assert got.get(key) == fault.get(key), key
        assert "follower_frames" not in got and "runs" not in got   # indexes are not facts a follower reads
    assert result["take"] == {"start_s": REPLAY["follower_t"][0], "end_s": REPLAY["follower_t"][-1]}
    assert result["warnings"] == [w["code"] for w in ANALYSIS.get("warnings", [])]


@pytest.mark.parametrize("joint, parts", [("right_elbow", ("right_shoulder", "right_elbow", "right_wrist")),
                                          ("left_knee", ("left_hip", "left_knee", "left_ankle"))])
def test_ac_ask_01_get_joint_angle_is_the_bend_computed_from_the_replay_frames(joint, parts):
    t0, t1 = 0.5, 1.5
    record, _ = call(golden_take(), "get_joint_angle", joint=joint, t0=t0, t1=t1)
    times = np.array(REPLAY["follower_t"])
    frames = [f for f, t in enumerate(times) if t0 <= t <= t1]
    values = np.array([bend(REPLAY["follower"], f, *parts) for f in frames])
    row = next(r for r in record["result"]["measures"] if r["measure"].endswith("_flexion"))
    assert record["ok"] and record["result"]["frames"] == len(frames) and row["seen_frames"] == len(frames)
    assert (row["min"], row["max"], row["mean"]) == (round(values.min(), 1), round(values.max(), 1),
                                                     round(values.mean(), 1))
    assert row["min_at_s"] == round(times[frames[int(values.argmin())]], 2)
    assert row["max_at_s"] == round(times[frames[int(values.argmax())]], 2)
    assert row["side"] == joint.split("_")[0] and row["unit"] == "degrees"


def test_ac_ask_01_compare_with_teacher_reads_the_frames_the_alignment_pairs():
    t = 0.7
    record, _ = call(golden_take(), "compare_with_teacher", joint="right_elbow", t=t)
    times = np.array(REPLAY["follower_t"])
    f = int(np.argmin(np.abs(times - t)))
    matched = [i for i, g in enumerate(REPLAY["exp_to_fol"]) if g == f]
    e = matched[len(matched) // 2]
    parts = ("right_shoulder", "right_elbow", "right_wrist")
    mine, theirs = bend(REPLAY["follower"], f, *parts), bend(REPLAY["expected"], e, *parts)
    row = next(r for r in record["result"]["measures"] if r["measure"] == "elbow_flexion")
    assert (row["take_deg"], row["example_deg"], row["difference_deg"]) == (round(mine, 1), round(theirs, 1),
                                                                            round(mine - theirs, 1))
    assert record["result"]["take_t_s"] == round(times[f], 2)
    assert record["result"]["example_t_s"] == round(REPLAY["expected_t"][e], 2)


def test_ac_ask_01_a_follower_frame_the_alignment_skips_takes_the_nearest_example_frame():
    take = golden_take()
    shown = set(REPLAY["exp_to_fol"])
    skipped = next(f for f in range(len(REPLAY["follower"])) if f not in shown)
    nearest = int(np.argmin(np.abs(np.array(REPLAY["exp_to_fol"]) - skipped)))
    assert take.example_frame(skipped) == nearest


def test_ac_ask_01_the_ui_tools_return_their_action():
    take = golden_take()
    record, action = call(take, "seek", t=1.9)
    assert record["ok"] and action == record["result"] == {"type": "seek", "t": 1.9, "limb": None}
    record, action = call(take, "spotlight", limb="right_leg", t=1.9)
    assert action == {"type": "spotlight", "t": 1.9, "limb": "right_leg",
                      "joints": ["right_hip", "right_knee", "right_ankle"]}
    assert call(take, "spotlight", limb="left_wrist", t=0)[1]["joints"] == ["left_wrist"]


def test_ac_ask_01_the_take_digest_depends_on_the_tool_data_only():
    a, b = golden_take(), golden_take()
    assert a.sha256() == b.sha256()
    other = copy.deepcopy(ANALYSIS)
    other["score"] = {"value": 1}   # not tool data
    assert agent.ask_take(other, copy.deepcopy(REPLAY)).sha256() == a.sha256()
    other["faults"][0]["magnitude_deg"] = 1.0
    assert agent.ask_take(other, copy.deepcopy(REPLAY)).sha256() != a.sha256()


def test_ac_ask_01_canonical_makes_every_number_a_float_and_leaves_the_rest_alone():
    got = tools.canonical({"a": [1, 2.5, -0.0, 0, True, False, None, "x"], "b": {"c": (3, [4])}})
    assert got == {"a": [1.0, 2.5, 0.0, 0.0, True, False, None, "x"], "b": {"c": [3.0, [4.0]]}}
    numbers = [*got["a"][:4], *got["b"]["c"][:1], *got["b"]["c"][1]]
    assert all(type(n) is float for n in numbers) and str(got["a"][2]) == "0.0"   # -0.0 became the positive zero
    assert got["a"][4] is True and got["a"][5] is False and got["a"][6] is None   # a bool is not turned into 1.0


def test_ac_ask_01_the_digest_ignores_the_type_of_a_number_and_the_sign_of_zero_and_nothing_else():
    """TICKET-100: the page's JSON.stringify writes `6` for `6.0` and `0` for `-0.0`; the digest is of the same take."""
    def digest(analysis=ANALYSIS, **edits):
        replay_doc = copy.deepcopy(REPLAY)
        for key, value in edits.items():
            replay_doc[key][0][0][0] = value
        return agent.ask_take(copy.deepcopy(analysis), replay_doc).sha256()

    assert digest(follower=-0.0) == digest(follower=0.0) == digest(follower=0)
    assert digest(expected=3.0) == digest(expected=3) != digest(expected=3.5)
    tiny = copy.deepcopy(ANALYSIS)
    tiny["faults"][0]["magnitude_deg"] += 1e-9   # no rounding: the least change of a double is a change
    assert digest(tiny) != digest()


# ---- AC-ASK-02: every argument is checked ---------------------------------------------------------------------------
@pytest.mark.parametrize("name, args, error", [
    ("get_joint_angle", {"joint": "elbow", "t0": 0, "t1": 1}, "joint must be a joint of the take"),
    ("get_joint_angle", {"joint": "nose", "t0": 0, "t1": 1}, "no measure is read at that joint; the joints with"),
    ("get_joint_angle", {"joint": "left_wrist", "t0": 0, "t1": 1}, "no measure is read at that joint"),
    ("get_joint_angle", {"joint": "left_knee", "t0": 1, "t1": 0.5}, "t0 must not be after t1"),
    ("get_joint_angle", {"joint": "left_knee", "t0": -1, "t1": 1}, "t0 must be inside the take, 0.00 to 2.50 s"),
    ("get_joint_angle", {"joint": "left_knee", "t0": 0, "t1": "1"}, "t1 must be a number of seconds"),
    ("get_joint_angle", {"joint": "left_knee", "t0": True, "t1": 1}, "t0 must be a number of seconds"),
    ("get_joint_angle", {"joint": "left_knee", "t0": 0}, "t1 must be a number of seconds"),
    ("compare_with_teacher", {"joint": 3, "t": 1}, "joint must be a joint of the take"),
    ("compare_with_teacher", {"joint": "left_knee", "t": 2.6}, "t must be inside the take"),
    ("seek", {"t": 1, "x": 2}, "unknown argument; this tool takes t"),
    ("get_faults", {"joint": "left_knee"}, "unknown argument; this tool takes no argument"),
    ("spotlight", {"limb": "tail", "t": 1}, "limb must be one of left_arm"),
    ("spotlight", {"limb": "left_arm", "t": None}, "t must be a number of seconds"),
])
def test_ac_ask_02_a_bad_argument_is_an_error_result_and_no_action(name, args, error):
    record, action = call(golden_take(), name, **args)
    assert not record["ok"] and action is None and record["result"]["error"].startswith(error)
    assert record["arguments"] == args


@pytest.mark.parametrize("text", ["[1, 2]", "not json", '{"t": NaN}', '{"t": 1e999}', '{"t": Infinity}', "{" * 5000,
                                  '"x"', '{"t": 1' + " " * 2000 + "}"])
def test_ac_ask_02_arguments_that_are_not_one_json_object_of_finite_values_are_refused(text):
    record, action = tools.run_tool(golden_take(), "seek", text)
    assert record == {"name": "seek", "arguments": {}, "ok": False, "result": {"error": tools.ARGUMENTS_NOT_OBJECT}}
    assert action is None
    json.dumps(record, allow_nan=False)   # what is recorded can always be written back


@pytest.mark.parametrize("name, args, said", [
    ("seek", {"87.5": 1}, "87.5"),                          # the review's laundering probe (R1 of the 1.14.0 review)
    ("seek", {"t": 1, "knee 87.5 degrees": 2}, "87.5"),
    ("get_faults", {"x": "a word the model chose"}, "x"),
    ("get_joint_angle", {"joint": "left knee at 87.5", "t0": 0, "t1": 1}, "87.5"),
    ("get_joint_angle", {"joint": "right_eye", "t0": 0, "t1": 1}, "right_eye"),
    ("compare_with_teacher", {"joint": "elbow 12", "t": 1}, "12"),
    ("spotlight", {"limb": "tail 3.25", "t": 1}, "3.25"),
])
def test_r1_an_error_result_never_echoes_text_the_model_sent(name, args, said):
    record, action = call(golden_take(), name, **args)
    error = record["result"]["error"]
    assert not record["ok"] and action is None and record["arguments"] == args
    assert said not in error


@pytest.mark.parametrize("args", [
    {"limb": "see www.example.com now", "t": 1.0},          # the review's probe: a link in a value
    {"Visit www.evil.com for medical advice": 1},          # a link and a banned word in a key
    {"limb": "right_arm‮", "t": 1},                     # a bidi override
    {"limb": "left_arm​", "t": 1},                      # a zero-width space
    {"limb": "your knee pain", "t": 1},                      # a banned word
    {"limb": "Great job", "t": 1},                           # praise
    {"t": 1, "x": [{"y": ["mailto:a@b.co"]}]},               # nested inside a list
])
def test_r1_model_text_the_word_guard_refuses_is_not_run_and_not_recorded(args):
    record, action = call(golden_take(), "spotlight", **args)
    assert record == {"name": "spotlight", "arguments": {}, "ok": False,
                      "result": {"error": tools.ARGUMENTS_NOT_SHOWN}}
    assert action is None


def test_r1_arguments_nested_as_deep_as_the_parser_allows_are_read_without_recursion():
    text = '{"t": ' + "[" * 900 + '"www.a.com"' + "]" * 900 + "}"
    assert len(text) <= tools.MAX_ARGUMENTS_CHARS
    record, _ = tools.run_tool(golden_take(), "seek", text)
    assert record["result"]["error"] in (tools.ARGUMENTS_NOT_SHOWN, tools.ARGUMENTS_NOT_OBJECT)
    assert record["arguments"] == {}


def test_r1_arguments_of_names_and_numbers_pass_the_word_guard():
    assert tools.arguments_shown({"joint": "right_ankle", "t0": 0, "t1": 3.4, "limb": "left_leg"})
    assert all(tools.arguments_shown({"limb": limb}) for limb in (*tools.LIMBS, *JOINTS))


def test_ac_ask_02_empty_arguments_are_no_arguments():
    record, _ = tools.run_tool(golden_take(), "get_faults", "  ")
    assert record["ok"] and record["arguments"] == {}


def test_ac_ask_02_a_time_at_the_edge_of_the_take_is_inside_it():
    end = REPLAY["follower_t"][-1]
    record, _ = call(golden_take(), "get_joint_angle", joint="left_knee", t0=end, t1=end)
    assert record["ok"] and record["result"]["frames"] == 1


def test_ac_ask_02_a_joint_not_seen_reads_null_and_counts_no_frame():
    doc = copy.deepcopy(REPLAY)
    for frame in doc["follower"]:
        frame[JOINTS.index("left_ankle")] = None
    record, _ = call(agent.ask_take(copy.deepcopy(ANALYSIS), doc), "get_joint_angle", joint="left_knee", t0=0, t1=1)
    flexion = next(r for r in record["result"]["measures"] if r["measure"] == "knee_flexion")
    assert flexion["seen_frames"] == 0 and flexion["min"] is None and flexion["max_at_s"] is None
    record, _ = call(agent.ask_take(copy.deepcopy(ANALYSIS), doc), "compare_with_teacher", joint="left_knee", t=1)
    assert all(r["take_deg"] is None and r["difference_deg"] is None for r in record["result"]["measures"])


# ---- the pair a caller sends ----------------------------------------------------------------------------------------
def broken(change):
    analysis, doc = copy.deepcopy(ANALYSIS), copy.deepcopy(REPLAY)
    change(analysis, doc)
    return analysis, doc


@pytest.mark.parametrize("change, field, message", [
    (lambda a, r: a.update(format="other"), "analysis", "analysis: not an analysis"),
    (lambda a, r: a.update(faults=[1]), "analysis", "analysis: a fault is not an object"),
    (lambda a, r: r.update(format="simon.replay.v2"), "replay", "replay: not a replay"),
    (lambda a, r: r.update(joints=r["joints"][::-1]), "replay", "replay: joints are not the 17 canonical joints"),
    (lambda a, r: r["follower"][0].pop(), "replay", "replay: follower is not a list of frames of 17 points"),
    (lambda a, r: r["expected"][0].__setitem__(0, [0, 0, "x"]), "replay", "replay: expected is not a list of frames"),
    (lambda a, r: r.update(follower=[]), "replay", "replay: follower is not a list of frames"),
    (lambda a, r: r["follower_t"].__setitem__(0, True), "replay", "replay: follower_t is not a list of times"),
    (lambda a, r: r["exp_to_fol"].__setitem__(0, 1.5), "replay", "replay: exp_to_fol is not a list of frame indexes"),
    (lambda a, r: r["exp_to_fol"].__setitem__(0, 10_000), "replay", "replay: exp_to_fol[0] is 10000, outside"),
    (lambda a, r: r["follower_t"].__setitem__(1, -1), "replay", "replay: follower_t[1] is -1"),
    (lambda a, r: r.update(cut(r, 10)), "replay",
     "replay: not the replay of this analysis"),
])
def test_a_pair_that_is_not_one_readable_take_is_refused_naming_the_document(change, field, message):
    with pytest.raises(agent.AskError) as caught:
        agent.ask_take(*broken(change))
    assert caught.value.field == field and str(caught.value).startswith(message)


# ---- R3 of the 1.14.0 review: a declared body mask (ADR-0023, TICKET-084) ---------------------------------------------
SEATED_TAKE = {"expected": {"sample": "exercise"}, "follower": {"sample": "exercise_front_good_03_foot_out-right"},
               "mask": "seated"}


@pytest.fixture(scope="module")
def seated():
    """A seated take as Part 5's page gets it: `POST api/analyse` with `mask: "seated"`, its analysis and its replay."""
    status, _, body = api.handle("POST", "/api/analyse", json.dumps(SEATED_TAKE).encode(), base_path="/")
    assert status == 200
    doc = json.loads(body)
    assert doc["analysis"]["body_mask"]["declared"] == ["seated"]
    return doc["analysis"], doc["replay"]


def seated_take(seated):
    return agent.ask_take(*copy.deepcopy(seated))


def test_r3_the_take_reads_the_masked_joints_and_the_measures_not_scored(seated):
    take = seated_take(seated)
    assert take.masked_joints == {"left_knee", "right_knee", "left_ankle", "right_ankle"}
    assert take.not_scored == set(parse_mask("seated").block()["not_scored_measures"])
    assert golden_take().masked_joints == golden_take().not_scored == frozenset()


@pytest.mark.parametrize("name, args", [
    ("get_joint_angle", {"joint": "left_knee", "t0": 0, "t1": 1}),
    ("get_joint_angle", {"joint": "right_ankle", "t0": 0, "t1": 1}),
    ("get_joint_angle", {"joint": "left_hip", "t0": 0, "t1": 1}),       # both hip measures read the masked knee
    ("compare_with_teacher", {"joint": "right_ankle", "t": 1.9}),
    ("compare_with_teacher", {"joint": "right_knee", "t": 1.9}),
])
def test_r3_a_seated_take_gives_no_leg_angle(seated, name, args):
    record, action = call(seated_take(seated), name, **args)
    assert (record["ok"], record["result"], action) == (False, {"error": tools.JOINT_NOT_SCORED}, None)


@pytest.mark.parametrize("limb", ["right_leg", "left_leg", "right_knee", "left_ankle"])
def test_r3_a_seated_take_highlights_no_leg(seated, limb):
    record, action = call(seated_take(seated), "spotlight", limb=limb, t=1.9)
    assert (record["ok"], record["result"], action) == (False, {"error": tools.LIMB_NOT_SCORED}, None)


def test_r3_a_seated_take_still_answers_about_the_body_it_scored(seated):
    take = seated_take(seated)
    record, _ = call(take, "get_joint_angle", joint="right_elbow", t0=0, t1=1)
    assert record["ok"] and [r["measure"] for r in record["result"]["measures"]] == ["elbow_flexion", "forearm_out"]
    assert call(take, "compare_with_teacher", joint="left_shoulder", t=1.9)[0]["ok"]
    assert call(take, "spotlight", limb="torso", t=1.9)[1]["joints"] == list(tools.LIMBS["torso"])
    assert call(take, "spotlight", limb="right_hip", t=1.9)[0]["ok"]
    assert call(take, "get_faults")[0]["result"]["count"] == 0   # the right foot fault is not scored when seated


def bare(mask):
    """An analysis of the golden take with no item that names a measure, and the block of `mask`."""
    return {"format": ANALYSIS["format"], "faults": [], "body_mask": parse_mask(mask).block()}


def test_r3_a_forearm_mask_refuses_the_elbow_and_keeps_the_shoulder():
    take = agent.ask_take(bare("left_forearm"), copy.deepcopy(REPLAY))
    assert call(take, "get_joint_angle", joint="left_elbow", t0=0, t1=1)[0]["result"] == {
        "error": tools.JOINT_NOT_SCORED}
    record, _ = call(take, "get_joint_angle", joint="left_shoulder", t0=0, t1=1)
    assert [r["measure"] for r in record["result"]["measures"]] == ["upper_arm_out", "upper_arm_forward"]
    assert call(take, "spotlight", limb="left_arm", t=1)[0]["result"] == {"error": tools.LIMB_NOT_SCORED}


def test_r3_a_measure_the_mask_drops_at_a_scored_joint_is_left_out():
    take = golden_take()
    take.not_scored = frozenset({"left_forearm_out"})
    record, _ = call(take, "compare_with_teacher", joint="left_elbow", t=1)
    assert [r["measure"] for r in record["result"]["measures"]] == ["elbow_flexion"]


def test_r3_the_digest_names_what_the_mask_leaves_out(seated):
    analysis, replay_doc = copy.deepcopy(seated)
    unmasked = agent.ask_take({k: v for k, v in analysis.items() if k != "body_mask"}, replay_doc)
    assert seated_take(seated).sha256() != unmasked.sha256()
    whole = dict(copy.deepcopy(ANALYSIS), body_mask=parse_mask("full_body").block())
    assert agent.ask_take(whole, copy.deepcopy(REPLAY)).sha256() == golden_take().sha256()
    assert agent.ask_take(bare("left_forearm"), copy.deepcopy(REPLAY)).sha256() != agent.ask_take(
        dict(bare("left_forearm"), body_mask=None), copy.deepcopy(REPLAY)).sha256()


@pytest.mark.parametrize("block", [5, {"declared": ["seated"], "source": "api"},
                                   dict(parse_mask("seated").block(), masked_joints=[]),
                                   dict(parse_mask("seated").block(), declared=["tail"])])
def test_r3_a_body_mask_that_fails_the_analysis_check_is_refused(block):
    with pytest.raises(agent.AskError) as caught:
        agent.ask_take(dict(bare("seated"), body_mask=block), copy.deepcopy(REPLAY))
    assert caught.value.field == "analysis" and str(caught.value).startswith("analysis: body_mask")


def test_r3_a_mask_whose_measure_a_fault_names_is_refused():
    with pytest.raises(agent.AskError, match="analysis: faults"):
        agent.ask_take(dict(copy.deepcopy(ANALYSIS), body_mask=parse_mask("right_arm").block()), copy.deepcopy(REPLAY))
