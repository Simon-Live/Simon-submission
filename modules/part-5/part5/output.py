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
from .cues import cue_for, validate_cues
from . import profiles
from .detect import EXPLAINED_BY, MAX_NEAR_MISSES, PERSISTENCE, REASONS, margin_deg
from .insights import MAX_INSIGHTS, insights_of
from .lateral import lateral_for
from .words import describe, describe_timed
from .score import CREDIT_GRADES, VERSION_V1, VERSION_V2, VERSION_V3, WARNING_CAP, credit_grade, document_ceiling
from .opinion.guard import validate_block as _validate_second_opinion
from .mask import validate_mask_block

FORMAT = "simon.analysis.v1"
# 1.2.0 time fields (ADR-0009), 1.3.0 rep fields (ADR-0010), 1.4.0 warnings and match (ADR-0012). From 1.5.0
# (ADR-0014) every new document carries cues and `insights`, so every new document is 1.5.0; a reader tells
# the earlier groups apart by their fields, which stay optional. 1.6.0 (ADR-0015) adds the foot measures
# `foot_rotation` and `ankle_inversion` (body part "feet") and `diagnostics.feet`; every new document is 1.6.0.
# 1.7.0 (ADR-0016) adds `profile`, the analysis profile that produced the document (always present in a new one).
# 1.8.0 (TICKET-043) adds `diagnostics.near_misses`, the candidates detection considered and dropped (present in every
# new document whose take was compared); every new document is 1.8.0.
# 1.9.0 (TICKET-045, TICKET-046) adds `phrasing.lang` (and `lang_requested`), `phrasing.faults[].text` and `.lang`, in
# every new document, and the top-level `second_opinion` when clips were given (docs/specs/second-opinion.md). The same
# 1.9.0 adds `score.uncapped` (Part 7 TICKET-155) and, for the reader, the optional top-level `source` and the warning
# code `no_person` (TICKET-048), which only Part 7's own analysis carries; Part 5 writes neither.
# 1.10.0 (TICKET-047, ADR-0018) adds `score.fault_cap` and `score.version` "simon.score.v2": a take that reports a fault
# is capped at 89, `fault_cap` says so, and `score.uncapped` is the value before every cap (the fault cap and the
# warning cap); `capped_by` stays the warning codes only. Every new document is 1.10.0.
# 1.11.0 (TICKET-060, ADR-0019) adds `score.version` "simon.score.v3": `score.fault_cap` is the ceiling in force, 89 for a
# take that reports one fault and 79 for two or more. Every new document is 1.11.0.
# 1.12.0 (TICKET-071, docs/specs/history-per-rep.md) adds, for the cross-take patterns of Part 7: `faults[].rep_sizes` (the
# size of a fault in each rep that found it, on a take compared rep by rep), `score.per_rep[].rep` and `.tempo_ratio` (the
# rep's tempo, null where unmeasured) and `diagnostics.near_misses.items[].margin_deg` (the size past the threshold).
# Nothing reads them back. Every new document is 1.12.0.
# 1.13.0 (ADR-0020) adds `score.credit` (`simon.credit.v1`, the DDR-style credit display): a percent and points earned per
# measure and frame by how close the follower stayed, at three levels, with one `per_window` entry per compared window of
# `score.timeline`; null when nothing was compared. Additive: no other field of the score changes and nothing reads it
# back. Every new document is 1.13.0.
# 1.14.0: `body_mask` for a declared mask (TICKET-084, ADR-0023); `phrasing.cues` and `phrasing.native_review` for a listed
# language other than English, the English cue fields unchanged (TICKET-080, docs/specs/language-cues.md);
# `quality.signals.heading_offset_deg` and the reason `heading_offset` (TICKET-086). Every new document is 1.14.0.
SCHEMA_VERSION = "1.14.0"
SCHEMA_VERSION_RE = re.compile(r"^1\.[0-9]+\.[0-9]+$")
PROFILE_SINCE = (1, 7, 0)   # from this schema version on, `profile` is required
# Status codes of documents written before ADR-0012 (no faults, no score); a new analysis is always "ok".
REFUSED_CODES = (DIFFERENT_MOVEMENT, NOT_ENOUGH_VISIBLE, MOVING_PART_OUT_OF_FRAME)
STATUS_CODES = (OK, *REFUSED_CODES)
WARNING_CODES = (LOW_MATCH, MOVING_PART_OUT_OF_FRAME, NOT_ENOUGH_VISIBLE, NO_USABLE_MEASURES)   # what Part 5 writes
# 1.9.0 (TICKET-048): Part 7 writes its own analysis when Part 2 finds nobody in the take: `source` "part7", the warning
# below, no comparison and so no `match`. Part 5 never writes it; a reader of analysis.json accepts it.
NO_PERSON = "no_person"
READABLE_WARNING_CODES = (*WARNING_CODES, NO_PERSON)
SOURCE_PART5 = "part5"   # what an absent `source` means
# ADR-0021: the optional top-level `quality` (simon.quality.v1, TICKET-079), how well the camera saw the take. It is built in
# part5/quality.py and validated here like every other block; it is reported only and no score field reads it.
QUALITY_VERSION = "simon.quality.v1"
QUALITY_LEVELS = ("ok", "degraded", "major")
QUALITY_WARNING_CODES = (NOT_ENOUGH_VISIBLE, MOVING_PART_OUT_OF_FRAME, NO_USABLE_MEASURES)   # a take with one is major; low_match is not a reason
QUALITY_CODES = (*QUALITY_WARNING_CODES, "joints_unseen", "joints_missing", "frames_missing", "measures_hidden", "position_jitter",
                 "heading_offset")
