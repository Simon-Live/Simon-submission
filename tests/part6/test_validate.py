"""part6/validate.py: one failing case per validity rule of shared-files.md sections 1 to 3 (the
strict checks of Part 6's own shapes) and of the manifest v1 and entry rules (AC-C01, AC-F12)."""
import copy
import hashlib
import json
import math
import shutil
from pathlib import Path

import pytest
from conftest import short_id

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

PROVENANCE_FILE = {"part": 6, "format": None, "detected_by": "file", "sha256": "0" * 64,
                   "bytes": 10}


def manifest():
    return json.loads((CATALOG / "squat" / "manifest.json").read_text())


def test_a_valid_provenance_with_every_optional_field_and_a_video():
    data = manifest()
    data["provenance"]["video"] = dict(PROVENANCE_FILE, source="phone", original_name="take.mp4")
    data["provenance"]["animation"].update(source="Part 4 at 9f4c073", original_name="a.json")
    data["visitor"] = True
    assert validate.check_manifest(data, "squat") == []


def test_provenance_may_hold_fewer_kinds_than_the_manifest_names():
    data = manifest()
    data["provenance"] = {"animation": data["provenance"]["animation"]}
    assert validate.check_manifest(data, "squat") == []
    data["provenance"] = {}
    assert validate.check_manifest(data, "squat") == []


def test_an_unknown_provenance_key_and_unknown_record_fields_are_ignored_not_errors():
    data = manifest()
    data["provenance"]["pose3d"] = dict(PROVENANCE_FILE, format="simon.pose3d/9")
    data["provenance"]["audio"] = "anything at all"
    data["provenance"]["animation"]["future"] = {"nested": [1, 2]}
    assert validate.check_manifest(data, "squat") == []


def test_known_provenance_keys_keep_their_checks_beside_unknown_ones():
    data = manifest()
    data["provenance"]["pose3d"] = {}
    data["provenance"]["skeleton"]["part"] = 9
    assert validate.check_manifest(data, "squat") == [
        "provenance.skeleton.part: must be a whole number from 1 to 7, or null"]


def test_a_null_provenance_part_is_valid_and_a_missing_one_is_not():
    data = manifest()
    data["provenance"]["skeleton"]["part"] = None
    assert validate.check_manifest(data, "squat") == []
    del data["provenance"]["skeleton"]["part"]
    assert validate.check_manifest(data, "squat") == [
        "provenance.skeleton.part: must be a whole number from 1 to 7, or null"]


def test_valid_manifest():
    assert validate.check_manifest(manifest(), "squat") == []
    data = manifest()
    data["video_uri"] = "video.webm"
    data["files_source"] = "processor"
    assert validate.check_manifest(data, "squat") == []


@pytest.mark.parametrize("source", ["fixture", "mock", "import", "processor"])
def test_every_files_source_of_v1_is_valid(source):
    data = manifest()
    data["files_source"] = source
    assert validate.check_manifest(data, "squat") == []


def test_phase_1_manifests_without_provenance_stay_valid():
    data = manifest()
    data.pop("provenance")
    assert "visitor" not in data
    assert validate.check_manifest(data, "squat") == []


def test_extra_manifest_fields_are_ignored():
    data = manifest()
    data["future_field"] = {"anything": [1, 2]}
    assert validate.check_manifest(data, "squat") == []


def test_a_kind_may_be_null_when_the_entry_still_plays():
    for kinds in ({"keyframes": None}, {"animation": None}, {"skeleton": None},
                  {"keyframes": None, "skeleton": None}):
        data = manifest()
        data.update(kinds)
        assert validate.check_manifest(data, "squat") == [], kinds


@pytest.mark.parametrize("field", ["video_uri", "keyframes", "skeleton", "animation"])
def test_a_nullable_key_left_out_is_missing_not_null(field):
    data = manifest()
    del data[field]
    assert validate.check_manifest(data, "squat") == [
        f"{field}: is required"]
    data[field] = None
    assert validate.check_manifest(data, "squat") == []


def test_an_entry_whose_manifest_leaves_a_key_out_is_reported_not_crashed(entry):
    data = json.loads((entry / "manifest.json").read_text())
    del data["keyframes"], data["video_uri"]
    (entry / "manifest.json").write_text(json.dumps(data))
    assert validate.check_entry(entry) == [
        "manifest.json: video_uri: is required",
        "manifest.json: keyframes: is required"]


