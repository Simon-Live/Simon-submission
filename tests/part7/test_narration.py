"""TICKET-146: trainer narration becomes timed cues (docs/specs/narration.md). The API is faked; no test spends money."""

from __future__ import annotations

import io
import json
import math
from pathlib import Path
import struct
import subprocess
from typing import Any
import urllib.error
import wave

import pytest

from part7 import narration, narration_api, narration_routes

RATE = 16000
SECTIONS = [
    {"start_ms": 0, "end_ms": 5000, "index": 1, "count": 2},
    {"start_ms": 5000, "end_ms": 10000, "index": 2, "count": 2},
]


def tone_wav(path: Path, bursts: list[tuple[float, float]], seconds: float = 10.0, amp: float = 0.5) -> Path:
    """A mono WAV with a 220 Hz burst at each (start_s, end_s): the speech whose times we know."""
    total = int(seconds * RATE)
    data = [0] * total
    for a, b in bursts:
        for i in range(int(a * RATE), min(total, int(b * RATE))):
            data[i] = int(amp * 32767 * math.sin(2 * math.pi * 220 * i / RATE))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(struct.pack(f"<{total}h", *data))
    return path


def video_with_audio(path: Path, wav: Path, seconds: float = 10.0) -> Path:
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc=size=160x120:rate=5:duration={seconds}",
         "-i", str(wav), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path)],
        check=True, timeout=120,
    )
    return path


def video_without_audio(path: Path, seconds: float = 10.0) -> Path:
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc=size=160x120:rate=5:duration={seconds}",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)],
        check=True, timeout=120,
    )
    return path


class Resp(io.BytesIO):
    def __enter__(self) -> "Resp":
        return self

    def __exit__(self, *a: Any) -> None:
        return None


def answer(turns: list[dict[str, Any]], text: str = "hello") -> Any:
    seen: list[Any] = []

    def opener(req: Any, timeout: float = 0) -> Resp:
        seen.append(req)
        return Resp(json.dumps({"sessionId": "s", "transcript": text, "audioDurationMs": 10000, "turns": turns}).encode())

    opener.seen = seen  # type: ignore[attr-defined]
    return opener


def turn(i: int, start_ms: int, end_ms: int, text: str) -> dict[str, Any]:
    return {"turnId": i, "startMs": start_ms, "endMs": end_ms, "transcript": text}


@pytest.fixture(autouse=True)
def _narration_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """tests/conftest.py switches narration off for every other test; these need it on."""
    monkeypatch.setenv("SIMON7_NARRATION", "on")


@pytest.fixture()
def keys_dir(tmp_path: Path) -> Path:
    d = tmp_path / "keys"
    d.mkdir()
    (d / "MODEL_API_KEY").write_text("test-key-1234567890\n")
    return d


# ----- sections and attaching ----------------------------------------------------------------------------------
def test_derive_sections_equal_slices_and_repetitions() -> None:
    assert narration.derive_sections({}, 1500) == []
    ten = narration.derive_sections({}, 10000)  # round(10 / 4) = 2 slices
    assert [(s["start_ms"], s["end_ms"]) for s in ten] == [(0, 5000), (5000, 10000)]
    assert all(s["count"] == 2 for s in ten)
    doc = {"fps": 30, "people": [{"id": 0, "repetitions": [
        {"keyframes": [{"t_ms": 0}, {"t_ms": 900}]}, {"keyframes": [{"frame": 120}, {"frame": 150}]},
        {"keyframes": [{"t": 8.0}]}]}]}
    assert narration.rep_starts(doc) == [0, 4000, 8000]
    reps = narration.derive_sections(doc, 12000)
    assert [(s["start_ms"], s["end_ms"]) for s in reps] == [(0, 4000), (4000, 8000), (8000, 12000)]
    short = narration.derive_sections({"people": [{"id": 0, "repetitions": [{"keyframes": [{"t_ms": 500}]}]}]}, 9000)
    assert [(s["start_ms"], s["end_ms"]) for s in short] == [(0, 4500), (4500, 9000)]  # a 0.5 s section is joined, then equal slices


def test_cue_in_one_section_and_on_the_boundary() -> None:
    one = narration.attach_cue({"start_s": 1.2, "end_s": 2.3, "text": "a"}, SECTIONS, [], 0)
    assert one["section"]["index"] == 1 and one["also_sections"] == []
    edge = narration.attach_cue({"start_s": 5.0, "end_s": 6.0, "text": "b"}, SECTIONS, [], 1)
    assert edge["section"]["index"] == 2 and edge["also_sections"] == []  # a phrase starting at the cut belongs after it


