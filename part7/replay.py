"""Serve Part 5's replay file after checking it against Part 5's `contracts/replay.schema.json` (ADR-0006).

Part 7 never computes a replay. The check uses the schema file in the pinned Part 5 clone; a pin that
does not ship the file yet is checked against `BUILTIN_SCHEMA`, the fields of `simon.replay.v1` as
`journey.md` lists them. The checker covers the schema keywords such files use (no `jsonschema` import).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from part7 import pins

SCHEMA_REL = Path("contracts") / "replay.schema.json"
_NUMBER_LIST = {"type": "array", "items": {"type": "number"}}
_POINT = {"type": "array", "minItems": 3, "maxItems": 3, "items": {"type": "number"}}
_FRAMES = {"type": "array", "minItems": 1, "items": {"type": "array", "items": _POINT}}
BUILTIN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": [
        "format", "fps", "joints", "bones", "expected", "follower",
        "expected_t", "follower_t", "exp_to_fol", "coordinate_frame",
    ],
    "properties": {
        "format": {"const": "simon.replay.v1"},
        "fps": {"type": "number", "minimum": 1},
        "joints": {"type": "array", "minItems": 1, "items": {"type": "string"}},
        "bones": {"type": "array", "items": {"type": "array", "minItems": 2, "maxItems": 2, "items": {"type": "integer", "minimum": 0}}},
        "expected": _FRAMES,
        "follower": _FRAMES,
        "expected_t": _NUMBER_LIST,
        "follower_t": _NUMBER_LIST,
        "exp_to_fol": {"type": "array", "items": {"type": "integer", "minimum": 0}},
        "coordinate_frame": {"type": "object"},
    },
}


def schema_for(lock: pins.Lock | None = None, state: Path | str | None = None) -> dict[str, Any]:
    """Return Part 5's schema from the pinned clone, or `BUILTIN_SCHEMA` when the pin has none."""
    try:
        lk = lock or pins.load()
        path = lk.path("5", state=state) / SCHEMA_REL
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, KeyError):
        pass
    return BUILTIN_SCHEMA


def _type_ok(value: Any, name: str) -> bool:
    if name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    py = {"object": dict, "array": list, "string": str, "boolean": bool}.get(name)
    if name == "null":
        return value is None
    return py is not None and isinstance(value, py)


def _resolve(ref: str, root: dict[str, Any]) -> dict[str, Any]:
    node: Any = root
    for part in ref.lstrip("#/").split("/"):
        node = node[part]
    return node


def check(value: Any, schema: dict[str, Any], root: dict[str, Any], where: str, out: list[str]) -> None:
    """Append one message per violation of `schema` by `value` to `out` (stops at 20 messages)."""
    if len(out) >= 20:
        return
    if "$ref" in schema:
        schema = _resolve(schema["$ref"], root)
    wanted = schema.get("type")
    if wanted is not None:
        names = wanted if isinstance(wanted, list) else [wanted]
        if not any(_type_ok(value, n) for n in names):
            out.append(f"{where}: must be {' or '.join(names)}")
            return
    if "const" in schema and value != schema["const"]:
        out.append(f"{where}: must be {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        out.append(f"{where}: not one of the allowed values")
    if _type_ok(value, "number"):
        if "minimum" in schema and value < schema["minimum"]:
            out.append(f"{where}: below {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            out.append(f"{where}: above {schema['maximum']}")
    if isinstance(value, dict):
        for name in schema.get("required", []):
            if name not in value:
                out.append(f"{where}.{name}: is required")
        for name, sub in schema.get("properties", {}).items():
            if name in value:
                check(value[name], sub, root, f"{where}.{name}", out)
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            out.append(f"{where}: fewer than {schema['minItems']} items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            out.append(f"{where}: more than {schema['maxItems']} items")
        if isinstance(schema.get("items"), dict):
            for index, item in enumerate(value[:400]):
                check(item, schema["items"], root, f"{where}[{index}]", out)


def lengths_agree(doc: dict[str, Any]) -> list[str]:
    """Cross-field rules the compare view relies on: per-frame times match frames, the map fits the follower."""
    problems: list[str] = []
    if len(doc.get("expected_t", [])) != len(doc.get("expected", [])):
        problems.append("expected_t: must have one time per expected frame")
    if len(doc.get("follower_t", [])) != len(doc.get("follower", [])):
        problems.append("follower_t: must have one time per follower frame")
    if len(doc.get("exp_to_fol", [])) != len(doc.get("expected", [])):
        problems.append("exp_to_fol: must have one entry per expected frame")
    follower_count = len(doc.get("follower", []))
    if any(isinstance(i, int) and i >= follower_count for i in doc.get("exp_to_fol", [])):
        problems.append("exp_to_fol: points past the last follower frame")
    return problems


def validate(doc: Any, lock: pins.Lock | None = None, state: Path | str | None = None) -> list[str]:
    """Return the problems of a replay document (empty when it is valid)."""
    schema = schema_for(lock, state)
    problems: list[str] = []
    check(doc, schema, schema, "replay", problems)
    if not problems and isinstance(doc, dict):
        problems.extend(lengths_agree(doc))
    return problems


def read_valid(
    path: Path | str, lock: pins.Lock | None = None, state: Path | str | None = None
) -> tuple[bytes | None, list[str]]:
    """Read a replay file; return `(bytes, [])` when valid, else `(None, problems)`."""
    raw = Path(path).read_bytes()
    try:
        doc = json.loads(raw)
    except ValueError:
        return (None, ["replay: not valid JSON"])
    problems = validate(doc, lock, state)
    return (None, problems) if problems else (raw, [])
