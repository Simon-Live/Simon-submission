"""Per-take measures of a rehab take: reps, the peak angle of the primary measure, tempo (docs/specs/progress-sheet.md).

PART-5 SEAM (TICKET-283). Part 5 owns "the primary measure and its peak angle". Its analysis (schema 1.12.0) has neither
a primary measure nor an absolute peak angle: `faults[].peak_deg` is a difference from the trainer, and only for a fault.
Until Part 5 publishes them, this adapter reads the best data the result already holds:
- reps: `diagnostics.expected_reference.follower_reps`, else the count of `diagnostics.guard.reps`;
- tempo: `score.tempo.ratio` (read through `history_series._tempo`, so a take with no aligned rep has none);
- angles: the follower's normalised 3D joints in `replay.json` (`simon.replay.v1`, hip-midpoint origin, x subject left,
  y up, z anterior), with the same formulas as Part 5's `part5/measures.py` for the measures listed in `MEASURES`;
- primary measure: the programme's declared measure (`part7/programme.py`), else Part 5's rep measure
  (`diagnostics.expected_reference.measure`), else the measure that moves most in the trainer's own frames.
When Part 5 ships a primary measure and peak angle, `take_facts` is the one function to point at them.
"""

from __future__ import annotations

import math
from typing import Any, Callable

from part7 import history_series

SOURCE = "part7-adapter"  # the facts below were worked out in Part 7 from Part 5's replay, not published by Part 5
ERROR_DEG: float | None = None  # ADR-0006: no in-repo rehab dataset run measures the peak-angle error yet (AC-4)
ERROR_SOURCE = "not yet validated"
MAX_FRAMES = 150
MAX_FPS = 10.0

Vec = tuple[float, float, float]
Frame = dict[str, Vec | None]


def _sub(a: Vec, b: Vec) -> Vec:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _norm(v: Vec) -> float:
    return math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2)


def _between(u: Vec, v: Vec) -> float | None:
    nu, nv = _norm(u), _norm(v)
    if nu == 0 or nv == 0:
        return None
    c = max(-1.0, min(1.0, (u[0] * v[0] + u[1] * v[1] + u[2] * v[2]) / (nu * nv)))
    return math.degrees(math.acos(c))


def _flexion(a: Vec, b: Vec, c: Vec) -> float | None:
    """180 minus the inside angle at `b`: 0 is straight, it grows as the joint bends (Part 5 `_flexion`)."""
    inside = _between(_sub(a, b), _sub(c, b))
    return None if inside is None else 180.0 - inside


def _forward_from_down(seg: Vec) -> float:
    """0 hanging straight down, 90 pointing forward (Part 5 `_forward_from_down`)."""
    return math.degrees(math.atan2(seg[2], -seg[1]))


def _out(seg: Vec, side: str) -> float | None:
    """Signed angle out of the sagittal plane, positive away from the midline (Part 5 `_out_angle`)."""
    n = _norm(seg)
    if n == 0:
        return None
    away = seg[0] if side == "left" else -seg[0]
    return math.degrees(math.asin(max(-1.0, min(1.0, away / n))))


def _mid(a: Vec, b: Vec) -> Vec:
    return ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, (a[2] + b[2]) / 2)


def _lean(f: Frame) -> float | None:
    if any(f.get(j) is None for j in ("left_shoulder", "right_shoulder", "left_hip", "right_hip")):
        return None
    spine = _sub(_mid(f["left_shoulder"], f["right_shoulder"]), _mid(f["left_hip"], f["right_hip"]))  # type: ignore[arg-type]
    return math.degrees(math.atan2(spine[2], spine[1]))


def _sided(side: str) -> dict[str, tuple[tuple[str, ...], Callable[..., float | None], str]]:
    j = lambda *names: tuple(f"{side}_{n}" for n in names)  # noqa: E731
    return {
        f"{side}_knee_flexion": (j("hip", "knee", "ankle"), _flexion, "sagittal"),
        f"{side}_elbow_flexion": (j("shoulder", "elbow", "wrist"), _flexion, "sagittal"),
        f"{side}_thigh_forward": (j("hip", "knee"), lambda a, b: _forward_from_down(_sub(b, a)), "sagittal"),
        f"{side}_thigh_out": (j("hip", "knee"), lambda a, b: _out(_sub(b, a), side), "frontal"),
        f"{side}_upper_arm_out": (j("shoulder", "elbow"), lambda a, b: _out(_sub(b, a), side), "frontal"),
    }


# name -> (joints, formula over those joints, plane the skeleton replay is drawn in)
MEASURES = {**_sided("left"), **_sided("right")}
LEAN = "trunk_lean_forward"
ARM_FORWARD = ("left_upper_arm_forward", "right_upper_arm_forward")  # relative to the trunk, as Part 5
ALL_NAMES = (*MEASURES, LEAN, *ARM_FORWARD)


def plane(measure: str | None) -> str:
    """"side" for a measure seen best from the side (a bend, a raise forward), else "front"."""
    if measure in MEASURES:
        return "side" if MEASURES[measure][2] == "sagittal" else "front"
    return "side" if measure in (LEAN, *ARM_FORWARD) else "front"


