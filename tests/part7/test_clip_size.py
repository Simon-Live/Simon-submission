"""TICKET-067: every job's clip has a long side of at most 1280 px, and the track stage names Part 2's exit.

Part 2 `track` sends every frame to a remote tracker, so its time grows with the pixel count (processor.md
"Clip size", people.md "One clip path").
"""

from __future__ import annotations

from pathlib import Path
import subprocess
from typing import Any

import pytest

from part7 import config, media, people, runner
from media_frames import coded_frames  # APP-M2: a remux keeps the frames, not the file bytes
from part7.parts import p2_pose
from support import Api
from test_people import VISITOR, Fakes, _people_job, _step


def _make(dst: Path, size: str, *, codec: list[str] | None = None, extra: list[str] | None = None) -> Path:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc=size={size}:rate=5:duration=2",
                    *(codec or ["-c:v", "libx264", "-pix_fmt", "yuv420p"]), *(extra or []), str(dst)],
                   check=True, timeout=120)
    return dst


def _size(path: Path) -> tuple[int, int]:
    meta = media.probe(path)
    return (meta["width"], meta["height"])


def _log(api: Api, job: dict[str, Any]) -> str:
    return (api.app.queue.job_dir(job["id"]) / "steps" / "part7.log").read_text(encoding="utf-8")


# ----- the scale rule --------------------------------------------------------------------------------------
@pytest.mark.parametrize("w, h, cap, out", [
    (1080, 1920, 1280, (608, 1080)),  # portrait phone clip: 1080 px tall at most, as the trim rule before TICKET-067
    (2160, 3840, 1280, (608, 1080)),  # 4K portrait
    (3840, 2160, 1280, (1280, 720)),  # 4K landscape
    (2048, 1080, 1280, (1280, 674)),  # the staging upload of job 85186cf1f3c0
    (1920, 1080, 1280, (1280, 720)),
    (1280, 720, 1280, (1280, 720)),  # at the cap: unchanged
    (720, 1280, 1280, (608, 1080)),
    (640, 360, 1280, (640, 360)),  # below the cap: never upscaled
    (360, 640, 1280, (360, 640)),
    (641, 361, 1280, (640, 360)),  # odd sizes become even
    (1281, 721, 1280, (1280, 720)),
    (1920, 1080, 960, (960, 540)),  # a cap under 1080 bounds the height too
    (1080, 1920, 960, (540, 960)),
    (1, 1, 1280, (2, 2)),
    (2048, 1080, 0, (2048, 1080)),  # 0: the legacy trim rule, 1080 px tall at most and nothing else
    (1080, 1920, 0, (608, 1080)),
    (3840, 2160, 0, (1920, 1080)),
])
def test_scaled_size_fits_the_long_side_and_height_keeps_aspect_and_evens(
    w: int, h: int, cap: int, out: tuple[int, int]
) -> None:
    assert media.scaled_size(w, h, cap) == out


@pytest.mark.parametrize("env, cap", [
    (None, 1280), ("960", 960), ("0", 0), ("abc", 1280), ("5", 1280), ("-1", 1280), (" 720 ", 720),
])
def test_clip_max_side_reads_the_env(monkeypatch: pytest.MonkeyPatch, env: str | None, cap: int) -> None:
    if env is None:
        monkeypatch.delenv("SIMON7_CLIP_MAX_SIDE", raising=False)
    else:
        monkeypatch.setenv("SIMON7_CLIP_MAX_SIDE", env)
    assert config.clip_max_side() == cap


def _meta(w: int, h: int, rotation: int = 0, sar: tuple[int, int] = (1, 1)) -> dict[str, Any]:
    return {"width": w, "height": h, "rotation": rotation, "sar": sar}


def test_display_size_turns_rotated_frames_and_widens_non_square_pixels() -> None:
    assert media.display_size(_meta(1920, 1080)) == (1920, 1080)
    assert media.display_size(_meta(1920, 1080, 90)) == (1080, 1920)
    assert media.display_size(_meta(1920, 1080, 270)) == (1080, 1920)
    assert media.display_size(_meta(1920, 1080, 180)) == (1920, 1080)
    assert media.display_size(_meta(1440, 1080, sar=(4, 3))) == (1920, 1080)
    assert media.display_size(_meta(1440, 1080, 90, (4, 3))) == (810, 1440)  # the pixel shape turns with the frame


