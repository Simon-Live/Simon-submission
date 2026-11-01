"""TICKET-202: a member the tracker cut into brief pieces, the one 10 fps repeat, and a failed repeat (R1, R2, R4, R5)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from part7.parts import p2_pose
from support import Api
from test_people import Fakes, _step, class_mp4, tracks_doc  # noqa: F401 (class_mp4 is a fixture)
from test_people_fps import _clean_env, _fake_track, _log, _moving, _post  # noqa: F401 (_clean_env is a fixture)


def _ranges(spans: dict[int, tuple[int, int]], frames: int = 20) -> dict[str, Any]:
    """tracks.json where person `id` is seen in frames start..end-1 and the box travels."""
    doc = tracks_doc({}, frames)
    for f in doc["frames"]:
        for pid, (start, end) in spans.items():
            if start <= f["frame"] < end:
                f["people"].append({"id": pid, "bbox": [10 + 90 * pid + f["frame"] * 8, 40, 80, 160], "confidence": 0.9})
    return doc


def _frames_json(folder: Path, fps: int, frames: int = 20) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "frames.json").write_text(
        json.dumps({"frames": [{"frame": n, "t_ms": round(n * 1000 / fps)} for n in range(frames)]}), encoding="utf-8")


def test_a_member_present_7_of_20_frames_is_offered_and_there_is_no_repeat(
    api: Api, class_mp4: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fakes = Fakes(monkeypatch, {0: 20})
    _fake_track(fakes, monkeypatch, {3: _ranges({0: (0, 20), 1: (0, 7)})})  # 7 frames at 3 fps is 2.33 s
    job = _post(api, class_mp4, mode="group")
    assert fakes.track_fps == [3]
    assert [p["id"] for p in job["result"]["people"]] == ["0", "1"]
    assert "dropped moving tracks: 0, 0.0 s in total" in _log(api, job)


def test_a_mover_under_2_seconds_is_shown_when_nobody_qualifies(
    api: Api, class_mp4: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fakes = Fakes(monkeypatch, {0: 5})
    _fake_track(fakes, monkeypatch, {3: _moving({0: 5}), 10: _moving({0: 5})})  # 5 frames at 3 fps is 1.67 s
    job = _post(api, class_mp4, mode="single")
    assert [p["id"] for p in job["result"]["people"]] == ["0"]
    assert fakes.track_fps == [3, 10]  # nobody qualified: the one repeat, and the mover is still shown


def test_brief_pieces_of_one_member_trigger_the_repeat_and_the_drop_is_logged(
    api: Api, class_mp4: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fakes = Fakes(monkeypatch, {0: 20})
    split = _ranges({0: (0, 20), 1: (0, 4), 2: (6, 10)})  # two pieces of 1.33 s: 2.66 s together, a participant is there
    _fake_track(fakes, monkeypatch, {3: split, 10: _ranges({0: (0, 20), 1: (0, 20)})})
    job = _post(api, class_mp4, mode="group")
    assert fakes.track_fps == [3, 10]
    text = _log(api, job)
    assert "2 brief moving tracks at 3 fps cover 2.66 s together" in text and "tracking again at 10 fps" in text
    assert [p["id"] for p in job["result"]["people"]] == ["0", "1"]


def test_pieces_that_together_stay_under_the_threshold_do_not_repeat(
    api: Api, class_mp4: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SIMON7_PEOPLE_MIN_PRESENT_S", "3.0")
    fakes = Fakes(monkeypatch, {0: 20})
    _fake_track(fakes, monkeypatch, {3: _ranges({0: (0, 20), 1: (0, 4), 2: (6, 10)})})  # 1.33 s each, 2.66 s: not over 3 s
    job = _post(api, class_mp4, mode="group")
    assert fakes.track_fps == [3]
    assert "dropped moving tracks: 2, 2.66 s in total" in _log(api, job)


def test_a_failed_repeat_keeps_the_3_fps_result_and_its_frame_times(
    api: Api, class_mp4: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    Fakes(monkeypatch, {0: 20})
    calls: list[int] = []

    def track(clip: Path, work: Path, **kw: Any) -> tuple[Any, Path]:
        calls.append(kw["fps"])
        path = Path(work) / "part2_track" / "tracks.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        if kw["fps"] == 3:
            path.write_text(json.dumps(_ranges({0: (0, 20), 1: (0, 4), 2: (6, 10)})), encoding="utf-8")
            _frames_json(path.parent, 3)
            return (_step(2), path)
        return (_step(2, code=1), path)  # the repeat fails

    monkeypatch.setattr(p2_pose, "track", track)
    job = _post(api, class_mp4, mode="single")
    assert calls == [3, 10]
    assert job["status"] == "done" and job["result"]["people"][0]["id"] == "0"
    work = api.app.queue.job_dir(job["id"]) / "work"
    assert json.loads((work / "track_fps.json").read_text(encoding="utf-8"))["fps"] == 3
    times = json.loads((work / "frames.json").read_text(encoding="utf-8"))["frames"]
    assert times[1]["t_ms"] == 333  # the 3 fps times, restored
    assert "ANOMALY people_retry_failed" in _log(api, job)


def test_the_repeat_starts_without_the_3_fps_frame_times(
    api: Api, class_mp4: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    Fakes(monkeypatch, {0: 20})
    seen: list[bool] = []

    def track(clip: Path, work: Path, **kw: Any) -> tuple[Any, Path]:
        seen.append((Path(work).parent / "frames.json").is_file() if kw["fps"] == 10 else False)
        path = Path(work) / "part2_track" / "tracks.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(tracks_doc({0: 20}) if kw["fps"] == 3 else _moving({0: 20})), encoding="utf-8")
        if kw["fps"] == 3:
            _frames_json(path.parent, 3)  # the repeat writes no frames.json at all
        return (_step(2), path)

    monkeypatch.setattr(p2_pose, "track", track)
    job = _post(api, class_mp4, mode="single")
    assert seen == [False, False]  # at the repeat the top-level 3 fps frames.json was already moved aside
    work = api.app.queue.job_dir(job["id"]) / "work"
    assert not (work / "frames.json").exists() and not (work / "frames.lowrate.json").exists()
