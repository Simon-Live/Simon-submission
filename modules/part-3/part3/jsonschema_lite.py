"""A small JSON Schema validator in the standard library (docs/specs/integration-contract.md, AC-C03).

It checks the draft 2020-12 keywords the files in `contracts/` use and nothing else, so a neighbour
does not need a schema package to check a file. Any validator reads the same schema files; a test
cross-checks this one against the `jsonschema` package when that is installed.

`validate(instance, schema)` returns `<json path>: <reason>` strings, empty when the instance is valid.
Booleans are not numbers; integers are numbers; a float with no fraction is an integer.
"""

import json
import re

SUPPORTED_KEYWORDS = frozenset({
    "type", "properties", "required", "additionalProperties", "patternProperties", "items", "prefixItems",
    "minItems", "maxItems", "enum", "const", "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum",
    "minLength", "maxLength", "pattern", "anyOf", "oneOf", "allOf", "$ref", "$defs",
})
ANNOTATION_KEYWORDS = frozenset({"$schema", "$id", "$comment", "title", "description", "default", "examples"})
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*\Z")
_SHOWN = 90


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_type(value, name):
    if name == "object":
        return isinstance(value, dict)
    if name == "array":
        return isinstance(value, list)
    if name == "string":
        return isinstance(value, str)
    if name == "boolean":
        return isinstance(value, bool)
    if name == "null":
        return value is None
    if name == "number":
        return _is_number(value)
    if name == "integer":
        return (isinstance(value, int) and not isinstance(value, bool)) or (
            isinstance(value, float) and value.is_integer())
    raise ValueError(f"unknown type {name!r} in schema")


def _type_name(value):
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    for name, kind in (("integer", int), ("number", float), ("string", str), ("array", list), ("object", dict)):
        if isinstance(value, kind):
            return name
    return type(value).__name__


def _equal(a, b):
    """JSON equality: true is not 1, 1 equals 1.0, containers compare element by element."""
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_equal(x, y) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_equal(a[k], b[k]) for k in a)
    if isinstance(a, (list, dict)) or isinstance(b, (list, dict)):
        return False
    return a == b


def _shown(value):
    text = json.dumps(value, ensure_ascii=False)
    return text if len(text) <= _SHOWN else text[:_SHOWN - 3] + "..."


def _key_path(path, key):
    return f"{path}.{key}" if _IDENTIFIER.match(key) else f"{path}[{json.dumps(key)}]"


