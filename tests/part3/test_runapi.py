"""The pure logic of the run app: samples, one run, the error table (docs/specs/run-app.md AC-R01..R05, AC-NFR-05) and
the run options (docs/specs/compare-mode.md AC-M01, AC-M02)."""

import copy
import hashlib
import json
import math
import re
import subprocess
import sys
import time
import types

import numpy as np
import pytest

from conftest import ROOT
from part3 import bones, cli, io, profiles, runapi
from part3.angles import joint_angles
from part3.metrics import BONE_MAX, bone_variation
from part3.schema import ContractError, validate_skeleton
from test_view_part4 import across_the_body, take1_with_arms

SAMPLE_IDS = ["part2-squat", "take-1", "take-2", "take-3", "take-4", "take-1-mirrored", "armraise-control"]
SAMPLE_FRAMES = [107, 113, 121, 107, 121, 113, 105]
METRIC_KEYS = ["frames", "frames_present", "frames_dropped", "person_id", "people_in_input",
               "bone_length_variation_output", "bone_length_variation_input", "variation_limit",
               "flips_repaired_frames", "flips_repaired_total", "mirror", "profile", "stature_m",
               "input_height_estimate_m", "up_source"]
REPLY_KEYS = ["ok", "source", "flip", "options", "metrics", "input_frames", "bones", "angles", "skeleton_text",
              "output_text", "output_name", "run_ms"]
NOSE_CONF = "pose3d.frames[0].people[0].joints.nose.conf"


def file_of(sample_id):
    return ROOT / "fixtures" / "input" / next(rel for sid, rel, _ in runapi.SAMPLES if sid == sample_id)


def run_sample(sample_id, flip="auto"):
    return runapi.handle(sample_id, flip, None, b"")


def upload(doc, flip="auto", name="clip.json"):
    return runapi.handle(None, flip, name, json.dumps(doc).encode())


def code_of(result):
    status, body = result
    assert body["ok"] is False and list(body) == ["ok", "error"]
    assert list(body["error"]) == ["code", "field", "message"]
    return status, body["error"]


@pytest.fixture
def clip(real_doc):
    """A private 40-frame copy of the real clip with a new person id."""
    doc = copy.deepcopy(real_doc)
    doc["frames"] = doc["frames"][:40]
    for frame in doc["frames"]:
        for person in frame["people"]:
            person["id"] = 7
    return doc


# ---- AC-R01: samples ---------------------------------------------------------------------------

def test_samples_lists_the_seven_inputs_in_order():
    listed = runapi.samples()
    assert [s["id"] for s in listed] == SAMPLE_IDS
    assert [s["frames"] for s in listed] == SAMPLE_FRAMES
    assert [s["label"] for s in listed] == [
        "Part 2 squat (real clip)", "Synthetic squat, take 1", "Synthetic squat, take 2",
        "Synthetic squat, take 3", "Synthetic squat, take 4", "Synthetic squat, take 1, saved mirrored",
        "Arm raise (negative control)"]
    assert all(list(s) == ["id", "label", "detail", "frames", "mirrored_hint"] for s in listed)


def test_samples_mirrored_hint_is_true_only_for_the_mirrored_take():
    assert {s["id"]: s["mirrored_hint"] for s in runapi.samples()} == {
        sid: sid == "take-1-mirrored" for sid in SAMPLE_IDS}


def test_samples_detail_is_one_sentence_with_the_camera_from_the_truth_file():
    detail = {s["id"]: s["detail"] for s in runapi.samples()}
    assert all(text.endswith(".") and text.count(". ") == 0 for text in detail.values())
    assert "azimuth 90 degrees, pitch 20 degrees" in detail["take-3"]
    assert "azimuth 0 degrees, pitch 12 degrees" in detail["take-1"]
    assert "azimuth 180 degrees, pitch -15 degrees" in detail["armraise-control"]
    assert "swapped in 10 frames" in detail["take-4"]
    assert "swapped" not in detail["take-1"]


def test_samples_returns_copies():
    first = runapi.samples()
    first[0]["label"] = "changed"
    assert runapi.samples()[0]["label"] == "Part 2 squat (real clip)"


# ---- AC-R02: a run of each sample --------------------------------------------------------------

