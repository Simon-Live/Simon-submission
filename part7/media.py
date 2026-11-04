"""Video probing, normalization, trimming, and Y4M conversion (TICKET-009)."""

from __future__ import annotations

import json
import math
from pathlib import Path
import subprocess
import threading
from typing import Any

from part7 import config, ffsafe

NON_VIDEO_CODECS = {"png", "mjpeg", "gif", "webp", "bmp", "tiff", "ppm", "pgm"}
# A browser MediaRecorder WebM has a 1 ms time base, `r_frame_rate` 1000/1 and no average rate. Encoded as is,
# the MP4 gets 1000 frames per second of duplicates and an ffmpeg banner of "1k fps", which Part 1 cannot read
# (TICKET-064). The stated rate is trusted up to TRUSTED_FPS without counting. Above it (a 240 fps phone clip,
# or the recorder's 1000/1) the packets are counted: a stated rate up to MAX_FPS that the count agrees with is
# real and kept; anything else, or a missing rate, is re-timed to the counted rate. MAX_FPS is Part 5's limit.
TRUSTED_FPS = 120.0
MAX_FPS = 240.0
FALLBACK_FPS = 30.0
COMMON_FPS = (24.0, 25.0, 30.0, 50.0, 60.0)
SNAP = 0.03  # a counted rate within 3% of a common one is that one
MAX_CLIP_HEIGHT = 1080  # TICKET-067: also the height of the legacy trim rule below
LEGACY_TRIM_FILTER = "scale=-2:'min(1080,ih)'"  # trim before TICKET-067 (the `videos.py` test clips, cap 0)
# The clip keeps the source's first audio track, if it has one (AAC), so the result screen plays it with its sound;
# the parts read the video stream only. `history_store` copies stay silent on purpose.
AUDIO_ARGS = ["-map", "0:v:0", "-map", "0:a:0?", "-c:a", "aac", "-b:a", "128k"]
# APP-M5: no output holds more frames than a source may (`probe` refuses a longer one; this stops a lying container).
FRAME_CAP_ARGS = ["-frames:v", str(ffsafe.MAX_FRAMES)]


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


_PACKETS: dict[tuple[str, int, int], int] = {}  # (path, size, mtime_ns) -> packet count
_PACKETS_MAX = 64
_PACKETS_LOCK = threading.Lock()


def _count_packets(path: Path) -> int:
    """The number of video packets (frames) in `path`, counted by ffprobe without decoding; 0 when unknown.

    Cached per (path, size, mtime): one upload is probed several times while its clip is prepared."""
    try:
        st = Path(path).stat()
    except OSError:
        return 0
    key = (str(Path(path).resolve()), st.st_size, st.st_mtime_ns)
    with _PACKETS_LOCK:
        if key in _PACKETS:
            return _PACKETS[key]
    frames = _ffprobe_packets(path)
    if frames > 0:  # a failed count (0) is tried again next time
        with _PACKETS_LOCK:
            while len(_PACKETS) >= _PACKETS_MAX:
                del _PACKETS[next(iter(_PACKETS))]
            _PACKETS[key] = frames
    return frames


def _ffprobe_packets(path: Path) -> int:
    try:
        res = ffsafe.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_packets",
             "-show_entries", "stream=nb_read_packets", "-of", "csv=p=0", str(path)],
            timeout=60, text=True,
        )
    except (OSError, subprocess.SubprocessError):
        return 0
    try:
        return int(res.stdout.strip().split(",")[0]) if res.returncode == 0 else 0
    except ValueError:
        return 0


def counted_fps(frames: int, duration_s: float) -> float:
    """The frame rate of `frames` over `duration_s`, snapped to a common rate; `FALLBACK_FPS` when implausible."""
    if frames <= 1 or duration_s <= 0:
        return FALLBACK_FPS
    rate = frames / duration_s
    for common in COMMON_FPS:
        if abs(rate - common) <= common * SNAP:
            return common
    return round(rate, 2) if 1.0 <= rate <= MAX_FPS else FALLBACK_FPS


