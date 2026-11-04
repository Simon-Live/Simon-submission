"""Go-live re-verification fixes (docs/specs/prod-data.md; private-default.md P-N1, data-integrity.md DI-N1 and DI-R1,
review R2 to R6, a11y-copy R5).

Real sessions through the sign-in routes, the real identity store, queue and upload route. Account A owns the data,
account B is someone else, "anon" sends no cookie.
"""

from __future__ import annotations

import io
import json
import logging
from pathlib import Path
import sqlite3
import types
from typing import Any
import zipfile

import pytest

from auth_support import authenv, get, post, sign_in  # noqa: F401  authenv is a fixture
from part7 import (applog, auth, entry_access, identity, legal_drafts, narration, people_routes, processor, runner,
                   server, trainer_publish, upload_owner)
from support import Api

pytestmark = pytest.mark.usefixtures("authenv")
OTHER = "grace.hopper@example.com"


def user_of(api: Api, sid: str) -> str:
    return get(api, "api/auth/me", cookie=sid)[2]["user_id"]


def cookie(sid: str | None) -> dict[str, str]:
    return {"Cookie": f"{auth.COOKIE}={sid}"} if sid else {}


def upload(api: Api, video: Path, sid: str | None) -> str:
    status, doc = api.upload(video, headers=cookie(sid))
    assert status == 201, doc
    return doc["upload_id"]


def people_job(api: Api, owner: str, upload_id: str) -> str:
    """A finished people job of `owner` from `upload_id`, with its clip, tracks and a picture of each person."""
    def fn(ctx: Any) -> dict[str, Any]:
        (ctx.work / "clip.mp4").write_bytes(b"clip")
        (ctx.work / "tracks.json").write_text("{}")
        (ctx.dir / "people").mkdir(exist_ok=True)
        (ctx.dir / "people" / "1.jpg").write_bytes(b"jpeg")
        return {"result": {"people": [{"id": "1"}], "auto_id": "1"}}

    made = api.app.queue.submit("people", fn, upload_id=upload_id, **{people_routes.OWNER_FIELD: owner})
    assert api.app.queue.wait(made["id"], 10)["status"] == "done"
    return made["id"]


# ----- P-N1: the people job record and the upload answer only their owner -----------------------------------------
def test_pn1_a_people_job_record_answers_only_its_owner(api: Api, tiny_mp4: Path) -> None:
    a, b = sign_in(api), sign_in(api, OTHER)
    job = people_job(api, user_of(api, a), upload(api, tiny_mp4, a))
    status, _, mine = get(api, f"api/jobs/{job}", cookie=a)
    assert status == 200 and mine["kind"] == "people" and people_routes.OWNER_FIELD not in json.dumps(mine)
    missing = api.request("GET", "api/jobs/0123456789ab")
    for sid in (b, None):
        got = api.request("GET", f"api/jobs/{job}", None, cookie(sid))
        assert (got[0], got[2]) == (missing[0], missing[2]) == (404, missing[2]), "the same answer as a missing job"
        assert get(api, f"api/jobs/{job}/people/1.jpg", cookie=sid)[0] == 404


def test_pn1_a_group_take_made_signed_in_answers_only_its_owner(api: Api) -> None:
    a, b = sign_in(api), sign_in(api, OTHER)
    made = api.app.queue.submit("group", lambda ctx: {"result": {}}, **{people_routes.OWNER_FIELD: user_of(api, a)})
    assert api.app.queue.wait(made["id"], 10)["status"] == "done"
    assert get(api, f"api/jobs/{made['id']}", cookie=a)[0] == 200
    assert get(api, f"api/jobs/{made['id']}", cookie=b)[0] == 404 and get(api, f"api/jobs/{made['id']}")[0] == 404
    assert post(api, f"api/jobs/{made['id']}/delete", {}, cookie=b)[0] == 403  # nor may another account delete it
    legacy = api.app.queue.submit("people", lambda ctx: {"result": {}})  # a record without the field: nobody's (fails closed)
    api.app.queue.wait(legacy["id"], 10)
    assert get(api, f"api/jobs/{legacy['id']}", cookie=a)[0] == 404
    anon = api.app.queue.submit("people", lambda ctx: {"result": {}}, **{people_routes.OWNER_FIELD: ""})
    api.app.queue.wait(anon["id"], 10)
    assert get(api, f"api/jobs/{anon['id']}")[0] == 200  # made signed out: the id is its key (identity.md)


