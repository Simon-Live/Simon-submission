"""The Phase 2 command line: profiles, views, fps, people, subcommands (spec integration-contract.md;
AC-B01 to AC-B05, AC-A02, AC-V01 to AC-V04, AC-NFR-001 to AC-NFR-003)."""

import copy
import json
import os
import pathlib
import subprocess
import sys
import time
import types

import pytest

from clipkit import coincident_hips, crowd, write_profile
from conftest import REAL_CLIP, ROOT
from part3 import cli, views
from part3.schema import validate_skeleton
from part5rules import part5_input_rules


@pytest.fixture(autouse=True)
def quiet_environment(tmp_path, monkeypatch):
    """No profile channel from the machine: no PART3_* variables and no part3.toml in the working directory."""
    for key in ("PART3_BODY", "PART3_STATURE", "PART3_CONFIG"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path)


def run(args, capsys):
    code = cli.main([str(a) for a in args])
    return code, capsys.readouterr().err


def go(tmp_path, capsys, *options, source=REAL_CLIP, name="out.json"):
    target = tmp_path / name
    code, err = run(["run", "--in", source, "--out", target, *options], capsys)
    return code, err, target


def written(target):
    return json.loads(pathlib.Path(target).read_text())


# --- profiles on the command line -----------------------------------------------------------------------

def test_ac_b01_a_default_run_records_the_default_body_and_no_adapters(tmp_path, capsys):
    code, err, target = go(tmp_path, capsys)
    out = written(target)
    assert (code, err) == (0, "")
    assert out["body"]["profile"] == "simon-standard" and out["body"]["selected_by"] == "default"
    assert out["input"]["adapters"] == [] and "resample" not in out and out["person"]["rule"] == "most_frames"


@pytest.mark.parametrize("option,profile", [("part4-rig", "part4-rig"), ("measured", "measured"),
                                            ("simon-standard", "simon-standard")])
def test_ac_b02_body_flag_selects_the_profile(tmp_path, capsys, option, profile):
    code, _, target = go(tmp_path, capsys, "--body", option)
    out = written(target)
    assert code == 0 and out["body"]["profile"] == profile and out["body"]["selected_by"] == "flag"
    validate_skeleton(out)


def test_ac_b02_body_file_flag_reads_a_profile_relative_to_the_working_directory(tmp_path, capsys):
    write_profile(tmp_path / "mine.json")
    code, _, target = go(tmp_path, capsys, "--body", "file:mine.json")
    out = written(target)
    assert code == 0 and out["body"]["profile"] == "file:tall-test" and out["standard"]["stature_m"] == 1.9


def test_ac_b03_stature_flag_scales_and_records(tmp_path, capsys):
    code, _, target = go(tmp_path, capsys, "--stature", "1.85")
    out = written(target)
    assert code == 0 and out["standard"]["stature_m"] == 1.85
    assert out["body"]["scale"] == pytest.approx(1.85 / 1.7) and out["body"]["stature_selected_by"] == "flag"


def test_ac_b04_precedence_on_the_command_line(tmp_path, capsys, monkeypatch):
    config = tmp_path / "c.toml"
    config.write_text('[body]\nprofile = "measured"\nstature = 1.6\n')
    code, _, target = go(tmp_path, capsys, "--config", config)
    assert (written(target)["body"]["selected_by"], written(target)["body"]["profile"]) == ("config", "measured")
    monkeypatch.setenv("PART3_BODY", "part4-rig")
    monkeypatch.setenv("PART3_STATURE", "1.7")
    _, _, target = go(tmp_path, capsys, "--config", config)
    body = written(target)["body"]
    assert (body["selected_by"], body["profile"], body["stature_selected_by"]) == ("env", "part4-rig", "env")
    _, _, target = go(tmp_path, capsys, "--config", config, "--body", "simon-standard", "--stature", "1.8")
    body = written(target)["body"]
    assert (body["selected_by"], body["profile"], body["stature_selected_by"]) == ("flag", "simon-standard", "flag")


