"""Catalog contract v1 (docs/specs/catalog-contract.md AC-C01, C03, C04, C14, C15).

Covers `part6/schema_check.py` keyword by keyword, the schema files under `contracts/`, the
agreement of `contracts/manifest.schema.json` with `part6.validate.check_manifest`, the shipped and
conformance files against their schemas, and `part6/contract.py`.
"""
import copy
import io
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from part6 import contract, formats, schema_check, validate
from part6.schema_check import SchemaError, errors

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "fixtures" / "output" / "catalog"
CONFORMANCE = ROOT / "fixtures" / "conformance"
GOLDEN = CONFORMANCE / "formats" / "cases.json"

try:  # a second opinion; the schema_check assertions below always run
    import jsonschema
except ImportError:  # pragma: no cover (depends on the host)
    jsonschema = None


def third_party_valid(instance, schema):
    """What the jsonschema package says, or None when it is not installed."""
    if jsonschema is None:
        return None
    return jsonschema.Draft202012Validator(schema).is_valid(instance)


# ---- schema_check, keyword by keyword ----------------------------------------------------------

def test_type_names():
    cases = [("null", None, True), ("null", 0, False), ("boolean", True, True),
             ("boolean", 0, False), ("object", {}, True), ("object", [], False),
             ("array", [], True), ("array", {}, False), ("string", "", True),
             ("string", 1, False), ("number", 1, True), ("number", 1.5, True),
             ("number", "1", False), ("integer", 3, True), ("integer", 3.5, False),
             ("integer", "3", False)]
    for name, value, valid in cases:
        assert (errors(value, {"type": name}) == []) is valid, (name, value)


def test_booleans_are_neither_integers_nor_numbers():
    assert errors(True, {"type": "integer"}) == ["$: must be integer"]
    assert errors(False, {"type": "number"}) == ["$: must be number"]
    assert errors(True, {"type": ["integer", "number"]}) == ["$: must be integer or number"]


def test_integer_means_an_integer_literal_and_number_must_be_finite():
    assert errors(5.0, {"type": "integer"}) == ["$: must be integer"]
    assert errors(5.0, {"type": "number"}) == []
    assert errors(float("nan"), {"type": "number"}) == ["$: must be number"]
    assert errors(float("inf"), {"type": "number"}) == ["$: must be number"]


def test_type_list_and_null():
    schema = {"type": ["string", "null"]}
    assert errors(None, schema) == []
    assert errors("x", schema) == []
    assert errors(1, schema) == ["$: must be string or null"]


def test_enum_and_const_tell_booleans_from_numbers():
    assert errors("a", {"enum": ["a", "b"]}) == []
    assert errors("c", {"enum": ["a", "b"]}) == ["$: must be one of a, b"]
    assert errors(1, {"const": 1}) == []
    assert errors(True, {"const": 1}) == ["$: must be 1"]
    assert errors(1, {"enum": [True]}) != []
    assert errors([1, {"a": 2}], {"const": [1, {"a": 2}]}) == []
    assert errors([1, {"a": 3}], {"const": [1, {"a": 2}]}) != []
    assert errors(None, {"const": None}) == []


def test_required_names_the_missing_key_as_a_path():
    schema = {"type": "object", "required": ["a", "b"]}
    assert errors({"a": 1, "b": 2}, schema) == []
    assert errors({"a": 1}, schema) == ["b: is required"]
    assert errors([], {"required": ["a"]}) == []  # required only speaks about objects


def test_properties_check_only_the_keys_present():
    schema = {"properties": {"a": {"type": "integer"}, "b": {"type": "string"}}}
    assert errors({"a": 1}, schema) == []
    assert errors({"a": "x", "b": 2}, schema) == ["a: must be integer", "b: must be string"]


def test_additional_properties_true_false_and_schema():
    props = {"properties": {"a": {}}}
    assert errors({"a": 1, "z": 1}, props) == []
    assert errors({"a": 1, "z": 1}, dict(props, additionalProperties=True)) == []
    assert errors({"a": 1, "z": 1}, dict(props, additionalProperties=False)) == ["z: is not allowed"]
    typed = dict(props, additionalProperties={"type": "integer"})
    assert errors({"a": "x", "z": 1}, typed) == []
    assert errors({"z": "x"}, typed) == ["z: must be integer"]


def test_pattern_searches_and_a_final_dollar_ends_the_text():
    assert errors("abc", {"pattern": "b"}) == []
    assert errors("abc", {"pattern": "^b"}) == ["$: does not match ^b"]
    assert errors("abc", {"pattern": "^[a-c]{3}$"}) == []
    assert errors("abc\n", {"pattern": "^[a-c]{3}$"}) != []
    assert errors(5, {"pattern": "^x$"}) == []  # a pattern only speaks about strings