def test_pn1_no_one_starts_work_from_another_persons_upload(api: Api, tiny_mp4: Path) -> None:
    a, b = sign_in(api), sign_in(api, OTHER)
    theirs = upload(api, tiny_mp4, a)
    assert json.loads((api.app.uploads / theirs / upload_owner.FILE).read_text()) == {"user": user_of(api, a)}
    missing = post(api, "api/trainer", {"upload_id": "f" * 16, "name": "Mine", "category": "exercise"}, cookie=b)
    assert missing[0] == 400 and missing[2]["error"] == server.MSG_NO_UPLOAD
    for sid in (b, None):
        for route, doc in (("api/trainer", {"name": "Mine", "category": "exercise", "public": True}), ("api/follow",
                           {"entry_id": "lateral-raise"}), ("api/people", {})):
            status, _, body = post(api, route, {"upload_id": theirs, **doc}, cookie=sid)
            assert (status, body) == (400, missing[2]), (route, sid)
    status, _, body = post(api, "api/trainer", {"upload_id": theirs, "name": "Mine", "category": "exercise"}, cookie=a)
    assert status == 202, body  # the uploader's own session still may
    anon_up = upload(api, tiny_mp4, None)
    assert upload_owner.may_use(api.app.uploads / anon_up, None) and upload_owner.may_use(api.app.uploads / anon_up, "u-x")
    (api.app.uploads / anon_up / upload_owner.FILE).unlink()
    assert not upload_owner.may_use(api.app.uploads / anon_up, None), "an upload without its owner file is refused"


def test_sr1_a_legacy_group_record_takes_the_owner_of_its_people_job(tmp_path: Path) -> None:
    """A group record written before it kept `_people_owner` answers with its people job's owner, else UNKNOWN."""
    queue = types.SimpleNamespace(job_dir=lambda job_id: tmp_path / job_id)

    def job(job_id: str, **doc: Any) -> str:
        (tmp_path / job_id).mkdir()
        (tmp_path / job_id / "job.json").write_text(json.dumps(doc))
        return job_id

    people = job("aaaaaaaaaaaa", kind="people", **{upload_owner.PEOPLE_OWNER: "u-owner"})
    ownerless = job("bbbbbbbbbbbb", kind="people")
    assert upload_owner.people_owner(queue, job("cccccccccccc", kind="group", people_job=people)) == "u-owner"
    assert upload_owner.people_owner(queue, job("dddddddddddd", kind="group", people_job=ownerless)) is upload_owner.UNKNOWN
    assert upload_owner.people_owner(queue, job("eeeeeeeeeeee", kind="group")) is upload_owner.UNKNOWN
    assert upload_owner.people_owner(queue, job("ffffffffffff", kind="group", people_job="../x")) is upload_owner.UNKNOWN
    signed_out = job("abababababab", kind="people", **{upload_owner.PEOPLE_OWNER: ""})
    assert upload_owner.people_owner(queue, job("bcbcbcbcbcbc", kind="group", people_job=signed_out)) == ""
    assert upload_owner.people_owner(queue, job("cdcdcdcdcdcd", kind="group", people_job="0" * 12)) is upload_owner.UNKNOWN
    loop = job("dededededede", kind="group", people_job="dededededede")  # never another group record, never a loop
    assert upload_owner.people_owner(queue, loop) is upload_owner.UNKNOWN
    owned_group = job("efefefefefef", kind="group", **{upload_owner.PEOPLE_OWNER: "u-group"})
    assert upload_owner.people_owner(queue, job("fafafafafafa", kind="group", people_job=owned_group)) is upload_owner.UNKNOWN