@pytest.mark.parametrize("sample_id", SAMPLE_IDS)
def test_run_sample_auto_returns_the_documented_body(sample_id):
    status, body = run_sample(sample_id)
    assert status == 200 and body["ok"] is True
    assert list(body) == REPLY_KEYS
    raw = file_of(sample_id).read_bytes()
    label = next(s["label"] for s in runapi.samples() if s["id"] == sample_id)
    assert body["source"] == {"kind": "sample", "id": sample_id, "name": label, "bytes": len(raw),
                              "sha256": hashlib.sha256(raw).hexdigest()}
    assert body["flip"] == "auto" and isinstance(body["run_ms"], float)
    metrics = body["metrics"]
    assert list(metrics) == METRIC_KEYS
    assert metrics["frames"] == SAMPLE_FRAMES[SAMPLE_IDS.index(sample_id)] == len(body["input_frames"])
    assert metrics["bone_length_variation_output"] < BONE_MAX == metrics["variation_limit"]
    assert metrics["mirror"]["applied"] is (sample_id == "take-1-mirrored")
    skeleton = json.loads(body["skeleton_text"])
    validate_skeleton(skeleton)
    assert skeleton["input"]["sha256"] == body["source"]["sha256"]


@pytest.mark.parametrize("sample_id", ["part2-squat", "take-1-mirrored"])
@pytest.mark.parametrize("flip", ["auto", "on", "off"])
def test_run_sample_mirror_decision_follows_the_setting(sample_id, flip):
    _, body = run_sample(sample_id, flip)
    mirror = body["metrics"]["mirror"]
    hint = sample_id == "take-1-mirrored"
    assert body["flip"] == flip
    assert mirror["setting"] == flip
    assert mirror["applied"] is {"on": True, "off": False, "auto": hint}[flip]
    auto = "auto: input mirrored true" if hint else "auto: no mirrored key in input"
    assert mirror["reason"] == {"on": "flag on", "off": "flag off", "auto": auto}[flip]


def test_run_sample_metrics_match_independent_measures():
    _, body = run_sample("part2-squat")
    skeleton = json.loads(body["skeleton_text"])
    metrics = body["metrics"]
    expected = bone_variation(skeleton, bones.lengths_array(skeleton["bone_lengths_m"]))
    assert metrics["bone_length_variation_output"] == round(expected, 4)
    assert 0.1 < metrics["bone_length_variation_input"] < 0.2  # the clip as Part 2 delivered it
    assert metrics["frames_present"] == skeleton["person"]["frames_present"] == 107
    assert metrics["frames_dropped"] == 0 and metrics["person_id"] == "0" and metrics["people_in_input"] == 1
    assert metrics["stature_m"] == 1.7 and metrics["up_source"] == "standing_frames"


def test_run_sample_estimates_the_input_height_from_the_leg_and_trunk_chain():
    _, body = run_sample("part2-squat")
    skeleton = json.loads(body["skeleton_text"])
    measured, standard = skeleton["person"]["measured_bone_lengths_m"], skeleton["bone_lengths_m"]

    def chain(lengths):
        return (lengths["left_thigh"] + lengths["right_thigh"] + lengths["left_shank"] + lengths["right_shank"]) / 2 \
            + lengths["spine"]

    assert body["metrics"]["input_height_estimate_m"] == round(1.7 * chain(measured) / chain(standard), 4)
    assert 1.0 < body["metrics"]["input_height_estimate_m"] < 2.5


def test_a_metric_that_is_not_finite_is_null(monkeypatch):
    monkeypatch.setattr(runapi, "bone_variation", lambda *args: float("nan"))
    monkeypatch.setattr(runapi, "input_bone_variation", lambda *args, **kwargs: float("inf"))
    metrics = run_sample("take-1")[1]["metrics"]
    assert metrics["bone_length_variation_output"] is None and metrics["bone_length_variation_input"] is None


def test_run_sample_counts_the_repaired_frames():
    _, body = run_sample("take-4")
    skeleton = json.loads(body["skeleton_text"])
    repaired = sum(1 for f in skeleton["frames"] if f["people"][0]["flips_repaired"])
    assert repaired > 0 and body["metrics"]["flips_repaired_frames"] == repaired
    assert body["metrics"]["flips_repaired_total"] == skeleton["person"]["flips_repaired_total"]


