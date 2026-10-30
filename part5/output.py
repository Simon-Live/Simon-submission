"""The output contract: `analysis.json` (`simon.analysis.v1`), documented in docs/schemas.md.

`build_analysis` maps detected faults (`part5.detect.Fault`) plus their plain-words lines
(`part5.words.describe`) onto the schema Part 7 consumes. `validate_analysis` checks a document
against the contract and raises `OutputError` naming the file and field, mirroring `part5.io`.
Unknown extra fields are allowed, so the format can grow without breaking older readers.
"""
import json
import math
import re
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from .guard import DIFFERENT_MOVEMENT, OK
from .io import JOINTS
from .measures import MEASURES
from .lateral import lateral_for
from .words import describe, describe_timed

FORMAT = "simon.analysis.v1"
SCHEMA_VERSION = "1.2.0"
SCHEMA_VERSION_REPS = "1.3.0"   # a document with the rep fields (ADR-0010); one without stays 1.2.0
SCHEMA_VERSION_RE = re.compile(r"^1\.[0-9]+\.[0-9]+$")
STATUS_CODES = (OK, DIFFERENT_MOVEMENT)
UNIT = "degrees"
SIDES = ("left", "right", "both", "center")
DIRECTIONS = ("more", "less")
NO_SCORE = object()  # build_analysis(score=NO_SCORE): no `score` key at all
LATERALS = ("left", "right", None)


class OutputError(ValueError):
    """An analysis document breaks the contract; the message says where."""


def _spec(measure, side):
    """The MEASURES spec for a side-less measure name and a fault side."""
    name = {"left": f"left_{measure}", "right": f"right_{measure}",
            "both": f"left_{measure}", "center": measure}.get(side, measure)
    return MEASURES.get(name)


def _joint_for(measure, side):
    spec = _spec(measure, side)
    if spec is None:
        return None
    return spec.joint.removeprefix("left_") if side == "both" else spec.joint


def generic_measures():
    """Side-less measure names a fault may report (the `measure` vocabulary)."""
    out = []
    for name in MEASURES:
        g = name[len("left_"):] if name.startswith("left_") else \
            name[len("right_"):] if name.startswith("right_") else name
        if g not in out:
            out.append(g)
    return out


GENERIC_MEASURES = generic_measures()


