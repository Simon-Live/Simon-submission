"""The output contract: `analysis.json` (`simon.analysis.v1`), documented in docs/schemas.md.

`build_analysis` maps detected faults (`part5.detect.Fault`) plus their plain-words lines
(`part5.words.describe`) onto the schema Part 7 consumes. `validate_analysis` checks a document
against the contract and raises `OutputError` naming the file and field, mirroring `part5.io`.
Unknown extra fields are allowed, so the format can grow without breaking older readers.
"""
import json
import math
from pathlib import Path

from .measures import MEASURES
from .words import describe

FORMAT = "simon.analysis.v1"
UNIT = "degrees"
SIDES = ("left", "right", "both", "center")
DIRECTIONS = ("more", "less")


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


def fault_to_dict(fault):
    """One `detect.Fault` → its `analysis.json` fault object, text included."""
    spec = _spec(fault.measure, fault.side)
    return {
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
        "phase": [float(fault.phase[0]), float(fault.phase[1])],
        "coverage": float(fault.coverage),
        "confidence": float(fault.confidence),
        "text": describe(fault),
    }


def _input_ref(ref):
    return {"path": str(ref)} if isinstance(ref, (str, Path)) else dict(ref)


def build_analysis(expected, follower, faults, diagnostics=None):
    """Assemble a validated analysis document.

    `expected`/`follower` identify the input clips: a path, or an object with at least
    `path` (extra ids like `take_id`/`set`/`movement` pass through). `faults` are
    `detect.Fault` objects (already sorted); an empty sequence means a correct take.
    `diagnostics`, if given, is carried as an optional object Part 7 may ignore.
    """
    doc = {"format": FORMAT,
           "expected": _input_ref(expected),
           "follower": _input_ref(follower),
           "faults": [fault_to_dict(f) for f in faults]}
    if diagnostics is not None:
        doc["diagnostics"] = diagnostics
    return validate_analysis(doc, source="<built analysis>")


def write_analysis(path, analysis):
    doc = validate_analysis(analysis, source=str(path))
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(doc, indent=2) + "\n")
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
    faults = doc.get("faults")
    if not isinstance(faults, list):
        fail("faults must be a list")
    for i, f in enumerate(faults):
        _validate_fault(f, f"faults[{i}]", fail)
    return doc


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
    phase = f.get("phase")
    if not (isinstance(phase, (list, tuple)) and len(phase) == 2 and all(_is_number(x) for x in phase)):
        fail(f"{where}.phase must be [start, end] numbers in 0..1, got {phase!r}")
    if not 0 <= phase[0] <= phase[1] <= 1:
        fail(f"{where}.phase must satisfy 0 <= start <= end <= 1, got {phase!r}")
    if not isinstance(f.get("text"), str) or not f["text"]:
        fail(f"{where}.text must be a non-empty string")
