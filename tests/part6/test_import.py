"""part6/importer.py: dropped files and processor output become catalog entries (AC-C02, AC-C06,
AC-C07 importer side, AC-C09 storage side, AC-F12)."""
import hashlib
import json
import re
import time
from pathlib import Path

import pytest
from conftest import short_id

from part6 import catalog, formats, importer, motion, processor, validate

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "fixtures" / "conformance" / "formats"
PART4 = ROOT / "fixtures" / "part4"
WEBM = b"\x1a\x45\xdf\xa3" + b"\x9f\x42\x86\x81\x01" * 4
MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 16
NAMES = ("keyframes.json", "skeleton.json", "animation.json")


@pytest.fixture
def root(tmp_path):
    return tmp_path / "cat"


def part4_items(set_name="exercise"):
    return [{"name": n, "data": (PART4 / set_name / n).read_bytes()} for n in NAMES]


def own_files(duration_ms=2000):
    return processor.generate("squat", duration_ms, motion.MotionParams(2.0, 1))


def own_items(duration_ms=2000):
    made = own_files(duration_ms)
    return [{"name": f"{k}.json", "data": json.dumps(made[k]).encode()} for k in made]


def golden(name):
    return (GOLDEN / name).read_bytes()


def item(name, data):
    return {"name": name, "data": data if isinstance(data, bytes) else json.dumps(data).encode()}


def do_import(root, items, **kw):
    kw.setdefault("name", "Moves")
    kw.setdefault("category", "dance")
    return importer.import_files(root, kw.pop("name"), kw.pop("category"), items, **kw)


def nothing_written(root):
    return not root.exists() or list(root.iterdir()) == []


def problem(root, items, **kw):
    """The ImportProblem message of an import that must fail; checks nothing was written."""
    with pytest.raises(importer.ImportProblem) as caught:
        do_import(root, items, **kw)
    assert nothing_written(root), [p.name for p in root.iterdir()]
    return str(caught.value)


def folder_of(root, manifest):
    return root / manifest["id"]


def v1_animation(frames, step=1 / 30):
    """A minimal valid simon.animation.v1 file with `frames` frames."""
    joints = {n: [0.1 * i, 0.2, 0.0] for i, n in enumerate(motion.JOINTS)}
    return {"format": "simon.animation.v1", "fps": 30,
            "frames": [{"index": i, "t": round(i * step, 6), "interpolated": False,
                        "joints": joints} for i in range(frames)]}


# a whole import

def test_part_4_files_become_an_import_entry(root):
    items = part4_items()
    manifest = do_import(root, items, name="  Part 4  squat ", category="exercise")
    folder = folder_of(root, manifest)
    assert re.fullmatch(r"part-4-squat-[0-9a-f]{8}", manifest["id"])
    assert manifest["name"] == "Part 4 squat" and manifest["category"] == "exercise"
    assert manifest["files_source"] == "import" and manifest["visitor"] is False
    assert manifest["video_uri"] is None and manifest["schema_version"] == 1
    assert manifest["duration_ms"] == 3000
    assert (manifest["keyframes"], manifest["skeleton"], manifest["animation"]) == NAMES
    assert manifest["thumbnail"] == "thumbnail.svg"
    assert json.loads((folder / "manifest.json").read_text()) == manifest
    assert validate.check_entry(folder) == [] and validate.check_manifest(manifest, manifest["id"]) == []
    assert sorted(p.name for p in folder.iterdir()) == sorted(NAMES + ("manifest.json", "thumbnail.svg"))


def test_the_original_json_bytes_are_stored_as_given(root):
    items = part4_items()
    manifest = do_import(root, items)
    for one in items:
        assert (folder_of(root, manifest) / one["name"]).read_bytes() == one["data"]


def test_the_thumbnail_is_drawn_from_what_plays(root):
    manifest = do_import(root, part4_items())
    svg = (folder_of(root, manifest) / "thumbnail.svg").read_text()
    assert svg.count("<line") == 16 and svg.count("<circle") == 17


def test_the_default_description_says_when_and_which_files(root, monkeypatch):
    from datetime import datetime, timezone
    monkeypatch.setattr(catalog, "utc_now", lambda: datetime(2026, 10, 28, 9, 30, tzinfo=timezone.utc))
    manifest = do_import(root, part4_items())
    assert manifest["description"] == "Imported on 2026-10-28. Files: key frames, skeleton, animation."
    assert manifest["created_at"] == "2026-10-28T09:30:00Z"
    other = do_import(root, [part4_items()[1]])
    assert other["description"] == "Imported on 2026-10-28. Files: skeleton."


def test_description_source_and_part_are_used(root):
    manifest = do_import(root, part4_items(), description="  My   own text ", source="  a  b ",
                         part=2)
    assert manifest["description"] == "My own text"
    for kind in formats.KINDS:
        record = manifest["provenance"][kind]
        assert record["source"] == "a b" and record["part"] == 2
    assert "source" not in do_import(root, part4_items())["provenance"]["animation"]


def test_provenance_records_format_hash_size_and_the_dropped_name(root):
    items = part4_items()
    items[2]["name"] = "my take/final animation.json"
    manifest = do_import(root, items)
    animation = manifest["provenance"]["animation"]
    raw = items[2]["data"]
    assert animation == {"part": 4, "format": "simon.animation.v1", "detected_by": "version",
                         "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw),
                         "original_name": "final animation.json"}
    assert manifest["provenance"]["keyframes"]["original_name"] == "keyframes.json"
    assert list(manifest["provenance"]) == ["keyframes", "skeleton", "animation"]