def frames_of(replay: Any, key: str = "follower") -> list[Frame]:
    """Each frame of `replay[key]` as `{joint: (x, y, z) or None}`; [] for anything that is not a replay."""
    joints = replay.get("joints") if isinstance(replay, dict) else None
    rows = replay.get(key) if isinstance(replay, dict) else None
    if not isinstance(joints, list) or not isinstance(rows, list):
        return []
    out = []
    for row in rows:
        if not isinstance(row, list) or len(row) != len(joints):
            return []
        out.append({str(name): _point(p) for name, p in zip(joints, row)})
    return out


def _point(p: Any) -> Vec | None:
    if isinstance(p, list) and len(p) == 3 and all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in p):
        return (float(p[0]), float(p[1]), float(p[2]))
    return None


def value(frame: Frame, measure: str) -> float | None:
    """One measure in one frame, degrees; None when a joint it needs is unseen."""
    if measure == LEAN:
        return _lean(frame)
    if measure in ARM_FORWARD:
        side = measure.split("_")[0]
        sh, el, lean = frame.get(f"{side}_shoulder"), frame.get(f"{side}_elbow"), _lean(frame)
        return None if sh is None or el is None or lean is None else _forward_from_down(_sub(el, sh)) + lean
    joints, formula, _ = MEASURES[measure]
    pts = [frame.get(name) for name in joints]
    return None if any(p is None for p in pts) else formula(*pts)


def series(frames: list[Frame], measure: str) -> list[float | None]:
    return [value(f, measure) for f in frames]


def peak(values: list[float | None]) -> tuple[float, int] | None:
    """`(degrees, frame)` of the largest value after a 3-frame median (one bad frame is not a peak); None with no value."""
    best: tuple[float, int] | None = None
    for i in range(len(values)):
        window = [v for v in values[max(0, i - 1): i + 2] if v is not None]
        if values[i] is None or not window:
            continue
        smooth = sorted(window)[len(window) // 2]
        if best is None or smooth > best[0]:
            best = (smooth, i)
    return (round(best[0], 1), best[1]) if best else None


def _span(values: list[float | None]) -> float:
    seen = [v for v in values if v is not None]
    return max(seen) - min(seen) if seen else 0.0


def _obj(value_: Any) -> dict[str, Any]:
    return value_ if isinstance(value_, dict) else {}


def reps(analysis: Any) -> int | None:
    ref = _obj(_obj(_obj(analysis).get("diagnostics")).get("expected_reference"))
    count = ref.get("follower_reps")
    if isinstance(count, int) and not isinstance(count, bool) and count >= 0:
        return count
    guard = _obj(_obj(_obj(analysis).get("diagnostics")).get("guard")).get("reps")
    return len(guard) if isinstance(guard, list) and guard else None


def tempo(analysis: Any) -> float | None:
    ratio = history_series._tempo(_obj(analysis), True)["ratio"]
    return round(ratio, 2) if ratio is not None else None


def primary(analysis: Any, replay: Any, declared: str | None = None) -> tuple[str | None, str]:
    """`(measure, why)`: "declared" by the programme, "part5_reps" (Part 5's rep measure) or "trainer_range"."""
    if declared in ALL_NAMES:
        return declared, "declared"
    rep_measure = _obj(_obj(_obj(analysis).get("diagnostics")).get("expected_reference")).get("measure")
    if rep_measure in ALL_NAMES:
        return rep_measure, "part5_reps"
    trainer = frames_of(replay, "expected")
    if not trainer:
        return None, "none"
    ranked = max(ALL_NAMES, key=lambda m: (_span(series(trainer, m)), m))
    return (ranked, "trainer_range") if _span(series(trainer, ranked)) > 0 else (None, "none")


def take_facts(analysis: Any, replay: Any, declared: str | None = None) -> dict[str, Any]:
    """`{measure, measure_source, peak_deg, peaks, reps, tempo_ratio, source}` of one take. `peaks` holds every measure's
    peak, so a sheet can follow a measure the programme declares after the take was made."""
    follower = frames_of(replay)
    peaks = {}
    for name in ALL_NAMES:
        found = peak(series(follower, name))
        if found is not None:
            peaks[name] = found[0]
    measure, why = primary(analysis, replay, declared)
    return {"measure": measure, "measure_source": why, "peak_deg": peaks.get(measure) if measure else None, "peaks": peaks,
            "reps": reps(analysis), "tempo_ratio": tempo(analysis), "source": SOURCE}


def skeleton(replay: Any) -> dict[str, Any] | None:
    """The follower's 3D joints at up to MAX_FPS and MAX_FRAMES frames, 3 decimals: the take's skeleton-only replay."""
    joints, bones = (replay.get(k) if isinstance(replay, dict) else None for k in ("joints", "bones"))
    rows, times = (replay.get(k) if isinstance(replay, dict) else None for k in ("follower", "follower_t"))
    if not frames_of(replay) or not isinstance(bones, list):
        return None
    times = times if isinstance(times, list) and len(times) == len(rows) else [i / 30.0 for i in range(len(rows))]
    span = (times[-1] - times[0]) if len(times) > 1 else 0.0
    keep = max(1, min(MAX_FRAMES, int(span * MAX_FPS) + 1))
    picks = sorted({round(i * (len(rows) - 1) / max(1, keep - 1)) for i in range(keep)}) if keep > 1 else [0]
    frames = [[[round(v, 3) for v in p] if _point(p) else None for p in rows[i]] for i in picks]
    return {"joints": list(joints), "bones": [list(b) for b in bones if isinstance(b, list) and len(b) == 2],
            "t": [round(float(times[i]) - float(times[0]), 3) for i in picks], "frames": frames}
