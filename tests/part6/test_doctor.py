"""`python3 -m part6 doctor` (docs/specs/catalog-contract.md AC-C05)."""
import hashlib
import io
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import short_id

from part6 import doctor

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "fixtures" / "output" / "catalog"
PART4 = ROOT / "fixtures" / "part4" / "exercise"
DASHES = (chr(0x2014), chr(0x2013))  # the em and en dash, spelled so this file holds neither
FILE_NAMES = {"keyframes": "keyframes.json", "skeleton": "skeleton.json", "animation": "animation.json"}


def fingerprint(path):
    raw = Path(path).read_bytes()
    return {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def read_manifest(folder):
    return json.loads((folder / "manifest.json").read_text())


def write_manifest(folder, manifest):
    (folder / "manifest.json").write_text(json.dumps(manifest))


@pytest.fixture
def entry(tmp_path):
    """A copy of the Phase 1 squat fixture entry, without provenance."""
    folder = tmp_path / "squat"
    shutil.copytree(CATALOG / "squat", folder)
    manifest = read_manifest(folder)
    manifest.pop("provenance", None)
    write_manifest(folder, manifest)
    return folder


@pytest.fixture
def part4_entry(tmp_path):
    """An entry made of Part 4's v1 files, with provenance that matches them."""
    folder = tmp_path / "part4-squat"
    folder.mkdir()
    provenance = {}
    for kind, name in FILE_NAMES.items():
        shutil.copy(PART4 / name, folder / name)
        fmt = {"keyframes": "simon.keyframes.v1", "skeleton": "simon.skeleton.v1",
               "animation": "simon.animation.v1"}[kind]
        provenance[kind] = {"part": 4, "format": fmt, "detected_by": "version",
                            **fingerprint(folder / name)}
    (folder / "thumbnail.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>")
    write_manifest(folder, {
        "id": "part4-squat", "name": "Squat (Part 4)", "video_uri": None, **FILE_NAMES,
        "created_at": "2026-10-28T00:00:00Z", "schema_version": 1, "category": "exercise",
        "description": "", "thumbnail": "thumbnail.svg", "duration_ms": 3000,
        "files_source": "import", "provenance": provenance})
    return folder


def run_doctor(path):
    out = io.StringIO()
    code = doctor.run(path, out)
    lines = out.getvalue().splitlines()
    return code, lines[:-1], json.loads(lines[-1])


# ---- a good entry ----------------------------------------------------------------------------------

def test_good_entry_exits_0_with_one_ok_line_per_file_and_the_json_line(entry):
    code, lines, summary = run_doctor(entry)
    assert code == 0
    assert lines == [
        "ok manifest.json: manifest v1",
        "ok keyframes.json: simon.keyframes/part1 (shape), part 1",
        "ok skeleton.json: simon.skeleton/1 (version), part 3",
        "ok animation.json: simon.animation/1 (version), part 6",
        "ok thumbnail.svg: thumbnail",
    ]
    assert summary == {"entry": "squat", "ok": True, "plays": "plays animation", "problems": []}


def test_every_shipped_fixture_entry_is_ok(tmp_path):
    folders = sorted(p for p in CATALOG.iterdir() if p.is_dir())
    assert len(folders) >= 8
    for folder in folders:
        code, lines, summary = run_doctor(folder)
        assert code == 0, (folder.name, lines)
        assert summary["ok"] is True and summary["plays"] == "plays animation", folder.name
        assert summary["entry"] == folder.name


def test_part4_entry_reads_its_v1_files_and_names_part_4(part4_entry):
    code, lines, summary = run_doctor(part4_entry)
    assert code == 0, lines
    assert "ok animation.json: simon.animation.v1 (version), part 4" in lines
    assert "ok skeleton.json: simon.skeleton.v1 (version), part 4" in lines
    assert "ok keyframes.json: simon.keyframes.v1 (version), part 4" in lines
    assert summary["plays"] == "plays animation"


def test_provenance_part_wins_over_the_usual_producer(part4_entry):
    manifest = read_manifest(part4_entry)
    manifest["provenance"]["animation"]["part"] = 5
    write_manifest(part4_entry, manifest)
    _, lines, _ = run_doctor(part4_entry)
    assert "ok animation.json: simon.animation.v1 (version), part 5" in lines


def test_skeleton_only_entry_plays_the_skeleton(entry):
    manifest = read_manifest(entry)
    manifest.update(animation=None, keyframes=None)
    write_manifest(entry, manifest)
    (entry / "animation.json").unlink()
    code, lines, summary = run_doctor(entry)
    assert code == 0, lines
    assert summary["plays"] == "plays skeleton (no animation)"
    assert not any("animation.json" in line for line in lines)


def test_animation_only_entry_plays_the_animation(entry):
    manifest = read_manifest(entry)
    manifest["skeleton"] = None
    write_manifest(entry, manifest)
    code, _, summary = run_doctor(entry)
    assert code == 0 and summary["plays"] == "plays animation"


def test_video_is_checked_when_the_manifest_names_one(entry):
    (entry / "video.webm").write_bytes(b"\x1a\x45\xdf\xa3 not a real movie")
    manifest = read_manifest(entry)
    manifest["video_uri"] = "video.webm"
    manifest["provenance"] = {"video": {"part": 1, "format": None, "detected_by": "file",
                                        **fingerprint(entry / "video.webm")}}
    write_manifest(entry, manifest)
    code, lines, summary = run_doctor(entry)
    assert code == 0, lines
    assert "ok video.webm: video (file), part 1" in lines
    assert summary["ok"] is True


def test_missing_video_fails_and_the_entry_still_plays(entry):
    manifest = read_manifest(entry)
    manifest["video_uri"] = "video.mp4"
    write_manifest(entry, manifest)
    code, lines, summary = run_doctor(entry)
    assert code == 1
    assert "fail video.mp4: file is missing" in lines
    assert summary["ok"] is False and summary["plays"] == "plays animation"
    assert summary["problems"] == ["video.mp4: file is missing"]


def test_thumbnail_missing_or_empty_fails(entry):
    (entry / "thumbnail.svg").unlink()
    code, lines, summary = run_doctor(entry)
    assert code == 1 and "fail thumbnail.svg: file is missing" in lines
    (entry / "thumbnail.svg").write_text("")
    code, lines, _ = run_doctor(entry)
    assert code == 1 and "fail thumbnail.svg: file is empty" in lines


# ---- a broken file ----------------------------------------------------------------------------------

def test_broken_animation_with_a_readable_skeleton_plays_the_skeleton_and_is_not_ok(entry):
    animation = json.loads((entry / "animation.json").read_text())
    animation["frames"] = []
    (entry / "animation.json").write_text(json.dumps(animation))
    code, lines, summary = run_doctor(entry)
    assert code == 1
    assert "fail animation.json: frames: must be a non-empty list" in lines
    assert "ok skeleton.json: simon.skeleton/1 (version), part 3" in lines
    assert summary["ok"] is False
    assert summary["plays"] == "plays skeleton (animation unreadable)"
    assert summary["problems"] == ["animation.json: frames: must be a non-empty list"]


def test_fail_line_is_the_reader_message_after_the_word_fail(entry):
    animation = json.loads((entry / "animation.json").read_text())
    del animation["frames"][3]["people"][0]["joints"]["nose"]
    (entry / "animation.json").write_text(json.dumps(animation))
    _, lines, summary = run_doctor(entry)
    message = "animation.json: frames[3].people[0].joints.nose: missing"
    assert f"fail {message}" in lines
    assert summary["problems"] == [message]


def test_a_file_that_is_not_json_is_said_so(entry):
    (entry / "animation.json").write_text("{not json")
    code, lines, summary = run_doctor(entry)
    assert code == 1
    assert "fail animation.json: is not valid JSON" in lines
    assert summary["plays"] == "plays skeleton (animation unreadable)"
    (entry / "animation.json").write_bytes(b"\xff\xfe\x00")
    assert "fail animation.json: is not valid JSON" in run_doctor(entry)[1]


@pytest.mark.parametrize("name", ["manifest.json", "animation.json", "skeleton.json", "keyframes.json"])
@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity", "1e400", "-1e400",
                                      "1" + "0" * 5000, "1" + "0" * 400], ids=short_id)