# ----- DI-N1: Delete my data and the export cover the people job and its upload -----------------------------------
def test_din1_export_lists_the_people_job_and_delete_leaves_none_of_it(api: Api, tiny_mp4: Path) -> None:
    a = sign_in(api)
    user = user_of(api, a)
    up, spare = upload(api, tiny_mp4, a), upload(api, tiny_mp4, a)
    job = people_job(api, user, up)
    status, _, data = api.request("GET", "api/me/export.zip", None, cookie(a))
    assert status == 200
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = set(zf.namelist())
        doc = json.loads(next(zf.read(n) for n in names if n.endswith(".json") and "/" not in n))
    for want in (f"people/{job}/clip.mp4", f"people/{job}/tracks.json", f"people/{job}/pictures/1.jpg",
                 f"people/{job}/upload.mp4", f"uploads/{spare}/upload.mp4"):
        assert want in names, want
    assert job in {r.get("id") for r in doc["job_records"]}  # the people job's record, consent answers included
    assert post(api, "api/me/delete", {"confirm": "delete"}, cookie=a)[0] == 200
    assert not api.app.queue.job_dir(job).exists() and api.app.queue.get(job) is None
    assert not (api.app.uploads / up).exists() and not (api.app.uploads / spare).exists()
    leftovers = [p for p in api.app.state.rglob("*") if p.is_file() and user.encode() in p.read_bytes()
                 and p.parent.name not in ("identity",)]
    assert leftovers == [], leftovers


def test_sr3_the_group_takes_outputs_go_to_its_owner_only(api: Api) -> None:
    a, b = sign_in(api), sign_in(api, OTHER)

    def fn(ctx: Any) -> dict[str, Any]:
        for rel in ("part2/pose3d.json", "trainer/skeleton.json", "person/1/analysis.json", "person/1/replay.json",
                    "person/1/follower.json"):
            (ctx.work / rel).parent.mkdir(parents=True, exist_ok=True)
            (ctx.work / rel).write_text("{}")
        return {"result": {"people": []}}

    made = api.app.queue.submit("group", fn, **{people_routes.OWNER_FIELD: user_of(api, a)})
    assert api.app.queue.wait(made["id"], 10)["status"] == "done"
    base = f"group/{made['id']}"
    want = {f"{base}/pose3d.json", f"{base}/trainer/skeleton.json", f"{base}/person/1/analysis.json",
            f"{base}/person/1/replay.json"}
    names = {}
    for sid in (a, b):
        status, _, data = api.request("GET", "api/me/export.zip", None, cookie(sid))
        assert status == 200
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names[sid] = {n for n in zf.namelist() if n.startswith("group/")}
    assert names[a] == want, "the owner gets the take's outputs, and only the listed ones"
    assert names[b] == set(), "nobody else gets any of them"


def test_din1_delete_waits_while_a_people_job_runs(api: Api, tiny_mp4: Path) -> None:
    import threading

    a = sign_in(api)
    hold = threading.Event()
    made = api.app.queue.submit("people", lambda ctx: hold.wait(10) and {"result": {}},
                                **{people_routes.OWNER_FIELD: user_of(api, a)})
    try:
        status, _, body = post(api, "api/me/delete", {"confirm": "delete"}, cookie=a)
        assert status == 409 and get(api, "api/auth/me", cookie=a)[2]["signed_in"] is True
    finally:
        hold.set()
        api.app.queue.wait(made["id"], 10)


