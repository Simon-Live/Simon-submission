"""Part 5's published contract: six JSON Schemas, the compatibility table, `part5 contract` and
`make check-5-contract` (`python -m part5.contract --check`). Who sends what is in CONTRACT.md.

`contract_document()` is exactly what `part5 contract --json` prints; the staging API serves it at
`api/contract`. `check()` proves the schemas, the committed fixtures and the golden outputs agree.
`golden_run()` is the one path that builds a golden: what `part5 analyse` does, template phrasing forced.
"""
# ADR-0006: faults[].joints and the 1.1.0 additions are published as schema analysis 1.1.0.
# ADR-0009: the replay is a published file (simon.replay.v1); replay_problems() checks what a schema cannot.
# ADR-0012: the goldens carry what a real run carries (score, timeline, tempo, insights).
# ASM-005: Part 7 reads status before faults; the table and doctor --for part7 name that duty.
import argparse
import importlib.util
import json
import os
import re
import sys
import tempfile
from collections import Counter
from importlib import metadata
from pathlib import Path

from .io import InputError, load_clip
from .output import OutputError, load_analysis, write_analysis

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_NAMES = ("analysis", "input-animation", "input-skeleton", "labels", "metrics", "replay")
ID_BASE = "https://github.com/moalborati/simon-part-5-fault-analysis/contracts/"
DRAFT = "https://json-schema.org/draft/2020-12/schema"
# Commits of the neighbours whose files the Part 2 and Part 6 rows were checked against: the heads
# that scripts/neighbour-check.sh recorded. Parts 3 and 4 come from contracts/sources.lock.json.
NEIGHBOUR_COMMITS = {"part2": "2e06d58", "part6": "fc3249a"}  # progress/neighbour-check-20261031.json
TABLE_COLUMNS = ("Producer", "File", "format", "Part 5 role", "Verdict", "Fix", "Checked against")
TABLE_KEYS = ("producer", "file", "format", "part5_role", "verdict", "fix", "checked_against")
HANDOFF_FILE = "`{v: 1, id, name, category, link, manifest, files: {keyframes, skeleton, animation, video}}`"
HANDOFF_FIX = "download `files.animation` and pass it as `--expected`; Part 5 never fetches URLs"
# (producer, file, format, role, verdict, fix, checked against); {partN} is filled from a commit.
TABLE_ROWS = (
    ("Part 2", "`pose3d.json`", "`part2.pose3d/2026-10-28` (Part 3 CONTRACT.md)", "none", "rejected",
     "run Part 3 `--view part5` on it; `doctor` exits 1 with \"run Part 3 --view part5\"", "Part 2 {part2}"),
    ("Part 3 `run --view part5`", "`skeleton.json`", "`simon.animation.v1`", "follower or expected", "works",
     "", "Part 3 {part3}"),
    ("Part 3 `run --view part4`", "`skeleton.json`", "`simon.skeleton.v1`", "expected", "works", "",
     "Part 3 {part3}"),
    ("Part 3 native", "`skeleton.json`", "`simon.skeleton/1` (no `format`)", "none", "rejected",
     "rerun Part 3 with `--view part5`", "Part 3 {part3}"),
    ("Part 4", "`animation.json`", "`simon.animation.v1`", "expected", "works", "", "Part 4 {part4}"),
    ("Part 6 Follow hand-off (event detail)", HANDOFF_FILE, "none", "none", "works with an option",
     HANDOFF_FIX, "Part 6 {part6}"),
    ("Part 6 Follow hand-off (framed message, Part 6 CONTRACT.md \"The hand-off to Part 7\")",
     HANDOFF_FILE + " with `type: \"simon:follow\"`", "none", "none", "works with an option", HANDOFF_FIX,
     "Part 6 {part6}"),
    ("Part 5", "`analysis.json`", "`simon.analysis.v1`", "output for Part 7", "works",
     "Part 7 reads `warnings` and `score` (ADR-0012); each fault's `confidence` is a number or the literal `\"low\"`; "
     "the 1.2.0 to 1.5.0 fields (`at_s`, `text_timed`, `lateral`, `score`, `cue`, `insights`) are all optional", "Part 5 (this repo)"),
    ("Part 5 `analyse --replay <replay.json>`", "`replay.json`", "`simon.replay.v1`", "output for Part 7", "works",
     "optional second file; `expected_t` and `follower_t` carry the times in seconds; check it with `part5 doctor <replay.json>`",
     "Part 5 (this repo)"),
    ("Part 5 `analyse --live`", "live mode (`--live`, `serve --live`, `SIMON5_LIVE=1`, `META_LIVE=1`)",
     "`simon.analysis.v1` with `phrasing.selected_by` `live`", "option for Part 7", "works with an option",
     "needs the Baseten key file on the host that runs Part 5; without it each fault keeps its timed template line "
     "(`fallback_reason: \"no key\"`); the template stays the default for tests and `make check-5`", "Part 5 (this repo)"),
    ("Part 5", "`part5 analyse` exit code",
     "0 analysis written (with or without warnings), 1 unreadable or invalid input file or write error, 2 usage; 3 is no longer used (ADR-0012)",
     "for Part 7", "works with a mapping",
     "Part 7 at 90aa473 expects the family codes 0 written, 1 not writable, 2 input or option breaks the "
     "contract (Part 3 CONTRACT.md, row for Part 7): 0 is \"written\" (read `warnings`), 1 and 2 are failures; 3 is no longer produced", "Part 7 90aa473 (as Part 3 CONTRACT.md records it)"),
    ("Part 5", "`labels.json`", "none", "evaluation", "works", "", "Part 5 (this repo)"),
)