QUALITY_SIGNALS = ("unseen_joint_share", "missing_joint_share", "missing_frame_share", "hidden_measure_share", "position_jitter_mm",
                   "heading_offset_deg")
QUALITY_SIGNAL_SINCE = {"heading_offset_deg": (1, 14, 0)}   # TICKET-086; a signal not listed is required from 1.13.0
QUALITY_SIGNAL_TOP = {"position_jitter_mm": (None, "a number of at least 0"), "heading_offset_deg": (180, "a number from 0 to 180")}
QUALITY_CAP = WARNING_CAP   # 59, the cap a warning puts on score.value; the block reports it when the level is major
CREDIT_LETTERS = tuple(letter for _, letter in CREDIT_GRADES)   # S to F, best first: score.credit's own scale (ADR-0020)
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
        if times.get("rep_sizes") is not None:   # 1.12.0: the size in each rep that found it (a take compared rep by rep)
            d["rep_sizes"] = [{"rep": int(e["rep"]), "magnitude_deg": float(e["magnitude_deg"]), "side": e["side"],
                               "body_part": e["body_part"]} for e in times["rep_sizes"]]
    return d


def _input_ref(ref, key):
    if isinstance(ref, (str, Path)):
        return {"path": str(ref)}
    if isinstance(ref, dict):
        return dict(ref)
    raise OutputError(f"{key} must be a path or an object with a 'path', got {ref!r}")


