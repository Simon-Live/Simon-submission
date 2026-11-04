"""Auth-social fixes found by the QA rehearsal: the profile answer carries entries, movements and the per-group summary
(TICKET-231 AC-5, AC-6), the entry author line has its own light route (TICKET-232 AC-3), a share keeps only the ticked
parts (TICKET-233 AC-2, AC-11) and the viewer answers send Referrer-Policy once."""

from __future__ import annotations

import http.client
import json
from pathlib import Path
from typing import Any

import pytest

from auth_support import authenv, get, post, sign_in  # noqa: F401
from history_support import ENTRY as SQUAT, FIRST, SECOND
from part7 import auth, history_store, share, teacher_stats
from support import Api
from test_history_facts import KNOWN, _made, _real
from test_share import ENTRY, make_share, owned_job, share_body, store

pytestmark = pytest.mark.usefixtures("authenv")


def raw_headers(api: Api, path: str, cookie: str | None = None) -> list[tuple[str, str]]:
    conn = http.client.HTTPConnection("127.0.0.1", api.port, timeout=30)
    conn.request("GET", api.app.base + path, headers={"Cookie": f"{auth.COOKIE}={cookie}"} if cookie else {})
    resp = conn.getresponse()
    resp.read()
    out = [(k.lower(), v) for k, v in resp.getheaders()]
    conn.close()
    return out


def guard(api: Api, sid: str | None = None, origin: bool = True) -> dict[str, str]:
    head = {"Content-Type": "application/json"}
    if origin:
        head["Origin"] = f"http://127.0.0.1:{api.port}"
    if sid:
        head["Cookie"] = f"{auth.COOKIE}={sid}"
    return head


def user_id(api: Api, sid: str) -> str:
    return get(api, "api/auth/me", cookie=sid)[2]["user_id"]


# ----- bug 6: Referrer-Policy once ---------------------------------------------------------------------------------
def test_referrer_policy_is_sent_once_on_share_and_auth_routes(api: Api) -> None:
    sid = sign_in(api)
    token = make_share(api, sid, owned_job(api, sid))
    for path in (f"api/shared/{token}", "api/shared/nope", "api/auth/me", "api/me/profile"):
        names = [k for k, _ in raw_headers(api, path, sid)]
        assert names.count("referrer-policy") == 1, (path, names)


# ----- bug 3: entries on the profile answer ------------------------------------------------------------------------
def test_profile_answer_lists_only_the_owners_entries(api: Api) -> None:
    sid, other = sign_in(api), sign_in(api, "grace@example.com")
    auth.identity(api.app).attach_entry(ENTRY, user_id(api, sid))
    body = get(api, "api/me/profile", cookie=sid)[2]
    assert [e["entry_id"] for e in body["entries"]] == [ENTRY]
    assert set(body["entries"][0]) >= {"entry_id", "name", "count", "last_at"}
    assert get(api, "api/me/profile", cookie=other)[2]["entries"] == []  # negative: another account never sees them
    assert get(api, "api/me/profile")[0] == 401
    assert "example.com" not in json.dumps(body)


def test_entry_count_and_date_ignore_private_takes(api: Api) -> None:
    sid = sign_in(api)
    auth.identity(api.app).attach_entry(ENTRY, user_id(api, sid))
    job = owned_job(api, sid)
    analysis = api.app.state / "jobs" / job / "work" / "follower" / "analysis.json"
    analysis.write_text(json.dumps({**json.loads(analysis.read_text()), "status": {"code": "ok"}}))  # the teacher page counts finished, scored takes
    assert get(api, "api/me/profile", cookie=sid)[2]["entries"][0]["count"] == 0  # not shared yet (private-default D3)
    teacher_stats.set_shared(analysis.parents[2], True)
    assert get(api, "api/me/profile", cookie=sid)[2]["entries"][0]["count"] == 1
    path = api.app.state / "jobs" / job / "job.json"
    path.write_text(json.dumps({**json.loads(path.read_text()), "private": True}))
    entry = get(api, "api/me/profile", cookie=sid)[2]["entries"][0]
    assert entry["count"] == 0 and entry["last_at"] is None


# ----- bug 3: the per-group summary (AC-6) -------------------------------------------------------------------------
def summary_module() -> Any:
    from part7 import profile_summary

    return profile_summary