def test_the_part_defaults_to_the_formats_usual_producer(root):
    items = [item("keyframes.json", golden("keyframes-part1.json")),
             item("skeleton.json", golden("skeleton-1-part3.json")),
             item("animation.json", golden("animation-1-part6.json"))]
    manifest = do_import(root, items)
    assert {k: v["part"] for k, v in manifest["provenance"].items()} == {
        "keyframes": 1, "skeleton": 3, "animation": 6}
    assert {k: v["detected_by"] for k, v in manifest["provenance"].items()} == {
        "keyframes": "shape", "skeleton": "version", "animation": "version"}


def test_a_visitor_import_says_so(root):
    assert do_import(root, part4_items(), visitor=True)["visitor"] is True
    assert do_import(root, part4_items())["visitor"] is False


def test_created_at_can_be_given(root):
    assert do_import(root, part4_items(), created_at="2000-01-02T03:04:05Z")["created_at"] == (
        "2000-01-02T03:04:05Z")


# kinds

def test_a_version_field_decides_the_kind_whatever_the_file_is_called(root):
    items = [item("one.json", part4_items()[0]["data"]), item("two.json", part4_items()[1]["data"]),
             item("three.json", part4_items()[2]["data"])]
    manifest = do_import(root, items)
    assert (manifest["keyframes"], manifest["skeleton"], manifest["animation"]) == NAMES


def test_the_file_name_decides_when_there_is_no_version_field(root):
    data = json.loads(golden("keyframes-part1.json"))
    manifest = do_import(root, [item("my-KeyFrames-v2.json", data)] + own_items()[1:])
    assert manifest["keyframes"] == "keyframes.json"
    assert manifest["provenance"]["keyframes"]["original_name"] == "my-KeyFrames-v2.json"


def test_the_shape_decides_when_name_and_version_say_nothing(root):
    manifest = do_import(root, [item("a.json", golden("keyframes-part1.json")),
                                item("b.json", golden("animation-shape-joints.json"))])
    assert manifest["keyframes"] and manifest["animation"] and manifest["skeleton"] is None
    assert manifest["provenance"]["animation"]["format"] == "simon.animation.v1"
    assert manifest["provenance"]["animation"]["detected_by"] == "shape"


def test_kinds_are_found_by_formats_detect_kind(root, monkeypatch):
    seen = []
    real = formats.detect_kind
    monkeypatch.setattr(importer.formats, "detect_kind",
                        lambda data, name: seen.append(name) or real(data, name))
    do_import(root, part4_items())
    assert seen == list(NAMES)


def test_a_skeleton_only_entry_plays_the_skeleton(root):
    manifest = do_import(root, [item("skeleton.json", golden("skeleton-1-part3.json"))])
    assert manifest["animation"] is None and manifest["keyframes"] is None
    assert manifest["skeleton"] == "skeleton.json"
    played = formats.playable(None, formats.read_skeleton(json.loads(golden("skeleton-1-part3.json"))))
    assert manifest["duration_ms"] == importer.duration_ms_of(played) == round(
        played["frames"][-1]["t"] * 1000) > 0
    folder = folder_of(root, manifest)
    assert sorted(p.name for p in folder.iterdir()) == ["manifest.json", "skeleton.json",
                                                        "thumbnail.svg"]
    assert validate.check_entry(folder) == []
    assert "<line" in (folder / "thumbnail.svg").read_text()


def test_a_keys_only_part_4_skeleton_plays(root):
    manifest = do_import(root, [item("skeleton.json", golden("skeleton-v1-keys-part4.json"))])
    assert manifest["provenance"]["skeleton"]["format"] == "simon.skeleton.v1"
    assert manifest["duration_ms"] > 0


def test_part_1_keyframes_on_a_60_fps_clock_with_a_part_3_skeleton_and_no_animation(root):
    manifest = do_import(root, [item("keyframes.json", golden("keyframes-part1-60fps.json")),
                                item("skeleton.json", golden("skeleton-1-part3.json"))])
    assert manifest["animation"] is None
    assert manifest["provenance"]["keyframes"]["part"] == 1
    assert manifest["provenance"]["skeleton"]["part"] == 3


def test_the_animation_beats_the_skeleton_for_duration_and_thumbnail(root):
    manifest = do_import(root, part4_items())
    assert manifest["duration_ms"] == 3000      # the animation, not the 1 s golden skeleton
    other = do_import(root, [part4_items()[2], item("s.json", golden("skeleton-1-part3.json"))])
    assert other["duration_ms"] == 3000


# duration

@pytest.mark.parametrize("last_t,expected", [(0.0, 1), (0.0004, 1), (0.0025, 3), (0.0015, 2),
                                             (1.2345, 1235), (3.0, 3000)])
def test_duration_is_floor_of_milliseconds_plus_half_and_at_least_one(root, last_t, expected):
    animation = v1_animation(2)
    animation["frames"][1]["t"] = last_t
    if last_t == 0.0:
        animation["frames"] = animation["frames"][:1]
    assert do_import(root, [item("animation.json", animation)])["duration_ms"] == expected


def test_a_one_frame_animation_is_one_millisecond_long(root):
    manifest = do_import(root, [item("animation.json", golden("animation-1-single.json"))])
    assert manifest["duration_ms"] == 1


# folder layout and fixed names

