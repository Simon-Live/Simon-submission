"""`python -m part2 doctor FILE [--for ...]`: kind, version, one verdict per consumer, exit 0, 1 or 2."""
import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest
from test_canonical import _body3d
from test_multi3d import _two_person_body3d

from part2 import contract, doctor
from part2.canonical import convert

ROOT = Path(__file__).resolve().parent.parent
POSE3D = sorted((ROOT / "fixtures" / "output").rglob("pose3d*.json"))
COMMITTED = contract.committed_files(ROOT)
VERSION = "part2.pose3d/2026-10-28"
NAN = float("nan")


def _pose(*, people=1):
    doc = convert(_two_person_body3d() if people == 2 else _body3d([0, 10]))[0]
    return doc


def _write(tmp_path, doc, name="pose3d.json"):
    path = tmp_path / name
    path.write_text(doc if isinstance(doc, str) else json.dumps(doc))  # NaN is written as the token NaN
    return path


def _run(capsys, path, consumer=None, as_json=False):
    code = doctor.command(path, consumer, as_json)
    out = capsys.readouterr()
    return code, out.out, out.err


def _line(out, name):
    return next(line for line in out.splitlines() if line.startswith(f"{name}:"))


# --- AC-C04: the committed outputs --------------------------------------------------------------

@pytest.mark.parametrize("path", POSE3D, ids=[str(p.relative_to(ROOT)) for p in POSE3D])
def test_every_committed_pose3d_is_accepted_for_part3(path, capsys):
    for consumer in (None, "part3"):
        code, out, err = _run(capsys, path, consumer)
        assert code == 0 and err == "" and f"kind pose3d, version {VERSION} (by shape)" in out
        assert _line(out, "Part 3").startswith("Part 3: accepts")


def test_the_single_fixture_is_one_person_accepted_without_an_option(capsys):
    code, out, _ = _run(capsys, ROOT / "fixtures" / "output" / "single" / "pose3d.json")
    assert code == 0 and "1 person, 107 frames" in out and _line(out, "Part 3") == "Part 3: accepts"


@pytest.mark.parametrize("name", ["class", "dance"])
def test_multi_person_fixtures_name_person_and_all_people(name, capsys):
    code, out, _ = _run(capsys, ROOT / "fixtures" / "output" / name / "pose3d.json", "part3")
    assert code == 0
    line = _line(out, "Part 3")
    assert line.startswith("Part 3: accepts with option: several people; fix: ") and "--person <id>" in line and "--all-people" in line


def test_the_class_fixture_prints_the_lines_the_spec_shows(capsys):
    code, out, _ = _run(capsys, ROOT / "fixtures" / "output" / "class" / "pose3d.json")
    assert code == 0
    assert out.splitlines()[1:] == [
        "Part 3: accepts with option: several people; fix: python3 -m part3 run ... --person <id> or --all-people",
        "Part 5: would reject: Part 5 reads skeleton.json; fix: run Part 3 first (--view part5)",
        "Part 6: accepts (generic reader: 17 joints, finite numbers, person id 0 played)"]
    assert out.splitlines()[0].endswith(f"kind pose3d, version {VERSION} (by shape), 7 people, 89 frames")


# --- AC-C04: crafted files, one test per case ---------------------------------------------------

def test_several_people_exit_0_with_the_option(tmp_path, capsys):
    code, out, _ = _run(capsys, _write(tmp_path, _pose(people=2)))
    assert code == 0 and "2 people, 2 frames" in out
    assert _line(out, "Part 3") == "Part 3: accepts with option: several people; fix: python3 -m part3 run ... --person <id> or --all-people"


def test_no_t_ms_exit_0_with_the_input_fps_option(tmp_path, capsys):
    doc = _pose()
    for f in doc["frames"]:
        del f["t_ms"]
    code, out, _ = _run(capsys, _write(tmp_path, doc))
    assert code == 0
    assert _line(out, "Part 3") == "Part 3: accepts with option: no t_ms; fix: python3 -m part3 run ... --input-fps <n> or add a top-level fps"
    assert "schema: breaks part2.pose3d/2026-10-28 at pose3d.frames[0].t_ms: required" in out  # Part 2's own promise still names it


