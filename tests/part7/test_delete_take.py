"""Delete this take (TICKET-159): the route removes the clip, the tracks, the analysis, the raw upload, the people job
and the board entries of a take; it refuses a running job and unknown ids; a follow records `upload_id` and `lang`."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from part7 import challenges, delete_routes
from support import Api
from test_challenges import _add, _create, _job
from test_practice import _follow

UPLOAD = "0123456789abcdef"


def _take(api: Api, job_id: str = "aaaaaaaaaaaa", **record: Any) -> Path:
    """A finished follow job with a clip, tracks and an analysis on disk; returns its folder."""
    _job(api, job_id, **record)
    work = api.app.queue.job_dir(job_id) / "work"
    (work / "video.mp4").write_bytes(b"clip")
    (work / "follower" / "tracks.json").write_text("{}", encoding="utf-8")
    (api.app.queue.job_dir(job_id) / "job.json").write_text(json.dumps({"id": job_id}), encoding="utf-8")
    return api.app.queue.job_dir(job_id)


def _delete(api: Api, job_id: str) -> tuple[int, Any]:
    return api.json("POST", f"api/jobs/{job_id}/delete", {})


def _error(api: Api, job_id: str) -> tuple[int, str]:
    status, body = _delete(api, job_id)
    return status, body["error"]


def test_delete_removes_clip_tracks_and_analysis(api: Api) -> None:
    folder = _take(api)
    assert (folder / "work" / "video.mp4").is_file() and (folder / "work" / "follower" / "analysis.json").is_file()
    status, body = _delete(api, "aaaaaaaaaaaa")
    assert status == 200 and body == {"deleted": True, "removed": ["job"]}
    assert not folder.exists()
    assert api.json("GET", "api/jobs/aaaaaaaaaaaa")[0] == 404  # the record is gone
    assert api.json("GET", "api/results/aaaaaaaaaaaa/analysis.json")[0] == 404
    assert api.request("GET", "api/results/aaaaaaaaaaaa/video.mp4")[0] == 404


def test_delete_drops_the_raw_upload_the_people_job_and_the_board_entry(api: Api) -> None:
    upload = api.app.uploads / UPLOAD
    upload.mkdir(parents=True)
    (upload / "upload.mp4").write_bytes(b"raw")
    people = api.app.queue.job_dir("bbbbbbbbbbbb") / "work"
    people.mkdir(parents=True)
    (people / "clip.mp4").write_bytes(b"cut")
    api.app.queue._jobs["bbbbbbbbbbbb"] = {"id": "bbbbbbbbbbbb", "kind": "people", "status": "done", "stages": [], "note": None}
    _take(api, upload_id=UPLOAD, people_job="bbbbbbbbbbbb")
    made = _create(api)
    assert _add(api, made["id"], job_id="aaaaaaaaaaaa", name="Sam")[0] == 201
    status, body = _delete(api, "aaaaaaaaaaaa")
    assert status == 200 and body["removed"] == ["job", "upload", "people", "board"]
    assert not upload.exists() and not people.exists()
    assert challenges.get(api.app.state, made["id"])["entries"] == []


def test_delete_forgets_the_idempotency_answers_that_name_the_take(api: Api) -> None:
    """Offline takes retry with a key; after a delete that retry must not get the id of a take that is gone."""
    _take(api)
    store = api.app.idempotency
    store.put("follow", "11111111-1111-4111-8111-111111111111", 202, {"id": "aaaaaaaaaaaa", "status": "queued"})
    store.put("follow", "22222222-2222-4222-8222-222222222222", 202, {"id": "bbbbbbbbbbbb", "status": "queued"})
    assert _delete(api, "aaaaaaaaaaaa")[0] == 200
    assert store.get("follow", "11111111-1111-4111-8111-111111111111") is None
    assert store.get("follow", "22222222-2222-4222-8222-222222222222") is not None


def test_delete_leaves_another_take_alone(api: Api) -> None:
    keep = _take(api, "cccccccccccc")
    _take(api, "aaaaaaaaaaaa")
    assert _delete(api, "aaaaaaaaaaaa")[0] == 200
    assert (keep / "work" / "video.mp4").is_file() and api.json("GET", "api/jobs/cccccccccccc")[0] == 200


def test_delete_refuses_unknown_running_and_non_take_jobs(api: Api) -> None:
    assert _error(api, "dddddddddddd") == (404, delete_routes.MSG_NO_JOB)
    assert _delete(api, "not-a-job-id!")[0] == 404
    _take(api, "eeeeeeeeeeee")
    api.app.queue._jobs["eeeeeeeeeeee"]["status"] = "running"
    assert _error(api, "eeeeeeeeeeee") == (409, delete_routes.MSG_BUSY)
    assert api.app.queue.job_dir("eeeeeeeeeeee").exists()  # a running job keeps its folder
    api.app.queue._jobs["ffffffffffff"] = {"id": "ffffffffffff", "kind": "people", "status": "done", "stages": [], "note": None}
    assert _error(api, "ffffffffffff") == (400, delete_routes.MSG_NOT_TAKE)


def test_delete_needs_post_and_deleting_twice_is_a_404(api: Api) -> None:
    _take(api)
    assert api.json("GET", "api/jobs/aaaaaaaaaaaa/delete")[0] == 405
    assert api.app.queue.job_dir("aaaaaaaaaaaa").exists()
    assert _delete(api, "aaaaaaaaaaaa")[0] == 200
    assert _delete(api, "aaaaaaaaaaaa")[0] == 404


def test_a_follow_keeps_its_upload_id_and_language(api: Api, tiny_mp4: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    status, doc = _follow(api, tiny_mp4, monkeypatch, lang="es")
    assert status == 202, doc
    job = api.app.queue.get(doc["job"])
    assert job["lang"] == "es" and len(job["upload_id"]) == 16
    status, doc = _follow(api, tiny_mp4, monkeypatch, lang="not a language!")
    second = api.app.queue.get(doc["job"])
    assert status == 202 and "lang" not in second  # an invalid code is dropped, not trusted
    assert (api.app.uploads / second["upload_id"]).is_dir()
    assert _delete(api, doc["job"])[1]["removed"][:2] == ["job", "upload"]
    assert not (api.app.uploads / second["upload_id"]).exists()


# ----- trainer takes (TICKET-111) ---------------------------------------------------------------------
ENTRY = "knee-raise-0a1b2c3d"


def _trainer(api: Api, job_id: str = "1a2b3c4d5e6f", files_source: str = "import", **record: Any) -> tuple[Path, Path]:
    """A finished trainer job (folder with meshes, raw upload) and the catalog entry it made; returns both folders."""
    folder = api.app.queue.job_dir(job_id)
    mesh = folder / "work" / "trainer" / "part2"
    mesh.mkdir(parents=True)
    (mesh / "mesh3d.json").write_text("{}", encoding="utf-8")
    (mesh / "mesh3d.bin").write_bytes(b"m")
    (folder / "job.json").write_text(json.dumps({"id": job_id}), encoding="utf-8")
    upload = api.app.uploads / UPLOAD
    upload.mkdir(parents=True, exist_ok=True)
    (upload / "upload.mp4").write_bytes(b"raw with sound")
    entry = api.app.child.catalog_dir / ENTRY
    entry.mkdir(parents=True)
    for name in ("video.mp4", "keyframes.json", "narration.json"):
        (entry / name).write_text("x", encoding="utf-8")
    (entry / "manifest.json").write_text(json.dumps({"id": ENTRY, "files_source": files_source}), encoding="utf-8")
    api.app.queue._jobs[job_id] = {"id": job_id, "kind": "trainer", "status": "done", "entry_id": ENTRY, "upload_id": UPLOAD,
                                   "stages": [], "note": None, **record}
    return folder, entry


def test_trainer_delete_removes_the_files_and_keeps_the_movement(api: Api) -> None:
    folder, entry = _trainer(api)
    status, body = _delete(api, "1a2b3c4d5e6f")
    assert status == 200 and body == {"deleted": True, "removed": ["job", "upload", "narration"]}
    assert not folder.exists() and not (api.app.uploads / UPLOAD).exists()  # recording, meshes, job record
    assert (entry / "video.mp4").is_file() and (entry / "keyframes.json").is_file() and (entry / "manifest.json").is_file()
    assert not (entry / "narration.json").exists(), "the transcripts made from the voice go"
    assert api.json("GET", "api/jobs/1a2b3c4d5e6f")[0] == 404


def test_trainer_delete_with_remove_entry_removes_the_movement_and_its_labels(api: Api) -> None:
    _, entry = _trainer(api)
    labels_file = api.app.state / "labels" / f"{ENTRY}.json"
    labels_file.parent.mkdir(parents=True)
    labels_file.write_text("{}", encoding="utf-8")
    status, body = api.json("POST", "api/jobs/1a2b3c4d5e6f/delete", {"remove_entry": True})
    assert status == 200 and body["removed"] == ["job", "upload", "entry"]
    assert not entry.exists() and not labels_file.exists()
    assert not (entry.parent / f".evict-{ENTRY}").exists()


def test_trainer_delete_keeps_a_shipped_sample_even_when_asked(api: Api) -> None:
    _, entry = _trainer(api, files_source="fixture")
    status, body = api.json("POST", "api/jobs/1a2b3c4d5e6f/delete", {"remove_entry": True})
    assert status == 200 and body["kept"] == ["entry"] and "entry" not in body["removed"]
    assert entry.is_dir() and not (entry / "narration.json").exists()


def test_trainer_delete_keeps_a_movement_a_challenge_uses(api: Api) -> None:
    _, entry = _trainer(api)
    api.app.child.entries[ENTRY] = {"id": ENTRY, "animation": "animation.json", "skeleton": "skeleton.json"}
    made = _create(api, entry_id=ENTRY)
    status, body = api.json("POST", "api/jobs/1a2b3c4d5e6f/delete", {"remove_entry": True})
    assert status == 200 and body["kept"] == ["entry"] and entry.is_dir()
    assert challenges.get(api.app.state, made["id"]) is not None


def test_trainer_delete_refuses_a_running_job_and_a_bad_body(api: Api) -> None:
    folder, entry = _trainer(api, status="running")
    assert _error(api, "1a2b3c4d5e6f") == (409, delete_routes.MSG_BUSY)
    api.app.queue._jobs["1a2b3c4d5e6f"]["status"] = "done"
    assert api.request("POST", "api/jobs/1a2b3c4d5e6f/delete", b"not json", {"Content-Type": "application/json"})[0] == 400
    assert folder.is_dir() and entry.is_dir(), "negative: nothing was deleted"


def test_trainer_delete_keeps_an_upload_another_job_still_uses(api: Api) -> None:
    folder, _ = _trainer(api)
    api.app.queue._jobs["9a8b7c6d5e4f"] = {"id": "9a8b7c6d5e4f", "kind": "follow", "status": "running", "upload_id": UPLOAD,
                                           "stages": [], "note": None}
    status, body = _delete(api, "1a2b3c4d5e6f")
    assert status == 200 and body["kept"] == ["upload"] and (api.app.uploads / UPLOAD).is_dir()
    assert not folder.exists()
