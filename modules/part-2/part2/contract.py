"""Downstream contract (CONTRACT.md): the schemas Part 2 publishes and the copy of Part 3's own.

    contracts/<kind>.schema.json      Part 2's promise for pose3d, tracks, camera and frames, and for the optional
                                      mesh3d.json header (`part2 run --mesh`, TICKET-048; its bin: part2.mesh3d)
    contracts/compatibility.json      which consumer reads which file, and with what option
    contracts/consumers/part3-pose3d.schema.json   Part 3's consumer schema, copied byte for byte;
        the sidecar part3-pose3d.schema.source.json names the repo, path, commit and sha256 it came from.

    validate(doc, kind)    Part 2's schema plus the rules a schema cannot say; raises ContractError
    validate_part3(doc)    the copied schema plus the rules Part 3 states outside it
    contract_json()        {"schemas": [...], "compatibility": [...]} (python -m part2 contract --json)
    python -m part2.contract sync [--check] | validate FILE... | check   (make contract-sync, contract-check, check-2-contract)

The checker below covers only the JSON Schema keywords the schemas use and refuses any other
keyword, so a schema that starts using a new keyword fails loudly instead of passing.
"""
import argparse
import base64
import functools
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

from part2.schema import ContractError, check_finite, is_number

ROOT = Path(__file__).resolve().parent.parent
CONTRACTS = ROOT / "contracts"
KINDS = ("pose3d", "tracks", "camera", "frames")
OPTIONAL_KINDS = ("mesh3d",)  # written only on request; validated with its bin by part2.mesh3d.validate
PUBLISHED = KINDS + OPTIONAL_KINDS
PART3_LABEL = "contracts/consumers/part3-pose3d.schema.json"
PART3_SCHEMA = ROOT / PART3_LABEL
PART3_SOURCE = ROOT / "contracts" / "consumers" / "part3-pose3d.schema.source.json"
COMPATIBILITY = CONTRACTS / "compatibility.json"
DRAFT = "https://json-schema.org/draft/2020-12/schema"

ANNOTATIONS = {"$schema", "$id", "title", "description"}
CHECKED = {"type", "required", "properties", "additionalProperties", "items", "prefixItems", "$ref", "$defs",
           "minimum", "maximum", "exclusiveMinimum", "minItems", "maxItems", "minLength", "pattern", "anyOf"}


# --- the schemas and the table ------------------------------------------------------------------

def load_schema(path=PART3_SCHEMA) -> dict:
    """A schema file; by default Part 3's consumer copy."""
    return json.loads(Path(path).read_text())


def schema_path(kind: str) -> Path:
    if kind not in PUBLISHED:
        raise ContractError(kind, f"no schema; schemas: {', '.join(PUBLISHED)}")
    return CONTRACTS / f"{kind}.schema.json"


@functools.cache
def own_schema(kind: str) -> dict:
    """Part 2's own schema for `kind` (read once; do not mutate)."""
    return load_schema(schema_path(kind))


def version(kind: str) -> str:
    return own_schema(kind)["x-simon-version"]


def schema_rows() -> list[dict]:
    return [{"name": k, "version": version(k), "direction": own_schema(k)["x-direction"],
             "file": f"contracts/{k}.schema.json"} for k in PUBLISHED]


def compatibility() -> list[dict]:
    return json.loads(COMPATIBILITY.read_text())


def contract_json() -> dict:
    return {"schemas": schema_rows(), "compatibility": compatibility()}


# --- validation ---------------------------------------------------------------------------------

def validate(doc, kind: str) -> None:
    """Raise ContractError(path, msg) unless `doc` keeps Part 2's promise for `kind`."""
    schema = own_schema(kind)
    check_finite(doc, kind)
    check_schema(doc, schema, at=kind)
    check_sequence(doc, kind)


def validate_part3(doc, schema: dict | None = None) -> None:
    """Raise ContractError unless Part 3 accepts `doc` as a pose3d.json without any option."""
    check_finite(doc, "pose3d")
    check_schema(doc, load_schema() if schema is None else schema)
    check_sequence(doc, "pose3d")