def test_no_t_ms_but_a_top_level_fps_needs_no_option(tmp_path, capsys):
    doc = {**_pose(), "fps": 10}
    for f in doc["frames"]:
        del f["t_ms"]
    code, out, _ = _run(capsys, _write(tmp_path, doc), "part3")
    assert code == 0 and _line(out, "Part 3") == "Part 3: accepts (no t_ms; Part 3 derives it from the top-level fps)"


def test_some_frames_without_t_ms_are_rejected(tmp_path, capsys):
    doc = _pose()
    del doc["frames"][1]["t_ms"]
    code, out, _ = _run(capsys, _write(tmp_path, doc))
    assert code == 1 and "pose3d.frames[1].t_ms: required" in _line(out, "Part 3") and "fix: give every frame a t_ms" in _line(out, "Part 3")


def test_nan_conf_exit_1_names_the_path_and_the_fix(tmp_path, capsys):
    doc = _pose()
    doc["frames"][0]["people"][0]["joints"]["nose"]["conf"] = NAN
    path = _write(tmp_path, doc)
    assert "NaN" in path.read_text()
    code, out, err = _run(capsys, path)
    line = _line(out, "Part 3")
    assert code == 1 and err == ""
    assert line.startswith("Part 3: would reject: pose3d.frames[0].people[0].joints.nose.conf: NaN or infinity is not allowed; fix: write finite numbers")
    assert "Part 6: would reject" in out and "not valid JSON" in _line(out, "Part 6")


def test_a_skeleton_json_is_not_a_part2_file(tmp_path, capsys):
    skeleton = {"schema": "skeleton", "bone_lengths_m": {"upper_arm": 0.3}, "joints": ["nose"], "bones": []}
    code, out, err = _run(capsys, _write(tmp_path, skeleton, "skeleton.json"))
    assert code == 2 and out == ""
    assert err.strip() == f"{tmp_path / 'skeleton.json'}: not a Part 2 file (no frames list)"


def test_a_file_that_is_not_json_exits_2_with_the_line(tmp_path, capsys):
    code, out, err = _run(capsys, _write(tmp_path, '{"frames": [\n  1,\n  oops\n]}'))
    assert code == 2 and out == "" and err.strip() == f"{tmp_path / 'pose3d.json'}: not JSON (line 3)"


def test_unknown_consumer_exits_2(tmp_path, capsys):
    code, out, err = _run(capsys, _write(tmp_path, _pose()), "part9")
    assert code == 2 and out == "" and err.strip() == "doctor: unknown consumer 'part9'; choose part3, part5 or part6"


def test_empty_frames_are_valid_for_the_schema_but_part3_has_no_person(tmp_path, capsys):
    code, out, _ = _run(capsys, _write(tmp_path, {"frames": []}))
    assert code == 1 and "0 people, 0 frames" in out and "(assumed: no people to tell the kinds apart)" in out
    assert _line(out, "Part 3").startswith("Part 3: would reject: no person in any frame; fix: ")
    assert "schema:" not in out


def test_frames_where_nobody_was_found_have_no_person_either(tmp_path, capsys):
    doc = _pose()
    for f in doc["frames"]:
        f["people"] = []
    code, out, _ = _run(capsys, _write(tmp_path, doc))
    assert code == 1 and "kind pose3d" in out and "(by shape)" in out and "no person in any frame" in _line(out, "Part 6")


def test_a_string_person_id_is_accepted(tmp_path, capsys):
    doc = _pose()
    for f in doc["frames"]:
        f["people"][0]["id"] = "dancer-a"
    code, out, _ = _run(capsys, _write(tmp_path, doc))
    assert code == 0 and _line(out, "Part 3") == "Part 3: accepts"
    assert _line(out, "Part 6") == "Part 6: accepts (generic reader: 17 joints, finite numbers, the first person of each frame played)"


def test_a_frame_with_no_people_among_others_is_accepted(tmp_path, capsys):
    doc = _pose()
    doc["frames"][1]["people"] = []
    code, out, _ = _run(capsys, _write(tmp_path, doc))
    assert code == 0 and _line(out, "Part 3") == "Part 3: accepts" and "1 person, 2 frames" in out


