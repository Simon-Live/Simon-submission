"""The trainer's own words cut into wav clips (TICKET-270, docs/specs/narration.md)."""

from __future__ import annotations

import json
from pathlib import Path
import wave

import pytest

from part7 import narration, narration_routes
from test_narration import (FakeHandler, _narration_on, answer, keys_dir, run_attach, speech_clip, tone_wav, turn,  # noqa: F401
                            video_with_audio, video_without_audio)


def wav_ms(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / w.getframerate() * 1000


def test_each_clip_is_as_long_as_its_cue_within_50_ms(tmp_path: Path, keys_dir: Path) -> None:  # AC-1
    opener = answer([turn(0, 780, 2860, "knees out"), turn(1, 4780, 6060, "push the floor away")])
    got, entry = run_attach(tmp_path, speech_clip(tmp_path), keys_dir, opener)
    doc = json.loads(got.read_text())
    assert len(doc["cues"]) == 2
    for cue in doc["cues"]:
        clip = entry / "narration" / cue["clip"]["file"]
        assert clip.is_file()
        assert abs(wav_ms(clip) - (cue["end_s"] - cue["start_s"]) * 1000) <= 50
        assert abs(cue["clip"]["ms"] - wav_ms(clip)) <= 1


def test_clips_follow_the_trim_window(tmp_path: Path, keys_dir: Path) -> None:
    raw = video_with_audio(tmp_path / "raw.mp4", tone_wav(tmp_path / "t.wav", [(6.2, 7.2)], seconds=12.0), seconds=12.0)
    got, entry = run_attach(tmp_path, raw, keys_dir, answer([turn(0, 1000, 2400, "after the trim start")]),
                            trim={"start_ms": 5000, "end_ms": 15000})
    cue = json.loads(got.read_text())["cues"][0]
    assert (entry / "narration" / cue["clip"]["file"]).is_file()


def test_no_audio_or_narration_off_writes_no_clip(tmp_path: Path, keys_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    got, entry = run_attach(tmp_path, video_without_audio(tmp_path / "raw.mp4"), keys_dir, answer([turn(0, 0, 1000, "x")]))
    assert got is None and not (entry / "narration").exists()
    monkeypatch.setenv("SIMON7_NARRATION", "off")
    got, entry = run_attach(tmp_path, speech_clip(tmp_path), keys_dir, answer([turn(0, 780, 2860, "knees out")]))
    assert got is None and not (entry / "narration").exists()


def test_a_phrase_too_long_for_a_clip_keeps_its_text_only(tmp_path: Path, keys_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(narration, "CLIP_MAX_MS", 1000)
    got, entry = run_attach(tmp_path, speech_clip(tmp_path), keys_dir, answer([turn(0, 780, 2860, "knees out")]))
    cue = json.loads(got.read_text())["cues"][0]
    assert "clip" not in cue and not (entry / "narration").exists()


def test_a_failed_attach_removes_stale_clips(tmp_path: Path, keys_dir: Path) -> None:
    entry = tmp_path / "entry"
    (entry / "narration").mkdir(parents=True)
    (entry / "narration" / "cue-0.wav").write_bytes(b"old")
    got, _ = run_attach(tmp_path, speech_clip(tmp_path), keys_dir, answer([]))
    assert got is None and not (entry / "narration").exists()


def test_clip_route_serves_the_wav_and_404s_the_rest(tmp_path: Path) -> None:  # AC-2 server side, AC-3
    (tmp_path / "squat" / "narration").mkdir(parents=True)
    (tmp_path / "squat" / "narration" / "cue-1.wav").write_bytes(b"RIFFdata")
    h = FakeHandler(tmp_path)
    assert narration_routes.handle(h, "GET", "narration/squat/cue-1.wav") and h.sent[-1] == ("bytes", 200, ("audio/wav", b"RIFFdata"))
    for route in ("narration/squat/cue-2.wav", "narration/squat/narration.json", "narration/squat/dot",
                  "narration/other/cue-1.wav", "narration/squat/cue-1.mp3", "narration/A_B/cue-1.wav"):
        assert narration_routes.handle(h, "GET", route) and h.sent[-1][:2] == ("error", 404), route
