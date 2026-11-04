"""`python3 -m part3 contract [--json] [--schema <name>]`: the published contract of Part 3.

Reads `contracts/`: one JSON Schema per file Part 3 reads or writes (name = file name without
`.schema.json`) and `compatibility.json`, the table of which producer file works with which consumer.
`CONTRACT.md` renders the same rows (`compatibility_markdown`). Two files are generated, not typed:
`skeleton-part4.schema.json` is the native schema plus a part4 overlay (`part4_schema`), and the two tables
of `CONTRACT.md` come from `contracts/`. `python3 -m part3.contract build-schemas` and `build-docs` write
them; a test holds the committed files equal to the generated ones. Spec: docs/specs/integration-contract.md
"Contract and doctor"; ACs AC-C01, AC-C02, AC-C07.
"""

import argparse
import copy
import json
import pathlib
import sys

from part3.joints import COORDINATE_FRAME, JOINTS
from part3.rig import FK_ORDER, HIERARCHY, ROOT_JOINT, ROTATED

REPO = pathlib.Path(__file__).resolve().parents[1]
CONTRACTS_DIR = REPO / "contracts"
CONTRACT_MD = REPO / "CONTRACT.md"
SCHEMA_SUFFIX = ".schema.json"
COMPATIBILITY_FILE = "compatibility.json"
RESULTS = ("works", "works with option", "rejected")
COMPAT_COLUMNS = (("producer", "Producer"), ("file", "File"), ("version", "Version"), ("consumer", "Consumer"),
                  ("consumer_version", "Consumer version"), ("result", "Result"), ("option", "Option"),
                  ("evidence", "Evidence"))
_CODE_COLUMNS = ("version", "option")  # shown in backticks in Markdown


def _read_json(path):
    return json.loads(pathlib.Path(path).read_bytes().decode("utf-8"))


def load_schemas(directory=CONTRACTS_DIR):
    """{name: info} for every `*.schema.json` in `directory`, sorted by name.

    `info` holds name, file (repo-relative), path, version (`x-simon-version`), direction (`x-direction`),
    title, producer, consumers, version_field (the key that carries the version, or None) and schema.
    """
    registry = {}
    directory = pathlib.Path(directory)
    if not directory.is_dir():
        return registry
    for path in sorted(directory.glob(f"*{SCHEMA_SUFFIX}"), key=lambda p: p.name[:-len(SCHEMA_SUFFIX)]):
        name = path.name[:-len(SCHEMA_SUFFIX)]
        schema = _read_json(path)
        registry[name] = {
            "name": name, "file": f"contracts/{path.name}", "path": path,
            "version": schema.get("x-simon-version"), "direction": schema.get("x-direction"),
            "title": schema.get("title"), "producer": schema.get("x-producer"),
            "consumers": schema.get("x-consumers", []), "version_field": schema.get("x-version-field"),
            "schema": schema,
        }
    return registry


SCHEMAS = load_schemas()


def schema_bytes(name):
    """The bytes of one schema file, exactly as stored. Raises KeyError for an unknown name."""
    return SCHEMAS[name]["path"].read_bytes()


def compatibility_document(directory=CONTRACTS_DIR):
    return _read_json(pathlib.Path(directory) / COMPATIBILITY_FILE)


def compatibility(directory=CONTRACTS_DIR):
    """The rows of `contracts/compatibility.json`, in file order."""
    return compatibility_document(directory)["rows"]


# --- the part4 schema: the native schema plus an overlay ----------------------------------------

