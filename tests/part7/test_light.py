"""Part 7 measures the video's light and caps a dark take (docs/specs/video-light.md, TICKET-247)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from part7 import light


def clip(path: Path, color: str) -> Path:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"color=c={color}:size=64x48:rate=10:duration=2",
                    "-pix_fmt", "yuv420p", str(path)], check=True)
    return path


def test_a_bright_clip_reads_ok(tmp_path: Path) -> None:
    got = light.measure(clip(tmp_path / "b.mp4", "0xC8C8C8"))
    assert got and got["level"] == "ok" and got["median_y"] > 150 and got["dark_share"] == 0


def test_a_dark_clip_reads_major(tmp_path: Path) -> None:
    got = light.measure(clip(tmp_path / "d.mp4", "0x2C2C2C"))
    assert got and got["level"] == "major" and got["median_y"] < 60 and got["dark_share"] == 1


def test_a_dim_clip_reads_degraded(tmp_path: Path) -> None:
    got = light.measure(clip(tmp_path / "m.mp4", "0x484848"))
    assert got and got["level"] == "degraded" and 60 <= got["median_y"] < 85


def test_an_unreadable_file_has_no_light(tmp_path: Path) -> None:
    junk = tmp_path / "x.mp4"
    junk.write_bytes(b"not a video")
    assert light.measure(junk) is None
    assert light.measure(tmp_path / "missing.mp4") is None
    assert light.measure(junk, ffmpeg="no-such-ffmpeg") is None


def test_the_twins_calibration_sits_apart() -> None:
    # measured on the check-7 twins: clean median Y 167.2, dark 43.7 (docs/specs/video-light.md)
    assert light.classify(167.2, 0.0) == "ok"
    assert light.classify(43.7, 1.0) == "major"
    assert light.classify(70, 0.0) == "degraded" and light.classify(120, 0.3) == "degraded"


def test_summarise_median_and_share() -> None:
    assert light.summarise([]) is None
    got = light.summarise([30, 200, 210, 220, 230])
    assert got == {"median_y": 210.0, "dark_share": 0.2, "level": "ok"}


def dark() -> dict[str, Any]:
    return {"median_y": 43.7, "dark_share": 1.0, "level": "major"}


def test_a_major_light_caps_at_59_with_the_label() -> None:
    got = light.apply({"score": 85, "grade": "B", "faults": 1}, dark())
    assert got["score"] == 59 and got["grade"] == "F" and got["capped_by"] == [light.CAP_CODE]
    assert got["light_note"] == "The video was too dark to judge form reliably" and got["light"] == dark()
    assert got["video_level"] == "major"


def test_a_score_under_the_cap_is_kept() -> None:
    got = light.apply({"score": 40, "grade": "F"}, dark())
    assert got["score"] == 40 and got["grade"] == "F" and "capped_by" not in got


def test_a_clean_light_changes_no_score() -> None:
    ok = {"median_y": 167.2, "dark_share": 0.0, "level": "ok"}
    got = light.apply({"score": 85, "grade": "B"}, ok)
    assert got["score"] == 85 and got["grade"] == "B" and "light_note" not in got and got["light"] == ok


def test_a_degraded_light_adds_a_note_and_no_cap() -> None:
    got = light.apply({"score": 85, "grade": "B"}, {"median_y": 70, "dark_share": 0.0, "level": "degraded"})
    assert got["score"] == 85 and "capped_by" not in got and got["light_note"] == light.DEGRADED_NOTE
    assert got["video_level"] == "degraded"


def test_no_light_leaves_the_summary_as_it_was() -> None:
    summary = {"score": 85}
    assert light.apply(summary, None) is summary


@pytest.mark.parametrize("light_level,quality,want", [
    ("ok", "ok", "ok"), ("ok", "major", "major"), ("major", "ok", "major"), ("degraded", "ok", "degraded"),
    ("ok", "degraded", "degraded"), ("degraded", "major", "major"), ("ok", None, "not_assessed"), ("degraded", None, "degraded"),
])
def test_the_worst_of_light_and_part_5_wins(light_level: str, quality: str | None, want: str) -> None:
    summary: dict[str, Any] = {"score": 80, "grade": "B"}
    if quality:
        summary["quality"] = {"level": quality}
    got = light.apply(summary, {"median_y": 100, "dark_share": 0, "level": light_level})
    assert got["video_level"] == want