# ---------------------------------------------------------------- schemas
def schema_path(key, root=ROOT):
    """`key` is a Part 5 schema name or a copy such as `part3/skeleton`."""
    return Path(root) / "contracts" / f"{key}.schema.json"


def load_schema(key, root=ROOT):
    return json.loads(schema_path(key, root).read_text())


def have_jsonschema():
    """jsonschema is a dev dependency; without it doctor falls back to the part5 loaders."""
    return importlib.util.find_spec("jsonschema") is not None


def jsonschema_version():
    return metadata.version("jsonschema")


def make_validator(key, root=ROOT):
    import jsonschema
    return jsonschema.Draft202012Validator(load_schema(key, root))


def schema_errors(validator, doc):
    """All violations of `doc`, in field order."""
    return sorted(validator.iter_errors(doc), key=lambda e: [str(p) for p in e.absolute_path])


def dotted(path):
    out = ""
    for p in path:
        out += f"[{p}]" if isinstance(p, int) else (f".{p}" if out else str(p))
    return out


def _clip(text, n=160):
    return text if len(text) <= n else text[:n - 3] + "..."


def _json_type(v):
    """The JSON Schema name of a parsed value (bool before number: True is an int in Python)."""
    for kind, name in ((type(None), "null"), (bool, "boolean"), ((int, float), "number"),
                       (str, "string"), (list, "array")):
        if isinstance(v, kind):
            return name
    return "object"


def explain(err, key):
    """A jsonschema error as (field path, what is wrong, option that fixes it)."""
    path, kw = list(err.absolute_path), err.validator
    where = f"contracts/{key}.schema.json"
    if kw == "required":
        name = err.message.split("'")[1]
        return dotted(path + [name]), "missing", f'add "{name}"'
    if kw == "const":
        value = _clip(json.dumps(err.validator_value), 80)
        return dotted(path), f"must be {value}", f"write {value}"
    if kw == "enum":
        return dotted(path), _clip(f"must be one of {json.dumps(err.validator_value)}"), "use one of the listed values"
    if kw == "type":
        want = err.validator_value if isinstance(err.validator_value, str) else " or ".join(err.validator_value)
        return dotted(path), f"must be {want}, got {_json_type(err.instance)}", f"write {want}"
    if kw == "anyOf":  # the clip schemas' only anyOf: a clock is needed
        return dotted(path), "needs a top-level fps or a t on every frame", "add fps (Part 3 and Part 4 always write it)"
    return dotted(path), _clip(err.message), f"match {where} (python -m part5 contract --schema <name>)"