def build_analysis(expected, follower, faults, diagnostics=None, status=None, times=None, score=NO_SCORE,
                   warnings=None, match=None, profile=profiles.IDENTITY, quality=None, body_mask=None):
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
    `quality` (1.13.0, ADR-0021) is the `simon.quality.v1` block (`part5.quality`), written after `match` and before
    `diagnostics`; left out when None (not assessed). It is reported only: nothing else in the document reads it.
    `body_mask` (1.14.0, ADR-0023) is the declared mask's block (`mask.BodyMask.block`), written after `profile`;
    None, the default, writes nothing.
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
           "profile": profile}
    if body_mask is not None:
        doc["body_mask"] = body_mask
    doc["expected"] = _input_ref(expected, "expected")
    doc["follower"] = _input_ref(follower, "follower")
    if status is not None:
        doc["status"] = dict(status)
    doc["faults"] = faults
    if warned:
        doc["warnings"] = [dict(w) for w in warnings]
        doc["match"] = match
    if quality is not None:
        doc["quality"] = quality
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
    if "near_misses" in doc.get("diagnostics", {}):
        _validate_near_misses(doc["diagnostics"]["near_misses"], fail)
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
    if "source" in doc and not (isinstance(doc["source"], str) and doc["source"]):
        fail(f"source must be a non-empty string (the producing part; absent means {SOURCE_PART5}), got {doc['source']!r}")
    if "warnings" in doc:
        _validate_warnings(doc["warnings"], doc.get("match"), fail)
    if "quality" in doc:
        _validate_quality(doc["quality"], doc.get("warnings"), fail, doc.get("schema_version"))
    if "phrasing" in doc:
        _validate_phrasing(doc["phrasing"], faults, fail)
        validate_cues(doc["phrasing"], doc, fail)   # 1.14.0 (TICKET-080), beside cue_fields in part5/cues.py
    if "second_opinion" in doc:
        _validate_second_opinion(doc["second_opinion"], len(faults), fail)
    if "score" in doc and doc["score"] is not None and not isinstance(doc["score"], dict):
        fail("score must be an object or null")
    _validate_fault_cap(doc.get("score"), len(faults), fail)
    _validate_per_rep(doc, fail)
    _check_credit_shape(doc.get("score"), fail)
    _validate_credit(doc.get("score"), fail)
    if "insights" in doc:
        _validate_insights(doc["insights"], fail)
    if "body_mask" in doc:   # 1.14.0 (ADR-0023): nothing in the document may name a measure the mask does not score
        validate_mask_block(doc, fail)
    if isinstance(doc.get("score"), dict) and doc.get("status", {}).get("code") in REFUSED_CODES:
        fail("score must be null for a refused take")
    try:  # nothing anywhere (incl. diagnostics/extras) may make this invalid JSON downstream
        json.dumps(doc, allow_nan=False)
    except (TypeError, ValueError) as e:
        fail(f"document is not JSON-serialisable ({e})")
    return doc


def _validate_fault_cap(score, n_faults, fail):
    """The 1.10.0 and 1.11.0 `score.fault_cap` (ADR-0018, ADR-0019) must be the ceiling in force for the faults the document
    reports: under `simon.score.v2` 89 for one or more, under `simon.score.v3` 89 for one and 79 for two or more, and
    absent for none. A producer that wrote 89 on a two-fault v3 take, or left it out, would otherwise still validate. A
    `simon.score.v1` block has no ceiling, so it carries no `fault_cap` at all (a writer that put one there has mixed two
    versions up)."""
    if isinstance(score, dict) and score.get("version") == VERSION_V1 and "fault_cap" in score:
        fail(f"score.fault_cap must be absent from a {VERSION_V1} score block, which has no ceiling, got {score['fault_cap']!r}")
    if not isinstance(score, dict) or score.get("version") not in (VERSION_V2, VERSION_V3):
        return
    want = document_ceiling(score["version"], n_faults)
    if want is None:
        if "fault_cap" in score:
            fail(f"score.fault_cap must be absent for a take that reports no fault, got {score['fault_cap']!r}")
    elif score.get("fault_cap") != want:   # 89 and 79 are never equal to True or False, so a boolean fails here too
        fail(f"score.fault_cap must be {want} for a {score['version']} take that reports {n_faults} fault"
             f"{'s' if n_faults != 1 else ''}, got {score.get('fault_cap')!r}")