def test_a_constant_a_browser_cannot_parse_in_an_ignored_field_is_not_valid_json(
        entry, name, constant):
    text = (entry / name).read_text().rstrip()
    (entry / name).write_text(text[:-1] + f', "ignored": {constant}}}')
    code, lines, summary = run_doctor(entry)
    assert code == 1
    assert f"fail {name}: is not valid JSON" in lines
    assert summary["ok"] is False and f"{name}: is not valid JSON" in summary["problems"]


def test_a_single_file_holding_nan_is_not_valid_json(tmp_path):
    bad = tmp_path / "animation.json"
    text = (CATALOG / "squat" / "animation.json").read_text().rstrip()
    bad.write_text(text[:-1] + ', "ignored": NaN}')
    code, lines, summary = run_doctor(bad)
    assert code == 1 and lines == ["fail animation.json: is not valid JSON"]
    assert summary["ok"] is False


@pytest.mark.parametrize("name", ["manifest.json", "animation.json", "skeleton.json", "keyframes.json"])
def test_a_file_with_a_byte_order_mark_is_read_and_its_hash_is_of_the_stored_bytes(
        part4_entry, name):
    path = part4_entry / name
    manifest = read_manifest(part4_entry)
    path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes())
    if name != "manifest.json":
        manifest["provenance"][name.removesuffix(".json")].update(fingerprint(path))
        write_manifest(part4_entry, manifest)
    code, lines, summary = run_doctor(part4_entry)
    assert code == 0 and summary["problems"] == [] and summary["plays"] == "plays animation"