def test_part3_rejections_come_with_a_fix(tmp_path, capsys):
    dup = _pose()
    dup["frames"][0]["people"].append(copy.deepcopy(dup["frames"][0]["people"][0]))
    code, out, _ = _run(capsys, _write(tmp_path, dup), "part3")
    assert code == 1 and "duplicate id 0" in out and "fix: give each person one id per frame" in out
    backwards = _pose()
    backwards["frames"][1]["frame"] = 0
    code, out, _ = _run(capsys, _write(tmp_path, backwards), "part3")
    assert code == 1 and "fix: number the frames in increasing order" in out
    missing = _pose()
    del missing["frames"][0]["people"][0]["joints"]["nose"]
    code, out, _ = _run(capsys, _write(tmp_path, missing), "part3")
    assert code == 1 and "fix: follow the schema: python -m part2 contract --schema pose3d" in out


# --- AC-C05: mirrored ---------------------------------------------------------------------------

def test_mirrored_true_is_accepted_and_a_string_is_rejected(tmp_path, capsys):
    code, out, _ = _run(capsys, _write(tmp_path, {**_pose(), "mirrored": True}), "part3")
    assert code == 0 and "mirrored: Part 3 --flip auto mirrors left and right" in out
    code, out, _ = _run(capsys, _write(tmp_path, {**_pose(), "mirrored": "yes"}), "part3")
    assert code == 1 and "pose3d.mirrored" in out and "fix: set mirrored to true or false" in out


# --- AC-C11: the Part 1 time-join warning -------------------------------------------------------

WARNING = "warning: t0_pts_ms is {v}; a consumer joining on file time (Part 1) must add it to t_ms"


@pytest.mark.parametrize("consumer, code", [(None, 0), ("part3", 0), ("part5", 1), ("part6", 0)])
def test_t0_pts_ms_not_zero_warns_with_any_for_and_leaves_the_exit_code(tmp_path, capsys, consumer, code):
    path = _write(tmp_path, {**_pose(), "t0_pts_ms": 2500})
    got, out, _ = _run(capsys, path, consumer)
    assert got == code and out.splitlines()[-1] == WARNING.format(v=2500)
    baseline = _write(tmp_path, _pose(), "plain.json")
    assert _run(capsys, baseline, consumer)[0] == code


def test_a_fractional_t0_pts_ms_is_printed_as_written(tmp_path, capsys):
    _, out, _ = _run(capsys, _write(tmp_path, {**_pose(), "t0_pts_ms": 33.367}))
    assert WARNING.format(v=33.367) in out


@pytest.mark.parametrize("extra", [{}, {"t0_pts_ms": 0}, {"t0_pts_ms": 0.0}])
def test_no_warning_when_t0_pts_ms_is_absent_or_zero(tmp_path, capsys, extra):
    _, out, _ = _run(capsys, _write(tmp_path, {**_pose(), **extra}))
    assert not any(line.startswith("warning:") for line in out.splitlines())


def test_tracks_json_warns_too(tmp_path, capsys):
    tracks = json.loads((ROOT / "fixtures" / "output" / "class" / "tracks.json").read_text())
    _, out, _ = _run(capsys, _write(tmp_path, {**tracks, "t0_pts_ms": 40}, "tracks.json"))
    assert WARNING.format(v=40) in out


# --- the other consumers and kinds ----------------------------------------------------------------

def test_part5_rejects_every_part2_file_and_points_to_part3(tmp_path, capsys):
    code, out, _ = _run(capsys, _write(tmp_path, _pose()), "part5")
    assert code == 1 and out.splitlines()[1] == "Part 5: would reject: Part 5 reads skeleton.json; fix: run Part 3 first (--view part5)"


def test_part6_applies_the_generic_reader_rules(tmp_path, capsys):
    code, out, _ = _run(capsys, _write(tmp_path, _pose(people=2)), "part6")
    assert code == 0 and out.splitlines()[1] == "Part 6: accepts (generic reader: 17 joints, finite numbers, person id 0 played)"
    missing = _pose()
    del missing["frames"][1]["people"][0]["joints"]["left_wrist"]
    code, out, _ = _run(capsys, _write(tmp_path, missing), "part6")
    assert code == 1 and "joint left_wrist is missing or has no finite x, y, z" in out
    no_zero = _pose(people=2)
    for f in no_zero["frames"]:
        f["people"][0]["id"], f["people"][1]["id"] = 5, 6
    _, out, _ = _run(capsys, _write(tmp_path, no_zero), "part6")
    assert "the first person of each frame played" in out


