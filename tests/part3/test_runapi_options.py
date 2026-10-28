"""The run options and the views of the run app (docs/specs/run-app.md, docs/specs/compare-mode.md AC-M01, AC-M02,
review R1): option parsing, how the options reach the pipeline, a View that refuses the clip, and the parity of the
page's download with the command line. The samples, one run and the error table are in test_runapi.py."""

import ast
import json
import math
import pathlib
import re
import subprocess
import sys
import types

import numpy as np
import pytest

from clipkit import equal_times
from conftest import ROOT
from part3 import cli, io, profiles, runapi, views
from part3.angles import joint_angles
from part3.metrics import BONE_MAX
from part3.schema import ContractError, LongWayError, ViewError
from runapikit import (REPLY_KEYS, TAKE_1, across_the_body, clip, code_of, file_of, options_for, run_sample,
                       take1_with_arms, upload)

# ---- AC-M01, AC-M02: the run options -----------------------------------------------------------

DEFAULTS = {"body": None, "stature": None, "view": "native", "fps": None}  # body None: the View's default (ASM-012)
BAD_BODY = "Body must be blank, simon-standard, part4-rig or measured."


def test_parse_options_defaults_when_nothing_is_given():
    assert runapi.parse_options({}) == (DEFAULTS, None)
    assert runapi.parse_options("") == (DEFAULTS, None)
    assert runapi.parse_options("sample=take-1&flip=on") == (DEFAULTS, None)


@pytest.mark.parametrize("query, expected", [
    ("body=part4-rig", {"body": "part4-rig"}),
    ("body=measured", {"body": "measured"}),
    ("body=simon-standard", {"body": "simon-standard"}),
    ("body=", {"body": None}),
    ("stature=1.85", {"stature": 1.85}),
    ("stature=0.5", {"stature": 0.5}),
    ("stature=2.5", {"stature": 2.5}),
    ("stature=2", {"stature": 2.0}),
    ("stature=", {"stature": None}),
    ("view=part4", {"view": "part4"}),
    ("view=part5", {"view": "part5"}),
    ("view=native", {"view": "native"}),
    ("fps=30", {"fps": 30}),
    ("fps=60", {"fps": 60}),
    ("fps=", {"fps": None}),
    ("body=part4-rig&stature=1.6&view=part5&fps=60&sample=take-1",
     {"body": "part4-rig", "stature": 1.6, "view": "part5", "fps": 60}),
    ("body=measured&body=part4-rig", {"body": "measured"}),  # the first value of a repeated field wins
])
def test_parse_options_accepts_every_documented_value(query, expected):
    options, failure = runapi.parse_options(query)
    assert failure is None and options == {**DEFAULTS, **expected}


@pytest.mark.parametrize("query, code, field, message", [
    ("body=file:/etc/passwd", "bad_body", "body", BAD_BODY),
    ("body=file:part3/standard_body.json", "bad_body", "body", BAD_BODY),
    ("body=nonsense", "bad_body", "body", BAD_BODY),
    ("body=Part4-rig", "bad_body", "body", BAD_BODY),
    ("stature=0.49", "bad_stature", "stature", "Height must be blank or 0.5 to 2.5 m."),
    ("stature=2.51", "bad_stature", "stature", "Height must be blank or 0.5 to 2.5 m."),
    ("stature=nan", "bad_stature", "stature", "Height must be blank or 0.5 to 2.5 m."),
    ("stature=inf", "bad_stature", "stature", "Height must be blank or 0.5 to 2.5 m."),
    ("stature=1e0", "bad_stature", "stature", "Height must be blank or 0.5 to 2.5 m."),
    ("stature=-1.7", "bad_stature", "stature", "Height must be blank or 0.5 to 2.5 m."),
    ("stature=1,8", "bad_stature", "stature", "Height must be blank or 0.5 to 2.5 m."),
    ("stature=tall", "bad_stature", "stature", "Height must be blank or 0.5 to 2.5 m."),
    ("view=part6", "bad_view", "view", "View must be native, part4 or part5."),
    ("view=", "bad_view", "view", "View must be native, part4 or part5."),
    ("view=file:x", "bad_view", "view", "View must be native, part4 or part5."),
    ("fps=45", "bad_fps", "fps", "Frame rate must be blank, 30 or 60."),
    ("fps=30.0", "bad_fps", "fps", "Frame rate must be blank, 30 or 60."),
    ("fps=030", "bad_fps", "fps", "Frame rate must be blank, 30 or 60."),
    ("fps=abc", "bad_fps", "fps", "Frame rate must be blank, 30 or 60."),
])
def test_parse_options_refuses_anything_else_naming_the_field(query, code, field, message):
    options, failure = runapi.parse_options(query)
    assert options is None
    status, body = failure
    assert (status, body["ok"]) == (400, False)
    assert body["error"] == {"code": code, "field": field, "message": message}


