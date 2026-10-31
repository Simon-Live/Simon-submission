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

from .guard import (DIFFERENT_MOVEMENT, LOW_MATCH, MOVING_PART_OUT_OF_FRAME, NO_USABLE_MEASURES, NOT_ENOUGH_VISIBLE,
                    OK)
from .io import JOINTS
from .measures import ALL_SPECS, FOOT_MEASURES
from .cues import KINDS as CUE_KINDS
from .cues import MAX_WORDS as CUE_MAX_WORDS
from .cues import cue_for
from . import profiles
from .insights import MAX_INSIGHTS, insights_of
from .lateral import lateral_for
from .words import describe, describe_timed

FORMAT = "simon.analysis.v1"
# 1.2.0 time fields (ADR-0009), 1.3.0 rep fields (ADR-0010), 1.4.0 warnings and match (ADR-0012). From 1.5.0
# (ADR-0014) every new document carries cues and `insights`, so every new document is 1.5.0; a reader tells
# the earlier groups apart by their fields, which stay optional. 1.6.0 (ADR-0015) adds the foot measures
# `foot_rotation` and `ankle_inversion` (body part "feet") and `diagnostics.feet`; every new document is 1.6.0.
# 1.7.0 (ADR-0016) adds `profile`, the analysis profile that produced the document (always present in a new one).
SCHEMA_VERSION = "1.7.0"
SCHEMA_VERSION_RE = re.compile(r"^1\.[0-9]+\.[0-9]+$")
PROFILE_SINCE = (1, 7, 0)   # from this schema version on, `profile` is required
# Status codes of documents written before ADR-0012 (no faults, no score); a new analysis is always "ok".
REFUSED_CODES = (DIFFERENT_MOVEMENT, NOT_ENOUGH_VISIBLE, MOVING_PART_OUT_OF_FRAME)
STATUS_CODES = (OK, *REFUSED_CODES)
WARNING_CODES = (LOW_MATCH, MOVING_PART_OUT_OF_FRAME, NOT_ENOUGH_VISIBLE, NO_USABLE_MEASURES)
LOW_CONFIDENCE = "low"   # a fault's `confidence` on a low match (ADR-0012)
UNIT = "degrees"
SIDES = ("left", "right", "both", "center")
DIRECTIONS = ("more", "less")
NO_SCORE = object()  # build_analysis(score=NO_SCORE): no `score` key at all
LATERALS = ("left", "right", None)


class OutputError(ValueError):
    """An analysis document breaks the contract; the message says where."""


def _spec(measure, side):
    """The spec (body or foot measure) for a side-less measure name and a fault side."""
    name = {"left": f"left_{measure}", "right": f"right_{measure}",
            "both": f"left_{measure}", "center": measure}.get(side, measure)
    return ALL_SPECS.get(name)


def _joint_for(measure, side):
    spec = _spec(measure, side)
    if spec is None:
        return None
    return spec.joint.removeprefix("left_") if side == "both" else spec.joint


def generic_measures():
    """Side-less measure names a fault may report (the `measure` vocabulary)."""
    out = []
    for name in ALL_SPECS:
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
    d["cue"], d["cue_kind"] = cue_for(fault.measure, fault.direction, fault.side)   # ADR-0014
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