HOSTILE = ["../../outside.json", "/etc/passwd", "..\\..\\win.json", ".hidden", "a/b/c.json",
           "x\x00y.json", "con‮text.json", "n" * 500 + ".json", "manifest.json",
           "thumbnail.svg"]


@pytest.mark.parametrize("dropped", HOSTILE)
def test_a_dropped_name_never_builds_a_path(root, tmp_path, dropped):
    data = part4_items()[2]["data"]
    manifest = do_import(root, [item(dropped, data)])
    folder = folder_of(root, manifest)
    assert sorted(p.name for p in folder.iterdir()) == ["animation.json", "manifest.json",
                                                        "thumbnail.svg"]
    assert (folder / "animation.json").read_bytes() == data
    assert [p.name for p in root.iterdir()] == [manifest["id"]]
    assert not (tmp_path / "outside.json").exists()
    original = manifest["provenance"]["animation"].get("original_name", "")
    assert len(original) <= importer.LABEL_MAX and "/" not in original
    assert "\x00" not in original and "\\" not in original


def test_a_hostile_name_is_not_an_id(root):
    manifest = do_import(root, part4_items(), name="../../x")
    assert catalog.is_valid_id(manifest["id"]) and manifest["id"].startswith("x-")


def test_file_label_keeps_the_last_part_without_control_characters():
    assert importer.file_label("a/b\\c.json") == "c.json"
    assert importer.file_label("\x00\x07 x.json ") == "x.json"
    assert importer.file_label("") == "file" and importer.file_label("///") == "file"
    assert importer.file_label(5) == "file"
    assert len(importer.file_label("z" * 999)) == importer.LABEL_MAX


def test_the_root_is_created_when_missing(tmp_path):
    root = tmp_path / "deep" / "er" / "cat"
    manifest = do_import(root, part4_items())
    assert (root / manifest["id"] / "manifest.json").is_file()


def test_no_temp_folder_is_left_behind(root):
    manifest = do_import(root, part4_items())
    assert [p.name for p in root.iterdir()] == [manifest["id"]]


# ids

def test_an_id_can_be_chosen(root):
    manifest = do_import(root, part4_items(), entry_id="my-id-7")
    assert manifest["id"] == "my-id-7" and (root / "my-id-7" / "manifest.json").is_file()


@pytest.mark.parametrize("bad", ["", "A", "-a", "a b", "a/b", "../x", ".x", "x" * 64, "café",
                                 "a\n", 5, "squat\x00"])
def test_a_bad_id_is_refused_before_anything_is_read(root, bad):
    message = problem(root, part4_items(), entry_id=bad)
    assert message.startswith("id: ")


def test_a_taken_id_is_refused_and_the_old_entry_stays(root):
    do_import(root, part4_items(), entry_id="taken")
    before = (root / "taken" / "manifest.json").read_bytes()
    with pytest.raises(importer.ImportProblem, match="id: taken is already in the catalog"):
        do_import(root, part4_items(), entry_id="taken", name="Other")
    assert (root / "taken" / "manifest.json").read_bytes() == before
    assert [p.name for p in root.iterdir()] == ["taken"]


def test_a_generated_id_is_retried_when_it_is_taken(root, monkeypatch):
    ids = iter(["same-00000001", "same-00000001", "next-00000002"])
    monkeypatch.setattr(catalog, "new_id", lambda name: next(ids))
    first = do_import(root, part4_items())
    second = do_import(root, part4_items())
    assert (first["id"], second["id"]) == ("same-00000001", "next-00000002")


def test_a_generated_id_gives_up_after_repeated_collisions(root, monkeypatch):
    do_import(root, part4_items(), entry_id="taken-00000001")
    monkeypatch.setattr(catalog, "new_id", lambda name: "taken-00000001")
    with pytest.raises(RuntimeError):
        do_import(root, part4_items())


def test_a_write_that_finds_the_folder_taken_is_retried(root, monkeypatch):
    real = catalog.write_shared_entry
    calls = []

    def racing(root_, entry_id, manifest, files):
        calls.append(entry_id)
        if len(calls) == 1:
            raise FileExistsError(entry_id)
        return real(root_, entry_id, manifest, files)

    monkeypatch.setattr(catalog, "write_shared_entry", racing)
    manifest = do_import(root, part4_items())
    assert len(calls) == 2 and calls[0] != calls[1] and manifest["id"] == calls[1]


# the 400 reasons

@pytest.mark.parametrize("name", ["", "   ", "x" * 81, "a\x00b", "a\nb", None, 5, ["a"]])
def test_name(root, name):
    assert problem(root, part4_items(), name=name) == "name"


@pytest.mark.parametrize("category", ["", "yoga", "Dance", None, 5, ["dance"]])
def test_category(root, category):
    assert problem(root, part4_items(), category=category) == "category"


def test_name_is_checked_before_category_and_files(root):
    assert problem(root, [], name="", category="yoga") == "name"
    assert problem(root, [], category="yoga") == "category"


@pytest.mark.parametrize("files", [[], None, "x", {"name": "a.json", "data": b"{}"}, 5])
def test_files_must_be_a_non_empty_list(root, files):
    assert problem(root, files) == "files"


@pytest.mark.parametrize("bad", [None, "x", 5, {}, {"name": "a.json"}, {"data": b"{}"},
                                 {"name": 5, "data": b"{}"}, {"name": "a.json", "data": "{}"},
                                 {"name": "a.json", "data": None}])
def test_every_file_needs_a_name_and_bytes(root, bad):
    assert problem(root, [part4_items()[2], bad]) == "files"


