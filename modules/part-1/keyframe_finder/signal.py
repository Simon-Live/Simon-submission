"""Read and write the movement videos the finder consumes."""

import re
import subprocess

import numpy as np


def ffmpeg_exe():
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def probe(path):
    proc = subprocess.run(
        [ffmpeg_exe(), "-hide_banner", "-i", str(path)],
        capture_output=True,
        text=True,
    )
    text = proc.stderr or ""
    size = re.search(r"(\d{2,5})x(\d{2,5})", text)
    fps = re.search(r"(\d+(?:\.\d+)?)\s+fps", text) or re.search(
        r"(\d+(?:\.\d+)?)\s+tbr", text
    )
    if not size or not fps:
        raise RuntimeError(f"could not read video metadata for {path}\n{text}")
    return int(size.group(1)), int(size.group(2)), float(fps.group(1))


def encode_rgb(path, frames, fps):
    """Encode uint8 RGB frames shaped (N, H, W, 3) to an H.264 mp4."""
    frames = np.ascontiguousarray(frames, dtype=np.uint8)
    if frames.ndim != 4 or frames.shape[-1] != 3:
        raise ValueError(f"expected RGB frames, got {frames.shape}")
    count, height, width, _ = frames.shape
    if width % 2 or height % 2:
        raise ValueError("H.264 needs even width and height")
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg_exe(),
        "-y",
        "-loglevel",
        "error",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-s",
        f"{width}x{height}",
        "-r",
        str(fps),
        "-i",
        "pipe:0",
        "-an",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        "-frames:v",
        str(count),
        str(path),
    ]
    proc = subprocess.run(cmd, input=frames.tobytes(), capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode() or f"ffmpeg failed to encode {path}")
