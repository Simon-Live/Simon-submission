"""TICKET-064 item 1: trainer and follower take the same clip, people, trim and 3D path (people.md "One clip path").

The only difference is Part 1, which only the trainer runs: it sees a copy cropped to the chosen person.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from part7 import media, people
from support import Api, part1_reads, recorder_webm
from test_people import VISITOR, Fakes, _people_job, class_mp4  # noqa: F401 (class_mp4 is a fixture)


def _start(api: Api, route: str, body: dict[str, Any]) -> dict[str, Any]:
    status, doc = api.json("POST", route, body, VISITOR)
    assert status == 202, doc
    job = api.app.queue.wait(doc["job"], 60)
    assert job is not None and job["status"] == "done", job
    return job


def _video(api: Api, job: dict[str, Any]) -> bytes:
    return (api.app.queue.job_dir(job["id"]) / "work" / "video.mp4").read_bytes()


def _log(api: Api, job: dict[str, Any]) -> str:
    return (api.app.queue.job_dir(job["id"]) / "steps" / "part7.log").read_text(encoding="utf-8")


def test_trainer_and_follow_with_a_person_share_the_clip_the_tracks_and_the_3d_call(
    api: Api, class_mp4: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fakes = Fakes(monkeypatch, {0: 20, 1: 18})
    pj = _people_job(api, class_mp4)["id"]
    _, up = api.upload(class_mp4)
    trainer = _start(api, "api/trainer", {"upload_id": up["upload_id"], "name": "Warm-up", "category": "exercise",
                                          "people_job": pj, "person_id": "1"})
    trainer_p2 = fakes.p2_calls[-1]
    follow = _start(api, "api/follow", {"upload_id": up["upload_id"], "entry_id": "lateral-raise",
                                        "people_job": pj, "person_id": "1"})
    clip = (api.app.queue.job_dir(pj) / "work" / "clip.mp4").read_bytes()
    assert _video(api, trainer) == clip == _video(api, follow)  # one trimmed clip, made once by the people job
    follow_p2 = fakes.p2_calls[-1]
    assert trainer_p2["ids"] == follow_p2["ids"] == ["1"]  # same Part 2 call: ids, and the people job's tracks...
    assert Path(trainer_p2["tracks"]).name == Path(follow_p2["tracks"]).name == "tracks_10fps.json"  # ...at the 3D rate
    assert Path(trainer_p2["tracks"]).read_bytes() == Path(follow_p2["tracks"]).read_bytes()
    assert str(api.app.queue.job_dir(pj)) not in trainer_p2["tracks"]  # each job's copy, the people job's file untouched
    assert [p for _, p in fakes.p3_people[-2:]] == ["1", "1"]  # same person for Part 3
    assert fakes.p1_videos[-1].name == "person.mp4" and len(fakes.p1_videos) == 1  # Part 1: trainer only, cropped
    for job in (trainer, follow):
        text = _log(api, job)
        assert f"clip reused from people job {pj}" in text and "stage pose start:" in text and "person=1 ids=1" in text
        assert "done in " in text
    assert "Part 1 input cropped to person 1: box x=" in _log(api, trainer)


def test_without_a_people_job_trainer_and_follow_both_cut_through_prepare_clip(
    api: Api, class_mp4: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    Fakes(monkeypatch, {0: 20})
    seen: list[tuple[str, Any]] = []
    real = people.prepare_clip

    def spy(ctx: Any, raw: Path, trim: Any, name: str = "clip.mp4") -> Path:
        seen.append((name, trim))
        return real(ctx, raw, trim, name)

    monkeypatch.setattr(people, "prepare_clip", spy)
    _, up = api.upload(class_mp4)
    trim = {"start_ms": 500, "end_ms": 3000}
    trainer = _start(api, "api/trainer", {"upload_id": up["upload_id"], "name": "x", "category": "dance", "trim": trim})
    follow = _start(api, "api/follow", {"upload_id": up["upload_id"], "entry_id": "lateral-raise", "trim": trim})
    assert seen == [("video.mp4", trim), ("video.mp4", trim)]
    assert _video(api, trainer) == _video(api, follow)
    assert abs(follow["trimmed_duration_ms"] - 2500) <= 250


def test_a_recorder_webm_reaches_part1_as_a_readable_constant_rate_crop(
    api: Api, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The staging failure (Part 1 'could not read video metadata' on a recorded take), end to end."""
    fakes = Fakes(monkeypatch, {0: 20})
    webm = recorder_webm(tmp_path / "take.webm", 3.0)
    status, up = api.upload(webm, "video/webm")
    assert status == 201
    status, doc = api.json("POST", "api/people", {"upload_id": up["upload_id"]}, VISITOR)
    assert status == 202
    pj = api.app.queue.wait(doc["job"], 60)
    assert pj and pj["status"] == "done" and pj["result"]["auto_id"] == "0"
    _start(api, "api/trainer", {"upload_id": up["upload_id"], "name": "Take", "category": "dance", "people_job": pj["id"]})
    crop = fakes.p1_videos[-1]
    assert crop.name == "person.mp4" and part1_reads(crop)
    assert media.probe(crop)["fps"] == 30.0 and media._count_packets(crop) <= 31 * 3.2
    assert "30 fps (counted)" in (api.app.queue.job_dir(pj["id"]) / "steps" / "part7.log").read_text(encoding="utf-8")