def check_schema(doc, schema: dict, root: dict | None = None, at: str = "pose3d") -> None:
    """Raise ContractError at the first place `doc` breaks `schema` (a JSON Schema subset)."""
    root = schema if root is None else root
    _reject_unsupported(schema, at)
    if "$ref" in schema:
        return check_schema(doc, _resolve(schema["$ref"], root), root, at)
    if "type" in schema and not _is_type(doc, schema["type"]):
        raise ContractError(at, f"expected {schema['type']}, got {type(doc).__name__}")
    if "anyOf" in schema:
        _any_of(doc, schema["anyOf"], root, at)
    if isinstance(doc, dict):
        _check_object(doc, schema, root, at)
    elif isinstance(doc, list):
        _check_array(doc, schema, root, at)
    elif isinstance(doc, str):
        _check_string(doc, schema, at)
    elif is_number(doc):
        _check_number(doc, schema, at)


def _reject_unsupported(schema: dict, at: str) -> None:
    unknown = {k for k in schema if not k.startswith("x-")} - ANNOTATIONS - CHECKED
    if unknown:
        raise ContractError(at, f"schema keyword(s) {sorted(unknown)} are not supported by part2.contract")


def _any_of(doc, options: list, root: dict, at: str) -> None:
    for sub in options:
        _reject_unsupported(sub, at)
    for sub in options:
        try:
            return check_schema(doc, sub, root, at)
        except ContractError:
            continue
    raise ContractError(at, "matches none of the allowed shapes")


def _check_object(doc: dict, schema: dict, root: dict, at: str) -> None:
    for key in schema.get("required", []):
        if key not in doc:
            raise ContractError(f"{at}.{key}", "required")
    props = schema.get("properties", {})
    if schema.get("additionalProperties") is False:
        extra = sorted(set(doc) - set(props))
        if extra:
            raise ContractError(at, f"unexpected key(s) {extra}")
    for key, sub in props.items():
        if key in doc:
            check_schema(doc[key], sub, root, f"{at}.{key}")


def _check_array(doc: list, schema: dict, root: dict, at: str) -> None:
    if len(doc) < schema.get("minItems", 0):
        raise ContractError(at, f"expected at least {schema['minItems']} items, got {len(doc)}")
    if len(doc) > schema.get("maxItems", len(doc)):
        raise ContractError(at, f"expected at most {schema['maxItems']} items, got {len(doc)}")
    prefix = schema.get("prefixItems", [])
    for i, item in enumerate(doc):
        sub = prefix[i] if i < len(prefix) else schema.get("items")
        if sub is not None:
            check_schema(item, sub, root, f"{at}[{i}]")


def _check_string(doc: str, schema: dict, at: str) -> None:
    if len(doc) < schema.get("minLength", 0):
        raise ContractError(at, f"shorter than {schema['minLength']} characters")
    if "pattern" in schema and not re.search(schema["pattern"], doc):
        raise ContractError(at, f"{doc!r} does not match {schema['pattern']}")


def _check_number(doc, schema: dict, at: str) -> None:
    if "minimum" in schema and doc < schema["minimum"]:
        raise ContractError(at, f"{doc} below minimum {schema['minimum']}")
    if "maximum" in schema and doc > schema["maximum"]:
        raise ContractError(at, f"{doc} above maximum {schema['maximum']}")
    if "exclusiveMinimum" in schema and doc <= schema["exclusiveMinimum"]:
        raise ContractError(at, f"{doc} not above {schema['exclusiveMinimum']}")


def check_sequence(doc: dict, kind: str) -> None:
    """What no schema can say (Part 3 states it outside its schema): whole-number frames that strictly
    increase, and person ids that are unique within a frame. Call after check_schema."""
    previous = None
    for i, f in enumerate(doc["frames"]):
        at = f"{kind}.frames[{i}]"
        frame = f["frame"]
        if not isinstance(frame, int) or isinstance(frame, bool):  # the schema's integer type admits 3.0
            raise ContractError(f"{at}.frame", f"expected a whole number, not {frame!r}")
        if previous is not None and frame <= previous:
            raise ContractError(f"{at}.frame", "frame indices must be strictly increasing")
        previous = frame
        seen = set()
        for k, p in enumerate(f.get("people", [])):
            key = (type(p["id"]), p["id"])
            if key in seen:
                raise ContractError(f"{at}.people[{k}].id", f"duplicate id {p['id']!r} in this frame")
            seen.add(key)


