"""TICKET-309: a valid video is never refused because the trim editor sent its 0 to 0 ms placeholder.

On staging (2026-11-02T05:11:08Z and 14:31:48Z) the browser sent `trim {start_ms: 0, end_ms: 0}` because Continue was
pressed before it had read the clip's length; the server answered 400 MSG_TRIM_ORDER and the page said "not a video".
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from part7 import chain, media, server
from support import Api, ffmpeg_video, load_scaled
from test_people import VISITOR, Fakes
from test_server import _fake_follower, _fake_trainer, _upload

UNSET = {"start_ms": 0, "end_ms": 0}


@pytest.fixture(scope="module")
def clip_mp4(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return ffmpeg_video(tmp_path_factory.mktemp("unset") / "clip.mp4", 12)


def _whole_clip(status: int, doc: Any) -> None:
    assert status == 202, doc
    assert doc["trim"] is None and 11000 <= doc["duration_ms"] <= 12000


def test_people_job_takes_the_unset_trim_as_the_whole_clip(api: Api, clip_mp4: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    Fakes(monkeypatch, {0: 20})
    status, doc = api.json("POST", "api/people", {"upload_id": _upload(api, clip_mp4), "trim": UNSET}, VISITOR)
    assert status == 202, doc
    assert api.app.queue.wait(doc["job"], load_scaled(60))["status"] == "done"
    clip = media.probe(api.app.queue.job_dir(doc["job"]) / "work" / "clip.mp4")
    assert 11000 <= clip["duration_ms"] <= 12200, clip


def test_trainer_and_follow_take_the_unset_trim_as_the_whole_clip(
    api: Api, clip_mp4: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(chain, "trainer", _fake_trainer())
    monkeypatch.setattr(chain, "follower", _fake_follower())
    upload_id = _upload(api, clip_mp4)
    _whole_clip(*api.json("POST", "api/trainer", {"upload_id": upload_id, "name": "Squat", "category": "exercise",
                                                  "trim": UNSET}))
    _whole_clip(*api.json("POST", "api/follow", {"upload_id": upload_id, "entry_id": "lateral-raise", "trim": UNSET}))


def test_the_unset_trim_on_a_clip_over_60_seconds_still_needs_a_trim(api: Api, tmp_path: Path) -> None:
    upload_id = _upload(api, ffmpeg_video(tmp_path / "v70.mp4", 70))
    status, doc = api.json("POST", "api/people", {"upload_id": upload_id, "trim": UNSET}, VISITOR)
    assert status == 413 and doc["error"] == server.MSG_TOO_LONG


@pytest.mark.parametrize("trim,message", [
    ({"start_ms": False, "end_ms": False}, server.MSG_TRIM_SHAPE),
    ({"start_ms": 0, "end_ms": 0, "x": 1}, server.MSG_TRIM_ORDER),
    ({"start_ms": 3000, "end_ms": 3000}, server.MSG_TRIM_ORDER),
])
def test_other_empty_selections_are_still_refused(api: Api, clip_mp4: Path, trim: Any, message: str) -> None:
    status, doc = api.json("POST", "api/people", {"upload_id": _upload(api, clip_mp4), "trim": trim}, VISITOR)
    assert status == 400 and doc["error"] == message
    assert api.app.queue.counts() == {"running": 0, "waiting": 0}


def test_a_real_non_video_is_still_refused_as_not_a_video(api: Api, tmp_path: Path) -> None:
    fake = tmp_path / "notes.mp4"
    fake.write_bytes(b"these are notes, not frames\n" * 64)
    status, doc = api.upload(fake)
    assert status == 400 and doc["error"] == server.MSG_NOT_VIDEO
