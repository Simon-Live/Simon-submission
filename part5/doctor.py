"""`part5 doctor <file> [--for part5|part7]`: name a file's kind and version, validate it and say, in
plain words, what the consumer would reject and which option fixes it. It reads a clip, an analysis.json
and a replay.json (`simon.replay.v1`, checked against its schema and for lengths, indexes and times). A Part 2
pose3d.json is accepted as the optional feet side input (ADR-0015) with a note, not as a clip.

Exit 0 accepted, 1 rejected, 2 unreadable (missing, not a file, not JSON). The schema runs through
`jsonschema` when it is installed and the loaders (`part5.io`, `part5.output`) always run after it, so
the verdict line says which validators ran. The command is offline: it reads one file and never
fetches a URL, hand-off files included.
"""
# ADR-0004: a refused analysis (status.code different_movement, schema before 1.4.0) is valid and has faults [] by design.
# ADR-0012: from 1.4.0 status.code is always ok and a top-level `warnings` list says why the grade is F.
# ADR-0009: a replay.json (simon.replay.v1) is accepted for both consumers once its lengths, indexes and times agree.
# ASM-005: Part 7 reads status before faults; --for part7 warns when status.code is not ok.
# ASM-001: only simon.animation.v1 and simon.skeleton.v1 are read as clips.
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

from . import contract, feet
from .io import InputError, parse_clip
from .output import OutputError, validate_analysis

MAX_PROBLEMS = 8
POSE3D = "part2.pose3d/2026-10-28"  # Part 3 CONTRACT.md names this version of Part 2's pose3d.json
CONSUMERS = ("part5", "part7")
HANDOFF_FIX = "download files.animation and pass it as --expected"
CLIP_FIX = ("pass Part 4's animation.json, or a skeleton.json from Part 3 made with --view part5 "
            "(expected or follower) or --view part4 (expected)")
# Files other parts publish that Part 5 knows by name and does not read: {format or schema: (what, fix)}.
NOT_READ = {
    "simon.keyframes.v1": ("Part 4 keyframes.json", "pass the animation.json Part 4 made from it"),
    "simon.keyframes/part1": ("Part 1 keyframes.json", "pass the animation.json Part 4 made from it"),
    "simon.animation/1": ("Part 6 provisional animation.json (simon.animation/1)",
                          "use an entry whose animation.json is Part 4's simon.animation.v1"),
}
IO_FIXES = (
    ("hip midpoint", "subtract the hip midpoint from every joint in every frame (Part 3 --view part5 does)"),
    ("strictly increase", "make t strictly increasing"),
    ("canonical 17", "list the 17 joints of CONTRACT.md in that order"),
)
IO_FIX_DEFAULT = "re-export the clip with Part 3 --view part5, or use Part 4's animation.json"
ANALYSIS_FIX = "write the file with part5 analyse instead of editing it by hand"


@dataclass
class Problem:
    path: str
    message: str
    fix: str | None = None

    def line(self):
        return (f"{self.path}: " if self.path else "") + self.message + (f"; fix: {self.fix}" if self.fix else "")


@dataclass(frozen=True)
class Kind:
    id: str            # animation, skeleton, native, handoff, pose3d, analysis, replay, labels, named, unknown
    label: str         # the kind line, e.g. "simon.animation.v1 (Part 4 animation.json)"
    version: str | None = None


@dataclass
class Report:
    file: str
    consumer: str = "part5"
    kind: Kind = Kind("unknown", "unknown")
    problems: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    validators: list = field(default_factory=list)
    unreadable: bool = False

    @property
    def verdict(self):
        return "unreadable" if self.unreadable else "rejected" if self.problems else "accepted"

    @property
    def exit_code(self):
        return {"accepted": 0, "rejected": 1, "unreadable": 2}[self.verdict]

    def to_dict(self):
        return {"file": self.file, "kind": self.kind.id, "label": self.kind.label, "version": self.kind.version,
                "for": self.consumer, "verdict": self.verdict, "exit": self.exit_code,
                "problems": [vars(p) for p in self.problems], "warnings": self.warnings, "notes": self.notes,
                "validator": " then ".join(self.validators)}


