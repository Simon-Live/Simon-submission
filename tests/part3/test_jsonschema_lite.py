"""The stdlib JSON Schema validator: each keyword, and agreement with `jsonschema` (AC-C03)."""

import copy
import json

import pytest

import contractkit
from conftest import ROOT
from part3 import contract, jsonschema_lite
from part3.jsonschema_lite import unsupported_keywords, validate

GOLDEN_SKELETONS = sorted((ROOT / "fixtures" / "output").rglob("skeleton.json"))


def ok(instance, schema):
    return validate(instance, schema) == []


# --- keywords ----------------------------------------------------------------------------------

def test_type_booleans_are_not_numbers_and_integers_are_numbers():
    assert not ok(True, {"type": "number"})
    assert not ok(True, {"type": "integer"})
    assert ok(3, {"type": "number"})
    assert ok(3.5, {"type": "number"})
    assert ok(2.0, {"type": "integer"})
    assert not ok(2.5, {"type": "integer"})
    assert ok(True, {"type": "boolean"})
    assert ok(None, {"type": "null"})
    assert not ok("1", {"type": "number"})


def test_type_list_accepts_any_listed_type():
    schema = {"type": ["integer", "string"]}
    assert ok(1, schema) and ok("a", schema)
    assert validate(None, schema) == ["$: expected integer or string, got null"]


def test_unknown_type_name_is_a_schema_error():
    with pytest.raises(ValueError, match="unknown type"):
        validate(1, {"type": "float"})


def test_properties_required_and_paths():
    schema = {"type": "object", "required": ["a", "b"], "properties": {"a": {"type": "integer"}}}
    assert ok({"a": 1, "b": None}, schema)
    errors = validate({"a": "x"}, schema, root="doc")
    assert sorted(errors) == ["doc.a: expected integer, got string", "doc.b: missing required property"]


def test_paths_index_lists_and_quote_odd_keys():
    schema = {"type": "array", "items": {"type": "object", "properties": {"a b": {"type": "integer"}}}}
    assert validate([{"a b": 1}, {"a b": "x"}], schema) == ['$[1]["a b"]: expected integer, got string']


def test_additional_properties_false_and_schema():
    closed = {"properties": {"a": {}}, "additionalProperties": False}
    assert validate({"a": 1, "z": 2}, closed) == ["$.z: unexpected property"]
    typed = {"properties": {"a": {}}, "additionalProperties": {"type": "integer"}}
    assert ok({"a": "x", "z": 2}, typed)
    assert validate({"z": "x"}, typed) == ["$.z: expected integer, got string"]
    assert ok({"anything": 1}, {"properties": {}, "additionalProperties": True})


def test_pattern_properties_exempt_matching_keys_from_additional():
    schema = {"patternProperties": {"^x-": {"type": "integer"}}, "additionalProperties": False}
    assert ok({"x-a": 1}, schema)
    assert validate({"x-a": "s"}, schema) == ["$.x-a: expected integer, got string"]
    assert validate({"y": 1}, schema) == ["$.y: unexpected property"]


def test_items_and_item_counts():
    schema = {"type": "array", "items": {"type": "integer"}, "minItems": 1, "maxItems": 2}
    assert ok([1], schema)
    assert validate([], schema) == ["$: expected at least 1 items, got 0"]
    assert validate([1, 2, 3], schema) == ["$: expected at most 2 items, got 3"]
    assert validate([1, "a"], {"items": {"type": "integer"}}) == ["$[1]: expected integer, got string"]


def test_prefix_items_then_items_for_the_rest():
    schema = {"prefixItems": [{"type": "integer"}, {"type": "string"}], "items": {"type": "boolean"}}
    assert ok([1, "a", True, False], schema)
    assert validate([1, 2, 3], schema) == ["$[1]: expected string, got integer", "$[2]: expected boolean, got integer"]
    assert ok([1], schema)  # shorter than the prefix is fine without minItems


def test_enum_and_const_tell_booleans_from_numbers():
    assert ok("a", {"enum": ["a", "b"]})
    assert not ok(1, {"enum": [True]})
    assert not ok(True, {"enum": [1]})
    assert ok(1.0, {"const": 1})
    assert not ok(False, {"const": 0})
    assert ok({"a": [1, {"b": None}]}, {"const": {"a": [1, {"b": None}]}})
    assert not ok({"a": [1]}, {"const": {"a": [1, 2]}})
    assert validate("z", {"enum": ["a", "b"]}) == ['$: "z" is not one of ["a", "b"]']
    assert validate(2, {"const": 1}) == ["$: expected 1, got 2"]