def test_minimum_maximum_and_exclusive_minimum():
    assert errors(1, {"minimum": 1}) == []
    assert errors(0, {"minimum": 1}) == ["$: must be at least 1"]
    assert errors(5, {"maximum": 5}) == []
    assert errors(6, {"maximum": 5}) == ["$: must be at most 5"]
    assert errors(0.1, {"exclusiveMinimum": 0}) == []
    assert errors(0, {"exclusiveMinimum": 0}) == ["$: must be above 0"]
    assert errors("0", {"minimum": 1}) == []  # numbers only
    assert errors(True, {"minimum": 5}) == []  # a boolean is not a number to compare


def test_min_and_max_length_count_characters():
    assert errors("", {"minLength": 1}) == ["$: must have at least 1 characters"]
    assert errors("a", {"minLength": 1}) == []
    assert errors("abc", {"maxLength": 3}) == []
    assert errors("abcd", {"maxLength": 3}) == ["$: must have at most 3 characters"]
    assert errors("éé", {"maxLength": 2}) == []


def test_items_and_item_counts_with_indexed_paths():
    schema = {"type": "array", "items": {"type": "integer"}, "minItems": 1, "maxItems": 2}
    assert errors([1, 2], schema) == []
    assert errors([], schema) == ["$: must have at least 1 items"]
    assert errors([1, 2, 3], schema) == ["$: must have at most 2 items"]
    assert errors([1, "x"], schema) == ["[1]: must be integer"]
    nested = {"properties": {"rows": {"items": {"properties": {"n": {"type": "integer"}}}}}}
    assert errors({"rows": [{"n": 1}, {"n": "x"}]}, nested) == ["rows[1].n: must be integer"]


def test_any_of_needs_one_branch():
    schema = {"anyOf": [{"type": "string"}, {"type": "null"}]}
    assert errors("x", schema) == []
    assert errors(None, schema) == []
    out = errors(1, schema)
    assert len(out) == 1 and out[0].startswith("$: matches none of the allowed forms")
    assert "must be string" in out[0] and "must be null" in out[0]


def test_one_of_needs_exactly_one_branch():
    schema = {"oneOf": [{"type": "integer"}, {"minimum": 10}]}
    assert errors(5, schema) == []
    assert errors(10.5, schema) == []
    assert errors(11, schema) == ["$: matches more than one of the allowed forms"]
    neither = {"oneOf": [{"type": "integer"}, {"type": "string"}]}
    assert errors(None, neither) == [
        "$: matches none of the allowed forms (must be integer; must be string)"]


def test_ref_to_defs_and_to_the_whole_schema():
    schema = {"$defs": {"n": {"type": "integer"}},
              "type": "object", "properties": {"a": {"$ref": "#/$defs/n"}, "b": {"$ref": "#/$defs/n"}}}
    assert errors({"a": 1, "b": 2}, schema) == []
    assert errors({"a": 1, "b": "x"}, schema) == ["b: must be integer"]
    tree = {"type": "object", "properties": {"kid": {"$ref": "#"}}}
    assert errors({"kid": {"kid": 1}}, tree) == ["kid.kid: must be object"]


def test_a_ref_next_to_other_keywords_applies_both():
    schema = {"$defs": {"n": {"type": "integer"}}, "$ref": "#/$defs/n", "minimum": 5}
    assert errors(7, schema) == []
    assert errors(3, schema) == ["$: must be at least 5"]
    assert errors("x", schema) == ["$: must be integer"]


def test_bad_refs_and_unsupported_keywords_are_refused_not_ignored():
    with pytest.raises(SchemaError):
        errors(1, {"$ref": "#/$defs/missing"})
    with pytest.raises(SchemaError):
        errors(1, {"$ref": "https://example.com/other.json"})
    with pytest.raises(SchemaError):
        errors("x", {"format": "email"})
    with pytest.raises(SchemaError):
        errors(1, {"type": "decimal"})


def test_annotations_are_ignored_and_boolean_schemas_work():
    assert errors(1, {"$schema": "x", "$id": "y", "title": "t", "description": "d",
                      "$comment": "c", "default": 1, "examples": [1]}) == []
    assert errors(1, {"properties": {"a": True}}) == []
    assert errors({"a": 1}, {"properties": {"a": False}}) == ["a: is not allowed"]


def test_errors_come_back_in_schema_order_and_empty_means_valid():
    schema = {"type": "object", "required": ["a"], "properties": {"b": {"type": "integer"}}}
    assert errors({"b": "x"}, schema) == ["a: is required", "b: must be integer"]
    assert errors({"a": 0, "b": 1}, schema) == []


# ---- the schema files ----------------------------------------------------------------------------