def test_ac_b04_part3_toml_in_the_working_directory_is_used_and_part3_config_beats_it(tmp_path, capsys, monkeypatch):
    (tmp_path / "part3.toml").write_text('[body]\nprofile = "part4-rig"\n')
    _, _, target = go(tmp_path, capsys)
    assert written(target)["body"]["selected_by"] == "config"
    other = tmp_path / "other.toml"
    other.write_text('[body]\nprofile = "measured"\n')
    monkeypatch.setenv("PART3_CONFIG", str(other))
    _, _, target = go(tmp_path, capsys)
    assert written(target)["body"]["profile"] == "measured"


def test_an_empty_config_file_selects_nothing_and_is_not_an_error(tmp_path, capsys, monkeypatch):
    empty = tmp_path / "empty.toml"
    empty.write_text("")
    monkeypatch.setenv("PART3_CONFIG", str(empty))
    code, err, target = go(tmp_path, capsys)
    out = written(target)
    assert (code, err) == (0, "") and out["body"]["selected_by"] == "default"


@pytest.mark.parametrize("options,fragment", [
    (["--body", "bespoke"], "--body: unknown body profile"),
    (["--stature", "9"], "--stature: stature must be 0.5 to 2.5 m (got 9)"),
    (["--stature", "tall"], "--stature: stature must be 0.5 to 2.5 m"),
    (["--body", "file:missing.json"], "body file:missing.json: cannot read"),
    (["--config", "missing.toml"], "--config: missing.toml: cannot read"),
    (["--fps", "0"], "--fps: must be 1 to 240"),
    (["--fps", "241"], "--fps: must be 1 to 240"),
    (["--input-fps", "-4"], "--input-fps: must be a positive number"),
    (["--view", "bogus"], "--view: must be one of native, part4, part5"),
    (["--person", "9"], "--person 9: not in the input (ids: 0)"),
    (["--keyframes", "every:10"], "--keyframes: only applies to --view part4"),
    (["--keyframes-person", "1"], "--keyframes-person: only applies to --view part4"),
    (["--keyframes-out", "k.json"], "--keyframes-out: only applies to --view part4"),
])
def test_ac_b05_and_nfr_003_a_bad_option_exits_two_naming_it_and_writes_nothing(tmp_path, capsys, options, fragment):
    code, err, target = go(tmp_path, capsys, *options)
    assert code == 2 and fragment in err and "Traceback" not in err
    assert not target.exists() and not (tmp_path / "k.json").exists()


def test_ac_b05_a_bad_toml_file_exits_two_naming_the_file(tmp_path, capsys):
    bad = tmp_path / "bad.toml"
    bad.write_text("[body\n")
    code, err, target = go(tmp_path, capsys, "--config", bad)
    assert code == 2 and str(bad) in err and "not valid TOML" in err and not target.exists()


def test_ac_b05_a_bad_file_profile_exits_two_naming_the_bone(tmp_path, capsys):
    path = write_profile(tmp_path / "p.json", bone_lengths_m={})
    code, err, target = go(tmp_path, capsys, "--body", f"file:{path}")
    assert code == 2 and "bone_lengths_m.left_pelvis: missing" in err and not target.exists()


# --- adapters on the command line ---------------------------------------------------------------------------

def stripped(doc):
    out = copy.deepcopy(doc)
    for frame in out["frames"]:
        del frame["t_ms"]
    return out


def test_ac_a02_input_fps_option_and_the_top_level_fps_both_derive_t_ms(tmp_path, capsys, real_doc):
    source = tmp_path / "no-t.json"
    source.write_text(json.dumps(stripped(real_doc)))
    code, err, target = go(tmp_path, capsys, source=source)
    assert code == 2 and "--input-fps" in err and not target.exists()
    code, _, with_option = go(tmp_path, capsys, "--input-fps", "15", source=source, name="a.json")
    keyed = tmp_path / "keyed.json"
    keyed.write_text(json.dumps(dict(stripped(real_doc), fps=15)))
    code2, _, with_key = go(tmp_path, capsys, source=keyed, name="b.json")
    assert code == code2 == 0
    a, b = written(with_option), written(with_key)
    assert a["input"]["adapters"] == b["input"]["adapters"] == ["derive-t_ms"] and a["frames"] == b["frames"]
    assert a["frames"] == written(go(tmp_path, capsys, name="c.json")[2])["frames"]


