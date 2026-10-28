"""Format adapters (docs/specs/formats.md): the golden suite plus the rules the suite cannot show.

Every case of fixtures/conformance/formats/cases.json runs against part6/formats.py here and
against web/formats.js in check/formats-golden.mjs. Both runners read a golden file the way the
product reads a JSON file (here through part6.validate.parse_json), so a file the strict parse
refuses gives "<file>: is not valid JSON" with no reader involved. The direct tests below pin
detection order, the held-pose rule, the frame rounding rule, purity and the read time.
"""
import ast
import json
import math
import time
from copy import deepcopy
from pathlib import Path

import pytest

from part6 import formats, validate

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "fixtures" / "conformance" / "formats"
CASES = json.loads((GOLDEN / "cases.json").read_text(encoding="utf-8"))
ERROR_IDS = {"E1", "E2", "E3", "E4", "E5", "E6", "E7", "E8", "E9", "E9s", "E10", "E11", "E12",
             "E13", "E14", "E15", "E16"}
TOL = 1e-6
OVERFLOW = "invalid-json-number-overflow.json"
BAD_UTF8 = "invalid-json-bad-utf8.json"
PARSE_LEVEL = sorted([OVERFLOW, BAD_UTF8])  # the only cases the strict parse refuses (no error id)


class Refused(Exception):
    """A golden file the product's strict parse refuses; the message is the product's sentence."""


def load(name, shown=None):
    """A golden file parsed as the importer, doctor and server parse it (docs/specs/formats.md
    "Error Cases"). Raises Refused("<shown>: is not valid JSON") when the strict parse refuses it."""
    try:
        return validate.parse_json((GOLDEN / name).read_bytes())
    except validate.NotJson as err:
        raise Refused(f"{shown or name}: {err}") from None


def same(a, b, path="value"):
    """None when a equals b (numbers within 1e-6), else a sentence naming the first difference."""
    if isinstance(a, bool) or isinstance(b, bool):
        return None if a is b else f"{path}: {a!r} is not {b!r}"
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return None if abs(a - b) <= TOL else f"{path}: {a!r} is not {b!r}"
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return f"{path}: length {len(a)} is not {len(b)}"
        for i, (x, y) in enumerate(zip(a, b)):
            diff = same(x, y, f"{path}[{i}]")
            if diff:
                return diff
        return None
    if isinstance(a, dict) and isinstance(b, dict):
        if set(a) != set(b):
            return f"{path}: keys {sorted(a)} are not {sorted(b)}"
        for key in a:
            diff = same(a[key], b[key], f"{path}.{key}")
            if diff:
                return diff
        return None
    return None if a == b else f"{path}: {a!r} is not {b!r}"


def outcome(case):
    """What the product says about a case: ({"error": ...} or a result, error code or None). A
    refused parse has no error code, because no reader ran."""
    kind, name = case["kind"], case.get("name") or case["file"]
    try:
        if kind == "detect":
            return {"kind": formats.detect_kind(load(case["file"], name), name)}, None
        if kind == "playable":
            a = case.get("animation")
            s = case.get("skeleton")
            anim = formats.read_animation(load(a), a) if a else None
            skel = formats.read_skeleton(load(s), s) if s else None
            return formats.summary(formats.playable(anim, skel)), None
        return formats.summary(formats.read(kind, load(case["file"], name), name)), None
    except Refused as err:
        return {"error": str(err)}, None
    except formats.FormatError as err:
        return {"error": str(err)}, err.code


def label(case):
    return f"{case['kind']}:{case['file']}:{case.get('name', '')}"


@pytest.mark.parametrize("case", CASES, ids=[f"{i}-{label(c)}" for i, c in enumerate(CASES)])
def test_golden_case(case):
    got, code = outcome(case)
    assert same(got, case["expect"]) is None, same(got, case["expect"])
    if "error" in case["expect"]:
        assert code == case.get("error_id")


@pytest.mark.parametrize("case", [c for c in CASES if "expect_animation" in c],
                         ids=lambda c: c["file"])
def test_skeleton_played_as_animation(case):
    skeleton = formats.read_skeleton(load(case["file"]), case["file"])
    got = formats.summary(formats.animation_from_skeleton(skeleton))
    assert same(got, case["expect_animation"]) is None, same(got, case["expect_animation"])


