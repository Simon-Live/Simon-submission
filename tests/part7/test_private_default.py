"""Private by default (docs/prod-verify/private-default.md D1, D3, D4, D6, D8 and the people job owner; docs/specs/
prod-data.md AC-PD15 to AC-PD19, trainer-publish.md AC-TP5).

Real sessions through the sign-in routes, the real identity store, the real queue and the stub Part 6 catalog.
Account A owns a movement; account B is someone else; "anon" sends no cookie.
"""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import types
from typing import Any

import pytest

from auth_support import authenv, claim_doc, get, post, sign_in  # noqa: F401  authenv is a fixture
from part7 import auth, entry_access, identity, impact, judge_view, narration, people_routes, take_access, teacher_stats
from part7 import trainer_publish
from support import Api

pytestmark = pytest.mark.usefixtures("authenv")
OTHER = "grace.hopper@example.com"
MOVE, PUBLIC = "lateral-raise", "skel-only"
ANALYSIS = {"status": {"code": "ok"}, "score": {"value": 70, "grade": "C", "timeline": [{"misses": [{"cue": "Lift higher"}]}]}}


def user_of(api: Api, sid: str) -> str:
    return get(api, "api/auth/me", cookie=sid)[2]["user_id"]


def follow(api: Api, entry: str = MOVE, owner: str | None = None, **record: Any) -> str:
    """A finished, scored follow take of `entry`, owned by `owner` when given; returns its id."""
    def fn(ctx: Any) -> dict[str, Any]:
        (ctx.work / "follower").mkdir(parents=True)
        (ctx.work / "follower" / "analysis.json").write_text(json.dumps(ANALYSIS))
        return {"result": {"entry_id": entry, "score": 70}}

    made = api.app.queue.submit("follow", fn, entry_id=entry, **record)
    assert api.app.queue.wait(made["id"], 10)["status"] == "done"
    if owner:
        auth.identity(api.app).attach(made["id"], owner, "follow", entry, None, "submit")
    return made["id"]


def trainer(api: Api, entry: str, band: str | None = None) -> str:
    """A finished trainer take whose upload answered `band` (none: no answer), with its catalog folder."""
    def fn(ctx: Any) -> dict[str, Any]:
        return {"entry_id": entry, "result": {"entry_id": entry}}

    made = api.app.queue.submit("trainer", fn, **({"consent": {"age_band": band}} if band else {}))
    assert api.app.queue.wait(made["id"], 10)["status"] == "done"
    folder = api.app.child.catalog_dir / entry
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "manifest.json").write_text(json.dumps({"id": entry, "files_source": "import"}), encoding="utf-8")
    api.app.child.entries[entry] = {"id": entry, "animation": None, "skeleton": None}
    return made["id"]


def owned_movement(api: Api, sid: str, entry: str, band: str | None = None) -> str:
    job_id = trainer(api, entry, band)
    assert post(api, "api/me/claims", claim_doc(api, job_id), cookie=sid)[0] == 200
    return job_id


def publish(api: Api, sid: str, entry: str, value: bool) -> tuple[int, Any]:
    status, _, body = post(api, f"api/me/entries/{entry}", {"published": value}, cookie=sid)
    return status, body


def make_private(api: Api, entry: str, owner: str) -> None:
    entry_access.record(api.app.state, entry, owner=owner, published=False)
    auth.identity(api.app).attach_entry(entry, owner, "")


# ----- D1: a 13 to 17 account never publishes ------------------------------------------------------------------
def test_d1_a_movement_made_with_a_13_to_17_answer_never_publishes(api: Api) -> None:
    sid = sign_in(api)
    owned_movement(api, sid, "teen-stretch-1a2b", "minor")
    row = entry_access.get(api.app.state, "teen-stretch-1a2b")
    assert row["age_band"] == "minor" and row["published"] is False  # outside prod the claim would publish; not a minor's
    status, body = publish(api, sid, "teen-stretch-1a2b", True)
    assert (status, body["error"]) == (403, trainer_publish.MSG_MINOR_PUBLISH)
    assert entry_access.get(api.app.state, "teen-stretch-1a2b")["published"] is False
    assert get(api, "catalog/api/entries/teen-stretch-1a2b")[0] == 404  # negative: still hidden from a signed-out caller
    assert publish(api, sid, "teen-stretch-1a2b", False)[0] == 200  # making it private is never refused
    rows = get(api, "api/me/entries", cookie=sid)[2]["entries"]
    assert [r["may_publish"] for r in rows] == [False]