def real_rows() -> list[dict[str, Any]]:
    first, second = _real(FIRST, 1), _real(SECOND, 2)
    first.update(score=100, grade="A", at="2026-11-01T10:00:00Z")
    second.update(score=77, grade="C", at="2026-11-01T11:00:00Z")
    return [first, second]


def test_summary_groups_like_with_like_with_first_and_latest_score(tmp_path: Path) -> None:
    other = {**_made(tmp_path, 1, 50, [], mode="rehab"), "at": "2026-11-01T09:00:00Z"}
    groups = summary_module().groups({SQUAT: real_rows(), "other": [other]})
    by = {(g["section"], g["mode"]): g for g in groups}
    assert set(by) == {("full", "fitness"), ("full", "rehab")}  # a different mode is never mixed in
    g = by[("full", "fitness")]
    assert (g["takes"], g["movements"], g["first_score"], g["latest_score"], g["score_version"]) == (2, 1, 100, 77, KNOWN["score_version"])
    assert isinstance(g["came_back"], int) and g["came_back"] >= 0
    rehab = by[("full", "rehab")]
    assert rehab["takes"] == 1 and rehab["first_score"] == rehab["latest_score"] == 50


def test_summary_groups_round_trip_through_json_with_only_the_public_fields(tmp_path: Path) -> None:
    # staging 785f447: GET api/me/profile crashed with "Object of type set is not JSON serializable" (the
    # working set of entry ids leaked into each group). Every field must survive json, and no working field is sent.
    other = {**_made(tmp_path, 1, 50, [], mode="rehab"), "at": "2026-11-01T09:00:00Z"}
    groups = summary_module().groups({SQUAT: real_rows(), "other": [other]})
    assert groups and json.loads(json.dumps(groups)) == groups
    for g in groups:
        assert set(g) == {"section", "mode", "score_version", "takes", "came_back", "movements", "first_score", "latest_score"}