def test_an_entry_with_neither_skeleton_nor_animation_is_invalid():
    data = manifest()
    data.update(skeleton=None, animation=None)
    assert hits(validate.check_manifest(data, "squat"), "at least one")
    del data["skeleton"], data["animation"]
    assert hits(validate.check_manifest(data, "squat"), "at least one")


@pytest.mark.parametrize("mutate,needle", [
    (lambda m: m.pop("id"), "id"),
    (lambda m: m.update(id="Squat"), "id"),
    (lambda m: m.update(id="-squat"), "id"),
    (lambda m: m.update(id="x" * 64), "id"),
    (lambda m: m.update(id="other"), "folder name"),
    (lambda m: m.update(name=""), "name"),
    (lambda m: m.update(name="   "), "name"),
    (lambda m: m.update(name=" Squat"), "name"),
    (lambda m: m.update(name="Squat "), "name"),
    (lambda m: m.update(name="x" * 81), "name"),
    (lambda m: m.update(name=3), "name"),
    (lambda m: m.update(video_uri=5), "video_uri"),
    (lambda m: m.update(video_uri="https://x.example/take.webm"), "video_uri"),
    (lambda m: m.update(video_uri="sub/take.webm"), "video_uri"),
    (lambda m: m.update(keyframes="../keyframes.json"), "keyframes"),
    (lambda m: m.update(keyframes=5), "keyframes"),
    (lambda m: m.update(skeleton="a/b.json"), "skeleton"),
    (lambda m: m.update(animation=".hidden"), "animation"),
    (lambda m: m.pop("animation") and m.update(skeleton=None), "animation"),
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
    (lambda m: m.update(files_source="pipeline"), "files_source"),
    (lambda m: m.update(visitor="yes"), "visitor"),
    (lambda m: m.update(visitor=1), "visitor"),
    (lambda m: m.update(provenance=[]), "provenance"),
    (lambda m: m["provenance"].update(skeleton="x"), "provenance.skeleton"),
    (lambda m: m["provenance"]["skeleton"].update(part=0), "provenance.skeleton.part"),
    (lambda m: m["provenance"]["skeleton"].update(part=8), "provenance.skeleton.part"),
    (lambda m: m["provenance"]["skeleton"].update(part=True), "provenance.skeleton.part"),
    (lambda m: m["provenance"]["skeleton"].pop("part"), "provenance.skeleton.part"),
    (lambda m: m["provenance"]["skeleton"].update(format="simon.animation/1"),
     "provenance.skeleton.format"),
    (lambda m: m["provenance"]["skeleton"].update(format=None), "provenance.skeleton.format"),
    (lambda m: m["provenance"]["skeleton"].pop("format"), "provenance.skeleton.format"),
    (lambda m: m["provenance"]["skeleton"].update(detected_by="guess"),
     "provenance.skeleton.detected_by"),
    (lambda m: m["provenance"]["skeleton"].update(detected_by="file"),
     "provenance.skeleton.detected_by"),
    (lambda m: m["provenance"]["skeleton"].update(sha256="abc"), "provenance.skeleton.sha256"),
    (lambda m: m["provenance"]["skeleton"].update(sha256="A" * 64), "provenance.skeleton.sha256"),
    (lambda m: m["provenance"]["skeleton"].pop("sha256"), "provenance.skeleton.sha256"),
    (lambda m: m["provenance"]["skeleton"].update(bytes=-1), "provenance.skeleton.bytes"),
    (lambda m: m["provenance"]["skeleton"].update(bytes=1.5), "provenance.skeleton.bytes"),
    (lambda m: m["provenance"]["skeleton"].update(bytes="9"), "provenance.skeleton.bytes"),
    (lambda m: m["provenance"]["skeleton"].update(source=4), "provenance.skeleton.source"),
    (lambda m: m["provenance"]["skeleton"].update(original_name=[]),
     "provenance.skeleton.original_name"),
    (lambda m: m["provenance"].update(video=dict(PROVENANCE_FILE, format="simon.animation/1",
                                                 detected_by="file")), "provenance.video.format"),
    (lambda m: m["provenance"].update(video=dict(PROVENANCE_FILE, format=None,
                                                 detected_by="shape")), "provenance.video.detected_by"),
])
def test_invalid_manifest(mutate, needle):
    data = manifest()
    mutate(data)
    assert hits(validate.check_manifest(data, "squat"), needle)


def test_manifest_must_be_an_object():
    assert validate.check_manifest([], "squat") == ["manifest: not an object"]


