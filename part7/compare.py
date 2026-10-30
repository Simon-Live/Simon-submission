"""Fault set comparison, tolerance, score and timing checks, geometry diffs for check-7.

ADR-0005: tolerance fixed before any measurement. ADR-0006: score, at_s and text_timed gates.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

DEG_ABS: float = 2.0
M_ABS: float = 0.01
REL_TOL: float = 0.10

TOLERANCE: dict[str, float] = {
    "deg_abs": DEG_ABS,
    "m_abs": M_ABS,
    "rel": REL_TOL,
}


def status_code(analysis: dict[str, Any]) -> str:
    """Return status.code from a Part 5 analysis dict (schema 1.0 without status reads as 'ok')."""
    if not isinstance(analysis, dict):
        return "ok"
    status = analysis.get("status")
    if status is None:
        return "ok"
    if isinstance(status, dict):
        code = status.get("code")
        return str(code) if code is not None else "ok"
    if isinstance(status, str):
        return status
    return "ok"


OLD_REFUSALS = ("different_movement", "not_enough_visible", "moving_part_out_of_frame")


def warning_codes(analysis: dict[str, Any]) -> list[str]:
    """Sorted warning codes of an analysis: `warnings[].code`, plus an old-pin refusal status read as one (ADR-0005)."""
    if not isinstance(analysis, dict):
        return []
    codes = {str(w.get("code")) for w in analysis.get("warnings") or [] if isinstance(w, dict) and w.get("code")}
    status = status_code(analysis)
    if status in OLD_REFUSALS:
        codes.add(status)
    return sorted(codes)


def effective_grade(analysis: dict[str, Any]) -> str | None:
    """`score.grade`; an old-pin refusal has no score and reads as F; None when an ok take has no grade."""
    score = analysis.get("score") if isinstance(analysis, dict) else None
    if isinstance(score, dict):
        grade = score.get("grade")
        return str(grade) if grade is not None else None
    return "F" if status_code(analysis) in OLD_REFUSALS else None


def fault_key(fault: dict[str, Any]) -> tuple[str, str, str]:
    """Return the (measure, side, direction) identity key for a fault."""
    return (
        str(fault.get("measure", "")),
        str(fault.get("side", "")),
        str(fault.get("direction", "")),
    )


def within_tolerance(
    val_a: float,
    val_d: float,
    abs_tol: float,
    rel_tol: float = REL_TOL,
) -> bool:
    """Return True when |val_a - val_d| <= max(abs_tol, rel_tol * max(|val_a|, |val_d|))."""
    a = float(val_a)
    d = float(val_d)
    if math.isnan(a) or math.isnan(d) or math.isinf(a) or math.isinf(d):
        return False
    bound = max(float(abs_tol), float(rel_tol) * max(abs(a), abs(d)))
    return abs(a - d) <= bound + 1e-12


def fault_magnitude(fault: dict[str, Any]) -> tuple[float, float, str]:
    """Extract (value, abs_tol, field_name) from a fault dictionary."""
    if "magnitude_deg" in fault and fault["magnitude_deg"] is not None:
        return (float(fault["magnitude_deg"]), DEG_ABS, "magnitude_deg")
    if "magnitude_m" in fault and fault["magnitude_m"] is not None:
        return (float(fault["magnitude_m"]), M_ABS, "magnitude_m")
    unit = str(fault.get("unit", "degrees")).lower()
    val = float(fault.get("magnitude", 0.0))
    if unit in ("m", "metre", "metres", "meter", "meters"):
        return (val, M_ABS, "magnitude_m")
    return (val, DEG_ABS, "magnitude_deg")


def at_s_equal(app_fault: dict[str, Any], direct_fault: dict[str, Any]) -> bool:
    """Return True when both faults carry the same numeric `at_s` (ADR-0006: equal, no tolerance)."""
    a = app_fault.get("at_s")
    d = direct_fault.get("at_s")
    if isinstance(a, bool) or isinstance(d, bool):
        return False
    if not isinstance(a, (int, float)) or not isinstance(d, (int, float)):
        return False
    return math.isclose(float(a), float(d), rel_tol=0.0, abs_tol=1e-9)


def score_value(analysis: dict[str, Any]) -> Any:
    """Return `score.value` of an analysis, or None when `score` is null or absent."""
    score = analysis.get("score") if isinstance(analysis, dict) else None
    if isinstance(score, dict):
        return score.get("value")
    return None


def score_equal(app_analysis: dict[str, Any], direct_analysis: dict[str, Any]) -> bool:
    """`score.value` identical in both paths; both null on a refused take; null on an ok take fails."""
    app_v = score_value(app_analysis)
    direct_v = score_value(direct_analysis)
    app_st = status_code(app_analysis)
    if app_st != status_code(direct_analysis):
        return False
    if app_st == "ok":
        return app_v is not None and app_v == direct_v
    return app_v is None and direct_v is None


def text_timed_present(analysis: dict[str, Any]) -> bool:
    """Every fault carries a non-empty `text_timed` string (true with no faults)."""
    faults = analysis.get("faults") if isinstance(analysis, dict) else None
    for fault in faults or []:
        text = fault.get("text_timed") if isinstance(fault, dict) else None
        if not isinstance(text, str) or not text.strip():
            return False
    return True


def app_result_complete(analysis: dict[str, Any]) -> bool:
    """The app result carries `score` (null allowed only when refused) and every fault's `text_timed`."""
    if not isinstance(analysis, dict):
        return False
    if status_code(analysis) == "ok" and not isinstance(analysis.get("score"), dict):
        return False
    return text_timed_present(analysis)