class _Walker:
    def __init__(self, root):
        self.root = root

    def resolve(self, ref):
        if ref == "#":
            return self.root
        if not ref.startswith("#/"):
            raise ValueError(f"unsupported $ref {ref!r}: only #/... pointers are supported")
        node = self.root
        for token in ref[2:].split("/"):
            token = token.replace("~1", "/").replace("~0", "~")
            if isinstance(node, dict) and token in node:
                node = node[token]
            else:
                raise ValueError(f"cannot resolve $ref {ref!r}")
        return node

    def check(self, value, schema, path, out):
        if schema is True:
            return
        if schema is False:
            out.append(f"{path}: no value is allowed here")
            return
        if not isinstance(schema, dict):
            raise ValueError(f"a schema must be an object or a boolean (at {path})")
        if "$ref" in schema:
            self.check(value, self.resolve(schema["$ref"]), path, out)
        self._generic(value, schema, path, out)
        if _is_number(value):
            self._number(value, schema, path, out)
        elif isinstance(value, str):
            self._string(value, schema, path, out)
        elif isinstance(value, list):
            self._array(value, schema, path, out)
        elif isinstance(value, dict):
            self._object(value, schema, path, out)
        self._combinators(value, schema, path, out)

    def _generic(self, value, schema, path, out):
        if "type" in schema:
            names = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
            if not any(_is_type(value, n) for n in names):
                out.append(f"{path}: expected {' or '.join(names)}, got {_type_name(value)}")
        if "enum" in schema and not any(_equal(value, option) for option in schema["enum"]):
            out.append(f"{path}: {_shown(value)} is not one of {_shown(schema['enum'])}")
        if "const" in schema and not _equal(value, schema["const"]):
            out.append(f"{path}: expected {_shown(schema['const'])}, got {_shown(value)}")

    def _number(self, value, schema, path, out):
        if "minimum" in schema and value < schema["minimum"]:
            out.append(f"{path}: {value} is below the minimum {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            out.append(f"{path}: {value} is above the maximum {schema['maximum']}")
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            out.append(f"{path}: {value} must be above {schema['exclusiveMinimum']}")
        if "exclusiveMaximum" in schema and value >= schema["exclusiveMaximum"]:
            out.append(f"{path}: {value} must be below {schema['exclusiveMaximum']}")

    def _string(self, value, schema, path, out):
        if "minLength" in schema and len(value) < schema["minLength"]:
            out.append(f"{path}: shorter than {schema['minLength']} characters")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            out.append(f"{path}: longer than {schema['maxLength']} characters")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            out.append(f"{path}: {_shown(value)} does not match the pattern {schema['pattern']}")

    def _array(self, value, schema, path, out):
        if "minItems" in schema and len(value) < schema["minItems"]:
            out.append(f"{path}: expected at least {schema['minItems']} items, got {len(value)}")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            out.append(f"{path}: expected at most {schema['maxItems']} items, got {len(value)}")
        prefix = schema.get("prefixItems", [])
        for i, sub in enumerate(prefix[:len(value)]):
            self.check(value[i], sub, f"{path}[{i}]", out)
        if "items" in schema:
            for i in range(len(prefix), len(value)):
                self.check(value[i], schema["items"], f"{path}[{i}]", out)

    def _object(self, value, schema, path, out):
        for name in schema.get("required", []):
            if name not in value:
                out.append(f"{_key_path(path, name)}: missing required property")
        properties = schema.get("properties", {})
        patterns = schema.get("patternProperties", {})
        for key, item in value.items():
            matched = False
            if key in properties:
                matched = True
                self.check(item, properties[key], _key_path(path, key), out)
            for pattern, sub in patterns.items():
                if re.search(pattern, key):
                    matched = True
                    self.check(item, sub, _key_path(path, key), out)
            if not matched and "additionalProperties" in schema:
                self._additional(item, schema["additionalProperties"], _key_path(path, key), out)

    def _additional(self, item, rule, path, out):
        if rule is False:
            out.append(f"{path}: unexpected property")
        elif rule is not True:
            self.check(item, rule, path, out)

    def _combinators(self, value, schema, path, out):
        for sub in schema.get("allOf", []):
            self.check(value, sub, path, out)
        if "anyOf" in schema:
            results = self._alternatives(value, schema["anyOf"], path)
            if all(results):
                out.append(self._no_match(path, results))
        if "oneOf" in schema:
            results = self._alternatives(value, schema["oneOf"], path)
            passing = sum(1 for r in results if not r)
            if passing == 0:
                out.append(self._no_match(path, results))
            elif passing > 1:
                out.append(f"{path}: matches {passing} of the {len(results)} alternatives, expected exactly one")

    def _alternatives(self, value, alternatives, path):
        results = []
        for sub in alternatives:
            errors = []
            self.check(value, sub, path, errors)
            results.append(errors)
        return results

    @staticmethod
    def _no_match(path, results):
        closest = min(results, key=len)[0]
        return f"{path}: matches none of the {len(results)} alternatives (closest: {closest})"


def validate(instance, schema, *, root="$"):
    """Errors of `instance` against `schema` as `<json path>: <reason>` strings; empty when valid.

    `root` names the document in the paths (default `$`, so `$.frames[0].t_ms`). Raises ValueError
    for a malformed schema (an unresolvable `$ref`, an unknown type name), never for a bad instance.
    """
    out = []
    _Walker(schema).check(instance, schema, root, out)
    return out


def unsupported_keywords(schema):
    """`<path>: <keyword>` strings for schema keywords this validator would silently ignore.

    `x-` extension keys are annotations. A schema with an empty result is checked in full.
    """
    found = []
    _scan(schema, "#", found)
    return found


_SCHEMA_MAPS = ("properties", "patternProperties", "$defs")
_SCHEMA_LISTS = ("prefixItems", "anyOf", "oneOf", "allOf")
_SCHEMA_SINGLES = ("items", "additionalProperties")


def _scan(schema, path, found):
    if not isinstance(schema, dict):
        return
    for key, value in schema.items():
        known = key in SUPPORTED_KEYWORDS or key in ANNOTATION_KEYWORDS or key.startswith("x-")
        if not known:
            found.append(f"{path}: {key}")
        if key in _SCHEMA_MAPS and isinstance(value, dict):
            for name, sub in value.items():
                _scan(sub, f"{path}/{key}/{name}", found)
        elif key in _SCHEMA_LISTS and isinstance(value, list):
            for i, sub in enumerate(value):
                _scan(sub, f"{path}/{key}/{i}", found)
        elif key in _SCHEMA_SINGLES:
            _scan(value, f"{path}/{key}", found)