PART4_NAME = "skeleton-part4"
_POINT = {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3}
_QUATERNION = {"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4}
_PART4_DESCRIPTION = (
    "The output of python3 -m part3 run --view part4 --keyframes ...: the native skeleton plus the block Part 4 "
    "reads. Key joints are the forward kinematics of local_rotations on rest_offsets_m, so Part 4's 1 mm rule "
    "holds; rig.fit reports how far the snapped pose is from the native frame. Part 5 also reads this file as an "
    "expected skeleton (keyframes[] with joints as [x, y, z] lists). Rules a schema cannot say (checked by "
    "python3 -m part3 doctor <file> --for part4): key t equals index / 30 within one microsecond, indices strictly "
    "increase inside the clip, no quaternion has a norm under 1e-8, no joint turns more than 180 degrees between "
    "neighbouring keys in rotation-vector space (Part 3 refuses to write such a clip), forward kinematics "
    "reproduces each key within 1 mm, and keyframes.json sits beside this file with the same key indices.")


def _per_joint(names, definition):
    """An object that holds `definition` under every name in `names` and nothing else."""
    return {"type": "object", "properties": {name: definition for name in names}, "required": list(names),
            "additionalProperties": False}


def _rest_offsets_schema():
    entry = {joint: {"type": "object", "properties": {"parent": {"const": HIERARCHY[joint]}, "offset": _POINT},
                     "required": ["parent", "offset"]} for joint in FK_ORDER}
    return {"type": "object", "properties": entry, "required": list(FK_ORDER), "additionalProperties": False,
            "description": "Part 4's rig: every non-root joint with its fixed parent and its rest offset in the "
                           "parent frame, metres."}


def _key_schema():
    return {"type": "object", "properties": {
        "index": {"type": "integer", "minimum": 0}, "t": {"type": "number", "minimum": 0},
        "name": {"type": "string"}, "source_frame": {"type": "integer"}, "source_t_ms": {"type": "number"},
        "joints": _per_joint(JOINTS, _POINT),
        "conf": _per_joint(JOINTS, {"type": "number", "minimum": 0, "maximum": 1}),
        "local_rotations": _per_joint(ROTATED, _QUATERNION)},
        "required": ["index", "t", "name", "source_frame", "source_t_ms", "joints", "conf", "local_rotations"],
        "description": "One key pose. Quaternions are (x, y, z, w) with w >= 0."}


def _timeline_schema():
    dropped = {"type": "object", "properties": {"name": {"type": "string"}, "t_ms": {"type": "number"},
                                                "reason": {"type": "string", "minLength": 1}},
               "required": ["name", "t_ms", "reason"]}
    return {"type": "object", "properties": {
        "fps": {"const": 30}, "duration_s": {"type": "number", "minimum": 0},
        "frame_count": {"type": "integer", "minimum": 1}, "t0_ms": {"type": "number"},
        "source_kind": {"enum": ["part1", "part4", "every"]}, "person": {"type": ["integer", "string", "null"]},
        "dropped": {"type": "array", "items": dropped},
        "densify": {"type": "object", "properties": {
            "every": {"type": "integer", "minimum": 1, "maximum": 300},
            "selected_by": {"enum": ["flag", "env", "config", "api"]},
            "added": {"type": "integer", "minimum": 0}}, "required": ["every", "selected_by", "added"],
            "description": "Present only when --keyframes-densify ran: n, the channel and the filler keys written."}},
        "required": ["fps", "duration_s", "frame_count", "t0_ms", "source_kind", "dropped"]}


def _rig_schema():
    fit = {"type": "object", "properties": {
        "max_m": {"type": "number", "minimum": 0}, "mean_m": {"type": "number", "minimum": 0},
        "worst_joint": {"type": "string"}, "worst_index": {"type": "integer", "minimum": 0}},
        "required": ["max_m", "mean_m", "worst_joint", "worst_index"],
        "description": "Distance between the snapped key pose and the native frame, metres."}
    return {"type": "object", "properties": {"convention": {"type": "string", "minLength": 1}, "fit": fit},
            "required": ["convention", "fit"]}


def _part4_properties():
    """What the part4 view adds to the native document, in file order."""
    return {
        "format": {"const": "simon.skeleton.v1"},
        "fps": {"const": 30, "description": "The rate of the Part 4 timeline: key t is index / fps."},
        "coordinate_frame": {"$ref": "#/$defs/coordinate_frame"},
        "root_joint": {"const": ROOT_JOINT}, "virtual_joints": {"const": [ROOT_JOINT, "neck"]},
        "rest_offsets_m": _rest_offsets_schema(), "timeline": _timeline_schema(), "rig": _rig_schema(),
        "keyframes": {"type": "array", "items": _key_schema(), "minItems": 1},
    }


def _coordinate_frame_def():
    return {"type": "object", "properties": {key: {"const": value} for key, value in COORDINATE_FRAME.items()},
            "required": list(COORDINATE_FRAME),
            "description": "The frame Part 4 and Part 5 read. y is world_up: Part 3's body up is its estimate of "
                           "world up."}


def part4_schema():
    """`skeleton-part4.schema.json` as a dict: the native schema plus the block the part4 view adds."""
    native = SCHEMAS["skeleton"]["schema"]
    schema = copy.deepcopy(native)
    added = _part4_properties()
    schema.update({
        "$id": native["$id"].rsplit("/", 1)[0] + f"/{PART4_NAME}{SCHEMA_SUFFIX}",
        "title": "Part 3 skeleton.json (part4 view)", "description": _PART4_DESCRIPTION,
        "x-simon-version": "simon.skeleton.v1", "x-consumers": ["Part 4", "Part 5"], "x-version-field": "format",
        "required": native["required"] + list(added),
        "properties": {**native["properties"], **added},
        "$defs": {**native["$defs"], "coordinate_frame": _coordinate_frame_def()},
    })
    return copy.deepcopy(schema)


def render_schema(schema):
    """The bytes a schema file holds: two-space JSON and a final newline."""
    return (json.dumps(schema, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


GENERATED = {PART4_NAME: part4_schema}  # schema name -> builder; `build_schemas` writes these files


def build_schemas(directory=None):
    """Write every generated schema into `directory` (default `contracts/`); returns the paths written."""
    directory = pathlib.Path(directory or CONTRACTS_DIR)
    written = []
    for name, build in GENERATED.items():
        path = directory / f"{name}{SCHEMA_SUFFIX}"
        path.write_bytes(render_schema(build()))
        written.append(path)
    return written


# --- rendering ---------------------------------------------------------------------------------

def _table(headers, rows):
    """Plain text columns padded to the widest cell; the last column is not padded."""
    widths = [max(len(str(cell)) for cell in column) for column in zip(headers, *rows)]
    lines = []
    for row in [headers, *rows]:
        cells = [str(cell).ljust(widths[i]) if i < len(widths) - 1 else str(cell) for i, cell in enumerate(row)]
        lines.append("  ".join(cells).rstrip())
    return lines


def schema_lines():
    rows = [(s["name"], s["version"], s["direction"], s["file"]) for s in SCHEMAS.values()]
    return _table(("name", "version", "direction", "file"), rows)


def compatibility_lines(doc=None):
    doc = doc or compatibility_document()
    rows = doc["rows"]
    body = [(str(i), r["producer"], r["file"], r["version"], r["consumer"], r["result"], r["option"] or "-")
            for i, r in enumerate(rows, 1)]
    lines = _table(("#", "producer", "file", "version", "consumer", "result", "option"), body)
    lines += ["", "Evidence (neighbour commits: " + ", ".join(f"{k} {v}" for k, v in doc["neighbours"].items()) + ")"]
    lines += [f"{i}. {r['evidence']}" for i, r in enumerate(rows, 1)]
    return lines


def _cell(key, value):
    text = str(value).replace("|", "\\|")
    return f"`{text}`" if key in _CODE_COLUMNS and text else text


def _markdown_table(headers, rows):
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join(lines) + "\n"


def compatibility_markdown(rows=None):
    """The compatibility rows as a Markdown table: the block in CONTRACT.md (AC-C07)."""
    rows = compatibility() if rows is None else rows
    body = [[_cell(key, row[key]) for key, _ in COMPAT_COLUMNS] for row in rows]
    return _markdown_table([label for _, label in COMPAT_COLUMNS], body)


def schemas_markdown():
    """The schema list as a Markdown table: the block in CONTRACT.md."""
    body = [[f"`{s['name']}`", f"`{s['version']}`", s["direction"], f"`{s['file']}`", s["producer"],
             ", ".join(s["consumers"])] for s in SCHEMAS.values()]
    return _markdown_table(["Name", "Version", "Direction", "File", "Producer", "Consumers"], body)


DOC_BLOCKS = (("schema-table", schemas_markdown), ("compatibility-table", compatibility_markdown))


def render_contract_md(text):
    """`text` (CONTRACT.md) with each table between its `<!-- name:begin -->` and `<!-- name:end -->` regenerated."""
    for name, render in DOC_BLOCKS:
        start, end = f"<!-- {name}:begin -->\n", f"<!-- {name}:end -->"
        if start not in text or end not in text:
            raise ValueError(f"CONTRACT.md has no {name} block ({start.strip()} ... {end})")
        head, rest = text.split(start, 1)
        text = head + start + render() + end + rest.split(end, 1)[1]
    return text


def build_docs(path=None):
    """Rewrite the generated tables of CONTRACT.md in place; returns the path."""
    path = pathlib.Path(path or CONTRACT_MD)
    path.write_bytes(render_contract_md(path.read_bytes().decode("utf-8")).encode("utf-8"))
    return path


def _write_bytes(data):
    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is None:
        sys.stdout.write(data.decode("utf-8"))
        return
    sys.stdout.flush()
    buffer.write(data)
    buffer.flush()


def _json_view():
    listed = [{key: info[key] for key in ("name", "version", "direction", "file", "title", "producer",
                                           "consumers", "version_field")} for info in SCHEMAS.values()]
    return {"schemas": listed, "compatibility": compatibility()}


BUILDS = {"build-schemas": build_schemas, "build-docs": lambda: [build_docs()]}


def _build(command):
    """Run one generator command; 0 written, 1 a file could not be written or CONTRACT.md lacks a table."""
    try:
        written = BUILDS[command]()
    except (OSError, ValueError) as error:
        print(f"{command}: {error}", file=sys.stderr)
        return 1
    print("\n".join(f"wrote {path}" for path in written))
    return 0


def _parser():
    parser = argparse.ArgumentParser(
        prog="python3 -m part3 contract",
        description="Print the schemas in contracts/ and the compatibility table, or one schema as stored.")
    parser.add_argument("command", nargs="?", choices=sorted(BUILDS),
                        help="build-schemas writes the generated schema files, build-docs the tables in CONTRACT.md")
    parser.add_argument("--json", action="store_true", help="print {schemas, compatibility} as JSON")
    parser.add_argument("--schema", metavar="NAME",
                        help="print one schema file exactly as stored (name from the list; wins over --json)")
    return parser


def main(argv=None):
    """Exit codes: 0 printed or written, 1 a generator could not write, 2 unknown schema or bad option."""
    try:
        args = _parser().parse_args(argv)
    except SystemExit as stop:
        return int(stop.code or 0)
    if not SCHEMAS:
        print(f"{CONTRACTS_DIR}: no *{SCHEMA_SUFFIX} files found", file=sys.stderr)
        return 2
    if args.command:
        return _build(args.command)
    if args.schema is not None:
        if args.schema not in SCHEMAS:
            print(f'unknown schema "{args.schema}"; choose one of: {", ".join(SCHEMAS)}', file=sys.stderr)
            return 2
        _write_bytes(schema_bytes(args.schema))
        return 0
    if args.json:
        print(json.dumps(_json_view(), indent=2, ensure_ascii=False))
        return 0
    doc = compatibility_document()
    lines = ["Schemas (contracts/, JSON Schema draft 2020-12; print one with --schema <name>)", ""]
    lines += schema_lines()
    lines += ["", f"Compatibility (checked {doc['checked']})", ""]
    lines += compatibility_lines(doc)
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