def _fault_sort_key(fault: dict[str, Any]) -> tuple[int, float]:
    frames = fault.get("expected_frames")
    start_frame = 0
    if isinstance(frames, list) and frames and isinstance(frames[0], (int, float)):
        start_frame = int(frames[0])
    mag, _, _ = fault_magnitude(fault)
    return (start_frame, -abs(mag))


def match(app_analysis: dict[str, Any], direct_analysis: dict[str, Any]) -> dict[str, Any]:
    """Compare app-path analysis.json with direct-path analysis.json under ADR-0005."""
    app_st = status_code(app_analysis)
    direct_st = status_code(direct_analysis)
    status_equal = app_st == direct_st

    app_faults = list(app_analysis.get("faults") or []) if isinstance(app_analysis, dict) else []
    direct_faults = (
        list(direct_analysis.get("faults") or []) if isinstance(direct_analysis, dict) else []
    )

    app_buckets: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for f in app_faults:
        if isinstance(f, dict):
            app_buckets.setdefault(fault_key(f), []).append(f)

    direct_buckets: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for f in direct_faults:
        if isinstance(f, dict):
            direct_buckets.setdefault(fault_key(f), []).append(f)

    for bucket in app_buckets.values():
        bucket.sort(key=_fault_sort_key)
    for bucket in direct_buckets.values():
        bucket.sort(key=_fault_sort_key)

    all_keys = sorted(set(app_buckets.keys()) | set(direct_buckets.keys()))

    faults_equal = set(app_buckets.keys()) == set(direct_buckets.keys()) and all(
        len(app_buckets[k]) == len(direct_buckets[k]) for k in all_keys
    )

    faults_compared = 0
    all_mags_ok = True
    all_at_s_equal = True
    details: list[dict[str, Any]] = []

    for k in all_keys:
        a_list = app_buckets.get(k, [])
        d_list = direct_buckets.get(k, [])
        paired = min(len(a_list), len(d_list))
        for idx in range(paired):
            fa = a_list[idx]
            fd = d_list[idx]
            val_a, tol_a, field_a = fault_magnitude(fa)
            val_d, tol_d, field_d = fault_magnitude(fd)
            faults_compared += 1
            if field_a != field_d:
                ok_mag = False
            else:
                ok_mag = within_tolerance(val_a, val_d, max(tol_a, tol_d), REL_TOL)
            if not ok_mag:
                all_mags_ok = False
            details.append(
                {
                    "key": list(k),
                    "matched": True,
                    "field": field_a,
                    "app": val_a,
                    "direct": val_d,
                    "diff": abs(val_a - val_d),
                    "within_tolerance": ok_mag,
                    "at_s_app": fa.get("at_s"),
                    "at_s_direct": fd.get("at_s"),
                    "at_s_equal": at_s_equal(fa, fd),
                }
            )
            if not at_s_equal(fa, fd):
                all_at_s_equal = False
        if len(a_list) > paired:
            all_mags_ok = False
            for idx in range(paired, len(a_list)):
                val_a, _, field_a = fault_magnitude(a_list[idx])
                details.append(
                    {
                        "key": list(k),
                        "matched": False,
                        "only_in": "app",
                        "field": field_a,
                        "app": val_a,
                        "within_tolerance": False,
                    }
                )
        if len(d_list) > paired:
            all_mags_ok = False
            for idx in range(paired, len(d_list)):
                val_d, _, field_d = fault_magnitude(d_list[idx])
                details.append(
                    {
                        "key": list(k),
                        "matched": False,
                        "only_in": "direct",
                        "field": field_d,
                        "direct": val_d,
                        "within_tolerance": False,
                    }
                )

    magnitudes_within = bool(faults_equal and all_mags_ok)
    matched = bool(status_equal and faults_equal and magnitudes_within)

    return {
        "matched": matched,
        "faults_equal": faults_equal,
        "magnitudes_within": magnitudes_within,
        "status_equal": status_equal,
        "warnings_equal": warning_codes(app_analysis) == warning_codes(direct_analysis),
        "faults_compared": faults_compared,
        "at_s_equal": all_at_s_equal,
        "app_status": app_st,
        "direct_status": direct_st,
        "details": details,
    }


