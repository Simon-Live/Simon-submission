"""My reference (docs/specs/my-reference.md AC-MR-1 to AC-MR-12; ADR-0019). Fake chain, no GPU, no real clip."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from auth_support import authenv, get, post, sign_in  # noqa: F401
from part7 import auth, chain, history_facts, judge_view, mesh_files, my_reference, my_reference_routes, processor, resume, server, teacher_stats
from support import Api
from test_history_facts import _made
from test_practice import animation
from test_server import OK_ANALYSIS, _upload

ENTRY = "lateral-raise"
ADA, GRACE = "ada@example.com", "grace@example.com"


@pytest.fixture()
def seen(monkeypatch: pytest.MonkeyPatch) -> list[bytes]:
    """The `expected` bytes each follow run was given. The fake writes its own `follower.json`, named by the job."""
    got: list[bytes] = []

    def fake(video: Path, expected: Path, work: Path, report: Any = None, **kw: Any) -> dict[str, Any]:
        got.append(Path(expected).read_bytes())
        work.mkdir(parents=True, exist_ok=True)
        (work / "analysis.json").write_text(json.dumps(OK_ANALYSIS), encoding="utf-8")
        (work / "follower.json").write_text(json.dumps({"format": "simon.skeleton.v1", "own": len(got)}), encoding="utf-8")
        return {"ok": True, "files": {"analysis": str(work / "analysis.json")}, "note": None}

    monkeypatch.setattr(chain, "follower", fake)
    monkeypatch.setattr(my_reference_routes, "accepts", lambda app, data: True)
    return got


def follow(api: Api, mp4: Path, sid: str | None, **extra: Any) -> dict[str, Any]:
    api.app.child.files["animation.json"] = animation()
    headers = {"Cookie": f"{auth.COOKIE}={sid}"} if sid else {}
    status, doc = api.json("POST", "api/follow", {"upload_id": _upload(api, mp4), "entry_id": ENTRY, **extra}, headers)
    assert status == 202, doc
    return api.app.queue.wait(doc["job"], 60)


def mark(api: Api, sid: str, job_id: Any) -> tuple[int, Any]:
    status, _, body = post(api, "api/me/reference", {"job_id": job_id}, cookie=sid)
    return status, body


def mine(api: Api, sid: str) -> Any:
    return get(api, f"api/me/reference?entry={ENTRY}", sid)[2]


@pytest.mark.usefixtures("authenv")
def test_default_is_the_teacher_reference_and_says_so(api: Api, tiny_mp4: Path, seen: list[bytes]) -> None:  # AC-MR-1, AC-MR-5
    sid = sign_in(api, ADA)
    job = follow(api, tiny_mp4, sid)
    assert job["reference"] == {"used": "teacher"} and seen[0] == animation()
    assert follow(api, tiny_mp4, None)["reference"] == {"used": "teacher"}  # signed out: same


@pytest.mark.usefixtures("authenv")
def test_marked_take_becomes_the_reference_of_later_takes(api: Api, tiny_mp4: Path, seen: list[bytes]) -> None:  # AC-MR-2, 3, 4
    sid = sign_in(api, ADA)
    first = follow(api, tiny_mp4, sid)
    status, body = mark(api, sid, first["id"])
    assert status == 200 and body["reference"]["job_id"] == first["id"] and body["reference"]["teacher_note"] is False
    second = follow(api, tiny_mp4, sid)
    ref = second["reference"]
    assert ref["used"] == "own" and ref["job_id"] == first["id"] and ref["date"] == str(first["created_at"])[:10]
    assert json.loads(seen[1]) == {"format": "simon.skeleton.v1", "own": 1}  # the first take's skeleton, not the teacher's animation
    assert seen[0] == animation() and seen[1] != animation()


@pytest.mark.usefixtures("authenv")
def test_replace_and_remove(api: Api, tiny_mp4: Path, seen: list[bytes]) -> None:  # AC-MR-6
    sid = sign_in(api, ADA)
    a, b = follow(api, tiny_mp4, sid), follow(api, tiny_mp4, sid)
    mark(api, sid, a["id"])
    assert mark(api, sid, b["id"])[0] == 200 and mine(api, sid)["reference"]["job_id"] == b["id"]  # one per movement
    assert len(list((api.app.state / "myref").glob("*/*"))) == 1
    assert post(api, "api/me/reference/remove", {"entry_id": ENTRY}, cookie=sid)[0] == 200
    assert mine(api, sid)["reference"] is None
    assert follow(api, tiny_mp4, sid)["reference"] == {"used": "teacher"}  # reversal: back to the teacher's clip
    assert post(api, "api/me/reference/remove", {"entry_id": ENTRY}, cookie=sid)[0] == 404


@pytest.mark.usefixtures("authenv")
def test_owner_only(api: Api, tiny_mp4: Path, seen: list[bytes]) -> None:  # AC-MR-7
    ada, grace = sign_in(api, ADA), sign_in(api, GRACE)
    a = follow(api, tiny_mp4, ada)
    assert mark(api, grace, a["id"])[0] == 404  # not Grace's take: same answer as a take that does not exist
    assert mark(api, grace, "ffffffffffff")[0] == 404
    mark(api, ada, a["id"])
    assert mine(api, grace)["reference"] is None
    assert post(api, "api/me/reference/remove", {"entry_id": ENTRY}, cookie=grace)[0] == 404
    assert follow(api, tiny_mp4, grace)["reference"] == {"used": "teacher"}  # Grace is not compared with Ada's rep
    assert mine(api, ada)["reference"]["job_id"] == a["id"]
    for call in (lambda: get(api, f"api/me/reference?entry={ENTRY}"), lambda: post(api, "api/me/reference", {"job_id": a["id"]})):
        assert call()[0] == 401


@pytest.mark.usefixtures("authenv")
def test_refusals(api: Api, tiny_mp4: Path, seen: list[bytes]) -> None:  # AC-MR-8
    sid = sign_in(api, ADA)
    done = follow(api, tiny_mp4, sid)
    priv = follow(api, tiny_mp4, sid, private=True)
    assert mark(api, sid, priv["id"])[0] == 409
    assert mark(api, sid, 5)[0] == 404 and mark(api, sid, "../x")[0] == 404
    assert post(api, "api/me/reference", {"job_id": done["id"]}, guard=False, cookie=sid)[0] == 403  # CSRF guard
    (api.app.queue.job_dir(done["id"]) / "work" / "follower" / "follower.json").unlink()
    assert mark(api, sid, done["id"])[0] == 422
    assert mine(api, sid)["reference"] is None


@pytest.mark.usefixtures("authenv")
def test_part5_refusal_is_422(api: Api, tiny_mp4: Path, seen: list[bytes], monkeypatch: pytest.MonkeyPatch) -> None:  # AC-MR-8
    sid = sign_in(api, ADA)
    done = follow(api, tiny_mp4, sid)
    monkeypatch.setattr(my_reference_routes, "accepts", lambda app, data: False)
    assert mark(api, sid, done["id"])[0] == 422 and mine(api, sid)["reference"] is None


@pytest.mark.usefixtures("authenv")
def test_deleted_reference_take_falls_back_and_says_so(api: Api, tiny_mp4: Path, seen: list[bytes]) -> None:  # AC-MR-9
    sid = sign_in(api, ADA)
    first = follow(api, tiny_mp4, sid)
    mark(api, sid, first["id"])
    assert api.json("POST", f"api/jobs/{first['id']}/delete", None)[0] == 200
    later = follow(api, tiny_mp4, sid)
    assert later["reference"] == {"used": "teacher", "why": "reference_deleted"} and seen[-1] == animation()
    body = mine(api, sid)
    assert body["reference"] is None and body["fell_back"] is True
    third = follow(api, tiny_mp4, sid)  # a new mark replaces the marker
    mark(api, sid, third["id"])
    assert mine(api, sid)["fell_back"] is False


@pytest.mark.usefixtures("authenv")
def test_a_section_take_uses_the_teacher_and_says_so(api: Api, tiny_mp4: Path, seen: list[bytes]) -> None:  # AC-MR-10
    sid = sign_in(api, ADA)
    first = follow(api, tiny_mp4, sid)
    mark(api, sid, first["id"])
    sec = {"start_ms": 1000, "end_ms": 3000, "index": 2, "count": 4}
    assert follow(api, tiny_mp4, sid, section=sec)["reference"] == {"used": "teacher", "why": "section"}


@pytest.mark.usefixtures("authenv")
def test_teacher_loop_link_is_recorded_when_a_note_was_answered(api: Api, tiny_mp4: Path, seen: list[bytes], monkeypatch: pytest.MonkeyPatch) -> None:  # AC-MR-11
    sid = sign_in(api, ADA)
    first = follow(api, tiny_mp4, sid)
    monkeypatch.setattr(my_reference_routes.notes, "latest_for_job", lambda store, user, job: {"state": "answered"})
    assert mark(api, sid, first["id"])[1]["reference"]["teacher_note"] is True
    assert follow(api, tiny_mp4, sid)["reference"]["teacher_note"] is True


@pytest.mark.usefixtures("authenv")
def test_download_my_data_lists_it_and_account_deletion_removes_it(api: Api, tiny_mp4: Path, seen: list[bytes]) -> None:  # AC-MR-12
    ada, grace = sign_in(api, ADA), sign_in(api, GRACE)
    a, g = follow(api, tiny_mp4, ada), follow(api, tiny_mp4, grace)
    mark(api, ada, a["id"])
    mark(api, grace, g["id"])
    rows = get(api, "api/me/export", ada)[2]["my_references"]
    assert [r["entry_id"] for r in rows] == [ENTRY] and rows[0]["state"] == "ok" and "own" not in json.dumps(rows)
    assert g["id"] not in json.dumps(rows)  # nothing of another account
    assert post(api, "api/me/delete", {"confirm": "delete"}, cookie=ada)[0] == 200
    assert len(list((api.app.state / "myref").glob("*/*"))) == 1  # only Grace's is left
    assert mine(api, grace)["reference"]["job_id"] == g["id"]


def test_choose_without_a_user_or_with_a_bad_id_is_the_teacher(tmp_path: Path) -> None:  # AC-MR-1
    assert my_reference.choose(tmp_path, None, ENTRY, b"t").record == {"used": "teacher"}
    assert my_reference.choose(tmp_path, "../x", ENTRY, b"t").expected == b"t"
    assert my_reference.forget(tmp_path, "../x") == 0 and my_reference.take_deleted(tmp_path, "nope") == 0


def test_an_unreadable_copy_falls_back_with_a_reason(tmp_path: Path) -> None:  # AC-MR-9
    user = "u-0123456789abcdef01234567"
    my_reference.set_reference(tmp_path, user, ENTRY, "a" * 12, "2026-10-12", b"{}", False)
    (my_reference.folder(tmp_path, user, ENTRY) / my_reference.REFERENCE_NAME).unlink()
    assert my_reference.choose(tmp_path, user, ENTRY, b"t").record == {"used": "teacher", "why": "reference_unusable"}


def test_restart_rebuild_keeps_the_named_reference_or_refuses(tmp_path: Path) -> None:  # AC-MR-3
    from types import SimpleNamespace
    from unittest import mock

    from part7 import resume

    user = "u-0123456789abcdef01234567"
    app = SimpleNamespace(state=tmp_path)
    record = {"id": "b" * 12, "entry_id": ENTRY, "reference": {"used": "own", "job_id": "a" * 12}}
    with mock.patch.object(resume.auth, "job_owner", return_value=user):
        assert resume._reference(app, record, b"t") == (None, False)  # reference gone: the job cannot run under a false label
        my_reference.set_reference(tmp_path, user, ENTRY, "a" * 12, "2026-10-12", b"own", False)
        assert resume._reference(app, record, b"t") == (b"own", True)
    assert resume._reference(app, {"id": "c" * 12}, b"t") == (b"t", False)


# ----- review fixes (B1 to B7, R1 to R5) -----------------------------------------------------------------------------
def record_of(api: Api, job_id: str, sid: str | None) -> dict[str, Any]:
    return get(api, f"api/jobs/{job_id}", sid)[2]["reference"]


@pytest.mark.usefixtures("authenv")
def test_job_record_hides_the_reference_take_and_the_teacher_link_from_everyone_but_the_owner(
        api: Api, tiny_mp4: Path, seen: list[bytes], monkeypatch: pytest.MonkeyPatch) -> None:  # AC-MR-15 (B1)
    ada, grace = sign_in(api, ADA), sign_in(api, GRACE)
    first = follow(api, tiny_mp4, ada)
    monkeypatch.setattr(my_reference_routes.notes, "latest_for_job", lambda store, user, job: {"state": "answered"})
    mark(api, ada, first["id"])
    second = follow(api, tiny_mp4, ada)
    mine_ = record_of(api, second["id"], ada)
    assert mine_["job_id"] == first["id"] and mine_["teacher_note"] is True
    for viewer in (grace, None):  # another account, and a link viewer who is signed out
        seen_ref = record_of(api, second["id"], viewer)
        assert seen_ref == {"used": "own", "date": mine_["date"]}
        raw = api.request("GET", f"api/jobs/{second['id']}", None, {"Cookie": f"{auth.COOKIE}={viewer}"} if viewer else {})[2].decode()
        assert first["id"] not in raw.replace(second["id"], "") and "teacher_note" not in raw


@pytest.mark.usefixtures("authenv")
def test_a_person_of_a_group_video_is_scored_against_the_teacher_and_cannot_be_marked(
        api: Api, tiny_mp4: Path, seen: list[bytes], monkeypatch: pytest.MonkeyPatch) -> None:  # AC-MR-16 (B3)
    sid = sign_in(api, ADA)
    first = follow(api, tiny_mp4, sid)
    mark(api, sid, first["id"])
    assert my_reference.choose(api.app.state, "u-0123456789abcdef01234567", ENTRY, b"t", None, True).record == {"used": "teacher", "why": "group"}
    with monkeypatch.context() as scoped:  # TICKET-349: a bare monkeypatch.undo() also undid the fakes and ran real Part 2
        scoped.setattr(server._Handler, "_clip_of", lambda self, doc, raw: (None, {"people_job": "p" * 12}, None))
        grouped = follow(api, tiny_mp4, sid)
        assert grouped["reference"] == {"used": "teacher", "why": "group"} and seen[-1] == animation()
    other = follow(api, tiny_mp4, sid)
    api.app.queue._jobs[other["id"]]["person_id"] = "p1"
    assert mark(api, sid, other["id"])[0] == 409
    api.app.queue._jobs[other["id"]].pop("person_id")
    api.app.queue._jobs[other["id"]]["people_job"] = "p" * 12
    assert mark(api, sid, other["id"])[0] == 409
    assert mine(api, sid)["reference"]["job_id"] == first["id"]


@pytest.mark.usefixtures("authenv")
def test_an_unfinished_take_is_409(api: Api, tiny_mp4: Path, seen: list[bytes]) -> None:  # AC-MR-8 (B7)
    sid = sign_in(api, ADA)
    job = follow(api, tiny_mp4, sid)
    api.app.queue._jobs[job["id"]]["status"] = "running"
    assert mark(api, sid, job["id"])[0] == 409 and mine(api, sid)["reference"] is None


@pytest.mark.usefixtures("authenv")
def test_delete_my_data_and_forgetting_one_movement_remove_the_reference(api: Api, tiny_mp4: Path, seen: list[bytes]) -> None:  # AC-MR-12 (B7)
    sid = sign_in(api, ADA)
    hdr = {"Cookie": f"{auth.COOKIE}={sid}", "Origin": f"http://127.0.0.1:{api.port}"}
    job = follow(api, tiny_mp4, sid)
    mark(api, sid, job["id"])
    assert api.json("DELETE", f"api/me/history/{ENTRY}", None, hdr)[0] == 200  # forget this movement
    assert mine(api, sid)["reference"] is None and not list((api.app.state / "myref").glob("*/*"))
    mark(api, sid, job["id"])
    assert api.json("DELETE", "api/me/history", None, hdr)[0] == 200  # delete my data
    assert not list((api.app.state / "myref").glob("*/*"))


@pytest.mark.usefixtures("authenv")
def test_marking_the_same_take_again_runs_no_check_and_many_changes_are_limited(
        api: Api, tiny_mp4: Path, seen: list[bytes], monkeypatch: pytest.MonkeyPatch) -> None:  # AC-MR-17 (R2)
    sid = sign_in(api, ADA)
    a, b = follow(api, tiny_mp4, sid), follow(api, tiny_mp4, sid)
    calls: list[int] = []
    monkeypatch.setattr(my_reference_routes, "accepts", lambda app, data: calls.append(1) or True)
    monkeypatch.setattr(my_reference_routes, "LIMIT", (2, 60))
    assert mark(api, sid, a["id"])[0] == 200 and mark(api, sid, a["id"])[0] == 200 and len(calls) == 1
    assert mark(api, sid, b["id"])[0] == 200
    assert mark(api, sid, a["id"])[0] == 429 and len(calls) == 2


def test_a_switch_of_reference_is_never_improved_or_fixed(tmp_path: Path) -> None:  # AC-MR-18 (B4)
    def takes(refs: list[str]) -> list[dict[str, Any]]:
        mags = [30, 25, 10]
        return [_made(tmp_path, n + 1, 60 + n, [("knee_valgus", "left", 1.0, mags[n])], reference=refs[n]) for n in range(3)]
    statuses = lambda refs: {m["status"] for m in history_facts.build(takes(refs))["measures"]}  # noqa: E731
    assert statuses(["teacher", "teacher", "teacher"]) & {"improved", "fixed"}  # control: a real fall in one series is reported
    switched = history_facts.build(takes(["teacher", "teacher", "own:" + "a" * 12]))
    assert not {m["status"] for m in switched["measures"]} & {"improved", "fixed"}
    assert [r["in_group"] for r in switched["takes"]] == [False, False, True]


def test_the_history_row_stores_the_reference(tmp_path: Path) -> None:  # AC-MR-18 (B4)
    from part7 import history_store
    assert history_store.reference_key({"reference": {"used": "own", "job_id": "a" * 12}}) == "own:" + "a" * 12
    assert history_store.reference_key({"reference": {"used": "teacher"}}) == history_store.reference_key({}) == "teacher"


def test_an_own_reference_take_is_never_the_hero_and_not_in_the_teachers_stats(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # AC-MR-19 (R5)
    jobs_root = tmp_path / "jobs"
    for name, extra in (("a" * 12, {}), ("b" * 12, {"reference": {"used": "own", "job_id": "c" * 12}})):
        folder = jobs_root / name
        (folder / "work" / "follower").mkdir(parents=True)
        (folder / "job.json").write_text(json.dumps({"id": name, "kind": "follow", "status": "done", "entry_id": ENTRY, "finished_at": "2026-11-01T10:00:00Z",
                                                      "result": {"score": 90}, **extra}), encoding="utf-8")
        (folder / "work" / "follower" / "analysis.json").write_text(json.dumps({"status": {"code": "ok"}, "score": {"value": 90, "grade": "A"}}), encoding="utf-8")
    monkeypatch.setattr(mesh_files, "index", lambda root, job: {"trainer": True, "you": True})
    monkeypatch.setattr(judge_view, "_warned", lambda folder, result: False)
    assert judge_view._candidate(jobs_root, "a" * 12)["job_id"] == "a" * 12
    assert judge_view._candidate(jobs_root, "b" * 12) is None
    assert teacher_stats._parse_folder(jobs_root / ("a" * 12))[1] is not None
    assert teacher_stats._parse_folder(jobs_root / ("b" * 12)) is None


@pytest.fixture()
def visibility_seen(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """The `visibility` each `processor.follow_job` was built with (the teacher's skeleton, or None)."""
    got: list[Any] = []
    real = processor.follow_job

    def spy(*args: Any, **kw: Any) -> Any:
        got.append(kw.get("visibility"))
        return real(*args, **kw)

    monkeypatch.setattr(processor, "follow_job", spy)
    return got


@pytest.mark.usefixtures("authenv")
def test_the_teachers_visibility_goes_to_a_teacher_take_and_not_to_an_own_take(
        api: Api, tiny_mp4: Path, seen: list[bytes], visibility_seen: list[Any]) -> None:  # AC-MR-14 (K2)
    sid = sign_in(api, ADA)
    first = follow(api, tiny_mp4, sid)
    mark(api, sid, first["id"])
    follow(api, tiny_mp4, sid)
    assert visibility_seen[0] == api.app.child.files["skeleton.json"] and visibility_seen[1] is None


def test_a_rebuilt_job_gets_the_same_visibility_rule(tmp_path: Path, api: Api, visibility_seen: list[Any], monkeypatch: pytest.MonkeyPatch) -> None:  # AC-MR-14 (K2)
    user = "u-0123456789abcdef01234567"
    monkeypatch.setattr(resume.auth, "job_owner", lambda app, job_id: user)
    raw = tmp_path / "raw.mp4"
    raw.write_bytes(b"x")
    api.app.child.files["animation.json"] = animation()
    teacher = {"id": "b" * 12, "entry_id": ENTRY, "reference": {"used": "teacher"}}
    resume._follow(api.app, teacher, raw, None)
    my_reference.set_reference(api.app.state, user, ENTRY, "a" * 12, "2026-10-12", b"{}", False)
    own = {"id": "c" * 12, "entry_id": ENTRY, "reference": {"used": "own", "job_id": "a" * 12}}
    resume._follow(api.app, own, raw, None)
    assert visibility_seen[0] == api.app.child.files["skeleton.json"] and visibility_seen[1] is None


def people_job(api: Api, job_id: str, count: int) -> str:
    """A finished people job that found `count` people, with the files `people_routes.people_result` needs."""
    work = api.app.queue.job_dir(job_id) / "work"
    work.mkdir(parents=True)
    (work / "clip.mp4").write_bytes(b"c")
    (work / "tracks.json").write_text("{}", encoding="utf-8")
    api.app.queue._jobs[job_id] = {"id": job_id, "kind": "people", "status": "done",
                                   "result": {"people": [{"id": str(n)} for n in range(count)], "auto_id": "0"}}
    return job_id


@pytest.mark.usefixtures("authenv")
def test_a_one_person_upload_with_a_people_job_can_be_marked_and_uses_its_reference(
        api: Api, tiny_mp4: Path, seen: list[bytes], monkeypatch: pytest.MonkeyPatch) -> None:  # AC-MR-17 (QA defect)
    sid = sign_in(api, ADA)
    pj = people_job(api, "1" * 12, 1)
    monkeypatch.setattr(server._Handler, "_clip_of", lambda self, doc, raw: (None, {"people_job": pj, "person_id": "0"}, None))
    first = follow(api, tiny_mp4, sid)
    assert first["reference"] == {"used": "teacher"}  # not "group"
    assert mark(api, sid, first["id"])[0] == 200
    second = follow(api, tiny_mp4, sid)
    assert second["reference"]["used"] == "own" and second["reference"]["job_id"] == first["id"]


@pytest.mark.usefixtures("authenv")
def test_a_two_person_group_take_still_cannot_be_marked_or_scored_against_a_reference(
        api: Api, tiny_mp4: Path, seen: list[bytes], monkeypatch: pytest.MonkeyPatch) -> None:  # AC-MR-16
    sid = sign_in(api, ADA)
    solo = follow(api, tiny_mp4, sid)
    mark(api, sid, solo["id"])
    pj = people_job(api, "2" * 12, 2)
    monkeypatch.setattr(server._Handler, "_clip_of", lambda self, doc, raw: (None, {"people_job": pj, "person_id": "1"}, None))
    friend = follow(api, tiny_mp4, sid)
    assert friend["reference"] == {"used": "teacher", "why": "group"} and seen[-1] == animation()
    assert mark(api, sid, friend["id"])[0] == 409
    assert my_reference.is_group(api.app.queue, {"people_job": pj}) and not my_reference.is_group(api.app.queue, {})