def _validate_per_rep(doc, fail):
    """The 1.12.0 `rep` and `tempo_ratio` of each `score.per_rep` entry (docs/specs/history-per-rep.md); a 1.3.0 entry
    with a value and a grade only is as valid as it was. `rep` is the follower rep's index, so the entry joins
    `faults[].rep_sizes[].rep` and `score.timeline[rep]`. `tempo_ratio` is that window's `tempo.ratio` (ADR-0014: made in
    one place, `score.tempo_ratio`), a number or null where unmeasured. That it is null for every rep of a low match
    (TICKET-063) is the producer's rule, as it is for the windows' `tempo`, which this validator does not check either."""
    score = doc.get("score")
    per_rep = score.get("per_rep") if isinstance(score, dict) else None
    for i, e in enumerate(per_rep if isinstance(per_rep, list) else []):
        where = f"score.per_rep[{i}]"
        if not isinstance(e, dict):
            continue
        if "rep" in e and not (_is_int(e["rep"]) and e["rep"] >= 0):
            fail(f"{where}.rep must be a rep index (an integer from 0), got {e['rep']!r}")
        if "tempo_ratio" not in e:
            continue
        ratio = e["tempo_ratio"]
        if not (ratio is None or (_is_number(ratio) and ratio >= 0)):
            fail(f"{where}.tempo_ratio must be a number of at least 0 or null (unmeasured), got {ratio!r}")
        window = _timeline_window(score, e.get("rep"))
        tempo = window.get("tempo") if isinstance(window, dict) else None
        if isinstance(tempo, dict) and "ratio" in tempo and tempo["ratio"] != ratio:
            fail(f"{where}.tempo_ratio must be the tempo.ratio of score.timeline[{e['rep']}] "
                 f"({tempo['ratio']!r}), got {ratio!r}")


def _check_credit_shape(score, fail):
    """The shape `_validate_credit` reads (ADR-0020): `score.credit` absent, null or an object, whose `levels` is an object of
    objects and whose `per_window` is a list of objects. The schema says more; this keeps a document the schema was not run
    on (`part5 doctor` without jsonschema) from raising an AttributeError, or from passing as a string, instead of failing."""
    if not isinstance(score, dict) or score.get("credit") is None:
        return
    credit = score["credit"]
    if not isinstance(credit, dict):
        fail(f"score.credit must be an object or null, got {type(credit).__name__}")
    levels, windows = credit.get("levels", {}), credit.get("per_window", [])
    if not isinstance(levels, dict) or not all(isinstance(v, dict) for v in levels.values()):
        fail("score.credit.levels must be an object whose values are objects")
    if not isinstance(windows, list) or not all(isinstance(w, dict) for w in windows):
        fail("score.credit.per_window must be a list of objects")
    # review R8 of 1.13.0: the letters, which the schema alone checked, so `grade: "Z"` and `grades: "S"` passed without it
    if "grades" in credit and not _is_credit_scale(credit["grades"]):
        fail(f"score.credit.grades must be [percent at least, letter] pairs, the percents falling and the letters from "
             f"{', '.join(CREDIT_LETTERS)} in that order, got {credit['grades']!r}")
    if "grade" in credit and credit["grade"] not in CREDIT_LETTERS:
        fail(f"score.credit.grade must be one of {', '.join(CREDIT_LETTERS)}, got {credit['grade']!r}")


def _is_credit_scale(grades):
    """`score.credit.grades` (ADR-0020): a non-empty list of [number, letter] pairs, each number below the one before and each
    letter later in CREDIT_LETTERS than the one before (so no letter twice)."""
    if not (isinstance(grades, list) and grades and all(isinstance(g, list) and len(g) == 2 and _is_number(g[0])
                                                        and isinstance(g[1], str) and g[1] in CREDIT_LETTERS for g in grades)):
        return False
    marks, ranks = [g[0] for g in grades], [CREDIT_LETTERS.index(g[1]) for g in grades]
    return all(a > b for a, b in zip(marks, marks[1:])) and all(a < b for a, b in zip(ranks, ranks[1:]))