def test_a_tuple_of_items_is_a_list_too(root):
    assert do_import(root, tuple(part4_items()))["files_source"] == "import"


def test_bytearray_data_is_accepted(root):
    manifest = do_import(root, [{"name": "animation.json", "data": bytearray(part4_items()[2]["data"])}])
    assert manifest["animation"] == "animation.json"


def test_too_many_files(root):
    items = part4_items() + [item("video.mp4", MP4), item("more.json", golden("keyframes-part1.json"))]
    assert len(items) == importer.MAX_FILES + 1 and importer.MAX_FILES == 4
    assert problem(root, items) == "too many files"


def test_four_files_are_fine_and_a_video_is_one_of_them(root):
    manifest = do_import(root, part4_items() + [item("clip.mp4", MP4)])
    assert manifest["video_uri"] == "video.mp4" and manifest["duration_ms"] == 3000


@pytest.mark.parametrize("kind,second", [
    ("skeleton", ("s2.json", "skeleton-1-part3.json")),
    ("keyframes", ("k2.json", "keyframes-part1.json")),
    ("animation", ("a2.json", "animation-1-part6.json"))])
def test_two_files_of_one_kind(root, kind, second):
    items = part4_items() + [item(second[0], golden(second[1]))]
    assert problem(root, items[:3] + items[3:]) == f"two {kind} files"


def test_two_videos(root):
    assert problem(root, [part4_items()[2], item("a.mp4", MP4), item("b.webm", WEBM)]) == (
        "two video files")


def test_two_of_a_kind_is_said_before_the_second_file_is_read(root):
    broken = item("skeleton2.json", {"schema": "simon.skeleton/1", "frames": []})
    assert problem(root, [part4_items()[1], broken]) == "two skeleton files"


@pytest.mark.parametrize("data", [b"", b"not json", b"{", b"\xff\xfe\x00", b"\xef\xbb\xbf",
                                  b'{"a": NaN, ', b"[" * 100000, b"{'a': 1}"])
def test_not_valid_json(root, data):
    assert problem(root, [item("animation.json", data)]) == "animation.json: is not valid JSON"


def with_ignored_field(name, value):
    """A golden file whose top level gains a field no reader looks at, written as raw JSON text."""
    text = golden(name).decode().rstrip()
    assert text.endswith("}")
    return (text[:-1] + f', "ignored": {value}}}').encode()


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity", "[1, NaN]", "1e400", "-1e400",
                                      "[1, 1e999]", "1" + "0" * 5000, "-1" + "0" * 400], ids=short_id)
def test_a_json_constant_a_browser_cannot_parse_is_refused_even_in_an_ignored_field(root, constant):
    items = [item("animation.json", with_ignored_field("animation-v1-part4.json", constant))]
    assert problem(root, items) == "animation.json: is not valid JSON"


@pytest.mark.parametrize("value", ["[1, 2]", "1e308", "-1.7976931348623157e308", "1" + "0" * 300,
                                   "1e-400"])
def test_the_same_file_without_the_constant_imports(root, value):
    items = [item("animation.json", with_ignored_field("animation-v1-part4.json", value))]
    assert do_import(root, items)["animation"] == "animation.json"


@pytest.mark.parametrize("kind,golden_name", [("animation", "animation-v1-part4.json"),
                                              ("skeleton", "skeleton-1-part3.json"),
                                              ("keyframes", "keyframes-part1-60fps.json")])
def test_a_file_with_a_utf_8_byte_order_mark_imports_and_is_stored_as_given(root, kind, golden_name):
    data = b"\xef\xbb\xbf" + golden(golden_name)
    items = [item(f"{kind}.json", data)]
    if kind == "keyframes":
        items.append(item("skeleton.json", golden("skeleton-1-part3.json")))    # key frames alone cannot play
    manifest = do_import(root, items)
    assert (folder_of(root, manifest) / manifest[kind]).read_bytes() == data
    assert manifest["provenance"][kind]["sha256"] == hashlib.sha256(data).hexdigest()
    assert validate.check_entry(folder_of(root, manifest)) == []


def test_a_byte_order_mark_does_not_hide_a_constant_after_it(root):
    data = b"\xef\xbb\xbf" + with_ignored_field("animation-v1-part4.json", "NaN")
    assert problem(root, [item("animation.json", data)]) == "animation.json: is not valid JSON"


def test_not_valid_json_names_the_file_as_dropped_without_its_path(root):
    assert problem(root, [item("some/where/take.json", b"nope")]) == "take.json: is not valid JSON"


@pytest.mark.parametrize("data,expected", [
    (b"[]", "x.json: is not a JSON object"), (b"5", "x.json: is not a JSON object"),
    (b"null", "x.json: is not a JSON object"), (b'"s"', "x.json: is not a JSON object"),
    (b"{}", "x.json: has no format or schema field and its shape matches no reader")])
def test_a_file_whose_kind_cannot_be_found(root, data, expected):
    assert problem(root, [item("x.json", data)]) == expected


def test_a_reader_rejects_the_file_with_its_e_message(root):
    broken = json.loads(golden("animation-v1-part4.json"))
    del broken["frames"][2]["joints"]["left_knee"]
    assert problem(root, [item("take.json", broken)]) == (
        "take.json: frames[2].joints.left_knee: missing")


def test_an_unknown_version_names_the_file_and_the_versions_read(root):
    data = json.loads(golden("animation-v1-part4.json"))
    data["format"] = "simon.animation.v9"
    assert problem(root, [item("animation.json", data)]) == (
        "animation.json: format \"simon.animation.v9\" is not a version Part 6 reads "
        "(it reads simon.animation/1, simon.animation.v1)")


