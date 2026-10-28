"""A small JSON Schema 2020-12 checker for the contract files (docs/specs/catalog-contract.md AC-C15).

It supports only the keywords the files under `contracts/` use, and refuses any other validating
keyword, so a schema can never silently ask for a check this module does not make:

    type (one name or a list; integer and number never match a boolean), enum, const, required,
    properties, additionalProperties (true, false or a schema), pattern, minimum, maximum,
    exclusiveMinimum, minLength, maxLength, items, minItems, maxItems, anyOf, oneOf, and $ref to
    "#/$defs/<name>" (or "#" for the whole schema).

Two deliberate choices. "integer" means an integer literal, so 5.0 is a number and not an integer
(the standard also accepts 5.0; Part 6's validator does not). A pattern that ends in "$" ends the
text exactly, as it does in the standard's regular expressions, so a trailing newline fails it.

`errors(instance, schema)` returns "path: reason" strings, empty when the instance is valid. The
path is "$" for the instance itself, else keys and indexes such as `provenance.skeleton.part` or
`frames[2].people`.
"""
from __future__ import annotations

import math
import re

# Annotation or structure keywords that never make a check.
IGNORED = frozenset({"$schema", "$id", "$defs", "$comment", "title", "description", "default",
                     "examples"})
CHECKED = frozenset({"type", "enum", "const", "required", "properties", "additionalProperties",
                     "pattern", "minimum", "maximum", "exclusiveMinimum", "minLength", "maxLength",
                     "items", "minItems", "maxItems", "anyOf", "oneOf", "$ref"})
TYPES = ("null", "boolean", "object", "array", "number", "integer", "string")
REF_PREFIX = "#/$defs/"


class SchemaError(ValueError):
    """The schema uses something this checker does not support, or a bad $ref."""


def _is_type(value, name):
    if name == "null":
        return value is None
    if name == "boolean":
        return isinstance(value, bool)
    if name == "object":
        return isinstance(value, dict)
    if name == "array":
        return isinstance(value, list)
    if name == "string":
        return isinstance(value, str)
    if name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if name == "number":
        return (isinstance(value, (int, float)) and not isinstance(value, bool)
                and math.isfinite(value))
    raise SchemaError(f"unknown type {name!r}")


def _same(a, b):
    """JSON equality: true and 1 differ, lists and objects compare deeply."""
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_same(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    if isinstance(a, (dict, list)) or isinstance(b, (dict, list)):
        return False
    return a == b


def _regex(pattern):
    """Compile a schema pattern; a final "$" means the end of the text, not before a newline."""
    if pattern.endswith("$") and not pattern.endswith("\\$"):
        pattern = pattern[:-1] + r"\Z"
    return re.compile(pattern)


def _join(path, key):
    return f"{path}.{key}" if path else str(key)


def _label(path):
    return path or "$"


def _resolve(ref, root):
    if ref == "#":
        return root
    if not ref.startswith(REF_PREFIX):
        raise SchemaError(f"unsupported $ref {ref!r}")
    target = root.get("$defs", {}).get(ref[len(REF_PREFIX):])
    if not isinstance(target, dict):
        raise SchemaError(f"$ref {ref!r} names no definition")
    return target


def _type_errors(value, schema, path):
    names = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
    if any(_is_type(value, n) for n in names):
        return []
    return [f"{_label(path)}: must be {' or '.join(names)}"]


def _number_errors(value, schema, path):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return []
    out = []
    if "minimum" in schema and value < schema["minimum"]:
        out.append(f"{_label(path)}: must be at least {schema['minimum']}")
    if "maximum" in schema and value > schema["maximum"]:
        out.append(f"{_label(path)}: must be at most {schema['maximum']}")
    if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
        out.append(f"{_label(path)}: must be above {schema['exclusiveMinimum']}")
    return out


def _string_errors(value, schema, path):
    if not isinstance(value, str):
        return []
    out = []
    if "minLength" in schema and len(value) < schema["minLength"]:
        out.append(f"{_label(path)}: must have at least {schema['minLength']} characters")
    if "maxLength" in schema and len(value) > schema["maxLength"]:
        out.append(f"{_label(path)}: must have at most {schema['maxLength']} characters")
    if "pattern" in schema and not _regex(schema["pattern"]).search(value):
        out.append(f"{_label(path)}: does not match {schema['pattern']}")
    return out


def _object_errors(value, schema, path, root):
    if not isinstance(value, dict):
        return []
    out = [f"{_join(path, key)}: is required" for key in schema.get("required", ())
           if key not in value]
    props = schema.get("properties", {})
    for key, sub in props.items():
        if key in value:
            out += _check(value[key], sub, _join(path, key), root)
    extra = schema.get("additionalProperties", True)
    for key in value:
        if key in props or extra is True:
            continue
        if extra is False:
            out.append(f"{_join(path, key)}: is not allowed")
        else:
            out += _check(value[key], extra, _join(path, key), root)
    return out


def _array_errors(value, schema, path, root):
    if not isinstance(value, list):
        return []
    out = []
    if "minItems" in schema and len(value) < schema["minItems"]:
        out.append(f"{_label(path)}: must have at least {schema['minItems']} items")
    if "maxItems" in schema and len(value) > schema["maxItems"]:
        out.append(f"{_label(path)}: must have at most {schema['maxItems']} items")
    if "items" in schema:
        for i, item in enumerate(value):
            out += _check(item, schema["items"], f"{path}[{i}]", root)
    return out


def _combiner_errors(value, schema, path, root):
    out = []
    for word in ("anyOf", "oneOf"):
        if word not in schema:
            continue
        branches = [_check(value, sub, path, root) for sub in schema[word]]
        matched = sum(1 for b in branches if not b)
        if matched == 0:
            own = f"{_label(path)}: "
            first = "; ".join(b[0].removeprefix(own) for b in branches if b)
            out.append(f"{_label(path)}: matches none of the allowed forms ({first})")
        elif word == "oneOf" and matched > 1:
            out.append(f"{_label(path)}: matches more than one of the allowed forms")
    return out


def _check(value, schema, path, root):
    if schema is True:
        return []
    if schema is False:
        return [f"{_label(path)}: is not allowed"]
    if not isinstance(schema, dict):
        raise SchemaError(f"schema at {_label(path)} is not an object")
    unknown = set(schema) - CHECKED - IGNORED
    if unknown:
        raise SchemaError(f"unsupported keyword {sorted(unknown)[0]!r}")
    out = []
    if "$ref" in schema:
        out += _check(value, _resolve(schema["$ref"], root), path, root)
    if "type" in schema:
        out += _type_errors(value, schema, path)
    if "const" in schema and not _same(value, schema["const"]):
        out.append(f"{_label(path)}: must be {schema['const']!r}")
    if "enum" in schema and not any(_same(value, option) for option in schema["enum"]):
        out.append(f"{_label(path)}: must be one of {', '.join(map(str, schema['enum']))}")
    return (out + _number_errors(value, schema, path) + _string_errors(value, schema, path)
            + _object_errors(value, schema, path, root) + _array_errors(value, schema, path, root)
            + _combiner_errors(value, schema, path, root))


def errors(instance, schema):
    """Every "path: reason" the instance breaks, in schema order; [] when it is valid."""
    return _check(instance, schema, "", schema)