def test_suite_shape():
    assert len(CASES) >= 24
    present = {fid for c in CASES if "format" in c["expect"] for fid in [c["expect"]["format"]]}
    every = {fid for ids in formats.FORMATS.values() for fid in ids}
    assert present >= every, "one golden case per format id"
    assert {c["error_id"] for c in CASES if "error_id" in c} == ERROR_IDS
    assert sorted(c["file"] for c in CASES if "error" in c["expect"] and "error_id" not in c) == PARSE_LEVEL
    assert any(c["kind"] == "skeleton" and c["expect"]["frame_count"] and c["expect"]["key_count"]
               for c in CASES if "error" not in c["expect"]), "a mixed skeleton"
    assert any(c["expect"].get("clock_fps") == 60.0 for c in CASES), "a Part 1 file on a 60 fps clock"


def test_every_golden_file_is_used():
    used = {c[k] for c in CASES for k in ("file", "animation", "skeleton") if c.get(k)}
    on_disk = {p.name for p in GOLDEN.glob("*.json")} - {"cases.json"}
    assert on_disk == used


def test_the_overflow_golden_is_a_valid_animation_but_for_its_one_number():
    raw = (GOLDEN / OVERFLOW).read_text(encoding="utf-8")
    assert raw.count("1e999") == 1
    with pytest.raises(validate.NotJson, match="^is not valid JSON$"):
        validate.parse_json(raw.encode("utf-8"))
    assert math.isinf(json.loads(raw)["frames"][2]["joints"]["right_hip"][1])
    fixed = validate.parse_json(raw.replace("1e999", "0.0"))
    assert formats.read_animation(fixed, OVERFLOW)["frames"][2]["joints"]["right_hip"][1] == 0.0
    case = next(c for c in CASES if c["file"] == OVERFLOW)
    assert outcome(case) == ({"error": f"{OVERFLOW}: is not valid JSON"}, None)


def test_the_bad_utf8_golden_is_a_valid_animation_but_for_its_one_byte():
    raw = (GOLDEN / BAD_UTF8).read_bytes()
    assert raw.count(b"\xff") == 1 and raw.count(b"caf\xff") == 1
    with pytest.raises(UnicodeDecodeError):
        raw.decode("utf-8")
    with pytest.raises(validate.NotJson, match="^is not valid JSON$"):
        validate.parse_json(raw)
    # A loose decoder turns the byte into U+FFFD and reads a clean animation: the trap this case sets.
    loose = json.loads(raw.decode("utf-8", errors="replace"))
    assert loose["note"] == "caf\ufffd"
    assert len(formats.read_animation(loose, BAD_UTF8)["frames"]) == 3
    fixed = validate.parse_json(raw.replace(b"\xff", b"e"))
    assert fixed["note"] == "cafe" and len(formats.read_animation(fixed, BAD_UTF8)["frames"]) == 3
    case = next(c for c in CASES if c["file"] == BAD_UTF8)
    assert outcome(case) == ({"error": f"{BAD_UTF8}: is not valid JSON"}, None)


def test_golden_files_are_small():
    for path in GOLDEN.glob("*.json"):
        assert path.stat().st_size < 64_000, path.name
        try:
            data = validate.parse_json(path.read_bytes())
        except validate.NotJson:
            assert path.name in PARSE_LEVEL, f"{path.name} is not strict JSON but is not a parse-level case"
            continue
        frames = data.get("frames") if isinstance(data, dict) else None
        assert not isinstance(frames, list) or len(frames) <= 64, path.name


# ---- detection, AC-F02 ---------------------------------------------------------------------

def test_part4_skeleton_with_both_fields_reads_as_v1():
    data = load("skeleton-v1-keys-part4.json")
    assert data["format"] == "simon.skeleton.v1" and data["schema"] == "simon.skeleton/1"
    got = formats.read_skeleton(data)
    assert (got["format"], got["detected_by"]) == ("simon.skeleton.v1", "version")


def test_unknown_format_names_the_field_and_the_ids():
    with pytest.raises(formats.FormatError) as err:
        formats.read_animation({"format": "simon.animation.v2", "fps": 30, "frames": []})
    assert str(err.value) == ('animation.json: format "simon.animation.v2" is not a version Part 6 '
                              'reads (it reads simon.animation/1, simon.animation.v1)')
    assert err.value.code == "E2"


def test_schema_field_is_named_when_there_is_no_format():
    with pytest.raises(formats.FormatError, match='skeleton.json: schema "simon.skeleton/9" is not'):
        formats.read_skeleton({"schema": "simon.skeleton/9"})