@pytest.mark.parametrize("name", sorted(p.name for p in GOLDEN.glob("invalid-*.json")))
def test_every_invalid_golden_is_refused_with_nothing_written(root, name):
    with pytest.raises(importer.ImportProblem):
        do_import(root, [item(name, golden(name))])
    assert nothing_written(root)


@pytest.mark.parametrize("name", ["invalid-json-number-overflow.json", "invalid-json-bad-utf8.json"])
def test_the_parse_level_goldens_are_refused_as_not_valid_json(root, name):
    assert problem(root, [item(name, golden(name))]) == f"{name}: is not valid JSON"


def test_one_bad_file_among_good_ones_writes_nothing(root):
    items = part4_items()
    items[1]["data"] = b"{"
    assert problem(root, items) == "skeleton.json: is not valid JSON"


def test_nothing_to_play_e12(root):
    e12 = "nothing to play: add an animation.json or a skeleton.json"
    assert problem(root, [part4_items()[0]]) == e12
    assert problem(root, [item("clip.webm", WEBM)]) == e12
    assert problem(root, [part4_items()[0], item("clip.mp4", MP4)]) == e12


# the caps

def test_the_caps_are_the_locked_ones():
    assert importer.MAX_FILES == 4
    assert importer.MAX_JSON_BYTES == 8 * 1024 * 1024
    assert importer.MAX_VIDEO_BYTES == 16 * 1024 * 1024


def test_a_json_file_over_the_cap(root, monkeypatch):
    items = part4_items()
    monkeypatch.setattr(importer, "MAX_JSON_BYTES", len(items[2]["data"]) - 1)
    assert problem(root, items) == "animation.json: file too large"
    monkeypatch.setattr(importer, "MAX_JSON_BYTES", len(items[2]["data"]))
    assert do_import(root, items)["animation"] == "animation.json"


def test_the_json_cap_is_checked_before_the_file_is_parsed(root, monkeypatch):
    monkeypatch.setattr(importer, "MAX_JSON_BYTES", 10)
    monkeypatch.setattr(importer, "_parse", lambda *a: pytest.fail("parsed an oversize file"))
    assert problem(root, [item("a.json", b"x" * 11)]) == "a.json: file too large"


def test_a_video_over_the_cap(root, monkeypatch):
    monkeypatch.setattr(importer, "MAX_VIDEO_BYTES", len(MP4) - 1)
    assert problem(root, [part4_items()[2], item("clip.mp4", MP4)]) == "clip.mp4: file too large"
    monkeypatch.setattr(importer, "MAX_VIDEO_BYTES", len(MP4))
    assert do_import(root, [part4_items()[2], item("clip.mp4", MP4)])["video_uri"] == "video.mp4"


def test_a_json_file_may_not_use_the_larger_video_cap(root, monkeypatch):
    monkeypatch.setattr(importer, "MAX_JSON_BYTES", 100)
    monkeypatch.setattr(importer, "MAX_VIDEO_BYTES", 10_000)
    assert problem(root, [item("a.json", b"x" * 200)]) == "a.json: file too large"


def test_a_large_import_validates_quickly(root):
    animation = v1_animation(1)
    frame = animation["frames"][0]
    animation["frames"] = [dict(frame, index=i, t=round(i / 30, 6)) for i in range(10000)]
    data = json.dumps(animation).encode()
    assert 6 * 1024 * 1024 < len(data) < importer.MAX_JSON_BYTES
    began = time.monotonic()
    manifest = do_import(root, [item("animation.json", data)])
    assert time.monotonic() - began < 2.0     # the spec's limit; about 0.3 s on this host
    assert manifest["duration_ms"] == round(9999 / 30 * 1000)


# video

def test_a_webm_is_stored_as_video_webm(root):
    manifest = do_import(root, part4_items() + [item("my take.webm", WEBM)])
    folder = folder_of(root, manifest)
    assert manifest["video_uri"] == "video.webm" and (folder / "video.webm").read_bytes() == WEBM
    assert validate.check_entry(folder) == []
    assert manifest["provenance"]["video"] == {
        "part": 6, "format": None, "detected_by": "file", "sha256": hashlib.sha256(WEBM).hexdigest(),
        "bytes": len(WEBM), "original_name": "my take.webm"}


def test_an_mp4_is_stored_as_video_mp4(root):
    manifest = do_import(root, [part4_items()[2], item("clip.MP4", MP4)])
    folder = folder_of(root, manifest)
    assert manifest["video_uri"] == "video.mp4" and (folder / "video.mp4").read_bytes() == MP4
    assert sorted(p.name for p in folder.iterdir()) == [
        "animation.json", "manifest.json", "thumbnail.svg", "video.mp4"]


def test_the_video_type_comes_from_its_bytes_not_its_name(root):
    manifest = do_import(root, [part4_items()[2], item("really-webm.mp4", WEBM)])
    assert manifest["video_uri"] == "video.webm"
    assert manifest["provenance"]["video"]["original_name"] == "really-webm.mp4"
    manifest = do_import(root, [part4_items()[2], item("noextension", MP4)])
    assert manifest["video_uri"] == "video.mp4"


def test_a_video_takes_part_and_source_like_the_other_files(root):
    manifest = do_import(root, [part4_items()[2], item("c.mp4", MP4)], part=1, source="phone")
    assert manifest["provenance"]["video"]["part"] == 1
    assert manifest["provenance"]["video"]["source"] == "phone"