# --- views, fps, people ------------------------------------------------------------------------------------------

def test_ac_v04_view_part5_writes_a_file_part5_accepts(tmp_path, capsys):
    code, _, target = go(tmp_path, capsys, "--view", "part5")
    out = written(target)
    assert code == 0 and out["format"] == "simon.animation.v1"
    part5_input_rules(out)


def test_view_native_is_the_default_output(tmp_path, capsys):
    _, _, plain = go(tmp_path, capsys, name="a.json")
    _, _, native = go(tmp_path, capsys, "--view", "native", name="b.json")
    assert plain.read_bytes() == native.read_bytes()


def test_ac_v03_fps_writes_the_grid(tmp_path, capsys):
    code, _, target = go(tmp_path, capsys, "--fps", "30")
    out = written(target)
    assert code == 0 and out["resample"]["fps"] == 30 and len(out["frames"]) == 213
    validate_skeleton(out)


def test_ac_v01_person_flag_converts_digits_to_an_integer_id(tmp_path, capsys, real_doc):
    doc = crowd(real_doc, ids=(7, "7", "guest"), frames=12)
    source = tmp_path / "crowd.json"
    source.write_text(json.dumps(doc))
    for argument, expected in (("7", 7), ("guest", "guest"), ("0", 0)):
        code, _, target = go(tmp_path, capsys, "--person", argument, source=source)
        person = written(target)["person"]
        assert code == 0 and person["id"] == expected and type(person["id"]) is type(expected)
        assert person["rule"] == "requested" and person["requested"] == expected
    code, err, _ = go(tmp_path, capsys, "--person", "8", source=source)
    assert code == 2 and "--person 8: not in the input (ids: 0, 7, 7, guest)" in err


def test_ac_v01_person_and_all_people_together_exit_two(tmp_path, capsys):
    with pytest.raises(SystemExit) as caught:
        run(["run", "--in", REAL_CLIP, "--out", tmp_path / "o", "--person", "0", "--all-people"], capsys)
    assert caught.value.code == 2


def test_ac_v02_all_people_writes_a_folder_per_id_and_the_index(tmp_path, capsys, real_doc):
    doc = coincident_hips(crowd(real_doc, ids=("guest", "a/b", "flat"), frames=16), "flat")
    source, out = tmp_path / "crowd.json", tmp_path / "people-out"
    source.write_text(json.dumps(doc))
    code, err = run(["run", "--in", source, "--out", out, "--all-people"], capsys)
    assert (code, err) == (0, "")
    index = written(out / "people.json")
    assert index["schema"] == "simon.part3.people/1"
    assert [p["id"] for p in index["people"]] == [0, "guest", "a/b", "flat"]
    assert [p.get("dir") for p in index["people"]] == ["person-0", "person-guest", "person-p2", "person-flat"]
    assert index["people"][3]["skipped"].startswith("the chosen person has no usable frame")
    assert "file" not in index["people"][3] and not (out / "person-flat").exists()
    assert sorted(p.name for p in out.iterdir()) == ["people.json", "person-0", "person-guest", "person-p2"]
    for entry in index["people"][:3]:
        skeleton = written(out / entry["file"])
        validate_skeleton(skeleton)
        assert skeleton["person"]["id"] == entry["id"] and skeleton["person"]["frames_present"] == entry["frames_present"]


def test_ac_v02_all_people_in_the_part5_view_writes_part5_files(tmp_path, capsys, real_doc):
    source, out = tmp_path / "crowd.json", tmp_path / "o"
    source.write_text(json.dumps(crowd(real_doc, frames=10)))
    code, _ = run(["run", "--in", source, "--out", out, "--all-people", "--view", "part5"], capsys)
    assert code == 0
    for folder in ("person-0", "person-b"):
        part5_input_rules(written(out / folder / "skeleton.json"))
        assert sorted(p.name for p in (out / folder).iterdir()) == ["skeleton.json"]