def test_numeric_limits():
    schema = {"minimum": 0, "maximum": 1, "exclusiveMinimum": -1, "exclusiveMaximum": 2}
    assert ok(0, schema) and ok(1, schema)
    assert validate(-0.5, schema) == ["$: -0.5 is below the minimum 0"]
    assert validate(1.5, schema) == ["$: 1.5 is above the maximum 1"]
    assert validate(-1, {"exclusiveMinimum": -1}) == ["$: -1 must be above -1"]
    assert validate(2, {"exclusiveMaximum": 2}) == ["$: 2 must be below 2"]
    assert ok("text", {"minimum": 5})  # limits only apply to numbers
    assert ok(True, {"minimum": 5})


def test_string_limits_and_pattern():
    assert validate("", {"minLength": 1}) == ["$: shorter than 1 characters"]
    assert validate("abc", {"maxLength": 2}) == ["$: longer than 2 characters"]
    assert ok("ab" * 32, {"pattern": "^[a-b]{64}$"})
    assert validate("zz", {"pattern": "^a"}) == ['$: "zz" does not match the pattern ^a']
    assert ok(5, {"minLength": 3, "pattern": "^a"})


def test_combinators():
    any_of = {"anyOf": [{"type": "integer"}, {"type": "string"}]}
    assert ok(1, any_of) and ok("a", any_of)
    assert validate(None, any_of)[0].startswith("$: matches none of the 2 alternatives")
    one_of = {"oneOf": [{"type": "integer"}, {"minimum": 0}]}
    assert ok("a", {"oneOf": [{"type": "integer"}, {"type": "string"}]})
    assert validate(1, one_of) == ["$: matches 2 of the 2 alternatives, expected exactly one"]
    assert validate(None, {"oneOf": [{"type": "integer"}, {"type": "string"}]})[0].startswith("$: matches none")
    all_of = {"allOf": [{"type": "integer"}, {"minimum": 3}]}
    assert ok(3, all_of)
    assert validate(1, all_of) == ["$: 1 is below the minimum 3"]


def test_required_alternatives_inside_one_of():
    schema = {"type": "object", "oneOf": [{"required": ["file"]}, {"required": ["skipped"]}]}
    assert ok({"file": "a"}, schema) and ok({"skipped": "x"}, schema)
    assert not ok({}, schema)
    assert not ok({"file": "a", "skipped": "x"}, schema)


def test_ref_to_defs_and_recursion_through_properties():
    schema = {"$defs": {"n": {"type": "integer"}, "pair": {"type": "array", "items": {"$ref": "#/$defs/n"}}},
              "properties": {"p": {"$ref": "#/$defs/pair"}}}
    assert ok({"p": [1, 2]}, schema)
    assert validate({"p": [1, "x"]}, schema) == ["$.p[1]: expected integer, got string"]
    with pytest.raises(ValueError, match="cannot resolve"):
        validate({"p": 1}, {"properties": {"p": {"$ref": "#/$defs/missing"}}})
    with pytest.raises(ValueError, match="only #/"):
        validate(1, {"$ref": "http://example.com/x.json"})


def test_boolean_schemas():
    assert ok(1, True)
    assert validate(1, False) == ["$: no value is allowed here"]
    assert ok([1], {"items": True})


def test_annotations_and_extension_keywords_are_ignored():
    schema = {"$schema": "x", "$id": "y", "title": "t", "description": "d", "x-simon-version": "v", "type": "integer"}
    assert ok(1, schema)


def test_unsupported_keywords_are_named_not_hidden():
    schema = {"properties": {"a": {"format": "date", "type": "string"}}, "$defs": {"b": {"not": {}}},
              "anyOf": [{"uniqueItems": True}], "x-ok": 1, "description": "d"}
    assert sorted(unsupported_keywords(schema)) == [
        "#/$defs/b: not", "#/anyOf/0: uniqueItems", "#/properties/a: format"]
    assert unsupported_keywords({"properties": {"format": {"type": "string"}}}) == []  # a property named format


# --- the contract's own schemas ----------------------------------------------------------------

def test_every_contract_schema_uses_only_supported_keywords():
    for name, info in contract.SCHEMAS.items():
        assert unsupported_keywords(info["schema"]) == [], name


def test_golden_files_validate_without_any_package():
    schema = contract.SCHEMAS["skeleton"]["schema"]
    assert GOLDEN_SKELETONS, "no golden skeleton.json found under fixtures/output"
    for path in GOLDEN_SKELETONS:
        assert validate(json.loads(path.read_text()), schema, root="skeleton") == [], path


