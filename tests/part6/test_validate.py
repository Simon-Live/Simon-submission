"""part6/validate.py: one failing case per validity rule of shared-files.md sections 1 to 4."""
import copy
import json
import math
import shutil
from pathlib import Path

import pytest

from part6 import motion, processor, validate

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "fixtures" / "output" / "catalog"
SHARED = processor.generate("squat", 2000, motion.MotionParams(2.0, 1))


def good(name):
    return copy.deepcopy(SHARED[name])


def hits(errors, text):
    return any(text in e for e in errors)


# keyframes.json (section 1)

def test_valid_keyframes():
    assert validate.check_keyframes(good("keyframes")) == []
    assert validate.check_keyframes({"people": []}) == []


@pytest.mark.parametrize("mutate,needle", [
    (lambda d: d.pop("people"), "people"),
    (lambda d: d.update(people={"id": 0}), "people"),
    (lambda d: d["people"][0].pop("repetitions"), "repetitions"),
    (lambda d: d["people"][0]["repetitions"][0].update(keyframes="x"), "keyframes"),
    (lambda d: d["people"][0]["repetitions"][0]["keyframes"][0].pop("name"), "name"),
    (lambda d: d["people"][0]["repetitions"][0]["keyframes"][0].update(name=5), "name"),
    (lambda d: d["people"][0]["repetitions"][0]["keyframes"][0].pop("t_ms"), "t_ms"),
    (lambda d: d["people"][0]["repetitions"][0]["keyframes"][0].update(t_ms=-1), "t_ms"),
    (lambda d: d["people"][0]["repetitions"][0]["keyframes"][0].update(t_ms="5"), "t_ms"),
    (lambda d: d["people"][0]["repetitions"][0]["keyframes"][0].update(t_ms=True), "t_ms"),
    (lambda d: d.update(fps=0), "fps"),
])
def test_invalid_keyframes(mutate, needle):
    data = good("keyframes")
    mutate(data)
    assert hits(validate.check_keyframes(data), needle)


def test_keyframes_must_be_an_object():
    assert validate.check_keyframes([]) != []


# skeleton.json (section 2)

def test_valid_skeleton_and_extra_fields_are_ignored():
    data = good("skeleton")
    data["extra"] = {"anything": 1}
    assert validate.check_skeleton(data) == []


def first_person(data):
    return data["frames"][0]["people"][0]


@pytest.mark.parametrize("mutate,needle", [
    (lambda d: d.update(schema="simon.skeleton/2"), "schema"),
    (lambda d: d.pop("schema"), "schema"),
    (lambda d: d.update(frames=[]), "frames"),
    (lambda d: d.update(frames="x"), "frames"),
    (lambda d: d["frames"][0].update(t_ms="0"), "t_ms"),
    (lambda d: d["frames"][0].pop("t_ms"), "t_ms"),
    (lambda d: d["frames"][0].update(people=None), "people"),
    (lambda d: d["frames"][0].update(people=[{"id": 0, "joints": {}}, {"id": 1}]), "people"),
    (lambda d: first_person(d)["joints"].pop("nose"), "nose"),
    (lambda d: first_person(d)["joints"]["left_knee"].update(x=None), "left_knee"),
    (lambda d: first_person(d)["joints"]["left_knee"].update(y=math.nan), "left_knee"),
    (lambda d: first_person(d)["joints"]["left_knee"].update(z=math.inf), "left_knee"),
    (lambda d: first_person(d).update(joints=[]), "joints"),
    (lambda d: d.pop("bone_lengths_m"), "bone_lengths_m"),
    (lambda d: d.update(bone_lengths_m=[1]), "bone_lengths_m"),
    (lambda d: d["bone_lengths_m"].update(spine=0), "bone_lengths_m"),
    (lambda d: d["bone_lengths_m"].update(spine=-0.4), "bone_lengths_m"),
    (lambda d: d["bone_lengths_m"].update(spine="long"), "bone_lengths_m"),
])
def test_invalid_skeleton(mutate, needle):
    data = good("skeleton")
    mutate(data)
    assert hits(validate.check_skeleton(data), needle)


def test_skeleton_needs_at_least_one_frame_with_a_person():
    data = good("skeleton")
    for frame in data["frames"]:
        frame["people"] = []
    assert hits(validate.check_skeleton(data), "no frame has a person")


def test_skeleton_allows_dropped_frames():
    data = good("skeleton")
    data["frames"][1]["people"] = []
    assert validate.check_skeleton(data) == []


