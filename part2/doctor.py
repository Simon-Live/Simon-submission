"""python -m part2 doctor FILE [--for part3|part5|part6] [--json]

Names a Part 2 file's kind and version, validates it, and says in plain words what each consumer
would reject and which option fixes it. Reads only the given file. The consumer rules are restated
from each consumer's published CONTRACT.md, not imported:

  Part 3  reads pose3d.json; its schema, its checks outside the schema, `--person` / `--all-people`
          for several people, `--input-fps` or a top-level fps for a file without t_ms.
  Part 5  reads skeleton.json, which Part 3 writes, so a Part 2 file never goes to it directly.
  Part 6  has no Part 2 kind: only its generic reader rules are checked (17 joints, finite numbers,
          person id 0 else the first, JSON read strictly so NaN and Infinity are refused).

Exit 0 when the named consumer (Part 3 without --for) accepts, with or without an option; 1 when
it would reject; 2 when the file is not JSON or of no known kind. A pose3d file whose people carry the
optional `extra_joints` (foot points, TICKET-043) gets one more line naming them; no verdict changes.
"""
import json
import sys
from pathlib import Path

from part2 import contract
from part2.joints import CANONICAL, EXTRA
from part2.schema import ContractError, check_finite, is_number

CONSUMERS = {"part3": "Part 3", "part5": "Part 5", "part6": "Part 6"}
ACCEPTS, OPTION, REJECTS = "accepts", "accepts with option", "would reject"
NAME_HINTS = {"frames.json": "frames", "tracks.json": "tracks", "camera.json": "camera"}
FIXES = (  # (text in the reason, fix), first match wins
    ("NaN or infinity", "write finite numbers; Part 2's writers never emit NaN or infinity"),
    ("too large", "write finite numbers; Part 2's writers never emit NaN or infinity"),
    (".t_ms", "give every frame a t_ms (part2 frames writes it)"),
    ("duplicate id", "give each person one id per frame"),
    ("strictly increasing", "number the frames in increasing order"),
    (".mirrored", "set mirrored to true or false, or leave it out"),
)
DEFAULT_FIX = "follow the schema: python -m part2 contract --schema pose3d"


class DoctorError(ValueError):
    """The file cannot be diagnosed: not JSON, or not a Part 2 file (exit 2)."""


def read_json(path):
    try:
        raw = Path(path).read_bytes()
    except OSError as e:
        raise DoctorError(f"{path}: cannot read ({e.strerror or e})") from None
    try:
        return json.loads(raw.decode("utf-8-sig"))  # a UTF-8 byte order mark is ignored, as Part 6 does
    except UnicodeDecodeError as e:
        line = raw.count(b"\n", 0, e.start) + 1
        raise DoctorError(f"{path}: not JSON (line {line})") from None
    except json.JSONDecodeError as e:
        raise DoctorError(f"{path}: not JSON (line {e.lineno})") from None
    except RecursionError:
        raise DoctorError(f"{path}: not JSON (nested too deeply)") from None


def detect(doc, path) -> tuple[str, str]:
    """(kind, how it was told): by shape, else by file name, else assumed pose3d."""
    if not isinstance(doc, dict) or not isinstance(doc.get("frames"), list):
        raise DoctorError(f"{path}: not a Part 2 file (no frames list)")
    if "K" in doc and "camera_frame" in doc:
        return "camera", "by shape"
    frames = [f for f in doc["frames"] if isinstance(f, dict)]
    people = list(people_in(doc))
    if any("joints" in p for p in people) or any("people" in f and "t_ms" in f for f in frames):
        return "pose3d", "by shape"
    if any("bbox" in p or "mask_rle" in p for p in people):
        return "tracks", "by shape"
    if frames and all("file" in f and "people" not in f for f in frames):
        return "frames", "by shape"
    hint = NAME_HINTS.get(Path(path).name)
    return (hint, "by file name") if hint else ("pose3d", "assumed: no people to tell the kinds apart")