def _fallback_packet_duration_s(path: Path) -> float:
    try:
        res = ffsafe.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "packet=pts_time,duration_time",
             "-of", "json", str(path)],
            timeout=30, text=True,
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
        res = ffsafe.run(
            [
                "ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                "stream=codec_name,codec_type,width,height,r_frame_rate,avg_frame_rate,duration,sample_aspect_ratio"
                ":stream_tags=rotate:stream_side_data=rotation:format=duration,format_name",
                "-of", "json", str(p),
            ],
            timeout=30, text=True,
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
    if max(width, height) > ffsafe.MAX_SIDE or width * height > ffsafe.MAX_PIXELS:
        raise ValueError(f"video too large: {width}x{height} in {p}")

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

    if duration_s > ffsafe.MAX_SOURCE_S:
        raise ValueError(f"video too long: {duration_s:.0f} s in {p}")
    fps, counted = _clip_rate(p, stream, duration_s)
    if fps * duration_s > ffsafe.MAX_FRAMES:
        raise ValueError(f"video has too many frames: about {fps * duration_s:.0f} in {p}")
    duration_ms = int(math.floor(duration_s * 1000.0))

    return {
        "duration_ms": duration_ms,
        "duration_s": float(duration_s),
        "width": width,
        "height": height,
        "codec": codec,
        "fps": round(float(fps), 4),
        "fps_counted": counted,  # the container's rate was missing or not believed; outputs are re-timed to `fps`
        "rotation": _rotation(stream),  # degrees a player turns the coded frame (`width` x `height`) by
        "sar": _sar(stream.get("sample_aspect_ratio")),  # pixel shape (num, den); (1, 1) is square
    }


def _rotation(stream: dict[str, Any]) -> int:
    """The display rotation of `stream` in degrees (side data, else the old `rotate` tag), 0 when none."""
    values = [d.get("rotation") for d in stream.get("side_data_list") or [] if isinstance(d, dict)]
    values.append((stream.get("tags") or {}).get("rotate"))
    for value in values:
        try:
            return int(round(float(value))) % 360
        except (TypeError, ValueError):
            continue
    return 0


def _sar(text: Any) -> tuple[int, int]:
    """`"4:3"` as `(4, 3)`; a missing, zero or unreadable ratio is square."""
    num, _, den = str(text or "").partition(":")
    try:
        n, d = int(num), int(den)
    except ValueError:
        return (1, 1)
    return (n, d) if n > 0 and d > 0 else (1, 1)


def _clip_rate(p: Path, stream: dict[str, Any], duration_s: float) -> tuple[float, bool]:
    """`(fps, counted)`: the stated rate when believable, else the rate counted from the packets (re-timed)."""
    stated = _parse_fps(stream.get("avg_frame_rate")) or _parse_fps(stream.get("r_frame_rate"))
    if 0 < stated <= TRUSTED_FPS:
        return (stated, False)
    frames = _count_packets(p)
    if not stated and frames == 0:
        return (FALLBACK_FPS, False)  # nothing stated, nothing counted: ffmpeg's default rate, no re-timing
    if 0 < stated <= MAX_FPS and frames > 1 and abs(frames / duration_s - stated) <= stated * SNAP:
        return (stated, False)  # a real high-rate clip: the packets agree with the container
    return (counted_fps(frames, duration_s), True)


def rate_args(meta: dict[str, Any]) -> list[str]:
    """ffmpeg output options for a constant `meta["fps"]` when the source rate was counted, else none.

    Sources with a believable rate keep ffmpeg's defaults, so the frozen test clips re-encode byte for byte.
    """
    return ["-fps_mode", "cfr", "-r", f"{meta['fps']:g}"] if meta.get("fps_counted") else []


def clamp_part6_duration_ms(duration_ms: int) -> int:
    """Clamp duration in ms to Part 6's allowed `[1000, 120000]` range."""
    return max(
        config.PART6_MIN_DURATION_MS,
        min(config.PART6_MAX_DURATION_MS, int(duration_ms)),
    )


def _rescale(a: int, b: int, c: int) -> int:
    """`a * b / c` rounded to the nearest integer, halves away from zero (ffmpeg's `av_rescale`)."""
    return (a * b + c // 2) // c


def _turned(meta: dict[str, Any]) -> bool:
    return int(meta.get("rotation") or 0) % 180 == 90


def upright_size(meta: dict[str, Any]) -> tuple[int, int]:
    """The coded size of a probed clip with its rotation applied: the frame ffmpeg's filters see."""
    width, height = int(meta["width"]), int(meta["height"])
    return (height, width) if _turned(meta) else (width, height)


def display_size(meta: dict[str, Any]) -> tuple[int, int]:
    """The size a player shows a probed clip at: the upright frame (rotation applied) with square pixels.

    ffmpeg turns the frame before the filters run and turns the pixel shape with it, so a non-square pixel
    widens or narrows the upright width (`iw*sar`) and the height stays.
    """
    width, height = upright_size(meta)
    num, den = meta.get("sar") or (1, 1)
    if _turned(meta):
        num, den = den, num
    return (max(1, _rescale(width, num, den)), height)


def scaled_size(width: int, height: int, max_side: int) -> tuple[int, int]:
    """The clip size for a `width` x `height` upright frame with square pixels (TICKET-067).

    With a cap the frame fits inside a long side of `max_side` px and a height of `MAX_CLIP_HEIGHT` px: a
    1080x1920 phone clip becomes 608x1080, 2048x1080 becomes 1280x674. The aspect is kept, nothing is
    upscaled and both sides are even (H.264 yuv420p needs that), by the rounding of ffmpeg's
    `force_original_aspect_ratio=decrease:force_divisible_by=2`. `max_side` 0 is the legacy trim rule
    (`LEGACY_TRIM_FILTER`): at most 1080 px tall, the width rounded to the nearest even number.
    """
    if max_side <= 0:
        tall = min(MAX_CLIP_HEIGHT, height)
        return (max(2, _rescale(tall, width, height * 2) * 2), tall)
    box_w, box_h = min(width, max_side), min(height, max_side, MAX_CLIP_HEIGHT)
    out_w = min(box_w, _rescale(box_h, width, height))
    out_h = min(box_h, _rescale(box_w, height, width))
    return (max(2, out_w - out_w % 2), max(2, out_h - out_h % 2))


def clip_size(meta: dict[str, Any], max_side: int, *, cut: bool) -> tuple[int, int] | None:
    """The size `normalize` (`cut` False) or `trim` (`cut` True) gives a probed clip; None: the frame is left as is.

    `max_side` 0 keeps the size rules from before TICKET-067: `normalize` leaves the frame alone and `trim`
    applies `LEGACY_TRIM_FILTER`. A clip with square pixels whose display size the rule keeps is left alone.
    """
    if max_side <= 0:
        return scaled_size(*upright_size(meta), 0) if cut else None
    shown = display_size(meta)
    out = scaled_size(*shown, max_side)
    if out == shown and tuple(meta.get("sar") or (1, 1)) == (1, 1) and not cut:
        return None
    return out


def scale_filter(size: tuple[int, int]) -> str:
    """The ffmpeg filter that scales the upright frame to `size` with square pixels (`clip_size`)."""
    return f"scale={size[0]}:{size[1]},setsar=1"


def normalize(src: Path | str, dst: Path | str, max_side: int = 0) -> Path:
    """Remux MP4 H.264 without re-encoding, or re-encode other formats (and implausible rates) to MP4 H.264 yuv420p.

    `max_side` caps the size (`clip_size`, 0: no cap); a clip it changes is re-encoded, others keep the rules above.
    Every output is stripped of the source's metadata and chapters (APP-M2): the remux is a stream copy that keeps the
    coded frames and drops the tags (GPS, title, handler names), never a plain file copy.
    """
    src_p = Path(src)
    dst_p = Path(dst)
    dst_p.parent.mkdir(parents=True, exist_ok=True)
    meta = probe(src_p)
    size = clip_size(meta, max_side, cut=False)
    if src_p.suffix.lower() == ".mp4" and meta["codec"] == "h264" and not meta["fps_counted"] and size is None:
        args = ["-map", "0:v:0", "-map", "0:a:0?", "-c", "copy"]
    else:
        args = [*(["-vf", scale_filter(size)] if size else []), "-c:v", "libx264", "-pix_fmt", "yuv420p",
                *rate_args(meta), *AUDIO_ARGS]
    # a source and a destination that are one file are written beside and swapped in
    tmp = dst_p.with_name(f".{dst_p.stem}.norm{dst_p.suffix}") if src_p.resolve() == dst_p.resolve() else dst_p
    res = ffsafe.run(
        ["ffmpeg", "-y", "-i", str(src_p), *args, *FRAME_CAP_ARGS, "-map_metadata", "-1", "-map_chapters", "-1", str(tmp)],
        timeout=300, text=True,
    )
    if res.returncode != 0 or not tmp.is_file():
        if tmp != dst_p:
            tmp.unlink(missing_ok=True)
        raise RuntimeError(f"ffmpeg normalize failed on {src_p}: {res.stderr}")
    if tmp != dst_p:
        tmp.replace(dst_p)
    return dst_p


def trim(src: Path | str, dst: Path | str, start_ms: int, end_ms: int, max_side: int | None = None) -> Path:
    """Trim `src` to [start_ms, end_ms) frame-accurately: an accurate seek and an H.264 re-encode.

    The size is up to 1080p (`LEGACY_TRIM_FILTER`, `max_side` None or 0), or `clip_size(max_side)` (the job clip
    path with its cap).
    """
    src_p, dst_p = Path(src), Path(dst)
    if src_p.resolve() == dst_p.resolve():
        raise ValueError("trim needs a different output file")
    dst_p.parent.mkdir(parents=True, exist_ok=True)
    vf = LEGACY_TRIM_FILTER
    try:
        meta = probe(src_p)
        rate = rate_args(meta)
        size = clip_size(meta, max_side, cut=True) if max_side else None
        if size:
            vf = scale_filter(size)
    except ValueError:
        rate = []  # ffmpeg below names the problem
    res = ffsafe.run(
        [
            "ffmpeg", "-y", "-ss", f"{start_ms / 1000:.3f}", "-i", str(src_p),
            "-t", f"{(end_ms - start_ms) / 1000:.3f}",
            "-vf", vf,
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", *rate,
            *AUDIO_ARGS, *FRAME_CAP_ARGS, "-movflags", "+faststart", str(dst_p),
        ],
        timeout=300, text=True,
    )
    if res.returncode != 0 or not dst_p.is_file():
        raise RuntimeError(f"ffmpeg trim failed on {src_p}: {res.stderr}")
    return dst_p


def to_y4m(src: Path | str, dst: Path | str, seconds: float = 6.0) -> Path:
    """Convert `src` to a 640p 30fps Y4M file for Chromium's fake camera."""
    src_p = Path(src)
    dst_p = Path(dst)
    dst_p.parent.mkdir(parents=True, exist_ok=True)
    res = ffsafe.run(
        ["ffmpeg", "-y", "-i", str(src_p), "-t", str(seconds), "-vf", "scale=640:-2,fps=30", "-pix_fmt", "yuv420p",
         *FRAME_CAP_ARGS, str(dst_p)],
        timeout=180, text=True,
    )
    if res.returncode != 0 or not dst_p.is_file():
        raise RuntimeError(f"ffmpeg to_y4m failed on {src_p}: {res.stderr}")
    return dst_p