def test_scale_decision_names_the_rule() -> None:
    assert people.scale_decision(_meta(2048, 1080), 1280, cut=False) == (
        "scale to 1280x674 (long side cap 1280 px, 1080 px tall at most)")
    assert people.scale_decision(_meta(1280, 720), 1280, cut=True) == (
        "size kept (long side cap 1280 px, 1080 px tall at most)")
    assert people.scale_decision(_meta(1920, 1080, 90), 1280, cut=False) == (
        "scale to 608x1080 (long side cap 1280 px, 1080 px tall at most)")  # by the displayed size
    assert people.scale_decision(_meta(1440, 1080, sar=(4, 3)), 1280, cut=False) == (
        "scale to 1280x720 (long side cap 1280 px, 1080 px tall at most)")
    assert people.scale_decision(_meta(2048, 1080), 0, cut=False) == "size kept (long side cap off)"
    assert people.scale_decision(_meta(1080, 1920), 0, cut=True) == (
        "scale to 608x1080 (long side cap off, trim keeps 1080 px tall at most)")


# ----- ffmpeg gives the rule's size --------------------------------------------------------------------------
@pytest.mark.parametrize("size, want", [("2160x3840", (608, 1080)), ("1080x1920", (608, 1080)),
                                        ("2048x1080", (1280, 674))])
def test_normalize_and_trim_scale_large_clips_to_the_rule(tmp_path: Path, size: str, want: tuple[int, int]) -> None:
    src = _make(tmp_path / "src.mp4", size)
    assert _size(media.normalize(src, tmp_path / "n.mp4", max_side=1280)) == want
    cut = media.trim(src, tmp_path / "t.mp4", 200, 1600, max_side=1280)
    assert _size(cut) == want
    assert media.probe(cut)["fps"] == 5.0  # the frame rate is untouched


@pytest.mark.parametrize("size", ["1280x720", "640x360"])
def test_a_clip_within_the_cap_is_copied_byte_for_byte(tmp_path: Path, size: str) -> None:
    src = _make(tmp_path / "src.mp4", size)
    assert coded_frames(media.normalize(src, tmp_path / "n.mp4", max_side=1280)) == coded_frames(src)
    assert _size(media.trim(src, tmp_path / "t.mp4", 200, 1600, max_side=1280)) == _size(src)


def test_odd_sizes_are_made_even(tmp_path: Path) -> None:
    src = _make(tmp_path / "odd.mkv", "641x361", codec=["-c:v", "ffv1"])
    assert _size(media.normalize(src, tmp_path / "n.mp4", max_side=1280)) == (640, 360)
    assert _size(media.trim(src, tmp_path / "t.mp4", 200, 1600, max_side=1280)) == (640, 360)


def _rotated(tmp_path: Path) -> Path:
    src = tmp_path / "phone.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-display_rotation", "90", "-i",
                    str(_make(tmp_path / "land.mp4", "1920x1080")), "-c", "copy", str(src)], check=True, timeout=60)
    return src


def test_a_rotated_phone_clip_scales_upright(tmp_path: Path) -> None:
    src = _rotated(tmp_path)
    meta = media.probe(src)
    assert (meta["width"], meta["height"], meta["rotation"]) == (1920, 1080, 90)  # coded size; shown 1080x1920
    assert media.display_size(meta) == (1080, 1920)
    assert _size(media.normalize(src, tmp_path / "n.mp4", max_side=1280)) == (608, 1080)
    assert _size(media.trim(src, tmp_path / "t.mp4", 200, 1600, max_side=1280)) == (608, 1080)


@pytest.mark.parametrize("size, want", [("1440x1080", (1280, 720)), ("480x360", (640, 360))])
def test_non_square_pixels_scale_by_the_displayed_size_without_distortion(
    tmp_path: Path, size: str, want: tuple[int, int]
) -> None:
    src = _make(tmp_path / "ana.mp4", size, extra=["-vf", "setsar=4/3"])
    assert media.probe(src)["sar"] == (4, 3)  # shown 16:9 from 4:3 coded pixels
    for out in (media.normalize(src, tmp_path / "n.mp4", max_side=1280),
                media.trim(src, tmp_path / "t.mp4", 200, 1600, max_side=1280)):
        meta = media.probe(out)
        assert (meta["width"], meta["height"], meta["sar"]) == (*want, (1, 1))  # still 16:9, square pixels


def test_cap_zero_keeps_the_rules_from_before_ticket_067(tmp_path: Path) -> None:
    src = _make(tmp_path / "src.mp4", "1080x1920")
    assert coded_frames(media.normalize(src, tmp_path / "n.mp4", max_side=0)) == coded_frames(src)  # no cap at all
    legacy = media.trim(src, tmp_path / "legacy.mp4", 200, 1600)
    assert _size(legacy) == (608, 1080)  # the trim keeps its 1080 px height cap
    assert media.trim(src, tmp_path / "zero.mp4", 200, 1600, max_side=0).read_bytes() == legacy.read_bytes()


def test_the_legacy_trim_keeps_its_1080p_cap(tmp_path: Path) -> None:
    src = _make(tmp_path / "src.mp4", "2048x1080")
    assert _size(media.trim(src, tmp_path / "t.mp4", 200, 1600)) == (2048, 1080)  # `videos.py` test clips