def diagnose(path, consumer=None) -> dict:
    """{"kind", "version", "detected_by", "findings": [{consumer, verdict, reason, fix}], ...}.
    Raises DoctorError for a file of no known kind and for an unknown consumer."""
    if consumer is not None and consumer not in CONSUMERS:
        raise DoctorError(f"doctor: unknown consumer '{consumer}'; choose part3, part5 or part6")
    doc = read_json(path)
    kind, how = detect(doc, path)
    asked = [consumer] if consumer else list(CONSUMERS)
    findings = [RULES[c](doc, kind) for c in asked]
    decider = next(f for f in findings if f["consumer"] == (consumer or "part3"))
    return {"file": str(path), "kind": kind, "version": contract.version(kind), "detected_by": how,
            "people": len(_ids(doc)), "frames": len(doc["frames"]), "findings": findings,
            "schema_error": _schema_error(doc, kind), "extra_joints": _extra_joints(doc, kind),
            "warnings": _warnings(doc), "exit": 1 if decider["verdict"] == REJECTS else 0}


def render(result: dict) -> list[str]:
    """The lines doctor prints: a header, one line per finding, then schema, extra-joint and time-join notes."""
    n, m = result["people"], result["frames"]
    counts = f"{m} frame{'s' * (m != 1)}"
    if result["kind"] != "frames":
        counts = f"{n} {'person' if n == 1 else 'people'}, {counts}"
    lines = [f"{result['file']}: kind {result['kind']}, version {result['version']} ({result['detected_by']}), {counts}"]
    lines += [_line(f) for f in result["findings"]]
    if result["schema_error"]:
        lines.append(f"schema: breaks {result['version']} at {result['schema_error']}")
    extra = result.get("extra_joints")
    if extra:
        lines.append(f"extra joints: {', '.join(extra['names'])} on {extra['person_frames']} of {extra['of']} "
                     "person-frames (optional extra_joints beside the 17 joints)")
    return lines + result["warnings"]


def command(path, consumer=None, as_json=False) -> int:
    """python -m part2 doctor; prints and returns the exit code. No input gives a stack trace."""
    try:
        result = diagnose(path, consumer)
    except (DoctorError, RecursionError) as e:
        message = str(e) if isinstance(e, DoctorError) else f"{path}: not a Part 2 file (nested too deeply)"
        if as_json:
            print(json.dumps({"file": str(path), "error": message, "exit": 2}))
        else:
            print(message, file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2) if as_json else "\n".join(render(result)))
    return result["exit"]


# --- consumers ----------------------------------------------------------------------------------

def _part3(doc, kind) -> dict:
    if kind != "pose3d":
        return _finding("part3", REJECTS, f"Part 3 reads pose3d.json, not {kind}.json",
                        "give it pose3d.json or a pose3d_person_<id>.json from the same run")
    options, notes, candidate = [], [], doc
    if _lacks_t_ms(doc):  # Part 3's derive-t_ms adapter
        if is_number(doc.get("fps")) and doc["fps"] > 0:
            notes.append("no t_ms; Part 3 derives it from the top-level fps")
        else:
            options.append(("no t_ms", "python3 -m part3 run ... --input-fps <n> or add a top-level fps"))
        candidate = {**doc, "frames": [{**f, "t_ms": 0.0} for f in doc["frames"]]}
    try:
        contract.validate_part3(candidate)
    except ContractError as e:
        return _finding("part3", REJECTS, str(e), next((fix for text, fix in FIXES if text in str(e)), DEFAULT_FIX))
    ids = _ids(doc)
    if not ids:
        return _finding("part3", REJECTS, "no person in any frame", "run Part 2 on a clip in which a person is visible")
    if len(ids) > 1:
        options.append(("several people", "python3 -m part3 run ... --person <id> or --all-people"))
    if doc.get("mirrored") is True:
        notes.append("mirrored: Part 3 --flip auto mirrors left and right")
    if options:
        return _finding("part3", OPTION, "; ".join(r for r, _ in options), "; ".join(f for _, f in options))
    return _finding("part3", ACCEPTS, "; ".join(notes))


def _part5(doc, kind) -> dict:
    what = "skeleton.json" if kind == "pose3d" else f"skeleton.json, not {kind}.json"
    return _finding("part5", REJECTS, f"Part 5 reads {what}", "run Part 3 first (--view part5)")