def test_a_single_file_with_a_byte_order_mark_is_read(tmp_path):
    good = tmp_path / "animation.json"
    good.write_bytes(b"\xef\xbb\xbf" + (PART4 / "animation.json").read_bytes())
    code, lines, summary = run_doctor(good)
    assert code == 0 and summary["ok"] is True


def test_a_named_file_that_is_missing_fails_and_the_other_plays(entry):
    (entry / "animation.json").unlink()
    code, lines, summary = run_doctor(entry)
    assert code == 1
    assert "fail animation.json: file is missing" in lines
    assert summary["plays"] == "plays skeleton (animation unreadable)"


def test_nothing_readable_cannot_play_and_gives_the_reason(entry):
    for name in ("animation.json", "skeleton.json"):
        (entry / name).write_text(json.dumps({"fps": 30}))
    code, _, summary = run_doctor(entry)
    assert code == 1 and summary["ok"] is False
    assert summary["plays"].startswith("cannot play: animation.json: ")
    assert summary["plays"] != "cannot play: "


def test_a_wrong_kind_in_a_slot_is_error_e3(entry):
    shutil.copy(entry / "skeleton.json", entry / "animation.json")
    _, lines, summary = run_doctor(entry)
    assert any(line.startswith("fail animation.json: holds simon.skeleton/1, which belongs in skeleton.json")
               for line in lines)
    assert summary["plays"] == "plays skeleton (animation unreadable)"


def test_a_broken_keyframes_file_fails_the_entry_but_it_still_plays(entry):
    (entry / "keyframes.json").write_text(
        json.dumps({"schema": "simon.keyframes/part1", "people": {}}))
    code, lines, summary = run_doctor(entry)
    assert code == 1
    assert "fail keyframes.json: people: must be a list" in lines
    assert summary["plays"] == "plays animation" and summary["ok"] is False


# ---- manifest -----------------------------------------------------------------------------------------

def test_missing_manifest(tmp_path):
    folder = tmp_path / "empty"
    folder.mkdir()
    code, lines, summary = run_doctor(folder)
    assert code == 1
    assert lines == ["fail manifest.json: file is missing"]
    assert summary == {"entry": "empty", "ok": False, "plays": "cannot play: manifest.json is missing",
                       "problems": ["manifest.json: file is missing"]}


def test_manifest_that_is_not_json(entry):
    (entry / "manifest.json").write_text("nope")
    code, lines, summary = run_doctor(entry)
    assert code == 1 and lines == ["fail manifest.json: is not valid JSON"]
    assert summary["ok"] is False


def test_manifest_that_is_not_an_object(entry):
    (entry / "manifest.json").write_text("[]")
    code, lines, summary = run_doctor(entry)
    assert code == 1 and lines[0].startswith("fail manifest.json: ")
    assert summary["plays"] == "cannot play: manifest.json is not an object"


def test_manifest_problems_are_listed_once_per_field(entry):
    manifest = read_manifest(entry)
    manifest.update(category="sport", schema_version=2, duration_ms=0)
    write_manifest(entry, manifest)
    code, lines, summary = run_doctor(entry)
    assert code == 1
    fields = [p.split(": ")[1] for p in summary["problems"] if p.startswith("manifest.json: ")]
    assert sorted(fields) == ["category", "duration_ms", "schema_version"]
    assert summary["plays"] == "plays animation"


def test_a_manifest_with_a_required_key_left_out_fails_even_for_a_nullable_one(entry):
    manifest = read_manifest(entry)
    del manifest["video_uri"]
    write_manifest(entry, manifest)
    code, lines, summary = run_doctor(entry)
    assert code == 1
    assert "fail manifest.json: video_uri: is required" in lines
    assert summary["plays"] == "plays animation"


def test_both_skeleton_and_animation_null_is_one_manifest_problem(entry):
    manifest = read_manifest(entry)
    manifest.update(skeleton=None, animation=None)
    write_manifest(entry, manifest)
    _, _, summary = run_doctor(entry)
    assert len([p for p in summary["problems"] if p.startswith("manifest.json: ")]) == 1