def test_parse_options_checks_the_body_before_the_other_fields():
    assert runapi.parse_options("body=x&view=y&fps=1&stature=9")[1][1]["error"]["code"] == "bad_body"


def test_parse_query_keeps_the_first_value_and_refuses_a_flood_of_fields():
    assert runapi.parse_query("a=1&a=2&b=&c=%20x") == {"a": "1", "b": "", "c": " x"}
    with pytest.raises(ValueError):
        runapi.parse_query("a=1&" * 30)


def test_the_error_table_has_the_option_codes_and_plain_ascii_messages():
    for code in ("bad_body", "bad_stature", "bad_view", "bad_fps", "compare_count", "compare_shape", "compare_size"):
        status, message = runapi.ERRORS[code]
        assert status == 400 and message.endswith(".") and message.isascii(), code
    assert runapi.error("compare_count", reason="Compare needs 2 to 6 inputs.")[1]["error"]["message"] == (
        "Compare needs 2 to 6 inputs.")


def test_the_allowed_bodies_are_three_named_profiles_and_never_a_path():
    assert runapi.BODIES == ("simon-standard", "part4-rig", "measured")
    assert not any(name.startswith("file:") or "/" in name for name in runapi.BODIES)
    assert runapi.VIEWS == ("native", "part4", "part5") and runapi.FPS_VALUES == (30, 60)
    assert runapi.OUTPUT_NAMES == {"native": "skeleton.json", "part4": "skeleton.json", "part5": "skeleton.part5.json"}


def test_the_named_profiles_exist_in_the_profile_module():
    assert set(runapi.BODIES) <= set(profiles.NAMES)


def test_a_run_with_default_options_carries_the_new_fields():
    status, body = run_sample("take-2")
    assert status == 200 and list(body) == REPLY_KEYS
    assert body["options"] == {**DEFAULTS, "body": "simon-standard"}  # the echo names the body the run used
    assert body["metrics"]["profile"] == "simon-standard"
    assert body["output_text"] == body["skeleton_text"] and body["output_name"] == "skeleton.json"


def test_options_none_and_the_parsed_defaults_run_the_same():
    plain = runapi.handle("take-3", "auto", None, b"")[1]
    parsed = runapi.handle("take-3", "auto", None, b"", runapi.parse_options("")[0])[1]
    plain.pop("run_ms"), parsed.pop("run_ms")
    assert plain == parsed


def test_angles_are_the_joint_angle_series_check_3_uses():
    _, body = run_sample("take-4")
    skeleton = json.loads(body["skeleton_text"])
    table = joint_angles(skeleton)
    assert len(body["angles"]) == len(skeleton["frames"]) and all(len(row) == 9 for row in body["angles"])
    assert np.array_equal(np.array(body["angles"], dtype=float), table)  # exact: nothing is rounded


def test_angles_are_null_for_a_frame_without_the_person(clip):
    clip["frames"][5]["people"] = []
    body = upload(clip)[1]
    assert body["angles"][5] == [None] * 9 and None not in body["angles"][4]
    json.dumps(body["angles"], allow_nan=False)  # no NaN reaches the wire