DASHES = (chr(0x2014), chr(0x2013))  # the em and en dash, spelled so this file holds neither
EXPECTED_NAMES = ["animation.1", "animation.v1", "import-request", "job-status", "keyframes.part1",
                  "keyframes.v1", "manifest", "skeleton.1", "skeleton.v1"]
ID_PREFIX = "https://github.com/moalborati/simon-part-6-recording-catalog/contracts/"


def subschemas(node):
    """Every schema object reachable through the keywords the files use."""
    if not isinstance(node, dict):
        return
    yield node
    for word in ("properties", "$defs"):
        for sub in node.get(word, {}).values():
            yield from subschemas(sub)
    for word in ("anyOf", "oneOf"):
        for sub in node.get(word, ()):
            yield from subschemas(sub)
    yield from subschemas(node.get("items"))
    yield from subschemas(node.get("additionalProperties"))


def test_the_contract_folder_holds_exactly_the_published_schemas():
    assert contract.schema_names() == EXPECTED_NAMES
    assert sorted(p.name for p in contract.SCHEMA_DIR.iterdir()) == \
        [f"{n}.schema.json" for n in EXPECTED_NAMES]


@pytest.mark.parametrize("name", EXPECTED_NAMES)
def test_every_schema_file_is_described_and_uses_only_supported_keywords(name):
    body = json.loads((contract.SCHEMA_DIR / f"{name}.schema.json").read_text())
    assert body["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert body["$id"] == f"{ID_PREFIX}{name}.schema.json"
    assert body["title"].strip() and body["description"].strip()
    for node in subschemas(body):
        unknown = set(node) - schema_check.CHECKED - schema_check.IGNORED
        assert not unknown, f"{name}: {sorted(unknown)}"
    for text in (body["title"], body["description"]):
        assert DASHES[0] not in text and DASHES[1] not in text and " - " not in text


@pytest.mark.parametrize("name", EXPECTED_NAMES)
def test_every_schema_is_valid_for_the_second_opinion(name):
    if jsonschema is not None:
        jsonschema.Draft202012Validator.check_schema(contract.schema(name))
    assert contract.schema(name)["$id"].endswith(f"/{name}.schema.json")


# ---- manifest schema and part6.validate agree ----------------------------------------------------

def good_manifest(**changes):
    manifest = {
        "id": "squat", "name": "Squat", "video_uri": None, "keyframes": "keyframes.json",
        "skeleton": "skeleton.json", "animation": "animation.json",
        "created_at": "2026-10-28T09:00:00Z", "schema_version": 1, "category": "exercise",
        "description": "Bodyweight squat.", "thumbnail": "thumbnail.svg", "duration_ms": 10000,
        "files_source": "fixture"}
    manifest.update(changes)
    return {k: v for k, v in manifest.items() if v is not ABSENT}


ABSENT = object()
HEX = "ab" * 32


def prov(**changes):
    entry = {"part": 4, "format": "simon.animation.v1", "detected_by": "version", "sha256": HEX,
             "bytes": 10, "source": "somewhere", "original_name": "anim.json"}
    entry.update(changes)
    return {k: v for k, v in entry.items() if v is not ABSENT}


VIDEO = {"part": 1, "format": None, "detected_by": "file", "sha256": HEX, "bytes": 10}

GOOD_MANIFESTS = {
    "phase 1 fixture": good_manifest(),
    "mock": good_manifest(files_source="mock", visitor=True),
    "import": good_manifest(files_source="import", visitor=True),
    "processor": good_manifest(files_source="processor"),
    "animation only": good_manifest(skeleton=None, keyframes=None),
    "skeleton only": good_manifest(animation=None),
    "video": good_manifest(video_uri="video.webm", provenance={"video": VIDEO}),
    "dance": good_manifest(category="dance", id="a", name="A"),
    "long id": good_manifest(id="a" + "b" * 62),
    "name of 80": good_manifest(name="n" * 80),
    "extra fields": good_manifest(owner="x", tags=["a"]),
    "provenance": good_manifest(provenance={"animation": prov(), "video": VIDEO}),
    "provenance without optional": good_manifest(
        provenance={"animation": prov(source=ABSENT, original_name=ABSENT)}),
    "provenance part 7": good_manifest(provenance={"animation": prov(part=7)}),
    # The version policy: what a newer version adds never hides an entry (review B4).
    "provenance unknown kind": good_manifest(provenance={"pose3d": prov(), "animation": prov()}),
    "provenance unknown kind of any shape": good_manifest(provenance={"audio": 5, "x": [1]}),
    "provenance unknown record field": good_manifest(
        provenance={"animation": prov(confidence=0.9, tool={"name": "x"})}),
}
BAD_MANIFESTS = {
    "not an object": [],
    "id upper case": good_manifest(id="Squat"),
    "id leading hyphen": good_manifest(id="-squat"),
    "id too long": good_manifest(id="a" * 64),
    "id trailing newline": good_manifest(id="squat\n"),
    "id not a string": good_manifest(id=5),
    "id missing": good_manifest(id=ABSENT),
    "name empty": good_manifest(name=""),
    "name padded": good_manifest(name=" Squat"),
    "name padded after": good_manifest(name="Squat "),
    "name too long": good_manifest(name="n" * 81),
    "name not a string": good_manifest(name=3),
    "video_uri with a folder": good_manifest(video_uri="a/video.webm"),
    "video_uri dotfile": good_manifest(video_uri=".video"),
    "video_uri a number": good_manifest(video_uri=4),
    "keyframes with a folder": good_manifest(keyframes="../keyframes.json"),
    "keyframes a number": good_manifest(keyframes=1),
    "skeleton with a space": good_manifest(skeleton="my skeleton.json"),
    "animation dotfile": good_manifest(animation=".animation.json"),
    "neither skeleton nor animation": good_manifest(skeleton=None, animation=None),
    "thumbnail missing": good_manifest(thumbnail=ABSENT),
    "thumbnail null": good_manifest(thumbnail=None),
    "thumbnail with a folder": good_manifest(thumbnail="a/t.svg"),
    "created_at without Z": good_manifest(created_at="2026-10-28T09:00:00"),
    "created_at date only": good_manifest(created_at="2026-10-28"),
    "created_at month 13": good_manifest(created_at="2026-13-01T00:00:00Z"),
    "created_at number": good_manifest(created_at=5),
    "schema_version 2": good_manifest(schema_version=2),
    "schema_version true": good_manifest(schema_version=True),
    "schema_version string": good_manifest(schema_version="1"),
    "category other": good_manifest(category="sport"),
    "description number": good_manifest(description=1),
    "description missing": good_manifest(description=ABSENT),
    "duration zero": good_manifest(duration_ms=0),
    "duration negative": good_manifest(duration_ms=-5),
    "duration float": good_manifest(duration_ms=1000.5),
    "duration whole float": good_manifest(duration_ms=1000.0),
    "duration true": good_manifest(duration_ms=True),
    "duration string": good_manifest(duration_ms="1000"),
    "files_source pipeline": good_manifest(files_source="pipeline"),
    "files_source missing": good_manifest(files_source=ABSENT),
    "visitor a string": good_manifest(visitor="yes"),
    "provenance a list": good_manifest(provenance=[]),
    "provenance part 0": good_manifest(provenance={"animation": prov(part=0)}),
    "provenance part 8": good_manifest(provenance={"animation": prov(part=8)}),
    "provenance part true": good_manifest(provenance={"animation": prov(part=True)}),
    "provenance format of another kind": good_manifest(
        provenance={"animation": prov(format="simon.skeleton/1")}),
    "provenance format null": good_manifest(provenance={"animation": prov(format=None)}),
    "provenance detected_by file": good_manifest(provenance={"animation": prov(detected_by="file")}),
    "provenance detected_by guess": good_manifest(provenance={"animation": prov(detected_by="guess")}),
    "provenance sha too short": good_manifest(provenance={"animation": prov(sha256="ab" * 31)}),
    "provenance sha upper case": good_manifest(provenance={"animation": prov(sha256="AB" * 32)}),
    "provenance sha missing": good_manifest(provenance={"animation": prov(sha256=ABSENT)}),
    "provenance bytes negative": good_manifest(provenance={"animation": prov(bytes=-1)}),
    "provenance bytes string": good_manifest(provenance={"animation": prov(bytes="10")}),
    "provenance source number": good_manifest(provenance={"animation": prov(source=3)}),
    "provenance original_name number": good_manifest(provenance={"animation": prov(original_name=3)}),
    "provenance video with a format": good_manifest(
        video_uri="video.webm", provenance={"video": dict(VIDEO, format="simon.animation.v1")}),
    "provenance video detected_by shape": good_manifest(
        video_uri="video.webm", provenance={"video": dict(VIDEO, detected_by="shape")}),
    "provenance entry not an object": good_manifest(provenance={"animation": "x"}),
}
# Absent keys are covered separately: the validator reads a missing nullable key as null.
NULLABLE_ABSENT = {
    "video_uri missing": good_manifest(video_uri=ABSENT),
    "keyframes missing": good_manifest(keyframes=ABSENT),
    "skeleton missing": good_manifest(skeleton=ABSENT),
    "animation missing": good_manifest(animation=ABSENT),
}


def schema_ok(manifest):
    return not errors(manifest, contract.schema("manifest"))


def validator_ok(manifest):
    return not validate.check_manifest(manifest, manifest.get("id") if isinstance(manifest, dict) else None)


@pytest.mark.parametrize("label", sorted(GOOD_MANIFESTS))
def test_good_manifests_pass_the_schema_and_the_validator(label):
    manifest = GOOD_MANIFESTS[label]
    assert errors(manifest, contract.schema("manifest")) == []
    assert validate.check_manifest(manifest, manifest["id"]) == []
    assert third_party_valid(manifest, contract.schema("manifest")) in (True, None)


@pytest.mark.parametrize("label", sorted(BAD_MANIFESTS))
def test_bad_manifests_fail_the_schema_and_the_validator(label):
    manifest = BAD_MANIFESTS[label]
    assert schema_ok(manifest) is False, "the schema accepts it"
    assert validator_ok(manifest) is False, "the validator accepts it"
    if label not in ("id trailing newline", "duration whole float"):
        # The second opinion reads "$" as before a final newline and 5.0 as an integer.
        assert third_party_valid(manifest, contract.schema("manifest")) in (False, None)


@pytest.mark.parametrize("label", sorted(NULLABLE_ABSENT))
def test_a_manifest_with_a_nullable_key_left_out_fails_both(label):
    manifest = NULLABLE_ABSENT[label]
    assert schema_ok(manifest) is False
    assert validator_ok(manifest) is False


def test_a_known_provenance_key_keeps_its_checks_beside_an_unknown_one():
    manifest = good_manifest(provenance={"pose3d": prov(), "animation": prov(part=0)})
    assert schema_ok(manifest) is False and validator_ok(manifest) is False
    assert validate.check_manifest(manifest, "squat") == [
        "provenance.animation.part: must be a whole number from 1 to 7"]


def test_the_validator_also_checks_the_folder_name_which_the_schema_cannot():
    manifest = good_manifest()
    assert schema_ok(manifest)
    assert validate.check_manifest(manifest, "other") == ["id: differs from the folder name"]


def test_the_schema_requires_one_of_skeleton_or_animation_to_be_a_string():
    schema = contract.schema("manifest")
    both_null = good_manifest(skeleton=None, animation=None)
    problems = errors(both_null, schema)
    assert len(problems) == 1 and "matches none of the allowed forms" in problems[0]
    assert errors(good_manifest(skeleton=None), schema) == []
    assert errors(good_manifest(animation=None), schema) == []


# ---- shipped and conformance files against their schemas -----------------------------------------

def schema_for_format(format_id):
    return contract.schema(format_id.removeprefix("simon.").replace("/", "."))


def test_every_shipped_fixture_manifest_passes_the_schema():
    folders = sorted(p for p in CATALOG.iterdir() if p.is_dir())
    assert len(folders) >= 8
    for folder in folders:
        manifest = json.loads((folder / "manifest.json").read_text())
        assert errors(manifest, contract.schema("manifest")) == [], folder.name


def test_every_conformance_entry_passes_the_schema_the_validator_and_its_file_schemas():
    manifests = sorted((CONFORMANCE / "entries").glob("*/manifest.json"))
    assert len(manifests) == 8, "two conformance entries per files_source are expected"
    sources = {}
    for path in manifests:
        manifest = json.loads(path.read_text())
        assert errors(manifest, contract.schema("manifest")) == [], path.parent.name
        assert validate.check_manifest(manifest, path.parent.name) == [], path.parent.name
        sources[manifest["files_source"]] = sources.get(manifest["files_source"], 0) + 1
        for kind in formats.KINDS:
            if manifest[kind] is not None:
                data = json.loads((path.parent / manifest[kind]).read_text())
                normal = formats.read(kind, data, manifest[kind])
                assert errors(data, schema_for_format(normal["format"])) == [], (path.parent.name, kind)
    assert sources == {"fixture": 2, "mock": 2, "import": 2, "processor": 2}


def test_every_shipped_entry_file_passes_the_schema_of_the_format_it_reads_as():
    seen = set()
    for manifest_path in sorted(CATALOG.glob("*/manifest.json")):
        manifest = json.loads(manifest_path.read_text())
        for kind in formats.KINDS:
            if manifest[kind] is None:
                continue
            data = json.loads((manifest_path.parent / manifest[kind]).read_text())
            format_id = formats.read(kind, data, manifest[kind])["format"]
            seen.add(format_id)
            assert errors(data, schema_for_format(format_id)) == [], (manifest_path.parent.name, kind)
            assert third_party_valid(data, schema_for_format(format_id)) in (True, None)
    assert {"simon.animation/1", "simon.animation.v1", "simon.skeleton.v1"} <= seen


def golden_cases():
    cases = json.loads(GOLDEN.read_text())
    return cases["cases"] if isinstance(cases, dict) else cases


def golden_data(case):
    return json.loads((GOLDEN.parent / case["file"]).read_text())


def test_every_valid_golden_file_passes_its_format_schema_and_every_format_has_one():
    valid = [c for c in golden_cases() if c["kind"] in formats.KINDS and "error" not in c["expect"]]
    assert len(valid) >= 10
    covered = set()
    for case in valid:
        data = golden_data(case)
        format_id = formats.read(case["kind"], data, case["file"])["format"]
        covered.add(format_id)
        schema = schema_for_format(format_id)
        assert errors(data, schema) == [], case["file"]
        assert third_party_valid(data, schema) in (True, None), case["file"]
    assert covered == set(formats.PRODUCER)


# What a schema cannot say: which version string is known, that times increase, that a mark needs
# fps when it has only a frame, that at least one frame has a person, and the nested key block.
SCHEMA_CAN_SAY = ("is not a JSON object", "fps: must be a number above 0",
                  "frames: must be a non-empty list", "needs three finite numbers", ": missing",
                  "must be a list", ".name: must be a string", ": has no person", "needs t_ms or t")
NESTED_KEY_BLOCK = "invalid-e7-skeleton-nested-key.json"


def test_invalid_golden_files_the_schema_can_describe_fail_every_schema_of_their_kind():
    checked = 0
    for case in golden_cases():
        message = case["expect"].get("error", "") if case["kind"] in formats.KINDS else ""
        if not any(part in message for part in SCHEMA_CAN_SAY) or case["file"] == NESTED_KEY_BLOCK:
            continue
        data = golden_data(case)
        for fid in formats.FORMATS[case["kind"]]:
            schema = schema_for_format(fid)
            assert errors(data, schema) != [], (case["file"], fid)
            assert third_party_valid(data, schema) in (False, None), (case["file"], fid)
        checked += 1
    assert checked >= 20


# ---- the schemas reject what the readers reject --------------------------------------------------

def joint_map(shape="object"):
    return {n: ({"x": 0.0, "y": 0.0, "z": 0.0} if shape == "object" else [0.0, 0.0, 0.0, 1.0])
            for n in formats.JOINTS}


def test_joints_may_be_objects_or_arrays_of_three_or_more_and_all_17_are_needed():
    animation = {"format": "simon.animation.v1", "fps": 30,
                 "frames": [{"t": 0.0, "joints": joint_map("array")},
                            {"t": 0.1, "joints": joint_map("object")}]}
    schema = contract.schema("animation.v1")
    assert errors(animation, schema) == []
    assert formats.read_animation(animation)["frames"][0]["joints"]["nose"] == [0.0, 0.0, 0.0]
    broken = copy.deepcopy(animation)
    del broken["frames"][1]["joints"]["nose"]
    assert errors(broken, schema) == ["frames[1].joints.nose: is required"]
    short = copy.deepcopy(animation)
    short["frames"][0]["joints"]["nose"] = [0.0, 0.0]
    assert errors(short, schema) != []
    stringy = copy.deepcopy(animation)
    stringy["frames"][0]["joints"]["nose"] = {"x": "0", "y": 0, "z": 0}
    assert errors(stringy, schema) != []
    assert third_party_valid(broken, schema) in (False, None)
    assert third_party_valid(short, schema) in (False, None)


def test_the_version_fields_must_name_their_own_format():
    wrong = {"schema": "simon.animation.v1", "fps": 30, "frames": []}
    assert errors(wrong, contract.schema("animation.1")) != []
    assert errors({"format": "simon.skeleton/1", "keyframes": [{"joints": joint_map()}]},
                  contract.schema("skeleton.v1")) != []


def test_part1_marks_need_a_name_and_a_time_in_ms_or_a_frame():
    schema = contract.schema("keyframes.part1")

    def doc(mark):
        return {"fps": 60, "people": [{"id": 0, "repetitions": [{"rep": 1, "keyframes": [mark]}]}]}

    assert errors(doc({"name": "start", "frame": 120, "t_ms": 2000}), schema) == []
    assert errors(doc({"name": "start", "frame": 120}), schema) == []
    assert errors(doc({"name": "start", "t_ms": 2000}), schema) == []
    assert errors(doc({"frame": 120, "t_ms": 2000}), schema) == ["people[0].repetitions[0].keyframes[0].name: is required"]
    assert errors(doc({"name": "start"}), schema) != []
    assert errors(doc({"name": "start", "t_ms": -1}), schema) != []
    assert errors({"fps": 0, "people": []}, schema) == ["fps: must be above 0"]
    assert errors({"people": {}}, schema) == ["people: must be array"]


def test_import_request_body_matches_the_http_contract():
    schema = contract.schema("import-request")
    text = {"name": "skeleton.json", "text": "{}"}
    video = {"name": "clip.webm", "base64": "AAAA"}
    good = {"name": "Squat", "category": "exercise", "files": [text, video]}
    assert errors(good, schema) == []
    assert third_party_valid(good, schema) in (True, None)
    bad = {
        "no files": dict(good, files=[]),
        "five files": dict(good, files=[text] * 5),
        "category": dict(good, category="sport"),
        "name": dict(good, name=""),
        "file with neither": dict(good, files=[{"name": "a.json"}]),
        "file with both": dict(good, files=[{"name": "a.json", "text": "{}", "base64": "AA"}]),
        "files missing": {"name": "Squat", "category": "dance"},
        "text a number": dict(good, files=[{"name": "a.json", "text": 5}]),
    }
    for label, body in bad.items():
        assert errors(body, schema) != [], label
        assert third_party_valid(body, schema) in (False, None), label
    assert errors(dict(good, files=[text] * 4), schema) == []


IMPORT_400 = ("name", "category", "files", "too many files", "two <kind> files",
              "<name>: is not valid JSON", "<name>: file too large",
              "<name>: not a WebM or MP4 video", "<name>: not valid base64", "body")


def test_the_import_answers_are_published_in_the_contract_text_and_the_schema(tmp_path):
    text = (ROOT / "CONTRACT.md").read_text()
    section = text[text.index("### Import over HTTP"):text.index("## The processor plug-in seam")]
    description = contract.schema("import-request")["description"]
    for reason in IMPORT_400:
        assert f"`{reason}`" in section, reason
        assert reason in description, reason
    for answer in ("408", "body too slow", "413", "503", "busy, try again"):
        assert answer in section and answer in description, answer
    assert "One import runs at a time" in " ".join(section.split())
    assert "One import runs at a time" in description
    row = next(r for r in contract.document()["api"] if r["path"] == "api/import")
    assert "408 body too slow" in row["result"]
    assert "408 body too slow" in next(l for l in text.splitlines() if l.startswith("| `POST api/import`"))


def contract_text_between(start, end):
    text = (ROOT / "CONTRACT.md").read_text()
    return text[text.index(start):text.index(end)]


def kit_thresholds():
    """The metric names in THRESHOLDS of check/check6-contract.mjs, read from the source."""
    source = (ROOT / "check" / "check6-contract.mjs").read_text()
    block = source[source.index("const THRESHOLDS = {"):]
    block = block[:block.index("};")]
    return re.findall(r"^  (\w+): \{", block, re.MULTILINE)


def test_the_conformance_kit_section_lists_every_metric_the_kit_measures():
    metrics = kit_thresholds()
    assert len(metrics) >= 21 and "follow_note_ok" in metrics and "nan_import_refused" in metrics
    section = contract_text_between("## The conformance kit", "## Version policy")
    listed = re.findall(r"^\| `(\w+)` \|", section, re.MULTILINE)
    assert sorted(listed) == sorted(metrics)
    assert len(set(listed)) == len(listed)


def test_the_processor_section_says_visitors_read_a_failure_reason():
    section = " ".join(contract_text_between(
        "## The processor plug-in seam", "## The hand-off to Part 7").split())
    assert "shown on the Record screen" in section
    assert "must not put secrets, tokens, private paths or host names in them" in section


@pytest.mark.parametrize("status,valid", [
    ("queued", True), ("done", True), ("processing:keyframes", True), ("processing:a", True),
    ("processing:" + "a" * 32, True), ("failed:pose: no person found in the video", True),
    ("failed:validate: animation.json: frames: must be a non-empty list", True),
    ("failed:processing: boom", True),
    ("processing:" + "a" * 33, False), ("processing:", False), ("processing:Pose", False),
    ("processing:-x", False), ("failed:pose", False), ("failed:pose:", False),
    ("failed:pose: ", False), ("failed:: reason", False), ("queued ", False), ("running", False),
    ("done\n", False), ("", False), ("failed:pose: line one\nline two", False),
])
def test_job_status_pattern_is_the_status_vocabulary(status, valid):
    schema = contract.schema("job-status")
    assert (errors(status, schema) == []) is valid
    if "\n" not in status:
        assert third_party_valid(status, schema) in (valid, None)
    assert errors(None, schema) == ["$: must be string"]


# ---- part6/contract.py ---------------------------------------------------------------------------

def test_schema_returns_the_file_and_raises_keyerror_for_an_unknown_name():
    assert contract.schema("manifest")["$id"] == f"{ID_PREFIX}manifest.schema.json"
    for name in ("nope", "", "../manifest", "manifest.schema.json", "MANIFEST"):
        with pytest.raises(KeyError):
            contract.schema(name)


def test_constants():
    assert contract.CONTRACT_VERSION == 1
    assert contract.SCHEMA_DIR == ROOT / "contracts"


def test_document_has_the_ac_c04_keys():
    doc = contract.document()
    assert list(doc) == ["contract_version", "schemas", "formats", "files_sources", "api", "handoff"]
    assert doc["contract_version"] == 1
    assert sorted(doc["schemas"]) == EXPECTED_NAMES
    for name in EXPECTED_NAMES:
        assert doc["schemas"][name] == contract.schema(name)
    assert doc["files_sources"] == ["fixture", "mock", "import", "processor"]
    assert doc["files_sources"] == list(validate.FILES_SOURCES)
    assert doc["handoff"] == {"route": "#/entry/{id}", "event": "simon:follow",
                              "message_type": "simon:follow", "follow_url": None}


def test_document_formats_come_from_the_readers_with_their_version_field():
    rows = {row["id"]: row for row in contract.document()["formats"]}
    assert set(rows) == set(formats.PRODUCER)
    assert all(set(row) == {"id", "kind", "producer_part", "version_field"} for row in rows.values())
    expect = {
        "simon.keyframes/part1": ("keyframes", 1, None),
        "simon.keyframes.v1": ("keyframes", 4, "format"),
        "simon.skeleton/1": ("skeleton", 3, "schema"),
        "simon.skeleton.v1": ("skeleton", 4, "format"),
        "simon.animation/1": ("animation", 6, "schema"),
        "simon.animation.v1": ("animation", 4, "format"),
    }
    for fid, (kind, part, field) in expect.items():
        assert (rows[fid]["kind"], rows[fid]["producer_part"], rows[fid]["version_field"]) == \
            (kind, part, field), fid


def test_document_api_table_is_ac_c03():
    api = contract.document()["api"]
    assert [(r["method"], r["path"]) for r in api] == [
        ("GET", "api/health"), ("GET", "api/contract"), ("GET", "api/entries[?q=&category=&source=]"),
        ("GET", "api/entries/<id>"), ("GET", "api/entries/<id>/<file>"), ("POST", "api/entries"),
        ("GET", "api/jobs/<id>"), ("POST", "api/import")]
    assert all(r["result"].strip() for r in api)


def test_document_carries_the_follow_url_and_is_json():
    doc = contract.document("https://part7.example/follow?m={manifest}&id={id}")
    assert doc["handoff"]["follow_url"] == "https://part7.example/follow?m={manifest}&id={id}"
    assert json.loads(json.dumps(doc)) == doc
    assert contract.document()["handoff"]["follow_url"] is None


def test_document_is_a_fresh_object_each_time():
    first = contract.document()
    first["schemas"]["manifest"]["title"] = "changed"
    assert contract.document()["schemas"]["manifest"]["title"] != "changed"


def test_run_prints_the_document_and_one_schema():
    out = io.StringIO()
    assert contract.run(None, out) == 0
    assert json.loads(out.getvalue()) == contract.document()
    assert out.getvalue().startswith("{\n  \"contract_version\": 1,")
    one = io.StringIO()
    assert contract.run("job-status", one) == 0
    assert json.loads(one.getvalue()) == contract.schema("job-status")


def test_run_with_an_unknown_schema_says_so_on_stderr_and_exits_2(capsys):
    out = io.StringIO()
    assert contract.run("nope", out) == 2
    assert out.getvalue() == ""
    err = capsys.readouterr().err
    assert "nope" in err and "manifest" in err


def cli(*args):
    return subprocess.run([sys.executable, "-m", "part6", *args], cwd=ROOT, capture_output=True,
                          text=True, timeout=60)


def test_cli_contract_prints_the_same_object_as_document():
    done = cli("contract")
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout) == contract.document()