# ----- R4: the movement stays private until captions exist or the sound is gone ------------------------------------
def test_r4_a_trainer_movement_is_published_only_after_narration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state, catalog = tmp_path / "state", tmp_path / "catalog"
    seen: list[Any] = []
    link = entry_access.Link(state, "u-0123456789abcdef01234567", True, deferred=True)
    link.job("abcdef012345")
    on_entry = auth.owned_entry(types.SimpleNamespace(state=state), None, None, link=link)
    monkeypatch.setattr(processor.people, "prepare_clip", lambda ctx, raw, trim, name: raw)
    monkeypatch.setattr(processor.chain, "trainer", lambda *a, **k: {"ok": True, "entry_id": "my-move-0a1b2c3d", "parts": []})
    monkeypatch.setattr(processor.narration, "attach",
                        lambda *a, **k: seen.append(entry_access.visible(state, "my-move-0a1b2c3d", None, None)))
    ctx = types.SimpleNamespace(work=tmp_path / "work", id="abcdef012345", set_stage=lambda s: None, add_note=lambda n: None,
                                set_fields=lambda **f: None)
    fn = processor.trainer_job(tmp_path / "raw.mp4", name="My move", category="exercise", catalog=catalog, on_entry=on_entry)
    assert fn(ctx)["entry_id"] == "my-move-0a1b2c3d"
    assert seen == [False], "a stranger could see the movement while its captions were being made"
    assert entry_access.get(state, "my-move-0a1b2c3d")["published"] is True  # then published, as the upload asked
    assert entry_access.visible(state, "my-move-0a1b2c3d", None, None) is True


def test_r4_without_an_opt_in_the_row_stays_private_after_narration(tmp_path: Path) -> None:
    link = entry_access.Link(tmp_path, "", False, deferred=True)
    link.saved("quiet-move-0a1b2c3d")
    link.ready()
    assert entry_access.get(tmp_path, "quiet-move-0a1b2c3d")["published"] is False


def test_r4_the_take_delete_drops_the_sound_with_the_captions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from part7 import delete_routes

    folder = tmp_path / "catalog" / "voice-move-0a1b2c3d"
    (folder / narration.CLIPS_DIR).mkdir(parents=True)
    (folder / narration.FILE_NAME).write_text("{}")
    dropped: list[Path] = []
    monkeypatch.setattr(delete_routes, "_entry_folder", lambda app, job: ("voice-move-0a1b2c3d", folder))
    monkeypatch.setattr(delete_routes.ghost, "forget", lambda state, entry: False)
    monkeypatch.setattr(delete_routes.narration_own, "drop_audio", lambda entry_dir, job=None: dropped.append(entry_dir) or True)
    removed: list[str] = []
    delete_routes._trainer_entry(types.SimpleNamespace(state=tmp_path), {"id": "j"}, False, removed, [])
    assert removed == ["narration", "sound"] and dropped == [folder]
    assert not (folder / narration.FILE_NAME).exists() and not (folder / narration.CLIPS_DIR).exists()


# ----- R5, R6, R3: the 13 to 17 answer -----------------------------------------------------------------------------
def test_r5_a_minor_band_row_is_never_visible_to_others_whatever_published_says(tmp_path: Path) -> None:
    entry_access.record(tmp_path, "teen-move-0a1b2c3d", owner="u-0123456789abcdef01234567", published=True, age_band="minor")
    row = entry_access.get(tmp_path, "teen-move-0a1b2c3d")
    row["published"] = True  # a row edited by hand, or written before the rule
    (tmp_path / entry_access.FOLDER / "teen-move-0a1b2c3d.json").write_text(json.dumps(row))
    assert entry_access.visible(tmp_path, "teen-move-0a1b2c3d", None, None) is False
    assert entry_access.visible(tmp_path, "teen-move-0a1b2c3d", "u-0123456789abcdef01234567", None) is True  # the owner
    assert entry_access.release(tmp_path, "teen-move-0a1b2c3d", "u-0123456789abcdef01234567") is False


