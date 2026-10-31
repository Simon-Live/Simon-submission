"""`part5 doctor` (docs/specs/integration-contract.md): AC-C05 to AC-C09, AC-C11 and AC-C-NFR-01."""
import copy
import json
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from part5 import cli, contract, doctor
from part5.io import JOINTS

ROOT = Path(__file__).resolve().parent.parent
P3 = ROOT / "fixtures/input/contract/part3"
PART4_CLIP = ROOT / "fixtures/input/contract/part4/exercise/animation.json"
PART3_FOLLOWER = P3 / "followers/squat_front_correct/skeleton.json"
PART3_NATIVE = P3 / "native/skeleton.json"
PART3_VIEW4 = P3 / "view-part4/skeleton.json"
EXAMPLE = ROOT / "fixtures/output/analysis.example.json"
NO_FAULTS = ROOT / "fixtures/output/analysis.no-faults.example.json"


def run(args, capsys):
    code = cli.main(["doctor", *map(str, args)])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def write(tmp_path, name, doc):
    p = tmp_path / name
    p.write_text(json.dumps(doc) if not isinstance(doc, str) else doc)
    return p


def handoff(**over):
    """Part 6's Follow hand-off as event detail (Part 6 CONTRACT.md, "The hand-off to Part 7")."""
    base = "https://catalog.invalid/api/entries/part4-squat"
    doc = {"v": 1, "id": "part4-squat", "name": "Squat", "category": "exercise",
           "link": "https://catalog.invalid/#/entry/part4-squat", "manifest": f"{base}/manifest.json",
           "files": {"keyframes": f"{base}/keyframes.json", "skeleton": f"{base}/skeleton.json",
                     "animation": f"{base}/animation.json", "video": None}}
    doc.update(over)
    return doc


def pose3d():
    joints = {n: {"x": 0.01 * i, "y": 0.1 * i, "z": 0.0, "conf": 1.0} for i, n in enumerate(JOINTS)}
    return {"frames": [{"frame": 0, "t_ms": 0.0, "people": [{"id": 0, "joints": joints}]}]}


def refused():
    doc = json.loads(NO_FAULTS.read_text())
    doc["schema_version"] = "1.1.0"
    doc["status"] = {"code": "different_movement", "text": "This does not look like the expected movement."}
    doc["diagnostics"]["guard"] = {"residual": 3.1, "timing_corr": 0.1, "span_share": 0.5}
    doc["score"] = None   # before ADR-0012 a refused take had no score
    return doc


# ---------------------------------------------------------------- AC-C05
def test_ac_c05_part4_animation_is_accepted_and_the_kind_line_names_format_and_origin(capsys):
    code, out, _ = run([PART4_CLIP], capsys)
    assert code == 0
    first = out.splitlines()[0]
    assert "simon.animation.v1 (Part 4 animation.json)" in first and first.endswith("accepted for part5")
    assert "validator: jsonschema" in out and "part5.io.parse_clip" in out


def test_ac_c05_part3_view_part5_follower_is_accepted(capsys):
    code, out, _ = run([PART3_FOLLOWER, "--for", "part5"], capsys)
    assert code == 0 and "simon.animation.v1 (Part 3 --view part5 skeleton.json)" in out


def test_ac_c05_json_prints_one_object(capsys):
    code, out, _ = run([PART4_CLIP, "--json"], capsys)
    doc = json.loads(out)
    assert code == 0 and doc["kind"] == "animation" and doc["version"] == "simon.animation.v1"
    assert doc["verdict"] == "accepted" and doc["exit"] == 0 and doc["for"] == "part5"
    assert doc["problems"] == [] and "jsonschema" in doc["validator"]


def test_part3_view_part4_skeleton_is_named_and_accepted_as_an_expected_clip(capsys):
    code, out, _ = run([PART3_VIEW4], capsys)
    assert code == 0 and "simon.skeleton.v1 (Part 3 --view part4 skeleton.json)" in out
    assert "input-skeleton.schema.json" in out


def test_a_skeleton_v1_not_written_by_part3_is_named_as_such_and_still_judged(tmp_path, capsys):
    clip = json.loads(PART4_CLIP.read_text())
    keys = [{"index": f["index"], "t": f["t"], "name": f"key{f['index']}", "joints": f["joints"]}
            for f in clip["frames"][:3]]
    p = write(tmp_path, "skeleton.json", {"format": "simon.skeleton.v1", "fps": 30, "keyframes": keys,
                                          "rest_offsets_m": {}, "local_rotations": []})
    code, out, _ = run([p], capsys)
    assert code == 0 and "simon.skeleton.v1 (not written by Part 3)" in out