def _resolve(ref: str, root: dict) -> dict:
    if not ref.startswith("#/"):
        raise ContractError(ref, "only local $ref references are supported")
    node = root
    for part in ref[2:].split("/"):
        node = node[part]
    return node


def _is_type(v, t) -> bool:
    if isinstance(t, list):
        return any(_is_type(v, x) for x in t)
    return {
        "object": lambda: isinstance(v, dict),
        "array": lambda: isinstance(v, list),
        "string": lambda: isinstance(v, str),
        "boolean": lambda: isinstance(v, bool),
        "integer": lambda: isinstance(v, int) and not isinstance(v, bool)
                           or isinstance(v, float) and v.is_integer(),
        "number": lambda: is_number(v),
        "null": lambda: v is None,
    }[t]()


# --- sync: refresh the copy from Part 3 ---------------------------------------------------------

def _gh(*args: str) -> str:
    """Part 3's repo is private, so reads go through the GitHub CLI and its login."""
    try:
        return subprocess.run(["gh", "api", *args], check=True, capture_output=True, text=True).stdout
    except FileNotFoundError as e:
        raise RuntimeError("gh (GitHub CLI) not found; install it and run gh auth login") from e
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"gh api {' '.join(args)} failed: {e.stderr.strip()}") from e


def fetch(source: dict) -> tuple[bytes, str]:
    """(schema bytes, commit sha) from the head of the source branch."""
    repo, path, ref = source["repo"], source["path"], source["branch"]
    commit = _gh(f"repos/{repo}/commits/{ref}", "--jq", ".sha").strip()
    content = json.loads(_gh(f"repos/{repo}/contents/{path}?ref={commit}"))["content"]
    return base64.b64decode(content), commit


def sync(check_only: bool = False, fetcher=fetch) -> int:
    """0 when the copy matches Part 3; 1 when it changed (rewritten unless check_only)."""
    source = json.loads(PART3_SOURCE.read_text())
    new, commit = fetcher(source)
    if new == PART3_SCHEMA.read_bytes():
        print(f"{PART3_LABEL} matches {source['repo']}@{commit[:7]} (copied at {source['commit'][:7]})")
        return 0
    if check_only:
        print(f"{PART3_LABEL} differs from {source['repo']}@{commit[:7]}; run make contract-sync")
        return 1
    PART3_SCHEMA.write_bytes(new)
    source.update(commit=commit, sha256=hashlib.sha256(new).hexdigest())
    PART3_SOURCE.write_text(json.dumps(source, indent=2) + "\n")
    print(f"{PART3_LABEL} CHANGED: refreshed from {source['repo']}@{commit[:7]}. "
          "Run make test, update CONTRACT.md if the shape moved, and commit both files.")
    return 1


# --- the contract command and the committed-output check ----------------------------------------

def command(as_json: bool = False, schema: str | None = None) -> int:
    """python -m part2 contract [--json] [--schema NAME]; returns the exit code."""
    if schema is not None:
        if schema not in PUBLISHED:
            print(f"contract: no schema '{schema}'; schemas: {', '.join(PUBLISHED)}", file=sys.stderr)
            return 2
        raw = schema_path(schema).read_bytes()
        sys.stdout.flush()
        if hasattr(sys.stdout, "buffer"):  # byte for byte
            sys.stdout.buffer.write(raw)
            sys.stdout.buffer.flush()
        else:
            sys.stdout.write(raw.decode())
        return 0
    doc = contract_json()
    if as_json:
        print(json.dumps(doc, indent=2))
        return 0
    print("Schemas Part 2 writes")
    for r in doc["schemas"]:
        print(f"  {r['name']:<8} {r['version']:<26} {r['direction']:<7} {r['file']}")
    print("Compatibility (producer file | version | consumer | result | option | evidence)")
    for r in doc["compatibility"]:
        print("  " + " | ".join([r["producer_file"], r["version"], r["consumer"], r["result"], r["option"] or "-", r["evidence"]]))
    return 0