def _extract_xyz(joint_val: Any) -> tuple[float, float, float] | None:
    if isinstance(joint_val, dict):
        if "x" in joint_val and "y" in joint_val and "z" in joint_val:
            x, y, z = joint_val["x"], joint_val["y"], joint_val["z"]
            if x is None or y is None or z is None:
                return None
            return (float(x), float(y), float(z))
        return None
    if isinstance(joint_val, (list, tuple)) and len(joint_val) >= 3:
        x, y, z = joint_val[0], joint_val[1], joint_val[2]
        if x is None or y is None or z is None:
            return None
        return (float(x), float(y), float(z))
    return None


def _euclidean_m(p1: tuple[float, float, float], p2: tuple[float, float, float]) -> float:
    dx = p1[0] - p2[0]
    dy = p1[1] - p2[1]
    dz = p1[2] - p2[2]
    return math.sqrt(dx * dx + dy * dy + dz * dz)


def _compare_joints_container(joints_a: Any, joints_b: Any) -> float:
    max_diff = 0.0
    if isinstance(joints_a, dict) and isinstance(joints_b, dict):
        for name in set(joints_a.keys()) & set(joints_b.keys()):
            pa = _extract_xyz(joints_a[name])
            pb = _extract_xyz(joints_b[name])
            if pa is not None and pb is not None:
                d = _euclidean_m(pa, pb)
                if d > max_diff:
                    max_diff = d
    elif isinstance(joints_a, list) and isinstance(joints_b, list):
        for ja, jb in zip(joints_a, joints_b):
            pa = _extract_xyz(ja)
            pb = _extract_xyz(jb)
            if pa is not None and pb is not None:
                d = _euclidean_m(pa, pb)
                if d > max_diff:
                    max_diff = d
    return max_diff


