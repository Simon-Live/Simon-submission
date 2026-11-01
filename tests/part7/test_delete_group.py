"""Delete a group take (TICKET-106 B1, R3, R7): the group job, the raw upload, the people job (cut video, tracks, face
crops) and the board entries all go; a source still used by a queued or running job stays; a take whose export is
being made is refused. Spec: docs/specs/delete-take.md."""

from __future__ import annotations

from pathlib import Path

import pytest

from part7 import delete_routes, export_routes
from support import Api
from test_delete_take import UPLOAD, _delete, _error, _take
from test_people import VISITOR, Fakes, _group_body, _people_job, class_mp4  # noqa: F401


@pytest.fixture(autouse=True)
def _clean_export_state() -> object:
    export_routes._STATE.clear()
    yield
    export_routes._STATE.clear()


def test_a_group_take_records_its_people_job_and_upload(api: Api, class_mp4: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    Fakes(monkeypatch, {0: 20, 1: 20, 2: 20, 3: 20})
    people = _people_job(api, class_mp4)
    assert len(people["upload_id"]) == 16
    status, doc = api.json("POST", "api/group", _group_body(api, people["id"]), VISITOR)
    assert status == 202, doc
    job = api.app.queue.wait(doc["job"], 90)
    assert job["people_job"] == people["id"] and job["upload_id"] == people["upload_id"]


def test_deleting_a_group_take_removes_every_artefact(api: Api, class_mp4: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    Fakes(monkeypatch, {0: 20, 1: 20, 2: 20, 3: 20})
    people = _people_job(api, class_mp4)
    status, doc = api.json("POST", "api/group", _group_body(api, people["id"]), VISITOR)
    assert status == 202, doc
    group = api.app.queue.wait(doc["job"], 90)
    folders = [api.app.queue.job_dir(group["id"]), api.app.queue.job_dir(people["id"]), api.app.uploads / people["upload_id"]]
    assert all(f.is_dir() for f in folders)
    assert (api.app.queue.job_dir(people["id"]) / "work" / "clip.mp4").is_file()
    status, body = _delete(api, group["id"])
    assert status == 200 and body["removed"][:3] == ["job", "upload", "people"]
    assert not any(f.exists() for f in folders)
    assert api.json("GET", f"api/jobs/{group['id']}")[0] == 404
    assert api.json("GET", f"api/jobs/{people['id']}")[0] == 404
    assert api.json("GET", f"api/results/{group['id']}/0/analysis.json")[0] == 404


def _people_and_group(api: Api) -> None:
    upload = api.app.uploads / UPLOAD
    upload.mkdir(parents=True)
    (upload / "upload.mp4").write_bytes(b"raw")
    work = api.app.queue.job_dir("bbbbbbbbbbbb") / "work"
    work.mkdir(parents=True)
    api.app.queue._jobs["bbbbbbbbbbbb"] = {"id": "bbbbbbbbbbbb", "kind": "people", "status": "done", "stages": [], "note": None}
    _take(api, upload_id=UPLOAD, people_job="bbbbbbbbbbbb")


def test_a_source_still_used_by_a_running_job_is_kept_and_named(api: Api) -> None:
    _people_and_group(api)
    api.app.queue._jobs["cccccccccccc"] = {"id": "cccccccccccc", "kind": "follow", "status": "running", "stages": [],
                                           "note": None, "upload_id": UPLOAD, "people_job": "bbbbbbbbbbbb"}
    status, body = _delete(api, "aaaaaaaaaaaa")
    assert status == 200 and body["removed"] == ["job"] and body["kept"] == ["upload", "people"]
    assert (api.app.uploads / UPLOAD).is_dir() and api.app.queue.job_dir("bbbbbbbbbbbb").is_dir()
    assert api.app.queue.get("bbbbbbbbbbbb") is not None


def _finished_sibling(api: Api) -> None:
    api.app.queue._jobs["cccccccccccc"] = {"id": "cccccccccccc", "kind": "follow", "status": "done", "stages": [],
                                           "note": None, "upload_id": UPLOAD, "people_job": "bbbbbbbbbbbb"}


def test_a_source_used_by_a_finished_job_is_kept_and_named(api: Api) -> None:
    _people_and_group(api)
    api.app.queue._jobs["aaaaaaaaaaaa"]["kind"] = "follow"
    _finished_sibling(api)
    status, body = _delete(api, "aaaaaaaaaaaa")
    assert status == 200 and body["removed"] == ["job"] and body["kept"] == ["upload", "people"]
    assert (api.app.uploads / UPLOAD).is_dir() and api.app.queue.get("bbbbbbbbbbbb") is not None


def test_the_group_take_that_owns_the_sources_removes_them_despite_a_finished_group_sibling(api: Api) -> None:
    _people_and_group(api)
    api.app.queue._jobs["aaaaaaaaaaaa"]["kind"] = "group"
    _finished_sibling(api)
    api.app.queue._jobs["cccccccccccc"]["kind"] = "group"
    assert _delete(api, "aaaaaaaaaaaa")[1]["removed"] == ["job", "upload", "people"]


def test_a_take_with_an_export_being_made_is_refused_until_it_finishes(api: Api) -> None:
    folder = _take(api)
    export_routes._STATE["aaaaaaaaaaaa"] = {"state": "rendering"}
    assert _error(api, "aaaaaaaaaaaa") == (409, delete_routes.MSG_EXPORTING)
    assert folder.is_dir()
    export_routes._STATE["aaaaaaaaaaaa"] = {"state": "queued"}
    assert _delete(api, "aaaaaaaaaaaa")[0] == 409
    export_routes._STATE["aaaaaaaaaaaa"] = {"state": "ready"}
    assert _delete(api, "aaaaaaaaaaaa")[0] == 200 and not folder.exists()


def test_a_take_whose_spoken_cue_is_being_made_is_refused(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    from part7 import speech

    folder = _take(api)
    wav = folder / "speech" / "0-eng-abc.wav"
    monkeypatch.setattr(speech, "_ACTIVE", {wav})
    assert _error(api, "aaaaaaaaaaaa") == (409, delete_routes.MSG_SPEAKING)
    assert folder.is_dir()
    speech._ACTIVE.clear()
    assert _delete(api, "aaaaaaaaaaaa")[0] == 200


@pytest.mark.parametrize("other", ["follow", "trainer"])
def test_the_group_owner_exception_does_not_hide_a_finished_follow_or_trainer_take(api: Api, other: str) -> None:
    """TICKET-109: only another group take is ignored; a follow or trainer take from the same people job keeps it."""
    _people_and_group(api)
    api.app.queue._jobs["aaaaaaaaaaaa"]["kind"] = "group"
    _finished_sibling(api)
    api.app.queue._jobs["cccccccccccc"]["kind"] = other
    assert _delete(api, "aaaaaaaaaaaa")[1]["kept"] == ["upload", "people"]


def test_a_sweep_forgets_expired_jobs_so_delete_does_not_keep_sources_for_them(api: Api) -> None:
    import os
    import time
    _people_and_group(api)
    api.app.queue._jobs["aaaaaaaaaaaa"]["kind"] = "follow"
    _finished_sibling(api)
    folder = api.app.queue.job_dir("cccccccccccc")
    folder.mkdir(parents=True)
    record = folder / "job.json"
    record.write_text("{}")
    old = time.time() - 30 * 86400
    os.utime(record, (old, old))
    assert api.app.queue.cleanup() == 1 and api.app.queue.get("cccccccccccc") is None
    assert _delete(api, "aaaaaaaaaaaa")[1]["removed"] == ["job", "upload", "people"]


def test_the_job_sweep_also_sweeps_old_uploads(api: Api) -> None:
    import os
    import time
    old = api.app.uploads / "0123456789abcdef"
    old.mkdir(parents=True)
    stamp = time.time() - 30 * 86400
    os.utime(old, (stamp, stamp))
    api.app.queue.cleanup()
    assert not old.exists()
