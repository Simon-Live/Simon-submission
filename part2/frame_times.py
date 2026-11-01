"""The frame times Part 2 samples from a video: a public, documented read of the rule `run` and `track` use.

    part2 frame-times --input clip.mp4 [--fps 5] [--out frames.json]

`sample_times(pts, fps)` and `frame_times(src, fps)` return the same `frame` / `t_ms` / `file` records, in the same
frames.json document, that `part2 run` and `part2 track` write for the same video and fps (frames.ingest): the same
ffprobe `best_effort_timestamp_time` source and the same nearest-per-step rule (frames._nearest_per_step, imported, not
copied), without decoding or writing a single image. Callers such as Part 7 resample onto Part 2's 3D rate with this
and never copy the rule. docs/specs/frame-times.md.
"""
import json
from pathlib import Path

from part2 import frames
from part2.schema import write_json


def sample_times(pts: list[float], fps: float | None = None) -> list[int]:
    """Indices into `pts` (decoded frame timestamps in seconds, in decode order) of the frames `run` keeps at `fps`:
    the source frame nearest t0, t0 + 1/fps, ... deduplicated, in order. Every index when `fps` is None."""
    if not pts:
        raise ValueError("no video frames to sample")
    if fps is None:
        return list(range(len(pts)))
    if fps <= 0:
        raise ValueError(f"fps must be > 0, got {fps}")
    return frames._nearest_per_step(pts, fps)


def manifest(src: Path, pts: list[float], fps: float | None = None) -> dict:
    """The frames.json document `frames.ingest` writes for a video with timestamps `pts` at `fps`."""
    keep = sample_times(pts, fps)
    recs = [{"frame": i, "t_ms": round((pts[k] - pts[0]) * 1000, 3), "file": f"{i:06d}.jpg"} for i, k in enumerate(keep)]
    return {"source": str(src), "t0_pts_ms": round(pts[0] * 1000, 3), "frames": recs}


def frame_times(src: Path, fps: float | None = None) -> dict:
    """The frames.json document `run` would use for video `src` at `fps`. FileNotFoundError for a missing file,
    ValueError for a directory, a bad fps or a file with no video frames, RuntimeError when ffprobe fails."""
    src = Path(src)
    if src.is_dir():
        raise ValueError(f"{src} is a directory; frame-times reads a video (an image dir keeps its own frames.json)")
    if not src.is_file():
        raise FileNotFoundError(src)
    if fps is not None and fps <= 0:
        raise ValueError(f"fps must be > 0, got {fps}")
    pts = frames._probe_timestamps(src)
    if not pts:
        raise ValueError(f"no video frames decoded from {src}")
    return manifest(src, pts, fps)


def command(src: Path, fps: float | None, out: Path | None) -> int:
    """Print the document (indent 1, as frames.json is written) or write it to `out`; exit code 0."""
    doc = frame_times(src, fps)
    if out is None:
        print(json.dumps(doc, indent=1))
    else:
        out = Path(out)
        out.parent.mkdir(parents=True, exist_ok=True)
        write_json(out, doc, indent=1)
        print(f"{len(doc['frames'])} frames -> {out}")
    return 0