# ----- the people job --------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def wide_mp4(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _make(tmp_path_factory.mktemp("clipsize") / "wide.mp4", "2048x1080")


def test_the_people_job_scales_its_clip_and_logs_the_decision_and_part2s_exit(
    api: Api, wide_mp4: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SIMON7_CLIP_MAX_SIDE", raising=False)
    Fakes(monkeypatch, {0: 20})
    job = _people_job(api, wide_mp4)
    assert _size(api.app.queue.job_dir(job["id"]) / "work" / "clip.mp4") == (1280, 674)
    text = _log(api, job)
    assert " 2048x1080 5 fps 2000 ms h264, no trim, scale to 1280x674 (long side cap 1280 px, 1080 px tall" in text
    assert "clip out: clip.mp4 1280x674 5 fps" in text and "from 2048x1080" in text
    assert "stage track end in" in text and "exits 2:0" in text and "no part calls" not in text


def test_a_trimmed_people_job_scales_too_and_the_env_can_turn_the_cap_off(
    api: Api, wide_mp4: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    Fakes(monkeypatch, {0: 20})
    job = _people_job(api, wide_mp4, {"start_ms": 200, "end_ms": 1800})
    assert _size(api.app.queue.job_dir(job["id"]) / "work" / "clip.mp4") == (1280, 674)
    monkeypatch.setenv("SIMON7_CLIP_MAX_SIDE", "0")
    job = _people_job(api, wide_mp4)
    assert _size(api.app.queue.job_dir(job["id"]) / "work" / "clip.mp4") == (2048, 1080)
    assert "size kept (long side cap off)" in _log(api, job)


def test_a_trimmed_portrait_people_job_is_1080_px_tall_and_cap_zero_keeps_that(
    api: Api, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    portrait = _make(tmp_path / "portrait.mp4", "1080x1920")
    Fakes(monkeypatch, {0: 20})
    monkeypatch.delenv("SIMON7_CLIP_MAX_SIDE", raising=False)
    job = _people_job(api, portrait, {"start_ms": 200, "end_ms": 1800})
    assert _size(api.app.queue.job_dir(job["id"]) / "work" / "clip.mp4") == (608, 1080)
    assert "scale to 608x1080 (long side cap 1280 px, 1080 px tall at most)" in _log(api, job)
    monkeypatch.setenv("SIMON7_CLIP_MAX_SIDE", "0")
    job = _people_job(api, portrait, {"start_ms": 200, "end_ms": 1800})
    assert _size(api.app.queue.job_dir(job["id"]) / "work" / "clip.mp4") == (608, 1080)
    assert "scale to 608x1080 (long side cap off, trim keeps 1080 px tall at most)" in _log(api, job)


def test_a_rotated_people_job_logs_the_size_it_writes(api: Api, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    Fakes(monkeypatch, {0: 20})
    monkeypatch.delenv("SIMON7_CLIP_MAX_SIDE", raising=False)
    job = _people_job(api, _rotated(tmp_path))
    assert _size(api.app.queue.job_dir(job["id"]) / "work" / "clip.mp4") == (608, 1080)
    text = _log(api, job)
    assert "scale to 608x1080 (long side cap 1280 px, 1080 px tall at most)" in text
    assert "clip out: clip.mp4 608x1080 5 fps" in text


def test_a_failed_tracker_attempt_and_its_fallback_both_show_in_the_track_stage(
    api: Api, wide_mp4: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fakes = Fakes(monkeypatch, {0: 20})

    def track(clip: Path, work: Path, **kw: Any) -> tuple[runner.Step, Path]:
        step, found = fakes.track(clip, work, **kw)
        step["first_try"] = _step(2, 1)  # as `p2_pose.track` returns the fallback after a failed api-sam31 run
        return (step, found)

    monkeypatch.setattr(p2_pose, "track", track)
    assert "stage track end in" in _log(api, job := _people_job(api, wide_mp4))
    assert "exits 2:1 2:0" in _log(api, job)


def test_a_failed_track_stage_quotes_part2s_step(api: Api, wide_mp4: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    Fakes(monkeypatch, {0: 20})
    monkeypatch.setattr(p2_pose, "track", lambda clip, work, **kw: (_step(2, 1), Path(work) / "missing.json"))
    status, up = api.upload(wide_mp4)
    assert status == 201
    status, doc = api.json("POST", "api/people", {"upload_id": up["upload_id"]}, VISITOR)
    assert status == 202, doc
    job = api.app.queue.wait(doc["job"], 60)
    assert job and job["status"] == "failed", job
    assert "stage track failed in" in _log(api, job) and "part 2 exit 1" in _log(api, job)