def test_part6_takes_joints_given_as_arrays_and_ignores_extra_joints(tmp_path, capsys):
    doc = _pose()
    joints = doc["frames"][0]["people"][0]["joints"]
    joints["nose"] = [joints["nose"]["x"], joints["nose"]["y"], joints["nose"]["z"], 1.0]
    joints["tail"] = {"x": 0, "y": 0, "z": 0}
    code, out, _ = _run(capsys, _write(tmp_path, doc), "part6")
    assert code == 0 and "Part 6: accepts" in out


def test_kinds_are_told_by_shape(tmp_path, capsys):
    tracks = ROOT / "fixtures" / "output" / "class" / "tracks.json"
    camera = ROOT / "fixtures" / "output" / "single" / "camera.json"
    frames = ROOT / "fixtures" / "input" / "single" / "frames" / "frames.json"
    for path, kind in ((tracks, "tracks"), (camera, "camera"), (frames, "frames")):
        result = doctor.diagnose(path)
        assert (result["kind"], result["version"], result["detected_by"]) == (kind, f"part2.{kind}/2026-10-28", "by shape")
        assert result["schema_error"] is None
    code, out, _ = _run(capsys, tracks)
    assert code == 1 and "kind tracks" in out and _line(out, "Part 3").startswith("Part 3: would reject: Part 3 reads pose3d.json, not tracks.json")
    assert _line(out, "Part 6").startswith("Part 6: would reject: tracks.json holds no joints")
    assert "111 frames" in _run(capsys, frames)[1] and "person" not in _run(capsys, frames)[1].splitlines()[0]


def test_a_broken_tracks_file_names_the_schema_rule(tmp_path, capsys):
    person = {"id": 0, "bbox": [1, 2, 3], "mask_rle": {"size": [4, 5], "counts": "abc"}, "confidence": 0.5}
    tracks = {"frames": [{"frame": 0, "people": [person]}]}
    code, out, _ = _run(capsys, _write(tmp_path, tracks, "tracks.json"), "part3")
    assert code == 1 and "kind tracks" in out and "schema: breaks part2.tracks/2026-10-28 at tracks.frames[0].people[0].bbox" in out


def test_json_flag_prints_the_findings_for_a_program(tmp_path, capsys):
    code, out, _ = _run(capsys, _write(tmp_path, _pose(people=2)), as_json=True)
    result = json.loads(out)
    assert code == result["exit"] == 0
    assert [f["consumer"] for f in result["findings"]] == ["part3", "part5", "part6"]
    assert {"kind", "version", "detected_by", "people", "frames", "warnings", "schema_error"} <= set(result)
    assert set(result["findings"][0]) == {"consumer", "verdict", "reason", "fix"}
    assert [f["verdict"] for f in result["findings"]] == ["accepts with option", "would reject", "accepts"]


def test_json_flag_reports_errors_as_json_with_exit_2(tmp_path, capsys):
    code, out, err = _run(capsys, _write(tmp_path, "nope"), as_json=True)
    assert code == 2 and err == "" and json.loads(out)["exit"] == 2 and "not JSON (line 1)" in json.loads(out)["error"]


def test_diagnose_returns_the_documented_structure(tmp_path):
    result = doctor.diagnose(_write(tmp_path, _pose()), "part3")
    assert (result["kind"], result["version"], result["detected_by"]) == ("pose3d", VERSION, "by shape")
    assert result["findings"] == [{"consumer": "part3", "verdict": "accepts", "reason": "", "fix": ""}]


# --- no stack trace on any input ----------------------------------------------------------------

def _deep(n):
    return "[" * n + "]" * n