def test_format_is_named_before_schema():
    with pytest.raises(formats.FormatError, match='format "a"'):
        formats.read_keyframes({"schema": "b", "format": "a"})


def test_an_unknown_format_is_never_rescued_by_a_known_schema():
    data = load("animation-1-part6.json")
    data["format"] = "simon.animation.v9"
    assert data["schema"] == "simon.animation/1"
    with pytest.raises(formats.FormatError) as err:
        formats.read_animation(data)
    assert err.value.code == "E2" and 'format "simon.animation.v9"' in str(err.value)


def test_a_string_format_decides_before_schema_is_looked_at():
    data = load("skeleton-1-part3.json")
    data["format"] = "simon.animation.v1"           # another kind's id: E3, though schema fits
    with pytest.raises(formats.FormatError) as err:
        formats.read_skeleton(data)
    assert err.value.code == "E3"
    data["format"] = "simon.skeleton.v1"            # this kind's id wins over the /1 schema
    assert formats.read_skeleton(data)["format"] == "simon.skeleton.v1"


def test_a_format_that_is_not_text_falls_through_to_schema():
    data = load("animation-1-part6.json")
    for value in (None, 2, True, ["simon.animation.v1"], {"id": 1}):
        data["format"] = value
        assert formats.read_animation(data)["format"] == "simon.animation/1"


def test_version_wins_over_shape():
    data = load("animation-shape-people.json")
    data["format"] = "simon.animation.v1"
    with pytest.raises(formats.FormatError) as err:
        formats.read_animation(data)
    assert err.value.code == "E7" and "frames[0].joints.nose" in str(err.value)


def test_known_id_of_another_kind_is_e3_even_if_the_shape_fits():
    data = load("animation-v1-part4.json")
    with pytest.raises(formats.FormatError) as err:
        formats.read_skeleton(data, "mine.json")
    assert str(err.value) == ("mine.json: holds simon.animation.v1, which belongs in animation.json, "
                              "not skeleton.json")


def test_default_file_names():
    for kind in formats.KINDS:
        with pytest.raises(formats.FormatError, match=f"^{kind}.json: is not a JSON object$"):
            formats.read(kind, [])
    with pytest.raises(formats.FormatError, match="^keyframes.json: is not a JSON object$"):
        formats.read_keyframes("x")


def test_format_error_is_a_value_error_with_a_code():
    assert issubclass(formats.FormatError, ValueError)
    with pytest.raises(ValueError):
        formats.read_animation(None)


# ---- detect_kind, AC-F03 -----------------------------------------------------------------------

def test_detect_kind_by_version_even_against_the_name():
    assert formats.detect_kind({"format": "simon.keyframes.v1"}, "skeleton.json") == "keyframes"
    assert formats.detect_kind({"schema": "simon.animation/1"}, "x.json") == "animation"
    assert formats.detect_kind({"format": "nope", "schema": "simon.skeleton/1"}, "x.json") == "skeleton"


def test_detect_kind_by_name_is_case_insensitive_and_ordered():
    assert formats.detect_kind({}, "My-SKELETON.json") == "skeleton"
    assert formats.detect_kind({}, "ANIMATION.JSON") == "animation"
    assert formats.detect_kind({}, "KeyFrames.json") == "keyframes"
    assert formats.detect_kind({"fps": 30, "frames": []}, "a-keyframe-animation.json") == "keyframes"
    assert formats.detect_kind({"format": "simon.animation.v7"}, "skeleton-take.json") == "skeleton"


def test_detect_kind_by_shape():
    assert formats.detect_kind({"fps": 30, "frames": [{}]}, "a.json") == "animation"
    assert formats.detect_kind({"frames": [{}]}, "a.json") == "skeleton"
    assert formats.detect_kind({"keyframes": [{"joints": {}}]}, "a.json") == "skeleton"
    assert formats.detect_kind({"keyframes": [{"name": "a"}]}, "a.json") == "keyframes"
    assert formats.detect_kind({"people": []}, "a.json") == "keyframes"
    assert formats.detect_kind({"keyframes": []}, "a.json") == "keyframes"


def test_detect_kind_nothing_matches_names_the_file():
    with pytest.raises(formats.FormatError) as err:
        formats.detect_kind({"hello": 1}, "notes.txt")
    assert str(err.value) == "notes.txt: has no format or schema field and its shape matches no reader"
    with pytest.raises(formats.FormatError, match="^list.json: is not a JSON object$"):
        formats.detect_kind([], "list.json")


