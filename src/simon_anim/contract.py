"""Part 4's input and output contracts as JSON Schema (draft 2020-12).

The schemas are built here from the rig in `skeleton.py`, so the joint lists
cannot drift from the code. `contracts/*.schema.json` is written from this
module (`make contracts`) and `make check-4` fails when the files differ.

The animator validates both inputs against these schemas before it reads
them, so a file a schema rejects is never animated. Rules a schema cannot
state (key times, index order, zero quaternions, the half-turn step) are
listed under `x-rules` and enforced in `interpolate.py`.

The validator below covers the keywords these schemas use and refuses any
other keyword, so a schema edit cannot be silently ignored. Standard library
only.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .skeleton import (
    CANONICAL_JOINTS,
    COORDINATE_FRAME,
    FK_ORDER,
    LENGTH_BONES,
    REST_OFFSETS,
    ROTATED_JOINTS,
)

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS_DIR = ROOT / "contracts"
DRAFT = "https://json-schema.org/draft/2020-12/schema"
REPO_URL = "https://github.com/moalborati/simon-part-4-animate-keyframes"

KEYFRAMES_FORMAT = "simon.keyframes.v1"
SKELETON_FORMAT = "simon.skeleton.v1"
ANIMATION_FORMAT = "simon.animation.v1"
# Names the part that wrote animation.json, so a reader can tell it from a copy or a stand-in (A-P4-06).
ANIMATION_PRODUCER = "part4"
FPS = 30

FILES = {
    "keyframes": "keyframes.schema.json",
    "skeleton": "skeleton.schema.json",
    "animation": "animation.schema.json",
}

_VEC3 = {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3}
_QUAT = {
    "type": "array",
    "items": {"type": "number"},
    "minItems": 4,
    "maxItems": 4,
    "description": "Local rotation (x, y, z, w). Normalized on read; a norm under 1e-8 is rejected.",
}
_CONF_VALUE = {"type": "number", "minimum": 0, "maximum": 1}
_CONF_PROPERTIES = {name: _CONF_VALUE for name in CANONICAL_JOINTS}
_JOINT_POSITION = {
    "anyOf": [
        {"$ref": "#/$defs/vec3"},
        {
            "type": "object",
            "required": ["x", "y", "z"],
            "properties": {
                "x": {"type": "number"},
                "y": {"type": "number"},
                "z": {"type": "number"},
                "conf": {"type": "number"},
            },
        },
    ],
    "description": "Metres in the body frame, as [x, y, z] or Part 3's {x, y, z, conf}.",
}


def _header(kind: str, title: str, description: str, direction: str, producer: str, consumers: list[str]) -> dict:
    return {
        "$schema": DRAFT,
        "$id": f"{REPO_URL}/contracts/{FILES[kind]}",
        "title": title,
        "description": description,
        "x-simon-version": {
            "keyframes": KEYFRAMES_FORMAT,
            "skeleton": SKELETON_FORMAT,
            "animation": ANIMATION_FORMAT,
        }[kind],
        "x-direction": direction,
        "x-producer": producer,
        "x-consumers": consumers,
        "x-version-field": "format",
    }


def keyframes_schema() -> dict:
    schema = _header(
        "keyframes",
        "keyframes.json read by Part 4",
        "The 30 fps timeline Part 4 animates: which frame indices are keys. Part 3 writes it with "
        "--view part4 --keyframes-out. Part 1's own keyframes.json (video clock, per person) is not "
        "this file; Part 3 maps it onto this timeline. Extra keys are allowed and ignored.",
        "input",
        "Part 3 (--keyframes-out) or a hand-authored fixture",
        ["Part 4"],
    )
    schema["x-rules"] = [
        "frame_count equals round(duration_s * 30) + 1",
        "keyframes[].index strictly increases and lies in 0 .. frame_count - 1",
        "keyframes[].t equals index / 30 within one microsecond",
        "the key indices equal the keyframes[].index list of the skeleton.json beside this file",
    ]
    schema.update(
        {
            "type": "object",
            "required": ["format", "fps", "duration_s", "frame_count", "keyframes"],
            "properties": {
                "format": {"const": KEYFRAMES_FORMAT},
                "fps": {"const": FPS},
                "duration_s": {"type": "number", "minimum": 0},
                "frame_count": {"type": "integer", "minimum": 1},
                "set": {"type": "string"},
                "movement": {"type": "string"},
                "keyframes": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "required": ["index", "t"],
                        "properties": {
                            "index": {"type": "integer", "minimum": 0},
                            "t": {"type": "number", "minimum": 0, "description": "Seconds, index / 30."},
                            "name": {"type": "string"},
                        },
                    },
                },
            },
        }
    )
    return schema


def _rest_offsets_schema() -> dict:
    return {
        "type": "object",
        "required": list(FK_ORDER),
        "properties": {
            joint: {
                "type": "object",
                "required": ["parent", "offset"],
                "properties": {"parent": {"const": REST_OFFSETS[joint][0]}, "offset": {"$ref": "#/$defs/vec3"}},
            }
            for joint in FK_ORDER
        },
        "description": "Rest offset of each joint in its parent's frame, metres. The parent is fixed by "
        "the standard rig; the length and direction come from the file. Extra joints are ignored.",
    }


def skeleton_schema() -> dict:
    schema = _header(
        "skeleton",
        "skeleton.json read by Part 4",
        "Part 3's body and the pose at each key. Part 3 writes it with --view part4. Part 4 reads "
        "rest_offsets_m and keyframes[].local_rotations; keyframes[].joints is the forward kinematics "
        "of those rotations and make check-4 holds it to 1 mm. Extra keys are allowed and ignored.",
        "input",
        "Part 3 (--view part4)",
        ["Part 4", "Part 5", "Part 6"],
    )
    schema["x-rules"] = [
        "keyframes[].t equals index / 30 within one microsecond",
        "keyframes[].index equals the key list of the keyframes.json beside this file",
        "no rest offset has zero length",
        "no local rotation has a norm under 1e-8",
        "no joint turns more than 180 degrees between neighbouring keys in rotation-vector space, "
        "measured on the shortest arc: each key in the previous key's quaternion hemisphere, the "
        "twist about a bone that ends in a leaf joint removed, and a joint with no child held still",
    ]
    schema["$defs"] = {"vec3": _VEC3, "quat": _QUAT, "joint_position": _JOINT_POSITION}
    schema.update(
        {
            "type": "object",
            "required": ["format", "rest_offsets_m", "keyframes"],
            "properties": {
                "format": {"const": SKELETON_FORMAT},
                "fps": {"const": FPS, "description": "Optional. When present it must be 30."},
                "joints": {"const": list(CANONICAL_JOINTS)},
                "rest_offsets_m": _rest_offsets_schema(),
                "keyframes": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "required": ["index", "t", "joints", "local_rotations"],
                        "properties": {
                            "index": {"type": "integer", "minimum": 0},
                            "t": {"type": "number", "minimum": 0},
                            "name": {"type": "string"},
                            "conf": {
                                "type": "object",
                                "properties": _CONF_PROPERTIES,
                                "description": (
                                    "Optional. Per joint confidence 0..1 (Part 3 writes 0.3 for a joint the "
                                    "camera never saw). Carried into animation.json; a joint missing here is 1.0."
                                ),
                            },
                            "joints": {
                                "type": "object",
                                "required": list(CANONICAL_JOINTS),
                                "properties": {
                                    name: {"$ref": "#/$defs/joint_position"} for name in CANONICAL_JOINTS
                                },
                            },
                            "local_rotations": {
                                "type": "object",
                                "required": list(ROTATED_JOINTS),
                                "properties": {name: {"$ref": "#/$defs/quat"} for name in ROTATED_JOINTS},
                            },
                        },
                    },
                },
            },
        }
    )
    return schema


def animation_schema() -> dict:
    schema = _header(
        "animation",
        "animation.json written by Part 4",
        "simon.animation.v1 exactly as Part 4 writes it: one frame per 30 fps tick, joints in metres "
        "in the hip-centred body frame. Every object is closed. producer joined v1 as a required "
        "constant (A-P4-06). unseen_joints and frames[].conf joined v1 as optional fields; a reader "
        "that ignores them is unaffected. Any other new field means a new format.",
        "output",
        "Part 4",
        ["Part 5", "Part 6"],
    )
    schema["x-rules"] = [
        "frame_count equals round(duration_s * 30) + 1 and equals len(frames)",
        "frames[i].index equals i and frames[i].t equals index / 30",
        "interpolated is false exactly on the key indices of keyframes.json",
        "every bone in bones keeps length_m within 1 mm on every frame",
        "the hip midpoint stays within 1 mm of the origin",
        "frames[].conf, when present, is on key frames the key's own values and on filled frames the "
        "minimum of the two neighbouring keys; unseen_joints is present exactly when conf is",
    ]
    schema["$defs"] = {"vec3": _VEC3}
    schema.update(
        {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "format",
                "producer",
                "fps",
                "duration_s",
                "frame_count",
                "movement",
                "set",
                "coordinate_frame",
                "joints",
                "bones",
                "frames",
            ],
            "properties": {
                "format": {"const": ANIMATION_FORMAT},
                "producer": {
                    "const": ANIMATION_PRODUCER,
                    "description": "The part that wrote this file. Part 4 always writes part4.",
                },
                "fps": {"const": FPS},
                "duration_s": {"type": "number", "minimum": 0},
                "frame_count": {"type": "integer", "minimum": 1},
                "movement": {
                    "type": ["string", "null"],
                    "description": "From keyframes.json, else skeleton.json; null when neither names it.",
                },
                "set": {
                    "type": ["string", "null"],
                    "description": "From keyframes.json, else skeleton.json, else the --set name.",
                },
                "coordinate_frame": {"const": dict(COORDINATE_FRAME)},
                "joints": {"const": list(CANONICAL_JOINTS)},
                "bones": {
                    "type": "array",
                    "minItems": len(LENGTH_BONES),
                    "maxItems": len(LENGTH_BONES),
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["name", "parent", "child", "length_m"],
                        "properties": {
                            "name": {"enum": [bone["name"] for bone in LENGTH_BONES]},
                            "parent": {"type": "string"},
                            "child": {"type": "string"},
                            "length_m": {"type": "number", "exclusiveMinimum": 0},
                        },
                    },
                },
                "unseen_joints": {
                    "type": "array",
                    "items": {"enum": list(CANONICAL_JOINTS)},
                    "description": (
                        "Optional. Joints at or below conf 0.3 at every key frame, in canonical order; their "
                        "positions are not measured. Present, possibly empty, exactly when frames carry conf."
                    ),
                },
                "frames": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["index", "t", "interpolated", "joints"],
                        "properties": {
                            "index": {"type": "integer", "minimum": 0},
                            "t": {"type": "number", "minimum": 0, "description": "Seconds, index / 30."},
                            "interpolated": {
                                "type": "boolean",
                                "description": "false on a key frame, true on every other frame.",
                            },
                            "joints": {
                                "type": "object",
                                "additionalProperties": False,
                                "required": list(CANONICAL_JOINTS),
                                "properties": {name: {"$ref": "#/$defs/vec3"} for name in CANONICAL_JOINTS},
                            },
                            "conf": {
                                "type": "object",
                                "additionalProperties": False,
                                "required": list(CANONICAL_JOINTS),
                                "properties": _CONF_PROPERTIES,
                                "description": (
                                    "Optional. Confidence 0..1 per joint, same shape as the follower files Part 5 "
                                    "reads. 0.3 marks a joint the camera never saw. A key frame carries its key's "
                                    "values; a filled frame the minimum of the two neighbouring keys. Absent when "
                                    "the input carries no confidence."
                                ),
                            },
                        },
                    },
                },
            },
        }
    )
    return schema


SCHEMAS = {"keyframes": keyframes_schema, "skeleton": skeleton_schema, "animation": animation_schema}

# --- validator -------------------------------------------------------------

_ANNOTATIONS = {"$schema", "$id", "title", "description", "$comment", "default", "examples", "$defs"}
_TYPES = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "integer": lambda v: (isinstance(v, int) and not isinstance(v, bool))
    or (isinstance(v, float) and v.is_integer()),
}


class SchemaError(Exception):
    """The schema uses a keyword this validator does not implement."""


def _equal(a: Any, b: Any) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_equal(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_equal(x, y) for x, y in zip(a, b))
    return a == b


def _resolve(root: dict, ref: str) -> dict:
    if not ref.startswith("#/$defs/"):
        raise SchemaError(f"unsupported $ref {ref}")
    return root["$defs"][ref[len("#/$defs/"):]]


def _check(value: Any, schema: dict, root: dict, path: str, errors: list[str]) -> None:
    for key in schema:
        if key in _ANNOTATIONS or key.startswith("x-") or key in _KEYWORDS:
            continue
        raise SchemaError(f"unsupported keyword {key} at {path}")
    if "$ref" in schema:
        _check(value, _resolve(root, schema["$ref"]), root, path, errors)
    if "anyOf" in schema:
        if not any(not validate(value, sub, root) for sub in schema["anyOf"]):
            errors.append(f"{path}: matches none of the allowed shapes")
            return
    if "const" in schema and not _equal(value, schema["const"]):
        errors.append(f"{path}: must be {json.dumps(schema['const'])[:80]}")
        return
    if "enum" in schema and not any(_equal(value, item) for item in schema["enum"]):
        errors.append(f"{path}: must be one of {schema['enum']}")
        return
    if "type" in schema:
        allowed = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_TYPES[name](value) for name in allowed):
            errors.append(f"{path}: must be {' or '.join(allowed)}")
            return
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: must be at least {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: must be at most {schema['maximum']}")
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            errors.append(f"{path}: must be more than {schema['exclusiveMinimum']}")
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errors.append(f"{path}: needs at least {schema['minItems']} items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append(f"{path}: allows at most {schema['maxItems']} items")
        if "items" in schema:
            for i, item in enumerate(value):
                _check(item, schema["items"], root, f"{path}[{i}]", errors)
    if isinstance(value, dict):
        for name in schema.get("required", []):
            if name not in value:
                errors.append(f"{path}: missing {name}")
        props = schema.get("properties", {})
        for name, item in value.items():
            if name in props:
                _check(item, props[name], root, f"{path}.{name}", errors)
            elif schema.get("additionalProperties") is False:
                errors.append(f"{path}: unexpected field {name}")


_KEYWORDS = {
    "$ref", "anyOf", "const", "enum", "type", "minimum", "maximum", "exclusiveMinimum", "minItems", "maxItems",
    "items", "required", "properties", "additionalProperties",
}


def validate(value: Any, schema: dict, root: dict | None = None) -> list[str]:
    """Every way `value` breaks `schema`, as `$.path: reason` lines. Empty when valid."""
    errors: list[str] = []
    _check(value, schema, root or schema, "$", errors)
    return errors


def require(doc: Any, kind: str, label: str) -> None:
    """Raise ValueError naming the first broken field when `doc` breaks the `kind` schema."""
    errors = validate(doc, SCHEMAS[kind]())
    if errors:
        more = f" (and {len(errors) - 1} more)" if len(errors) > 1 else ""
        raise ValueError(f"{label} breaks {FILES[kind]}: {errors[0]}{more}")


def schema_text(kind: str) -> str:
    return json.dumps(SCHEMAS[kind](), indent=2, ensure_ascii=False) + "\n"


def write_files(directory: Path = CONTRACTS_DIR) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    written = []
    for kind, name in FILES.items():
        path = directory / name
        path.write_text(schema_text(kind), encoding="utf-8")
        written.append(path)
    return written


def stale_files(directory: Path = CONTRACTS_DIR) -> list[str]:
    """Committed schema files that differ from this module."""
    stale = []
    for kind, name in FILES.items():
        path = directory / name
        if not path.is_file() or path.read_text(encoding="utf-8") != schema_text(kind):
            stale.append(name)
    return stale


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Write or apply Part 4's JSON Schemas")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("write", help="write contracts/*.schema.json")
    check = sub.add_parser("validate", help="validate a file against one schema")
    check.add_argument("kind", choices=sorted(FILES))
    check.add_argument("path")
    args = parser.parse_args(argv)
    if args.command == "write":
        for path in write_files():
            print(f"wrote {path.relative_to(ROOT)}")
        return
    with open(args.path, encoding="utf-8") as handle:
        doc = json.load(handle)
    errors = validate(doc, SCHEMAS[args.kind]())
    for line in errors:
        print(line)
    print(f"{args.path}: {'ok' if not errors else f'{len(errors)} errors'} against {FILES[args.kind]}")
    sys.exit(0 if not errors else 1)


if __name__ == "__main__":
    main()