@pytest.mark.parametrize("name,data", [
    ("clip.mov", b"\x00\x00\x00\x14moov    " + b"\x00" * 8),
    ("clip.mp4", b"\x00\x00\x00\x18moovmp42" + b"\x00" * 16),   # ftyp is not at byte 4
    ("clip.mp4", b"ftyp" + b"\x00" * 16),                        # ftyp at byte 0
    ("clip.webm", b"\x1a\x45\xdf" + b"\x00" * 16),               # short magic
    ("clip.webm", b"RIFF\x00\x00\x00\x00AVI "),
    ("clip.mkv", b"not a video"), ("clip.avi", b""), ("x.M4V", b"{}"),
    ("clip.ogv", b"OggS" + b"\x00" * 8), ("clip.3gp", b"abc")])
def test_a_video_of_another_type(root, name, data):
    assert problem(root, [part4_items()[2], item(name, data)]) == (
        f"{name}: not a WebM or MP4 video")


def test_json_in_a_file_called_json_is_not_mistaken_for_a_video(root):
    assert do_import(root, part4_items())["video_uri"] is None


def test_magic_bytes_make_a_video_whatever_the_name(root):
    manifest = do_import(root, [part4_items()[2], item("take.json", MP4)])
    assert manifest["video_uri"] == "video.mp4"


# the request fields

@pytest.mark.parametrize("field,value", [
    ("description", 5), ("description", "x" * 1001), ("description", "a\x00b"),
    ("description", ["x"]), ("source", 5), ("source", "x" * 201), ("source", "a\x07b"),
    ("part", 0), ("part", 8), ("part", True), ("part", "4"), ("part", 4.0), ("part", -1)])
def test_a_bad_optional_field(root, field, value):
    assert problem(root, part4_items(), **{field: value}) == field


def test_optional_fields_that_are_blank_count_as_not_given(root):
    manifest = do_import(root, part4_items(), description="   ", source="")
    assert manifest["description"].startswith("Imported on ")
    assert "source" not in manifest["provenance"]["animation"]


def test_every_part_from_one_to_seven_is_accepted(root):
    for part in range(1, 8):
        assert do_import(root, part4_items(), part=part)["provenance"]["animation"]["part"] == part


# roots

def test_the_fixture_catalog_is_not_a_root_for_imports():
    shipped = catalog.FIXTURE_CATALOG
    before = sorted(p.name for p in shipped.iterdir())
    with pytest.raises(catalog.RootError):
        do_import(shipped, part4_items())
    with pytest.raises(catalog.RootError):
        do_import(shipped / "squat", part4_items())
    assert sorted(p.name for p in shipped.iterdir()) == before


# atomic writes

def test_a_failed_write_leaves_no_entry_and_no_temp_folder(root, monkeypatch):
    real = Path.write_bytes
    calls = []

    def flaky(self, data):
        calls.append(self.name)
        if len(calls) == 3:
            raise OSError("disk full")
        return real(self, data)

    monkeypatch.setattr(Path, "write_bytes", flaky)
    with pytest.raises(OSError):
        do_import(root, part4_items())
    assert list(root.iterdir()) == []


def test_the_entry_appears_only_at_the_final_rename(root, monkeypatch):
    seen = []
    real = catalog.os.rename

    def spy(src, dst):
        seen.append(sorted(p.name for p in root.iterdir()))
        real(src, dst)

    monkeypatch.setattr(catalog.os, "rename", spy)
    manifest = do_import(root, part4_items(), entry_id="atomic")
    assert seen == [[".tmp-atomic"]] and [m["id"] for m in catalog.list_entries(root)] == [
        manifest["id"]]


def test_an_imported_entry_is_listed_with_the_import_source(root):
    do_import(root, part4_items())
    assert [m["files_source"] for m in catalog.list_entries(root, source="import")] == ["import"]
    assert catalog.list_entries(root, source="mock") == []


# add_entry and read_shared

def test_read_shared_reads_bytes_and_parsed_objects(root):
    data = part4_items()[2]["data"]
    from_bytes = importer.read_shared("animation", data=data)
    assert from_bytes.data == data and from_bytes.normalized["format"] == "simon.animation.v1"
    parsed = json.loads(data)
    from_parsed = importer.read_shared("animation", parsed=parsed)
    assert from_parsed.data == catalog.compact_json(parsed).encode()
    assert from_parsed.normalized == from_bytes.normalized


def test_read_shared_names_the_file_it_was_given():
    with pytest.raises(importer.ImportProblem, match=r"^my\.json: is not a JSON object$"):
        importer.read_shared("animation", data=b"[]", file="my.json")
    with pytest.raises(importer.ImportProblem, match=r"^animation\.json: is not valid JSON$"):
        importer.read_shared("animation", data=b"{")


def test_add_entry_needs_something_that_plays(root):
    shared = {"keyframes": importer.read_shared("keyframes", data=golden("keyframes-part1.json"))}
    with pytest.raises(importer.ImportProblem, match="nothing to play"):
        importer.add_entry(root, entry_id="empty", name="Empty", category="dance",
                           files_source="fixture", description="d",
                           created_at="2026-10-28T00:00:00Z", shared=shared)
    assert nothing_written(root)