def test_angles_survive_the_json_round_trip_exactly():
    body = run_sample("take-1")[1]
    assert json.loads(json.dumps(body["angles"])) == body["angles"]


def test_a_stature_is_refused_by_the_options_not_by_the_pipeline():
    assert runapi.parse_options("stature=3")[1][0] == 400


# The wiring of the options into the pipeline, with stand-ins for the profile and view modules.

@pytest.fixture
def stand_ins(monkeypatch):
    """Stand-ins for the profile resolver and the view registry that record their calls; cli.process records its
    keywords and runs the real pipeline with the default body."""
    calls = {"resolve": [], "process": [], "render": []}
    selection = types.SimpleNamespace(name="stand-in selection")
    real_process = cli.process

    def resolve(**kwargs):
        calls["resolve"].append(kwargs)
        return selection

    def process(doc, **kwargs):
        calls["process"].append(kwargs)
        return real_process(doc, **{k: v for k, v in kwargs.items() if k in ("flip", "sha256")}, env={}, config=False)

    def render(skeleton, view, **options):
        calls["render"].append((view, options))
        return {"format": f"stand-in.{view}", "frames": len(skeleton["frames"])}

    monkeypatch.setattr(runapi, "profiles", types.SimpleNamespace(resolve=resolve, estimate_stature=profiles.estimate_stature))
    monkeypatch.setattr(runapi, "views", types.SimpleNamespace(render=render))
    monkeypatch.setattr(cli, "process", process)
    calls["selection"] = selection
    return calls


def test_the_default_run_resolves_the_default_profile_and_renders_no_view(stand_ins):
    status, _ = runapi.handle("take-1", "auto", None, b"", options_for(""))
    assert status == 200 and stand_ins["render"] == []
    assert stand_ins["resolve"] == [{"flag": None, "stature_flag": None, "env": {}, "config": False, "view": "native"}]
    kwargs = stand_ins["process"][0]
    assert kwargs["body"] is stand_ins["selection"] and kwargs["fps"] is None
    assert kwargs["env"] == {} and kwargs["config"] is False  # the server's environment and files are never read
    assert kwargs["max_frames"] == runapi.SERVER_MAX_FRAMES  # the pipeline's own cap, behind the span pre-check


def test_a_named_simon_standard_is_a_choice_that_wins_over_the_views_default(stand_ins):
    """ASM-012: a blank body is the View's default; a named one is requested as `--body <name>` is, so
    simon-standard at View part4 stays simon-standard."""
    runapi.handle("take-1", "auto", None, b"", options_for("body=simon-standard&view=part4"))
    assert stand_ins["resolve"] == [
        {"flag": "simon-standard", "stature_flag": None, "env": {}, "config": False, "view": "part4"}]


def test_a_blank_body_passes_the_view_so_the_resolver_picks_its_default(stand_ins):
    runapi.handle("take-1", "auto", None, b"", options_for("body=&view=part4"))
    assert stand_ins["resolve"] == [{"flag": None, "stature_flag": None, "env": {}, "config": False, "view": "part4"}]


def test_a_named_body_resolves_with_no_environment_and_no_config_file(stand_ins):
    status, body = runapi.handle("take-1", "auto", None, b"", options_for("body=part4-rig"))
    used = json.loads(body["skeleton_text"])["body"]["profile"]  # the stand-in pipeline runs the default body
    assert status == 200 and body["options"]["body"] == used and body["metrics"]["profile"] == used
    assert stand_ins["resolve"] == [
        {"flag": "part4-rig", "stature_flag": None, "env": {}, "config": False, "view": "native"}]
    kwargs = stand_ins["process"][0]
    assert kwargs["body"] is stand_ins["selection"] and kwargs["fps"] is None
    assert kwargs["env"] == {} and kwargs["config"] is False


