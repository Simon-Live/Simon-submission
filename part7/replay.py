"""Serve Part 5's replay file after checking it against Part 5's `contracts/replay.schema.json` (ADR-0006).

Part 7 never computes a replay and keeps no copy of its schema: the check reads the schema file in the
Part 5 module and fails closed when the module does not ship it (ADR-0007). The checker covers the schema keywords such files use (no `jsonschema` import).
"""

from __future__ import annotations

import bisect
import json
from pathlib import Path
from typing import Any

from part7 import modules, skeleton2d

SCHEMA_REL = Path("contracts") / "replay.schema.json"


def schema_for(lock: modules.Modules | None = None, state: Path | str | None = None) -> dict[str, Any] | None:
    """Part 5's replay schema from its module, or None when the module does not ship it."""
    try:
        lk = lock or modules.load()
        path = lk.path("5") / SCHEMA_REL
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, KeyError):
        pass
    return None


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


def validate(doc: Any, lock: modules.Modules | None = None, state: Path | str | None = None) -> list[str]:
    """Return the problems of a replay document (empty when it is valid)."""
    schema = schema_for(lock, state)
    if schema is None:
        return ["replay: Part 5's contracts/replay.schema.json is missing (run make parts)"]
    problems: list[str] = []
    check(doc, schema, schema, "replay", problems)
    if not problems and isinstance(doc, dict):
        problems.extend(lengths_agree(doc))
    return problems


def read_valid(
    path: Path | str, lock: modules.Modules | None = None, state: Path | str | None = None
) -> tuple[bytes | None, list[str]]:
    """Read a replay file; return `(bytes, [])` when valid, else `(None, problems)`."""
    raw = Path(path).read_bytes()
    try:
        doc = json.loads(raw)
    except ValueError:
        return (None, ["replay: not valid JSON"])
    problems = validate(doc, lock, state)
    return (None, problems) if problems else (raw, [])


def follower_unseen(doc: dict[str, Any], part2_dir: Path, person_id: str | None) -> list[list[int]] | None:
    """Per follower frame of `doc`, the indices (in `doc["joints"]`) of the joints Part 2 marked unseen (conf at or
    below `skeleton2d.UNSEEN_CONF`) in the nearest `pose3d.json` frame by time; None when it cannot be told (TICKET-376).
    Part 5's replay drops the mark, so the 3D stick figure would draw those joints at guessed places. Both files count
    seconds from the clip start (`follower_t[0]` and the first `t_ms` are both near 0); a frame where `person_id` is
    absent marks nothing."""
    pose = skeleton2d.load_json(part2_dir / "pose3d.json")
    names, times = doc.get("joints"), doc.get("follower_t")
    frames = [f for f in (pose.get("frames") if isinstance(pose, dict) else None) or []
              if isinstance(f, dict) and isinstance(f.get("t_ms"), (int, float))]
    count = len(doc.get("follower") or [])
    if not frames or not isinstance(names, list) or not count:
        return None
    if not (isinstance(times, list) and len(times) == count):
        fps = doc.get("fps")
        times = [i / fps for i in range(count)] if isinstance(fps, (int, float)) and fps > 0 else None
    if times is None:
        return None
    frames.sort(key=lambda f: f["t_ms"])
    stamps = [f["t_ms"] / 1000.0 for f in frames]
    marks = []
    for f in frames:
        who = skeleton2d.pick_person(f.get("people"), person_id, strict=person_id is not None)
        joints = (who or {}).get("joints") or {}
        marks.append([i for i, n in enumerate(names)
                      if isinstance(joints.get(n), dict) and skeleton2d.is_unseen(joints[n].get("conf"))])
    out = []
    for t in times:
        k = bisect.bisect_left(stamps, t)
        if k > 0 and (k == len(stamps) or t - stamps[k - 1] <= stamps[k] - t):
            k -= 1
        out.append(list(marks[k]))
    return out


def with_follower_unseen(raw: bytes, part2_dir: Path, person_id: str | None) -> bytes:
    """`raw` (a valid replay) with `follower_unseen` added, or `raw` itself when Part 2's folder cannot say."""
    try:
        doc = json.loads(raw)
        marks = follower_unseen(doc, part2_dir, person_id)
    except (ValueError, AttributeError, TypeError):
        return raw
    if marks is None or not any(marks):
        return raw
    doc["follower_unseen"] = marks
    return json.dumps(doc, separators=(",", ":")).encode("utf-8")