# ---------------------------------------------------------------- AC-C06
def test_ac_c06_part3_native_is_rejected_with_the_fix_named(capsys):
    code, out, _ = run([PART3_NATIVE, "--for", "part5"], capsys)
    assert code == 1
    assert "simon.skeleton/1 (Part 3 native); rejected for part5" in out
    assert 'no "format"' in out and "fix: rerun Part 3 with --view part5" in out


# ---------------------------------------------------------------- AC-C07
@pytest.mark.parametrize("framed", [False, True])
def test_ac_c07_part6_handoff_is_named_and_rejected_with_the_fix(tmp_path, capsys, framed):
    doc = handoff(type="simon:follow") if framed else handoff()
    code, out, _ = run([write(tmp_path, "handoff.json", doc)], capsys)
    assert code == 1
    assert "simon:follow v1 hand-off (Part 6" in out
    assert ("framed message" in out) is framed and ("event detail" in out) is not framed
    assert "Part 6 hand-off; fix: download files.animation and pass it as --expected" in out


def test_ac_c07_a_framed_message_is_named_even_without_files(tmp_path, capsys):
    code, out, _ = run([write(tmp_path, "msg.json", {"type": "simon:follow", "v": 1, "id": "x"})], capsys)
    assert code == 1 and "hand-off (Part 6, framed message)" in out and "--expected" in out


def test_ac_c07_a_handoff_without_an_animation_and_with_another_version_gets_a_note_and_a_warning(tmp_path, capsys):
    doc = handoff(v=2)
    doc["files"]["animation"] = None
    code, out, _ = run([write(tmp_path, "handoff.json", doc)], capsys)
    assert code == 1
    assert "note: files.animation is null" in out and "warning: v is 2" in out


def test_ac_c07_handoff_is_not_an_analysis_for_part7(tmp_path, capsys):
    code, out, _ = run([write(tmp_path, "handoff.json", handoff()), "--for", "part7"], capsys)
    assert code == 1 and "Part 7 reads analysis.json" in out


# ---------------------------------------------------------------- AC-C08
def test_ac_c08_a_refused_analysis_is_accepted_for_part7_with_a_warning(tmp_path, capsys):
    code, out, _ = run([write(tmp_path, "analysis.json", refused()), "--for", "part7"], capsys)
    assert code == 0
    assert "accepted for part7" in out and "simon.analysis.v1 1.1.0" in out
    assert "warning: status.code is 'different_movement' and faults is empty by design" in out


def test_ac_c08_an_ok_analysis_has_no_warning(tmp_path, capsys):
    doc = json.loads(EXAMPLE.read_text())
    doc.update(schema_version="1.1.0", status={"code": "ok", "text": "Analysed."})
    code, out, _ = run([write(tmp_path, "analysis.json", doc), "--for", "part7"], capsys)
    assert code == 0 and "warning" not in out and "status" not in out


def test_ac_c08_an_analysis_missing_format_exits_1(tmp_path, capsys):
    doc = json.loads(EXAMPLE.read_text())
    del doc["format"]
    code, out, _ = run([write(tmp_path, "analysis.json", doc), "--for", "part7"], capsys)
    assert code == 1
    assert "simon.analysis.v1 (no format)" in out
    assert 'format: missing; fix: write "format": "simon.analysis.v1"' in out


def one_point_zero(example):
    """The shipped example as a schema 1.0 writer would have made it (no 1.1.0 fields)."""
    doc = json.loads(example.read_text())
    for key in ("schema_version", "status", "phrasing"):
        doc.pop(key, None)
    doc.get("diagnostics", {}).pop("guard", None)
    for f in doc["faults"]:
        for key in ("runs", "joints", "coaching"):
            f.pop(key, None)
    return doc


def test_a_1_0_analysis_is_accepted_for_part7_with_notes_about_status_and_joints(tmp_path, capsys):
    code, out, _ = run([write(tmp_path, "analysis.json", one_point_zero(EXAMPLE)), "--for", "part7"], capsys)
    assert code == 0 and "simon.analysis.v1 1.0.0 (no schema_version)" in out
    assert "note: no status block (schema 1.0): read it as ok" in out
    assert "faults[].joints is absent" in out