def _load_json_and_bytes(
    source: dict[str, Any] | str | Path | bytes,
) -> tuple[dict[str, Any], bytes]:
    if isinstance(source, Path):
        raw = source.read_bytes()
        return json.loads(raw.decode("utf-8")), raw
    if isinstance(source, str):
        p = Path(source)
        if p.exists() and p.is_file():
            raw = p.read_bytes()
            return json.loads(raw.decode("utf-8")), raw
        raw = source.encode("utf-8")
        return json.loads(source), raw
    if isinstance(source, bytes):
        return json.loads(source.decode("utf-8")), source
    if isinstance(source, dict):
        canonical = json.dumps(source, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return source, canonical
    raise TypeError(f"Unsupported pose/animation input type: {type(source)!r}")


def _select_person_joints(frame_obj: dict[str, Any]) -> Any:
    if "joints" in frame_obj and frame_obj["joints"] is not None:
        return frame_obj["joints"]
    people = frame_obj.get("people")
    if isinstance(people, list) and people:
        for person in people:
            if isinstance(person, dict) and person.get("id") == 0 and "joints" in person:
                return person["joints"]
        first = people[0]
        if isinstance(first, dict):
            return first.get("joints")
    return None


def pose3d_diff(
    pose_a: dict[str, Any] | str | Path | bytes,
    pose_b: dict[str, Any] | str | Path | bytes,
) -> tuple[bool, float]:
    """Return (byte_identical, max_joint_diff_m) between two pose3d structures or files."""
    dict_a, bytes_a = _load_json_and_bytes(pose_a)
    dict_b, bytes_b = _load_json_and_bytes(pose_b)
    byte_identical = bytes_a == bytes_b

    frames_a = dict_a.get("frames") or []
    frames_b = dict_b.get("frames") or []

    map_a: dict[int, dict[str, Any]] = {}
    for i, f in enumerate(frames_a):
        if isinstance(f, dict):
            idx = int(f.get("frame", f.get("index", i)))
            map_a[idx] = f

    map_b: dict[int, dict[str, Any]] = {}
    for i, f in enumerate(frames_b):
        if isinstance(f, dict):
            idx = int(f.get("frame", f.get("index", i)))
            map_b[idx] = f

    max_diff = 0.0
    for idx in sorted(set(map_a.keys()) & set(map_b.keys())):
        ja = _select_person_joints(map_a[idx])
        jb = _select_person_joints(map_b[idx])
        if ja is not None and jb is not None:
            d = _compare_joints_container(ja, jb)
            if d > max_diff:
                max_diff = d

    return (byte_identical, float(max_diff))


def animation_max_joint_diff_m(
    anim_a: dict[str, Any] | str | Path | bytes,
    anim_b: dict[str, Any] | str | Path | bytes,
) -> float:
    """Return the maximum joint Euclidean distance in metres between two animation files/dicts."""
    dict_a, _ = _load_json_and_bytes(anim_a)
    dict_b, _ = _load_json_and_bytes(anim_b)

    frames_a = dict_a.get("frames") or dict_a.get("keyframes") or []
    frames_b = dict_b.get("frames") or dict_b.get("keyframes") or []

    map_a: dict[int, dict[str, Any]] = {}
    for i, f in enumerate(frames_a):
        if isinstance(f, dict):
            idx = int(f.get("index", f.get("frame", i)))
            map_a[idx] = f

    map_b: dict[int, dict[str, Any]] = {}
    for i, f in enumerate(frames_b):
        if isinstance(f, dict):
            idx = int(f.get("index", f.get("frame", i)))
            map_b[idx] = f

    max_diff = 0.0
    for idx in sorted(set(map_a.keys()) & set(map_b.keys())):
        ja = _select_person_joints(map_a[idx])
        jb = _select_person_joints(map_b[idx])
        if ja is not None and jb is not None:
            d = _compare_joints_container(ja, jb)
            if d > max_diff:
                max_diff = d

    return float(max_diff)