# ---- joints, persons and times, AC-F04 to AC-F06 ---------------------------------------------------

def test_joints_as_objects_or_arrays_read_the_same():
    obj = formats.read_animation(load("animation-v1-bare.json"))
    arr = deepcopy(load("animation-v1-bare.json"))
    for fr in arr["frames"]:
        fr["joints"] = {k: [v["x"], v["y"], v["z"]] for k, v in fr["joints"].items()}
    assert formats.read_animation(arr)["frames"] == obj["frames"]


def test_normalized_joint_is_three_plain_numbers_in_joint_order():
    first = formats.read_animation(load("animation-v1-index-only.json"))["frames"][0]["joints"]
    assert list(first) == list(formats.JOINTS)
    assert all(isinstance(v, list) and len(v) == 3 for v in first.values())
    assert "pelvis" not in first


def test_person_choice_by_id_then_first():
    got = formats.read_animation(load("animation-1-people-choice.json"))["frames"]
    assert got[0]["joints"]["nose"][0] == 0.0           # id 0, not the decoy shifted by 1.0
    assert got[2]["joints"]["nose"][0] == 0.0           # only id 7: the first person


def test_a_boolean_is_not_a_number():
    data = load("animation-1-part6.json")
    data["fps"] = True
    with pytest.raises(formats.FormatError, match="fps: must be a number above 0"):
        formats.read_animation(data)
    data = load("animation-1-part6.json")
    data["frames"][1]["people"][0]["joints"]["nose"]["y"] = False
    with pytest.raises(formats.FormatError, match="frames\\[1\\].people\\[0\\].joints.nose: needs three"):
        formats.read_animation(data)


def test_interpolated_missing_means_false_and_only_true_counts():
    data = load("animation-1-part6.json")
    data["frames"][0]["interpolated"] = "yes"
    del data["frames"][2]["interpolated"]
    flags = [f["interpolated"] for f in formats.read_animation(data)["frames"]]
    assert flags[:3] == [False, True, False]


def test_a_v1_skeleton_key_block_inside_a_field_is_found_and_named():
    got = formats.read_skeleton(load("skeleton-mixed-nested.json"))
    assert [k["name"] for k in got["keys"]] == ["low", "high", "low"]
    assert len(got["frames"]) == 6 and got["format"] == "simon.skeleton/1"


def test_skeleton_without_frames_or_keys_lists_are_null():
    keys_only = formats.read_skeleton(load("skeleton-v1-keys-part4.json"))
    assert keys_only["frames"] is None and len(keys_only["keys"]) == 5
    frames_only = formats.read_skeleton(load("skeleton-1-part3.json"))
    assert frames_only["keys"] is None and len(frames_only["frames"]) == 33


def test_dropped_person_frames_have_null_joints():
    got = formats.read_skeleton(load("skeleton-1-dropped.json"))["frames"]
    assert [f["joints"] is None for f in got] == [True, True, False, False, False, True, False, True]


def test_ignored_fields_do_not_matter():
    data = load("skeleton-1-part3.json")
    data["bone_lengths_m"] = "garbage"
    data["bones"] = 7
    data["rest_offsets_m"] = None
    assert formats.read_skeleton(data)["format"] == "simon.skeleton/1"


# ---- key frames on any clock, AC-F08 ------------------------------------------------------------------

def test_mark_frame_moves_a_mark_between_clocks():
    got = formats.read_keyframes(load("keyframes-part1-60fps.json"))
    assert got["clock_fps"] == 60.0
    assert formats.mark_frame(got["marks"][0]["t"], 60) == 120
    assert formats.mark_frame(got["marks"][0]["t"], 30) == 60
    assert [formats.mark_frame(m["t"], 30) for m in got["marks"]] == [60, 75, 90, 120, 135, 150]


def test_mark_frame_rounds_halves_up_not_to_even():
    assert formats.mark_frame(0.5, 1) == 1       # Python round(0.5) is 0
    assert formats.mark_frame(2.5, 1) == 3       # Python round(2.5) is 2
    assert formats.mark_frame(0.75, 30) == 23    # 22.5 frames
    assert isinstance(formats.mark_frame(1.0, 30), int)


