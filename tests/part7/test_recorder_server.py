"""TICKET-055: trim, the 90 s raw limit, the 60 s clip limit and trainer labels (recorder.md "Server")."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from part7 import chain, labels, media, server
from support import Api, ffmpeg_video
from test_server import _fake_follower, _fake_trainer, _upload

BODY = {"name": "Squat", "category": "exercise"}


@pytest.fixture(scope="module")
def clip_mp4(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return ffmpeg_video(tmp_path_factory.mktemp("rec") / "clip.mp4", 12)


def _trainer(api: Api, upload_id: str, **extra: Any) -> tuple[int, Any]:
    return api.json("POST", "api/trainer", {"upload_id": upload_id, **BODY, **extra})


def test_media_cut_is_within_one_frame(clip_mp4: Path, tmp_path: Path) -> None:
    out = media.trim(clip_mp4, tmp_path / "cut.mp4", 2300, 9400)
    meta = media.probe(out)
    assert abs(meta["duration_s"] - 7.1) <= 1 / meta["fps"] + 0.001 and meta["codec"] == "h264"


@pytest.mark.parametrize("trim,fragment", [
    ({"start_ms": 0}, "start and an end"),
    ({"start_ms": "0", "end_ms": 5000}, "start and an end"),
    ({"start_ms": True, "end_ms": 5000}, "start and an end"),
    ("all", "start and an end"),
    ({"start_ms": -1, "end_ms": 5000}, "before it ends"),
    ({"start_ms": 5000, "end_ms": 5000}, "before it ends"),
    ({"start_ms": 1000, "end_ms": 99000}, "before it ends"),
    ({"start_ms": 1000, "end_ms": 1999}, "too short"),
])
def test_bad_trim_is_400_in_plain_words(api: Api, clip_mp4: Path, trim: Any, fragment: str) -> None:
    upload_id = _upload(api, clip_mp4)
    status, doc = _trainer(api, upload_id, trim=trim)
    assert status == 400 and fragment in doc["error"]
    status, doc = api.json("POST", "api/follow", {"upload_id": upload_id, "entry_id": "lateral-raise", "trim": trim})
    assert status == 400 and fragment in doc["error"]
    assert api.app.queue.counts() == {"running": 0, "waiting": 0} and api.app.quota.gpu_jobs_today() == 0


def test_trim_over_60_seconds_is_400(api: Api, tmp_path: Path) -> None:
    upload_id = _upload(api, ffmpeg_video(tmp_path / "v70.mp4", 70))
    status, doc = _trainer(api, upload_id, trim={"start_ms": 0, "end_ms": 61000})
    assert status == 400 and doc["error"] == server.MSG_TRIM_LONG


def test_raw_between_60_and_90_seconds_is_accepted_but_needs_a_trim(api: Api, tmp_path: Path) -> None:
    upload_id = _upload(api, ffmpeg_video(tmp_path / "v70.mp4", 70))
    status, doc = _trainer(api, upload_id)
    assert status == 413 and doc["error"] == server.MSG_TOO_LONG
    status, doc = api.json("POST", "api/follow", {"upload_id": upload_id, "entry_id": "lateral-raise"})
    assert status == 413 and api.app.queue.counts() == {"running": 0, "waiting": 0}


def test_trainer_job_keeps_trim_and_cuts_the_video(api: Api, clip_mp4: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}
    inner = _fake_trainer()

    def spy(video: Path, work: Path, **kw: Any) -> dict[str, Any]:
        seen["duration_s"] = media.probe(video)["duration_s"]
        return inner(video, work, **kw)

    monkeypatch.setattr(chain, "trainer", spy)
    trim = {"start_ms": 2000, "end_ms": 8000}
    status, doc = _trainer(api, _upload(api, clip_mp4), trim=trim)
    assert status == 202 and doc["trim"] == trim and doc["duration_ms"] == 6000
    done = api.app.queue.wait(doc["job"], 60)
    assert done["status"] == "done" and done["result"]["trim"] == trim
    assert abs(seen["duration_s"] - 6.0) <= 0.2 + 0.001 and abs(done["trimmed_duration_ms"] - 6000) <= 200


def test_job_without_trim_records_none_and_whole_duration(api: Api, clip_mp4: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chain, "trainer", _fake_trainer())
    status, doc = _trainer(api, _upload(api, clip_mp4))
    assert status == 202 and doc["trim"] is None and 11000 <= doc["duration_ms"] <= 12000
    assert api.app.queue.wait(doc["job"], 60)["result"]["trim"] is None


def test_follow_job_honours_trim(api: Api, clip_mp4: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}
    inner = _fake_follower()

    def spy(video: Path, expected: Path, work: Path, **kw: Any) -> dict[str, Any]:
        seen["duration_s"] = media.probe(video)["duration_s"]
        return inner(video, expected, work, **kw)

    monkeypatch.setattr(chain, "follower", spy)
    trim = {"start_ms": 1000, "end_ms": 4000}
    status, doc = api.json("POST", "api/follow", {"upload_id": _upload(api, clip_mp4), "entry_id": "lateral-raise", "trim": trim})
    assert status == 202 and doc["trim"] == trim and doc["duration_ms"] == 3000
    done = api.app.queue.wait(doc["job"], 60)
    assert done["status"] == "done" and done["result"]["trim"] == trim and abs(seen["duration_s"] - 3.0) <= 0.2 + 0.001


@pytest.mark.parametrize("bad", [
    "tags", {"tags": "a"}, {"tags": ["Upper"]}, {"tags": ["a b"]}, {"tags": [""]}, {"tags": ["x" * 25]},
    {"tags": [f"t{i}" for i in range(9)]}, {"tags": [1]}, {"tags": [], "notes": "n" * 281}, {"notes": 5},
])
def test_bad_labels_are_400(api: Api, clip_mp4: Path, bad: Any) -> None:
    status, doc = _trainer(api, _upload(api, clip_mp4), labels=bad)
    assert status == 400 and doc["error"] and api.app.queue.counts() == {"running": 0, "waiting": 0}


def test_labels_round_trip(api: Api, clip_mp4: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chain, "trainer", _fake_trainer(entry_id="squat"))
    assert api.json("GET", "api/labels") == (200, {}) and api.json("GET", "api/labels/squat")[0] == 404
    given = {"tags": ["legs", "warm-up", "legs", "a1"], "notes": " Keep the back flat. "}
    status, doc = _trainer(api, _upload(api, clip_mp4), labels=given)
    assert status == 202
    assert api.app.queue.wait(doc["job"], 60)["status"] == "done"
    expect = {"tags": ["legs", "warm-up", "a1"], "notes": "Keep the back flat."}
    assert api.json("GET", "api/labels/squat") == (200, expect)
    assert api.json("GET", "api/labels") == (200, {"squat": expect})
    stored = json.loads((api.app.state / "labels" / "squat.json").read_text())
    assert stored["tags"] == expect["tags"] and stored["updated_at"].endswith("Z")
    assert api.json("GET", "api/labels/Bad_Id")[0] == 404


def test_failed_trainer_job_saves_no_labels(api: Api, clip_mp4: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chain, "trainer", _fake_trainer(ok=False))
    _, doc = _trainer(api, _upload(api, clip_mp4), labels={"tags": ["a"], "notes": ""})
    assert api.app.queue.wait(doc["job"], 60)["status"] == "failed"
    assert api.json("GET", "api/labels") == (200, {})


def test_labels_module_limits(tmp_path: Path) -> None:
    ok = labels.validate({"tags": [f"t{i}" for i in range(8)], "notes": "n" * 280})
    assert len(ok["tags"]) == 8 and len(ok["notes"]) == 280
    assert labels.validate({}) == {"tags": [], "notes": ""}
    with pytest.raises(labels.LabelsError):
        labels.save(tmp_path, "../evil", ok)