def test_a_height_on_the_default_body_resolves_the_default_profile(stand_ins):
    runapi.handle("take-1", "auto", None, b"", options_for("stature=1.85"))
    assert stand_ins["resolve"] == [{"flag": None, "stature_flag": 1.85, "env": {}, "config": False, "view": "native"}]


def test_a_frame_rate_goes_to_the_pipeline_as_an_integer(stand_ins):
    runapi.handle("take-1", "auto", None, b"", options_for("fps=60"))
    assert stand_ins["process"][0]["fps"] == 60
    assert stand_ins["resolve"] == [{"flag": None, "stature_flag": None, "env": {}, "config": False, "view": "native"}]


@pytest.mark.parametrize("view, name, keywords", [
    ("part5", "skeleton.part5.json", {"max_frames": runapi.SERVER_MAX_FRAMES}),
    ("part4", "skeleton.json", {"max_frames": runapi.SERVER_MAX_FRAMES, "keyframes": "every:10"})])
def test_a_view_is_rendered_from_the_native_skeleton_and_its_text_is_the_output(stand_ins, view, name, keywords):
    status, body = runapi.handle("take-1", "auto", None, b"", options_for(f"view={view}"))
    assert status == 200 and body["output_name"] == name
    assert stand_ins["render"] == [(view, keywords)]
    assert body["output_text"] == io.dumps({"format": f"stand-in.{view}", "frames": 113})
    native = json.loads(body["skeleton_text"])
    assert native["schema"] == "simon.skeleton/1" and body["output_text"] != body["skeleton_text"]
    assert len(body["angles"]) == 113  # the angles and metrics come from the native skeleton


def test_a_view_that_breaks_the_contract_is_a_422_naming_the_field(stand_ins, monkeypatch):
    def refuse(skeleton, view, **options):
        raise ContractError("keyframes", "no keyframe falls inside the clip")
    monkeypatch.setattr(runapi, "views", types.SimpleNamespace(render=refuse))
    status, error = code_of(runapi.handle("take-1", "auto", None, b"", options_for("view=part4")))
    assert (status, error["code"], error["field"]) == (422, "contract", "keyframes")


# ---- review R1: a View that cannot write the clip is not an invalid file ---------------------------

SWEEP_SOURCE = {"kind": "upload", "id": None, "name": "sweep.json"}
VIEW_REFUSED = re.compile(r"^This clip cannot be written as Part 4 keys: left_shoulder turns \d+\.\d degrees between "
                          r"keys 110 and 120 \(Part 4 allows 180\)\. Choose another View\.$")


def swept_across_the_body():
    """take-1 with the left arm swept across the chest between two keys: a valid pose3d.json that Part 4 would reject."""
    return json.dumps(take1_with_arms(across_the_body)).encode()


def test_a_clip_the_part4_view_refuses_is_a_422_view_refused_and_not_an_invalid_file():
    status, error = code_of(runapi.run(swept_across_the_body(), "auto", SWEEP_SOURCE, options_for("view=part4")))
    assert (status, error["code"], error["field"]) == (422, "view_refused", "view")
    assert VIEW_REFUSED.match(error["message"]), error["message"]
    assert "--" not in error["message"] and "not a valid pose3d.json" not in error["message"]


def test_the_same_clip_runs_in_the_views_that_can_write_it():
    for query in ("", "view=native", "view=part5"):
        status, body = runapi.run(swept_across_the_body(), "auto", SWEEP_SOURCE, options_for(query))
        assert status == 200 and body["ok"] is True, query


def test_the_refusal_comes_through_handle_as_it_does_through_run():
    result = runapi.handle(None, "auto", "sweep.json", swept_across_the_body(), options_for("view=part4"))
    assert code_of(result)[1]["code"] == "view_refused"


def test_view_refused_is_in_the_error_table_as_a_422_with_a_plain_message():
    assert runapi.ERRORS["view_refused"] == (422, "This clip cannot be written in that View. Choose another View.")
    assert code_of(runapi.error("view_refused")) == (
        422, {"code": "view_refused", "field": "view", "message": runapi.ERRORS["view_refused"][1]})