def _validate_credit(score, fail):
    """The 1.13.0 `score.credit` (ADR-0020): absent (an earlier document), null (nothing compared) or a block whose
    `per_window` has one entry per compared window of `score.timeline`, at the same `t_s`, in the same order, whose
    points never pass its max points, and whose grade is the letter its percent reaches on its `grades` (the scale every
    document carries when it has none). The schema checks the types and ranges; `_check_credit_shape` has run first."""
    credit = score.get("credit") if isinstance(score, dict) else None
    if not isinstance(credit, dict):
        return
    timeline = score.get("timeline") if isinstance(score.get("timeline"), list) else []
    spans = [w.get("t_s") for w in timeline if isinstance(w, dict) and w.get("compared", True)]
    windows = credit.get("per_window", [])
    if [w.get("t_s") for w in windows] != spans:
        fail(f"score.credit.per_window must have one entry per compared window of score.timeline, at its t_s "
             f"({len(spans)} windows), got {len(windows)}")
    for where, entry in [("score.credit", credit), *((f"score.credit.levels.{k}", v)
                                                    for k, v in credit.get("levels", {}).items())]:
        if _is_int(entry.get("points")) and _is_int(entry.get("max_points")) and entry["points"] > entry["max_points"]:
            fail(f"{where}.points must be at most its max_points, got {entry['points']} > {entry['max_points']}")
    if "grade" in credit and _is_number(credit.get("percent")):
        letter = credit_grade(credit["percent"], credit.get("grades", CREDIT_GRADES))
        if credit["grade"] != letter:
            fail(f"score.credit.grade must be the letter score.credit.percent ({credit['percent']}) reaches on "
                 f"score.credit.grades, {letter}, got {credit['grade']!r}")


def _timeline_window(score, rep):
    """`score.timeline[rep]` when the score has a timeline and `rep` is an index into it, else None."""
    timeline = score.get("timeline")
    return timeline[rep] if isinstance(timeline, list) and _is_int(rep) and 0 <= rep < len(timeline) else None


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


def _validate_near_misses(block, fail):
    """The 1.8.0 `diagnostics.near_misses` (TICKET-043): how many there are, how many are left out and the largest ones."""
    where = "diagnostics.near_misses"
    items = block.get("items") if isinstance(block, dict) else None
    if not (isinstance(items, list) and len(items) <= MAX_NEAR_MISSES and _is_int(block.get("total"))
            and _is_int(block.get("omitted")) and block["omitted"] == block["total"] - len(items) >= 0):
        fail(f"{where} must be {{total, omitted, items}} with at most {MAX_NEAR_MISSES} items and "
             "omitted equal to total minus the items listed")
    for i, item in enumerate(items):
        _validate_near_miss(item, f"{where}.items[{i}]", fail)


def _validate_near_miss(item, where, fail):
    if not isinstance(item, dict):
        fail(f"{where} must be an object")
    measure, side = item.get("measure"), item.get("side")
    if measure not in GENERIC_MEASURES:
        fail(f"{where}.measure must be one of {GENERIC_MEASURES}, got {measure!r}")
    if side not in ("left", "right", "center"):   # sides are merged for faults only
        fail(f"{where}.side must be left, right or center, got {side!r}")
    spec = _spec(measure, side)
    if spec is None:
        fail(f"{where}: side {side!r} does not go with measure {measure!r}")
    if item.get("joint") != _joint_for(measure, side) or item.get("body_part") != spec.body_part:
        fail(f"{where}.joint and body_part must be {_joint_for(measure, side)!r} and {spec.body_part!r} for "
             f"{measure}/{side}, got {item.get('joint')!r} and {item.get('body_part')!r}")
    if item.get("direction") not in DIRECTIONS:
        fail(f"{where}.direction must be one of {DIRECTIONS}, got {item.get('direction')!r}")
    for key in ("magnitude_deg", "peak_deg"):
        if not _is_number(item.get(key)) or (item[key] > 0) != (item["direction"] == "more"):
            fail(f"{where}.{key} must be a nonzero number signed like the direction (more positive, less negative), "
                 f"got {item.get(key)!r}")
    if not _is_number(item.get("threshold_deg")) or item["threshold_deg"] <= 0:
        fail(f"{where}.threshold_deg must be a positive number, got {item.get('threshold_deg')!r}")
    if "margin_deg" in item and (not _is_number(item["margin_deg"])
                                 or item["margin_deg"] != margin_deg(item["magnitude_deg"], item["threshold_deg"])):   # 1.12.0
        fail(f"{where}.margin_deg must be abs(magnitude_deg) minus threshold_deg to one decimal, positive when past the "
             f"threshold: {margin_deg(item['magnitude_deg'], item['threshold_deg'])!r}, got {item['margin_deg']!r}")
    for key in ("expected_frames", "follower_frames"):
        v = item.get(key)
        if not (isinstance(v, list) and len(v) == 2 and all(_is_int(x) for x in v) and 0 <= v[0] <= v[1]):
            fail(f"{where}.{key} must be [start, end] integer frames with 0 <= start <= end, got {v!r}")
    for key in ("frames_over", "counted_frames", "needed_frames", "min_run_frames"):
        if not _is_int(item.get(key)) or item[key] < 0:
            fail(f"{where}.{key} must be an integer of at least 0, got {item.get(key)!r}")
    if item["frames_over"] < 1 or item["counted_frames"] > item["frames_over"]:
        fail(f"{where}: frames_over must be at least 1 and at least counted_frames")
    _validate_near_miss_reason(item, where, fail)
    if "reps" in item and not (isinstance(item["reps"], list) and item["reps"]
                               and all(_is_int(x) and x >= 0 for x in item["reps"])):
        fail(f"{where}.reps must be a non-empty list of rep indices (integers from 0), got {item['reps']!r}")