def test_part1_marks_carry_rep_and_person():
    got = formats.read_keyframes(load("keyframes-part1-people.json"))["marks"]
    assert [(m["name"], m["rep"], m["person"]) for m in got] == [
        ("start", 1, 0), ("top", 1, 0), ("bottom", 2, 0)]
    first = formats.read_keyframes(load("keyframes-part1.json"))["marks"]
    assert [m["rep"] for m in first] == [1, 1, 1, 2, 2, 2]


def test_v1_marks_have_no_rep_or_person_and_the_clock_is_fps():
    got = formats.read_keyframes(load("keyframes-v1.json"))
    assert got["clock_fps"] == 30.0
    assert all(m["rep"] is None and m["person"] is None for m in got["marks"])


def test_marks_with_equal_times_keep_file_order():
    got = formats.read_keyframes(load("keyframes-part1-no-tms.json"))["marks"]
    assert [m["name"] for m in got if m["t"] == 1.5] == ["start", "dup"]


def test_no_marks_is_valid():
    for name in ("keyframes-part1-empty.json", "keyframes-v1-empty.json"):
        assert formats.read_keyframes(load(name))["marks"] == []


# ---- skeleton played as its own animation, AC-F07 ---------------------------------------------------

def skeleton_at(times, key="t"):
    """A tiny skeleton whose pose at each time has nose x equal to the sample number."""
    base = {n: [0.0, 0.0, 0.0] for n in formats.JOINTS}
    frames = []
    for j, t in enumerate(times):
        joints = deepcopy(base)
        joints["nose"][0] = float(j)
        frames.append({"t": t, "joints": joints})
    return {"kind": "skeleton", "format": "simon.skeleton/1", "detected_by": "version",
            "frames": frames, "keys": None}


def test_poses_are_held_never_blended():
    got = formats.animation_from_skeleton(skeleton_at([0.0, 0.1]))
    assert got["held"] is True and got["source_kind"] == "skeleton" and got["fps"] == 30
    assert len(got["frames"]) == 4
    assert [f["joints"]["nose"][0] for f in got["frames"]] == [0.0, 0.0, 0.0, 1.0]
    assert [f["interpolated"] for f in got["frames"]] == [False, True, True, False]
    assert [f["t"] for f in got["frames"]] == [0.0, 1 / 30, 2 / 30, 3 / 30]


def test_frames_before_the_first_sample_show_the_first_pose():
    got = formats.animation_from_skeleton(skeleton_at([0.1]))
    assert len(got["frames"]) == 4
    assert all(f["joints"]["nose"][0] == 0.0 for f in got["frames"])
    assert [f["interpolated"] for f in got["frames"]] == [True, True, True, False]


def test_samples_are_sorted_by_time_and_ties_keep_file_order():
    got = formats.animation_from_skeleton(skeleton_at([0.1, 0.0, 0.1]))
    # sorted: sample 1 (t 0), sample 0 (t 0.1), sample 2 (t 0.1); the later tie wins
    assert [f["joints"]["nose"][0] for f in got["frames"]] == [1.0, 1.0, 1.0, 2.0]


def test_time_tolerance_is_one_microsecond():
    got = formats.animation_from_skeleton(skeleton_at([0.0, 1 / 30 + 5e-7]))
    assert got["frames"][1]["joints"]["nose"][0] == 1.0
    got = formats.animation_from_skeleton(skeleton_at([0.0, 1 / 30 + 5e-6]))
    assert got["frames"][1]["joints"]["nose"][0] == 0.0


def test_part3_three_decimal_milliseconds_show_on_their_own_frame():
    # 66.667 ms is 0.066667 s, a little after frame 2 (0.0666667 s); it must still show at frame 2
    ms = [round(i * 1000 / 15, 3) / 1000 for i in range(4)]
    got = formats.animation_from_skeleton(skeleton_at(ms))
    shown = [f["joints"]["nose"][0] for f in got["frames"]]
    assert shown[:7] == [0.0, 0.0, 1.0, 1.0, 2.0, 2.0, 3.0]
    assert [f["interpolated"] for f in got["frames"]][:7] == [False, True, False, True, False, True, False]


def test_a_single_pose_is_a_still():
    got = formats.animation_from_skeleton(skeleton_at([0.0]))
    assert len(got["frames"]) == 1 and got["frames"][0]["t"] == 0.0
    assert formats.summary(got)["duration_s"] == 0.0