def test_phrase_spanning_two_sections_goes_where_most_of_it_is() -> None:
    mostly_first = narration.attach_cue({"start_s": 3.0, "end_s": 5.5, "text": "a"}, SECTIONS, [], 0)
    assert mostly_first["section"]["index"] == 1 and mostly_first["also_sections"] == [2]
    mostly_second = narration.attach_cue({"start_s": 4.8, "end_s": 7.0, "text": "b"}, SECTIONS, [], 1)
    assert mostly_second["section"]["index"] == 2 and mostly_second["also_sections"] == [1]
    tie = narration.attach_cue({"start_s": 4.0, "end_s": 6.0, "text": "c"}, SECTIONS, [], 2)
    assert tie["section"]["index"] == 1  # equal share: the earlier section


def test_phrase_outside_the_clip_is_dropped_and_keyframe_is_the_last_before_start() -> None:
    assert narration.attach_cue({"start_s": 11.0, "end_s": 12.0, "text": "late"}, SECTIONS, [], 0) is None
    marks = [{"name": "start", "t": 0.0}, {"name": "bottom", "t": 1.0}, {"name": "top", "t": 2.0}]
    cue = narration.attach_cue({"start_s": 1.5, "end_s": 2.5, "text": "x"}, SECTIONS, marks, 0)
    assert cue["keyframe"] == {"name": "bottom", "t": 1.0}
    assert narration.attach_cue({"start_s": 0.0, "end_s": 0.5, "text": "y"}, SECTIONS, [{"name": "k", "t": 1.0}], 0)["keyframe"] is None
    assert narration.attach_all([], SECTIONS, marks) == []  # empty transcript


def test_keyframe_marks_from_keyframes_or_repetitions() -> None:
    assert narration.keyframe_marks({"fps": 30, "keyframes": [{"index": 30, "t": 1.0, "name": "b"}, {"t": 0, "name": "a"}, {"t": 2}]}) == [
        {"name": "a", "t": 0.0}, {"name": "b", "t": 1.0}]
    reps = {"people": [{"repetitions": [{"keyframes": [{"frame": 15, "name": "mid"}]}]}], "fps": 30}
    assert narration.keyframe_marks(reps) == [{"name": "mid", "t": 0.5}]
    assert narration.keyframe_marks(None) == []


# ----- audio ---------------------------------------------------------------------------------------------------
def test_snap_moves_the_start_to_the_first_voiced_frame(tmp_path: Path) -> None:
    levels = narration.frame_levels(tone_wav(tmp_path / "a.wav", [(1.2, 2.3), (4.8, 6.2)]))
    first = narration.snap({"start_s": 0.78, "end_s": 2.86, "text": "a"}, levels)
    assert abs(first["start_s"] - 1.2) <= 0.02 and abs(first["end_s"] - 2.3) <= 0.03
    assert first["api_start_s"] == 0.78 and first["api_end_s"] == 2.86
    silent = narration.snap({"start_s": 3.0, "end_s": 4.0, "text": "q"}, levels)
    assert silent["start_s"] == 3.0 and silent["end_s"] == 4.0  # nothing voiced inside: the API times stand
    assert narration.snap({"start_s": 50.0, "end_s": 51.0, "text": "z"}, levels)["start_s"] == 50.0


def test_loudest_dbfs() -> None:
    assert narration.loudest_dbfs([]) == -math.inf and narration.loudest_dbfs([0.0]) == -math.inf
    assert round(narration.loudest_dbfs([0.1, 0.5])) == -6


def test_extract_audio_keeps_the_trim_window_and_none_without_audio(tmp_path: Path) -> None:
    clip = video_with_audio(tmp_path / "v.mp4", tone_wav(tmp_path / "t.wav", [(6.0, 7.0)]))
    out = narration.extract_audio(clip, tmp_path / "o.wav", 5000, 10000)
    assert out is not None
    levels = narration.frame_levels(out)
    first = next(i for i, v in enumerate(levels) if v > 0.05) * 0.01
    assert abs(first - 1.0) <= 0.1 and len(levels) >= 490  # the burst at 6 s is at 1 s in a window from 5 s
    assert narration.extract_audio(video_without_audio(tmp_path / "n.mp4"), tmp_path / "x.wav") is None
    assert narration.extract_audio(tmp_path / "missing.mp4", tmp_path / "y.wav") is None  # nothing readable: no audio