def _part6(doc, kind) -> dict:
    if kind != "pose3d":
        return _finding("part6", REJECTS, f"{kind}.json holds no joints and Part 6 has no Part 2 kind", "give it pose3d.json")
    try:
        check_finite(doc, "pose3d")  # Part 6 reads JSON strictly: NaN, Infinity and 1e400 are not JSON
    except ContractError as e:
        return _finding("part6", REJECTS, f"{e.path}: {e.msg} (Part 6 refuses the file as not valid JSON)",
                        "write finite numbers")
    played = [_played(f) for f in doc["frames"] if isinstance(f, dict)]
    played = [p for p in played if p is not None]
    if not played:
        return _finding("part6", REJECTS, "no person in any frame", "run Part 2 on a clip in which a person is visible")
    for person in played:
        problem = _joint_problem(person)
        if problem:
            return _finding("part6", REJECTS, problem, "write all 17 joints as {x, y, z, conf} with finite numbers")
    zero = [_is_zero(p.get("id")) for p in played]
    who = ("person id 0 played" if all(zero) else "the first person of each frame played" if not any(zero)
           else "person id 0 played where present, else the first")
    return _finding("part6", ACCEPTS, f"generic reader: 17 joints, finite numbers, {who}")


RULES = {"part3": _part3, "part5": _part5, "part6": _part6}


# --- helpers ------------------------------------------------------------------------------------

def _finding(consumer, verdict, reason="", fix="") -> dict:
    return {"consumer": consumer, "verdict": verdict, "reason": reason, "fix": fix}


def _line(f: dict) -> str:
    name = CONSUMERS[f["consumer"]]
    if f["verdict"] == ACCEPTS:
        return f"{name}: accepts" + (f" ({f['reason']})" if f["reason"] else "")
    return f"{name}: {f['verdict']}: {f['reason']}" + (f"; fix: {f['fix']}" if f["fix"] else "")


def people_in(doc):
    """Every person dict of every frame of a Part 2 document, in file order; a frame or person that is not an object,
    or a frame without a people list, is skipped. Public: part2.foot_check reads files the same way."""
    for f in doc.get("frames", []):
        if isinstance(f, dict) and isinstance(f.get("people"), list):
            yield from (p for p in f["people"] if isinstance(p, dict))


def _ids(doc) -> set:
    return {json.dumps(p.get("id")) for p in people_in(doc)}


def _lacks_t_ms(doc) -> bool:
    frames = doc["frames"]
    return bool(frames) and all(isinstance(f, dict) and "t_ms" not in f for f in frames)


def _schema_error(doc, kind) -> str | None:
    try:
        contract.validate(doc, kind)
    except ContractError as e:
        return str(e)
    return None


def _extra_joints(doc, kind) -> dict | None:
    """{names, person_frames, of}: the foot points a pose3d file carries in the optional `extra_joints` (TICKET-043),
    names in part2.joints.EXTRA order (any other name after them, sorted); None when no person carries any."""
    if kind != "pose3d":
        return None
    people = list(people_in(doc))
    carrying = [p for p in people if isinstance(p.get("extra_joints"), dict) and p["extra_joints"]]
    if not carrying:
        return None
    seen = {str(n) for p in carrying for n in p["extra_joints"]}
    return {"names": [n for n in EXTRA if n in seen] + sorted(seen - set(EXTRA)),
            "person_frames": len(carrying), "of": len(people)}


def _warnings(doc) -> list[str]:
    t0 = doc.get("t0_pts_ms")
    if is_number(t0) and t0 != 0:
        return [f"warning: t0_pts_ms is {t0}; a consumer joining on file time (Part 1) must add it to t_ms"]
    return []


def _is_zero(pid) -> bool:
    return pid == 0 and not isinstance(pid, bool)


def _played(frame: dict):
    """The person Part 6's generic reader plays in a frame: id 0, else the first."""
    people = [p for p in frame.get("people", []) if isinstance(p, dict)] if isinstance(frame.get("people"), list) else []
    return next((p for p in people if _is_zero(p.get("id"))), people[0] if people else None)


def _joint_problem(person: dict) -> str | None:
    joints = person.get("joints")
    if not isinstance(joints, dict):
        return f"person {person.get('id')!r} has no joints object"
    for name in CANONICAL:
        j = joints.get(name)
        xyz = [j.get(k) for k in "xyz"] if isinstance(j, dict) else j[:3] if isinstance(j, list) and len(j) >= 3 else None
        if xyz is None or not all(is_number(v) for v in xyz):
            return f"person {person.get('id')!r}: joint {name} is missing or has no finite x, y, z"
    return None
