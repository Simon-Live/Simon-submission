"""Track geometry and the cropped copy Part 1 sees (people.md "Part 7 server", TICKET-058).

`tracks.json` is Part 2's `{frames: [{frame, people: [{id, bbox: [x, y, w, h], confidence, mask_rle?}]}]}`.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
from typing import Any

from part7 import media

MARGIN = 0.15  # people.md: the union box with a 15% margin
# people.md: at least 5% of the picture on every side as well. Tracks are sampled (10 fps) and a box hugs the
# body, so a hand or foot between two tracked frames can reach past a 15% margin of a tight box (TICKET-064).
PAD = 0.05


def load_tracks(path: Path | str) -> list[dict[str, Any]]:
    """Return the `frames` list of a tracks file; ValueError when it is not one."""
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError("the tracks file could not be read") from exc
    frames = doc.get("frames") if isinstance(doc, dict) else None
    if not isinstance(frames, list):
        raise ValueError("the tracks file has no frames")
    return [f for f in frames if isinstance(f, dict) and isinstance(f.get("people"), list)]


def track_size(frames: list[dict[str, Any]]) -> tuple[int, int] | None:
    """The (width, height) the boxes are in, from the first mask (`size` is `[h, w]`), else None."""
    for frame in frames:
        for person in frame["people"]:
            size = (person.get("mask_rle") or {}).get("size") if isinstance(person, dict) else None
            if isinstance(size, list) and len(size) == 2 and all(isinstance(v, (int, float)) and v > 0 for v in size):
                return (int(size[1]), int(size[0]))
    return None


def boxes_of(frames: list[dict[str, Any]], pid: str) -> list[tuple[int, list[float], float]]:
    """Every `(frame, bbox, confidence)` of person `pid`, in frame order."""
    out: list[tuple[int, list[float], float]] = []
    for frame in frames:
        for person in frame["people"]:
            box = person.get("bbox") if isinstance(person, dict) else None
            if str(person.get("id")) == pid and isinstance(box, list) and len(box) == 4:
                conf = person.get("confidence")
                out.append((int(frame.get("frame", 0)), [float(v) for v in box], float(conf) if conf is not None else 0.0))
    return out


def union_box(
    frames: list[dict[str, Any]], pid: str, width: int, height: int, margin: float = MARGIN, pad: float = PAD
) -> tuple[int, int, int, int] | None:
    """The box (x, y, w, h) in video pixels around everywhere `pid` stands; None without boxes.

    Each side grows by `margin` of the box or `pad` of the picture, whichever is larger.

    Width and height are even (libx264 yuv420p) and the box stays inside the picture.
    """
    boxes = boxes_of(frames, pid)
    if not boxes:
        return None
    sw, sh = track_size(frames) or (width, height)
    kx, ky = width / sw, height / sh
    x0 = min(b[0] for _, b, _ in boxes) * kx
    y0 = min(b[1] for _, b, _ in boxes) * ky
    x1 = max(b[0] + b[2] for _, b, _ in boxes) * kx
    y1 = max(b[1] + b[3] for _, b, _ in boxes) * ky
    mx, my = max((x1 - x0) * margin, width * pad), max((y1 - y0) * margin, height * pad)
    x0, y0, x1, y1 = max(0.0, x0 - mx), max(0.0, y0 - my), min(float(width), x1 + mx), min(float(height), y1 + my)
    x, y = int(x0) // 2 * 2, int(y0) // 2 * 2
    w, h = int(x1 - x) // 2 * 2, int(y1 - y) // 2 * 2
    if w < 2 or h < 2:
        return None
    return (x, y, w, h)


def crop_video(src: Path | str, dst: Path | str, box: tuple[int, int, int, int]) -> Path:
    """Write the part of `src` inside `box` as H.264 MP4 (same length and frame times); RuntimeError on failure.

    A source with an implausible frame rate (a clip made before TICKET-064) is re-timed to its counted rate, so
    the copy's ffmpeg banner shows a plain number of fps that Part 1's probe reads.
    """
    x, y, w, h = box
    dst_p = Path(dst)
    dst_p.parent.mkdir(parents=True, exist_ok=True)
    try:
        rate = media.rate_args(media.probe(src))
    except ValueError:
        rate = []  # ffmpeg below names the problem
    res = subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-vf", f"crop={w}:{h}:{x}:{y}",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", *rate, "-an", str(dst_p)],
        capture_output=True, text=True, timeout=300, check=False,
    )
    if res.returncode != 0 or not dst_p.is_file():
        raise RuntimeError(f"ffmpeg crop failed: {res.stderr[-300:]}")
    return dst_p


def person_box(src: Path | str, tracks: Path | str, pid: str) -> tuple[int, int, int, int]:
    """The crop box of `pid` in `src` (`union_box` with the defaults); ValueError when there is none."""
    meta = media.probe(src)
    box = union_box(load_tracks(tracks), pid, meta["width"], meta["height"])
    if box is None:
        raise ValueError(f"person {pid} has no boxes")
    return box


def cropped_for_person(src: Path | str, tracks: Path | str, pid: str, dst: Path | str) -> Path:
    """Crop `src` to the union box of `pid` in `tracks`; ValueError/RuntimeError when that cannot be done."""
    return crop_video(src, dst, person_box(src, tracks, pid))