def test_skeleton_must_be_an_object():
    assert validate.check_skeleton(None) != []


# animation.json (section 3)

def test_valid_animation():
    assert validate.check_animation(good("animation")) == []


def test_animation_schema_is_optional_but_checked_when_present():
    data = good("animation")
    del data["schema"]
    assert validate.check_animation(data) == []
    data["schema"] = "simon.animation/9"
    assert hits(validate.check_animation(data), "schema")


@pytest.mark.parametrize("mutate,needle", [
    (lambda d: d.update(fps=0), "fps"),
    (lambda d: d.update(fps=-30), "fps"),
    (lambda d: d.pop("fps"), "fps"),
    (lambda d: d.update(frames=[]), "frames"),
    (lambda d: d["frames"][3].update(frame=4), "frames[3].frame"),
    (lambda d: d["frames"][3].update(t_ms=d["frames"][2]["t_ms"]), "frames[3].t_ms"),
    (lambda d: d["frames"][3].update(t_ms=0.5), "frames[3].t_ms"),
    (lambda d: d["frames"][3].pop("t_ms"), "frames[3].t_ms"),
    (lambda d: d["frames"][3].pop("interpolated"), "interpolated"),
    (lambda d: d["frames"][3].update(interpolated=1), "interpolated"),
    (lambda d: d["frames"][3].update(people=[]), "people"),
    (lambda d: first_person(d)["joints"].pop("right_ankle"), "right_ankle"),
    (lambda d: first_person(d)["joints"]["nose"].update(x="0"), "nose"),
    (lambda d: first_person(d)["joints"]["nose"].update(x=math.nan), "nose"),
])
def test_invalid_animation(mutate, needle):
    data = good("animation")
    mutate(data)
    assert hits(validate.check_animation(data), needle)


def test_animation_error_list_is_capped():
    data = good("animation")
    for frame in data["frames"]:
        frame["people"] = []
    assert len(validate.check_animation(data)) == validate.MAX_ERRORS


# manifest.json (section 4)

def manifest():
    return json.loads((CATALOG / "squat" / "manifest.json").read_text())


def test_valid_manifest():
    assert validate.check_manifest(manifest(), "squat") == []
    data = manifest()
    data["video_uri"] = "video.webm"
    data["files_source"] = "pipeline"
    assert validate.check_manifest(data, "squat") == []


@pytest.mark.parametrize("mutate,needle", [
    (lambda m: m.pop("id"), "id"),
    (lambda m: m.update(id="Squat"), "id"),
    (lambda m: m.update(id="-squat"), "id"),
    (lambda m: m.update(id="x" * 64), "id"),
    (lambda m: m.update(id="other"), "folder name"),
    (lambda m: m.update(name=""), "name"),
    (lambda m: m.update(name="   "), "name"),
    (lambda m: m.update(name=3), "name"),
    (lambda m: m.update(video_uri=5), "video_uri"),
    (lambda m: m.update(keyframes="../keyframes.json"), "keyframes"),
    (lambda m: m.update(skeleton="a/b.json"), "skeleton"),
    (lambda m: m.update(animation=".hidden"), "animation"),
    (lambda m: m.update(thumbnail=None), "thumbnail"),
    (lambda m: m.update(created_at="2026-10-27"), "created_at"),
    (lambda m: m.update(created_at="2026-13-27T00:00:00Z"), "created_at"),
    (lambda m: m.pop("created_at"), "created_at"),
    (lambda m: m.update(schema_version=2), "schema_version"),
    (lambda m: m.update(schema_version=True), "schema_version"),
    (lambda m: m.update(category="yoga"), "category"),
    (lambda m: m.pop("category"), "category"),
    (lambda m: m.update(description=None), "description"),
    (lambda m: m.update(duration_ms=0), "duration_ms"),
    (lambda m: m.update(duration_ms=1000.5), "duration_ms"),
    (lambda m: m.update(duration_ms=True), "duration_ms"),
    (lambda m: m.update(files_source="camera"), "files_source"),
])
def test_invalid_manifest(mutate, needle):
    data = manifest()
    mutate(data)
    assert hits(validate.check_manifest(data, "squat"), needle)


def test_manifest_must_be_an_object():
    assert validate.check_manifest([], "squat") == ["manifest: not an object"]


# entries and catalogs

@pytest.fixture
def entry(tmp_path):
    shutil.copytree(CATALOG / "squat", tmp_path / "squat")
    return tmp_path / "squat"