def _validate_near_miss_reason(item, where, fail):
    """The reason and the field that goes with it: a shortfall, the fault that explains it, or the rep counts."""
    reason = item.get("reason")
    if reason not in REASONS:
        fail(f"{where}.reason must be one of {REASONS}, got {reason!r}")
    if reason == PERSISTENCE and not (_is_int(item.get("shortfall_frames")) and item["shortfall_frames"] >= 0):
        fail(f"{where}.shortfall_frames must be an integer of at least 0 for reason persistence, "
             f"got {item.get('shortfall_frames')!r}")
    if reason == EXPLAINED_BY:
        by = item.get("explained_by")
        if not (isinstance(by, dict) and by.get("measure") in GENERIC_MEASURES and by.get("side") in SIDES
                and by.get("direction") in DIRECTIONS):
            fail(f"{where}.explained_by must be {{measure, side, direction}} of the fault that explains it, got {by!r}")
    if reason not in (PERSISTENCE, EXPLAINED_BY) and not all(
            _is_int(item.get(k)) and item[k] >= 0 for k in ("found_in_reps", "needed_reps")):
        fail(f"{where}.found_in_reps and needed_reps must be integers of at least 0 for reason {reason}")


def _validate_warnings(warnings, match, fail):
    """The 1.4.0 `warnings` and `match` (ADR-0012). `match` says how the comparison went, so a document whose only
    warning is `no_person` (1.9.0, Part 7's own analysis: nothing was compared) may leave it out; if it has one, it is
    checked like any other."""
    if not (isinstance(warnings, list) and warnings):
        fail("warnings must be a non-empty list of {code, text}")
    for i, w in enumerate(warnings):
        if not isinstance(w, dict) or w.get("code") not in READABLE_WARNING_CODES:
            fail(f"warnings[{i}].code must be one of {READABLE_WARNING_CODES}, "
                 f"got {(w or {}).get('code') if isinstance(w, dict) else w!r}")
        if not isinstance(w.get("text"), str) or not w["text"]:
            fail(f"warnings[{i}].text must be a non-empty string")
    if match is None and all(w["code"] == NO_PERSON for w in warnings):
        return
    if not isinstance(match, dict) or match.get("quality") not in ("ok", "low"):
        fail("match must be an object with quality 'ok' or 'low' when there are warnings")
    for key in ("residual", "timing_corr"):
        if match.get(key) is not None and not _is_number(match[key]):
            fail(f"match.{key} must be a number or null, got {match[key]!r}")
    if not isinstance(match.get("limits"), dict):
        fail("match.limits must be an object")