def test_add_entry_takes_the_duration_it_is_given(root):
    shared = {"animation": importer.read_shared("animation", data=part4_items()[2]["data"])}
    manifest = importer.add_entry(root, entry_id="given", name="Given", category="dance",
                                  files_source="fixture", description="d",
                                  created_at="2026-10-28T00:00:00Z", shared=shared,
                                  duration_ms=7000)
    assert manifest["duration_ms"] == 7000 and "visitor" not in manifest
    assert importer.duration_ms_of(formats.read_animation(json.loads(part4_items()[2]["data"]))) == 3000


# store_processed

def recording(entry_id="job-1", **fields):
    return {"id": entry_id, "name": "Job one", "category": "exercise", "duration_ms": 2000,
            "video_path": None, **fields}


def stored(root, files=None, rec=None, **kw):
    kw.setdefault("files_source", "processor")
    kw.setdefault("description", "From a processor.")
    return importer.store_processed(root, rec or recording(),
                                    own_files() if files is None else files, **kw)


def test_store_processed_writes_an_entry_under_the_recording_id(root):
    manifest = stored(root)
    folder = root / "job-1"
    assert manifest["id"] == "job-1" and manifest["name"] == "Job one"
    assert manifest["files_source"] == "processor" and manifest["visitor"] is True
    assert manifest["description"] == "From a processor." and manifest["duration_ms"] == 2000
    assert manifest["category"] == "exercise" and manifest["video_uri"] is None
    assert json.loads((folder / "manifest.json").read_text()) == manifest
    assert validate.check_entry(folder) == []
    assert sorted(p.name for p in folder.iterdir()) == sorted(NAMES + ("manifest.json", "thumbnail.svg"))


def test_store_processed_writes_compact_json_with_a_final_newline(root):
    files = own_files()
    stored(root, files)
    for kind in formats.KINDS:
        raw = (root / "job-1" / f"{kind}.json").read_bytes()
        assert raw == catalog.compact_json(files[kind]).encode() and raw.endswith(b"}\n")


def test_store_processed_provenance_names_the_usual_producer(root):
    manifest = stored(root, {"animation": json.loads(part4_items()[2]["data"]),
                             "skeleton": json.loads(golden("skeleton-1-part3.json"))})
    assert manifest["animation"] == "animation.json" and manifest["keyframes"] is None
    prov = manifest["provenance"]
    assert prov["animation"]["part"] == 4 and prov["animation"]["format"] == "simon.animation.v1"
    assert prov["skeleton"]["part"] == 3 and prov["skeleton"]["format"] == "simon.skeleton/1"
    for kind, record in prov.items():
        raw = (root / "job-1" / f"{kind}.json").read_bytes()
        assert record["sha256"] == hashlib.sha256(raw).hexdigest() and record["bytes"] == len(raw)
        assert "original_name" not in record and "source" not in record


@pytest.mark.parametrize("source", ["mock", "processor", "import", "fixture"])
def test_store_processed_takes_the_files_source_it_is_given(root, source):
    assert stored(root, files_source=source)["files_source"] == source


def test_store_processed_refuses_an_unknown_files_source(root):
    with pytest.raises(ValueError, match="files_source"):
        stored(root, files_source="pipeline")
    assert nothing_written(root)


def test_store_processed_visitor_flag(root):
    assert stored(root, rec=recording("a"))["visitor"] is True
    assert stored(root, rec=recording("b"), visitor=False)["visitor"] is False


def test_store_processed_created_at_can_be_given_and_defaults_to_now(root, monkeypatch):
    from datetime import datetime, timezone
    monkeypatch.setattr(catalog, "utc_now", lambda: datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc))
    assert stored(root, rec=recording("a"))["created_at"] == "2026-01-02T03:04:05Z"
    assert stored(root, rec=recording("b"), created_at="2000-01-01T00:00:00Z")["created_at"] == (
        "2000-01-01T00:00:00Z")


def test_store_processed_uses_the_recording_duration_else_the_animations(root):
    assert stored(root, rec=recording("a", duration_ms=9000))["duration_ms"] == 9000
    for index, bad in enumerate((None, 0, -5, "3000", 2.5, True)):
        manifest = stored(root, rec=recording(f"b{index}", duration_ms=bad))
        assert manifest["duration_ms"] == 1967, bad
    del_duration = recording("c")
    del del_duration["duration_ms"]
    assert stored(root, rec=del_duration)["duration_ms"] > 0


def test_store_processed_ignores_missing_none_and_unknown_keys(root):
    files = own_files()
    manifest = stored(root, {"animation": files["animation"], "keyframes": None,
                             "status": "done", "extra": {"x": 1}})
    assert manifest["keyframes"] is None and manifest["skeleton"] is None
    assert sorted(p.name for p in (root / "job-1").iterdir()) == [
        "animation.json", "manifest.json", "thumbnail.svg"]


def test_store_processed_with_a_skeleton_only(root):
    manifest = stored(root, {"skeleton": own_files()["skeleton"]})
    assert manifest["animation"] is None and validate.check_entry(root / "job-1") == []


def test_store_processed_nothing_to_play(root):
    e12 = "nothing to play: add an animation.json or a skeleton.json"
    for files in ({}, {"keyframes": own_files()["keyframes"]}, {"animation": None}):
        with pytest.raises(importer.ImportProblem) as caught:
            stored(root, files)
        assert str(caught.value) == e12
    assert nothing_written(root)


def test_store_processed_names_the_reader_message_for_a_rejected_file(root):
    files = own_files()
    del files["animation"]["frames"][3]["people"][0]["joints"]["nose"]
    with pytest.raises(importer.ImportProblem) as caught:
        stored(root, files)
    assert str(caught.value) == "animation.json: frames[3].people[0].joints.nose: missing"
    assert nothing_written(root)