def round_half_up_tenth(seconds):
    """`seconds` to 0.1 s, halves up, decimal-safe (1.85 → 1.9, 1.849 → 1.8)."""
    return float(Decimal(repr(round(float(seconds), 3))).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def fault_to_dict(fault, times=None):
    """One `detect.Fault` → its `analysis.json` fault object, text included.

    `times`, if given, is `{follower_t_s, follower_runs, lateral_m?}` (ADR-0009): the 1.2.0
    time fields. `lateral` and `text_timed` follow from the fault and `at_s`.
    """
    spec = _spec(fault.measure, fault.side)
    d = {
        "measure": fault.measure,
        "measure_kind": spec.kind if spec else None,
        "joint": fault.joint,
        "body_part": fault.body_part,
        "side": fault.side,
        "direction": fault.direction,
        "magnitude_deg": float(fault.magnitude_deg),
        "peak_deg": float(fault.peak_deg),
        "threshold_deg": float(fault.threshold_deg),
        "unit": UNIT,
        "expected_frames": [int(fault.expected_frames[0]), int(fault.expected_frames[1])],
        "follower_frames": [int(fault.follower_frames[0]), int(fault.follower_frames[1])],
        "runs": [[int(a), int(b)] for a, b in fault.runs],
        "phase": [float(fault.phase[0]), float(fault.phase[1])],
        "coverage": float(fault.coverage),
        "confidence": float(fault.confidence),
        "text": describe(fault),
    }
    if times is not None:
        t0, t1 = (round(float(x), 3) for x in times["follower_t_s"])
        d["follower_t_s"] = [t0, t1]
        d["at_s"] = round_half_up_tenth(t0)
        d["follower_runs"] = [[int(a), int(b)] for a, b in times["follower_runs"]]
        d["lateral"] = lateral_for(fault.measure, fault.direction, fault.side)
        if times.get("lateral_m") is not None:
            d["lateral_m"] = float(times["lateral_m"])
        d["text_timed"] = f"{describe_timed(fault)} at {d['at_s']:.1f} s"
        if times.get("reps") is not None:
            d["reps"] = [int(i) for i in times["reps"]]
    return d


def _input_ref(ref, key):
    if isinstance(ref, (str, Path)):
        return {"path": str(ref)}
    if isinstance(ref, dict):
        return dict(ref)
    raise OutputError(f"{key} must be a path or an object with a 'path', got {ref!r}")


def build_analysis(expected, follower, faults, diagnostics=None, status=None, times=None, score=NO_SCORE):
    """Assemble a validated analysis document.

    `expected`/`follower` identify the input clips: a path, or an object with at least
    `path` (extra ids like `take_id`/`set`/`movement` pass through). `faults` are
    `detect.Fault` objects (already sorted); an empty sequence means a correct take.
    `status`, if given, is `{code, text}`: a refused take (`different_movement`) has no faults.
    `diagnostics`, if given, is carried as an optional object Part 7 may ignore.
    `times` is one `fault_to_dict` times entry per fault (1.2.0 time fields). `score` is the
    `score` block (a dict, or None for a refused take); left out entirely when not given.
    """
    times = times if times is not None else [None] * len(faults)
    try:
        faults = [fault_to_dict(f, t) for f, t in zip(faults, times, strict=True)]
    except (AttributeError, KeyError, TypeError, ValueError) as e:
        raise OutputError(f"<built analysis>: cannot build a fault object ({e})") from e
    by_reps = any("reps" in f for f in faults) or "reps" in (diagnostics or {}).get("guard", {})
    doc = {"format": FORMAT,
           "schema_version": SCHEMA_VERSION_REPS if by_reps else SCHEMA_VERSION,
           "expected": _input_ref(expected, "expected"),
           "follower": _input_ref(follower, "follower")}
    if status is not None:
        doc["status"] = dict(status)
    doc["faults"] = faults
    if diagnostics is not None:
        doc["diagnostics"] = diagnostics
    if score is not NO_SCORE:
        doc["score"] = score
    return validate_analysis(doc, source="<built analysis>")


def write_analysis(path, analysis):
    doc = validate_analysis(analysis, source=str(path))
    try:
        text = json.dumps(doc, indent=2, allow_nan=False) + "\n"
    except (TypeError, ValueError) as e:
        raise OutputError(f"{path}: analysis is not JSON-serialisable ({e})") from e
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(text)
    return doc


def load_analysis(path):
    path = Path(path)
    try:
        doc = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        raise OutputError(f"{path}: cannot read JSON ({e})") from e
    return validate_analysis(doc, source=str(path))


def _is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def validate_analysis(doc, source="<analysis>"):
    def fail(msg):
        raise OutputError(f"{source}: {msg}")

    if not isinstance(doc, dict):
        fail("top level must be an object")
    if doc.get("format") != FORMAT:
        fail(f"format must be {FORMAT!r}, got {doc.get('format')!r}")
    for key in ("expected", "follower"):
        ref = doc.get(key)
        if not isinstance(ref, dict) or not isinstance(ref.get("path"), str) or not ref["path"]:
            fail(f"{key} must be an object with a non-empty string 'path'")
    if "diagnostics" in doc and not isinstance(doc["diagnostics"], dict):
        fail("diagnostics must be an object")
    version = doc.get("schema_version")
    if "schema_version" in doc and not (isinstance(version, str) and SCHEMA_VERSION_RE.match(version)):
        fail(f"schema_version must look like '1.2.0', got {version!r}")
    faults = doc.get("faults")
    if not isinstance(faults, list):
        fail("faults must be a list")
    if "status" in doc:
        _validate_status(doc["status"], faults, fail)
    for i, f in enumerate(faults):
        _validate_fault(f, f"faults[{i}]", fail)
    if "phrasing" in doc:
        _validate_phrasing(doc["phrasing"], len(faults), fail)
    if "score" in doc and doc["score"] is not None and not isinstance(doc["score"], dict):
        fail("score must be an object or null")
    if isinstance(doc.get("score"), dict) and doc.get("status", {}).get("code") == DIFFERENT_MOVEMENT:
        fail("score must be null for a refused take")
    try:  # nothing anywhere (incl. diagnostics/extras) may make this invalid JSON downstream
        json.dumps(doc, allow_nan=False)
    except (TypeError, ValueError) as e:
        fail(f"document is not JSON-serialisable ({e})")
    return doc


def _validate_status(status, faults, fail):
    if not isinstance(status, dict):
        fail("status must be an object")
    if status.get("code") not in STATUS_CODES:
        fail(f"status.code must be one of {STATUS_CODES}, got {status.get('code')!r}")
    if not isinstance(status.get("text"), str) or not status["text"]:
        fail("status.text must be a non-empty string")
    if status["code"] == DIFFERENT_MOVEMENT and faults:
        fail(f"status.code {DIFFERENT_MOVEMENT!r} goes with faults [], got {len(faults)} fault(s)")


def _validate_runs(runs, where, fail, key="runs"):
    ok = (isinstance(runs, (list, tuple)) and runs
          and all(isinstance(r, (list, tuple)) and len(r) == 2 and all(_is_int(x) for x in r)
                  and 0 <= r[0] <= r[1] for r in runs))
    if not ok:
        fail(f"{where}.{key} must be a non-empty list of [start, end] integer frames with 0 <= start <= end, "
             f"got {runs!r}")


def _validate_fault(f, where, fail):
    if not isinstance(f, dict):
        fail(f"{where} must be an object")
    measure, side = f.get("measure"), f.get("side")
    if measure not in GENERIC_MEASURES:
        fail(f"{where}.measure must be one of {GENERIC_MEASURES}, got {measure!r}")
    if side not in SIDES:
        fail(f"{where}.side must be one of {SIDES}, got {side!r}")
    spec = _spec(measure, side)
    if spec is None:
        fail(f"{where}: side {side!r} does not go with measure {measure!r}")
    if f.get("measure_kind") != spec.kind:
        fail(f"{where}.measure_kind must be {spec.kind!r} for {measure}, got {f.get('measure_kind')!r}")
    want_joint = _joint_for(measure, side)
    if f.get("joint") != want_joint:
        fail(f"{where}.joint must be {want_joint!r} for {measure}/{side}, got {f.get('joint')!r}")
    if f.get("body_part") != spec.body_part:
        fail(f"{where}.body_part must be {spec.body_part!r} for {measure}, got {f.get('body_part')!r}")
    if f.get("direction") not in DIRECTIONS:
        fail(f"{where}.direction must be one of {DIRECTIONS}, got {f.get('direction')!r}")
    if _is_number(f.get("magnitude_deg")) and _is_number(f.get("peak_deg")):
        positive = f["magnitude_deg"] > 0 and f["peak_deg"] > 0
        negative = f["magnitude_deg"] < 0 and f["peak_deg"] < 0
        if (f["direction"] == "more") != positive or (f["direction"] == "less") != negative:
            fail(f"{where}: direction {f['direction']!r} disagrees with the signed "
                 f"magnitude_deg {f['magnitude_deg']!r} / peak_deg {f['peak_deg']!r} "
                 "(more ⇔ positive, less ⇔ negative)")
    if f.get("unit") != UNIT:
        fail(f"{where}.unit must be {UNIT!r}, got {f.get('unit')!r}")
    for key in ("magnitude_deg", "peak_deg", "threshold_deg"):
        if not _is_number(f.get(key)):
            fail(f"{where}.{key} must be a finite number, got {f.get(key)!r}")
    if f["threshold_deg"] <= 0:
        fail(f"{where}.threshold_deg must be positive, got {f['threshold_deg']!r}")
    for key in ("coverage", "confidence"):
        if not _is_number(f.get(key)) or not 0 <= f[key] <= 1:
            fail(f"{where}.{key} must be a number in 0..1, got {f.get(key)!r}")
    for key in ("expected_frames", "follower_frames"):
        v = f.get(key)
        if not (isinstance(v, (list, tuple)) and len(v) == 2 and all(_is_int(x) for x in v)):
            fail(f"{where}.{key} must be [start, end] integer frames, got {v!r}")
        if v[0] < 0 or v[1] < v[0]:
            fail(f"{where}.{key} must satisfy 0 <= start <= end, got {v!r}")
    if "runs" in f:
        _validate_runs(f["runs"], where, fail)
    phase = f.get("phase")
    if not (isinstance(phase, (list, tuple)) and len(phase) == 2 and all(_is_number(x) for x in phase)):
        fail(f"{where}.phase must be [start, end] numbers in 0..1, got {phase!r}")
    if not 0 <= phase[0] <= phase[1] <= 1:
        fail(f"{where}.phase must satisfy 0 <= start <= end <= 1, got {phase!r}")
    if not isinstance(f.get("text"), str) or not f["text"]:
        fail(f"{where}.text must be a non-empty string")
    if "joints" in f:
        joints = f["joints"]
        if not (isinstance(joints, list) and joints and all(j in JOINTS for j in joints)):
            fail(f"{where}.joints must be a non-empty list of canonical joint names, got {joints!r}")
    _validate_times(f, where, fail)
    if "coaching" in f and (not isinstance(f["coaching"], str) or not f["coaching"]):
        fail(f"{where}.coaching must be a non-empty string")


def _validate_phrasing(record, n_faults, fail):
    """The phrasing record: who phrased each coaching line and why a fault fell back (ADR-0005)."""
    if not isinstance(record, dict) or not isinstance(record.get("backend"), str):
        fail("phrasing must be an object with a string 'backend'")
    per_fault = record.get("faults")
    if not isinstance(per_fault, list) or len(per_fault) != n_faults:
        fail(f"phrasing.faults must hold one entry per fault ({n_faults}), got {per_fault!r}")


def _validate_times(f, where, fail):
    """The optional 1.2.0 fields of a fault (ADR-0009); a 1.1.0 fault has none of them."""
    if "follower_t_s" in f:
        v = f["follower_t_s"]
        if not (isinstance(v, (list, tuple)) and len(v) == 2 and all(_is_number(x) for x in v) and v[0] <= v[1]):
            fail(f"{where}.follower_t_s must be [start_s, end_s] numbers with start <= end, got {v!r}")
    if "at_s" in f and not _is_number(f["at_s"]):
        fail(f"{where}.at_s must be a number, got {f['at_s']!r}")
    if "follower_runs" in f:
        _validate_runs(f["follower_runs"], where, fail, "follower_runs")
        if "runs" in f and len(f["follower_runs"]) != len(f["runs"]):
            fail(f"{where}.follower_runs must have one entry per run ({len(f['runs'])}), got {len(f['follower_runs'])}")
    if "lateral" in f and f["lateral"] not in LATERALS:
        fail(f"{where}.lateral must be 'left', 'right' or null, got {f['lateral']!r}")
    if "lateral_m" in f and not _is_number(f["lateral_m"]):
        fail(f"{where}.lateral_m must be a number, got {f['lateral_m']!r}")
    if "text_timed" in f and (not isinstance(f["text_timed"], str) or not f["text_timed"]):
        fail(f"{where}.text_timed must be a non-empty string")
    if "reps" in f:
        v = f["reps"]
        if not (isinstance(v, list) and v and all(_is_int(x) and x >= 0 for x in v)):
            fail(f"{where}.reps must be a non-empty list of rep indices (integers from 0), got {v!r}")
