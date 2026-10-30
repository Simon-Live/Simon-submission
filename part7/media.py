"""Video probing, normalization, trimming, and Y4M conversion (TICKET-009)."""

from __future__ import annotations

import json
import math
from pathlib import Path
import shutil
import subprocess
from typing import Any

from part7 import config

NON_VIDEO_CODECS = {"png", "mjpeg", "gif", "webp", "bmp", "tiff", "ppm", "pgm"}


def _parse_fps(rate_str: str | None) -> float:
    if not rate_str or rate_str == "0/0":
        return 0.0
    if "/" in rate_str:
        num_s, _, den_s = rate_str.partition("/")
        try:
            num = float(num_s)
            den = float(den_s)
            return num / den if den > 0 else 0.0
        except ValueError:
            return 0.0
    try:
        return float(rate_str)
    except ValueError:
        return 0.0


def _fallback_packet_duration_s(path: Path) -> float:
    try:
        res = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "packet=pts_time,duration_time",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return 0.0
    if res.returncode != 0 or not res.stdout.strip():
        return 0.0
    try:
        data = json.loads(res.stdout)
    except json.JSONDecodeError:
        return 0.0
    max_end = 0.0
    for pkt in data.get("packets") or []:
        if not isinstance(pkt, dict):
            continue
        try:
            pts = float(pkt.get("pts_time") or 0.0)
        except (TypeError, ValueError):
            pts = 0.0
        try:
            dur = float(pkt.get("duration_time") or 0.0)
        except (TypeError, ValueError):
            dur = 0.0
        if pts + dur > max_end:
            max_end = pts + dur
    return max_end


def probe(path: Path | str) -> dict[str, Any]:
    """Run `ffprobe` on `path` and return video metadata or raise `ValueError`."""
    p = Path(path)
    if not p.is_file() or p.stat().st_size == 0:
        raise ValueError(f"not a video: {p}")

    try:
        res = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=codec_name,codec_type,width,height,r_frame_rate,avg_frame_rate,duration:format=duration,format_name",
                "-of",
                "json",
                str(p),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError(f"ffprobe failed on {p}: {exc}") from exc

    if res.returncode != 0 or not res.stdout.strip():
        raise ValueError(f"not a video: {p}")

    try:
        info = json.loads(res.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError(f"not a video: {p}") from exc

    streams = info.get("streams") or []
    if not streams or not isinstance(streams[0], dict):
        raise ValueError(f"no video stream in {p}")
    stream = streams[0]
    fmt = info.get("format") or {}
    format_name = str(fmt.get("format_name") or "").lower()
    if "image2" in format_name or format_name.endswith("_pipe"):
        raise ValueError(f"image file is not a video: {p}")

    codec = str(stream.get("codec_name") or "").lower()
    if not codec or codec in NON_VIDEO_CODECS:
        raise ValueError(f"unsupported video codec {codec!r} in {p}")

    width = int(stream.get("width") or 0)
    height = int(stream.get("height") or 0)
    if width <= 0 or height <= 0:
        raise ValueError(f"invalid dimensions {width}x{height} in {p}")

    duration_s = 0.0
    for candidate in (stream.get("duration"), fmt.get("duration")):
        if candidate is not None and str(candidate) != "N/A":
            try:
                val = float(candidate)
                if math.isfinite(val) and val > 0:
                    duration_s = val
                    break
            except (TypeError, ValueError):
                continue

    if duration_s <= 0:
        duration_s = _fallback_packet_duration_s(p)
    if duration_s <= 0:
        raise ValueError(f"could not determine positive duration for {p}")

    fps = _parse_fps(stream.get("avg_frame_rate")) or _parse_fps(stream.get("r_frame_rate")) or 30.0
    duration_ms = int(math.floor(duration_s * 1000.0))

    return {
        "duration_ms": duration_ms,
        "duration_s": float(duration_s),
        "width": width,
        "height": height,
        "codec": codec,
        "fps": round(float(fps), 4),
    }


def clamp_part6_duration_ms(duration_ms: int) -> int:
    """Clamp duration in ms to Part 6's allowed `[1000, 120000]` range."""
    return max(
        config.PART6_MIN_DURATION_MS,
        min(config.PART6_MAX_DURATION_MS, int(duration_ms)),
    )


def normalize(src: Path | str, dst: Path | str) -> Path:
    """Copy MP4 H.264 byte-for-byte, or re-encode other formats to MP4 H.264 yuv420p."""
    src_p = Path(src)
    dst_p = Path(dst)
    dst_p.parent.mkdir(parents=True, exist_ok=True)
    meta = probe(src_p)
    if src_p.suffix.lower() == ".mp4" and meta["codec"] == "h264":
        if src_p.resolve() != dst_p.resolve():
            shutil.copyfile(src_p, dst_p)
        return dst_p

    res = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(src_p),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-an",
            str(dst_p),
        ],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    if res.returncode != 0 or not dst_p.is_file():
        raise RuntimeError(f"ffmpeg normalize failed on {src_p}: {res.stderr}")
    return dst_p


def trim(src: Path | str, dst: Path | str, start_ms: int, end_ms: int) -> Path:
    """Trim `src` to [start_ms, end_ms) frame-accurately: an accurate seek and an H.264 re-encode, up to 1080p."""
    src_p, dst_p = Path(src), Path(dst)
    if src_p.resolve() == dst_p.resolve():
        raise ValueError("trim needs a different output file")
    dst_p.parent.mkdir(parents=True, exist_ok=True)
    res = subprocess.run(
        [
            "ffmpeg", "-y", "-ss", f"{start_ms / 1000:.3f}", "-i", str(src_p),
            "-t", f"{(end_ms - start_ms) / 1000:.3f}",
            "-vf", "scale=-2:'min(1080,ih)'",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
            "-an", "-movflags", "+faststart", str(dst_p),
        ],
        capture_output=True, text=True, timeout=300, check=False,
    )
    if res.returncode != 0 or not dst_p.is_file():
        raise RuntimeError(f"ffmpeg trim failed on {src_p}: {res.stderr}")
    return dst_p


def to_y4m(src: Path | str, dst: Path | str, seconds: float = 6.0) -> Path:
    """Convert `src` to a 640p 30fps Y4M file for Chromium's fake camera."""
    src_p = Path(src)
    dst_p = Path(dst)
    dst_p.parent.mkdir(parents=True, exist_ok=True)
    res = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(src_p),
            "-t",
            str(seconds),
            "-vf",
            "scale=640:-2,fps=30",
            "-pix_fmt",
            "yuv420p",
            str(dst_p),
        ],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    if res.returncode != 0 or not dst_p.is_file():
        raise RuntimeError(f"ffmpeg to_y4m failed on {src_p}: {res.stderr}")
    return dst_p