def test_keys_play_when_no_frame_has_a_person():
    skeleton = skeleton_at([0.0])
    skeleton["keys"] = skeleton_at([0.0, 0.5])["frames"]
    for key in skeleton["keys"]:
        key["name"] = ""
    skeleton["frames"][0]["joints"] = None
    got = formats.animation_from_skeleton(skeleton)
    assert len(got["frames"]) == 16 and got["frames"][-1]["joints"]["nose"][0] == 1.0


def test_playable_prefers_the_animation_then_the_skeleton_then_says_so():
    anim = formats.read_animation(load("animation-1-part6.json"))
    skel = formats.read_skeleton(load("skeleton-1-part3.json"))
    assert formats.playable(anim, skel) is anim
    assert formats.playable(anim)["source_kind"] == "animation"
    assert formats.playable(None, skel)["source_kind"] == "skeleton"
    with pytest.raises(formats.FormatError) as err:
        formats.playable()
    assert str(err.value) == "nothing to play: add an animation.json or a skeleton.json"
    assert err.value.code == "E12"


# ---- time from 0 to two hours, E16 ---------------------------------------------------------------------

def test_limit_constant():
    assert formats.MAX_TIME_S == 7200


def test_exactly_two_hours_is_allowed_and_a_hair_over_is_not():
    data = load("animation-v1-limit.json")
    assert formats.read_animation(data)["frames"][-1]["t"] == 7200.0
    data["frames"][2]["index"] = 7200.000001
    with pytest.raises(formats.FormatError, match="frames\\[2\\]: time must be from 0 to two hours") as err:
        formats.read_animation(data)
    assert err.value.code == "E16"


def test_the_longest_skeleton_plays_in_a_bounded_number_of_frames():
    skeleton = formats.read_skeleton(load("skeleton-1-limit.json"))
    got = formats.animation_from_skeleton(skeleton)
    assert len(got["frames"]) == 7200 * formats.PLAY_FPS + 1


def slow_clock():
    """A /1 animation with no t_ms on a 0.0001 fps clock: frame 1 is 10000 s in."""
    data = load("animation-1-part6.json")
    data["fps"] = 0.0001
    for fr in data["frames"]:
        del fr["t_ms"]
    return data


def test_every_way_to_derive_a_time_is_checked():
    cases = [
        ("animation", {"schema": "simon.animation/1", "fps": 30, "frames": [{"t_ms": 7200001, "people": []}]},
         "frames[0]"),
        ("animation", slow_clock(), "frames[1]"),
        ("animation", {"format": "simon.animation.v1", "fps": 30, "frames": [{"t": 7200.5}]}, "frames[0]"),
        ("animation", {"format": "simon.animation.v1", "fps": 1, "frames": [{"index": 9999}]}, "frames[0]"),
        ("skeleton", {"schema": "simon.skeleton/1", "frames": [{"t_ms": 8e9}]}, "frames[0]"),
        ("skeleton", {"schema": "simon.skeleton/1", "frames": [{"t": 7201}]}, "frames[0]"),
        ("skeleton", {"format": "simon.skeleton.v1", "keyframes": [{"t": 7201, "joints": {}}]},
         "keyframes[0]"),
        ("skeleton", {"format": "simon.skeleton.v1", "keyframes": [{"index": 400000, "joints": {}}]},
         "keyframes[0]"),
        ("keyframes", {"people": [{"id": 0, "repetitions": [{"keyframes": [{"name": "a", "t_ms": 7.3e6}]}]}]},
         "people[0].repetitions[0].keyframes[0]"),
        ("keyframes", {"fps": 60, "people": [{"id": 0, "repetitions": [{"keyframes": [
            {"name": "a", "frame": 500000}]}]}]}, "people[0].repetitions[0].keyframes[0]"),
        ("keyframes", {"format": "simon.keyframes.v1", "keyframes": [{"name": "a", "t": 1e300}]},
         "keyframes[0]"),
        ("keyframes", {"format": "simon.keyframes.v1", "fps": 30, "keyframes": [{"name": "a", "index": 1e9}]},
         "keyframes[0]"),
    ]
    for kind, data, where in cases:
        with pytest.raises(formats.FormatError) as err:
            formats.read(kind, data, "f.json")
        assert str(err.value) == f"f.json: {where}: time must be from 0 to two hours", (kind, data)
        assert err.value.code == "E16"