# ADR-0021: the 1.13.0 `quality`, checked here because every block of the document is. The schema says the same (`$defs.quality`);
# this keeps a document the schema was not run on (`part5 doctor` without jsonschema) from passing a block that contradicts itself.
def _validate_quality(block, warnings, fail, version=None):
    """The `quality` block (TICKET-079): version, a level that agrees with the reasons, well-formed reasons and signals, a
    `score_cap` of 59 exactly when the level is `major`, and, for a take that carries `not_enough_visible`,
    `moving_part_out_of_frame` or `no_usable_measures`, level `major` with that reason."""
    if not isinstance(block, dict):
        fail(f"quality must be an object, got {type(block).__name__}")
    if block.get("version") != QUALITY_VERSION:
        fail(f"quality.version must be {QUALITY_VERSION!r}, got {block.get('version')!r}")
    level, reasons = block.get("level"), block.get("reasons")
    if level not in QUALITY_LEVELS:
        fail(f"quality.level must be one of {QUALITY_LEVELS}, got {level!r}")
    if not isinstance(reasons, list):
        fail("quality.reasons must be a list")
    for i, reason in enumerate(reasons):
        _validate_quality_reason(reason, f"quality.reasons[{i}]", fail)
    if (level == "ok") != (not reasons):
        fail(f"quality.level {level!r} does not agree with its {len(reasons)} reason(s): ok has none, degraded and major at least one")
    _validate_quality_signals(block.get("signals"), fail, version)
    want = QUALITY_CAP if level == "major" else None
    if block.get("score_cap") != want or isinstance(block.get("score_cap"), bool):
        fail(f"quality.score_cap must be {want!r} for level {level!r}, got {block.get('score_cap')!r}")
    carried = {w["code"] for w in warnings if isinstance(w, dict) and w.get("code") in QUALITY_WARNING_CODES} \
        if isinstance(warnings, list) else set()
    if carried and (level != "major" or not carried <= {r["code"] for r in reasons}):
        fail(f"a take with the warning {sorted(carried)} must be quality.level 'major' with that reason")


def _validate_quality_reason(reason, where, fail):
    if not isinstance(reason, dict):
        fail(f"{where} must be an object")
    if reason.get("code") not in QUALITY_CODES:
        fail(f"{where}.code must be one of {QUALITY_CODES}, got {reason.get('code')!r}")
    if not isinstance(reason.get("words"), str) or not reason["words"].strip():
        fail(f"{where}.words must be a non-empty string")
    for key in ("value", "threshold"):
        if key not in reason or not (reason[key] is None or (_is_number(reason[key]) and reason[key] >= 0)):
            fail(f"{where}.{key} must be a number of at least 0 or null, got {reason.get(key, '<missing>')!r}")
    if "joint" in reason and reason["joint"] not in JOINTS:
        fail(f"{where}.joint must be a canonical joint name, got {reason['joint']!r}")


def _validate_quality_signals(signals, fail, version=None):
    """Each of `QUALITY_SIGNALS` is a number within `QUALITY_SIGNAL_TOP` (a share from 0 to 1) or null, never 0 in its place. One in
    `QUALITY_SIGNAL_SINCE` is required from that schema version on (the current one when `version` is None), checked if present."""
    at = tuple(map(int, version.split("."))) if isinstance(version, str) and SCHEMA_VERSION_RE.match(version) else (99,)
    need = [name for name in QUALITY_SIGNALS if at >= QUALITY_SIGNAL_SINCE.get(name, (1, 13, 0))]
    if not isinstance(signals, dict) or any(name not in signals for name in need):
        fail(f"quality.signals must be an object with {need}")
    for name in (n for n in QUALITY_SIGNALS if n in signals):
        value, (top, kind) = signals[name], QUALITY_SIGNAL_TOP.get(name, (1, "a share from 0 to 1"))
        if value is not None and not (_is_number(value) and value >= 0 and (top is None or value <= top)):
            fail(f"quality.signals.{name} must be {kind} or null, got {value!r}")


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


