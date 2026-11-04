"""A model-only take, "Use my 3D model instead of video" (docs/specs/model-only-take.md, AC-MO-1 to AC-MO-12)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from auth_support import authenv, get, post, sign_in, claim_doc  # noqa: F401
from export_seed import ENTRY as SEED_ENTRY, seed_takes
from history_support import FIRST, SECOND, USER, World, job_record, seed_job, world  # noqa: F401
from part7 import auth, chain, history_prompt, history_routes, history_store, jobs, model_only, processor, resume
from support import Api
from test_share import ENTRY as SHARE_ENTRY, make_job as share_job, share_body
from test_server import _fake_follower, _upload

MEDIA_SUFFIXES = tuple(model_only.MEDIA_SUFFIXES)


def media_in(folder: Path) -> list[str]:
    """Every file under `folder` that is a video or an image, relative to it (the test lists the folder, not a guess)."""
    return sorted(str(p.relative_to(folder)) for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in MEDIA_SUFFIXES)


def write(path: Path, data: bytes = b"x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def full_folder(root: Path) -> Path:
    """A job folder as the follow chain leaves it: every kind of derived media, and the 3D outputs and analysis."""
    work = root / "work"
    for name in ("video.mp4", "clip.mp4", "person.mp4", "expected_video.mp4", "annotated.mp4", "trim.webm", "thumb.jpg",
                 "keyframe_03.png", "follower/part2/frames/000001.jpg", "follower/part2/frames/000002.JPG",
                 "follower/annotated.mp4", "follower/keyframes/k1.webp", "people/0.jpg", "people/frame.jpg"):
        write(work / name if not name.startswith("people") else root / name)
    write(root / "export" / "export.mp4")
    for name in ("analysis.json", "replay.json", "follower.json", "part2/pose3d.json", "part2/mesh3d.json", "part2/body3d.json",
                 "part2/tracks.json", "part2/frames/frames.json"):
        write(work / "follower" / name, b"{}")
    write(work / "follower" / "part2" / "mesh3d.bin", b"\0\1")
    write(root / "steps" / "part7.log", b"log")
    write(root / "job.json", b"{}")
    return root


# ----- AC-MO-1: the delete step -----------------------------------------------------------------------
def test_purge_removes_every_video_and_image_and_keeps_the_3d_outputs(tmp_path: Path) -> None:  # AC-MO-1
    folder = full_folder(tmp_path / "job")
    assert len(media_in(folder)) >= 14
    removed = model_only.purge_job(folder)
    assert media_in(folder) == []  # the listing of the whole job folder: no video, no image
    assert len(removed) >= 14
    kept = sorted(str(p.relative_to(folder)) for p in folder.rglob("*") if p.is_file())
    for name in ("work/follower/analysis.json", "work/follower/replay.json", "work/follower/part2/pose3d.json",
                 "work/follower/part2/mesh3d.json", "work/follower/part2/mesh3d.bin", "work/follower/part2/body3d.json",
                 "work/follower/part2/tracks.json", "steps/part7.log", "job.json"):
        assert name in kept


def test_purge_does_not_follow_a_link_out_of_the_folder(tmp_path: Path) -> None:  # AC-MO-1
    outside = write(tmp_path / "outside" / "other.mp4")
    folder = full_folder(tmp_path / "job")
    (folder / "work" / "link.mp4").symlink_to(outside)
    (folder / "work" / "linked-dir").symlink_to(outside.parent, target_is_directory=True)
    model_only.purge_job(folder)
    assert outside.is_file()  # the target of a link is not touched
    assert not (folder / "work" / "link.mp4").is_symlink()


# ----- AC-MO-2, 3: the request, the job record and what the web reads -----------------------------------
def model_follow(api: Api, tiny_mp4: Path, monkeypatch: pytest.MonkeyPatch, **extra: Any) -> tuple[str, str]:
    """A follow with a fake chain that leaves media in the folder; returns (job id, upload id)."""
    inner = _fake_follower()

    def chain_with_media(video: Path, expected: Path, work: Path, report: Any = None, **kw: Any) -> dict[str, Any]:
        assert Path(video).is_file()  # the video is still there while the chain runs
        out = inner(video, expected, work, report, **kw)
        write(work / "part2" / "frames" / "000001.jpg")
        write(work / "annotated.mp4")
        write(work / "part2" / "pose3d.json", b"{}")
        return out

    monkeypatch.setattr(chain, "follower", chain_with_media)
    api.app.child.files["animation.json"] = json.dumps({"format": "simon.animation.v1", "fps": 10, "frame_count": 2, "duration_s": 0.2,
                                                        "frames": [{"index": i, "t": i / 10, "joints": {"nose": [0, 0, 0]}} for i in range(2)]}).encode()
    upload = _upload(api, tiny_mp4)
    status, doc = api.json("POST", "api/follow", {"upload_id": upload, "entry_id": "lateral-raise", **extra})
    assert status == 202, doc
    api.app.queue.wait(doc["job"], 60)
    return doc["job"], upload


def test_a_model_only_follow_deletes_the_video_after_the_analysis(api: Api, tiny_mp4: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # AC-MO-2
    job, upload = model_follow(api, tiny_mp4, monkeypatch, model_only=True)
    folder = api.app.queue.job_dir(job)
    assert media_in(folder) == []
    assert (folder / "work" / "follower" / "analysis.json").is_file() and (folder / "work" / "follower" / "replay.json").is_file()
    assert (folder / "work" / "follower" / "part2" / "pose3d.json").is_file()
    assert not (api.app.uploads / upload).exists()  # the raw upload went too
    status, record = api.json("GET", f"api/jobs/{job}")
    assert status == 200 and record["status"] == "done" and record["video_kept"] is False and record["result"]["video_kept"] is False
    assert api.request("GET", f"api/results/{job}/video.mp4")[0] == 404


def test_the_served_results_carry_video_kept_false(api: Api, tiny_mp4: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # AC-MO-3
    job, _ = model_follow(api, tiny_mp4, monkeypatch, model_only=True)
    for name in ("analysis.json", "replay.json"):
        status, _, data = api.request("GET", f"api/results/{job}/{name}")
        assert status == 200 and json.loads(data)["video_kept"] is False, name


def test_a_default_take_keeps_its_video_and_its_bytes(api: Api, tiny_mp4: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # AC-MO-3
    job, upload = model_follow(api, tiny_mp4, monkeypatch)
    folder = api.app.queue.job_dir(job)
    assert (folder / "work" / "video.mp4").is_file() and (api.app.uploads / upload).is_dir()
    record = api.json("GET", f"api/jobs/{job}")[1]
    assert record["video_kept"] is True and "video_kept" not in record["result"]  # absent in the stored record means true
    status, _, data = api.request("GET", f"api/results/{job}/analysis.json")
    assert status == 200 and "video_kept" not in json.loads(data)
    assert api.request("GET", f"api/results/{job}/video.mp4")[0] in (200, 206)


@pytest.mark.parametrize("value", ["yes", 1, None, "true"])
def test_only_a_real_true_turns_it_on(api: Api, tiny_mp4: Path, monkeypatch: pytest.MonkeyPatch, value: Any) -> None:  # AC-MO-2
    job, _ = model_follow(api, tiny_mp4, monkeypatch, model_only=value)
    assert (api.app.queue.job_dir(job) / "work" / "video.mp4").is_file()
    assert api.json("GET", f"api/jobs/{job}")[1]["video_kept"] is True


# ----- AC-MO-4: the order ---------------------------------------------------------------------------------
def test_the_delete_runs_only_after_the_analysis_and_3d_files_exist(tmp_path: Path, tiny_mp4: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # AC-MO-4
    seen: dict[str, Any] = {}
    real = model_only.purge_job

    def spy(folder: Path) -> list[str]:
        follower = folder / "work" / "follower"
        seen["at_purge"] = (follower / "analysis.json").is_file(), (follower / "replay.json").is_file(), (follower / "part2" / "pose3d.json").is_file()
        return real(folder)

    def chain_fake(video: Path, expected: Path, work: Path, report: Any = None, **kw: Any) -> dict[str, Any]:
        seen["video_during_chain"] = Path(video).is_file()
        write(Path(work) / "part2" / "pose3d.json", b"{}")
        return _fake_follower()(video, expected, work, report, **kw)

    monkeypatch.setattr(chain, "follower", chain_fake)
    monkeypatch.setattr(model_only, "purge_job", spy)
    queue = jobs.JobQueue(tmp_path / "jobs", workers=1)
    raw = write(tmp_path / "raw" / "upload.mp4", tiny_mp4.read_bytes())
    dropped: list[str] = []
    fn = processor.follow_job(raw, expected=b"{}", entry_id="e", phrasing="template", video_kept=False, drop_source=dropped.append)
    job = queue.submit("follow", fn, entry_id="e", video_kept=False)
    try:
        assert queue.wait(job["id"], 30)["status"] == "done"
    finally:
        queue.close()
    assert seen["video_during_chain"] is True and seen["at_purge"] == (True, True, True)
    assert dropped == [job["id"]]


def test_a_failed_model_only_take_keeps_no_video_either(tmp_path: Path, tiny_mp4: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # AC-MO-4
    monkeypatch.setattr(chain, "follower", lambda video, expected, work, report=None, **kw: {"ok": False, "stage": "pose", "error": "failed:pose: no person"})
    queue = jobs.JobQueue(tmp_path / "jobs", workers=1)
    raw = write(tmp_path / "raw" / "upload.mp4", tiny_mp4.read_bytes())
    fn = processor.follow_job(raw, expected=b"{}", entry_id="e", phrasing="template", video_kept=False)
    job = queue.submit("follow", fn, entry_id="e", video_kept=False)
    try:
        assert queue.wait(job["id"], 30)["status"] == "failed"
    finally:
        queue.close()
    assert media_in(queue.job_dir(job["id"])) == []


# ----- the raw upload and people job are kept while another job uses them --------------------------------
def test_the_dropper_keeps_what_another_job_still_uses(api: Api) -> None:  # AC-MO-2
    uploads = api.app.uploads
    write(uploads / "0123456789abcdef" / "upload.mp4")
    people = api.app.queue.job_dir("bbbbbbbbbbbb")
    write(people / "work" / "clip.mp4")
    write(people / "people" / "0.jpg")
    write(people / "work" / "tracks.json", b"{}")
    q = api.app.queue
    q._jobs["bbbbbbbbbbbb"] = {"id": "bbbbbbbbbbbb", "kind": "people", "status": "done", "upload_id": "0123456789abcdef"}
    q._jobs["aaaaaaaaaaaa"] = {"id": "aaaaaaaaaaaa", "kind": "follow", "status": "running", "upload_id": "0123456789abcdef", "people_job": "bbbbbbbbbbbb"}
    q._jobs["cccccccccccc"] = {"id": "cccccccccccc", "kind": "follow", "status": "done", "upload_id": "0123456789abcdef", "people_job": "bbbbbbbbbbbb"}
    drop = model_only.source_dropper(q, uploads, "0123456789abcdef", "bbbbbbbbbbbb")
    drop("aaaaaaaaaaaa")
    assert (uploads / "0123456789abcdef").is_dir() and media_in(people) != []  # a finished sibling still reads them
    del q._jobs["cccccccccccc"]
    drop("aaaaaaaaaaaa")
    assert not (uploads / "0123456789abcdef").exists() and media_in(people) == []
    assert (people / "work" / "tracks.json").is_file()  # the tracks stay for the models-used page


# ----- AC-MO-5: restart ----------------------------------------------------------------------------------
def test_a_rebuilt_job_after_a_restart_is_still_model_only(api: Api, tiny_mp4: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # AC-MO-5
    seen: dict[str, Any] = {}
    monkeypatch.setattr(processor, "follow_job", lambda raw, **kw: seen.update(kw) or (lambda ctx: {}))
    api.app.child.files["animation.json"] = json.dumps({"format": "simon.animation.v1", "frames": []}).encode()
    upload = _upload(api, tiny_mp4)
    record = {"id": "aaaaaaaaaaaa", "kind": "follow", "entry_id": "lateral-raise", "upload_id": upload, "video_kept": False,
              "_resume": {"v": resume.SPEC_VERSION, "upload_id": upload}}
    assert resume.rebuild(api.app, record) is not None
    assert seen["video_kept"] is False and callable(seen["drop_source"])
    seen.clear()
    assert resume.rebuild(api.app, {k: v for k, v in record.items() if k != "video_kept"}) is not None
    assert seen["video_kept"] is True and seen["drop_source"] is None


# ----- AC-MO-6: history never offers or sends a clip -----------------------------------------------------
def test_a_model_only_take_has_no_history_clip(tmp_path: Path, world: World) -> None:  # AC-MO-6
    world.opted_in.add(USER)
    folder = seed_job(tmp_path, SECOND, video_kept=False)
    world.owners[SECOND] = USER
    assert history_store.record_take(tmp_path, job_record(tmp_path, SECOND), folder) is True
    copy = next((tmp_path / "history" / USER).glob("*/takes/" + SECOND))
    assert sorted(p.name for p in copy.iterdir()) == ["analysis.json", "meta.json"]  # no clip.mp4 was made
    meta = json.loads((copy / "meta.json").read_text())
    assert meta["clip"] is False and meta["video_kept"] is False
    (row,) = history_store.takes(tmp_path, USER, "body-squat-19b06562")
    assert row["clip"] is None and row["video_kept"] is False
    write(copy / history_store.CLIP_NAME)  # even a stray file on disk is not a clip for a model-only take
    assert history_store.takes(tmp_path, USER, "body-squat-19b06562")[0]["clip"] is None


def test_the_reel_and_the_pack_never_offer_a_model_only_take(tmp_path: Path, world: World) -> None:  # AC-MO-6
    world.opted_in.add(USER)
    for job, fields in ((FIRST, {}), (SECOND, {"video_kept": False})):
        folder = seed_job(tmp_path, job, **fields)
        world.owners[job] = USER
        assert history_store.record_take(tmp_path, job_record(tmp_path, job), folder)
    rows = history_store.takes(tmp_path, USER, "body-squat-19b06562")
    by_job = {r["job_id"]: r for r in rows}
    assert by_job[FIRST]["clip"] is not None and by_job[SECOND]["clip"] is None
    assert history_prompt._eligible(by_job[FIRST], True) is True
    assert history_prompt._eligible(by_job[SECOND], True) is False  # never sent as video, never in the reel's clip list
    public = history_routes._public_take("body-squat-19b06562", by_job[SECOND], {})
    assert public["video_kept"] is False and public["clip"] is None
    assert history_routes._public_take("body-squat-19b06562", by_job[FIRST], {})["video_kept"] is True


def test_a_pending_take_is_marked_too(tmp_path: Path, world: World) -> None:  # AC-MO-6
    world.opted_in.add(USER)
    seed_job(tmp_path, SECOND, video_kept=False)
    world.owners[SECOND] = USER
    pending = history_store.pending_take(tmp_path, USER, SECOND)
    assert pending is not None and pending["video_kept"] is False and pending["clip"] is None


# ----- AC-MO-7: the guard and the facts do not break when the files are gone ---------------------------------
def test_facts_and_the_guard_read_a_take_whose_files_are_gone(tmp_path: Path, world: World) -> None:  # AC-MO-7
    from part7 import history_facts

    world.opted_in.add(USER)
    folder = seed_job(tmp_path, SECOND, video_kept=False)
    world.owners[SECOND] = USER
    model_only.purge_job(folder)  # what the job did before the history copy
    assert media_in(folder) == []
    assert history_store.record_take(tmp_path, job_record(tmp_path, SECOND), folder) is True
    rows = history_store.takes(tmp_path, USER, "body-squat-19b06562")
    facts = history_facts.build(rows, "body-squat-19b06562")
    assert facts["takes"] and facts["takes"][0]["take"] == 1


# ----- AC-MO-8: share never carries a clip ----------------------------------------------------------------
@pytest.mark.usefixtures("authenv")
def test_a_share_of_a_model_only_take_forces_the_clip_off(api: Api) -> None:  # AC-MO-8
    sid = sign_in(api)

    def fn(ctx: Any) -> dict[str, Any]:
        (ctx.work / "follower").mkdir()
        (ctx.work / "follower" / "analysis.json").write_text(json.dumps({"score": {"value": 70, "grade": "C"}, "faults": []}))
        return {"result": {}}

    made = api.app.queue.submit("follow", fn, entry_id=SHARE_ENTRY, video_kept=False)
    assert api.app.queue.wait(made["id"], 10)["status"] == "done"
    assert post(api, "api/me/claims", claim_doc(api, made["id"]), cookie=sid)[0] == 200
    status, _, doc = post(api, "api/shares", share_body(made["id"], show_clip=True), cookie=sid)
    assert status == 201, doc
    status, _, shared = get(api, f"api/shared/{doc['token']}")
    assert status == 200 and shared["clip"] is None
    assert get(api, f"api/shared/{doc['token']}/clip.mp4")[0] == 404
    assert post(api, "api/shares/preview", share_body(made["id"], show_clip=True), cookie=sid)[2]["clip_included"] is False
    plain = share_job(api)  # a take with a video still refuses a tick it cannot honour (unchanged)
    assert post(api, "api/me/claims", claim_doc(api, plain), cookie=sid)[0] == 200
    assert post(api, "api/shares", share_body(plain, show_clip=True), cookie=sid)[0] == 400


# ----- AC-MO-9: delete, forget, export still work ---------------------------------------------------------
def test_delete_my_take_works_on_a_model_only_take(api: Api, tiny_mp4: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # AC-MO-9
    job, _ = model_follow(api, tiny_mp4, monkeypatch, model_only=True)
    status, body = api.json("POST", f"api/jobs/{job}/delete", {})
    assert status == 200 and body["deleted"] is True and "job" in body["removed"]
    assert not api.app.queue.job_dir(job).exists()
    assert api.json("GET", f"api/jobs/{job}")[0] == 404


def test_forget_removes_a_model_only_history_copy(tmp_path: Path, world: World) -> None:  # AC-MO-9
    world.opted_in.add(USER)
    folder = seed_job(tmp_path, SECOND, video_kept=False)
    world.owners[SECOND] = USER
    assert history_store.record_take(tmp_path, job_record(tmp_path, SECOND), folder)
    assert history_store.forget(tmp_path, USER) >= 1
    assert history_store.takes(tmp_path, USER, "body-squat-19b06562") == []
    assert history_store.drop_take(tmp_path, SECOND) == 0  # nothing left, no error


@pytest.mark.usefixtures("authenv")
def test_export_my_data_lists_a_model_only_take(api: Api) -> None:  # AC-MO-9
    sid = sign_in(api)
    store = auth.identity(api.app)
    uid = store.session_user(sid)
    (kept,) = seed_takes(api.app.state, store, uid, "mo", 1, clip=False)
    meta_path = history_store.take_dir(api.app.state, uid, SEED_ENTRY, kept) / history_store.META_NAME
    meta = json.loads(meta_path.read_text())
    history_store.write_json(meta_path, {**meta, "video_kept": False})
    status, _, doc = get(api, "api/me/export", sid)
    assert status == 200
    assert doc["takes"][0]["video_kept"] is False
    assert doc["history"][0]["takes"][0]["clip"] is None
    status, _, listing = get(api, "api/me/takes", sid)
    assert status == 200 and listing["takes"][0]["video_kept"] is True  # no job folder for the seeded take: the default


# ----- AC-MO-10: no export clip -----------------------------------------------------------------------------
def test_an_export_clip_is_refused_with_a_plain_reason(api: Api, tiny_mp4: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # AC-MO-10
    job, _ = model_follow(api, tiny_mp4, monkeypatch, model_only=True)
    status, doc = api.json("POST", f"api/jobs/{job}/export", {})
    assert status == 409 and doc["error"] == model_only.MSG_NO_VIDEO


def test_kept_and_requested_read_only_the_exact_values() -> None:  # AC-MO-2
    assert model_only.kept({}) and model_only.kept({"video_kept": True}) and model_only.kept(None) and model_only.kept({"video_kept": "no"})
    assert not model_only.kept({"video_kept": False})
    assert model_only.requested({"model_only": True}) and not model_only.requested({"model_only": 1}) and not model_only.requested(None)
    assert model_only.mark(b"[1]") == b"[1]" and model_only.mark(b"nope") == b"nope"
    assert json.loads(model_only.mark(b'{"a": 1}')) == {"a": 1, "video_kept": False}
    assert os.sep not in model_only.FIELD
