"""Challenges: store, routes, server-side score read, limits and the operator CLI (docs/specs/challenges.md)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any

import pytest

from part7 import challenge_cli, challenges, cli, client_log, group
from support import Api

VISITOR = {"Cf-Connecting-Ip": "198.51.100.7"}
SPONSOR = {"name": "Example Sportswear", "tagline": "Move more", "url": "https://example.com/shop", "prize": "A pair of shoes"}


def _timeline(basis: str = "windows") -> dict[str, Any]:
    return {"value": 80, "grade": "B", "basis": basis, "timeline": [
        {"t_s": [0, 5], "compared": True, "value": 70, "grade": "C"},
        {"t_s": [5, 10], "compared": True, "value": 92, "grade": "A"},
        {"t_s": [10, 15], "compared": True, "value": 92, "grade": "A"},
        {"t_s": [15, 20], "compared": False, "value": 99, "grade": "A"},
    ]}


def _analysis(score: Any = None, code: str = "ok") -> dict[str, Any]:
    return {"status": {"code": code}, "score": score if score is not None else _timeline(), "faults": []}


def _job(api: Api, job_id: str, entry_id: str = "lateral-raise", analysis: Any = None, **record: Any) -> str:
    """A finished solo follow job with its analysis.json on disk."""
    folder = api.app.queue.job_dir(job_id) / "work" / "follower"
    folder.mkdir(parents=True)
    (folder / "analysis.json").write_text(json.dumps(analysis or _analysis()), encoding="utf-8")
    api.app.queue._jobs[job_id] = {"id": job_id, "kind": "follow", "status": "done", "entry_id": entry_id,
                                   "stages": [], "note": None, **record}
    return job_id


def _group_job(api: Api, job_id: str, scores: dict[str, Any], entry_id: str = "lateral-raise") -> str:
    people = [{"id": pid, "label": f"P{pid}", "score": 50} for pid in scores]
    api.app.queue._jobs[job_id] = {"id": job_id, "kind": "group", "status": "done", "entry_id": entry_id,
                                   "stages": [], "note": None, "result": {"entry_id": entry_id, "people": people}}
    for pid, analysis in scores.items():
        folder = group.person_dir(api.app.queue.job_dir(job_id), pid)
        folder.mkdir(parents=True)
        (folder / "analysis.json").write_text(json.dumps(analysis), encoding="utf-8")
    return job_id


def _create(api: Api, **over: Any) -> dict[str, Any]:
    body = {"entry_id": "lateral-raise", "title": "Beat my raises", "creator_name": "Sam", "kind": "friend", **over}
    status, doc = api.json("POST", "api/challenges", body, VISITOR)
    assert status == 201, doc
    return doc


def _sponsored(api: Api, **over: Any) -> dict[str, Any]:
    return challenges.create(
        api.app.state, entry_id="lateral-raise", title="Raise the roof", creator_name="Example Sportswear",
        kind="sponsored", sponsor=SPONSOR, allow_sponsored=True, **over)


def _add(api: Api, cid: str, **body: Any) -> tuple[int, Any]:
    return api.json("POST", f"api/challenges/{cid}/entries", body, VISITOR)


# ----- store ------------------------------------------------------------------------------------------------
def test_strongest_section_is_the_best_compared_window_ties_to_the_earliest() -> None:
    found = challenges.strongest_section(_timeline())
    assert found == {"label": "5.0 s to 10.0 s", "value": 92, "t_s": [5, 10]}  # the 99 window was not compared
    assert challenges.strongest_section(_timeline("reps"))["label"] == "Rep 2"


def test_strongest_section_none_without_a_usable_timeline() -> None:
    assert challenges.strongest_section({"value": 80}) is None
    assert challenges.strongest_section({"timeline": []}) is None
    assert challenges.strongest_section({"timeline": [{"t_s": [0, 1], "compared": False, "value": 5}, "x", {"value": 3}]}) is None


def test_ranking_orders_by_score_then_earliest_post() -> None:
    board = challenges.ranked([
        {"name": "b", "score": 80, "created_at": "2026-01-01T00:00:02Z"},
        {"name": "a", "score": 80, "created_at": "2026-01-01T00:00:01Z"},
        {"name": "c", "score": 95, "created_at": "2026-01-01T00:00:09Z"}])
    assert [(e["rank"], e["name"]) for e in board] == [(1, "c"), (2, "a"), (3, "b")]


def test_files_are_written_atomically_and_survive_job_pruning(api: Api) -> None:
    made = _create(api)
    folder = api.app.state / "challenges"
    assert sorted(p.name for p in folder.iterdir()) == [".lock", f"{made['id']}.json"]  # the lock file, no temp file left behind
    assert api.app.queue.cleanup(now=10 ** 12) == 0 and (folder / f"{made['id']}.json").is_file()


def test_clean_name_trims_and_refuses() -> None:
    assert challenges.clean_name("  Sam \n  Lee ") == "Sam Lee"  # runs of white space become one space
    for bad in ("", "   ", "x" * 25, "a\x00b", 5, None):
        with pytest.raises(challenges.ChallengeError):
            challenges.clean_name(bad)


@pytest.mark.parametrize("url", ["http://example.com", "javascript:alert(1)", "https://", "example.com", "https://a b.com", "", 5])
def test_sponsor_link_must_be_https(url: Any) -> None:
    with pytest.raises(challenges.ChallengeError):
        challenges.clean_sponsor({**SPONSOR, "url": url})


# ----- routes: create -----------------------------------------------------------------------------------------
def test_create_returns_a_url_safe_id_and_an_empty_board(api: Api) -> None:
    made = _create(api, kind="crew")
    assert challenges.ID_RE.match(made["id"]) and made["kind"] == "crew" and made["entries"] == []
    assert made["sponsor"] is None and made["ends_at"] is None and made["ended"] is False
    assert made["entry_id"] == "lateral-raise" and made["creator_name"] == "Sam"


@pytest.mark.parametrize("over,status", [
    ({"kind": "sponsored"}, 400), ({"sponsor": SPONSOR}, 400), ({"ends_at": "2999-01-01T00:00:00Z"}, 400),
    ({"kind": "party"}, 400), ({"title": ""}, 400), ({"title": "x" * 61}, 400), ({"creator_name": " "}, 400),
    ({"entry_id": "../x"}, 400), ({"entry_id": "no-such-movement"}, 404), ({"entry_id": None}, 400),
])
def test_create_refusals(api: Api, over: dict[str, Any], status: int) -> None:
    body = {"entry_id": "lateral-raise", "title": "T", "creator_name": "Sam", "kind": "friend", **over}
    assert api.json("POST", "api/challenges", body, VISITOR)[0] == status
    assert list((api.app.state / "challenges").glob("*.json")) == []  # nothing was stored


def test_public_cannot_set_a_sponsor_on_any_route(api: Api) -> None:
    status, doc = api.json("POST", "api/challenges", {"entry_id": "lateral-raise", "title": "T", "creator_name": "S",
                                                      "kind": "friend", "sponsor": SPONSOR}, VISITOR)
    assert status == 400 and "operator" in doc["error"]


def test_bad_bodies_and_sizes(api: Api) -> None:
    assert api.request("POST", "api/challenges", b"not json", {"Content-Length": "8"})[0] == 400
    assert api.request("POST", "api/challenges", b"[]", {})[0] == 400
    big = json.dumps({"entry_id": "lateral-raise", "title": "x" * 9000}).encode()
    assert api.request("POST", "api/challenges", big, {"Content-Type": "application/json"})[0] == 413


def test_wrong_methods_are_405_and_unknown_paths_404(api: Api) -> None:
    assert api.request("DELETE", "api/challenges")[0] == 405
    assert api.request("POST", "api/challenges/abcdefgh")[0] == 405
    assert api.request("GET", "api/challenges/abcdefgh/entries")[0] == 405
    assert api.request("GET", "api/challenges/a/b/c")[0] == 404


# ----- routes: read -----------------------------------------------------------------------------------------
def test_get_one_and_missing(api: Api) -> None:
    made = _create(api)
    status, doc = api.json("GET", f"api/challenges/{made['id']}")
    assert status == 200 and doc["title"] == "Beat my raises"
    assert api.json("GET", "api/challenges/nosuchid1")[0] == 404
    assert api.json("GET", "api/challenges/bad!id")[0] == 404


def test_list_filters_by_entry_and_kind_newest_first(api: Api) -> None:
    first = _create(api, title="One")
    second = _create(api, title="Two", kind="crew")
    api.app.child.entries["other"] = {"id": "other"}
    third = _create(api, entry_id="other", title="Three")
    _sponsored(api)
    ids = lambda q: [c["id"] for c in api.json("GET", f"api/challenges{q}")[1]["challenges"]]  # noqa: E731
    assert len(ids("")) == 4
    assert set(ids("?entry_id=lateral-raise")) == {first["id"], second["id"], _only(api, "sponsored")}
    assert ids("?entry_id=other") == [third["id"]]
    assert ids("?kind=crew") == [second["id"]]
    assert api.json("GET", "api/challenges?kind=zzz")[0] == 400
    assert api.json("GET", "api/challenges?entry_id=A/B")[0] == 400


def _only(api: Api, kind: str) -> str:
    rows = api.json("GET", f"api/challenges?kind={kind}")[1]["challenges"]
    assert len(rows) == 1
    return rows[0]["id"]


# ----- routes: entries ---------------------------------------------------------------------------------------
def test_entry_score_is_read_by_the_server_and_a_client_score_is_ignored(api: Api) -> None:
    made = _create(api)
    job = _job(api, "aaaaaaaaaaaa")
    status, doc = _add(api, made["id"], job_id=job, name="  Sam ", score=100, grade="A", strongest_section={"label": "x"})
    assert status == 201, doc
    entry = doc["entries"][0]
    assert (entry["name"], entry["score"], entry["grade"]) == ("Sam", 80, "B")
    assert "job_id" not in entry and "pid" not in entry  # public views never name the job (kept on disk)
    assert challenges.get(api.app.state, made["id"])["entries"][0]["job_id"] == job
    assert entry["strongest_section"]["label"] == "5.0 s to 10.0 s" and entry["rank"] == 1
    assert doc["added"][0]["name"] == "Sam" and "created_at" in entry


def test_the_board_keeps_its_entries_after_the_job_is_gone(api: Api) -> None:
    made = _create(api)
    job = _job(api, "aaaaaaaaaaaa")
    _add(api, made["id"], job_id=job, name="Sam")
    del api.app.queue._jobs[job]
    entries = api.json("GET", f"api/challenges/{made['id']}")[1]["entries"]
    assert [(e["name"], e["score"]) for e in entries] == [("Sam", 80)]


def test_entry_without_a_timeline_has_no_strongest_section(api: Api) -> None:
    made = _create(api)
    job = _job(api, "aaaaaaaaaaaa", analysis=_analysis({"value": 64, "grade": "D"}))
    assert _add(api, made["id"], job_id=job, name="Sam")[1]["entries"][0]["strongest_section"] is None


@pytest.mark.parametrize("body,status", [
    ({"name": "Sam"}, 400), ({"job_id": "nope", "name": "Sam"}, 400), ({"job_id": "bbbbbbbbbbbb", "name": "Sam"}, 404),
    ({"job_id": "aaaaaaaaaaaa", "name": ""}, 400), ({"job_id": "aaaaaaaaaaaa", "name": "y" * 25}, 400),
    ({"job_id": "aaaaaaaaaaaa", "pid": "1", "name": "Sam"}, 400), ({"job_id": "aaaaaaaaaaaa"}, 400),
])
def test_entry_refusals(api: Api, body: dict[str, Any], status: int) -> None:
    made = _create(api)
    _job(api, "aaaaaaaaaaaa")
    assert _add(api, made["id"], **body)[0] == status
    assert api.json("GET", f"api/challenges/{made['id']}")[1]["entries"] == []


def test_entry_for_a_different_movement_is_409(api: Api) -> None:
    made = _create(api)
    job = _job(api, "aaaaaaaaaaaa", entry_id="skel-only")
    status, doc = _add(api, made["id"], job_id=job, name="Sam")
    assert status == 409 and "different movement" in doc["error"]


def test_entry_from_an_unfinished_or_unscored_job_is_409(api: Api) -> None:
    made = _create(api)
    running = _job(api, "aaaaaaaaaaaa")
    api.app.queue._jobs[running]["status"] = "running"
    assert _add(api, made["id"], job_id=running, name="Sam")[0] == 409
    refused = _job(api, "cccccccccccc", analysis=_analysis(None, code="different_movement") | {"score": None})
    assert _add(api, made["id"], job_id=refused, name="Sam")[0] == 409
    low = _job(api, "dddddddddddd", analysis=_analysis(code="low_match"))
    assert _add(api, made["id"], job_id=low, name="Sam")[0] == 409


def test_unreadable_analysis_is_404(api: Api) -> None:
    made = _create(api)
    job = _job(api, "aaaaaaaaaaaa")
    (api.app.queue.job_dir(job) / "work" / "follower" / "analysis.json").write_text("{nope", encoding="utf-8")
    assert _add(api, made["id"], job_id=job, name="Sam")[0] == 404


def test_the_same_result_cannot_be_added_twice(api: Api) -> None:
    made = _create(api)
    job = _job(api, "aaaaaaaaaaaa")
    assert _add(api, made["id"], job_id=job, name="Sam")[0] == 201
    status, doc = _add(api, made["id"], job_id=job, name="Sam again")
    assert status == 409 and "already" in doc["error"]
    assert len(api.json("GET", f"api/challenges/{made['id']}")[1]["entries"]) == 1


def test_an_ended_challenge_rejects_entries_but_stays_readable(api: Api) -> None:
    doc = _sponsored(api, ends_at=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat())
    job = _job(api, "aaaaaaaaaaaa")
    assert _add(api, doc["id"], job_id=job, name="Sam")[0] == 201
    challenges.close(api.app.state, doc["id"])
    status, err = _add(api, doc["id"], job_id=_job(api, "eeeeeeeeeeee"), name="Late")
    assert status == 409 and err["error"] == challenges.MSG_ENDED
    board = api.json("GET", f"api/challenges/{doc['id']}")[1]
    assert board["ended"] is True and len(board["entries"]) == 1


def test_entry_on_a_missing_challenge_is_404(api: Api) -> None:
    job = _job(api, "aaaaaaaaaaaa")
    assert _add(api, "nosuchid1", job_id=job, name="Sam")[0] == 404


def test_a_full_board_is_409(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(challenges, "MAX_ENTRIES", 1)
    made = _create(api)
    assert _add(api, made["id"], job_id=_job(api, "aaaaaaaaaaaa"), name="A")[0] == 201
    assert _add(api, made["id"], job_id=_job(api, "bbbbbbbbbbbb"), name="B")[0] == 409


def test_ranking_across_entries_on_the_wire(api: Api) -> None:
    made = _create(api)
    for i, (name, value) in enumerate([("Low", 55), ("High", 91), ("Mid", 70)]):
        job = _job(api, f"{i:012d}", analysis=_analysis({"value": value, "grade": "C"}))
        _add(api, made["id"], job_id=job, name=name)
    board = api.json("GET", f"api/challenges/{made['id']}")[1]["entries"]
    assert [(e["rank"], e["name"]) for e in board] == [(1, "High"), (2, "Mid"), (3, "Low")]
    assert api.json("GET", "api/challenges")[1]["challenges"][0]["leader"] == {"name": "High", "score": 91}


# ----- group submit -----------------------------------------------------------------------------------------
def test_group_submit_adds_the_whole_crew_from_their_own_analyses(api: Api) -> None:
    made = _create(api, kind="crew")
    job = _group_job(api, "ffffffffffff", {"1": _analysis({"value": 90, "grade": "A"}), "2": _analysis()})
    status, doc = _add(api, made["id"], job_id=job, people=[{"pid": "1", "name": "Ana"}, {"pid": 2, "name": "Ben"}])
    assert status == 201, doc
    assert [(e["name"], e["score"]) for e in doc["entries"]] == [("Ana", 90), ("Ben", 80)]
    stored = challenges.get(api.app.state, made["id"])["entries"]
    assert [(e["job_id"], e["pid"]) for e in stored] == [(job, "1"), (job, "2")]
    assert _add(api, made["id"], job_id=job, people=[{"pid": "1", "name": "Ana"}])[0] == 409


@pytest.mark.parametrize("people", [
    [], "x", [{"pid": "9", "name": "Ghost"}], [{"pid": "1", "name": ""}], [{"pid": "1", "name": "A"}, {"pid": "1", "name": "B"}],
    [{"pid": str(i), "name": "n"} for i in range(9)], [5],
])
def test_group_submit_is_all_or_nothing(api: Api, people: Any) -> None:
    made = _create(api, kind="crew")
    job = _group_job(api, "ffffffffffff", {"1": _analysis(), "2": _analysis()})
    assert _add(api, made["id"], job_id=job, people=people)[0] in (400, 409)
    assert api.json("GET", f"api/challenges/{made['id']}")[1]["entries"] == []


def test_group_result_needs_a_person_and_the_right_movement(api: Api) -> None:
    made = _create(api)
    job = _group_job(api, "ffffffffffff", {"1": _analysis()})
    assert _add(api, made["id"], job_id=job, name="Ana")[0] == 400
    other = _group_job(api, "111111111111", {"1": _analysis()}, entry_id="skel-only")
    assert _add(api, made["id"], job_id=other, pid="1", name="Ana")[0] == 409
    assert _add(api, made["id"], job_id=job, pid="1", name="Ana")[0] == 201


# ----- rate limit -------------------------------------------------------------------------------------------
def test_posts_are_rate_limited_per_visitor(api: Api) -> None:
    api.app.__dict__["challenge_rate"] = client_log.RateLimit(limit=2)
    body = {"entry_id": "lateral-raise", "title": "T", "creator_name": "S", "kind": "friend"}
    assert [api.json("POST", "api/challenges", body, VISITOR)[0] for _ in range(3)] == [201, 201, 429]
    assert api.json("POST", "api/challenges", body, {"Cf-Connecting-Ip": "203.0.113.9"})[0] == 201
    assert api.json("GET", "api/challenges")[0] == 200  # reading is never limited


# ----- operator CLI -----------------------------------------------------------------------------------------
def _run(capsys: pytest.CaptureFixture[str], state: Path, *args: str) -> tuple[int, str, str]:
    code = cli.main(["challenge", "--state", str(state), *args])
    out = capsys.readouterr()
    return code, out.out, out.err


def test_cli_create_list_close(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = _run(capsys, tmp_path, "create", "--entry", "lateral-raise", "--title", "Raise the roof",
                        "--sponsor-name", "Example Sportswear", "--sponsor-url", "https://example.com",
                        "--prize", "Shoes", "--ends", "2999-12-01")
    assert code == 0
    made = json.loads(out)
    stored = challenges.get(tmp_path, made["id"])
    assert stored["kind"] == "sponsored" and stored["sponsor"]["prize"] == "Shoes" and stored["ends_at"] == "2999-12-01T23:59:59Z"
    assert stored["sponsor"]["tagline"] == "Raise the roof" and stored["creator_name"] == "Example Sportswear"
    code, out, _ = _run(capsys, tmp_path, "list")
    assert code == 0 and [c["id"] for c in json.loads(out)] == [made["id"]]
    code, out, _ = _run(capsys, tmp_path, "close", made["id"])
    assert code == 0 and challenges.ended(challenges.get(tmp_path, made["id"]))
    assert _run(capsys, tmp_path, "close", "nosuchid1")[0] == 2


@pytest.mark.parametrize("over", [["--sponsor-url", "http://example.com"], ["--ends", "tomorrow"], ["--ends", "2001-01-01"],
                                  ["--entry", "Bad Entry"]])
def test_cli_refuses_bad_input_with_exit_2(tmp_path: Path, capsys: pytest.CaptureFixture[str], over: list[str]) -> None:
    base = {"--entry": "lateral-raise", "--title": "T", "--sponsor-name": "Example Sportswear",
            "--sponsor-url": "https://example.com", "--prize": "Shoes"}
    base.update(dict(zip(over[::2], over[1::2])))
    code, out, err = _run(capsys, tmp_path, "create", *[x for kv in base.items() for x in kv])
    assert code == 2 and out == "" and err.startswith("challenge:")
    assert challenges.list_all(tmp_path) == []


def test_cli_state_defaults(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SIMON7_STATE_DIR", str(tmp_path))
    args = challenge_cli.argparse.Namespace(state=None, staging=True)
    assert challenge_cli._state(args) == (tmp_path / "staging").resolve()
    assert challenge_cli._state(challenge_cli.argparse.Namespace(state=None, staging=False)) == (tmp_path / "dev").resolve()


def test_sponsored_challenge_view_carries_the_sponsor_block(api: Api) -> None:
    doc = _sponsored(api)
    shown = api.json("GET", f"api/challenges/{doc['id']}")[1]
    assert shown["kind"] == "sponsored" and shown["sponsor"] == SPONSOR