PART5_REFUSED = ("This clip cannot be written as a Part 5 animation: frame 2: times must strictly increase "
                 "(Part 5 rejects a clip whose times do not). Choose another View.")


def test_a_clip_the_part5_view_refuses_is_a_422_view_refused_worded_without_a_flag():
    raw = json.dumps(equal_times(json.loads(TAKE_1.read_text()))).encode()
    status, error = code_of(runapi.run(raw, "auto", SWEEP_SOURCE, options_for("view=part5")))
    assert (status, error["code"], error["field"], error["message"]) == (422, "view_refused", "view", PART5_REFUSED)
    assert "--" not in error["message"] and "not a valid pose3d.json" not in error["message"]
    for query in ("", "view=native"):  # the same clip runs where the View can write it
        assert runapi.run(raw, "auto", SWEEP_SOURCE, options_for(query))[0] == 200


def test_the_part5_refusal_is_a_view_error_and_the_command_line_says_what_it_said(tmp_path):
    source = tmp_path / "pose3d.json"
    source.write_text(json.dumps(equal_times(json.loads(TAKE_1.read_text()))))
    result = subprocess.run([sys.executable, "-m", "part3", "run", "--in", str(source), "--out", str(tmp_path / "o.json"),
                             "--view", "part5"], cwd=ROOT, capture_output=True, text=True)
    assert (result.returncode, result.stdout) == (2, "")
    assert result.stderr == ("--view part5: frame 2: times must strictly increase "
                             "(Part 5 rejects a clip whose times do not)\n")


def test_the_part4_view_without_keys_is_a_view_error_worded_for_the_page():
    """The run app always gives the part4 view its keys, so this refusal is reached through the view itself."""
    skeleton = cli.process(json.loads(TAKE_1.read_text()),
                           env={}, config=False)
    with pytest.raises(ViewError) as caught:
        views.render(skeleton, "part4")
    status, error = code_of(runapi._contract_failure(caught.value, options_for("view=part4")))
    assert (status, error["code"], error["field"], error["message"]) == (
        422, "view_refused", "view", "This clip cannot be written as Part 4 keys. Choose another View.")
    assert str(caught.value) == "--view part4 needs --keyframes <keyframes.json> or every:<n>"


# Review residual 4 (TICKET-032): the long-way refusal carries its numbers as attributes and the page text is built
# from them, never read back out of the message.

@pytest.mark.parametrize("joint, degrees, first, second, limit, text", [
    ("right_elbow", 351.1, 10, 20, 180.0,
     "This clip cannot be written as Part 4 keys: right_elbow turns 351.1 degrees between keys 10 and 20 "
     "(Part 4 allows 180). Choose another View."),
    ("left_hip", 181.0, 0, 5, 150.5,
     "This clip cannot be written as Part 4 keys: left_hip turns 181.0 degrees between keys 0 and 5 "
     "(Part 4 allows 150.5). Choose another View."),
])
def test_the_long_way_text_is_built_from_the_attributes_of_the_error(joint, degrees, first, second, limit, text):
    problem = LongWayError("--view part4", "words that name none of the numbers", joint, degrees, first, second, limit)
    for view in ("part4", "native"):  # the long-way rule belongs to Part 4 whatever View the page names
        status, error = code_of(runapi._contract_failure(problem, options_for(f"view={view}")))
        assert (status, error["code"], error["field"], error["message"]) == (422, "view_refused", "view", text)


def test_runapi_does_not_read_a_refusal_back_out_of_its_message():
    source = pathlib.Path(runapi.__file__).read_text(encoding="utf-8")
    assert "_LONG_WAY" not in source and "Part 4 would reject this clip" not in source
    assert "re.compile" not in source.replace("_STATURE = re.compile", "")  # the height field is its only pattern
    assert not hasattr(runapi, "_view_detail") and not hasattr(runapi, "_view_text")