def committed_files(root: Path = ROOT) -> list[tuple[Path, str]]:
    """(path, kind) for every committed output and every committed frames.json."""
    out, inp = Path(root) / "fixtures" / "output", Path(root) / "fixtures" / "input"
    found = [(p, "pose3d") for p in sorted(out.rglob("pose3d*.json"))]
    found += [(p, kind) for kind, name in (("tracks", "tracks.json"), ("camera", "camera.json")) for p in sorted(out.rglob(name))]
    return found + [(p, "frames") for p in sorted(inp.rglob("frames.json"))]


def contract_problems() -> list[tuple[str, str]]:
    """(file, problem) for the published contract files themselves."""
    problems = []
    for kind in PUBLISHED:
        s = own_schema(kind)
        ok = (s.get("$schema") == DRAFT and s.get("$id", "").endswith(f"/{kind}.schema.json") and s.get("title")
              and re.fullmatch(rf"part2\.{kind}/\d{{4}}-\d{{2}}-\d{{2}}", s.get("x-simon-version", "")))
        if not ok:
            problems.append((f"contracts/{kind}.schema.json", "needs $schema (draft 2020-12), $id, title and x-simon-version part2.<kind>/<date>"))
    source = json.loads(PART3_SOURCE.read_text())
    if hashlib.sha256(PART3_SCHEMA.read_bytes()).hexdigest() != source["sha256"]:
        problems.append((PART3_LABEL, "does not match the sha256 in its .source.json sidecar"))
    keys = {"producer_file", "version", "consumer", "result", "option", "evidence"}
    if any(set(r) != keys for r in compatibility()):
        problems.append(("contracts/compatibility.json", f"every row needs exactly {sorted(keys)}"))
    return problems


def _file_problem(path: Path, kind: str) -> str | None:
    """The first rule a committed file breaks, or None. pose3d also goes through Part 2's validator,
    the Part 3 copy and doctor --for part3; tracks through Part 2's validator."""
    from part2 import doctor, schema

    try:
        doc = json.loads(path.read_text())
        validate(doc, kind)
        if kind == "pose3d":
            schema.validate_pose3d(doc)
            validate_part3(doc)
            found = doctor.diagnose(path, "part3")
            if found["exit"]:
                raise ContractError(path.name, f"doctor --for part3 would reject: {found['findings'][0]['reason']}")
        elif kind == "tracks":
            schema.validate_tracks(doc)
    except (ValueError, OSError) as e:
        return str(e)
    return None


def check_outputs(root: Path = ROOT) -> dict:
    """make check-2-contract: {files, valid, failures, pass}. Needs no GPU."""
    files = committed_files(root)
    failures = [{"file": file, "error": error} for file, error in contract_problems()]
    for path, kind in files:
        error = _file_problem(path, kind)
        if error:
            failures.append({"file": str(path.relative_to(root)) if path.is_relative_to(root) else str(path), "error": error})
    checked = len(files) + len(PUBLISHED) + 2
    return {"files": checked, "valid": checked - len(failures), "failures": failures, "pass": bool(files) and not failures}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m part2.contract")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("sync", help=f"refresh {PART3_LABEL} from Part 3; exit 1 if it changed")
    p.add_argument("--check", action="store_true", help="compare only, write nothing")
    v = sub.add_parser("validate", help="check pose3d.json files against Part 2's schema and Part 3's schema")
    v.add_argument("files", nargs="+", type=Path)
    sub.add_parser("check", help="every committed output against its schema, the Part 3 copy and doctor; metrics JSON (make check-2-contract)")
    args = parser.parse_args(argv)
    try:
        if args.command == "sync":
            return sync(check_only=args.check)
        if args.command == "check":
            report = check_outputs()
            print(json.dumps(report, indent=2))
            return 0 if report["pass"] else 1
        from part2.schema import validate_pose3d

        for f in args.files:
            doc = json.loads(f.read_text())
            validate_pose3d(doc)
            validate(doc, "pose3d")
            validate_part3(doc)
            print(f"{f}: valid for Part 2 and Part 3")
        return 0
    except (RuntimeError, ValueError) as e:
        print(f"part2.contract: {e}", file=sys.stderr)
        return 2 if isinstance(e, RuntimeError) else 1


if __name__ == "__main__":
    sys.exit(main())
