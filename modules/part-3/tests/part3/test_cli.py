"""The command line and the pipeline's outputs (AC-002 and the rule-based ACs)."""

import copy
import hashlib
import json
import subprocess
import sys
import time

import numpy as np
import pytest

from clipkit import doc_arrays, make_doc, real_skeleton
from conftest import REAL_CLIP, ROOT
from part3 import cli, io
from part3.joints import BONES, JOINTS
from part3.schema import validate_pose3d, validate_skeleton


def run(*args, cwd=ROOT):
    return subprocess.run([sys.executable, "-m", "part3", *map(str, args)], cwd=cwd,
                          capture_output=True, text=True)


@pytest.fixture(scope="module")
def produced(tmp_path_factory):
    out = tmp_path_factory.mktemp("run") / "skeleton.json"
    result = run("run", "--in", REAL_CLIP, "--out", out)
    assert result.returncode == 0, result.stderr
    return out


def test_run_on_the_real_fixture_writes_a_valid_skeleton(produced, real_doc):
    check = subprocess.run([sys.executable, "-m", "part3.schema", str(produced)], cwd=ROOT,
                           capture_output=True, text=True)
    assert check.returncode == 0, check.stderr
    skeleton = json.loads(produced.read_text())
    assert [(f["frame"], f["t_ms"]) for f in skeleton["frames"]] == \
        [(f["frame"], f["t_ms"]) for f in real_doc["frames"]]
    validate_pose3d(skeleton)  # a skeleton.json is also a valid pose3d.json
    validate_skeleton(skeleton)
    assert skeleton["input"]["sha256"] == hashlib.sha256(REAL_CLIP.read_bytes()).hexdigest()


def test_output_is_one_line_with_a_newline_and_contract_key_order(produced):
    text = produced.read_text()
    assert text.endswith("}\n") and text.count("\n") == 1
    skeleton = json.loads(text)
    assert list(skeleton) == ["schema", "units", "frame", "joints", "bones", "standard", "bone_lengths_m",
                              "body", "person", "mirror", "input", "frames"]
    assert list(skeleton["frame"]) == ["origin", "x", "y", "z", "up_source"]
    assert list(skeleton["person"]) == ["id", "rule", "candidates", "frames_present", "frames_dropped",
                                        "few_frames", "measured_bone_lengths_m", "flips_repaired_total"]
    assert list(skeleton["person"]["flips_repaired_total"]) == ["body", "legs", "arms", "face"]
    assert list(skeleton["mirror"]) == ["setting", "applied", "reason"]
    assert list(skeleton["standard"]) == ["stature_m", "sources"]
    assert skeleton["joints"] == list(JOINTS)
    assert [b["name"] for b in skeleton["bones"]] == [b[0] for b in BONES]
    assert list(skeleton["frames"][0]) == ["frame", "t_ms", "people"]
    person = skeleton["frames"][0]["people"][0]
    assert list(person) == ["id", "joints", "flips_repaired"]
    assert list(person["joints"]) == list(JOINTS) and list(person["joints"]["nose"]) == ["x", "y", "z", "conf"]


def test_numbers_are_rounded_to_four_decimals_and_negative_zero_is_written_as_zero(produced):
    seen = {"negative_zero": 0, "floats": 0}

    def parse_float(text):
        seen["floats"] += 1
        seen["negative_zero"] += text == "-0.0"
        digits = text.split(".")[1] if "." in text and "e" not in text.lower() else ""
        assert len(digits) <= 4, text
        return float(text)

    json.loads(produced.read_text(), parse_float=parse_float)
    assert seen["floats"] > 1000 and seen["negative_zero"] == 0


def test_rerun_is_byte_identical(produced, tmp_path):
    again = tmp_path / "again.json"
    assert run("run", "--in", REAL_CLIP, "--out", again).returncode == 0
    assert again.read_bytes() == produced.read_bytes()


def test_cli_output_equals_process_output(produced, real_doc):
    skeleton = cli.process(real_doc, sha256=io.read_json(REAL_CLIP)[1])
    assert io.dumps(skeleton) == produced.read_text()
    assert skeleton == real_skeleton() | {"input": skeleton["input"]}


def test_flip_option_on_the_command_line(tmp_path):
    out = tmp_path / "on.json"
    assert run("run", "--in", REAL_CLIP, "--out", out, "--flip", "on").returncode == 0
    assert json.loads(out.read_text())["mirror"] == {"setting": "on", "applied": True, "reason": "flag on"}


def test_bad_flip_value_exits_two_and_names_the_allowed_values(tmp_path):
    out = tmp_path / "x.json"
    result = run("run", "--in", REAL_CLIP, "--out", out, "--flip", "sideways")
    assert result.returncode == 2
    assert all(word in result.stderr for word in ("auto", "on", "off"))
    assert not out.exists()


def test_output_in_a_missing_directory_is_created(tmp_path):
    result = run("run", "--in", REAL_CLIP, "--out", tmp_path / "nope" / "skeleton.json")
    assert result.returncode == 0 and (tmp_path / "nope" / "skeleton.json").is_file()