def test_manifest_id_must_equal_the_folder_name(entry, tmp_path):
    other = tmp_path / "renamed"
    entry.rename(other)
    code, lines, summary = run_doctor(other)
    assert code == 1
    assert "fail manifest.json: id: differs from the folder name" in lines
    assert summary["entry"] == "squat"


def test_a_manifest_naming_a_path_outside_the_folder_is_not_followed(entry, tmp_path):
    (tmp_path / "secret.json").write_text("{}")
    manifest = read_manifest(entry)
    manifest["animation"] = "../secret.json"
    write_manifest(entry, manifest)
    code, lines, summary = run_doctor(entry)
    assert code == 1
    assert not any("secret.json: " in line and "not valid" in line for line in lines)
    assert any(line.startswith("fail manifest.json: animation") for line in lines)
    assert summary["plays"] == "plays skeleton (no animation)"


def test_a_manifest_naming_neither_skeleton_nor_animation_cannot_play(entry):
    manifest = read_manifest(entry)
    manifest.update(skeleton=None, animation=None)
    write_manifest(entry, manifest)
    code, _, summary = run_doctor(entry)
    assert code == 1
    assert summary["plays"] == "cannot play: nothing to play: add an animation.json or a skeleton.json"


# ---- provenance hashes --------------------------------------------------------------------------------

def with_provenance(entry, kind, **changes):
    manifest = read_manifest(entry)
    fmt = {"keyframes": "simon.keyframes/part1", "skeleton": "simon.skeleton/1",
           "animation": "simon.animation/1"}[kind]
    claim = {"part": 6, "format": fmt, "detected_by": "version", **fingerprint(entry / FILE_NAMES[kind])}
    claim.update(changes)
    manifest["provenance"] = {kind: claim}
    write_manifest(entry, manifest)


def test_matching_provenance_is_ok(entry):
    with_provenance(entry, "animation")
    code, lines, _ = run_doctor(entry)
    assert code == 0, lines


def test_sha256_mismatch_is_a_problem(entry):
    with_provenance(entry, "animation", sha256="0" * 64)
    code, lines, summary = run_doctor(entry)
    assert code == 1
    assert "fail animation.json: sha256 differs from provenance" in lines
    assert summary["problems"] == ["animation.json: sha256 differs from provenance"]
    assert summary["plays"] == "plays animation"


def test_a_changed_file_is_caught_by_its_hash(entry):
    with_provenance(entry, "skeleton")
    skeleton = json.loads((entry / "skeleton.json").read_text())
    skeleton["frames"][0]["people"][0]["joints"]["nose"]["x"] += 0.001
    (entry / "skeleton.json").write_text(json.dumps(skeleton))
    code, lines, _ = run_doctor(entry)
    assert code == 1 and "fail skeleton.json: sha256 differs from provenance" in lines


def test_size_mismatch_is_a_problem(entry):
    with_provenance(entry, "animation", bytes=5)
    code, lines, _ = run_doctor(entry)
    assert code == 1 and "fail animation.json: size differs from provenance" in lines


def test_video_hash_mismatch(entry):
    (entry / "video.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42")
    manifest = read_manifest(entry)
    manifest["video_uri"] = "video.mp4"
    manifest["provenance"] = {"video": {"part": 1, "format": None, "detected_by": "file",
                                        "sha256": "f" * 64, "bytes": 12}}
    write_manifest(entry, manifest)
    code, lines, _ = run_doctor(entry)
    assert code == 1 and "fail video.mp4: sha256 differs from provenance" in lines


def test_no_provenance_means_no_hash_check(entry):
    manifest = read_manifest(entry)
    assert "provenance" not in manifest
    assert run_doctor(entry)[0] == 0


# ---- a single file ------------------------------------------------------------------------------------

def test_single_file_says_its_kind_and_format(entry):
    code, lines, summary = run_doctor(entry / "animation.json")
    assert code == 0
    assert lines == ["ok animation.json: animation, simon.animation/1 (version), part 6"]
    assert summary == {"entry": "animation.json", "ok": True, "plays": "plays animation", "problems": []}
    code, lines, _ = run_doctor(entry / "keyframes.json")
    assert code == 0 and lines == ["ok keyframes.json: keyframes, simon.keyframes/part1 (shape), part 1"]


def test_single_part4_file(part4_entry):
    code, lines, _ = run_doctor(part4_entry / "skeleton.json")
    assert code == 0
    assert lines == ["ok skeleton.json: skeleton, simon.skeleton.v1 (version), part 4"]