def test_every_shipped_manifest_has_provenance_that_matches_its_files():
    for folder in sorted(CATALOG.iterdir()):
        data = json.loads((folder / "manifest.json").read_text())
        for kind, record in data["provenance"].items():
            raw = (folder / data[kind]).read_bytes()
            assert record["sha256"] == hashlib.sha256(raw).hexdigest(), (folder.name, kind)
            assert record["bytes"] == len(raw)


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
    assert validate.check_entry(entry) == ["manifest.json: is not valid JSON"]


@pytest.mark.parametrize("name", ["keyframes.json", "skeleton.json", "animation.json",
                                  "thumbnail.svg"])
def test_entry_missing_file(entry, name):
    (entry / name).unlink()
    assert hits(validate.check_entry(entry), f"{name}:")


@pytest.mark.parametrize("name", ["keyframes.json", "skeleton.json", "animation.json"])
def test_entry_invalid_shared_file(entry, name):
    (entry / name).write_text("[]")
    assert validate.check_entry(entry) == [f"{name}: is not a JSON object"]


@pytest.mark.parametrize("name", ["keyframes.json", "skeleton.json", "animation.json"])
def test_entry_shared_file_that_is_not_json(entry, name):
    (entry / name).write_text("{nope")
    assert validate.check_entry(entry) == [f"{name}: is not valid JSON"]


@pytest.mark.parametrize("name", ["manifest.json", "keyframes.json", "skeleton.json", "animation.json"])
def test_entry_file_holding_a_constant_a_browser_cannot_parse_is_not_valid_json(entry, name):
    text = (entry / name).read_text().rstrip()
    (entry / name).write_text(text[:-1] + ', "ignored": NaN}')
    assert validate.check_entry(entry) == [f"{name}: is not valid JSON"]


@pytest.mark.parametrize("name", ["manifest.json", "keyframes.json", "skeleton.json", "animation.json"])
def test_entry_file_with_a_byte_order_mark_is_valid(entry, name):
    raw = (entry / name).read_bytes()
    (entry / name).write_bytes(b"\xef\xbb\xbf" + raw)
    assert validate.check_entry(entry) == []


@pytest.mark.parametrize("raw,ok", [
    (b'{"a": 1}', True), (b'\xef\xbb\xbf{"a": 1}', True), ('{"a": 1}', True),
    (b"NaN", False), (b"Infinity", False), (b"-Infinity", False), (b'{"a": [NaN]}', False),
    (b'\xef\xbb\xbf{"a": -Infinity}', False), (b"", False), (b"\xff", False), (b"[" * 200000, False),
    (b'{"a": 1e999}', False), (b'{"a": 1e308, "b": -1.7976931348623157e308}', True)])
def test_parse_json_is_as_strict_as_a_browser(raw, ok):
    if ok:
        assert isinstance(validate.parse_json(raw), dict)
    else:
        with pytest.raises(validate.NotJson, match="^is not valid JSON$"):
            validate.parse_json(raw)


BIG_INT = "1" + "0" * 5000


@pytest.mark.parametrize("raw", ["1e400", "-1e400", "1E+400", "1.5e999", "[1, {\"a\": -1e400}]",
                                 BIG_INT, "-" + BIG_INT, "1" + "0" * 400, "-1" + "0" * 400,
                                 "[" + BIG_INT + "]"], ids=short_id)
def test_parse_json_refuses_a_number_that_does_not_fit_a_double(raw):
    for given in (raw, raw.encode(), b"\xef\xbb\xbf" + raw.encode()):
        with pytest.raises(validate.NotJson, match="^is not valid JSON$"):
            validate.parse_json(given)


@pytest.mark.parametrize("raw,value", [
    ("1e308", 1e308), ("-1.7976931348623157e308", -1.7976931348623157e308), ("1" + "0" * 308, 1e308),
    ("-1" + "0" * 307, -1e307), ("1" + "0" * 300, 10 ** 300), ("12345678901234567890123", 12345678901234567890123),
    ("1e-400", 0.0), ("0.1", 0.1), ("-0", 0), ("123456789", 123456789)])
def test_parse_json_reads_a_large_finite_number(raw, value):
    parsed = validate.parse_json(raw)
    assert parsed == value and math.isfinite(parsed)
    assert validate.parse_json(f"[{raw}]") == [value]