BAD_INPUTS = [  # (name, bytes)
    ("empty", b""), ("whitespace", b"  \n"), ("null", b"null"), ("number", b"5"), ("string", b'"frames"'), ("list", b"[]"),
    ("frames not a list", b'{"frames": 5}'), ("frames of numbers", b'{"frames": [1, 2]}'), ("people not a list", b'{"frames": [{"people": 3}]}'),
    ("person not an object", b'{"frames": [{"frame": 0, "t_ms": 0, "people": [1]}]}'),
    ("joints not an object", b'{"frames": [{"frame": 0, "t_ms": 0, "people": [{"id": 0, "joints": 3}]}]}'),
    ("joint not an object", b'{"frames": [{"frame": 0, "t_ms": 0, "people": [{"id": 0, "joints": {"nose": 3}}]}]}'),
    ("unhashable id", b'{"frames": [{"frame": 0, "t_ms": 0, "people": [{"id": [1], "joints": {}}]}]}'),
    ("huge integer", b'{"frames": [{"frame": 0, "t_ms": 1' + b"0" * 400 + b', "people": []}]}'),
    ("overflowing float", b'{"frames": [{"frame": 0, "t_ms": 1e400, "people": []}]}'),
    ("infinity token", b'{"frames": [{"frame": 0, "t_ms": -Infinity, "people": []}]}'),
    ("camera shaped", b'{"camera_frame": "opencv", "K": 1, "frames": [3]}'), ("frames shaped", b'{"frames": [{"file": 3}]}'),
    ("invalid utf-8", b'{"frames": []}\n\xff'), ("lone surrogate", b'{"frames": ["\\ud800"]}'),
    ("bom", b'\xef\xbb\xbf{"frames": []}'), ("deeply nested", _deep(100000).encode()),
    ("deep but valid", b'{"frames": [' + _deep(990).encode() + b"]}"),
    ("random bytes", bytes(range(256))),
]


@pytest.mark.parametrize("name, raw", BAD_INPUTS, ids=[n for n, _ in BAD_INPUTS])
@pytest.mark.parametrize("consumer", [None, "part3", "part5", "part6"])
def test_no_input_gives_a_stack_trace(tmp_path, capsys, name, raw, consumer):
    path = tmp_path / "input.json"
    path.write_bytes(raw)
    code, out, err = _run(capsys, path, consumer)
    assert code in (0, 1, 2) and "Traceback" not in out + err
    assert (code != 2) or err.strip()


def test_a_missing_file_and_a_directory_exit_2(tmp_path, capsys):
    for path in (tmp_path / "missing.json", tmp_path):
        code, out, err = _run(capsys, path)
        assert code == 2 and out == "" and f"{path}: cannot read" in err


def test_a_utf8_byte_order_mark_is_ignored(tmp_path, capsys):
    path = tmp_path / "pose3d.json"
    path.write_bytes(b"\xef\xbb\xbf" + json.dumps(_pose()).encode())
    assert _run(capsys, path)[0] == 0


def test_invalid_utf8_reports_the_line(tmp_path, capsys):
    path = tmp_path / "pose3d.json"
    path.write_bytes(b'{"frames":\n[]\n}\n\xff')
    code, _, err = _run(capsys, path)
    assert code == 2 and err.strip() == f"{path}: not JSON (line 4)"


# --- the command line ---------------------------------------------------------------------------

def _cli(*args):
    return subprocess.run([sys.executable, "-m", "part2", "doctor", *args], cwd=ROOT, capture_output=True, text=True)


def test_python_m_part2_doctor_exit_codes():
    fixture = str(ROOT / "fixtures" / "output" / "class" / "pose3d.json")
    ok, rejected = _cli(fixture, "--for", "part3"), _cli(fixture, "--for", "part5")
    assert (ok.returncode, rejected.returncode) == (0, 1) and ok.stdout.splitlines()[1].startswith("Part 3: accepts with option")
    assert _cli(str(ROOT / "README.md")).returncode == 2
    assert _cli(fixture, "--for", "partx").returncode == 2


def test_python_m_part2_doctor_json_flag():
    r = _cli(str(ROOT / "fixtures" / "output" / "single" / "pose3d.json"), "--json")
    assert r.returncode == 0 and json.loads(r.stdout)["findings"][0]["verdict"] == "accepts"


@pytest.mark.parametrize("path, kind", COMMITTED, ids=[str(p.relative_to(ROOT)) for p, _ in COMMITTED])
def test_every_committed_file_has_a_kind_and_no_schema_error(path, kind):
    result = doctor.diagnose(path)
    assert result["kind"] == kind and result["schema_error"] is None
