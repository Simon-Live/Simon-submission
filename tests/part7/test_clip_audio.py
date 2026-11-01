"""A trimmed, normalized or cropped clip keeps the source's sound, so the result screen plays it (results side by side)."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from part7 import crop, media

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")


def make_clip(path: Path, audio: bool, seconds: float = 3.0) -> Path:
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc=size=320x240:rate=15:duration={seconds}"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}", "-c:a", "aac"]
    subprocess.run([*cmd, "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)], check=True)
    return path


def kinds(path: Path) -> list[str]:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "json", str(path)],
                         capture_output=True, text=True, check=True).stdout
    return [s["codec_type"] for s in json.loads(out)["streams"]]


def test_trim_keeps_the_sound(tmp_path: Path) -> None:
    out = media.trim(make_clip(tmp_path / "a.mp4", audio=True), tmp_path / "t.mp4", 500, 2500)
    assert kinds(out) == ["video", "audio"]
    assert abs(media.probe(out)["duration_s"] - 2.0) < 0.15


def test_trim_of_a_silent_clip_stays_silent(tmp_path: Path) -> None:
    out = media.trim(make_clip(tmp_path / "s.mp4", audio=False), tmp_path / "t.mp4", 500, 2500)
    assert kinds(out) == ["video"]


def test_normalize_keeps_the_sound(tmp_path: Path) -> None:
    src = tmp_path / "a.webm"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(make_clip(tmp_path / "a.mp4", audio=True)),
                    "-c:v", "libvpx", "-c:a", "libopus", str(src)], check=True)
    assert kinds(media.normalize(src, tmp_path / "n.mp4")) == ["video", "audio"]


def test_crop_keeps_the_sound(tmp_path: Path) -> None:
    out = crop.crop_video(make_clip(tmp_path / "a.mp4", audio=True), tmp_path / "c.mp4", (0, 0, 160, 240))
    assert kinds(out) == ["video", "audio"]
