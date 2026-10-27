"""Builds web/data/demo.json for the demo viewer (spec demo-viewer.md).

The page needs, per take, the input as Part 2 delivered it, the aligned output, the DTW frame map
onto take 1's timeline and the label flips repaired, plus the metrics JSON and the per-frame spread.
`build` is pure; `main` gets the numbers from `part3.metrics.compute` and writes the file.
"""
import math

from part3 import io
from part3.joints import BONES, JOINTS, bone_index
from part3.metrics import compute
from part3.synth import FPS

OUT_PATH = io.REPO / "web" / "data" / "demo.json"
# ADR-0003: one phone at a time, so four separate takes; colours fixed by demo-viewer.md.
TAKE_COLORS = ("#1f77b4", "#ff7f0e", "#2ca02c", "#d62728")
COORD_DECIMALS = io.OUTPUT_DECIMALS
ANGLE_DECIMALS = 3
METRIC_DECIMALS = 3


def _finite(value):
    """float(value), or None for None, NaN and infinities."""
    if value is None:
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def _round(value, decimals):
    """Rounded float (negative zero folded to zero), or None when not finite."""
    value = _finite(value)
    return None if value is None else io.round_clean(value, decimals)


def round_metrics(obj):
    """Round every float to 3 decimals as `make check-3` prints it; ints and bools stay as they are."""
    if hasattr(obj, "item") and not isinstance(obj, (dict, list, tuple)):
        obj = obj.item()  # numpy scalar to the Python scalar
    if isinstance(obj, bool) or obj is None or isinstance(obj, (int, str)):
        return obj
    if isinstance(obj, float):
        return _round(obj, METRIC_DECIMALS)
    if isinstance(obj, dict):
        return {str(key): round_metrics(value) for key, value in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [round_metrics(value) for value in obj]
    raise TypeError(f"metrics hold a value the page cannot show: {type(obj).__name__}")


def _person(frame, person_id):
    """The kept person of a frame: the one with person_id when present, else the first; None if empty."""
    people = frame.get("people") or []
    for person in people:
        if person_id is not None and person.get("id") == person_id:
            return person
    return people[0] if people else None


def frames_to_points(doc, person_id=None):
    """Per frame: 17 [x, y, z] lists in canonical joint order (4 decimals), or None when no person."""
    out = []
    for frame in doc["frames"]:
        person = _person(frame, person_id)
        if person is None:
            out.append(None)
            continue
        joints = person["joints"]
        out.append([[_round(joints[name][axis], COORD_DECIMALS) for axis in "xyz"] for name in JOINTS])
    return out


def _bones():
    return [[bone_index(src), bone_index(dst)] for _, src, dst in BONES]


def _camera(camera):
    return {key: _round(camera[key], ANGLE_DECIMALS)
            for key in ("azimuth_deg", "pitch_deg", "roll_deg")}


def _take(entry, person_id):
    number = int(entry["take"])
    return {
        "take": number,
        "camera": _camera(entry["camera"]),
        "color": TAKE_COLORS[number - 1],
        "input": frames_to_points(entry["input"], person_id),
        "output": frames_to_points(entry["output"], person_id),
        "map": [_round(v, ANGLE_DECIMALS) for v in entry["map"]],
        "flips": sorted(int(i) for i in entry["flips"]),
    }


def build(metrics, detail):
    """The demo.json object from the metrics dict and the per-take detail (see module doc)."""
    entries = sorted(detail["takes"], key=lambda e: int(e["take"]))
    if [int(e["take"]) for e in entries] != [1, 2, 3, 4]:
        raise ValueError("demo data needs exactly the takes 1, 2, 3 and 4")
    person_id = (entries[0]["output"].get("person") or {}).get("id")
    return {
        "metrics": round_metrics(metrics),
        "takes": [_take(entry, person_id) for entry in entries],
        "bones": _bones(),
        "spread_max_per_frame": [_round(v, ANGLE_DECIMALS) for v in detail["spread_max_per_frame"]],
        "fps": FPS,
    }


def dumps(obj):
    """Deterministic compact JSON text; NaN can never reach the file."""
    return io.dumps(obj, separators=(",", ":"), allow_nan=False)


def main():
    metrics, detail = compute(out_dir="out/check-3")
    text = dumps(build(metrics, detail))
    io.write_text(OUT_PATH, text, mkdir=True)
    print(f"wrote {OUT_PATH.relative_to(io.REPO)} ({len(text)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