def test_below_zero_is_e16_but_a_missing_or_text_time_is_still_e14_or_e11():
    for data, kind in (
            ({"format": "simon.keyframes.v1", "fps": 30, "keyframes": [{"name": "a", "t": -0.5}]}, "keyframes"),
            ({"format": "simon.keyframes.v1", "fps": 30, "keyframes": [{"name": "a", "index": -1}]}, "keyframes"),
            ({"fps": 30, "people": [{"id": 0, "repetitions": [{"keyframes": [{"name": "a", "t_ms": -1}]}]}]},
             "keyframes"),
            ({"fps": 30, "people": [{"id": 0, "repetitions": [{"keyframes": [{"name": "a", "frame": -1}]}]}]},
             "keyframes")):
        with pytest.raises(formats.FormatError) as err:
            formats.read(kind, data)
        assert err.value.code == "E16", data
    for item in ({"name": "a"}, {"name": "a", "t": "soon"}, {"name": "a", "index": None}):
        with pytest.raises(formats.FormatError) as err:
            formats.read_keyframes({"format": "simon.keyframes.v1", "fps": 30, "keyframes": [item]})
        assert err.value.code == "E14", item


def test_a_negative_part1_t_ms_still_falls_back_to_the_frame_clock():
    data = {"fps": 60, "people": [{"id": 0, "repetitions": [{"keyframes": [
        {"name": "a", "t_ms": -5, "frame": 60}]}]}]}
    assert formats.read_keyframes(data)["marks"][0]["t"] == 1.0


NASTY = [1e308, -1e308, 1.7976931348623157e308, -1.7976931348623157e308, 5e-324, -5e-324, 1e-320,
         -1e-320, 2 ** 1000, -(2 ** 1000), 2 ** 1023, -(2 ** 1023), 10 ** 308, -(10 ** 308), 10 ** 400,
         -(10 ** 400), float("inf"), float("-inf"), float("nan"), 0, -0.0, 0.0, 7200, 7200.0000001, -1]


def sweeps():
    """Every reader with a nasty number in each field that carries a time, a rate or an index."""
    joints = {n: [0.0, 0.0, 0.0] for n in formats.JOINTS}
    person = {"id": 0, "joints": joints}
    for v in NASTY:
        yield "animation", {"schema": "simon.animation/1", "fps": v, "frames": [{"people": [person]}]}
        yield "animation", {"schema": "simon.animation/1", "fps": 30, "frames": [{"t_ms": v, "people": [person]}]}
        yield "animation", {"schema": "simon.animation/1", "fps": 0.001,
                            "frames": [{"people": [person]}, {"people": [person]}]}
        yield "animation", {"format": "simon.animation.v1", "fps": v, "frames": [{"joints": joints}]}
        yield "animation", {"format": "simon.animation.v1", "fps": 0.001,
                            "frames": [{"index": v, "joints": joints}]}
        yield "animation", {"format": "simon.animation.v1", "fps": 30, "frames": [{"t": v, "joints": joints}]}
        yield "skeleton", {"schema": "simon.skeleton/1", "frames": [{"t_ms": v, "people": [person]}]}
        yield "skeleton", {"schema": "simon.skeleton/1", "frames": [{"t": v, "people": [person]}]}
        yield "skeleton", {"format": "simon.skeleton.v1", "keyframes": [{"t": v, "joints": joints}]}
        yield "skeleton", {"format": "simon.skeleton.v1", "keyframes": [{"index": v, "joints": joints}]}
        for fps in (v, 0.001):
            reps = [{"keyframes": [{"name": "a", "frame": v}, {"name": "b", "t_ms": v}]}]
            yield "keyframes", {"fps": fps, "people": [{"id": 0, "repetitions": reps}]}
            yield "keyframes", {"format": "simon.keyframes.v1", "fps": fps,
                                "keyframes": [{"name": "a", "index": v}, {"name": "b", "t": v}]}


def test_no_value_makes_a_reader_raise_anything_but_a_format_error():
    count = 0
    for kind, data in sweeps():
        try:
            got = formats.read(kind, data)
        except formats.FormatError:
            continue
        count += 1
        formats.summary(got)
        if kind == "skeleton":
            assert len(formats.animation_from_skeleton(got)["frames"]) <= 7200 * 30 + 1
    assert count > 0


def test_mark_frame_never_raises_on_values_that_are_not_finite():
    for t in NASTY:
        for fps in (30, 1e308, 0.001, float("inf")):
            formats.mark_frame(t, fps)
    assert formats.mark_frame(1e308, 1e308) == float("inf")


