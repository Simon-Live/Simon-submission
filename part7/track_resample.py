"""People tracked at one rate, 3D at another (moalborati/simon#62).

The people step can track at a low rate (`SIMON7_P2_TRACK_FPS`, e.g. 3 fps) while Part 2's 3D run samples at
`SIMON7_P2_FPS` (e.g. 5 fps). `part2 run --tracks` needs an entry for every frame it samples and uses only each
person's `bbox` (`multi3d.tracks_to_boxes`), so Part 7 writes a tracks.json at the 3D rate: each box is
interpolated linearly in time between the two tracked frames around it; `mask_rle` and `confidence` come from the
nearer tracked frame (the contract requires them; the 3D run does not read the mask). Part 2 numbers sampled
frames 0, 1, 2, ... and `part2 run --tracks` refuses a file whose frame numbers differ from those it sampled, so the
resampled file must have exactly Part 2's frames (TICKET-203). Part 2's rule (`part2.frames._nearest_per_step`, which
`ingest` and `runapi.ingest_frame_count` use): over the decoded frame timestamps `pts` (ffprobe
`best_effort_timestamp_time`), sample n is the source frame nearest `pts[0] + n / fps`, and sampling stops at the first n
whose target is at least half a step (minus 1e-9 s) past `pts[-1]`. Sample n sits at `pts[k] - pts[0]` seconds
(frames.json `t_ms`). `sample_times` applies that rule; `probe_sample_times` reads the timestamps of the 3D input.
"""
from __future__ import annotations

import json
import math
import subprocess
from pathlib import Path
from typing import Any

PROBE_TIMEOUT_S = 120


def sample_times(pts: list[float], fps: float) -> list[float]:
    """The times (seconds from the first frame) of the frames `part2 run --fps <fps>` samples from a video whose
    decoded frame timestamps are `pts`: Part 2's own rule (part2/frames.py `_nearest_per_step`), the source frame
    nearest t0, t0 + 1/fps, ..., deduplicated, stopping half a step past the last frame. Part 2 refuses a tracks
    file that covers more or fewer frames than this (`_check_same_frames`).

    TICKET-203: this copies a private Part 2 rule. Exit condition: replace it with Part 2's documented frame listing
    when it ships; `tests/part7/test_track_resample_frames.py` compares it with Part 2's own code until then."""
    if not pts:
        return []
    keep, j, step, n = [], 0, 1 / fps, 0
    while True:
        target = pts[0] + n * step
        if target - pts[-1] >= step / 2 - 1e-9:
            return [round(pts[k] - pts[0], 6) for k in keep]
        while j + 1 < len(pts) and abs(pts[j + 1] - target) <= abs(pts[j] - target):
            j += 1
        if not keep or keep[-1] != j:
            keep.append(j)
        n += 1


def probe_pts(video: Path) -> list[float]:
    """The decoded frame timestamps of `video` in seconds, read the way Part 2 reads them (ffprobe)."""
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "frame=best_effort_timestamp_time", "-of", "csv=p=0", str(video)],
                         capture_output=True, text=True, check=True, timeout=PROBE_TIMEOUT_S).stdout
    return [float(x.strip().rstrip(",")) for x in out.splitlines() if x.strip().rstrip(",") not in ("", "N/A")]


def probe_sample_times(video: Path | str, fps: float) -> list[float] | None:
    """`sample_times` for `video` from its timestamps; None when ffprobe cannot read them."""
    try:
        return sample_times(probe_pts(Path(video)), fps) or None
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def uniform_sample_times(duration_s: float, source_fps: float, fps: float) -> list[float]:
    """`sample_times` for a clip of `duration_s` whose frames are evenly spaced at `source_fps` (no timestamps to read)."""
    count = max(1, round(duration_s * source_fps))
    return sample_times([k / source_fps for k in range(count)], fps)


def resample(doc: dict[str, Any], from_fps: float, to_fps: float, duration_s: float,
             times: dict[int, float] | None = None, out_times: list[float] | None = None) -> dict[str, Any]:
    """`doc` (tracks.json at `from_fps`) at `to_fps` over `duration_s`. `times` maps a tracked frame to its
    seconds (Part 2's frames.json); without it a frame is at `frame / from_fps`. `out_times` (from
    `sample_times`) gives the exact frames Part 2 will sample; without it, frames 0..duration*to_fps+1."""
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
    grid = out_times if out_times is not None else [i / to_fps for i in range(int(math.floor(duration_s * to_fps)) + 2)]
    for i, t in enumerate(grid):
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
                  times: dict[int, float] | None = None, video: Path | None = None,
                  out_times: list[float] | None = None) -> Path:
    """Write `tracks` resampled to `to_fps` at `out` and return `out`. With `video` (the clip Part 2 will read), or
    `out_times` already worked out from it, the frames are exactly the ones Part 2 samples from it (moalborati/simon#62:
    one frame too many was refused)."""
    doc = json.loads(tracks.read_text(encoding="utf-8"))
    if out_times is None and video is not None:
        out_times = sample_times(probe_pts(video), to_fps)
    out.write_text(json.dumps(resample(doc, from_fps, to_fps, duration_s, times, out_times)), encoding="utf-8")
    return out