def _validate_phrasing(record, faults, fail):
    """The phrasing record: who phrased each coaching line and why a fault fell back (ADR-0005). From 1.9.0 each
    entry's `text` is the line shown, so it equals the fault's `coaching` when both are there (AC-LA-04)."""
    if not isinstance(record, dict) or not isinstance(record.get("backend"), str):
        fail("phrasing must be an object with a string 'backend'")
    per_fault = record.get("faults")
    if not isinstance(per_fault, list) or len(per_fault) != len(faults):
        fail(f"phrasing.faults must hold one entry per fault ({len(faults)}), got {per_fault!r}")
    for key in ("lang", "lang_requested"):   # 1.9.0 (TICKET-046)
        if key in record and not (isinstance(record[key], str) and record[key]):
            fail(f"phrasing.{key} must be a non-empty string, got {record[key]!r}")
    for i, entry in enumerate(per_fault):
        for key in ("text", "lang"):
            if isinstance(entry, dict) and key in entry and not (isinstance(entry[key], str) and entry[key]):
                fail(f"phrasing.faults[{i}].{key} must be a non-empty string, got {entry[key]!r}")
        coaching = faults[i].get("coaching") if isinstance(faults[i], dict) else None
        if isinstance(entry, dict) and isinstance(entry.get("text"), str) and isinstance(coaching, str) \
                and entry["text"] != coaching:
            fail(f"phrasing.faults[{i}].text must equal faults[{i}].coaching, got {entry['text']!r} and {coaching!r}")


def _validate_times(f, where, fail):
    """The optional 1.2.0 fields of a fault (ADR-0009); a 1.1.0 fault has none of them."""
    if "follower_t_s" in f:
        v = f["follower_t_s"]
        if not (isinstance(v, (list, tuple)) and len(v) == 2 and all(_is_number(x) for x in v) and v[0] <= v[1]):
            fail(f"{where}.follower_t_s must be [start_s, end_s] numbers with start <= end, got {v!r}")
    if "at_s" in f and not _is_number(f["at_s"]):
        fail(f"{where}.at_s must be a number, got {f['at_s']!r}")
    if "at_s" in f and "follower_t_s" in f and f["at_s"] != round_half_up_tenth(f["follower_t_s"][0]):
        # TICKET-061: the J-1 rule (journey-followup.md, analysis.schema.json at_s); follower_t_s is valid by here
        fail(f"{where}.at_s {f['at_s']!r} is not follower_t_s[0] {f['follower_t_s'][0]!r} rounded half up to 0.1 s")
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
    if "rep_sizes" in f:
        _validate_rep_sizes(f, where, fail)


def _validate_rep_sizes(f, where, fail):
    """The optional 1.12.0 `rep_sizes` of a fault compared rep by rep (docs/specs/history-per-rep.md): one
    `{rep, magnitude_deg, side, body_part}` per rep in `reps`, in rep order, signed like the fault's direction. The side
    is the one that rep found the fault on (`both` when it found both), so it may differ from the fault's own side."""
    sizes, reps = f["rep_sizes"], f.get("reps")
    if not (isinstance(sizes, list) and sizes and all(isinstance(e, dict) for e in sizes)):
        fail(f"{where}.rep_sizes must be a non-empty list of {{rep, magnitude_deg, side, body_part}}, got {sizes!r}")
    if reps is None or [e.get("rep") for e in sizes] != reps:
        fail(f"{where}.rep_sizes must hold one entry per rep in {where}.reps, in order, got reps "
             f"{[e.get('rep') for e in sizes]!r} against {reps!r}")
    for i, e in enumerate(sizes):
        spot = f"{where}.rep_sizes[{i}]"
        spec = _spec(f["measure"], e.get("side"))
        if e.get("side") not in SIDES or spec is None:
            fail(f"{spot}.side must be one of {SIDES} and go with measure {f['measure']!r}, got {e.get('side')!r}")
        if e.get("body_part") != spec.body_part:
            fail(f"{spot}.body_part must be {spec.body_part!r} for {f['measure']}, got {e.get('body_part')!r}")
        size = e.get("magnitude_deg")
        if not _is_number(size) or (size > 0) != (f["direction"] == "more") or size == 0:
            fail(f"{spot}.magnitude_deg must be a nonzero number signed like the direction {f['direction']!r} "
                 f"(more positive, less negative), got {size!r}")