def test_d1_the_refusal_comes_before_any_other_change(api: Api) -> None:
    sid = sign_in(api)
    owned_movement(api, sid, "teen-move-1a2b", "minor")
    status, _, _ = post(api, "api/me/entries/teen-move-1a2b", {"published": True, "only_me": True}, cookie=sid)
    assert status == 403
    assert auth.identity(api.app).entry_owner("teen-move-1a2b")[1] is False  # "only me" was not set by a refused call


def test_d1_an_account_that_answered_13_to_17_once_never_publishes_any_movement(api: Api) -> None:
    sid = sign_in(api)
    owned_movement(api, sid, "adult-move-1a2b", "adult")
    entry_access.set_published(api.app.state, "adult-move-1a2b", False)
    assert publish(api, sid, "adult-move-1a2b", True)[0] == 200  # control: an adult's movement publishes
    entry_access.set_published(api.app.state, "adult-move-1a2b", False)
    owned_movement(api, sid, "teen-move-2c3d", "minor")
    assert publish(api, sid, "adult-move-1a2b", True)[0] == 403
    assert {r["entry_id"]: r["may_publish"] for r in get(api, "api/me/entries", cookie=sid)[2]["entries"]} == {
        "adult-move-1a2b": False, "teen-move-2c3d": False}


def test_d1_a_13_to_17_follow_take_marks_the_account_too(api: Api) -> None:
    sid = sign_in(api)
    owned_movement(api, sid, "adult-move-1a2b", "adult")
    entry_access.set_published(api.app.state, "adult-move-1a2b", False)
    follow(api, PUBLIC, owner=user_of(api, sid), consent={"age_band": "minor"})
    assert publish(api, sid, "adult-move-1a2b", True)[0] == 403
    assert entry_access.get(api.app.state, "adult-move-1a2b")["published"] is False


def test_d1_the_submit_path_writes_a_minor_row_unpublished_even_with_the_opt_in(api: Api) -> None:
    h = types.SimpleNamespace(app=api.app, headers={})
    saved = auth.on_entry(h, None, publish=True)
    job_id = trainer(api, "teen-group-1a2b", "minor")
    auth.attach_job(h, api.app.queue.get(job_id))
    saved("teen-group-1a2b")
    row = entry_access.get(api.app.state, "teen-group-1a2b")
    assert row["age_band"] == "minor" and row["published"] is False and row["trainer_job"] == job_id