# ----- the client ----------------------------------------------------------------------------------------------
def test_transcribe_sends_endpointing_and_returns_turns(tmp_path: Path, keys_dir: Path) -> None:
    wav = tone_wav(tmp_path / "a.wav", [(1.0, 2.0)])
    opener = answer([turn(0, 780, 2860, " first "), turn(1, 100, 100, "empty span"), turn(2, 4000, 5000, ""), {"junk": 1}, 7,
                     turn(3, 4780, 6060, "second")], "all text")
    ledger = tmp_path / "spend.jsonl"
    got = narration_api.transcribe(wav, ledger=ledger, keys_dir=keys_dir, opener=opener, call="t")
    assert got["turns"] == [{"start_s": 0.78, "end_s": 2.86, "text": "first"}, {"start_s": 4.78, "end_s": 6.06, "text": "second"}]
    assert got["text"] == "all text" and got["duration_s"] == 10.0
    req = opener.seen[0]
    assert req.full_url == narration_api.URL and req.get_header("Authorization") == "Bearer test-key-1234567890"
    assert b'"mode": "ENDPOINTING"' in req.data and b"muse-voice-transcribe-1.0" in req.data and b"RIFF" in req.data
    line = json.loads(ledger.read_text().splitlines()[0])
    assert line["call"] == "t" and line["estimated_usd"] == round(10 / 3600 * 0.18, 6) and line["model"] == narration_api.MODEL
    assert "test-key" not in ledger.read_text()