# ---------------------------------------------------------------- the replay file (simon.replay.v1)
def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _is_index(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _length_problems(doc):
    """The frame lists and the lists that go with them must agree in length."""
    out = []
    pairs = (("expected_t", "expected", "one time in seconds per expected frame"),
             ("exp_to_fol", "expected", "one follower frame index per expected frame"),
             ("follower_t", "follower", "one time in seconds per follower frame"))
    for name, frames, fix in pairs:
        got, want = doc.get(name), doc.get(frames)
        if isinstance(got, list) and isinstance(want, list) and len(got) != len(want):
            out.append((name, f"has {len(got)} entries but {frames} has {len(want)} frames", f"write {fix}"))
    return out


def _range_problem(path, value, size, owner):
    """One problem when the integer `value` is not a valid index into `size` items."""
    if _is_index(value) and not 0 <= value < size:
        return (path, f"is {value}, outside the {size} {owner} (0 to {size - 1})",
                f"point it at a frame that exists in {owner}")
    return None


def _index_problems(doc):
    """`exp_to_fol` into the follower frames, `bones` into the joints, `reps` into the frame lists."""
    out = []
    follower, expected, joints = doc.get("follower"), doc.get("expected"), doc.get("joints")
    if isinstance(doc.get("exp_to_fol"), list) and isinstance(follower, list):
        bad = [p for i, v in enumerate(doc["exp_to_fol"])
               if (p := _range_problem(f"exp_to_fol[{i}]", v, len(follower), "follower frames"))]
        if bad:   # the first is named, the rest counted
            more = f" ({len(bad) - 1} more entries are out of range)" if len(bad) > 1 else ""
            out.append((bad[0][0], bad[0][1] + more, bad[0][2]))
    if isinstance(doc.get("bones"), list) and isinstance(joints, list):
        for i, bone in enumerate(doc["bones"]):
            bad = [p for k, v in enumerate(bone if isinstance(bone, list) else [])
                   if (p := _range_problem(f"bones[{i}][{k}]", v, len(joints), "joints"))]
            if bad:
                out.append(bad[0])
                break
    for i, rep in enumerate(doc["reps"] if isinstance(doc.get("reps"), list) else []):
        for key, frames, owner in (("expected_frames", expected, "expected frames"),
                                   ("follower_frames", follower, "follower frames")):
            span = rep.get(key) if isinstance(rep, dict) else None
            if isinstance(span, list) and isinstance(frames, list):
                bad = [p for k, v in enumerate(span) if (p := _range_problem(f"reps[{i}].{key}[{k}]", v, len(frames), owner))]
                if bad:
                    out.append(bad[0])
    return out


def _time_problems(doc):
    """Both `t` lists must strictly increase (Part 5's clips do)."""
    out = []
    for name in ("expected_t", "follower_t"):
        times = doc.get(name)
        if not isinstance(times, list):
            continue
        for i in range(1, len(times)):
            if _is_num(times[i]) and _is_num(times[i - 1]) and not times[i] > times[i - 1]:
                out.append((f"{name}[{i}]", f"is {times[i]}, which does not come after {name}[{i - 1}] ({times[i - 1]})",
                            f"make {name} strictly increasing"))
                break
    return out


def replay_problems(doc):
    """What a schema cannot say about a `simon.replay.v1` document (journey-followup.md, AC-R03): the lengths of
    `expected`, `expected_t` and `exp_to_fol` agree, `follower` and `follower_t` agree, every `exp_to_fol` index
    and bone index is in range and both `t` lists strictly increase. A list that is missing or has the wrong type
    is the schema's to report. Returns [(field, what is wrong, fix)], empty when the file is sound."""
    return _length_problems(doc) + _index_problems(doc) + _time_problems(doc)


# ---------------------------------------------------------------- table and contract document
def lock_commits(root=ROOT):
    lock = json.loads((Path(root) / "contracts" / "sources.lock.json").read_text())
    return {name: up["commit"][:7] for name, up in lock["upstreams"].items()}


def table_rows(root=ROOT):
    """The compatibility table, every commit filled from the lock file or the neighbour check."""
    commits = {**lock_commits(root), **NEIGHBOUR_COMMITS}
    fill = lambda cell: re.sub(r"\{(part\d)\}", lambda m: commits[m.group(1)], cell)  # noqa: E731
    return [dict(zip(TABLE_KEYS, map(fill, row))) for row in TABLE_ROWS]


def table_markdown(rows):
    lines = ["| " + " | ".join(TABLE_COLUMNS) + " |", "|" + "---|" * len(TABLE_COLUMNS)]
    lines += ["| " + " | ".join(row[k] for k in TABLE_KEYS) + " |" for row in rows]
    return "\n".join(lines)


def schema_entries(root=ROOT):
    out = []
    for name in SCHEMA_NAMES:
        schema = load_schema(name, root)
        out.append({"name": name, "version": schema["version"], "id": schema["$id"],
                    "file": f"contracts/{name}.schema.json", "title": schema["title"], "schema": schema})
    return out


def contract_document(root=ROOT):
    """Exactly what `part5 contract --json` prints and the staging API serves at api/contract."""
    return {"schemas": schema_entries(root), "table": table_rows(root)}


def add_parser(sub):
    c = sub.add_parser("contract", help="print the schemas and the compatibility table")
    c.add_argument("--schema", metavar="NAME", help=f"print one schema verbatim ({', '.join(SCHEMA_NAMES)})")
    c.add_argument("--json", action="store_true", help="print {schemas, table} as JSON")
    c.set_defaults(run=run_contract)


def run_contract(args):
    try:
        return _print_contract(args)
    except BrokenPipeError:   # `part5 contract --json | head`: the reader left early; that is not an error
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        return 0


def _print_contract(args):
    if args.schema is not None:
        if args.schema not in SCHEMA_NAMES:
            print(f"part5 contract: no schema named {args.schema}; one of {', '.join(SCHEMA_NAMES)}",
                  file=sys.stderr)
            return 2
        sys.stdout.write(schema_path(args.schema).read_bytes().decode("utf-8"))
        return 0
    doc = contract_document()
    if args.json:
        print(json.dumps(doc, indent=2))
        return 0
    print("Part 5 contract. Field rules: docs/schemas.md. Who sends what: CONTRACT.md.\n\nSchemas")
    for s in doc["schemas"]:
        print(f"  {s['name']:<16} {s['version']:<6} {s['file']}  {s['title']}")
    print("\nCompatibility (the last column is the producer commit each row was checked against)\n")
    print(table_markdown(doc["table"]))
    return 0


# ---------------------------------------------------------------- the goldens (fixtures/output/)
REPLAY_SOURCE = "analysis.example.json"   # the golden replay is the replay of this golden's take


def golden_run(expected, follower):
    """The `PipelineResult` behind every golden: what `part5 analyse` does for a clean environment, with the
    score hook (so the goldens carry the score, timeline, tempo and insights real output carries) and the
    `template` phrasing forced whatever SIMON5_LIVE or META_LIVE say, so a golden never calls a model."""
    from .pipeline import run
    from .score_report import score_block
    return run(expected, follower, phrasing="template", score=score_block, live=False, selected_by="default")


def _write_analysis(path, result):
    return write_analysis(path, result.analysis)


def _write_replay(path, result):
    from .replay import write_replay
    return write_replay(path, result)


# ---------------------------------------------------------------- make check-5-contract
REQUIRED_DIRS = ("fixtures/input/expected", "fixtures/input/followers", "fixtures/input/contract",
                 "fixtures/output")
OPTIONAL_DIRS = ("fixtures/input/heldout", "fixtures/input/eval/real")
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def copied_keys(root):
    return [p.relative_to(Path(root) / "contracts").as_posix()[:-len(".schema.json")]
            for p in sorted((Path(root) / "contracts").glob("part[34]/*.schema.json"))]


def check_schemas(root, fail):
    """(summary per schema, keys of the schemas that are not usable)."""
    import jsonschema
    out, unusable = [], set()
    for key in list(SCHEMA_NAMES) + copied_keys(root):
        ours = key in SCHEMA_NAMES
        try:
            schema = load_schema(key, root)
            jsonschema.Draft202012Validator.check_schema(schema)
        except (OSError, ValueError, jsonschema.SchemaError) as e:
            fail(f"contracts/{key}.schema.json: not a valid draft 2020-12 schema ({_clip(str(e).splitlines()[0])})")
            out.append({"name": key, "version": None, "valid": False})
            unusable.add(key)
            continue
        problems = []
        if ours:
            if schema.get("$schema") != DRAFT:
                problems.append(f"$schema must be {DRAFT}")
            if schema.get("$id") != f"{ID_BASE}{key}.schema.json":
                problems.append(f"$id must be {ID_BASE}{key}.schema.json")
            if not SEMVER.match(str(schema.get("version", ""))):
                problems.append("version must be a string like 1.0.0")
        for p in problems:
            fail(f"contracts/{key}.schema.json: {p}")
        out.append({"name": key, "version": schema.get("version", schema.get("x-simon-version")),
                    "valid": not problems})
    return out, unusable


def classify(rel, doc):
    """(schema keys the file must satisfy, how part5 loads it) for one committed fixture."""
    name = rel.rsplit("/", 1)[-1]
    fmt = doc.get("format") if isinstance(doc, dict) else None
    from_part3, from_part4 = "/contract/part3/" in rel, "/contract/part4/" in rel
    if name == "labels.json":
        return (["part3/follower-labels"] if from_part3 else ["labels"]), None
    if fmt == "simon.analysis.v1":
        return ["analysis"], "analysis"
    if fmt == "simon.part5.check.v1":
        return ["metrics"], None
    if fmt == "simon.replay.v1":
        return ["replay"], "replay"
    if fmt == "simon.animation.v1":
        extra = ["part4/animation", "part3/animation-part5"] if from_part4 else \
            ["part3/animation-part5"] if from_part3 else []
        return extra + ["input-animation"], "clip"
    if fmt == "simon.skeleton.v1":
        return (["part3/skeleton-part4"] if from_part3 else []) + ["input-skeleton"], "clip"
    if isinstance(doc, dict) and doc.get("schema") == "simon.skeleton/1" and "format" not in doc:
        return ["part3/skeleton"], "rejected"  # Part 3 native: part5.io must refuse it
    return None, None


def fixture_paths(root, fail):
    paths = []
    for rel in REQUIRED_DIRS + OPTIONAL_DIRS:
        d = Path(root) / rel
        if d.is_dir():
            paths += sorted(d.rglob("*.json"))
        elif rel in REQUIRED_DIRS:
            fail(f"{rel}: directory is missing")
    return paths


class _Run:
    """State of one check: validators by schema key, counts and failures."""

    def __init__(self, root, unusable=()):
        self.root, self.failures, self.unusable = Path(root), [], set(unusable)
        self.by_schema, self.files, self.loaded, self.rejected, self.rebuilt = Counter(), 0, 0, 0, []
        self.replays = 0
        self._validators = {}

    def fail(self, msg):
        self.failures.append(msg)

    def validate(self, rel, doc, keys):
        for key in keys:
            if key in self.unusable:  # already reported as an invalid schema
                continue
            if key not in self._validators:
                self._validators[key] = make_validator(key, self.root)
            errs = schema_errors(self._validators[key], doc)
            for e in errs[:3]:
                path, what, _ = explain(e, key)
                self.fail(f"{rel}: {path + ': ' if path else ''}{what} (contracts/{key}.schema.json)")
            if len(errs) > 3:
                self.fail(f"{rel}: {len(errs) - 3} more violations of contracts/{key}.schema.json")
            self.by_schema[key] += 1

    def load(self, rel, path, how):
        if how == "rejected":  # Part 3's native view: part5.io must refuse it
            try:
                load_clip(path)
            except InputError:
                self.rejected += 1
            else:
                self.fail(f"{rel}: part5.io accepted a file it must reject (Part 3 native view)")
            return
        try:
            (load_clip if how == "clip" else load_analysis)(path)
        except (InputError, OutputError) as e:
            self.fail(str(e))
        else:
            self.loaded += 1

    def _golden_result(self, analysis_path):
        """The pipeline result behind a golden analysis: its own `expected` and `follower` refs, run again."""
        doc = json.loads(analysis_path.read_text())
        refs = [dict(doc[k], doc=json.loads((self.root / doc[k]["path"]).read_text())) for k in ("expected", "follower")]
        return golden_run(*refs)

    def _rebuilt(self, rel, path, source, build):
        """Note `rel` as rebuilt when `build(tmp_path, result)` for the take behind the analysis golden `source`
        writes `path` byte for byte; otherwise record the failure."""
        try:
            result = self._golden_result(source)
            with tempfile.TemporaryDirectory() as tmp:
                build(Path(tmp) / "golden.json", result)
                same = (Path(tmp) / "golden.json").read_bytes() == path.read_bytes()
        except (OSError, ValueError, KeyError, TypeError) as e:
            self.fail(f"{rel}: cannot rebuild through the pipeline ({_clip(str(e))})")
            return
        if same:
            self.rebuilt.append(rel)
        else:
            self.fail(f"{rel}: rebuilt through the pipeline it differs; run make output-examples and review the diff")

    def rebuild(self, rel, path):
        """A golden analysis rebuilt through the pipeline (the CLI's path, score included) must match byte for byte."""
        self._rebuilt(rel, path, path, _write_analysis)

    def rebuild_replay(self, rel, path):
        """The golden replay is the replay of the take behind `REPLAY_SOURCE`, rebuilt byte for byte."""
        self._rebuilt(rel, path, path.parent / REPLAY_SOURCE, _write_replay)

    def check_replay(self, rel, doc):
        """AC-R03: lengths, indexes and times, which the schema cannot say."""
        for field, what, _ in replay_problems(doc):
            self.fail(f"{rel}: {field}: {what}")
        self.replays += 1

    def fixture(self, path):
        rel = path.relative_to(self.root).as_posix()
        try:
            doc = json.loads(path.read_text())
        except ValueError as e:
            self.fail(f"{rel}: not JSON ({_clip(str(e))})")
            return
        keys, how = classify(rel, doc)
        if keys is None:
            fmt = doc.get("format") if isinstance(doc, dict) else None
            self.fail(f"{rel}: no schema covers this file (format {fmt!r})")
            return
        self.files += 1
        self.validate(rel, doc, keys)
        if how == "replay":
            self.check_replay(rel, doc)
        elif how:
            self.load(rel, path, how)
        golden = rel.startswith("fixtures/output/")
        if how == "analysis" and golden and path.name.startswith("analysis"):
            self.rebuild(rel, path)
        if how == "replay" and golden:
            self.rebuild_replay(rel, path)


def check(root=ROOT):
    """The summary `{schemas, validated, rebuilt_identical, failures}` of `make check-5-contract`."""
    run = _Run(root)
    schemas, run.unusable = check_schemas(run.root, run.fail)
    for path in fixture_paths(run.root, run.fail):
        run.fixture(path)
    return {"schemas": schemas,
            "validated": {"files": run.files, "by_schema": dict(sorted(run.by_schema.items())),
                          "loaded_through_part5": run.loaded, "rejected_as_documented": run.rejected,
                          "replays_checked": run.replays},
            "rebuilt_identical": run.rebuilt, "failures": run.failures}


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m part5.contract",
                                description="Check Part 5's published contract against the committed fixtures.")
    p.add_argument("--check", action="store_true", required=True,
                   help="validate the schemas, every committed fixture and the golden outputs")
    p.add_argument("--root", default=str(ROOT), help="repository root to check (default: this repository)")
    args = p.parse_args(argv)
    if not have_jsonschema():
        print("part5.contract --check needs the jsonschema package; run uv sync", file=sys.stderr)
        return 2
    summary = check(args.root)
    print(json.dumps(summary, indent=2))
    failures = summary["failures"]
    print("check-5-contract: PASS" if not failures else
          f"check-5-contract: FAIL ({len(failures)})\n  " + "\n  ".join(failures), file=sys.stderr)
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
