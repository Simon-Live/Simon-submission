"""TICKET-198: the take's "Just me" / "Group" choice sets the people-tracking rate (moalborati/simon#62)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from part7 import people
from part7.parts import p2_pose
from support import Api, load_scaled
from test_people import VISITOR, Fakes, _people_job, _step, class_mp4, tracks_doc  # noqa: F401 (class_mp4 is a fixture)

ENVS = (p2_pose.TRACK_FPS_ENV, p2_pose.TRACK_FPS_SINGLE_ENV, p2_pose.TRACK_FPS_GROUP_ENV)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ENVS:
        monkeypatch.delenv(name, raising=False)


# ----- mode -> fps -------------------------------------------------------------------------------------------
@pytest.mark.parametrize("mode, want", [("single", (3, "single")), ("group", (3, "group")), (None, (3, "group")),
                                        ("nonsense", (3, "group"))])
def test_defaults_by_mode_and_a_missing_mode_is_group(mode: str | None, want: tuple[int, str]) -> None:
    assert p2_pose.track_fps_for(mode) == want


def test_env_sets_each_rate_and_the_old_variable_overrides_both(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(p2_pose.TRACK_FPS_SINGLE_ENV, "4")
    monkeypatch.setenv(p2_pose.TRACK_FPS_GROUP_ENV, "8")
    assert p2_pose.track_fps_for("single") == (4, "single") and p2_pose.track_fps_for("group") == (8, "group")
    monkeypatch.setenv(p2_pose.TRACK_FPS_ENV, "5")
    assert p2_pose.track_fps_for("single") == (5, "single") and p2_pose.track_fps_for("group") == (5, "group")


@pytest.mark.parametrize("bad", ["0", "-2", "x", "2.5", " "])
def test_bad_env_values_fall_back_to_the_defaults(monkeypatch: pytest.MonkeyPatch, bad: str) -> None:
    monkeypatch.setenv(p2_pose.TRACK_FPS_SINGLE_ENV, bad)
    monkeypatch.setenv(p2_pose.TRACK_FPS_GROUP_ENV, bad)
    assert p2_pose.track_fps_for("single")[0] == 3 and p2_pose.track_fps_for("group")[0] == 3


# ----- the people job ----------------------------------------------------------------------------------------
def _log(api: Api, job: dict[str, Any]) -> str:
    return (api.app.queue.job_dir(job["id"]) / "steps" / "part7.log").read_text(encoding="utf-8")


def _post(api: Api, mp4: Path, **extra: Any) -> dict[str, Any]:
    _, up = api.upload(mp4)
    status, doc = api.json("POST", "api/people", {"upload_id": up["upload_id"], **extra}, VISITOR)
    assert status == 202, doc
    job = api.app.queue.wait(doc["job"], load_scaled(60))
    assert job and job["status"] == "done", job
    return job


def _moving(counts: dict[int, int]) -> dict[str, Any]:
    doc = tracks_doc(counts)
    for f in doc["frames"]:
        for p in f["people"]:
            p["bbox"][0] += f["frame"] * 8  # a box that travels: motion well over MIN_MOTION
    return doc


def _fake_track(fakes: Fakes, mp: pytest.MonkeyPatch, by_fps: dict[int, dict[str, Any]]) -> None:
    def track(clip: Path, work: Path, **kw: Any) -> tuple[Any, Path]:
        fakes.track_fps.append(kw.get("fps"))
        path = Path(work) / "part2_track" / "tracks.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(by_fps[kw["fps"]]), encoding="utf-8")
        return (_step(2), path)

    mp.setattr(p2_pose, "track", track)


@pytest.mark.parametrize("body, fps, kind", [({"mode": "single"}, 3, "single"), ({"mode": "group"}, 3, "group"),
                                             ({}, 3, "group"), ({"mode": "bogus"}, 3, "group")])
def test_the_people_job_passes_the_mode_rate_to_part2_and_logs_it(
    api: Api, class_mp4: Path, monkeypatch: pytest.MonkeyPatch, body: dict[str, Any], fps: int, kind: str
) -> None:
    fakes = Fakes(monkeypatch, {0: 20})
    _fake_track(fakes, monkeypatch, {fps: _moving({0: 20})})
    job = _post(api, class_mp4, **body)
    assert fakes.track_fps == [fps]  # a moving person at the first rate: no repeat
    assert f"people tracking at {fps} fps ({kind})" in _log(api, job)
    work = api.app.queue.job_dir(job["id"]) / "work"
    assert json.loads((work / "track_fps.json").read_text(encoding="utf-8")) == {"fps": fps, "mode": kind}


def test_the_old_variable_overrides_the_mode_in_the_job(api: Api, class_mp4: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(p2_pose.TRACK_FPS_ENV, "6")
    fakes = Fakes(monkeypatch, {0: 20})
    _fake_track(fakes, monkeypatch, {6: _moving({0: 20})})
    job = _post(api, class_mp4, mode="single")
    assert fakes.track_fps == [6] and "people tracking at 6 fps (single)" in _log(api, job)


def test_a_single_take_with_nobody_there_long_enough_repeats_once_at_10_fps(
    api: Api, class_mp4: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fakes = Fakes(monkeypatch, {0: 20})
    _fake_track(fakes, monkeypatch, {3: tracks_doc({0: 5}), 10: _moving({0: 20})})  # 5 frames at 3 fps is 1.67 s
    job = _post(api, class_mp4, mode="single")
    assert fakes.track_fps == [3, 10]
    text = _log(api, job)
    assert "no participant at 3 fps (present 2.0 s and moving): tracking again at 10 fps (single)" in text
    work = api.app.queue.job_dir(job["id"]) / "work"
    assert json.loads((work / "track_fps.json").read_text(encoding="utf-8"))["fps"] == 10
    assert [p["id"] for p in job["result"]["people"]] == ["0"]


def test_the_repeat_happens_once_even_when_the_10_fps_run_finds_nobody_moving(
    api: Api, class_mp4: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fakes = Fakes(monkeypatch, {0: 20})
    _fake_track(fakes, monkeypatch, {3: tracks_doc({0: 5}), 10: tracks_doc({0: 20})})
    _post(api, class_mp4, mode="single")
    assert fakes.track_fps == [3, 10]


@pytest.mark.parametrize("mode", ["single", "group"])
def test_someone_there_all_clip_who_barely_moves_is_tracked_once_and_offered(
    api: Api, class_mp4: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    """Prod job 4577688732c2 paid for two Modal runs that found the same still person."""
    fakes = Fakes(monkeypatch, {0: 20})
    _fake_track(fakes, monkeypatch, {3: tracks_doc({0: 20})})  # 6.67 s at 3 fps, a still box
    job = _post(api, class_mp4, mode=mode)
    assert fakes.track_fps == [3] and "tracking again" not in _log(api, job)
    assert [p["id"] for p in job["result"]["people"]] == ["0"]


def test_a_group_take_with_no_participant_repeats_once_at_10_fps(
    api: Api, class_mp4: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fakes = Fakes(monkeypatch, {0: 20})
    _fake_track(fakes, monkeypatch, {3: tracks_doc({0: 5}), 10: _moving({0: 20})})
    job = _post(api, class_mp4, mode="group")
    assert fakes.track_fps == [3, 10] and "(group)" in _log(api, job)


def test_an_operator_can_return_group_to_10_fps(api: Api, class_mp4: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(p2_pose.TRACK_FPS_GROUP_ENV, "10")
    fakes = Fakes(monkeypatch, {0: 20})
    _fake_track(fakes, monkeypatch, {10: _moving({0: 20})})
    _post(api, class_mp4, mode="group")
    assert fakes.track_fps == [10]


def test_a_track_present_under_2_seconds_is_a_passer_by_and_not_offered(
    api: Api, class_mp4: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fakes = Fakes(monkeypatch, {0: 20, 1: 5})
    _fake_track(fakes, monkeypatch, {3: _moving({0: 20, 1: 5})})  # 5 frames at 3 fps is 1.67 s
    job = _post(api, class_mp4, mode="group")
    assert fakes.track_fps == [3]  # a participant was found: no repeat
    assert [p["id"] for p in job["result"]["people"]] == ["0"]
    assert "passer-by, not offered" in _log(api, job) and "tracks 1" in _log(api, job)
    work = api.app.queue.job_dir(job["id"]) / "work"
    assert {str(p["id"]) for f in json.loads((work / "tracks.json").read_text(encoding="utf-8"))["frames"]
            for p in f["people"]} == {"0", "1"}  # the passer-by stays in tracks.json


def test_the_minimum_presence_is_an_env_setting(api: Api, class_mp4: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIMON7_PEOPLE_MIN_PRESENT_S", "1.0")
    fakes = Fakes(monkeypatch, {0: 20, 1: 5})
    _fake_track(fakes, monkeypatch, {3: _moving({0: 20, 1: 5})})
    job = _post(api, class_mp4, mode="group")
    assert [p["id"] for p in job["result"]["people"]] == ["0", "1"]


def test_a_single_take_tracked_at_3_fps_gives_the_3d_run_boxes_at_the_3d_rate(
    api: Api, class_mp4: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fakes = Fakes(monkeypatch, {0: 20, 1: 18})
    _fake_track(fakes, monkeypatch, {3: _moving({0: 20, 1: 18})})
    monkeypatch.setattr(p2_pose, "FPS", 10)
    monkeypatch.setattr(p2_pose, "frame_times", lambda *a, **k: None)  # TICKET-349: no real `part2 frame-times` launch
    pj = _post(api, class_mp4, mode="single")["id"]
    _, up = api.upload(class_mp4)
    status, doc = api.json("POST", "api/follow", {"upload_id": up["upload_id"], "entry_id": "lateral-raise",
                                                  "people_job": pj, "person_id": "1"}, VISITOR)
    assert status == 202, doc
    job = api.app.queue.wait(doc["job"], load_scaled(60))
    assert job and job["status"] == "done", job
    assert "people tracks at 3 fps resampled to 10 fps for the 3D run" in _log(api, job)


@pytest.mark.parametrize("barred, noted", [(True, False), (False, True)])
def test_the_open_tracker_is_only_called_a_fallback_where_another_is_allowed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, barred: bool, noted: bool
) -> None:
    monkeypatch.setattr(people.licence_gates, "meta_barred", lambda: barred)
    tracks = tmp_path / "tracks.json"
    tracks.write_text(json.dumps({"frames": [], "provenance": {"tracker": "local-open"}}), encoding="utf-8")
    notes: list[str] = []
    people._note_tracker(SimpleNamespace(add_note=notes.append), tracks)
    assert bool(notes) is noted