def test_transcribe_errors_are_narration_errors(tmp_path: Path, keys_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    wav = tone_wav(tmp_path / "a.wav", [(1.0, 2.0)])
    ledger = tmp_path / "spend.jsonl"

    def failing(exc: Exception) -> Any:
        def opener(req: Any, timeout: float = 0) -> Any:
            raise exc
        return opener

    http = urllib.error.HTTPError("u", 400, "bad", {}, io.BytesIO(b"x"))  # type: ignore[arg-type]
    for exc, text in ((http, "HTTP 400"), (urllib.error.URLError("down"), "URLError"), (TimeoutError(), "TimeoutError")):
        with pytest.raises(narration_api.NarrationError, match=text):
            narration_api.transcribe(wav, ledger=ledger, keys_dir=keys_dir, opener=failing(exc))
    assert len(ledger.read_text().splitlines()) == 3  # the call was reserved before it was sent: a billed 5xx or timeout counts
    bad = lambda req, timeout=0: Resp(b"not json")  # noqa: E731
    with pytest.raises(narration_api.NarrationError, match="not JSON"):
        narration_api.transcribe(wav, ledger=ledger, keys_dir=keys_dir, opener=bad)
    with pytest.raises(narration_api.NarrationError, match="no turns"):
        narration_api.transcribe(wav, ledger=ledger, keys_dir=keys_dir, opener=lambda req, timeout=0: Resp(b'{"transcript": "x", "turns": null}'))
    with pytest.raises(narration_api.NarrationError, match="no Meta Model API key"):
        narration_api.transcribe(wav, ledger=ledger, keys_dir=tmp_path / "nokeys", opener=answer([]))
    (tmp_path / "bad.wav").write_bytes(b"nope")
    with pytest.raises(narration_api.NarrationError, match="not a readable WAV"):
        narration_api.transcribe(tmp_path / "bad.wav", ledger=ledger, keys_dir=keys_dir, opener=answer([]))


def test_spend_cap_stops_the_call_before_it_is_made(tmp_path: Path, keys_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    wav = tone_wav(tmp_path / "a.wav", [(1.0, 2.0)])
    ledger = tmp_path / "spend.jsonl"
    ledger.write_text('{"estimated_usd": 0.4999}\nbroken\n{"estimated_usd": "x"}\n')
    opener = answer([turn(0, 0, 1000, "hi")])
    with pytest.raises(narration_api.NarrationError, match=r"cap of \$0.50"):
        narration_api.transcribe(wav, ledger=ledger, cap=0.50, keys_dir=keys_dir, opener=opener)
    assert opener.seen == []
    assert narration_api.transcribe(wav, ledger=ledger, cap=1.0, keys_dir=keys_dir, opener=opener)["turns"]
    monkeypatch.setenv("SIMON7_NARRATION_CAP_USD", "0.25")
    assert narration_api.cap_usd() == 0.25
    monkeypatch.setenv("SIMON7_NARRATION_CAP_USD", "nope")
    assert narration_api.cap_usd() is None
    monkeypatch.setenv("SIMON7_NARRATION_CAP_USD", "-1")
    assert narration_api.cap_usd() is None
    assert narration_api.spent_usd(tmp_path / "none.jsonl") == 0.0


# ----- attach: the whole path and its fallbacks ----------------------------------------------------------------
def speech_clip(tmp_path: Path) -> Path:
    return video_with_audio(tmp_path / "raw.mp4", tone_wav(tmp_path / "t.wav", [(1.2, 2.3), (4.8, 6.2)]))


def run_attach(tmp_path: Path, raw: Path, keys_dir: Path, opener: Any, **kw: Any) -> tuple[Path | None, Path]:
    entry = tmp_path / "entry"
    entry.mkdir(exist_ok=True)
    video = tmp_path / "video.mp4"
    if not video.exists():
        video_without_audio(video)
    got = narration.attach(raw, entry, keyframes=kw.pop("keyframes", None), video=video, ledger=tmp_path / "spend.jsonl",
                           keys_dir=keys_dir, opener=opener, **kw)
    return got, entry


def test_attach_writes_cues_snapped_to_the_voice(tmp_path: Path, keys_dir: Path) -> None:
    opener = answer([turn(0, 780, 2860, "knees out"), turn(1, 4780, 6060, "push the floor away")])
    got, entry = run_attach(tmp_path, speech_clip(tmp_path), keys_dir, opener)
    assert got == entry / "narration.json"
    doc = json.loads(got.read_text())
    assert doc["format"] == "simon.narration.v1" and doc["source"] == "muse-voice-transcribe-1.0" and doc["duration_s"] == 10.0
    first, second = doc["cues"]
    assert abs(first["start_s"] - 1.2) <= 0.05 and first["api_start_s"] == 0.78 and first["section"]["index"] == 1
    assert abs(second["start_s"] - 4.8) <= 0.05 and second["section"]["index"] == 2 and second["also_sections"] == [1]
    assert doc["sections"] == SECTIONS and "test-key" not in json.dumps(doc)
    assert len((tmp_path / "spend.jsonl").read_text().splitlines()) == 1


def test_attach_uses_the_trim_window_of_the_upload(tmp_path: Path, keys_dir: Path) -> None:
    raw = video_with_audio(tmp_path / "raw.mp4", tone_wav(tmp_path / "t.wav", [(6.2, 7.2)], seconds=12.0), seconds=12.0)
    opener = answer([turn(0, 1000, 2400, "after the trim start")])
    got, _ = run_attach(tmp_path, raw, keys_dir, opener, trim={"start_ms": 5000, "end_ms": 15000})
    cue = json.loads(got.read_text())["cues"][0]
    assert abs(cue["start_s"] - 1.2) <= 0.05  # 6.2 s in the upload is 1.2 s in the trimmed clip


def test_no_audio_track_means_no_file_and_no_call(tmp_path: Path, keys_dir: Path) -> None:
    opener = answer([turn(0, 0, 1000, "x")])
    got, entry = run_attach(tmp_path, video_without_audio(tmp_path / "raw.mp4"), keys_dir, opener)
    assert got is None and not (entry / "narration.json").exists() and opener.seen == []


def test_silent_audio_means_no_call(tmp_path: Path, keys_dir: Path) -> None:
    quiet = video_with_audio(tmp_path / "raw.mp4", tone_wav(tmp_path / "t.wav", [(1.0, 2.0)], amp=0.0001))
    opener = answer([turn(0, 0, 1000, "x")])
    got, _ = run_attach(tmp_path, quiet, keys_dir, opener)
    assert got is None and opener.seen == [] and not (tmp_path / "spend.jsonl").exists()


def test_empty_transcript_and_all_phrases_outside_mean_no_file(tmp_path: Path, keys_dir: Path) -> None:
    raw = speech_clip(tmp_path)
    assert run_attach(tmp_path, raw, keys_dir, answer([]))[0] is None
    assert run_attach(tmp_path, raw, keys_dir, answer([turn(0, 30000, 31000, "late")]))[0] is None


def test_api_failure_leaves_no_file_and_never_raises(tmp_path: Path, keys_dir: Path) -> None:
    raw = speech_clip(tmp_path)
    entry = tmp_path / "entry"
    entry.mkdir()
    (entry / "narration.json").write_text("{}")  # a stale file from an earlier run goes away

    def boom(req: Any, timeout: float = 0) -> Any:
        raise urllib.error.URLError("down")

    got, _ = run_attach(tmp_path, raw, keys_dir, boom)
    assert got is None and not (entry / "narration.json").exists()
    assert run_attach(tmp_path, raw, tmp_path / "nokeys", answer([turn(0, 0, 1000, "x")]))[0] is None
    assert run_attach(tmp_path, tmp_path / "missing.mp4", keys_dir, answer([]))[0] is None


def test_failure_is_one_log_line_in_the_job_log(tmp_path: Path, keys_dir: Path) -> None:
    jobs = tmp_path / "jobs" / "abc123" / "work"
    jobs.mkdir(parents=True)
    def boom(req: Any, timeout: float = 0) -> Any:
        raise urllib.error.URLError("down")

    got, _ = run_attach(tmp_path, speech_clip(tmp_path), keys_dir, boom, job_dir=jobs)
    assert got is None
    log = (tmp_path / "jobs" / "abc123" / "steps" / "part7.log").read_text()
    assert "narration: skipped" in log and "test-key" not in log


def test_off_switch(tmp_path: Path, keys_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIMON7_NARRATION", "off")
    opener = answer([turn(0, 780, 2860, "x")])
    assert run_attach(tmp_path, speech_clip(tmp_path), keys_dir, opener)[0] is None and opener.seen == []


# ----- the route and the job hook ------------------------------------------------------------------------------
class FakeHandler:
    def __init__(self, catalog: Path) -> None:
        self.app = type("A", (), {"child": type("C", (), {"catalog_dir": catalog})()})()
        self.sent: list[tuple[str, int, Any]] = []

    def _json(self, status: int, obj: Any) -> None:
        self.sent.append(("json", status, obj))

    def _error(self, status: int, message: str) -> None:
        self.sent.append(("error", status, message))

    def _send(self, status: int, body: bytes, ctype: str, extra: Any = None) -> None:
        self.sent.append(("bytes", status, (ctype, body)))


def test_route_serves_the_entry_file_and_404s_the_rest(tmp_path: Path) -> None:
    (tmp_path / "squat").mkdir()
    (tmp_path / "squat" / "narration.json").write_text(json.dumps({"format": "simon.narration.v1", "cues": []}))
    (tmp_path / "broken").mkdir()
    (tmp_path / "broken" / "narration.json").write_text("{nope")
    (tmp_path / "plain").mkdir()
    h = FakeHandler(tmp_path)
    assert narration_routes.handle(h, "GET", "narration/squat") and h.sent[-1] == ("json", 200, {"format": "simon.narration.v1", "cues": []})
    (tmp_path / "squat" / "narration.json").write_text(json.dumps({"cues": [], "estimated_usd": 0.0005}))
    narration_routes.handle(h, "GET", "narration/squat")
    assert "estimated_usd" not in h.sent[-1][2] and h.sent[-1][2] == {"cues": []}  # spend is not public
    for entry in ("broken", "plain", "absent", "..", "A_B"):
        assert narration_routes.handle(h, "GET", f"narration/{entry}") and h.sent[-1][:2] == ("error", 404)
    assert not narration_routes.handle(h, "POST", "narration/squat")
    assert not narration_routes.handle(h, "GET", "narration")
    assert not narration_routes.handle(h, "GET", "narration/a/b/c")
    assert not narration_routes.handle(h, "GET", "labels/squat")


def test_trainer_job_calls_narration_once_and_survives_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from part7 import chain, people, processor

    calls: list[dict[str, Any]] = []
    video = video_without_audio(tmp_path / "v.mp4")
    monkeypatch.setattr(people, "prepare_clip", lambda ctx, raw, trim, name: video)
    monkeypatch.setattr(chain, "trainer", lambda *a, **k: {"ok": True, "entry_id": "squat", "parts": {}, "note": None,
                                                         "files": {"keyframes": "kf.json"}})
    monkeypatch.setattr(narration, "attach", lambda raw, entry, **k: calls.append({"entry": entry, **k}))
    ctx = type("Ctx", (), {"work": tmp_path / "work", "set_stage": lambda s, n: None, "set_fields": lambda s, **k: None,
                           "add_note": lambda s, n: None})()
    out = processor.trainer_job(tmp_path / "raw.mp4", name="Squat", category="exercise", catalog=tmp_path / "cat",
                                trim={"start_ms": 1000, "end_ms": 4000})(ctx)
    assert out["entry_id"] == "squat" and len(calls) == 1
    assert calls[0]["entry"] == tmp_path / "cat" / "squat" and calls[0]["files"] == {"keyframes": "kf.json"} and calls[0]["video"] == video
    assert calls[0]["trim"] == {"start_ms": 1000, "end_ms": 4000}


def test_reservation_is_atomic_across_threads(tmp_path: Path) -> None:
    import threading

    ledger = tmp_path / "spend.jsonl"
    results: list[bool] = []

    def one() -> None:
        try:
            narration_api.reserve(ledger, {"estimated_usd": 0.4}, 0.5)
            results.append(True)
        except narration_api.NarrationError:
            results.append(False)

    threads = [threading.Thread(target=one) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert results.count(True) == 1 and len(ledger.read_text().splitlines()) == 1


def test_files_of_any_shape_never_fail_the_hook(tmp_path: Path, keys_dir: Path) -> None:
    for name in ("entry", "entry2"):
        (tmp_path / name).mkdir()
    video = video_without_audio(tmp_path / "v.mp4")
    for files in ("not a dict", ["keyframes"], 7, None, {"keyframes": 5}, {"keyframes": "/nonexistent/kf.json"}):
        got = narration.attach(tmp_path / "raw.mp4", tmp_path / "entry", files=files, video=video, keys_dir=keys_dir)
        assert got is None
    got = narration.attach(speech_clip(tmp_path), tmp_path / "entry2", files="oops", video=video, ledger=tmp_path / "s.jsonl",
                           keys_dir=keys_dir, opener=answer([turn(0, 780, 2860, "ok")]))
    assert got is not None and json.loads(got.read_text())["sections"]  # a bad files value falls back to equal slices


def test_spend_goes_to_the_state_of_the_job(tmp_path: Path, keys_dir: Path) -> None:
    job_work = tmp_path / "state" / "jobs" / "abc123" / "work"
    job_work.mkdir(parents=True)
    narration.attach(speech_clip(tmp_path), tmp_path / "entry", video=video_without_audio(tmp_path / "v.mp4"), job_dir=job_work,
                     keys_dir=keys_dir, opener=answer([turn(0, 780, 2860, "ok")]))
    assert (tmp_path / "state" / "narration" / "spend.jsonl").is_file()


def test_the_whole_job_is_held_to_the_budget(tmp_path: Path, keys_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[float] = []
    for name in ("entry", "entry3"):
        (tmp_path / name).mkdir()

    def opener(req: Any, timeout: float = 0) -> Resp:
        seen.append(timeout)
        return Resp(json.dumps({"turns": [turn(0, 780, 2860, "x")]}).encode())

    monkeypatch.setattr(narration, "BUDGET_S", 30.0)
    got = narration.attach(speech_clip(tmp_path), tmp_path / "entry", video=video_without_audio(tmp_path / "v.mp4"),
                           ledger=tmp_path / "s.jsonl", keys_dir=keys_dir, opener=opener)
    assert got is not None and 0 < seen[0] <= 30.0  # the request may take only what is left of the budget
    monkeypatch.setattr(narration, "BUDGET_S", 0.0)  # used up before the audio is cut: skipped, no call
    seen.clear()
    assert narration.attach(speech_clip(tmp_path), tmp_path / "entry3", video=tmp_path / "v.mp4", ledger=tmp_path / "s2.jsonl",
                            keys_dir=keys_dir, opener=opener) is None and seen == []


def test_no_cap_by_default_a_huge_ledger_never_refuses(tmp_path: Path, keys_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SIMON7_NARRATION_CAP_USD", raising=False)
    wav = tone_wav(tmp_path / "a.wav", [(1.0, 2.0)])
    ledger = tmp_path / "spend.jsonl"
    ledger.write_text('{"estimated_usd": 9999.0}\n')
    assert narration_api.cap_usd() is None
    assert narration_api.transcribe(wav, ledger=ledger, keys_dir=keys_dir, opener=answer([turn(0, 0, 1000, "hi")]))["turns"]
    assert narration_api.spent_usd(ledger) > 9999.0  # still recorded