def build_analysis(expected, follower, faults, diagnostics=None, status=None, times=None, score=NO_SCORE,
                   warnings=None, match=None, profile=profiles.IDENTITY):
    """Assemble a validated analysis document.

    `expected`/`follower` identify the input clips: a path, or an object with at least
    `path` (extra ids like `take_id`/`set`/`movement` pass through). `faults` are
    `detect.Fault` objects (already sorted); an empty sequence means a correct take.
    `status`, if given, is `{code, text}`; a new document is always `ok` (ADR-0012: every take is analysed, a
    poor one carries `warnings` and an F cap, never a refusal). Only a document written before ADR-0012 can
    still carry a refusal status (`different_movement`, which has no faults).
    `diagnostics`, if given, is carried as an optional object Part 7 may ignore.
    `times` is one `fault_to_dict` times entry per fault (1.2.0 time fields). `score` is the
    `score` block (a dict, or None in a document written before ADR-0012); left out entirely when not given.
    `warnings` (`[{code, text}]`) and `match` (`{quality, residual, timing_corr, limits}`) are the 1.4.0 fields
    (ADR-0012): given with at least one warning, the document is 1.4.0, and on a low match every fault's
    `confidence` is "low". Without warnings the document is exactly what it was.
    `profile` (1.7.0, ADR-0016) names the analysis profile and is written into every document, after `schema_version`;
    `fitness`, the default, is today's analysis.
    """
    times = times if times is not None else [None] * len(faults)
    try:
        faults = [fault_to_dict(f, t) for f, t in zip(faults, times, strict=True)]
    except (AttributeError, KeyError, TypeError, ValueError) as e:
        raise OutputError(f"<built analysis>: cannot build a fault object ({e})") from e
    warned = bool(warnings)
    if warned and (match or {}).get("quality") == "low":
        for f in faults:
            f["confidence"] = LOW_CONFIDENCE
    doc = {"format": FORMAT,
           "schema_version": SCHEMA_VERSION,
           "profile": profile,
           "expected": _input_ref(expected, "expected"),
           "follower": _input_ref(follower, "follower")}
    if status is not None:
        doc["status"] = dict(status)
    doc["faults"] = faults
    if warned:
        doc["warnings"] = [dict(w) for w in warnings]
        doc["match"] = match
    if diagnostics is not None:
        doc["diagnostics"] = diagnostics
    if score is not NO_SCORE:
        doc["score"] = score
    doc["insights"] = insights_of(doc)
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
    if "feet" in doc.get("diagnostics", {}):
        _validate_feet(doc["diagnostics"]["feet"], fail)
    version = doc.get("schema_version")
    if "schema_version" in doc and not (isinstance(version, str) and SCHEMA_VERSION_RE.match(version)):
        fail(f"schema_version must look like '1.2.0', got {version!r}")
    _validate_profile(doc, version, fail)
    faults = doc.get("faults")
    if not isinstance(faults, list):
        fail("faults must be a list")
    if "status" in doc:
        _validate_status(doc["status"], faults, fail)
    for i, f in enumerate(faults):
        _validate_fault(f, f"faults[{i}]", fail)
    if "warnings" in doc:
        _validate_warnings(doc["warnings"], doc.get("match"), fail)
    if "phrasing" in doc:
        _validate_phrasing(doc["phrasing"], len(faults), fail)
    if "score" in doc and doc["score"] is not None and not isinstance(doc["score"], dict):
        fail("score must be an object or null")
    if "insights" in doc:
        _validate_insights(doc["insights"], fail)
    if isinstance(doc.get("score"), dict) and doc.get("status", {}).get("code") in REFUSED_CODES:
        fail("score must be null for a refused take")
    try:  # nothing anywhere (incl. diagnostics/extras) may make this invalid JSON downstream
        json.dumps(doc, allow_nan=False)
    except (TypeError, ValueError) as e:
        fail(f"document is not JSON-serialisable ({e})")
    return doc


def _validate_profile(doc, version, fail):
    """The 1.7.0 `profile` (ADR-0016): a non-empty string, required from 1.7.0 on; a document before it has none
    and is read as `fitness`. Which names exist is data in part5/profiles.json, not checked here."""
    if "profile" in doc and not (isinstance(doc["profile"], str) and doc["profile"]):
        fail(f"profile must be a non-empty string, got {doc['profile']!r}")
    since_1_7 = isinstance(version, str) and tuple(map(int, version.split("."))) >= PROFILE_SINCE
    if since_1_7 and "profile" not in doc:
        fail(f"profile is required from schema_version {'.'.join(map(str, PROFILE_SINCE))}")


def _validate_feet(feet, fail):
    """The 1.6.0 `diagnostics.feet` (ADR-0015): each clip's feet file, the foot measures compared and why not."""
    where = "diagnostics.feet"
    if not isinstance(feet, dict):
        fail(f"{where} must be an object")
    for key in ("expected", "follower"):
        side = feet.get(key)
        ok = (isinstance(side, dict) and (side.get("source") is None or isinstance(side["source"], str))
              and _is_int(side.get("person")) and _is_int(side.get("frames_matched"))
              and isinstance(side.get("usable"), list) and all(m in FOOT_MEASURES for m in side["usable"]))
        if not ok:
            fail(f"{where}.{key} must be {{source, person, frames_matched, usable}} with usable foot measure names, "
                 f"got {side!r}")
    compared = feet.get("compared")
    if not (isinstance(compared, list) and all(m in FOOT_MEASURES for m in compared)):
        fail(f"{where}.compared must be a list of foot measure names {list(FOOT_MEASURES)}, got {compared!r}")
    reason = feet.get("hidden_reason")
    if reason is not None and not (isinstance(reason, str) and reason):
        fail(f"{where}.hidden_reason must be a non-empty string or null, got {reason!r}")