def test_diagnose_adds_kind_and_format_for_a_file(entry):
    result = doctor.diagnose(entry / "skeleton.json")
    assert (result["kind"], result["format"], result["ok"]) == ("skeleton", "simon.skeleton/1", True)
    assert result["plays"] == "plays skeleton (no animation)"


def test_single_file_reports_the_first_error(entry):
    animation = json.loads((entry / "animation.json").read_text())
    animation["fps"] = 0
    animation["frames"] = []
    (entry / "animation.json").write_text(json.dumps(animation))
    code, lines, summary = run_doctor(entry / "animation.json")
    assert code == 1
    assert lines == ["fail animation.json: fps: must be a number above 0"]
    assert summary["ok"] is False and summary["plays"] is None


def test_single_file_that_is_not_json_or_not_an_object(tmp_path):
    bad = tmp_path / "skeleton.json"
    bad.write_text("{oops")
    assert run_doctor(bad)[1] == ["fail skeleton.json: is not valid JSON"]
    bad.write_text("[1, 2]")
    code, lines, _ = run_doctor(bad)
    assert code == 1 and lines == ["fail skeleton.json: is not a JSON object"]


def test_single_file_of_unknown_shape_gets_the_detection_error(tmp_path):
    odd = tmp_path / "notes.json"
    odd.write_text(json.dumps({"hello": 1}))
    code, lines, summary = run_doctor(odd)
    assert code == 1
    assert lines == ["fail notes.json: has no format or schema field and its shape matches no reader"]
    assert summary["plays"] is None


def test_single_file_with_an_unknown_version(tmp_path):
    odd = tmp_path / "animation.json"
    odd.write_text(json.dumps({"format": "simon.animation.v9", "fps": 30, "frames": [{}]}))
    code, lines, _ = run_doctor(odd)
    assert code == 1
    assert lines == ['fail animation.json: format "simon.animation.v9" is not a version Part 6 reads '
                     "(it reads simon.animation/1, simon.animation.v1)"]


# ---- paths, output shape, exit codes ------------------------------------------------------------------

def test_missing_path_exits_2_with_a_message_on_stderr_and_nothing_on_stdout(tmp_path, capsys):
    out = io.StringIO()
    code = doctor.run(tmp_path / "nowhere", out)
    assert code == 2
    assert out.getvalue() == ""
    assert "nowhere" in capsys.readouterr().err


def test_diagnose_raises_for_a_missing_path(tmp_path):
    with pytest.raises(FileNotFoundError):
        doctor.diagnose(tmp_path / "nowhere")


def test_output_lines_follow_the_format_and_end_with_one_json_line(entry):
    animation = json.loads((entry / "animation.json").read_text())
    animation["frames"] = []
    (entry / "animation.json").write_text(json.dumps(animation))
    (entry / "thumbnail.svg").unlink()
    out = io.StringIO()
    doctor.run(entry, out)
    lines = out.getvalue().splitlines()
    assert out.getvalue().endswith("\n")
    for line in lines[:-1]:
        assert re.match(r"^(ok|fail) \S+: .+", line), line
    summary = json.loads(lines[-1])
    assert list(summary) == ["entry", "ok", "plays", "problems"]
    assert isinstance(summary["ok"], bool) and isinstance(summary["problems"], list)
    assert len([ln for ln in lines if ln.startswith("fail ")]) == len(summary["problems"]) == 2
    assert not any(DASHES[0] in line or DASHES[1] in line for line in lines)


def test_ok_is_false_for_any_problem_even_when_it_plays(entry):
    (entry / "thumbnail.svg").unlink()
    result = doctor.diagnose(entry)
    assert result["plays"] == "plays animation" and result["ok"] is False
    assert set(result) == {"entry", "ok", "plays", "problems", "lines"}


def test_the_folder_may_be_given_with_a_trailing_slash_or_as_dot(entry, monkeypatch):
    assert run_doctor(str(entry) + "/")[0] == 0
    monkeypatch.chdir(entry)
    code, _, summary = run_doctor(".")
    assert code == 0 and summary["entry"] == "squat"


def test_cli_exit_codes(entry, tmp_path):
    def cli(path):
        return subprocess.run([sys.executable, "-m", "part6", "doctor", str(path)], cwd=ROOT,
                              capture_output=True, text=True, timeout=60)

    good = cli(entry)
    assert good.returncode == 0, good.stderr
    assert json.loads(good.stdout.splitlines()[-1])["ok"] is True
    (entry / "thumbnail.svg").unlink()
    assert cli(entry).returncode == 1
    missing = cli(tmp_path / "nowhere")
    assert missing.returncode == 2 and missing.stdout == "" and "nowhere" in missing.stderr