# ---------------------------------------------------------------- reading and naming
def read_json(path):
    """(document, None), or (None, Problem) when the file can't be read as JSON."""
    p = Path(path)
    if not p.exists():
        return None, Problem("", "no such file")
    if not p.is_file():
        return None, Problem("", "not a file")
    try:
        text = p.read_bytes().decode("utf-8")
    except OSError as e:
        return None, Problem("", f"cannot be read ({e.strerror or e})")
    except UnicodeDecodeError:
        return None, Problem("", "not JSON (not UTF-8 text)")
    try:
        return json.loads(text), None
    except json.JSONDecodeError as e:
        return None, Problem("", f"not JSON ({e.lineno}:{e.colno})")


def _looks_like_pose3d(doc):
    frames = doc.get("frames")
    first = frames[0] if isinstance(frames, list) and frames else None
    return isinstance(first, dict) and (isinstance(first.get("people"), list)
                                        or ("joints" in first and "t_ms" in first))


def _looks_like_analysis(doc):
    return isinstance(doc.get("faults"), list) and isinstance(doc.get("expected"), dict) \
        and isinstance(doc.get("follower"), dict)


def identify(doc):
    """Name a parsed file by its format, its shape or both."""
    if not isinstance(doc, dict):
        return Kind("unknown", "not a JSON object")
    fmt, schema = doc.get("format"), doc.get("schema")
    ids = {x for x in (fmt, schema) if isinstance(x, str)}
    if doc.get("type") == "simon:follow":
        return Kind("handoff", f"simon:follow v{doc.get('v', 1)} hand-off (Part 6, framed message)", f"v{doc.get('v', 1)}")
    if fmt is None and schema is None and "v" in doc and isinstance(doc.get("id"), str) \
            and isinstance(doc.get("files"), dict):
        return Kind("handoff", f"simon:follow v{doc['v']} hand-off (Part 6, event detail)", f"v{doc['v']}")
    if fmt == "simon.analysis.v1":
        version = doc.get("schema_version", "1.0.0")
        return Kind("analysis", f"simon.analysis.v1 {version}" + ("" if "schema_version" in doc
                                                                     else " (no schema_version)"), version)
    if fmt == "simon.replay.v1":
        version = doc.get("schema_version", "1.0.0")
        return Kind("replay", f"simon.replay.v1 {version} (Part 5 replay.json)", version)
    if fmt == "simon.animation.v1":
        origin = {"part4": "Part 4 animation.json", "part3": "Part 3 --view part5 skeleton.json"}.get(doc.get("producer"))
        return Kind("animation", "simon.animation.v1" + (f" ({origin})" if origin else ""), "simon.animation.v1")
    if fmt == "simon.skeleton.v1":
        who = "Part 3 --view part4 skeleton.json" if isinstance(doc.get("input"), dict) else "not written by Part 3"
        return Kind("skeleton", f"simon.skeleton.v1 ({who})", "simon.skeleton.v1")
    if "simon.part5.labels.v1" in ids:
        return Kind("labels", "labels simon.part5.labels.v1 (Part 5)", "simon.part5.labels.v1")
    if "simon.part3.follower_labels/1" in ids:
        return Kind("labels", "labels simon.part3.follower_labels/1 (Part 3 kit)", "simon.part3.follower_labels/1")
    if fmt is None and schema == "simon.skeleton/1":
        return Kind("native", "simon.skeleton/1 (Part 3 native)", "simon.skeleton/1")
    for known in NOT_READ:
        if known in ids:
            return Kind("named", NOT_READ[known][0], known)
    if fmt is None and schema is None:
        if _looks_like_analysis(doc):
            return Kind("analysis", "simon.analysis.v1 (no format)", None)
        if _looks_like_pose3d(doc):
            return Kind("pose3d", "part2.pose3d (Part 2)", POSE3D)
    return Kind("unknown", f"unknown (format {fmt!r})" if fmt is not None else "unknown (no format)")


# ---------------------------------------------------------------- validation steps
def _schema_step(r, key, doc):
    """Run the jsonschema step when the package is installed; True when it ran."""
    if not contract.have_jsonschema():
        return False
    errs = contract.schema_errors(contract.make_validator(key), doc)
    r.problems += [Problem(*contract.explain(e, key)) for e in errs[:MAX_PROBLEMS]]
    if len(errs) > MAX_PROBLEMS:
        r.problems.append(Problem("", f"{len(errs) - MAX_PROBLEMS} more problems not shown"))
    schema = contract.load_schema(key)
    r.validators.append(f"jsonschema {contract.jsonschema_version()} with contracts/{key}.schema.json "
                        f"{schema.get('version', schema.get('x-simon-version'))}")
    return True


