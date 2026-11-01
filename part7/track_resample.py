"""People tracked at one rate, 3D at another (moalborati/simon#62).

The people step can track at a low rate (`SIMON7_P2_TRACK_FPS`, e.g. 3 fps) while Part 2's 3D run samples at
`SIMON7_P2_FPS` (e.g. 5 fps). `part2 run --tracks` needs an entry for every frame it samples and uses only each
person's `bbox` (`multi3d.tracks_to_boxes`), so Part 7 writes a tracks.json at the 3D rate: each box is
interpolated linearly in time between the two tracked frames around it; `mask_rle` and `confidence` come from the
nearer tracked frame (the contract requires them; the 3D run does not read the mask). Part 2 numbers sampled
frames 0, 1, 2, ... at `t = frame / fps` (to the nearest source frame), which is the time used here.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any


def resample(doc: dict[str, Any], from_fps: float, to_fps: float, duration_s: float,
             times: dict[int, float] | None = None) -> dict[str, Any]:
    """`doc` (tracks.json at `from_fps`) at `to_fps` over `duration_s`. `times` maps a tracked frame to its
    seconds (Part 2's frames.json); without it a frame is at `frame / from_fps`."""
    at = (lambda n: times[n]) if times else (lambda n: n / from_fps)
    tracks: dict[str, list[tuple[float, dict[str, Any]]]] = {}
    for f in doc.get("frames", []):
        n = int(f["frame"])
        if times and n not in times:
            continue
        for p in f.get("people", []):
            tracks.setdefault(str(p["id"]), []).append((at(n), p))
    for seq in tracks.values():
        seq.sort(key=lambda item: item[0])
    step = 1.0 / from_fps  # a person is carried at most one tracked step past their first or last frame
    frames = []
    for i in range(int(math.floor(duration_s * to_fps)) + 2):
        t = i / to_fps
        people = [p for p in (_at(seq, t, step) for seq in tracks.values()) if p is not None]
        frames.append({"frame": i, "people": people})
    out = {k: v for k, v in doc.items() if k != "frames"}
    out["frames"] = frames
    prov = dict(doc.get("provenance") or {})
    prov["resampled"] = {"by": "part7", "from_fps": from_fps, "to_fps": to_fps, "boxes": "linear in time",
                         "masks": "nearest tracked frame"}
    out["provenance"] = prov
    return out


def _at(seq: list[tuple[float, dict[str, Any]]], t: float, step: float) -> dict[str, Any] | None:
    """This person at time `t`, or None when they are not tracked near it."""
    after = next((k for k, (tk, _) in enumerate(seq) if tk >= t), None)
    if after is None:  # past the last tracked frame
        t0, p0 = seq[-1]
        return dict(p0) if t - t0 <= step else None
    t1, p1 = seq[after]
    if after == 0:  # before the first tracked frame
        return dict(p1) if t1 - t <= step else None
    t0, p0 = seq[after - 1]
    if t1 - t0 > 2 * step:  # a gap in the track: no box is made up across it
        near, tn = (p0, t0) if t - t0 <= t1 - t else (p1, t1)
        return dict(near) if abs(t - tn) <= step else None
    w = 0.0 if t1 == t0 else (t - t0) / (t1 - t0)
    box = [round(a + (b - a) * w, 2) for a, b in zip(p0["bbox"], p1["bbox"])]
    nearer = p0 if w < 0.5 else p1
    return {**nearer, "bbox": box}


def write_at_rate(tracks: Path, out: Path, from_fps: float, to_fps: float, duration_s: float,
                  times: dict[int, float] | None = None) -> Path:
    """Write `tracks` resampled to `to_fps` at `out` and return `out`."""
    doc = json.loads(tracks.read_text(encoding="utf-8"))
    out.write_text(json.dumps(resample(doc, from_fps, to_fps, duration_s, times)), encoding="utf-8")
    return out