def test_all_people_refuses_keyframes_out_and_writes_nothing(tmp_path, capsys):
    out = tmp_path / "o"
    code, err = run(["run", "--in", REAL_CLIP, "--out", out, "--all-people", "--keyframes-out", "k.json"], capsys)
    assert code == 2 and "--keyframes-out: not used with --all-people" in err and not out.exists()


def same_name_run(capsys, source, out, keyframes):
    return run(["run", "--in", source, "--out", out, "--view", "part4", "--keyframes", "every:30",
                "--keyframes-out", keyframes], capsys)


def test_r3_keyframes_out_naming_the_out_file_exits_two_before_anything_runs(tmp_path, capsys):
    same = tmp_path / "skeleton.json"
    code, err = same_name_run(capsys, tmp_path / "missing-input.json", same, same)
    assert code == 2 and err == "--keyframes-out must differ from --out\n"  # the missing input was never read
    assert left_over(tmp_path) == []


@pytest.mark.parametrize("spelling", ["./skeleton.json", "sub/../skeleton.json", "{tmp}/skeleton.json"])
def test_r3_other_spellings_of_the_same_file_are_the_same_file(tmp_path, capsys, monkeypatch, spelling):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "sub").mkdir()
    code, err = same_name_run(capsys, REAL_CLIP, "skeleton.json", spelling.format(tmp=tmp_path))
    assert code == 2 and err == "--keyframes-out must differ from --out\n"
    assert left_over(tmp_path) == ["sub"]


def test_r3_a_symlink_or_hard_link_to_the_out_file_is_the_same_file(tmp_path, capsys):
    out = tmp_path / "skeleton.json"
    out.write_text("old")
    (tmp_path / "soft.json").symlink_to(out)
    os.link(out, tmp_path / "hard.json")
    for alias in ("soft.json", "hard.json"):
        code, err = same_name_run(capsys, REAL_CLIP, out, tmp_path / alias)
        assert code == 2 and err == "--keyframes-out must differ from --out\n", alias
    assert out.read_text() == "old"


def test_all_people_output_that_is_a_file_exits_one(tmp_path, capsys):
    blocker = tmp_path / "blocker"
    blocker.write_text("x")
    code, err = run(["run", "--in", REAL_CLIP, "--out", blocker, "--all-people"], capsys)
    assert code == 1 and "cannot write" in err


def test_a_single_output_in_a_missing_folder_is_created(tmp_path, capsys):
    code, err, _ = go(tmp_path, capsys, name="nope/skeleton.json")
    assert code == 0 and err == "" and (tmp_path / "nope" / "skeleton.json").is_file()


def part4_run(tmp_path, capsys, *, skeleton="skeleton.json", keyframes="keyframes.json"):
    for name in (skeleton, keyframes):  # "nope/x.json": a file named nope, so the folder cannot be made
        if "/" in name:
            (tmp_path / name.split("/")[0]).write_text("in the way")
    args = ["run", "--in", REAL_CLIP, "--out", tmp_path / skeleton, "--view", "part4", "--keyframes", "every:30",
            "--keyframes-out", tmp_path / keyframes]
    return run(args, capsys)


def left_over(folder):
    return sorted(p.name for p in pathlib.Path(folder).iterdir())


def test_r11_a_run_that_writes_two_files_leaves_exactly_those_two(tmp_path, capsys):
    code, err = part4_run(tmp_path, capsys)
    assert (code, err) == (0, "") and left_over(tmp_path) == ["keyframes.json", "skeleton.json"]


def test_r11_a_keyframes_out_that_cannot_be_written_leaves_no_skeleton_behind(tmp_path, capsys):
    code, err = part4_run(tmp_path, capsys, keyframes="nope/keyframes.json")
    assert code == 1 and f"{tmp_path / 'nope' / 'keyframes.json'}: cannot write" in err
    assert left_over(tmp_path) == ["nope"]


def test_r11_a_keyframes_out_that_fails_at_the_rename_removes_the_skeleton_it_had_placed(tmp_path, capsys):
    (tmp_path / "keyframes.json").mkdir()  # a folder where the file should go: the rename fails after the first one
    code, err = part4_run(tmp_path, capsys)
    assert code == 1 and f"{tmp_path / 'keyframes.json'}: cannot write" in err
    assert left_over(tmp_path) == ["keyframes.json"] and (tmp_path / "keyframes.json").is_dir()