def test_an_invalid_analysis_names_the_field(tmp_path, capsys):
    doc = json.loads(EXAMPLE.read_text())
    doc["faults"][0]["side"] = "middle"
    doc["faults"][1]["magnitude_deg"] = -8.0
    code, out, _ = run([write(tmp_path, "analysis.json", doc), "--for", "part7"], capsys)
    assert code == 1 and "faults[0].side: must be one of" in out and "faults[1]" in out


def test_part5_does_not_read_an_analysis(capsys):
    code, out, _ = run([EXAMPLE], capsys)
    assert code == 1 and "Part 5 does not read analysis.json, it writes it; fix: check it for Part 7" in out


def test_a_clip_is_not_an_analysis_for_part7(capsys):
    code, out, _ = run([PART4_CLIP, "--for", "part7"], capsys)
    assert code == 1 and "Part 7 reads analysis.json; this file is simon.animation.v1" in out


# ---------------------------------------------------------------- AC-C09
def test_ac_c09_a_missing_file_exits_2_naming_it(tmp_path, capsys):
    missing = tmp_path / "nope.json"
    code, out, err = run([missing], capsys)
    assert code == 2 and out == "" and err.strip() == f"part5 doctor: {missing}: no such file"


def test_ac_c09_invalid_json_exits_2_with_line_and_column(tmp_path, capsys):
    p = write(tmp_path, "bad.json", '{"a": 1,\n  "b": }')
    code, _, err = run([p], capsys)
    assert code == 2 and err.strip() == f"part5 doctor: {p}: not JSON (2:8)"


def test_ac_c09_a_directory_and_binary_content_exit_2(tmp_path, capsys):
    code, _, err = run([tmp_path], capsys)
    assert code == 2 and f"{tmp_path}: not a file" in err
    binary = tmp_path / "x.json"
    binary.write_bytes(b"\xff\xfe\x00")
    code, _, err = run([binary], capsys)
    assert code == 2 and "not JSON (not UTF-8 text)" in err


def test_ac_c09_json_mode_prints_the_object_for_an_unreadable_file(tmp_path, capsys):
    code, out, _ = run([tmp_path / "nope.json", "--json"], capsys)
    doc = json.loads(out)
    assert code == 2 and doc["verdict"] == "unreadable" and doc["problems"][0]["message"] == "no such file"


# ---------------------------------------------------------------- AC-C11
def test_ac_c11_part2_pose3d_is_named_accepted_as_a_feet_input_and_not_a_clip(tmp_path, capsys):
    """ADR-0015, AC-FOOT-15: without extra_joints it is accepted with the note "no foot points"; it is still not a
    clip, and the note points to Part 3 for the body."""
    code, out, _ = run([write(tmp_path, "pose3d.json", pose3d()), "--for", "part5"], capsys)
    assert code == 0
    assert "part2.pose3d (Part 2); accepted for part5" in out
    assert "note: no foot points (no extra_joints in any frame" in out
    assert "note: not a clip: for the body pass Part 3's skeleton.json as --expected or --follower; run Part 3 --view part5" in out
    assert "validator: part5.feet.file_summary" in out


def test_ac_c11_part2_pose3d_with_extra_joints_is_accepted_as_a_feet_side_input(tmp_path, capsys):
    doc = pose3d()
    doc["frames"][0]["people"][0]["extra_joints"] = {"left_heel": {"x": 0.1, "y": -0.9, "z": -0.1, "conf": 1.0}}
    doc["mirrored"] = True
    code, out, _ = run([write(tmp_path, "pose3d.json", doc), "--for", "part5"], capsys)
    assert code == 0 and "accepted for part5" in out
    assert "note: feet side input for --expected-feet or --follower-feet: foot points in 1 of 1 frames, people ids [0]" in out
    assert "mirrored, so the left and right foot series are swapped" in out and "no foot points" not in out


def test_ac_c11_a_flat_pose3d_with_joints_and_t_ms_is_not_a_feet_input_either(tmp_path, capsys):
    doc = {"frames": [{"frame": 0, "t_ms": 0.0, "joints": pose3d()["frames"][0]["people"][0]["joints"]}]}
    code, out, _ = run([write(tmp_path, "pose3d.json", doc)], capsys)
    assert code == 1 and "run Part 3 --view part5" in out
    assert "not a feet side input either" in out and "people must be a list" in out