def test_parse_float_refuses_only_a_result_that_is_not_finite():
    assert validate.parse_float("1.5") == 1.5 and validate.parse_float("1.7e308") == 1.7e308
    for text in ("1e400", "-1e400", "1.5e999"):
        with pytest.raises(ValueError):
            validate.parse_float(text)


def test_parse_int_reads_an_integer_longer_than_pythons_digit_limit_as_a_float():
    assert len(BIG_INT) > 4300
    with pytest.raises(ValueError):
        int(BIG_INT)                            # what the default parser would do with it
    for text in (BIG_INT, "-" + BIG_INT, "1" + "0" * 400):
        with pytest.raises(ValueError):
            validate.parse_int(text)            # read as a float, which is not finite
    assert validate.parse_int("42") == 42 and isinstance(validate.parse_int("42"), int)
    assert validate.parse_int("1" + "0" * 300) == 10 ** 300


def test_a_shared_number_that_is_not_finite_never_reaches_is_number():
    # is_number would raise OverflowError on an integer of 400 digits; the parser refuses it first
    with pytest.raises(validate.NotJson):
        validate.parse_json('{"fps": ' + "1" * 400 + "}")


@pytest.mark.parametrize("name", ["manifest.json", "keyframes.json", "skeleton.json", "animation.json"])
@pytest.mark.parametrize("number", ["1e400", "-1e400", BIG_INT], ids=short_id)
def test_entry_file_holding_a_number_that_does_not_fit_a_double_is_not_valid_json(
        entry, name, number):
    text = (entry / name).read_text().rstrip()
    (entry / name).write_text(text[:-1] + f', "ignored": {number}}}')
    assert validate.check_entry(entry) == [f"{name}: is not valid JSON"]


def test_read_json_says_missing_or_not_valid_json(tmp_path):
    with pytest.raises(ValueError, match="^file is missing$"):
        validate.read_json(tmp_path / "nope.json")
    (tmp_path / "bad.json").write_text("{")
    with pytest.raises(validate.NotJson, match="^is not valid JSON$"):
        validate.read_json(tmp_path / "bad.json")
    with pytest.raises(ValueError, match="^unreadable: "):
        validate.read_json(tmp_path)


def test_entry_reader_errors_are_the_formats_messages(entry):
    data = json.loads((entry / "animation.json").read_text())
    data["schema"] = "simon.animation/9"
    (entry / "animation.json").write_text(json.dumps(data))
    assert validate.check_entry(entry) == [
        'animation.json: schema "simon.animation/9" is not a version Part 6 reads '
        "(it reads simon.animation/1, simon.animation.v1)"]


def test_entry_checks_each_file_with_its_kind(entry):
    (entry / "keyframes.json").write_bytes((entry / "animation.json").read_bytes())
    assert hits(validate.check_entry(entry),
                "holds simon.animation/1, which belongs in animation.json, not keyframes.json")


@pytest.mark.parametrize("set_name", ["exercise", "dance"])
def test_entry_reads_part_4_files_in_their_own_format(tmp_path, set_name):
    folder = tmp_path / "p4"
    shutil.copytree(CATALOG / f"part4-{'squat' if set_name == 'exercise' else 'step-touch'}",
                    folder)
    data = json.loads((folder / "manifest.json").read_text())
    data["id"] = "p4"
    (folder / "manifest.json").write_text(json.dumps(data))
    assert validate.check_entry(folder) == []


def test_part_4_files_fail_the_strict_checks_of_part_6_own_shapes():
    base = ROOT / "fixtures" / "part4" / "exercise"
    assert validate.check_animation(json.loads((base / "animation.json").read_text())) != []
    assert validate.check_skeleton(json.loads((base / "skeleton.json").read_text())) != []


def test_entry_with_a_null_kind_skips_that_file(entry):
    data = json.loads((entry / "manifest.json").read_text())
    data.update(keyframes=None, animation=None)
    (entry / "manifest.json").write_text(json.dumps(data))
    (entry / "keyframes.json").unlink()
    (entry / "animation.json").unlink()
    assert validate.check_entry(entry) == []


def test_entry_video_must_exist_when_named(entry):
    data = json.loads((entry / "manifest.json").read_text())
    data["video_uri"] = "video.webm"
    (entry / "manifest.json").write_text(json.dumps(data))
    assert validate.check_entry(entry) == ["video.webm: file is missing"]
    (entry / "video.webm").write_bytes(b"\x1a\x45\xdf\xa3")
    assert validate.check_entry(entry) == []


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
