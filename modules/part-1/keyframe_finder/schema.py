"""Shared keyframes.json helpers.

FORMAT is the version id every keyframes.json carries. The published contract is
contracts/keyframes.schema.json; validate() checks a document against it with
the standard library, so no schema package is needed.
"""

import json
from pathlib import Path

FORMAT = "simon.keyframes/part1"
SCHEMA_PATH = Path(__file__).resolve().parents[1] / "contracts" / "keyframes.schema.json"


def frame_ms(frame, fps):
    return int(round(float(frame) * 1000.0 / float(fps)))


def dump_json(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")


def load_schema():
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def validate(document, schema=None):
    """Return the contract errors in document, as 'path: problem' lines. Empty means valid."""
    schema = load_schema() if schema is None else schema
    errors = []
    _check(document, schema, schema, "keyframes.json", errors)
    return errors


_TYPES = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
}


def _check(value, rule, root, where, errors):
    if "$ref" in rule:
        rule = root["$defs"][rule["$ref"].rsplit("/", 1)[-1]]
    kinds = rule.get("type")
    if kinds is not None:
        kinds = [kinds] if isinstance(kinds, str) else kinds
        if not any(_TYPES[kind](value) for kind in kinds):
            errors.append(f"{where}: expected {' or '.join(kinds)}, got {json.dumps(value)[:40]}")
            return
    if "const" in rule and value != rule["const"]:
        errors.append(f"{where}: must be {json.dumps(rule['const'])}")
    if "enum" in rule and value not in rule["enum"]:
        errors.append(f"{where}: must be one of {', '.join(map(json.dumps, rule['enum']))}")
    if _TYPES["number"](value):
        if "minimum" in rule and value < rule["minimum"]:
            errors.append(f"{where}: must be at least {rule['minimum']}")
        if "exclusiveMinimum" in rule and value <= rule["exclusiveMinimum"]:
            errors.append(f"{where}: must be above {rule['exclusiveMinimum']}")
    if isinstance(value, str) and len(value) < rule.get("minLength", 0):
        errors.append(f"{where}: must not be empty")
    if isinstance(value, dict):
        for key in rule.get("required", []):
            if key not in value:
                errors.append(f"{where}: missing {key}")
        for key, child in rule.get("properties", {}).items():
            if key in value:
                _check(value[key], child, root, f"{where}.{key}", errors)
    if isinstance(value, list) and "items" in rule:
        for index, item in enumerate(value):
            _check(item, rule["items"], root, f"{where}[{index}]", errors)