def test_r11_a_skeleton_that_cannot_be_written_leaves_no_keyframes_behind(tmp_path, capsys):
    code, err = part4_run(tmp_path, capsys, skeleton="nope/skeleton.json")
    assert code == 1 and f"{tmp_path / 'nope' / 'skeleton.json'}: cannot write" in err
    assert left_over(tmp_path) == ["nope"]


@pytest.mark.skipif(os.geteuid() == 0, reason="root can write to a read-only file")
def test_r11_a_read_only_target_still_exits_one_and_leaves_its_neighbour_unwritten(tmp_path, capsys):
    (tmp_path / "keyframes.json").write_text("locked")
    (tmp_path / "keyframes.json").chmod(0o444)
    code, err = part4_run(tmp_path, capsys)
    assert code == 1 and f"{tmp_path / 'keyframes.json'}: cannot write (Permission denied)" in err
    assert left_over(tmp_path) == ["keyframes.json"] and (tmp_path / "keyframes.json").read_text() == "locked"


def test_r11_a_failed_run_leaves_the_files_that_were_there_untouched(tmp_path, capsys):
    (tmp_path / "skeleton.json").write_text("old skeleton")
    code, _ = part4_run(tmp_path, capsys, keyframes="nope/keyframes.json")
    assert code == 1 and (tmp_path / "skeleton.json").read_text() == "old skeleton"
    assert left_over(tmp_path) == ["nope", "skeleton.json"]


def test_r11_a_failed_all_people_run_leaves_no_file_in_the_folders_it_made(tmp_path, capsys, real_doc):
    source, out = tmp_path / "crowd.json", tmp_path / "o"
    source.write_text(json.dumps(crowd(real_doc, frames=10)))
    out.mkdir()
    (out / "people.json").mkdir()  # the index is written last: its rename fails after the skeletons were placed
    code, err = run(["run", "--in", source, "--out", out, "--all-people"], capsys)
    assert code == 1 and "people.json: cannot write" in err
    leftovers = [p for p in out.rglob("*") if p.is_file()]
    assert leftovers == [], leftovers


def test_an_id_that_cannot_be_encoded_exits_two_and_writes_nothing_with_all_people(tmp_path, capsys, real_doc):
    doc = crowd(real_doc, ids=("bad\udc80id",), frames=6)
    source, out = tmp_path / "in.json", tmp_path / "o"
    source.write_text(json.dumps(doc), encoding="utf-8")
    code, err = run(["run", "--in", source, "--out", out, "--all-people"], capsys)
    assert code == 2 and "UTF-8" in err and not out.exists()


def test_unreadable_input_still_exits_two_with_the_old_message(tmp_path, capsys):
    code, err, target = go(tmp_path, capsys, source=tmp_path / "missing.json")
    assert code == 2 and f"{tmp_path / 'missing.json'}: cannot read" in err and not target.exists()


# --- contract and doctor are delegated ----------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["contract", "doctor"])
def test_contract_and_doctor_pass_the_remaining_arguments_to_their_module(monkeypatch, name):
    seen = []
    module = types.SimpleNamespace(main=lambda argv: seen.append(argv) or 7)
    monkeypatch.setitem(sys.modules, f"part3.{name}", module)
    assert cli.main([name, "--json", "x.json"]) == 7 and seen == [["--json", "x.json"]]


def test_the_real_contract_and_doctor_modules_answer_with_their_own_exit_codes(tmp_path, capsys):
    """Both ship in this build, so delegation has no 'not available in this build' branch."""
    assert cli.main(["contract", "--schema", "no-such-schema"]) == 2
    assert cli.main(["doctor", str(tmp_path / "missing.json")]) == 2
    err = capsys.readouterr().err
    assert "no-such-schema" in err and "missing.json" in err and "not available" not in err


# --- the rule-based ACs -------------------------------------------------------------------------------------------