def _loader_step(r, load, name, doc, error, fix):
    """Run a part5 loader on a document that passed the schema; its error becomes a problem."""
    if r.problems:
        return
    try:
        load(doc)
    except error as e:
        message = str(e).removeprefix(f"{r.file}: ")
        r.problems.append(Problem("", message, fix(message)))
    r.validators.append(name)


def _clip_fix(message):
    return next((fix for needle, fix in IO_FIXES if needle in message), IO_FIX_DEFAULT)


def _no_validator_note(r):
    r.validators.append("part5 loaders only (the jsonschema package is not installed)")


# ---------------------------------------------------------------- a replay.json, for either consumer
REPLAY_LISTS = ("joints", "bones", "expected", "follower", "expected_t", "follower_t", "exp_to_fol")


def _replay_structure(r, doc):
    """Without jsonschema: every required key is there and the lists are lists."""
    for key in contract.load_schema("replay")["required"]:
        if key not in doc:
            r.problems.append(Problem(key, "missing", f'add "{key}"'))
        elif key in REPLAY_LISTS and not isinstance(doc[key], list):
            r.problems.append(Problem(key, "must be an array", "write the array part5 analyse --replay writes"))


def _for_replay(r, doc):
    """The schema, then what a schema cannot say: lengths, indexes and times (contract.replay_problems)."""
    if not _schema_step(r, "replay", doc):
        _no_validator_note(r)
        _replay_structure(r, doc)
    if not r.problems:
        r.problems += [Problem(*p) for p in contract.replay_problems(doc)]
        r.validators.append("part5.contract.replay_problems")
    if r.problems:
        return
    expected, follower = len(doc["expected"]), len(doc["follower"])
    r.notes.append(f"{expected} expected frames and {follower} follower frames; times in seconds as written in each "
                   "input file (expected_t, follower_t)")
    if isinstance(doc.get("reps"), list):
        r.notes.append(f"{len(doc['reps'])} repetitions (reps): the expected reference is repeated once per follower rep")
    if r.consumer == "part5":
        r.notes.append("Part 5 writes this file (part5 analyse --replay) and does not read it; Part 7 draws it")


# ---------------------------------------------------------------- verdicts for Part 5
def _for_part5_clip(r, doc):
    key = "input-animation" if r.kind.id == "animation" else "input-skeleton"
    if not _schema_step(r, key, doc):
        _no_validator_note(r)
    _loader_step(r, lambda d: parse_clip(d, source=r.file), "part5.io.parse_clip", doc, InputError, _clip_fix)


def _for_part5_native(r, doc):
    r.problems.append(Problem("", 'no "format" field: this is Part 3\'s native skeleton.json (simon.skeleton/1)',
                              "rerun Part 3 with --view part5"))


def _for_part5_handoff(r, doc):
    r.problems.append(Problem("", "Part 6 hand-off", HANDOFF_FIX))
    files = doc.get("files") if isinstance(doc.get("files"), dict) else {}
    if doc.get("v") != 1:
        r.warnings.append(f"v is {doc.get('v')!r}; this doctor knows hand-off v 1")
    if files.get("animation") is None:
        r.notes.append("files.animation is null in this hand-off: use an entry that has an animation, or "
                       "download files.skeleton and run doctor on it")


PART3_FIX = ("run Part 3 --view part5 "
             "(python3 -m part3 run --in pose3d.json --out skeleton.json --view part5)")