def test_r6_the_13_to_17_answer_outlives_the_job_sweep(api: Api, tiny_mp4: Path) -> None:
    a = sign_in(api)
    user = user_of(api, a)
    store = auth.identity(api.app)
    assert store.is_minor(user) is False
    made = api.app.queue.submit("follow", lambda ctx: {"result": {}}, consent={"age_band": "minor"})
    api.app.queue.wait(made["id"], 10)
    h = types.SimpleNamespace(app=api.app, headers={"Cookie": f"{auth.COOKIE}={a}"}, _entry_link=None)
    auth.attach_job(h, api.app.queue.get(made["id"]))
    assert store.is_minor(user) is True
    api.app.queue.forget(made["id"])  # the 7-day sweep: no job record says 13 to 17 any more
    assert trainer_publish.account_minor(api.app.queue, store, user) is True
    entry_access.record(api.app.state, "adult-move-0a1b2c3d", owner=user, published=False, age_band="adult")
    store.attach_entry("adult-move-0a1b2c3d", user, "")
    assert trainer_publish.publish_refused(api.app, store, "adult-move-0a1b2c3d", user) is True
    status, _, body = post(api, "api/me/entries/adult-move-0a1b2c3d", {"published": True}, cookie=a)
    assert (status, body["error"]) == (403, trainer_publish.MSG_MINOR_PUBLISH)
    rows = get(api, "api/me/entries", cookie=a)[2]["entries"]
    assert [r["may_publish"] for r in rows] == [False]
    on_entry = auth.on_entry(h, None, publish=True)  # a later upload that ticks the box still stays private
    on_entry("later-move-0a1b2c3d")
    assert entry_access.get(api.app.state, "later-move-0a1b2c3d")["published"] is False


def test_r6_the_column_is_added_once_with_a_copy(tmp_path: Path) -> None:
    db = sqlite3.connect(str(tmp_path / "identity.db"))
    db.execute("CREATE TABLE users (user_id TEXT PRIMARY KEY, email TEXT)")
    db.execute("INSERT INTO users VALUES ('u-1', 'a@b.co')")
    db.commit()  # the app's connection runs in autocommit; an open write would hold the backup copy
    assert identity.migrate_age_band(db, tmp_path / "identity.db") is True
    assert identity.migrate_age_band(db, tmp_path / "identity.db") is False
    assert (tmp_path / identity.AGE_BAND_BACKUP).is_file()
    assert db.execute("SELECT age_band FROM users").fetchone()[0] is None


def test_residual1_my_movements_never_call_a_rowless_movement_published(api: Api) -> None:
    a = sign_in(api)
    user = user_of(api, a)
    store = auth.identity(api.app)
    for entry in ("no-row-0a1b2c3d", "public-0a1b2c3d", "lateral-raise"):  # lateral-raise: a shipped sample stand-in
        store.attach_entry(entry, user, "")
    entry_access.record(api.app.state, "public-0a1b2c3d", owner=user, published=True, age_band="adult")
    rows = {r["entry_id"]: r for r in get(api, "api/me/entries", cookie=a)[2]["entries"]}
    assert (rows["no-row-0a1b2c3d"]["published"], rows["no-row-0a1b2c3d"]["hidden"]) == (False, True)
    assert (rows["public-0a1b2c3d"]["published"], rows["public-0a1b2c3d"]["hidden"]) == (True, False)
    assert (rows["lateral-raise"]["published"], rows["lateral-raise"]["hidden"]) == (True, False)
    assert get(api, "catalog/api/entries/no-row-0a1b2c3d", cookie=a)[0] == 404, "hidden from its owner too, as it says"