def _validate_warnings(warnings, match, fail):
    """The 1.4.0 `warnings` and `match` (ADR-0012)."""
    if not (isinstance(warnings, list) and warnings):
        fail("warnings must be a non-empty list of {code, text}")
    for i, w in enumerate(warnings):
        if not isinstance(w, dict) or w.get("code") not in WARNING_CODES:
            fail(f"warnings[{i}].code must be one of {WARNING_CODES}, got {(w or {}).get('code') if isinstance(w, dict) else w!r}")
        if not isinstance(w.get("text"), str) or not w["text"]:
            fail(f"warnings[{i}].text must be a non-empty string")
    if not isinstance(match, dict) or match.get("quality") not in ("ok", "low"):
        fail("match must be an object with quality 'ok' or 'low' when there are warnings")
    for key in ("residual", "timing_corr"):
        if match.get(key) is not None and not _is_number(match[key]):
            fail(f"match.{key} must be a number or null, got {match[key]!r}")
    if not isinstance(match.get("limits"), dict):
        fail("match.limits must be an object")


def _validate_status(status, faults, fail):
    if not isinstance(status, dict):
        fail("status must be an object")
    if status.get("code") not in STATUS_CODES:
        fail(f"status.code must be one of {STATUS_CODES}, got {status.get('code')!r}")
    if not isinstance(status.get("text"), str) or not status["text"]:
        fail("status.text must be a non-empty string")
    if status["code"] in REFUSED_CODES and faults:
        fail(f"status.code {status['code']!r} goes with faults [], got {len(faults)} fault(s)")


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
        if key == "confidence" and f.get(key) == LOW_CONFIDENCE:
            continue
        if not _is_number(f.get(key)) or not 0 <= f[key] <= 1:
            fail(f"{where}.{key} must be a number in 0..1{' or \"low\"' if key == 'confidence' else ''}, got {f.get(key)!r}")
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
    _validate_cue(f, where, fail, kinds=("position", "range"))


def _validate_cue(item, where, fail, kinds=CUE_KINDS, kind_key="cue_kind"):
    """The 1.5.0 `cue` and its kind (ADR-0014): both or neither."""
    if "cue" not in item and kind_key not in item:
        return
    cue = item.get("cue")
    if not isinstance(cue, str) or not cue or len(cue.split()) > CUE_MAX_WORDS:
        fail(f"{where}.cue must be a non-empty string of at most {CUE_MAX_WORDS} words, got {cue!r}")
    if item.get(kind_key) not in kinds:
        fail(f"{where}.{kind_key} must be one of {kinds}, got {item.get(kind_key)!r}")


def _validate_insights(insights, fail):
    """The 1.5.0 top-level `insights` (ADR-0014): at most MAX_INSIGHTS `{cue, why, kind, at_s, window, points}`."""
    if not isinstance(insights, list) or len(insights) > MAX_INSIGHTS:
        fail(f"insights must be a list of at most {MAX_INSIGHTS} items, got {insights!r}")
    for i, x in enumerate(insights):
        where = f"insights[{i}]"
        if not isinstance(x, dict) or "cue" not in x:
            fail(f"{where} must be an object with a cue")
        _validate_cue(x, where, fail, kind_key="kind")
        if not isinstance(x.get("why"), str) or not x["why"]:
            fail(f"{where}.why must be a non-empty string")
        for key in ("at_s", "points"):
            if x.get(key) is not None and not _is_number(x[key]):
                fail(f"{where}.{key} must be a number or null, got {x[key]!r}")
        if x.get("window") is not None and not (_is_int(x["window"]) and x["window"] >= 0):
            fail(f"{where}.window must be a window index (an integer from 0) or null, got {x['window']!r}")


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
