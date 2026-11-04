"""Tests for `part7.media` (TICKET-009)."""

from __future__ import annotations

from pathlib import Path
import subprocess
import pytest

from part7 import media


def _frame_hashes(path: Path) -> str:
    done = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:v:0", "-f", "md5", "-c", "copy", "-"],
                          capture_output=True, text=True, check=True)
    return done.stdout.strip()


def _make_sample_mp4(dst: Path, duration_s: float = 2.0) -> Path:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"testsrc=duration={duration_s}:size=320x240:rate=30",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(dst),
        ],
        capture_output=True,
        check=True,
    )
    return dst


def _make_sample_webm(dst: Path, duration_s: float = 1.5) -> Path:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"testsrc=duration={duration_s}:size=320x240:rate=30",
            "-c:v",
            "libvpx",
            "-pix_fmt",
            "yuv420p",
            str(dst),
        ],
        capture_output=True,
        check=True,
    )
    return dst


def test_probe_and_clamp(tmp_path: Path) -> None:
    mp4 = _make_sample_mp4(tmp_path / "sample.mp4", duration_s=2.0)
    info = media.probe(mp4)
    assert info["codec"] == "h264"
    assert info["width"] == 320
    assert info["height"] == 240
    assert 1900 <= info["duration_ms"] <= 2100
    assert info["fps"] == pytest.approx(30.0, abs=0.1)

    assert media.clamp_part6_duration_ms(400) == 1000
    assert media.clamp_part6_duration_ms(5000) == 5000
    assert media.clamp_part6_duration_ms(250000) == 120000

    bad = tmp_path / "not_video.txt"
    bad.write_text("plain text, not a video", encoding="utf-8")
    with pytest.raises(ValueError):
        media.probe(bad)


def test_normalize_preserves_h264_mp4_and_transcodes_webm(tmp_path: Path) -> None:
    mp4 = _make_sample_mp4(tmp_path / "orig.mp4", duration_s=1.2)
    norm_mp4 = media.normalize(mp4, tmp_path / "out_copy.mp4")
    # APP-M2: a remux (stream copy, tags stripped), not a file copy; the coded frames are the source's
    assert _frame_hashes(norm_mp4) == _frame_hashes(mp4)
    assert media.probe(norm_mp4)["codec"] == "h264"

    webm = _make_sample_webm(tmp_path / "orig.webm", duration_s=1.2)
    norm_from_webm = media.normalize(webm, tmp_path / "from_webm.mp4")
    info = media.probe(norm_from_webm)
    assert info["codec"] == "h264"
    assert info["width"] == 320


def test_trim_and_to_y4m(tmp_path: Path) -> None:
    mp4 = _make_sample_mp4(tmp_path / "long.mp4", duration_s=3.0)
    trimmed = media.trim(mp4, tmp_path / "trimmed.mp4", start_ms=500, end_ms=2000)
    info = media.probe(trimmed)
    assert info["codec"] == "h264"
    assert 1300 <= info["duration_ms"] <= 1700

    y4m = media.to_y4m(trimmed, tmp_path / "cam.y4m", seconds=1.0)
    assert y4m.is_file()
    header = y4m.read_bytes()[:64]
    assert header.startswith(b"YUV4MPEG2")