@pytest.mark.parametrize("kind,bad,expected", [
    ("animation", [], "animation.json: is not a JSON object"),
    ("skeleton", {"format": "simon.skeleton.v9"},
     'skeleton.json: format "simon.skeleton.v9" is not a version Part 6 reads '
     "(it reads simon.skeleton/1, simon.skeleton.v1)"),
    ("keyframes", {"format": "simon.animation/1"},
     "keyframes.json: holds simon.animation/1, which belongs in animation.json, not keyframes.json")])
def test_store_processed_reader_messages(root, kind, bad, expected):
    files = own_files()
    files[kind] = bad
    with pytest.raises(importer.ImportProblem) as caught:
        stored(root, files)
    assert str(caught.value) == expected


def test_store_processed_refuses_a_value_json_cannot_hold(root):
    files = own_files()
    files["animation"]["note"] = float("nan")
    with pytest.raises(importer.ImportProblem, match="animation.json: is not valid JSON"):
        stored(root, files)
    assert nothing_written(root)


def test_store_processed_raises_file_exists_for_a_taken_id(root):
    stored(root)
    before = (root / "job-1" / "manifest.json").read_bytes()
    with pytest.raises(FileExistsError):
        stored(root, files_source="mock")
    assert (root / "job-1" / "manifest.json").read_bytes() == before
    assert [p.name for p in root.iterdir()] == ["job-1"]


@pytest.mark.parametrize("bad", [None, "", "A", "../x", "a/b", ".x", "x" * 64, 5])
def test_store_processed_checks_the_id_before_any_path_is_built(root, bad):
    with pytest.raises(importer.ImportProblem, match="^id: "):
        stored(root, rec=recording(bad))
    assert nothing_written(root)


def test_store_processed_checks_the_name_and_category(root):
    with pytest.raises(importer.ImportProblem) as caught:
        stored(root, rec=recording(name="  "))
    assert str(caught.value) == "name"
    with pytest.raises(importer.ImportProblem) as caught:
        stored(root, rec=recording(category="yoga"))
    assert str(caught.value) == "category"
    assert nothing_written(root)


def test_store_processed_refuses_the_fixture_catalog():
    with pytest.raises(catalog.RootError):
        stored(catalog.FIXTURE_CATALOG)


def test_store_processed_reads_the_files_through_the_readers(root, monkeypatch):
    seen = []
    real = formats.read
    monkeypatch.setattr(importer.formats, "read",
                        lambda kind, data, file=None: seen.append((kind, file)) or real(kind, data, file))
    stored(root)
    assert seen == [("keyframes", "keyframes.json"), ("skeleton", "skeleton.json"),
                    ("animation", "animation.json")]


def test_store_processed_accepts_what_the_mock_processor_returns(root):
    rec = recording("mock-1", name="Mock", category="dance")
    manifest = stored(root, processor.process(rec), rec=rec, files_source="mock")
    assert manifest["files_source"] == "mock" and validate.check_entry(root / "mock-1") == []


# prepare then commit: the slow work apart from the write (review R5)

def test_prepare_import_reads_everything_and_writes_nothing(root):
    prepared = importer.prepare_import("Moves", "dance", part4_items())
    assert nothing_written(root)
    assert prepared.manifest["id"] is None and "visitor" not in prepared.manifest
    assert set(prepared.files) == {*NAMES, "thumbnail.svg"}


def test_commit_import_writes_the_entry_with_a_fresh_id_and_the_visitor_flag(root):
    prepared = importer.prepare_import("Moves", "dance", part4_items())
    first = importer.commit_import(root, prepared, visitor=True)
    second = importer.commit_import(root, prepared)
    assert first["id"] != second["id"] and first["visitor"] is True and second["visitor"] is False
    assert {k: v for k, v in first.items() if k not in ("id", "visitor")} == {
        k: v for k, v in second.items() if k not in ("id", "visitor")}
    assert validate.check_catalog(root) == {}


def test_commit_import_honours_the_asked_for_id_once(root):
    prepared = importer.prepare_import("Moves", "dance", part4_items(), entry_id="mine")
    assert importer.commit_import(root, prepared, entry_id="mine")["id"] == "mine"
    with pytest.raises(importer.ImportProblem, match="id: mine is already in the catalog"):
        importer.commit_import(root, prepared, entry_id="mine")


@pytest.mark.parametrize("changes", [dict(name="  "), dict(category="yoga"), dict(entry_id="Bad Id"),
                                     dict(items=[item("animation.json", b"nope")]),
                                     dict(items=[])])
def test_prepare_import_refuses_what_import_files_refuses(root, changes):
    args = dict(name="Moves", category="dance", items=part4_items(), entry_id=None)
    args.update(changes)
    with pytest.raises(importer.ImportProblem) as direct:
        importer.prepare_import(args["name"], args["category"], args["items"],
                                entry_id=args["entry_id"])
    with pytest.raises(importer.ImportProblem) as whole:
        importer.import_files(root, args["name"], args["category"], args["items"],
                              entry_id=args["entry_id"])
    assert str(direct.value) == str(whole.value) and nothing_written(root)


def test_commit_import_refuses_the_fixture_catalog():
    prepared = importer.prepare_import("Moves", "dance", part4_items())
    with pytest.raises(catalog.RootError):
        importer.commit_import(catalog.FIXTURE_CATALOG, prepared)