def test_cli_contract_schema_prints_one_schema_and_an_unknown_one_exits_2():
    done = cli("contract", "--schema", "manifest")
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout) == contract.schema("manifest")
    missing = cli("contract", "--schema", "nope")
    assert missing.returncode == 2 and missing.stdout == "" and "nope" in missing.stderr


# ---- check_follow_url ----------------------------------------------------------------------------

@pytest.mark.parametrize("url", [
    "http://localhost:3000/follow/{id}",
    "https://part7.example.com/follow?id={id}&manifest={manifest}",
    "HTTPS://Part7.example/x",
    "http://127.0.0.1:8080",
    "https://[::1]:8443/follow",
    "http://host/{id}",
])
def test_check_follow_url_returns_a_good_url_unchanged(url):
    assert contract.check_follow_url(url) == url


@pytest.mark.parametrize("url", [
    "", "   ", "ftp://host/x", "file:///etc/passwd", "javascript:alert(1)", "//host/x",
    "/follow/{id}", "part7.example/follow", "http://", "https://", "http:///path",
    "http://:80/x", "http://host:notaport/x", "http://host:99999/x", "http://ho st/x",
    "http://host/x\n", " http://host/x", "http://host/\x00x", None, 5,
])
def test_check_follow_url_refuses_the_rest_with_a_plain_message(url):
    with pytest.raises(ValueError) as caught:
        contract.check_follow_url(url)
    message = str(caught.value)
    assert message.startswith("the follow URL")
    assert DASHES[0] not in message