def test_mutated_documents_fail_without_any_package():
    for name, doc in contractkit.every_kind().items():
        schema = contract.SCHEMAS[name]["schema"]
        assert validate(doc, schema) == [], name
        broken = copy.deepcopy(doc)
        field = contract.SCHEMAS[name]["version_field"]
        if field:
            broken[field] = "bogus"
        else:
            broken.pop("people" if name == "keyframes-part1" else "frames")
        assert validate(broken, schema), name


# --- AC-C03: agreement with the jsonschema package ---------------------------------------------

def _nodes(doc, path=(), depth=0):
    yield path
    if isinstance(doc, dict):
        for key in (list(doc) if depth < 4 else list(doc)[:3]):
            yield from _nodes(doc[key], path + (key,), depth + 1)
    elif isinstance(doc, list):
        for i in range(min(len(doc), 2)):
            yield from _nodes(doc[i], path + (i,), depth + 1)


def _swap(value):
    return {dict: "x", list: {}, str: 1, bool: "x", type(None): []}.get(type(value), "x")


def _variants(value):
    """Replacement values that should break a slot: wrong type, wrong value, extra content."""
    out = [_swap(value)]
    if isinstance(value, bool):
        out.append(not value)
    elif isinstance(value, (int, float)):
        out += [True, value + 1e9, -abs(value) - 1e9]
    elif isinstance(value, str):
        out.append("bogus")
    elif isinstance(value, dict):
        out.append({**value, "zz_extra": 1})
    elif isinstance(value, list):
        out.append(value + [1])
    return out


def mutants(doc):
    """Copies of `doc` with one field deleted, retyped or given a wrong value (bounded, deterministic)."""
    for path in _nodes(doc):
        if not path:
            continue
        for i, value in enumerate([None] + _variants(_get(doc, path))):
            clone = copy.deepcopy(doc)
            parent = _get(clone, path[:-1])
            if i == 0:
                if not isinstance(parent, dict):
                    continue
                del parent[path[-1]]
            else:
                parent[path[-1]] = value
            yield f"{path} variant {i}", clone


def _get(doc, path):
    for step in path:
        doc = doc[step]
    return doc


def _trim(doc):
    """A copy with at most two frames and two keys, so one mutant is cheap to copy and check."""
    doc = copy.deepcopy(doc)
    for field in ("frames", "keyframes"):
        if isinstance(doc.get(field), list):
            doc[field] = doc[field][:2]
    return doc


@pytest.mark.parametrize("name", sorted(contract.SCHEMAS))
def test_agrees_with_jsonschema_on_valid_and_mutated_documents(name):
    jsonschema = pytest.importorskip("jsonschema")
    schema = contract.SCHEMAS[name]["schema"]
    reference = jsonschema.Draft202012Validator(schema)
    doc = _trim(contractkit.every_kind()[name])
    assert validate(doc, schema) == [] and not list(reference.iter_errors(doc))
    invalid_in_both = 0
    for label, clone in mutants(doc):
        ours, theirs = bool(validate(clone, schema)), bool(list(reference.iter_errors(clone)))
        assert ours == theirs, f"{name}: {label}: jsonschema_lite says {ours}, jsonschema says {theirs}"
        invalid_in_both += ours
    assert invalid_in_both > 10, f"{name}: too few mutants broke the document to be a test"


def test_agrees_with_jsonschema_on_every_golden_skeleton():
    jsonschema = pytest.importorskip("jsonschema")
    schema = contract.SCHEMAS["skeleton"]["schema"]
    reference = jsonschema.Draft202012Validator(schema)
    for path in GOLDEN_SKELETONS:
        doc = json.loads(path.read_text())
        assert validate(doc, schema) == [] and not list(reference.iter_errors(doc)), path
        doc["frames"][3]["people"][0]["joints"]["nose"]["conf"] = 2
        assert validate(doc, schema) and list(reference.iter_errors(doc)), path


def test_agrees_with_jsonschema_on_the_pose3d_fixtures():
    jsonschema = pytest.importorskip("jsonschema")
    schema = contract.SCHEMAS["pose3d"]["schema"]
    reference = jsonschema.Draft202012Validator(schema)
    paths = sorted((ROOT / "fixtures" / "input").rglob("pose3d.json"))
    assert paths
    for path in paths:
        doc = json.loads(path.read_text())
        assert validate(doc, schema) == [] and not list(reference.iter_errors(doc)), path


def test_module_is_stdlib_only():
    source = (ROOT / "part3" / "jsonschema_lite.py").read_text()
    imports = {line.split()[1].split(".")[0] for line in source.splitlines() if line.startswith(("import ", "from "))}
    assert imports <= {"json", "re"}, imports
    assert jsonschema_lite.SUPPORTED_KEYWORDS.isdisjoint(jsonschema_lite.ANNOTATION_KEYWORDS)
