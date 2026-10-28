"""Part 4's shipped sets as fixture entries (AC-C13): byte-identical copies in fixtures/part4/,
SOURCE.md that names them, and the two catalog entries built from them."""
import hashlib
import json
import re
from pathlib import Path

import pytest

from part6 import formats, validate

ROOT = Path(__file__).resolve().parents[2]
PART4 = ROOT / "fixtures" / "part4"
CATALOG = ROOT / "fixtures" / "output" / "catalog"
SOURCE = (PART4 / "SOURCE.md").read_text()
SETS = {
    "part4-squat": ("exercise", "Squat (Part 4)", "exercise", 3000, 91, 3.0,
                    "Part 4's shipped squat, three seconds, played from its simon.animation.v1 file."),
    "part4-step-touch": ("dance", "Step-touch (Part 4)", "dance", 4000, 121, 4.0,
                         "Part 4's shipped step-touch, four seconds, played from its simon.animation.v1 file."),
}
PART4_PATHS = {"keyframes": "fixtures/input/{set}/keyframes.json",
               "skeleton": "fixtures/input/{set}/skeleton.json",
               "animation": "fixtures/output/{set}/animation.json"}
FORMAT_OF = {"keyframes": "simon.keyframes.v1", "skeleton": "simon.skeleton.v1",
             "animation": "simon.animation.v1"}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_rows():
    """{file under fixtures/part4: (path in Part 4, sha256)} from the SOURCE.md table."""
    rows = re.findall(r"^\| `([^`]+)` \| `([^`]+)` \| `([0-9a-f]{64})` \|$", SOURCE, re.M)
    return {mine: (theirs, digest) for mine, theirs, digest in rows}


def test_fixtures_part4_holds_six_data_files_and_source_md_and_no_code():
    found = sorted(p.relative_to(PART4).as_posix() for p in PART4.rglob("*") if p.is_file())
    assert found == ["SOURCE.md",
                     "dance/animation.json", "dance/keyframes.json", "dance/skeleton.json",
                     "exercise/animation.json", "exercise/keyframes.json",
                     "exercise/skeleton.json"]


def test_source_md_names_the_repo_the_commit_and_every_file():
    assert "simon-part-4-animate-keyframes" in SOURCE and "9f4c073" in SOURCE
    rows = source_rows()
    assert len(rows) == 6
    for set_name in ("exercise", "dance"):
        for kind, template in PART4_PATHS.items():
            theirs, _ = rows[f"{set_name}/{kind}.json"]
            assert theirs == template.format(set=set_name)


@pytest.mark.parametrize("mine", sorted(source_rows()))
def test_source_md_hashes_match_the_copied_files(mine):
    assert source_rows()[mine][1] == sha(PART4 / mine)


def test_source_md_follows_the_writer_rules():
    em, en = chr(0x2014), chr(0x2013)    # spelled so this file holds neither
    assert em not in SOURCE and en not in SOURCE and " - " not in SOURCE


@pytest.mark.parametrize("entry", SETS)
def test_the_entry_is_the_locked_one(entry):
    folder, name, category, duration_ms, _, _, description = SETS[entry]
    manifest = json.loads((CATALOG / entry / "manifest.json").read_text())
    assert (manifest["id"], manifest["name"], manifest["category"]) == (entry, name, category)
    assert manifest["files_source"] == "fixture" and manifest["video_uri"] is None
    assert manifest["description"] == description and manifest["duration_ms"] == duration_ms
    assert (manifest["keyframes"], manifest["skeleton"], manifest["animation"]) == (
        "keyframes.json", "skeleton.json", "animation.json")
    assert validate.check_entry(CATALOG / entry) == []


@pytest.mark.parametrize("entry", SETS)
def test_the_entry_files_are_byte_identical_to_the_copies_in_fixtures_part4(entry):
    folder = SETS[entry][0]
    for kind in formats.KINDS:
        assert (CATALOG / entry / f"{kind}.json").read_bytes() == (
            PART4 / folder / f"{kind}.json").read_bytes()


@pytest.mark.parametrize("entry", SETS)
def test_the_provenance_is_part_4_with_the_source_path(entry):
    folder = SETS[entry][0]
    provenance = json.loads((CATALOG / entry / "manifest.json").read_text())["provenance"]
    assert set(provenance) == {"keyframes", "skeleton", "animation"}
    for kind, template in PART4_PATHS.items():
        record = provenance[kind]
        assert record["part"] == 4 and record["format"] == FORMAT_OF[kind]
        assert record["detected_by"] == "version"
        assert record["source"] == (
            "simon-part-4-animate-keyframes@9f4c073:" + template.format(set=folder))
        assert record["sha256"] == sha(PART4 / folder / f"{kind}.json")
        assert record["bytes"] == (PART4 / folder / f"{kind}.json").stat().st_size


@pytest.mark.parametrize("entry", SETS)
def test_the_animation_is_part_4_v1_and_plays_for_its_duration(entry):
    _, _, _, duration_ms, frame_count, duration_s, _ = SETS[entry]
    animation = formats.read_animation(json.loads((CATALOG / entry / "animation.json").read_text()))
    assert animation["format"] == "simon.animation.v1" and animation["fps"] == 30
    assert len(animation["frames"]) == frame_count
    assert animation["frames"][-1]["t"] == pytest.approx(duration_s)
    assert round(animation["frames"][-1]["t"] * 1000) == duration_ms


@pytest.mark.parametrize("entry", SETS)
def test_the_skeleton_is_read_as_v1_because_the_format_field_wins(entry):
    raw = json.loads((CATALOG / entry / "skeleton.json").read_text())
    assert raw["format"] == "simon.skeleton.v1" and raw["schema"] == "simon.skeleton/1"
    skeleton = formats.read_skeleton(raw)
    assert skeleton["format"] == "simon.skeleton.v1" and skeleton["keys"]


@pytest.mark.parametrize("entry", SETS)
def test_the_key_frames_are_part_4_v1_marks(entry):
    keyframes = formats.read_keyframes(json.loads((CATALOG / entry / "keyframes.json").read_text()))
    assert keyframes["format"] == "simon.keyframes.v1" and keyframes["marks"]


@pytest.mark.parametrize("entry", SETS)
def test_the_thumbnail_is_drawn(entry):
    svg = (CATALOG / entry / "thumbnail.svg").read_text()
    assert svg.count("<line") == 16 and svg.count("<circle") == 17
