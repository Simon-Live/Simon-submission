"""TICKET-064: recorder clips reach every part at their real, constant frame rate; Part 1 can read its copy."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from part7 import crop, media
from support import part1_reads, recorder_webm


def _packets(path: Path) -> int:
    return media._count_packets(path)


@pytest.fixture(scope="module")
def webm(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return recorder_webm(tmp_path_factory.mktemp("rec") / "upload.webm", 3.0)


@pytest.fixture(scope="module")
def old_1k_clip(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A clip as Part 7 made them before TICKET-064: every millisecond a frame, banner `1k fps`."""
    path = tmp_path_factory.mktemp("old") / "clip.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=30:duration=1",
                    "-r", "1000", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(path)],
                   check=True, timeout=120)
    return path


def test_the_fixture_has_the_recorder_signature(webm: Path) -> None:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=r_frame_rate,avg_frame_rate", "-of", "json", str(webm)],
                         capture_output=True, text=True, check=True).stdout
    stream = json.loads(out)["streams"][0]
    assert stream["r_frame_rate"] == "1000/1" and stream["avg_frame_rate"] == "0/0"


def test_probe_counts_the_real_rate_of_a_recorder_webm(webm: Path) -> None:
    meta = media.probe(webm)
    assert meta["fps_counted"] is True and meta["fps"] == 30.0
    assert 2900 <= meta["duration_ms"] <= 3200


def test_normalize_and_trim_of_a_recorder_webm_are_constant_rate_and_readable_by_part1(
    webm: Path, tmp_path: Path
) -> None:
    whole = media.normalize(webm, tmp_path / "normalized.mp4")
    meta = media.probe(whole)
    assert meta["fps"] == 30.0 and not meta["fps_counted"]
    assert _packets(whole) <= 31 * 3.2  # the old encode wrote about 1000 frames a second of duplicates
    assert part1_reads(whole)
    clip = media.trim(whole, tmp_path / "clip.mp4", 500, 2500)
    assert media.probe(clip)["fps"] == 30.0 and 55 <= _packets(clip) <= 62
    assert part1_reads(clip)


def test_the_old_1000_fps_clip_is_unreadable_by_part1_and_its_crop_is_readable(old_1k_clip: Path, tmp_path: Path) -> None:
    """The staging failure of job 8dddc922a628 reproduced, then fixed on Part 7's side."""
    assert not part1_reads(old_1k_clip)
    assert media.probe(old_1k_clip)["fps_counted"] is True  # 1000 fps is not believed; counted packets are 1000/s
    cropped = crop.crop_video(old_1k_clip, tmp_path / "person.mp4", (40, 20, 200, 200))
    meta = media.probe(cropped)
    assert part1_reads(cropped) and meta["fps"] == media.FALLBACK_FPS and (meta["width"], meta["height"]) == (200, 200)


@pytest.fixture(scope="module")
def phone_240(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A real high-rate clip, as a 240 fps phone records it: the stated and counted rates agree."""
    path = tmp_path_factory.mktemp("hi") / "slowmo.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=160x120:rate=240:duration=1",
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(path)], check=True, timeout=120)
    return path


def test_a_real_240_fps_clip_keeps_its_rate_and_is_not_re_timed(phone_240: Path, tmp_path: Path) -> None:
    meta = media.probe(phone_240)
    assert meta["fps"] == 240.0 and meta["fps_counted"] is False
    assert media.rate_args(meta) == []
    assert media.normalize(phone_240, tmp_path / "n.mp4").read_bytes() == phone_240.read_bytes()  # kept as is
    clip = media.trim(phone_240, tmp_path / "t.mp4", 0, 500)
    assert media.probe(clip)["fps"] == 240.0 and _packets(clip) >= 100  # not re-timed to 30 (15 frames)


def test_a_stated_high_rate_the_packets_disagree_with_is_re_timed(phone_240: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(media, "_count_packets", lambda p: 30)  # 30 packets in 1 s under a stated 240
    meta = media.probe(phone_240)
    assert meta["fps"] == 30.0 and meta["fps_counted"] is True


def test_the_packet_count_runs_once_per_file_version(phone_240: Path, tmp_path: Path,
                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    clip = tmp_path / "c.mp4"
    clip.write_bytes(phone_240.read_bytes())
    runs: list[Path] = []
    real = media._ffprobe_packets
    monkeypatch.setattr(media, "_ffprobe_packets", lambda p: runs.append(p) or real(p))
    counts = [media._count_packets(clip) for _ in range(3)]
    assert counts == [240, 240, 240] and len(runs) == 1
    for _ in range(3):
        media.probe(clip)  # prepare_clip probes the raw upload more than once
    assert len(runs) == 1
    clip.write_bytes(phone_240.read_bytes()[:-1] + b"\0")  # a new version of the file is counted again
    media._count_packets(clip)
    assert len(runs) == 2


def test_believable_rates_keep_ffmpeg_defaults_so_frozen_clips_are_byte_identical(tmp_path: Path) -> None:
    assert media.rate_args({"fps": 25.0, "fps_counted": False}) == []
    assert media.rate_args({"fps": 30.0, "fps_counted": True}) == ["-fps_mode", "cfr", "-r", "30"]
    src = tmp_path / "src.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=160x120:rate=25:duration=2",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(src)], check=True, timeout=60)
    a = media.trim(src, tmp_path / "a.mp4", 200, 1500).read_bytes()
    b = media.trim(src, tmp_path / "b.mp4", 200, 1500).read_bytes()
    assert a == b and media.normalize(src, tmp_path / "n.mp4").read_bytes() == src.read_bytes()


@pytest.mark.parametrize("frames, seconds, fps", [
    (167, 5.566, 30.0), (150, 6.0, 25.0), (139, 6.0, 23.17), (5560, 5.56, media.FALLBACK_FPS),
    (0, 5.0, media.FALLBACK_FPS), (10, 0.0, media.FALLBACK_FPS), (59, 1.0, 60.0),
])
def test_counted_fps_snaps_to_common_rates_and_falls_back(frames: int, seconds: float, fps: float) -> None:
    assert media.counted_fps(frames, seconds) == fps


def test_crop_keeps_context_around_a_tight_box() -> None:
    """A box that hugs the body gets at least 5% of the picture on each side (people.md)."""
    frames = [{"frame": 0, "people": [{"id": 0, "bbox": [300, 200, 40, 100], "confidence": 0.9}]}]
    x, y, w, h = crop.union_box(frames, "0", 640, 480)
    assert x <= 300 - 32 and y <= 200 - 24 and x + w >= 340 + 30 and y + h >= 300 + 22
    assert crop.union_box(frames, "0", 640, 480, margin=0.0, pad=0.0) == (300, 200, 40, 100)