def test_runapi_classifies_by_type_with_no_test_of_a_path_or_a_message_for_a_command_line_flag():
    """AC-M14: no `startswith("--...")` and no `"--" in msg` anywhere in the run app's logic."""
    tree = ast.parse(pathlib.Path(runapi.__file__).read_text(encoding="utf-8"))
    flags = [node.lineno for node in ast.walk(tree)
             if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.startswith("--")]
    tests = [node.lineno for node in ast.walk(tree)
             if isinstance(node, ast.Compare) and any(isinstance(op, ast.In) for op in node.ops)
             and isinstance(node.left, ast.Constant) and node.left.value == "--"]
    assert flags == [] and tests == []


@pytest.mark.parametrize("path", ["pose3d.frames", "keyframes", "every:10", "body measured", "viewer", "--view part4"])
def test_any_other_path_is_still_an_invalid_file(path):
    problem = ContractError(path, "no keyframe falls inside the clip")
    status, error = code_of(runapi._contract_failure(problem, options_for("view=part4")))
    assert (status, error["code"], error["field"]) == (422, "contract", path)


# The same options through the real profile and view modules.

def cli_bytes(sample_id, tmp_path, *args):
    target = tmp_path / "out.json"
    result = subprocess.run([sys.executable, "-m", "part3", "run", "--in", str(file_of(sample_id)), "--out", str(target),
                             "--flip", "auto", *args], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return target.read_bytes()


def test_switching_the_body_changes_the_bone_lengths_and_the_download_records_the_profile(tmp_path):
    standard = runapi.handle("take-1", "auto", None, b"", options_for(""))[1]
    rig = runapi.handle("take-1", "auto", None, b"", options_for("body=part4-rig"))[1]
    measured = runapi.handle("take-1", "auto", None, b"", options_for("body=measured"))[1]
    lengths = [json.loads(b["output_text"])["bone_lengths_m"] for b in (standard, rig, measured)]
    assert lengths[0] == lengths[1]  # Part 4's rig uses Part 3's own 1.70 m numbers: same lengths, another profile
    assert lengths[0] != lengths[2]  # the clip's own median lengths differ
    sources = [json.loads(b["output_text"])["body"]["source"] for b in (standard, rig, measured)]
    assert len(set(sources)) == 3
    assert [json.loads(b["output_text"])["body"]["profile"] for b in (standard, rig, measured)] == [
        "simon-standard", "part4-rig", "measured"]
    for body in (rig, measured):
        assert body["metrics"]["bone_length_variation_output"] < BONE_MAX
    assert rig["output_text"].encode() == cli_bytes("take-1", tmp_path, "--body", "part4-rig")
    assert measured["output_text"].encode() == cli_bytes("take-1", tmp_path, "--body", "measured")


def test_a_height_scales_every_bone_length():
    base = json.loads(runapi.handle("take-1", "auto", None, b"", options_for(""))[1]["output_text"])
    tall = json.loads(runapi.handle("take-1", "auto", None, b"", options_for("stature=1.85"))[1]["output_text"])
    assert math.isclose(tall["bone_lengths_m"]["spine"] / base["bone_lengths_m"]["spine"], 1.85 / 1.7, rel_tol=1e-3)


def test_a_frame_rate_resamples_the_frames():
    body = runapi.handle("take-1", "auto", None, b"", options_for("fps=30"))[1]
    skeleton = json.loads(body["skeleton_text"])
    assert skeleton["resample"]["fps"] == 30 and body["metrics"]["frames"] == len(skeleton["frames"])


def test_view_part5_is_a_simon_animation_file_equal_to_the_cli(tmp_path):
    body = runapi.handle("take-1", "auto", None, b"", options_for("view=part5"))[1]
    assert body["output_name"] == "skeleton.part5.json"
    assert json.loads(body["output_text"])["format"] == "simon.animation.v1"
    assert json.loads(body["skeleton_text"])["schema"] == "simon.skeleton/1"
    assert body["output_text"].encode() == cli_bytes("take-1", tmp_path, "--view", "part5")


def test_view_part4_has_a_key_every_ten_ticks_and_equals_the_cli(tmp_path):
    body = runapi.handle("take-1", "auto", None, b"", options_for("view=part4"))[1]
    assert body["output_name"] == "skeleton.json"
    output = json.loads(body["output_text"])
    assert output["format"] == "simon.skeleton.v1"
    assert [key["index"] for key in output["keyframes"]][:3] == [0, 10, 20]
    assert body["output_text"].encode() == cli_bytes("take-1", tmp_path, "--view", "part4", "--keyframes", "every:10")


def test_the_body_and_view_together_equal_the_cli(tmp_path):
    body = runapi.handle("part2-squat", "auto", None, b"", options_for("body=part4-rig&view=part4&fps=30"))[1]
    expected = cli_bytes("part2-squat", tmp_path, "--body", "part4-rig", "--view", "part4", "--keyframes", "every:10",
                         "--fps", "30")
    assert body["output_text"].encode() == expected


# ---- a request never reads the server's environment or files ------------------------------------

def test_the_servers_environment_and_config_file_do_not_change_a_run(monkeypatch, tmp_path):
    clean = run_sample("take-2")[1]
    monkeypatch.setenv("PART3_BODY", "measured")
    monkeypatch.setenv("PART3_STATURE", "2.1")
    (tmp_path / "part3.toml").write_text('[body]\nprofile = "part4-rig"\nstature = 1.2\n')
    monkeypatch.chdir(tmp_path)
    ambient = run_sample("take-2")[1]
    assert ambient["skeleton_text"] == clean["skeleton_text"]
    body = json.loads(ambient["skeleton_text"])["body"]
    assert (body["profile"], body["selected_by"], body["stature_m"]) == ("simon-standard", "default", 1.7)


def test_a_chosen_body_wins_over_the_servers_environment(monkeypatch):
    monkeypatch.setenv("PART3_BODY", "measured")
    body = runapi.handle("take-2", "auto", None, b"", options_for("body=part4-rig"))[1]
    assert json.loads(body["skeleton_text"])["body"]["profile"] == "part4-rig"


def test_the_height_estimate_of_the_input_does_not_depend_on_the_body_chosen():
    standard = run_sample("part2-squat")[1]["metrics"]["input_height_estimate_m"]
    stretched = runapi.handle("part2-squat", "auto", None, b"", options_for("stature=2"))[1]
    assert stretched["metrics"]["input_height_estimate_m"] == standard and stretched["metrics"]["stature_m"] == 2.0


def test_the_height_estimate_is_the_profile_modules_chain_sum():
    body = run_sample("part2-squat")[1]
    measured = json.loads(body["skeleton_text"])["person"]["measured_bone_lengths_m"]
    assert body["metrics"]["input_height_estimate_m"] == round(profiles.estimate_stature(measured), 4)


def test_an_upload_in_a_tolerated_shape_runs_and_shows_its_input_frames(clip):
    """The adapters accept joints given as arrays; the metrics and the input frames use the canonical form."""
    for frame in clip["frames"]:
        for person in frame["people"]:
            person["joints"] = {name: [j["x"], j["y"], j["z"], j["conf"]] for name, j in person["joints"].items()}
    status, body = upload(clip)
    assert status == 200 and json.loads(body["skeleton_text"])["input"]["adapters"] == ["joint-arrays"]
    assert len(body["input_frames"]) == 40 and body["input_frames"][0] is not None
    assert 0.1 < body["metrics"]["bone_length_variation_input"] < 0.2


def test_a_resampled_run_lists_the_output_frames_and_the_angles_of_each():
    body = runapi.handle("take-1", "auto", None, b"", options_for("fps=60"))[1]
    skeleton = json.loads(body["skeleton_text"])
    assert len(body["angles"]) == len(skeleton["frames"]) == body["metrics"]["frames"] > 113
    assert all("source" in frame for frame in skeleton["frames"])
    assert len(body["input_frames"]) == 113  # the input as delivered, one entry per input frame