def test_a_skeleton_with_several_key_blocks_uses_the_first_in_sorted_order():
    data = load("skeleton-mixed-several-blocks.json")
    assert list(data)[-4:] == ["B", "9", "10", "A"]      # file order
    got = formats.read_skeleton(data)
    assert [k["name"] for k in got["keys"]] == ["ten-a", "ten-b"]   # "10" sorts before "9", "A", "B"
    data["10"]["keyframes"][1]["joints"].pop("nose")
    with pytest.raises(formats.FormatError, match="^skeleton.json: 10.keyframes\\[1\\].joints.nose: missing$"):
        formats.read_skeleton(data)


def test_a_skeleton_key_without_time_says_t_or_index():
    data = load("skeleton-v1-keys-part4.json")
    del data["keyframes"][2]["t"], data["keyframes"][2]["index"]
    with pytest.raises(formats.FormatError) as err:
        formats.read_skeleton(data)
    assert str(err.value) == "skeleton.json: keyframes[2]: needs t or index" and err.value.code == "E11"
    frame = load("skeleton-1-part3.json")
    del frame["frames"][1]["t_ms"]
    with pytest.raises(formats.FormatError, match="^skeleton.json: frames\\[1\\]: needs t_ms or t$"):
        formats.read_skeleton(frame)


def test_e2_cuts_a_long_value_to_57_characters_and_three_dots():
    def message(value):
        with pytest.raises(formats.FormatError) as err:
            formats.read_animation({"format": value})
        return str(err.value)
    sixty = "a" * 60
    assert f'format "{sixty}" is not' in message(sixty)
    assert f'format "{"a" * 57}..." is not' in message("a" * 61)
    assert f'format "{"a" * 57}..." is not' in message("a" * 5000)
    emoji = "\U0001F600" * 30 + "b" * 31                  # 61 characters, 91 UTF-16 units
    assert f'format "{chr(0x1F600) * 30}{"b" * 27}..." is not' in message(emoji)


def test_the_check_comes_before_any_joint_is_read():
    with pytest.raises(formats.FormatError) as err:
        formats.read_skeleton({"schema": "simon.skeleton/1", "frames": [{"t": 1e12, "people": [{}]}]})
    assert err.value.code == "E16"


# ---- purity, speed and dependencies ------------------------------------------------------------------

READS = [("animation", "animation-1-part6.json"), ("animation", "animation-v1-part4.json"),
         ("skeleton", "skeleton-1-part3.json"), ("skeleton", "skeleton-mixed-nested.json"),
         ("skeleton", "skeleton-v1-keys-part4.json"), ("keyframes", "keyframes-part1-60fps.json"),
         ("keyframes", "keyframes-v1.json")]


@pytest.mark.parametrize("kind,name", READS)
def test_readers_are_pure(kind, name):
    data = load(name)
    before = deepcopy(data)
    first = formats.read(kind, data, name)
    second = formats.read(kind, data, name)
    assert data == before
    assert first == second
    assert formats.summary(first) == formats.summary(second)
    if kind == "skeleton":
        a = formats.animation_from_skeleton(first)
        assert a == formats.animation_from_skeleton(first)
        assert first == second and data == before


def test_a_long_v1_animation_reads_in_under_half_a_second():
    n = 1801
    base = {name: [0.0, 0.1, 0.2] for name in formats.JOINTS}
    data = {"format": "simon.animation.v1", "fps": 30, "frames": [
        {"index": i, "t": round(i / 30, 6), "interpolated": i % 2 == 1,
         "joints": {k: list(v) for k, v in base.items()}} for i in range(n)]}
    start = time.perf_counter()
    got = formats.read_animation(data)
    elapsed = time.perf_counter() - start
    assert len(got["frames"]) == n and elapsed < 0.5, elapsed


def test_module_is_pure_standard_library():
    tree = ast.parse((ROOT / "part6" / "formats.py").read_text(encoding="utf-8"))
    imports = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    imports |= {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert imports <= {"__future__", "math"}
    called = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert not called & {"open", "eval", "exec", "round", "print", "input"}


def test_constants_match_the_spec():
    assert formats.KINDS == ("keyframes", "skeleton", "animation")
    assert formats.PLAY_FPS == 30
    assert formats.PRODUCER["simon.animation.v1"] == 4 and formats.PRODUCER["simon.animation/1"] == 6
    assert len(formats.JOINTS) == 17 and math.isclose(len(set(formats.JOINTS)), 17)