def test_empty_frames_and_no_person_exit_two_with_a_reason(tmp_path):
    cases = {"empty": {"frames": []},
             "nobody": {"frames": [{"frame": 0, "t_ms": 0.0, "people": []}]}}
    for name, doc in cases.items():
        source, out = tmp_path / f"{name}.json", tmp_path / f"{name}-out.json"
        source.write_text(json.dumps(doc))
        result = run("run", "--in", source, "--out", out)
        assert result.returncode == 2 and ("empty" in result.stderr or "no person" in result.stderr)
        assert "pose3d.frames" in result.stderr and not out.exists()


def test_unreadable_inputs_exit_two_and_write_nothing(tmp_path):
    out = tmp_path / "out.json"
    junk, binary = tmp_path / "junk.json", tmp_path / "binary.json"
    junk.write_text("{not json")
    binary.write_bytes(b"\xff\xfe\x00\x01")
    for source in (junk, binary, tmp_path / "missing.json"):
        result = run("run", "--in", source, "--out", out)
        assert result.returncode == 2 and str(source) in result.stderr
    assert not out.exists()


def test_json_that_is_not_a_pose3d_object_exits_two(tmp_path):
    out = tmp_path / "out.json"
    for text in ("null", "[]", '"x"'):
        source = tmp_path / "in.json"
        source.write_text(text)
        result = run("run", "--in", source, "--out", out)
        assert result.returncode == 2 and "pose3d: expected an object" in result.stderr
    assert not out.exists()


def test_an_id_that_cannot_be_written_as_utf8_exits_two_and_writes_nothing(real_doc, tmp_path):
    J, conf = doc_arrays(real_doc)
    doc = make_doc(J[:6], conf[:6], pid="\ud800")  # a lone surrogate parses from JSON but cannot be encoded
    source, out = tmp_path / "in.json", tmp_path / "out.json"
    source.write_text(json.dumps(doc), encoding="utf-8")  # json.dumps escapes it as \ud800
    result = run("run", "--in", source, "--out", out)
    assert result.returncode == 2 and "UTF-8" in result.stderr
    assert not out.exists()


def test_missing_arguments_exit_two(tmp_path):
    assert run("run", "--in", REAL_CLIP).returncode == 2
    assert run().returncode == 2


def test_process_trace_and_sha256(real_doc):
    trace = {}
    skeleton = cli.process(real_doc, trace=trace)
    assert set(trace) == {"up_in_input", "up_source"} and len(trace["up_in_input"]) == 3
    expected = hashlib.sha256(json.dumps(real_doc, ensure_ascii=False).encode()).hexdigest()
    assert skeleton["input"]["sha256"] == expected
    assert cli.process(real_doc, sha256="a" * 64)["input"]["sha256"] == "a" * 64


def test_process_does_not_modify_the_input_and_rejects_bad_input(real_doc):
    doc = copy.deepcopy(real_doc)
    cli.process(doc)
    assert doc == real_doc
    doc["frames"][3]["people"][0]["joints"]["nose"]["conf"] = 1.2
    with pytest.raises(cli.ContractError) as caught:
        cli.process(doc)
    assert caught.value.path == "pose3d.frames[3].people[0].joints.nose.conf"


def test_io_helpers(tmp_path):
    assert io.dumps({"a": "é", "b": [1, 2.5]}) == '{"a": "é", "b": [1, 2.5]}\n'
    target = tmp_path / "t.json"
    io.write_text(target, io.dumps({"k": "é"}))
    assert target.read_bytes() == '{"k": "é"}\n'.encode("utf-8")
    assert io.read_json(target) == ({"k": "é"}, hashlib.sha256(target.read_bytes()).hexdigest())
    with pytest.raises(OSError):
        io.write_text(tmp_path / "missing" / "x.json", "x")
    io.write_text(tmp_path / "made" / "x.json", "x", mkdir=True)
    assert (tmp_path / "made" / "x.json").read_text() == "x"
    assert io.dumps({"a": [1, 2]}, separators=(",", ":"), allow_nan=False) == '{"a":[1,2]}\n'
    assert io.dumps({"a": 1}, indent=2) == '{\n  "a": 1\n}\n'


def test_round_clean_folds_negative_zero_for_scalars_and_arrays():
    assert str(io.round_clean(-0.00001, 4)) == "0.0" and io.round_clean(1.23456, 4) == 1.2346
    out = io.round_clean(np.array([-0.00001, 0.12344, 2.0]), 4)
    assert out.tolist() == [0.0, 0.1234, 2.0] and not np.signbit(out).any()


def test_a_thousand_frame_clip_runs_in_under_ten_seconds(real_doc, tmp_path):
    J, conf = doc_arrays(real_doc)
    reps = -(-1000 // len(J))
    tiled = make_doc(np.tile(J, (reps, 1, 1))[:1000], np.tile(conf, (reps, 1))[:1000])
    source, out = tmp_path / "long.json", tmp_path / "long-out.json"
    source.write_text(json.dumps(tiled))
    start = time.perf_counter()
    result = run("run", "--in", source, "--out", out)
    elapsed = time.perf_counter() - start
    assert result.returncode == 0, result.stderr
    assert elapsed < 10.0
    assert len(json.loads(out.read_text())["frames"]) == 1000