def test_ac_nfr_001_every_profile_and_view_runs_on_the_squat_in_under_two_seconds(real_doc):
    runs = [{}, {"body": "part4-rig"}, {"body": "measured"}, {"stature": 1.85}, {"fps": 30},
            {"fps": 60, "body": "measured", "stature": 1.7}]
    for kw in runs:
        start = time.perf_counter()
        skeleton = cli.process(real_doc, env={}, config=False, **kw)
        views.render(skeleton, "part5")
        assert time.perf_counter() - start < 2.0, kw


def test_ac_nfr_002_no_runtime_dependency_beyond_numpy_was_added():
    names = {line.split("==")[0].strip().lower() for line in (ROOT / "requirements.txt").read_text().splitlines()
             if line.strip() and not line.startswith("#")}
    assert names <= {"numpy", "pytest"}


def test_ac_nfr_003_a_bad_run_in_a_real_process_prints_a_plain_message_and_no_traceback(tmp_path):
    done = subprocess.run([sys.executable, "-m", "part3", "run", "--in", str(REAL_CLIP),
                           "--out", str(tmp_path / "o.json"), "--body", "bespoke"],
                          cwd=ROOT, capture_output=True, text=True,
                          env={"PATH": "/usr/bin:/bin", "PYTHONPATH": str(ROOT)})
    assert done.returncode == 2 and "--body" in done.stderr and "Traceback" not in done.stderr
    assert not (tmp_path / "o.json").exists()


# --- review B1: a long time span cannot make the run write millions of frames ------------------------------------

def two_frame_file(path, real_doc, last_ms):
    doc = copy.deepcopy(real_doc)
    doc["frames"] = doc["frames"][:2]
    doc["frames"][1]["t_ms"] = last_ms
    path.write_text(json.dumps(doc))
    return path


@pytest.mark.parametrize("last_ms,options,message,budget_s", [
    (10_000_000, ["--fps", "60"], "--fps 60 would write 600001 frames; the limit is 100000", 5.0),
    (1e300, ["--fps", "30"], "--fps 30 would write 3e+298 frames; the limit is 100000", 5.0),
    (1e300, ["--view", "part4", "--keyframes", "every:10"],
     "--keyframes: the 30 fps timeline would have 3e+298 ticks; the limit is 100000", 5.0),
    (10_000_000, ["--view", "part4", "--keyframes", "every:10"],
     "--keyframes: the 30 fps timeline would have 300001 ticks; the limit is 100000", 5.0),
])
def test_b1_a_span_that_needs_too_many_frames_exits_2_fast_with_the_message_and_no_traceback(
        tmp_path, real_doc, last_ms, options, message, budget_s):
    source = two_frame_file(tmp_path / "pose3d.json", real_doc, last_ms)
    start = time.perf_counter()
    done = subprocess.run([sys.executable, "-m", "part3", "run", "--in", str(source),
                           "--out", str(tmp_path / "skeleton.json"), *options],
                          cwd=ROOT, capture_output=True, text=True,
                          env={"PATH": "/usr/bin:/bin", "PYTHONPATH": str(ROOT)})
    assert done.returncode == 2, done.stderr
    assert done.stderr.strip() == message and "Traceback" not in done.stderr
    assert time.perf_counter() - start < budget_s
    assert not (tmp_path / "skeleton.json").exists()


def test_b1_a_span_the_cap_allows_still_runs_from_the_command_line(tmp_path, capsys, real_doc):
    source = two_frame_file(tmp_path / "pose3d.json", real_doc, 3000.0)
    code, err, target = go(tmp_path, capsys, "--fps", "10", source=source)
    assert (code, err) == (0, "") and len(written(target)["frames"]) == 31


def test_b1_process_all_takes_max_frames_too(real_doc):
    doc = copy.deepcopy(real_doc)
    doc["frames"] = doc["frames"][:2]
    doc["frames"][1]["t_ms"] = 3000.0
    assert len(cli.process_all(doc, fps=10, max_frames=31, env={}, config=False)[0][1]["frames"]) == 31
    with pytest.raises(cli.ContractError, match=r"^--fps 10 would write 31 frames; the limit is 30$"):
        cli.process_all(doc, fps=10, max_frames=30, env={}, config=False)