def test_valid_entry(entry):
    assert validate.check_entry(entry) == []


def test_entry_missing_manifest(tmp_path):
    (tmp_path / "x").mkdir()
    assert hits(validate.check_entry(tmp_path / "x"), "manifest.json: file is missing")


def test_entry_unparseable_manifest(entry):
    (entry / "manifest.json").write_text("{nope")
    assert hits(validate.check_entry(entry), "unreadable JSON")


@pytest.mark.parametrize("name", ["keyframes.json", "skeleton.json", "animation.json",
                                  "thumbnail.svg"])
def test_entry_missing_file(entry, name):
    (entry / name).unlink()
    assert hits(validate.check_entry(entry), f"{name}:")


@pytest.mark.parametrize("name", ["keyframes.json", "skeleton.json", "animation.json"])
def test_entry_invalid_shared_file(entry, name):
    (entry / name).write_text("[]")
    assert hits(validate.check_entry(entry), f"{name}:")


def test_entry_empty_thumbnail(entry):
    (entry / "thumbnail.svg").write_text("")
    assert hits(validate.check_entry(entry), "thumbnail.svg")


def test_entry_id_must_match_its_folder(entry, tmp_path):
    entry.rename(tmp_path / "renamed")
    assert hits(validate.check_entry(tmp_path / "renamed"), "folder name")


def test_catalog_reports_only_invalid_entries_and_ignores_dot_folders(tmp_path):
    for name in ("squat", "arm-wave"):
        shutil.copytree(CATALOG / name, tmp_path / name)
    (tmp_path / "arm-wave" / "animation.json").unlink()
    (tmp_path / ".tmp-half").mkdir()
    (tmp_path / "BadName").mkdir()
    (tmp_path / "file.txt").write_text("x")
    problems = validate.check_catalog(tmp_path)
    assert set(problems) == {"arm-wave", "BadName"}


def test_shipped_catalog_is_valid():
    assert validate.check_catalog(CATALOG) == {}


# create request

@pytest.mark.parametrize("raw,expected", [
    ("Squat", "Squat"), ("  Squat  ", "Squat"), ("a   b   c", "a b c"),
    ("x" * 80, "x" * 80), ("é", "é"), ("Café", "Café"),
])
def test_clean_name_accepts(raw, expected):
    assert validate.clean_name(raw) == expected


@pytest.mark.parametrize("raw", [
    "", "   ", "x" * 81, "a\x00b", "a\x07b", "a\nb", "a\tb", "\x7f", None, 5, ["a"], {"a": 1}])
def test_clean_name_rejects(raw):
    assert validate.clean_name(raw) is None


def test_name_length_counts_after_collapsing():
    assert validate.clean_name("a" + " " * 200 + "b") == "a b"
    assert validate.clean_name(" " + "x" * 80 + " ") == "x" * 80


@pytest.mark.parametrize("body,field", [
    ({}, "name"), ({"name": "a"}, "category"), ({"name": "a", "category": "yoga"}, "category"),
    ({"name": "a", "category": "Dance", "duration_ms": 2000}, "category"),
    ({"name": "a", "category": None, "duration_ms": 2000}, "category"),
    ({"name": "a", "category": ["dance"], "duration_ms": 2000}, "category"),
    ({"name": "a", "category": "dance"}, "duration_ms"),
    ({"name": "a", "category": "dance", "duration_ms": 999}, "duration_ms"),
    ({"name": "a", "category": "dance", "duration_ms": 120001}, "duration_ms"),
    ({"name": "a", "category": "dance", "duration_ms": 2000.0}, "duration_ms"),
    ({"name": "a", "category": "dance", "duration_ms": "2000"}, "duration_ms"),
    ({"name": "a", "category": "dance", "duration_ms": True}, "duration_ms"),
    ({"name": "a", "category": "dance", "duration_ms": None}, "duration_ms"),
    ({"name": "a", "category": "dance", "duration_ms": math.nan}, "duration_ms"),
])
def test_clean_create_request_rejects_the_first_bad_field(body, field):
    assert validate.clean_create_request(body) == (None, field)


@pytest.mark.parametrize("duration", [1000, 1001, 120000])
def test_clean_create_request_accepts_the_bounds(duration):
    fields, bad = validate.clean_create_request(
        {"name": " Hi  there ", "category": "exercise", "duration_ms": duration, "extra": 1})
    assert bad is None
    assert fields == {"name": "Hi there", "category": "exercise", "duration_ms": duration}