# ---------------------------------------------------------------- violations carry the field and the fix
def broken_clip():
    return json.loads(PART3_FOLLOWER.read_text())


def test_a_schema_violation_prints_field_what_and_fix(tmp_path, capsys):
    doc = broken_clip()
    doc["coordinate_frame"]["x"] = "subject_right"
    doc["frames"][2]["joints"]["nose"] = [0.1, 0.2]
    code, out, _ = run([write(tmp_path, "clip.json", doc)], capsys)
    assert code == 1
    assert 'coordinate_frame.x: must be "subject_left"; fix: write "subject_left"' in out
    assert "frames[2].joints.nose" in out and "; fix:" in out


def test_a_clip_with_no_clock_is_told_to_add_fps(tmp_path, capsys):
    doc = broken_clip()
    del doc["fps"]
    for f in doc["frames"]:
        del f["t"]
    code, out, _ = run([write(tmp_path, "clip.json", doc)], capsys)
    assert code == 1 and "needs a top-level fps or a t on every frame; fix: add fps" in out


def test_a_hip_midpoint_off_the_origin_passes_the_schema_and_fails_the_loader(tmp_path, capsys):
    doc = broken_clip()
    for f in doc["frames"]:
        for j in f["joints"].values():
            j[1] += 0.5
    code, out, _ = run([write(tmp_path, "clip.json", doc)], capsys)
    assert code == 1
    assert "hip midpoint must be at the origin" in out and "fix: subtract the hip midpoint" in out
    assert "part5.io.parse_clip" in out


def test_many_violations_are_capped(tmp_path, capsys):
    doc = broken_clip()
    for f in doc["frames"]:
        f["joints"]["nose"] = [1]
    code, out, _ = run([write(tmp_path, "clip.json", doc)], capsys)
    assert code == 1 and f"{len(doc['frames']) - doctor.MAX_PROBLEMS} more problems not shown" in out


def test_a_clip_with_a_lost_joint_and_conf_is_accepted(tmp_path, capsys):
    doc = broken_clip()
    doc["frames"][1]["joints"]["left_wrist"] = None
    doc["frames"][1]["conf"] = {"left_ankle": 0.1}
    assert run([write(tmp_path, "clip.json", doc)], capsys)[0] == 0


# ---------------------------------------------------------------- other kinds
def test_part5_labels_and_part3_kit_labels_are_named_and_accepted(capsys):
    code, out, _ = run([ROOT / "fixtures/input/followers/labels.json"], capsys)
    assert code == 0 and "labels simon.part5.labels.v1 (Part 5)" in out and "labels.schema.json" in out
    assert "note: evaluation labels" in out
    code, out, _ = run([P3 / "followers/labels.json"], capsys)
    assert code == 0 and "labels simon.part3.follower_labels/1 (Part 3 kit)" in out
    assert "part3/follower-labels.schema.json" in out


def test_labels_with_a_bad_field_are_rejected(tmp_path, capsys):
    doc = json.loads((ROOT / "fixtures/input/followers/labels.json").read_text())
    doc["takes"][2]["faults"][0]["side"] = "middle"
    code, out, _ = run([write(tmp_path, "labels.json", doc)], capsys)
    assert code == 1 and "takes[2].faults[0].side" in out


@pytest.mark.parametrize("doc,what", [
    ({"format": "simon.keyframes.v1", "fps": 30, "keyframes": []}, "Part 4 keyframes.json"),
    ({"schema": "simon.animation/1", "fps": 30, "frames": [{"people": []}]}, "Part 6 provisional animation.json"),
])
def test_files_other_parts_publish_are_named_and_not_read(tmp_path, capsys, doc, what):
    code, out, _ = run([write(tmp_path, "other.json", doc)], capsys)
    assert code == 1 and what in out and "Part 5 does not read it; fix:" in out


def test_an_unknown_format_and_a_missing_format_are_told_apart(tmp_path, capsys):
    code, out, _ = run([write(tmp_path, "a.json", {"format": "simon.animation.v2"})], capsys)
    assert code == 1 and "unknown (format 'simon.animation.v2')" in out and "Part 5 reads simon.animation.v1" in out
    clip = broken_clip()
    del clip["format"]
    code, out, _ = run([write(tmp_path, "b.json", clip)], capsys)
    assert code == 1 and "unknown (no format)" in out and 'format: missing; fix: write "format"' in out
    code, out, _ = run([write(tmp_path, "c.json", [1, 2])], capsys)
    assert code == 1 and "not a JSON object" in out