def test_profile_answer_with_kept_takes_round_trips_through_json(api: Api, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    other = {**_made(tmp_path, 1, 50, [], mode="rehab"), "at": "2026-11-01T09:00:00Z"}
    by_entry = {SQUAT: real_rows(), "other": [other]}
    mod = summary_module()
    monkeypatch.setattr(mod.history_store, "retention_opt_in", lambda *_: True)
    monkeypatch.setattr(mod.history_store, "entries", lambda *_: list(by_entry))
    monkeypatch.setattr(mod.history_store, "takes", lambda _s, _u, e: by_entry[e])
    out = mod.summary(object(), "u")
    assert out["kept"] is True and len(out["groups"]) == 2
    assert json.loads(json.dumps(out)) == out


def test_summary_leaves_private_and_unknown_group_takes_out(tmp_path: Path) -> None:
    rows = real_rows()
    rows[1]["private"] = True
    unknown = _made(tmp_path, 3, 60, [], section_key=None)
    groups = summary_module().groups({SQUAT: rows + [unknown]})
    assert [(g["takes"], g["latest_score"]) for g in groups] == [(1, 100)]


def test_summary_two_score_versions_stay_apart(tmp_path: Path) -> None:
    a = {**_made(tmp_path, 1, 70, []), "at": "2026-11-01T09:00:00Z"}
    b = {**_made(tmp_path, 2, 80, [], score_version="simon.score.v3:00000000"), "at": "2026-11-01T10:00:00Z"}
    assert len(summary_module().groups({"x": [a, b]})) == 2


def test_summary_counts_came_back_from_the_fact_table(tmp_path: Path) -> None:
    fault = [("knee_valgus", "left", 1.0, 20.0)]
    takes = [_made(tmp_path, 1, 60, fault), _made(tmp_path, 2, 80, []), _made(tmp_path, 3, 62, fault)]
    for n, t in enumerate(takes):
        t["at"] = f"2026-11-01T1{n}:00:00Z"
    group = summary_module().groups({"x": takes})[0]
    assert group["takes"] == 3 and group["came_back"] == 1


def test_profile_summary_says_nothing_was_kept_when_retention_is_off(api: Api) -> None:
    sid = sign_in(api)
    assert get(api, "api/me/profile", cookie=sid)[2]["summary"] == {"kept": False, "groups": [], "capped": False}  # not zeros


def test_profile_summary_is_kept_when_retention_is_on(api: Api) -> None:
    sid = sign_in(api)
    assert post(api, "api/me/consent", {"retention": True, "version": "t1"}, cookie=sid)[0] == 200
    body = get(api, "api/me/profile", cookie=sid)[2]
    assert body["summary"] == {"kept": True, "groups": [], "capped": False} and body["movements"] == []


# ----- bug 4: the entry author line without the teacher stats ------------------------------------------------------
def test_entry_attribution_route_credits_only_an_opted_in_trainer(api: Api) -> None:
    sid = sign_in(api)
    auth.identity(api.app).attach_entry(ENTRY, user_id(api, sid))
    put = lambda doc: api.request("PUT", "api/me/profile", json.dumps(doc).encode(), guard(api, sid))[0]  # noqa: E731
    assert put({"public_name": "Trainer Ada", "show_name": True}) == 200
    quiet = get(api, f"api/teacher/{ENTRY}/author")  # a signed out viewer
    assert quiet[0] == 200 and quiet[2]["attribution"]["author"]["name"] is None  # credit_me_as_trainer is off
    assert put({"credit_me_as_trainer": True}) == 200
    credited = get(api, f"api/teacher/{ENTRY}/author")[2]["attribution"]
    assert credited["author"]["name"] == "Trainer Ada" and "example.com" not in json.dumps(credited)
    assert get(api, "api/teacher/nope/author")[0] == 404


def test_entry_attribution_route_unattributed_entry_has_no_author(api: Api) -> None:
    assert get(api, f"api/teacher/{ENTRY}/author")[2]["attribution"]["author"] is None


# ----- bug 8: ticks for score and faults, enforced by the server ----------------------------------------------------
def test_share_keeps_only_the_ticked_parts(api: Api) -> None:
    sid = sign_in(api)
    job = owned_job(api, sid)
    both = get(api, f"api/shared/{make_share(api, sid, job)}")[2]  # defaults: score on, faults on
    assert both["score"] == 81 and both["faults"] and both["include"] == {"score": True, "faults": True}
    no_faults = get(api, f"api/shared/{make_share(api, sid, job, include_faults=False)}")[2]
    assert no_faults["score"] == 81 and not no_faults.get("faults")
    no_score = get(api, f"api/shared/{make_share(api, sid, job, include_score=False)}")[2]
    assert no_score.get("score") is None and no_score.get("grade") is None and no_score["faults"]
    token = make_share(api, sid, job, include_score=False, include_faults=False)
    bare = get(api, f"api/shared/{token}")[2]
    assert bare.get("score") is None and not bare.get("faults") and bare["title"] == ENTRY
    row = store(api).fetch("SELECT snapshot FROM shares WHERE token_hash = ?", (share.token_hash(token),))[0]
    assert "leaning forward" not in row["snapshot"] and '"score":81' not in row["snapshot"]  # negative: not stored either


def test_share_ticks_must_be_booleans(api: Api) -> None:
    sid = sign_in(api)
    assert post(api, "api/shares", share_body(owned_job(api, sid), include_score="no"), cookie=sid)[0] == 400


# ----- bug 9 and 10: created date on the list, revoke all ----------------------------------------------------------
def test_share_list_has_created_and_revoke_all_ends_every_link(api: Api) -> None:
    sid, other = sign_in(api), sign_in(api, "grace@example.com")
    job = owned_job(api, sid)
    tokens = [make_share(api, sid, job) for _ in range(3)]
    theirs = make_share(api, other, owned_job(api, other))
    listed = get(api, "api/me/shares", cookie=sid)[2]["shares"]
    assert len(listed) == 3 and all(r["created_utc"] for r in listed)
    assert api.request("DELETE", "api/me/shares", b"{}", guard(api, sid, origin=False))[0] == 403  # CSRF guard
    status, _, data = api.request("DELETE", "api/me/shares", b"{}", guard(api, sid))
    assert status == 200 and json.loads(data)["revoked"] == 3
    assert [get(api, f"api/shared/{t}")[0] for t in tokens] == [410, 410, 410]
    assert get(api, f"api/shared/{theirs}")[0] == 200  # negative: another person's link is untouched
    assert api.request("DELETE", "api/me/shares", b"{}", guard(api))[0] == 401


# ----- bug 5: the owner's preview is the snapshot the viewer gets ---------------------------------------------------
def test_preview_is_what_the_viewer_gets_and_stores_nothing(api: Api) -> None:
    sid = sign_in(api)
    job = owned_job(api, sid)
    body = share_body(job, include_faults=False)
    status, _, preview = post(api, "api/shares/preview", body, cookie=sid)
    assert status == 200
    assert not store(api).has_table("shares")  # nothing was made
    viewer = get(api, f"api/shared/{make_share(api, sid, job, include_faults=False)}")[2]
    for key in ("title", "score", "grade", "author", "attribution", "include", "kind"):
        assert preview.get(key) == viewer.get(key), key
    assert preview["title"] == ENTRY and "faults" not in preview  # the movement name, not a placeholder
    assert post(api, "api/shares/preview", body)[0] == 401
    assert post(api, "api/shares/preview", body, cookie=sign_in(api, "grace@example.com"))[0] == 404  # negative: not another person's take


# ----- the 200-take cap is said, not hidden ---------------------------------------------------------------------------
def test_summary_says_when_entry_counts_hit_the_take_cap(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    from part7 import teacher_stats

    sid = sign_in(api)
    auth.identity(api.app).attach_entry(ENTRY, user_id(api, sid))
    for _ in range(2):
        job = owned_job(api, sid)
        analysis = api.app.state / "jobs" / job / "work" / "follower" / "analysis.json"
        analysis.write_text(json.dumps({**json.loads(analysis.read_text()), "status": {"code": "ok"}}))
        teacher_stats.set_shared(analysis.parents[2], True)  # counted once shared (private-default D3)
    monkeypatch.setattr(teacher_stats, "TAKES_MAX", 3)
    below = get(api, "api/me/profile", cookie=sid)[2]
    assert below["entries"][0]["count"] == 2 and below["summary"]["capped"] is False  # negative: under the cap, no flag
    monkeypatch.setattr(teacher_stats, "TAKES_MAX", 2)
    at = get(api, "api/me/profile", cookie=sid)[2]
    assert at["entries"][0]["count"] == 2 and at["summary"]["capped"] is True


# ----- freeze fix: the profile answer with real groups (staging 500, "Object of type set is not JSON serializable") --
def _seed_variant(api: Api, source: str, job_id: str, **fields: Any) -> str:
    """A finished follow job copied from a real fixture (history_support.FIXTURES) under a new id, some job fields changed."""
    from history_support import FIXTURES

    folder = api.app.state / "jobs" / job_id / "work" / "follower"
    folder.mkdir(parents=True)
    record = {**json.loads((FIXTURES / source / "job.json").read_text()), "id": job_id, **fields}
    (folder.parents[1] / "job.json").write_text(json.dumps(record))
    (folder / "analysis.json").write_text((FIXTURES / source / "analysis.json").read_text())
    return job_id


def test_profile_answer_with_takes_in_several_movements_and_groups_is_json(api: Api) -> None:
    sid = sign_in(api)
    assert post(api, "api/me/consent", {"retention": True, "version": "t1"}, cookie=sid)[0] == 200
    jobs = [_seed_variant(api, FIRST, FIRST), _seed_variant(api, SECOND, SECOND),
            _seed_variant(api, FIRST, "a1b2c3d4e5f6", mode="rehab", finished_at="2026-11-01T09:00:00Z"),
            _seed_variant(api, SECOND, "0a1b2c3d4e5f", entry_id="lateral-raise", finished_at="2026-11-01T10:00:00Z")]
    uid, store = user_id(api, sid), auth.identity(api.app)
    for job in jobs:  # the claim route's own steps for jobs found on disk (the queue only lists the jobs it ran)
        record = json.loads((api.app.state / "jobs" / job / "job.json").read_text())
        assert store.attach(job, uid, "follow", record["entry_id"], None, "claim")
        assert history_store.claim(api.app.state, uid, job)
    status, _, body = get(api, "api/me/profile", cookie=sid)
    assert status == 200, body  # a set in a group made this a 500
    assert sorted(m["entry_id"] for m in body["movements"]) == ["body-squat-19b06562", "lateral-raise"]
    groups = body["summary"]["groups"]
    by = {(g["mode"], g["section"]): g for g in groups}
    assert set(by) == {("fitness", "full"), ("rehab", "full")}
    assert by[("fitness", "full")]["takes"] == 3 and by[("fitness", "full")]["movements"] == 2
    assert all("entries" not in g and "scored" not in g for g in groups)  # negative: no working field leaks out