def _for_part5_pose3d(r, doc):
    """ADR-0015: a Part 2 pose3d.json is not a clip, but it is the optional feet side input (`--expected-feet`,
    `--follower-feet`), so it is accepted with a note when its shape allows that, with or without `extra_joints`."""
    r.validators.append("part5.feet.file_summary")
    try:
        info = feet.file_summary(doc, r.file)
    except InputError as e:
        message = str(e).removeprefix(f"{r.file}: ")
        r.problems.append(Problem("", f"Part 2 pose3d.json that is not a feet side input either ({message})", PART3_FIX))
        return
    if info["with_points"]:
        r.notes.append(f"feet side input for --expected-feet or --follower-feet: foot points in {info['with_points']} "
                       f"of {info['frames']} frames, people ids {info['people']}"
                       + ("; mirrored, so the left and right foot series are swapped" if info["mirrored"] else ""))
    else:
        r.notes.append("no foot points (no extra_joints in any frame; Part 2's cpu backend writes none): as a feet "
                       "side input the foot measures would be hidden")
    r.notes.append(f"not a clip: for the body pass Part 3's skeleton.json as --expected or --follower; {PART3_FIX}")


def _for_part5_analysis(r, doc):
    r.problems.append(Problem("", "Part 5 does not read analysis.json, it writes it",
                              "check it for Part 7 with --for part7"))


def _for_part5_labels(r, doc):
    key = "part3/follower-labels" if r.kind.version.startswith("simon.part3") else "labels"
    if not _schema_step(r, key, doc):
        r.validators.append("structure only (the jsonschema package is not installed)")
        if not isinstance(doc.get("takes"), list):
            r.problems.append(Problem("takes", "must be a list", 'write "takes": [...]'))
    r.notes.append("evaluation labels: make check-5 reads them, part5 analyse does not")


def _for_part5_named(r, doc):
    what, fix = NOT_READ[r.kind.version]
    r.problems.append(Problem("", f"{what}; Part 5 does not read it", fix))


def _for_part5_unknown(r, doc):
    if isinstance(doc, dict) and "format" not in doc:
        r.problems.append(Problem("format", "missing", "write \"format\": \"simon.animation.v1\" or "
                                  "\"simon.skeleton.v1\" (Part 3 --view part5 and Part 4 do)"))
    else:
        r.problems.append(Problem("", "Part 5 reads simon.animation.v1 and simon.skeleton.v1 only", CLIP_FIX))


FOR_PART5 = {"animation": _for_part5_clip, "skeleton": _for_part5_clip, "native": _for_part5_native,
             "handoff": _for_part5_handoff, "pose3d": _for_part5_pose3d, "analysis": _for_part5_analysis,
             "labels": _for_part5_labels, "named": _for_part5_named, "unknown": _for_part5_unknown}


# ---------------------------------------------------------------- verdict for Part 7
def _for_part7(r, doc):
    if r.kind.id != "analysis":
        r.problems.append(Problem("", f"Part 7 reads analysis.json; this file is {r.kind.label}",
                                  "pass the analysis.json that part5 analyse wrote"))
        return
    if not _schema_step(r, "analysis", doc):
        _no_validator_note(r)
    for p in r.problems:
        if p.path == "format" and p.message == "missing":
            p.fix = 'write "format": "simon.analysis.v1"'
    _loader_step(r, lambda d: validate_analysis(d, source=r.file), "part5.output.validate_analysis",
                 doc, OutputError, lambda message: ANALYSIS_FIX)
    if r.problems:
        return
    status = doc.get("status")
    if status is None:
        r.notes.append("no status block (schema 1.0): read it as ok")
    elif status.get("code") != "ok":
        r.warnings.append(f"status.code is {status['code']!r} and faults is empty by design: show status.text "
                          'as a refusal, not as "no faults"')
    for w in doc.get("warnings", []):   # 1.4.0, ADR-0012: analysed all the same, the grade is capped at F
        r.warnings.append(f"{w['code']}: {w['text']}")   # printed as "warning: <code>: <text>"
    if "schema_version" not in doc:
        r.notes.append("no schema_version, so this is a 1.0 file: faults[].joints is absent and the viewer "
                       "needs its own joint mapping")
    _cue_notes(r, doc)
    _time_notes(r, doc)
    _score_notes(r, doc)
    _feet_notes(r, doc)
    _profile_notes(r, doc)


def _profile_notes(r, doc):
    """1.7.0 (ADR-0016): the analysis profile. A score is only comparable inside one profile; a document before 1.7.0
    names none (validate_analysis rejects a 1.7.0 document that lacks it, so it never gets here)."""
    if "profile" in doc:
        r.notes.append(f"profile {doc['profile']}: scores compare within one profile")
    else:
        r.notes.append("no profile (written before 1.7.0): read it as fitness")