# ---------------------------------------------------------------- the validators and their fallback
def test_without_jsonschema_the_loaders_run_and_the_output_says_so(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(contract, "have_jsonschema", lambda: False)
    code, out, _ = run([PART4_CLIP], capsys)
    assert code == 0 and "validator: part5 loaders only (the jsonschema package is not installed)" in out
    assert "part5.io.parse_clip" in out and "jsonschema 4" not in out
    code, out, _ = run([EXAMPLE, "--for", "part7"], capsys)
    assert code == 0 and "part5.output.validate_analysis" in out
    broken = broken_clip()
    broken["frames"][0]["joints"]["nose"] = [1]
    code, out, _ = run([write(tmp_path, "clip.json", broken)], capsys)
    assert code == 1 and "frames[0].joints.nose must be [x, y, z]" in out
    code, out, _ = run([ROOT / "fixtures/input/followers/labels.json"], capsys)
    assert code == 0 and "structure only" in out


def test_ac_c_nfr_01_doctor_runs_offline(monkeypatch, tmp_path, capsys):
    def no_network(*a, **k):
        raise AssertionError("network used")
    monkeypatch.setattr(socket, "socket", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    assert run([PART4_CLIP], capsys)[0] == 0
    assert run([write(tmp_path, "handoff.json", handoff()), "--for", "part5"], capsys)[0] == 1
    assert run([EXAMPLE, "--for", "part7"], capsys)[0] == 0


def test_the_command_line_entry_point_exits_with_the_verdict():
    def doctor_cli(*args):
        return subprocess.run([sys.executable, "-m", "part5", "doctor", *map(str, args)],
                              capture_output=True, text=True, cwd=ROOT)
    assert doctor_cli(PART4_CLIP).returncode == 0
    assert doctor_cli(PART3_NATIVE).returncode == 1
    assert doctor_cli(ROOT / "nope.json").returncode == 2
    assert doctor_cli(PART4_CLIP, "--for", "part9").returncode == 2  # usage


def test_every_committed_golden_output_is_accepted_for_part7(capsys):
    for path in sorted((ROOT / "fixtures/output").glob("analysis*.json")):
        assert run([path, "--for", "part7"], capsys)[0] == 0, path


def test_report_to_dict_is_pure_json(capsys):
    r = doctor.inspect_file(PART3_NATIVE)
    doc = copy.deepcopy(r.to_dict())
    assert json.loads(json.dumps(doc, allow_nan=False)) == doc


# ---------------------------------------------------------------- a replay.json (journey-followup.md, AC-R03)
REPLAY = ROOT / "fixtures/output/replay.example.json"


def small_replay(frames=4):
    """The golden replay cut to `frames` expected frames and 3 follower frames (still a sound file)."""
    doc = json.loads(REPLAY.read_text())
    doc["expected"], doc["expected_t"] = doc["expected"][:frames], doc["expected_t"][:frames]
    doc["follower"], doc["follower_t"] = doc["follower"][:3], doc["follower_t"][:3]
    doc["exp_to_fol"] = [0, 1, 1, 2][:frames]
    return doc


@pytest.mark.parametrize("consumer", ["part5", "part7"])
def test_ac_r03_a_valid_replay_is_accepted_and_named(capsys, consumer):
    code, out, _ = run([REPLAY, "--for", consumer], capsys)
    first = out.splitlines()[0]
    assert code == 0 and "simon.replay.v1 1.0.0" in first and first.endswith(f"accepted for {consumer}")
    assert "contracts/replay.schema.json 1.0.0" in out and "part5.contract.replay_problems" in out
    assert "note: 91 expected frames and 76 follower frames" in out


def test_ac_r03_the_default_consumer_is_told_part5_only_writes_the_file(capsys):
    code, out, _ = run([REPLAY], capsys)
    assert code == 0 and "Part 5 writes this file" in out
    assert "Part 5 writes this file" not in run([REPLAY, "--for", "part7"], capsys)[1]


def test_ac_r03_json_mode_names_the_kind_and_version(capsys):
    code, out, _ = run([REPLAY, "--json"], capsys)
    doc = json.loads(out)
    assert code == 0 and doc["kind"] == "replay" and doc["version"] == "1.0.0" and doc["problems"] == []


def test_ac_r03_a_small_replay_is_accepted(tmp_path, capsys):
    assert run([write(tmp_path, "replay.json", small_replay())], capsys)[0] == 0


@pytest.mark.parametrize("change,field,words", [
    (lambda d: d.update(exp_to_fol=d["exp_to_fol"][:3]), "exp_to_fol", "has 3 entries but expected has 4 frames"),
    (lambda d: d.update(expected_t=d["expected_t"][:2]), "expected_t", "has 2 entries but expected has 4 frames"),
    (lambda d: d.update(follower_t=d["follower_t"] + [9.0]), "follower_t", "has 4 entries but follower has 3 frames"),
    (lambda d: d["exp_to_fol"].__setitem__(2, 7), "exp_to_fol[2]", "is 7, outside the 3 follower frames (0 to 2)"),
    (lambda d: d["expected_t"].__setitem__(2, d["expected_t"][1]), "expected_t[2]", "does not come after expected_t[1]"),
    (lambda d: d["follower_t"].__setitem__(1, -1.0), "follower_t[1]", "does not come after follower_t[0]"),
])
def test_ac_r03_a_replay_that_disagrees_with_itself_exits_1_naming_the_field(tmp_path, capsys, change, field, words):
    doc = small_replay()
    change(doc)
    code, out, _ = run([write(tmp_path, "replay.json", doc)], capsys)
    assert code == 1 and "rejected for part5" in out
    assert f"{field}: " in out and words in out and "; fix: " in out
    assert run([write(tmp_path, "r7.json", doc), "--for", "part7"], capsys)[0] == 1


def test_ac_r03_a_bone_past_the_joints_is_named_by_the_schema_and_without_it_by_the_check(monkeypatch, tmp_path, capsys):
    doc = small_replay()
    doc["bones"][0] = [0, 17]
    code, out, _ = run([write(tmp_path, "replay.json", doc)], capsys)
    assert code == 1 and "bones[0][1]: " in out
    monkeypatch.setattr(contract, "have_jsonschema", lambda: False)
    code, out, _ = run([write(tmp_path, "replay.json", doc)], capsys)
    assert code == 1 and "bones[0][1]: is 17, outside the 17 joints (0 to 16)" in out


def test_ac_r03_an_index_past_the_follower_is_counted_once_with_the_first_named(tmp_path, capsys):
    doc = small_replay()
    doc["exp_to_fol"] = [5, 6, 1, 9]
    code, out, _ = run([write(tmp_path, "replay.json", doc)], capsys)
    assert code == 1 and "exp_to_fol[0]: is 5" in out and "(2 more entries are out of range)" in out


def test_ac_r03_a_schema_violation_in_a_replay_is_named_before_the_lengths(tmp_path, capsys):
    doc = small_replay()
    del doc["coordinate_frame"]
    doc["format"] = "simon.replay.v1"
    doc["expected"][0] = [[0.0, 0.0]]
    code, out, _ = run([write(tmp_path, "replay.json", doc)], capsys)
    assert code == 1 and "coordinate_frame: missing" in out and "expected[0]" in out
    assert "part5.contract.replay_problems" not in out   # the lengths run only on a file the schema accepts


def test_ac_r03_a_repetition_replay_checks_its_reps(tmp_path, capsys):
    doc = small_replay()
    doc["reps"] = [{"expected_frames": [0, 3], "follower_frames": [0, 2], "ok": True}]
    code, out, _ = run([write(tmp_path, "ok.json", doc), "--for", "part7"], capsys)
    assert code == 0 and "1 repetitions (reps)" in out
    doc["reps"][0]["follower_frames"] = [0, 3]
    code, out, _ = run([write(tmp_path, "bad.json", doc)], capsys)
    assert code == 1 and "reps[0].follower_frames[1]: is 3, outside the 3 follower frames" in out


def test_ac_r03_without_jsonschema_a_replay_is_checked_structurally(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(contract, "have_jsonschema", lambda: False)
    assert run([REPLAY], capsys)[0] == 0
    doc = small_replay()
    del doc["exp_to_fol"]
    doc["follower_t"] = "soon"
    code, out, _ = run([write(tmp_path, "replay.json", doc)], capsys)
    assert code == 1 and "exp_to_fol: missing" in out and "follower_t: must be an array" in out


def test_ac_r03_a_replay_with_extra_fields_is_accepted(tmp_path, capsys):
    doc = small_replay()
    doc["note"] = {"anything": 1}
    assert run([write(tmp_path, "replay.json", doc)], capsys)[0] == 0


# ---------------------------------------------------------------- what Part 7 reads (AC-C02, ADR-0012, ADR-0014)
def warned_analysis():
    """A 1.6.0 analysis of a take that earned a low_match warning: faults at confidence "low", the score capped at F."""
    doc = json.loads(EXAMPLE.read_text())
    doc["warnings"] = [{"code": "low_match", "text": "This take doesn't closely match the trainer's movement, so the "
                                                     "grade is capped at F. Check that you picked the right movement."}]
    doc["match"] = {"quality": "low", "residual": 0.6122, "timing_corr": 0.4998,
                    "limits": {"max_residual": 0.5677, "min_timing_corr": 0.8336}}
    for f in doc["faults"]:
        f["confidence"] = "low"
    doc["score"].update(value=59, grade="F", capped_by=["low_match"])
    return doc


def test_part7_accepts_a_warned_1_6_0_analysis_and_notes_what_it_carries(tmp_path, capsys):
    doc = warned_analysis()
    assert doc["schema_version"] == "1.6.0" and doc["score"]["tempo"] and doc["insights"] and doc["faults"][0]["cue"]
    code, out, _ = run([write(tmp_path, "analysis.json", doc), "--for", "part7"], capsys)
    assert code == 0 and "simon.analysis.v1 1.6.0; accepted for part7" in out
    assert "warning: low_match: This take doesn't closely match" in out and "warning: warning" not in out
    assert 'note: 2 of 2 faults have confidence "low" (a low match)' in out
    assert "note: score 59 out of 100, grade F, capped at F by low_match" in out
    assert "note: 2 of 2 faults carry at_s and text_timed" in out
    assert "note: score.timeline has 1 window (basis windows): show it as a timeline" in out


def test_part7_accepts_a_warned_analysis_without_jsonschema_too(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(contract, "have_jsonschema", lambda: False)
    code, out, _ = run([write(tmp_path, "analysis.json", warned_analysis()), "--for", "part7"], capsys)
    assert code == 0 and "part5.output.validate_analysis" in out and "warning: low_match:" in out


def test_part7_accepts_its_own_minimal_1_4_0_fallback_analysis(tmp_path, capsys):
    """What Part 7 writes when it has to: 1.4.0, status ok, no faults, no confidence field, no score."""
    doc = {"format": "simon.analysis.v1", "schema_version": "1.4.0",
           "expected": {"path": "expected.json"}, "follower": {"path": "follower.json"},
           "status": {"code": "ok", "text": "Compared with the expected movement."}, "faults": []}
    code, out, _ = run([write(tmp_path, "analysis.json", doc), "--for", "part7"], capsys)
    assert code == 0 and "simon.analysis.v1 1.4.0; accepted for part7" in out and "warning" not in out
    assert "note: no insights and no cues (written before 1.5.0)" in out
    assert "note: no score (written before 1.2.0, or not scored): show the faults only" in out
    assert json.loads(run([write(tmp_path, "a.json", doc), "--for", "part7", "--json"], capsys)[1])["problems"] == []


def test_part7_gets_the_time_and_score_notes_for_the_shipped_goldens(capsys):
    code, out, _ = run([EXAMPLE, "--for", "part7"], capsys)
    assert code == 0 and "note: score 66 out of 100, grade D" in out and "capped" not in out
    assert "note: 2 of 2 faults carry at_s and text_timed" in out
    code, out, _ = run([NO_FAULTS, "--for", "part7"], capsys)
    assert code == 0 and "note: score 100 out of 100, grade A" in out


def test_part7_is_told_when_a_fault_has_no_time(tmp_path, capsys):
    doc = json.loads(EXAMPLE.read_text())
    for f in doc["faults"]:
        for key in ("at_s", "follower_t_s", "follower_runs", "text_timed"):
            f.pop(key)
    code, out, _ = run([write(tmp_path, "analysis.json", doc), "--for", "part7"], capsys)
    assert code == 0 and "faults carry no at_s (written before 1.2.0): show text without a time" in out


def test_every_committed_golden_replay_is_accepted_for_part7(capsys):
    for path in sorted((ROOT / "fixtures/output").glob("replay*.json")):
        assert run([path, "--for", "part7"], capsys)[0] == 0, path