def test_d1_in_prod_an_unknown_answer_fails_closed(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    entry_access.record(api.app.state, "old-move-1a2b", owner="u1", published=False)  # no job, no answer
    entry_access.record(api.app.state, "new-move-1a2b", owner="u1", published=False, age_band="adult")
    assert entry_access.publish_refused(api.app.state, "old-move-1a2b", "u1") is False  # outside prod: no answer is fine
    monkeypatch.setenv("FIRM_ENV", "prod")
    assert entry_access.publish_refused(api.app.state, "old-move-1a2b", "u1") is True
    assert entry_access.publish_refused(api.app.state, "new-move-1a2b", "u1") is False


# ----- D3: the teacher page shows a take's row only after its owner shares it ----------------------------------------
def test_d3_take_rows_reach_the_movement_owner_only_after_the_take_owner_shares(api: Api) -> None:
    a, b = sign_in(api), sign_in(api, OTHER)
    auth.identity(api.app).attach_entry(MOVE, user_of(api, a), "")
    job_id = follow(api, owner=user_of(api, b))
    teacher = f"api/teacher/{MOVE}"
    shares = f"{teacher}/shares"
    empty = {"takes": [], "cue_counts": [], "class_table": None, "take_count": 0}
    for sid in (None, b):
        doc = get(api, teacher, cookie=sid)[2]
        assert {k: doc[k] for k in empty} == empty
    assert get(api, teacher, cookie=a)[2]["takes"] == []  # the owner sees nothing before the share
    assert get(api, shares, cookie=b)[2]["takes"] == [{"job_id": job_id, "at": api.app.queue.get(job_id)["finished_at"], "shared": False}]
    assert get(api, shares, cookie=a)[2]["takes"] == []
    assert get(api, shares)[0] == 401
    assert post(api, shares, {"job_id": job_id, "shared": True}, cookie=a)[0] == 404  # not the take's owner
    assert post(api, shares, {"job_id": job_id, "shared": True})[0] == 401
    assert post(api, shares, {"job_id": job_id, "shared": True}, cookie=b, guard=False)[0] == 403  # CSRF guard
    assert post(api, shares, {"job_id": job_id, "shared": "yes"}, cookie=b)[0] == 400
    assert not teacher_stats.shared_with_teacher(api.app.queue.job_dir(job_id))  # negative: nothing above shared it
    assert post(api, shares, {"job_id": job_id, "shared": True}, cookie=b)[2] == {"job_id": job_id, "shared": True}
    owner_view = get(api, teacher, cookie=a)[2]
    assert [(t["score"], t["grade"], t["top_cues"]) for t in owner_view["takes"]] == [(70, "C", ["Lift higher"])]
    assert owner_view["class_table"]["follower_count"] == 1
    for sid in (None, b):  # still no row, time or score for anyone else
        doc = get(api, teacher, cookie=sid)[2]
        assert {k: doc[k] for k in empty} == {**empty, "take_count": 1}
        assert "70" not in json.dumps({k: doc[k] for k in empty})
    assert post(api, shares, {"job_id": job_id, "shared": False}, cookie=b)[0] == 200  # revocable
    assert get(api, teacher, cookie=a)[2]["takes"] == []


SPECS = Path(__file__).resolve().parents[2] / "docs" / "specs"


def _section(name: str, heading: str) -> str:
    text = (SPECS / name).read_text(encoding="utf-8")
    start = text.index(heading)
    end = text.find("\n#", start + len(heading))
    return text[start:end if end != -1 else None]


def test_d3_the_teacher_specs_say_what_prod_data_says() -> None:
    """teacher-dashboard.md and class-table.md "Who sees what" defer to prod-data.md "Teacher page" (D3)."""
    rule = _section("prod-data.md", "## Teacher page")
    assert "class_table: null, take_count" in rule and "shared" in rule
    for name in ("teacher-dashboard.md", "class-table.md"):
        who = _section(name, "### Who sees what")
        assert 'prod-data.md` "Teacher page" (D3' in who and "class_table: null" in who and "take_count" in who
        assert "shared" in who and "seeded" in who
    whole = (SPECS / "teacher-dashboard.md").read_text(encoding="utf-8") + (SPECS / "class-table.md").read_text(encoding="utf-8")
    assert "public by entry id" not in whole and "adds, for everyone" not in whole


def test_d3_a_private_or_other_movement_take_cannot_be_shared(api: Api) -> None:
    b = sign_in(api, OTHER)
    private = follow(api, owner=user_of(api, b), private=True)
    other = follow(api, PUBLIC, owner=user_of(api, b))
    shares = f"api/teacher/{MOVE}/shares"
    assert get(api, shares, cookie=b)[2]["takes"] == []
    assert post(api, shares, {"job_id": private, "shared": True}, cookie=b)[0] == 404
    assert post(api, shares, {"job_id": other, "shared": True}, cookie=b)[0] == 404
    assert post(api, shares, {"job_id": "000000000000", "shared": True}, cookie=b)[0] == 404


# ----- D4: featuring opens nothing --------------------------------------------------------------------------------
def test_d4_a_featured_signed_in_take_stays_its_owners(api: Api) -> None:
    a, b = sign_in(api), sign_in(api, OTHER)
    owned = follow(api, owner=user_of(api, a))
    unowned = follow(api)
    (api.app.state / "hero.json").write_text(json.dumps({"job_id": owned}), encoding="utf-8")
    assert owned in take_access.featured(api.app)
    assert get(api, f"api/jobs/{owned}")[0] == 404 and get(api, f"api/jobs/{owned}", cookie=b)[0] == 404
    assert get(api, f"api/jobs/{owned}", cookie=a)[0] == 200
    assert get(api, f"api/jobs/{unowned}")[0] == 200  # the operator's own (nobody owns it) keeps the job id as its key
    assert take_access.may_feature(api.app.state, owned) is False
    assert take_access.may_feature(api.app.state, unowned) is True
    assert take_access.may_feature(api.app.state, "not-an-id") is False


def _hero_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    """Both meshes and no warning, so only ownership decides whether a named take is featured."""
    monkeypatch.delenv(judge_view.HERO_ENV, raising=False)
    monkeypatch.delenv(impact.ENV, raising=False)
    monkeypatch.setattr(judge_view.mesh_files, "index", lambda root, job_id: {"follower": True, "trainer": True})
    monkeypatch.setattr(judge_view, "_warned", lambda folder, result: False)


def test_d4_the_hero_never_names_an_owned_take(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    _hero_ready(monkeypatch)
    owned, unowned = follow(api, owner=user_of(api, sign_in(api))), follow(api)
    state, jobs_root = api.app.state, api.app.queue.job_dir(owned).parent
    assert judge_view._candidate(state, jobs_root, unowned)["job_id"] == unowned
    assert judge_view._candidate(state, jobs_root, owned) is None
    (state / "hero.json").write_text(json.dumps({"job_id": owned}), encoding="utf-8")
    assert judge_view.hero(state, jobs_root)["job_id"] is None
    assert get(api, "api/judge/hero")[2]["job_id"] is None


def test_d4_the_impact_page_reports_an_owned_take_missing(api: Api, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _hero_ready(monkeypatch)
    owned, unowned = follow(api, owner=user_of(api, sign_in(api))), follow(api)
    rows = [{"persona": "seated", "job_id": owned}, {"persona": "bodies", "job_id": unowned}]
    (api.app.state / impact.STATE_FILE).write_text(json.dumps(rows), encoding="utf-8")
    cards = {c["persona"]: c for c in impact.personas(api.app.state, api.app.queue.job_dir(owned).parent, tmp_path)["personas"]}
    assert cards["seated"]["take"] is None and cards["seated"]["missing"] == "not_found"
    assert cards["bodies"]["take"]["job_id"] == unowned and cards["bodies"]["missing"] is None


def test_d4_may_feature_fails_closed_when_the_store_errs(tmp_path: Path) -> None:
    db = identity.db_path(tmp_path)
    db.parent.mkdir(parents=True, exist_ok=True)
    sqlite3.connect(str(db)).close()  # a store with no takes table answers an error, not "nobody"
    assert take_access.may_feature(tmp_path, "0123456789ab") is False


# ----- D6: boards on private movements and other people's takes ------------------------------------------------
def board(api: Api, entry: str, sid: str | None = None, **more: Any) -> tuple[int, Any]:
    doc = {"entry_id": entry, "title": "Beat me", "creator_name": "Sam", "kind": "friend", **more}
    status, _, body = post(api, "api/challenges", doc, cookie=sid)
    return status, body


def test_d6_a_private_movement_answers_as_a_missing_one_and_its_boards_stay_hidden(api: Api) -> None:
    a, b = sign_in(api), sign_in(api, OTHER)
    make_private(api, MOVE, user_of(api, a))
    missing = board(api, "no-such-move-1a2b")
    assert missing[0] == 404
    for sid in (None, b):
        assert board(api, MOVE, sid) == missing  # the same status and body as an id that does not exist
    status, made = board(api, MOVE, a)
    assert status == 201
    for sid in (None, b):
        rows = get(api, "api/challenges", cookie=sid)[2]["challenges"]
        assert MOVE not in json.dumps(rows)
        assert get(api, f"api/challenges/{made['id']}", cookie=sid)[0] == 404
        assert post(api, f"api/challenges/{made['id']}/entries", {"job_id": "000000000000", "name": "B"}, cookie=sid)[0] == 404
    assert [r["entry_id"] for r in get(api, "api/challenges", cookie=a)[2]["challenges"]] == [MOVE]


def test_d6_only_the_takes_owner_puts_it_on_a_board(api: Api) -> None:
    a, b = sign_in(api), sign_in(api, OTHER)
    take = follow(api, PUBLIC, owner=user_of(api, a))
    status, made = board(api, PUBLIC)
    assert status == 201
    add = f"api/challenges/{made['id']}/entries"
    missing = post(api, add, {"job_id": "000000000000", "name": "B"}, cookie=b)
    for sid in (b, None):
        status, _, body = post(api, add, {"job_id": take, "name": "B"}, cookie=sid)
        assert (status, body["error"]) == (missing[0], missing[2]["error"]) == (404, body["error"])
    assert get(api, f"api/challenges/{made['id']}")[2]["entries"] == []
    assert post(api, add, {"job_id": take, "name": "Ann"}, cookie=a)[0] == 201


# ----- D8: narration follows the movement's visibility ------------------------------------------------------------
def test_d8_narration_and_its_clips_answer_only_who_may_view_the_movement(api: Api) -> None:
    a, b = sign_in(api), sign_in(api, OTHER)
    for entry in (MOVE, PUBLIC):
        folder = api.app.child.catalog_dir / entry
        (folder / narration.CLIPS_DIR).mkdir(parents=True, exist_ok=True)
        (folder / narration.FILE_NAME).write_text(json.dumps({"cues": [{"text": "Lift"}]}), encoding="utf-8")
        (folder / narration.CLIPS_DIR / "cue-1.wav").write_bytes(b"RIFF")
    make_private(api, MOVE, user_of(api, a))
    for sid in (None, b):
        assert get(api, f"api/narration/{MOVE}", cookie=sid)[0] == 404
        assert api.request("GET", f"api/narration/{MOVE}/cue-1.wav", None, {"Cookie": f"{auth.COOKIE}={sid}"} if sid else {})[0] == 404
        assert get(api, f"api/narration/{PUBLIC}", cookie=sid)[0] == 200  # control: a public movement still answers
    assert get(api, f"api/narration/{MOVE}", cookie=a)[0] == 200
    assert api.request("GET", f"api/narration/{MOVE}/cue-1.wav", None, {"Cookie": f"{auth.COOKIE}={a}"})[0] == 200


# ----- people jobs: only the caller's own -------------------------------------------------------------------------
def people_job(api: Api, owner: str | None) -> str:
    def fn(ctx: Any) -> dict[str, Any]:
        (ctx.work / "clip.mp4").write_bytes(b"clip")
        (ctx.work / "tracks.json").write_text("{}")
        (ctx.dir / "people").mkdir(exist_ok=True)
        (ctx.dir / "people" / "frame.jpg").write_bytes(b"jpeg")
        return {"result": {"people": [{"id": "1"}, {"id": "2"}], "auto_id": "1"}}

    record = {} if owner is None else {people_routes.OWNER_FIELD: owner}
    made = api.app.queue.submit("people", fn, **record)
    assert api.app.queue.wait(made["id"], 10)["status"] == "done"
    return made["id"]


def _handler(api: Api, sid: str | None) -> Any:
    errors: list[tuple[int, str]] = []
    h = types.SimpleNamespace(app=api.app, headers={"Cookie": f"{auth.COOKIE}={sid}"} if sid else {},
                              _error=lambda status, message, **_: errors.append((status, message)))
    return h, errors


def test_people_a_person_or_group_take_accepts_only_the_callers_own_people_job(api: Api) -> None:
    a, b = sign_in(api), sign_in(api, OTHER)
    mine = people_job(api, user_of(api, a))
    assert people_routes.OWNER_FIELD not in json.dumps(get(api, f"api/jobs/{mine}", cookie=a)[2])  # never in an answer
    for sid in (b, None):
        h, errors = _handler(api, sid)
        assert people_routes.selection(h, {"people_job": mine, "person_id": "1"}) == (False, None)
        assert errors == [(400, people_routes.MSG_PEOPLE_GONE)]
        status, _, body = post(api, "api/group", {"name": "Class", "category": "dance", "people_job": mine}, cookie=sid)
        assert (status, body["error"]) == (400, people_routes.MSG_PEOPLE_GONE)
        assert api.request("GET", f"api/jobs/{mine}/people/frame.jpg", None, {"Cookie": f"{auth.COOKIE}={sid}"} if sid else {})[0] == 404
    h, errors = _handler(api, a)
    ok, sel = people_routes.selection(h, {"people_job": mine, "person_id": "1"})
    assert ok and sel.id == "1" and errors == []
    status, _, body = post(api, "api/group", {"name": "Class", "category": "dance", "people_job": mine}, cookie=a)
    assert (status, body["error"]) == (400, people_routes.MSG_FOLLOWERS)  # past the owner check
    assert api.request("GET", f"api/jobs/{mine}/people/frame.jpg", None, {"Cookie": f"{auth.COOKIE}={a}"})[0] == 200


def test_people_a_signed_out_job_keeps_its_id_as_its_key_and_an_unmarked_one_is_refused(api: Api) -> None:
    b = sign_in(api, OTHER)
    anon, legacy = people_job(api, ""), people_job(api, None)
    for sid in (None, b):
        h, errors = _handler(api, sid)
        assert people_routes.selection(h, {"people_job": anon})[0] is True
        assert people_routes.selection(h, {"people_job": legacy}) == (False, None)
        assert errors == [(400, people_routes.MSG_PEOPLE_GONE)]