def _time_notes(r, doc):
    """1.2.0 and 1.4.0: which faults carry a time to show, and which say they are less certain."""
    faults = doc.get("faults", [])
    timed = [f for f in faults if "at_s" in f]
    if timed:
        r.notes.append(f"{len(timed)} of {len(faults)} faults carry at_s and text_timed: show text_timed (or coaching, "
                       "which names the time) with the moment to seek to")
    elif faults:
        r.notes.append("faults carry no at_s (written before 1.2.0): show text without a time")
    low = [f for f in faults if f.get("confidence") == "low"]
    if low:
        r.notes.append(f'{len(low)} of {len(faults)} faults have confidence "low" (a low match): show them as less certain')


def _score_notes(r, doc):
    """1.2.0, 1.3.0, 1.4.0: the score, how it was reached and what capped it."""
    score = doc.get("score")
    if not isinstance(score, dict):
        r.notes.append("no score (written before 1.2.0, or not scored): show the faults only")
        return
    line = (f"score {score['value']} out of 100, grade {score['grade']}" if "value" in score and "grade" in score
            else "score present")
    if score.get("capped_by"):
        line += f", capped at F by {', '.join(score['capped_by'])} (show the warnings beside it)"
    r.notes.append(line)
    windows = score.get("timeline")
    if isinstance(windows, list):
        r.notes.append(f"score.timeline has {len(windows)} window{'s' if len(windows) != 1 else ''} "
                       f"(basis {score.get('basis', 'windows')}): show {'them' if len(windows) != 1 else 'it'} as a timeline")


def _feet_notes(r, doc):
    """1.6.0 (ADR-0015): `diagnostics.feet` says whether the foot measures were compared and, if not, why."""
    info = (doc.get("diagnostics") or {}).get("feet")
    if not isinstance(info, dict):
        return
    foot_faults = [f for f in doc.get("faults", []) if f.get("body_part") == "feet"]
    if info.get("compared"):
        r.notes.append(f"foot measures compared ({', '.join(info['compared'])}); {len(foot_faults)} foot "
                       f"fault{'s' if len(foot_faults) != 1 else ''} (body_part feet, joint an ankle)")
    else:
        r.notes.append(f"foot measures hidden (diagnostics.feet): {info.get('hidden_reason')}")


def _cue_notes(r, doc):
    """1.5.0 (ADR-0014): a document without `insights` has no cues to show (validate_analysis checks them)."""
    if "insights" not in doc:
        r.notes.append("no insights and no cues (written before 1.5.0): show faults[].text as it is")


# ---------------------------------------------------------------- entry points
def inspect_file(path, consumer="part5"):
    r = Report(file=str(path), consumer=consumer)
    doc, problem = read_json(path)
    if problem:
        r.unreadable, r.problems = True, [problem]
        return r
    r.kind = identify(doc)
    judge = _for_replay if r.kind.id == "replay" else _for_part7 if consumer == "part7" else FOR_PART5[r.kind.id]
    judge(r, doc)
    return r


def render(r):
    if r.unreadable:
        return f"part5 doctor: {r.file}: {r.problems[0].message}"
    lines = [f"{r.file}: {r.kind.label}; {r.verdict} for {r.consumer}"]
    lines += [f"  {p.line()}" for p in r.problems]
    lines += [f"  warning: {w}" for w in r.warnings] + [f"  note: {n}" for n in r.notes]
    if r.validators:
        lines.append("  validator: " + " then ".join(r.validators))
    return "\n".join(lines)


def add_parser(sub):
    d = sub.add_parser("doctor", help="name a file's kind, validate it and say what a consumer would reject")
    d.add_argument("file", help="the file to check")
    d.add_argument("--for", dest="consumer", choices=CONSUMERS, default="part5",
                   help="who reads it: part5 (a clip, default) or part7 (an analysis.json or a replay.json)")
    d.add_argument("--json", action="store_true", help="print one JSON object")
    d.set_defaults(run=run_doctor)


def run_doctor(args):
    r = inspect_file(args.file, args.consumer)
    if args.json:
        print(json.dumps(r.to_dict(), indent=2))
    elif r.unreadable:
        print(render(r), file=sys.stderr)
    else:
        print(render(r))
    return r.exit_code