def test_run_sample_input_frames_are_the_input_as_delivered(real_doc):
    _, body = run_sample("part2-squat")
    first = real_doc["frames"][0]["people"][0]["joints"]
    assert body["input_frames"][0][0] == [round(first["nose"][a], 4) + 0.0 for a in "xyz"]
    assert all(len(points) == 17 for points in body["input_frames"])


def test_bones_are_the_demo_data_pairs():
    _, body = run_sample("take-1")
    demo = json.loads((ROOT / "web" / "data" / "demo.json").read_text())
    assert body["bones"] == demo["bones"] and len(body["bones"]) == 18


# ---- AC-R03: the download is the CLI's output --------------------------------------------------

@pytest.mark.parametrize("sample_id, flip", [("part2-squat", "auto"), ("take-1-mirrored", "on")])
def test_skeleton_text_equals_cli(sample_id, flip, tmp_path):
    target = tmp_path / "skeleton.json"
    result = subprocess.run([sys.executable, "-m", "part3", "run", "--in", str(file_of(sample_id)),
                             "--out", str(target), "--flip", flip], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    _, body = run_sample(sample_id, flip)
    assert body["skeleton_text"].encode("utf-8") == target.read_bytes()
    check = subprocess.run([sys.executable, "-m", "part3.schema", str(target)], cwd=ROOT, capture_output=True)
    assert check.returncode == 0


@pytest.mark.parametrize("sample_id, flip", [("part2-squat", "auto"), ("take-1-mirrored", "on")])
def test_output_text_of_the_native_view_is_the_cli_text(sample_id, flip, tmp_path):
    """AC-M01: output_text is what `python3 -m part3 run` writes with the same options (defaults: native)."""
    target = tmp_path / "skeleton.json"
    result = subprocess.run([sys.executable, "-m", "part3", "run", "--in", str(file_of(sample_id)),
                             "--out", str(target), "--flip", flip], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    body = run_sample(sample_id, flip)[1]
    assert body["output_text"].encode("utf-8") == target.read_bytes() == body["skeleton_text"].encode("utf-8")
    assert body["output_name"] == "skeleton.json"


def test_the_same_upload_twice_gives_the_same_text(clip):
    assert upload(clip)[1]["skeleton_text"] == upload(clip)[1]["skeleton_text"]


# ---- AC-R04: upload a good file ----------------------------------------------------------------

def test_upload_good_runs_like_a_sample(clip):
    raw = json.dumps(clip).encode()
    status, body = runapi.handle(None, "auto", "my clip.json", raw)
    assert status == 200
    assert body["source"] == {"kind": "upload", "id": None, "name": "my clip.json", "bytes": len(raw),
                              "sha256": hashlib.sha256(raw).hexdigest()}
    assert body["metrics"]["frames"] == 40 == len(body["input_frames"])
    assert body["metrics"]["person_id"] == "7"
    assert json.loads(body["skeleton_text"])["input"]["sha256"] == body["source"]["sha256"]


def test_upload_names_are_text_only_and_cut_at_80_characters(clip):
    assert upload(clip, name="x" * 200)[1]["source"]["name"] == "x" * 80
    assert upload(clip, name="../../etc/passwd")[1]["source"]["name"] == "../../etc/passwd"
    assert upload(clip, name="a\nb\x00c")[1]["source"]["name"] == "abc"
    assert upload(clip, name=None)[1]["source"]["name"] == "your file"
    assert upload(clip, name="   ")[1]["source"]["name"] == "your file"


def test_upload_with_several_people_keeps_the_one_with_most_frames(clip):
    alone = upload(clip)[1]
    for frame in clip["frames"][:10]:  # a passer-by in the first 10 frames
        other = copy.deepcopy(frame["people"][0])
        other["id"] = 9
        for joint in other["joints"].values():
            joint["x"] += 1.0
        frame["people"].append(other)
    status, body = upload(clip)
    assert status == 200
    assert body["metrics"]["people_in_input"] == 2 and body["metrics"]["person_id"] == "7"
    assert body["input_frames"][0][0] == [round(clip["frames"][0]["people"][0]["joints"]["nose"][a], 4)
                                          for a in "xyz"]
    assert body["metrics"]["bone_length_variation_input"] == alone["metrics"]["bone_length_variation_input"]
    assert body["input_frames"] == alone["input_frames"]  # measured on person 7, not on the passer-by


def test_a_frame_with_only_another_person_is_null_never_that_person(clip):
    other = copy.deepcopy(clip["frames"][5]["people"][0])
    other["id"] = 9
    clip["frames"][5]["people"] = [other]
    status, body = upload(clip)
    assert status == 200
    assert body["input_frames"][5] is None and body["input_frames"][6] is not None
    assert body["metrics"]["person_id"] == "7" and body["metrics"]["people_in_input"] == 2


def test_upload_where_the_person_is_missing_in_a_frame_has_null_there(clip):
    clip["frames"][5]["people"] = []
    status, body = upload(clip)
    assert status == 200
    assert body["input_frames"][5] is None and body["input_frames"][4] is not None
    assert body["metrics"]["frames"] == 40 and body["metrics"]["frames_present"] == 39
    assert json.loads(body["skeleton_text"])["frames"][5]["people"] == []


def test_upload_with_a_string_id_reports_it_as_text(clip):
    for frame in clip["frames"]:
        frame["people"][0]["id"] = "athlete"
    assert upload(clip)[1]["metrics"]["person_id"] == "athlete"


def test_upload_is_not_stored(clip, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    upload(clip)
    assert list(tmp_path.iterdir()) == []


# ---- AC-R05: errors ----------------------------------------------------------------------------

@pytest.mark.parametrize("raw", [b"not json at all", b"\xff\xfe\x00bad", b"", b"[" * 200000, b"1" * 100000,
                                 b'\xef\xbb\xbf{"frames": []}'])
def test_error_not_json(raw):
    status, error = code_of(runapi.run(raw, "auto", runapi.upload_source("f.json")))
    assert (status, error["code"], error["field"]) == (400, "not_json", None)
    assert error["message"] == "This file is not JSON. Choose a pose3d.json file."


def test_error_contract_names_the_failing_field(clip):
    del clip["frames"][0]["people"][0]["joints"]["nose"]["conf"]
    status, error = code_of(upload(clip))
    assert (status, error["code"], error["field"]) == (422, "contract", NOSE_CONF)
    assert error["message"] == ("This file is not a valid pose3d.json: pose3d.frames[0].people[0].joints.nose.conf: "
                                "missing (expected a number in [0, 1]).")


@pytest.mark.parametrize("doc, field", [
    ([1, 2], "pose3d"),
    ({"frames": []}, "pose3d.frames"),
    ({"frames": [{"frame": 0, "t_ms": 0, "people": []}]}, "pose3d.frames"),
    ({"frames": "x"}, "pose3d.frames"),
    ({"frames": [], "mirrored": "yes"}, "pose3d.mirrored"),
])
def test_error_contract_covers_validator_and_pipeline_breaks(doc, field):
    status, error = code_of(upload(doc))
    assert (status, error["code"], error["field"]) == (422, "contract", field)
    assert error["message"].startswith(f"This file is not a valid pose3d.json: {field}: ")
    assert error["message"].endswith(".") and not error["message"].endswith("..")


def test_error_contract_for_an_id_that_is_not_utf8(clip):
    for frame in clip["frames"]:
        frame["people"][0]["id"] = "bad\udc80id"
    status, error = code_of(runapi.run(json.dumps(clip).encode(), "auto", {}))
    assert (status, error["code"], error["field"]) == (422, "contract", "pose3d.frames")
    assert "UTF-8" in error["message"]


def test_error_contract_text_is_cut_and_has_no_class_name_or_path(clip):
    joints = clip["frames"][0]["people"][0]["joints"]
    for name in list(joints)[1:]:  # an extra joint is tolerated by an adapter now; missing ones still fail
        del joints[name]
    _, error = code_of(upload(clip))
    assert len(error["message"]) <= runapi.MESSAGE_MAX
    assert "missing" in error["message"]
    for leaked in ("Traceback", "ContractError", "/home/", ".py"):
        assert leaked not in error["message"]


def test_an_error_message_is_cut_at_300_characters():
    assert runapi.MESSAGE_MAX == 300
    assert len(code_of(runapi.error("contract", "f" * 200, "r" * 200))[1]["message"]) == 300


def test_error_bad_flip():
    status, error = code_of(runapi.handle("take-1", "sideways", None, b""))
    assert (status, error["code"], error["field"]) == (400, "bad_flip", None)
    assert error["message"] == "Mirror must be auto, on or off."
    assert code_of(runapi.handle("take-1", "", None, b""))[1]["code"] == "bad_flip"


def test_error_unknown_sample():
    status, error = code_of(runapi.handle("take-9", "auto", None, b""))
    assert (status, error["code"]) == (404, "unknown_sample")
    assert error["message"] == "There is no sample with that name."
    assert code_of(runapi.handle("../../etc/passwd", "auto", None, b""))[1]["code"] == "unknown_sample"


def test_error_no_input():
    status, error = code_of(runapi.handle(None, "auto", None, b""))
    assert (status, error["code"]) == (400, "no_input")
    assert error["message"] == "Choose a sample or a file first."
    assert code_of(runapi.handle("", "auto", None, b""))[1]["code"] == "no_input"


def test_error_both_inputs():
    status, error = code_of(runapi.handle("take-1", "auto", None, b"{}"))
    assert (status, error["code"]) == (400, "both_inputs")
    assert error["message"] == "Choose a sample or a file, not both."


def test_error_internal_hides_the_exception_and_logs_the_traceback(monkeypatch, capsys):
    def explode(*args, **kwargs):
        raise RuntimeError("secret detail at /home/someone/file.py")
    monkeypatch.setattr(cli, "process", explode)
    status, error = code_of(run_sample("take-1"))
    assert (status, error["code"], error["field"]) == (500, "internal", None)
    assert error["message"] == "Something went wrong on the server. Try again."
    seen = json.dumps(error)
    assert "RuntimeError" not in seen and "secret" not in seen and "Traceback" not in seen
    logged = capsys.readouterr().err
    assert "Traceback" in logged and "secret detail" in logged


@pytest.mark.parametrize("code, status, message", [
    ("too_large", 413, "This file is over 16 MB. Choose a smaller pose3d.json file."),
    ("too_long", 400,
     "This clip is too long for that frame rate here. Choose a lower frame rate or a shorter clip."),
    ("length_required", 411, "The upload had no length. Try again."),
    ("busy", 503, "The server is busy. Try again in a moment."),
    ("timeout", 503, "The run took too long and was stopped."),
    ("cross_site", 403, "This request came from another site and was refused."),
    ("bad_request", 400, "The upload was malformed. Try again."),
    ("internal", 500, "Something went wrong on the server. Try again."),
])
def test_error_table_for_the_limits_the_server_enforces(code, status, message):
    assert code_of(runapi.error(code)) == (status, {"code": code, "field": None, "message": message})


def test_every_error_message_is_plain_text():
    for code, (_, message) in runapi.ERRORS.items():
        assert message.endswith(".") and message.isascii(), code  # no dash variants, no fancy quotes


# ---- AC-NFR-05 ---------------------------------------------------------------------------------

@pytest.mark.parametrize("sample_id", SAMPLE_IDS)
def test_run_time_of_a_sample_is_under_two_seconds(sample_id):
    started = time.perf_counter()
    status, body = run_sample(sample_id)
    assert status == 200 and time.perf_counter() - started < 2.0
    assert 0 < body["run_ms"] < 2000


# ---- AC-M01, AC-M02: the run options -----------------------------------------------------------

DEFAULTS = {"body": "simon-standard", "stature": None, "view": "native", "fps": None}


def test_parse_options_defaults_when_nothing_is_given():
    assert runapi.parse_options({}) == (DEFAULTS, None)
    assert runapi.parse_options("") == (DEFAULTS, None)
    assert runapi.parse_options("sample=take-1&flip=on") == (DEFAULTS, None)


@pytest.mark.parametrize("query, expected", [
    ("body=part4-rig", {"body": "part4-rig"}),
    ("body=measured", {"body": "measured"}),
    ("body=simon-standard", {"body": "simon-standard"}),
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
    ("body=file:/etc/passwd", "bad_body", "body", "Body must be simon-standard, part4-rig or measured."),
    ("body=file:part3/standard_body.json", "bad_body", "body", "Body must be simon-standard, part4-rig or measured."),
    ("body=nonsense", "bad_body", "body", "Body must be simon-standard, part4-rig or measured."),
    ("body=", "bad_body", "body", "Body must be simon-standard, part4-rig or measured."),
    ("body=Part4-rig", "bad_body", "body", "Body must be simon-standard, part4-rig or measured."),
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
    assert body["options"] == DEFAULTS
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


def options_for(query):
    options, failure = runapi.parse_options(query)
    assert failure is None
    return options


def test_the_default_run_resolves_the_default_profile_and_renders_no_view(stand_ins):
    status, _ = runapi.handle("take-1", "auto", None, b"", options_for(""))
    assert status == 200 and stand_ins["render"] == []
    assert stand_ins["resolve"] == [{"flag": None, "stature_flag": None, "env": {}, "config": False}]
    kwargs = stand_ins["process"][0]
    assert kwargs["body"] is stand_ins["selection"] and kwargs["fps"] is None
    assert kwargs["env"] == {} and kwargs["config"] is False  # the server's environment and files are never read
    assert kwargs["max_frames"] == runapi.SERVER_MAX_FRAMES  # the pipeline's own cap, behind the span pre-check


def test_asking_for_simon_standard_is_asking_for_the_default(stand_ins):
    runapi.handle("take-1", "auto", None, b"", options_for("body=simon-standard"))
    assert stand_ins["resolve"] == [{"flag": None, "stature_flag": None, "env": {}, "config": False}]


def test_a_named_body_resolves_with_no_environment_and_no_config_file(stand_ins):
    status, body = runapi.handle("take-1", "auto", None, b"", options_for("body=part4-rig"))
    assert status == 200 and body["options"]["body"] == "part4-rig" and body["metrics"]["profile"] == "part4-rig"
    assert stand_ins["resolve"] == [{"flag": "part4-rig", "stature_flag": None, "env": {}, "config": False}]
    kwargs = stand_ins["process"][0]
    assert kwargs["body"] is stand_ins["selection"] and kwargs["fps"] is None
    assert kwargs["env"] == {} and kwargs["config"] is False


def test_a_height_on_the_default_body_resolves_the_default_profile(stand_ins):
    runapi.handle("take-1", "auto", None, b"", options_for("stature=1.85"))
    assert stand_ins["resolve"] == [{"flag": None, "stature_flag": 1.85, "env": {}, "config": False}]


def test_a_frame_rate_goes_to_the_pipeline_as_an_integer(stand_ins):
    runapi.handle("take-1", "auto", None, b"", options_for("fps=60"))
    assert stand_ins["process"][0]["fps"] == 60
    assert stand_ins["resolve"] == [{"flag": None, "stature_flag": None, "env": {}, "config": False}]


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


@pytest.mark.parametrize("path, msg, view, message", [
    # the long-way refusal keeps its joint and keys; whatever is appended to it (a command line hint) is dropped
    ("--view part4", "Part 4 would reject this clip: right_elbow turns 351.1 degrees between keys 10 and 20 "
                     "(Part 4 allows 180); drop --keyframes or use --view native",
     "part4", "This clip cannot be written as Part 4 keys: right_elbow turns 351.1 degrees between keys 10 and 20 "
              "(Part 4 allows 180). Choose another View."),
    # a refusal with no flag in its words is shown as it is
    ("--view part5", "frame 3: times must strictly increase (Part 5 rejects a clip whose times do not)",
     "part5", "This clip cannot be written as a Part 5 animation: frame 3: times must strictly increase "
              "(Part 5 rejects a clip whose times do not). Choose another View."),
    # a refusal that can only be worded with a flag is shown without its reason
    ("--view part4", "needs --keyframes <keyframes.json> or every:<n>", "part4",
     "This clip cannot be written as Part 4 keys. Choose another View."),
])
def test_a_view_refusal_is_worded_for_the_page_without_command_line_flags(path, msg, view, message):
    status, error = code_of(runapi._contract_failure(ContractError(path, msg), view))
    assert (status, error["code"], error["field"], error["message"]) == (422, "view_refused", "view", message)
    assert "--" not in error["message"]


@pytest.mark.parametrize("path", ["pose3d.frames", "keyframes", "every:10", "body measured", "viewer"])
def test_any_other_path_is_still_an_invalid_file(path):
    status, error = code_of(runapi._contract_failure(ContractError(path, "no keyframe falls inside the clip"), "part4"))
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
