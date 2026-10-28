"""The pure logic of the run app: samples, one run, the error table (docs/specs/run-app.md AC-R01..R05, AC-NFR-05)."""

import copy
import hashlib
import json
import subprocess
import sys
import time

import pytest

from conftest import ROOT
from part3 import bones, cli, runapi
from part3.metrics import BONE_MAX, bone_variation
from part3.schema import validate_skeleton

SAMPLE_IDS = ["part2-squat", "take-1", "take-2", "take-3", "take-4", "take-1-mirrored", "armraise-control"]
SAMPLE_FRAMES = [107, 113, 121, 107, 121, 113, 105]
METRIC_KEYS = ["frames", "frames_present", "frames_dropped", "person_id", "people_in_input",
               "bone_length_variation_output", "bone_length_variation_input", "variation_limit",
               "flips_repaired_frames", "flips_repaired_total", "mirror", "stature_m", "input_height_estimate_m",
               "up_source"]
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
    assert list(body) == ["ok", "source", "flip", "metrics", "input_frames", "bones", "skeleton_text", "run_ms"]
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
    clip["frames"][0]["people"][0]["joints"]["extra" * 100] = {}
    _, error = code_of(upload(clip))
    assert len(error["message"]) <= runapi.MESSAGE_MAX
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
    ("too_large", 413, "This file is larger than 2 MB. Choose a smaller pose3d.json."),
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