def test_r3_my_movements_read_the_access_rows_once(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    a = sign_in(api)
    user, store = user_of(api, a), auth.identity(api.app)
    for i in range(5):
        entry = f"move-{i}-0a1b2c3d"
        entry_access.record(api.app.state, entry, owner=user, published=False, age_band="adult")
        store.attach_entry(entry, user, "")
    calls: list[str] = []
    real = entry_access.rows
    monkeypatch.setattr(entry_access, "rows", lambda state: calls.append("rows") or real(state))
    rows = get(api, "api/me/entries", cookie=a)[2]["entries"]
    assert len(rows) == 5 and all(r["may_publish"] for r in rows)
    assert calls == ["rows"], "the account rule is read once per request"


# ----- R2: a checkpoint a reader held is retried by the sweep -----------------------------------------------------
def test_r2_a_checkpoint_kept_from_finishing_is_retried_until_it_succeeds(api: Api, caplog: pytest.LogCaptureFixture) -> None:
    a = sign_in(api)
    store = auth.identity(api.app)
    reader = sqlite3.connect(str(identity.db_path(api.app.state)))
    reader.execute("BEGIN")
    reader.execute("SELECT count(*) FROM users").fetchone()  # holds a snapshot
    store.write("UPDATE users SET last_seen_at = last_seen_at + 1")
    caplog.set_level(logging.INFO, logger="part7")
    assert store.checkpoint(200) is False and store.checkpoint_due is True
    server._sweep_records(api.app)  # still held: tried again, no second line
    assert store.checkpoint_due is True
    assert sum("checkpoint incomplete" in r.getMessage() for r in caplog.records) == 1
    reader.rollback()
    reader.close()
    server._sweep_records(api.app)
    assert store.checkpoint_due is False and any("checkpoint done after a retry" in r.getMessage() for r in caplog.records)
    assert a


# ----- DI-R1: no movement name in a log line -------------------------------------------------------------------------
def test_dir1_log_lines_name_no_movement(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    line = "GET /catalog/api/entries/a-private-raise-e171f111/video.mp4 entry=a-private-raise-e171f111 job bf5f8573d896"
    assert applog.scrub(line) == "GET /catalog/api/entries/<name>-e171f111/video.mp4 entry=<name>-e171f111 job bf5f8573d896"
    for kept in ("123e4567-e89b-12d3-a456-426614174000", "part2 run at c273b198f735", "simon-prod-20261103T141642Z"):
        assert applog.scrub(kept) == kept  # a uuid, a commit and a backup name are not movement ids
    longest = "a" * 40 + "-0a1b2c3d"  # S-R7: Part 6 slugs stop at 40 characters
    assert applog.scrub(longest) == "<name>-0a1b2c3d" and applog.scrub("a" + longest) == "a" + longest
    argv = ["python3", "-m", "part6", "import", "--catalog", "catalog", "--name", "A private raise", "--category", "x"]
    assert "private" not in runner._short_argv(argv) and "--name <name>" in runner._short_argv(argv)
    handler = server.make_handler(types.SimpleNamespace(base="/"))
    fake = types.SimpleNamespace()
    handler.log_message(fake, '"%s" %s', "GET /catalog/api/entries/a-private-raise-e171f111?q=Secret HTTP/1.1", "200")
    err = capsys.readouterr().err
    assert "private" not in err and "Secret" not in err and "<name>-e171f111" in err


def test_dir1_the_part6_log_is_written_through_the_scrub(tmp_path: Path) -> None:
    from part7.parts import p6_catalog

    src = io.BytesIO(b'"GET /catalog/api/entries/a-private-raise-e171f111 HTTP/1.1" 200 -\nplain line\n')
    sink = io.BytesIO()
    p6_catalog._pump(src, sink)
    assert sink.getvalue() == b'"GET /catalog/api/entries/<name>-e171f111 HTTP/1.1" 200 -\nplain line\n'


# ----- a11y R5: the BYOK card's operator line holds the prod start --------------------------------------------------
def test_r5_the_deploy_source_line_blocks_only_while_it_is_a_draft(tmp_path: Path) -> None:
    assert legal_drafts.copy_drafts() == [], "serverless-compute.md AC-SC13: the paused card holds prod start no longer"
    assert not any(p.startswith("served copy is a draft") for p in legal_drafts.problems({}))
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "modal-creds.js").write_text('deployWhere: "[OPERATOR: where]",\n')
    assert legal_drafts.copy_drafts(tmp_path) == [("web/modal-creds.js", 1, False)]
    (tmp_path / "web" / "modal-creds.js").write_text('deployWhere: "From the operator page.",\n')
    assert legal_drafts.copy_drafts(tmp_path) == []
