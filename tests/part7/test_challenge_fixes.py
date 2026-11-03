"""Challenge hardening (docs/specs/challenges.md "Privacy", "Limits"): public views, one request for a challenge and
its first entry, the follow `challenge_id`, the file lock, the board cap and prune, and negative Content-Length."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import multiprocessing
from pathlib import Path
from typing import Any

import pytest

from part7 import challenges
from support import Api
from test_challenges import VISITOR, _add, _analysis, _create, _group_job, _job
from test_practice import _follow

BODY = {"entry_id": "lateral-raise", "title": "Beat my raises", "creator_name": "Sam", "kind": "friend"}


def _post(api: Api, **over: Any) -> tuple[int, Any]:
    return api.json("POST", "api/challenges", {**BODY, **over}, VISITOR)


def _boards(api: Api) -> int:
    return len(api.json("GET", "api/challenges")[1]["challenges"])


# ----- B1: public views carry no job id ---------------------------------------------------------------------
def test_no_public_view_names_a_job_but_the_file_keeps_it(api: Api) -> None:
    made = _create(api)
    job = _job(api, "aaaaaaaaaaaa")
    status, added = _add(api, made["id"], job_id=job, name="Sam")
    assert status == 201
    for doc in (added, api.json("GET", f"api/challenges/{made['id']}")[1]):
        assert "job_id" not in json.dumps(doc) and '"pid"' not in json.dumps(doc), doc
    listing = api.json("GET", "api/challenges")[1]
    assert "job_id" not in json.dumps(listing) and {k: v for k, v in listing["challenges"][0]["leader"].items() if k != "shown"} == {"name": "Sam", "score": 80}
    assert challenges.get(api.app.state, made["id"])["entries"][0]["job_id"] == job


def test_a_result_on_a_board_cannot_join_another_under_a_different_name(api: Api) -> None:
    one, two = _create(api)["id"], _create(api)["id"]
    job = _job(api, "aaaaaaaaaaaa")
    assert _add(api, one, job_id=job, name="Sam")[0] == 201
    status, err = _add(api, two, job_id=job, name="Ana")
    assert status == 409 and "another name" in err["error"]
    assert api.json("GET", f"api/challenges/{two}")[1]["entries"] == []
    assert _add(api, two, job_id=job, name=" sam ")[0] == 201  # the same person on a second board is fine


def test_the_other_name_rule_covers_a_person_of_a_group_job(api: Api) -> None:
    one, two = _create(api, kind="crew")["id"], _create(api, kind="crew")["id"]
    job = _group_job(api, "ffffffffffff", {"1": _analysis(), "2": _analysis()})
    assert _add(api, one, job_id=job, people=[{"pid": "1", "name": "Ana"}])[0] == 201
    assert _add(api, two, job_id=job, people=[{"pid": "1", "name": "Zed"}])[0] == 409
    assert _add(api, two, job_id=job, people=[{"pid": "2", "name": "Zed"}])[0] == 201  # a different person


# ----- B4: the challenge and its first entry are one request ------------------------------------------------
def test_create_with_a_first_entry_stores_both(api: Api) -> None:
    job = _job(api, "aaaaaaaaaaaa")
    status, doc = _post(api, job_id=job, name="Sam")
    assert status == 201, doc
    assert [(e["name"], e["score"]) for e in doc["entries"]] == [("Sam", 80)] and doc["added"][0]["grade"] == "B"
    assert "job_id" not in json.dumps(doc)
    assert len(challenges.get(api.app.state, doc["id"])["entries"]) == 1


def test_create_with_a_crew_stores_everyone(api: Api) -> None:
    job = _group_job(api, "ffffffffffff", {"1": _analysis({"value": 90, "grade": "A"}), "2": _analysis()})
    status, doc = _post(api, kind="crew", job_id=job, people=[{"pid": "1", "name": "Ana"}, {"pid": "2", "name": "Ben"}])
    assert status == 201 and [e["name"] for e in doc["entries"]] == ["Ana", "Ben"]


@pytest.mark.parametrize("make", [
    lambda api: {"job_id": "bbbbbbbbbbbb", "name": "Sam"},  # unknown job: 404
    lambda api: {"job_id": _job(api, "cccccccccccc", analysis=_analysis(code="warn")), "name": "Sam"},  # not "ok": 409
    lambda api: {"job_id": _job(api, "dddddddddddd", entry_id="reverse-lunge"), "name": "Sam"},  # other movement: 409
    lambda api: {"job_id": _job(api, "eeeeeeeeeeee"), "name": ""},  # bad name: 400
    lambda api: {"job_id": _job(api, "ffffffffffff"), "people": []},  # bad crew: 400
])
def test_a_refused_first_entry_creates_nothing(api: Api, make: Any) -> None:
    status, doc = _post(api, **make(api))
    assert status in (400, 404, 409) and doc["error"], doc
    assert _boards(api) == 0 and not list((api.app.state / "challenges").glob("*.json"))


def test_create_without_an_entry_is_unchanged(api: Api) -> None:
    status, doc = _post(api)
    assert status == 201 and doc["entries"] == [] and doc["added"] == []


def test_a_crew_with_one_unscored_person_creates_nothing(api: Api) -> None:
    job = _group_job(api, "ffffffffffff", {"1": _analysis(), "2": _analysis(code="warn")})
    status, _ = _post(api, kind="crew", job_id=job, people=[{"pid": "1", "name": "Ana"}, {"pid": "2", "name": "Ben"}])
    assert status == 409 and _boards(api) == 0


# ----- B5: challenge_id on the follow request ----------------------------------------------------------------
def test_follow_stores_an_open_challenge_of_the_same_movement(api: Api, tiny_mp4: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    made = _create(api)
    status, doc = _follow(api, tiny_mp4, monkeypatch, challenge_id=made["id"])
    assert status == 202 and doc["challenge_id"] == made["id"]
    assert api.json("GET", f"api/jobs/{doc['job']}")[1]["challenge_id"] == made["id"]


def test_follow_without_a_challenge_id_has_none(api: Api, tiny_mp4: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    status, doc = _follow(api, tiny_mp4, monkeypatch)
    assert status == 202 and "challenge_id" not in doc


def test_follow_refuses_a_bad_challenge_and_queues_nothing(api: Api, tiny_mp4: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    other = challenges.create(api.app.state, entry_id="reverse-lunge", title="T", creator_name="S", kind="friend")["id"]
    for value, expect in (("nosuchid1", 400), (7, 400), (["x"], 400), (other, 400)):
        status, doc = _follow(api, tiny_mp4, monkeypatch, challenge_id=value)
        assert status == expect and doc["error"], (value, status, doc)
        assert api.app.queue.counts() == {"running": 0, "waiting": 0}


def test_a_challenge_that_ended_before_the_upload_does_not_refuse_the_take(api: Api, tiny_mp4: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ended = _create(api)["id"]
    challenges.close(api.app.state, ended)
    status, doc = _follow(api, tiny_mp4, monkeypatch, challenge_id=ended)
    assert status == 202 and "challenge_id" not in doc and doc["challenge_ended"] is True
    record = api.json("GET", f"api/jobs/{doc['job']}")[1]
    assert "challenge_id" not in record and record["challenge_ended"] is True


# ----- R5: two writers never lose an update -----------------------------------------------------------------
def _writer(args: tuple[str, str, int]) -> None:
    state, cid, n = args
    challenges.add_entries(Path(state), cid, [{"name": f"P{n}", "score": n, "grade": "C", "job_id": f"{n:012d}", "pid": None}])


def test_concurrent_processes_keep_every_update(tmp_path: Path) -> None:
    doc = challenges.create(tmp_path, entry_id="lateral-raise", title="T", creator_name="S", kind="friend")
    with multiprocessing.get_context("fork").Pool(6) as pool:
        pool.map(_writer, [(str(tmp_path), doc["id"], n) for n in range(12)], chunksize=1)
    challenges.close(tmp_path, doc["id"])  # after the writers, so the outcome never depends on scheduling
    stored = challenges.get(tmp_path, doc["id"])
    assert sorted(e["score"] for e in stored["entries"]) == list(range(12))  # no concurrent add was lost
    assert challenges.ended(stored)  # and the close did not drop an entry
    assert [p.name for p in (tmp_path / "challenges").iterdir() if p.suffix != ".json" and p.name != ".lock"] == []


# ----- R6: cap, prune and the read cache ---------------------------------------------------------------------
def test_the_board_cap_refuses_a_new_public_board_but_not_the_operator(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(challenges, "MAX_BOARDS", 2)
    assert [_post(api)[0] for _ in range(3)] == [201, 201, 409]
    assert _boards(api) == 2
    sponsor = {"name": "N", "tagline": "t", "url": "https://example.com", "prize": "p"}
    challenges.create(api.app.state, entry_id="lateral-raise", title="S", creator_name="N", kind="sponsored", sponsor=sponsor, allow_sponsored=True)
    assert _boards(api) == 3


def _age(state: Path, cid: str, days: int) -> None:
    path = state / "challenges" / f"{cid}.json"
    doc = json.loads(path.read_text())
    doc["created_at"] = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    path.write_text(json.dumps(doc))


def test_idle_public_boards_are_pruned_and_sponsored_ones_stay(tmp_path: Path) -> None:
    sponsor = {"name": "N", "tagline": "t", "url": "https://example.com", "prize": "p"}
    old = challenges.create(tmp_path, entry_id="lateral-raise", title="Old", creator_name="S", kind="friend")["id"]
    fresh = challenges.create(tmp_path, entry_id="lateral-raise", title="New", creator_name="S", kind="friend")["id"]
    kept = challenges.create(tmp_path, entry_id="lateral-raise", title="Ad", creator_name="N", kind="sponsored", sponsor=sponsor, allow_sponsored=True)["id"]
    for cid in (old, kept):
        _age(tmp_path, cid, challenges.STALE_DAYS + 5)
    challenges.create(tmp_path, entry_id="lateral-raise", title="Trigger", creator_name="S", kind="friend")
    ids = {d["id"] for d in challenges.list_all(tmp_path)}
    assert old not in ids and fresh in ids and kept in ids


def test_listing_reads_only_the_files_that_changed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    a = challenges.create(tmp_path, entry_id="lateral-raise", title="A", creator_name="S", kind="friend")["id"]
    challenges.create(tmp_path, entry_id="lateral-raise", title="B", creator_name="S", kind="friend")
    challenges.list_all(tmp_path)
    reads: list[str] = []
    real = challenges._read
    monkeypatch.setattr(challenges, "_read", lambda path, cid: reads.append(cid) or real(path, cid))
    assert len(challenges.list_all(tmp_path)) == 2 and reads == []  # nothing changed: nothing read
    challenges.add_entries(tmp_path, a, [{"name": "P", "score": 5, "grade": "F", "job_id": "x" * 12, "pid": None}])
    reads.clear()
    rows = challenges.list_all(tmp_path)
    assert reads == [a] and {r["id"]: r["entry_count"] for r in rows}[a] == 1


# ----- R7: a negative Content-Length is a 400, not a hang ---------------------------------------------------
@pytest.mark.parametrize("path", ["api/challenges", "api/challenges/abcdefgh/entries", "api/follow", "api/trainer"])
@pytest.mark.parametrize("length", ["-5", "abc"])
def test_a_bad_content_length_is_400(api: Api, path: str, length: str) -> None:
    status, _, _ = api.request("POST", path, b"", {"Content-Length": length})
    assert status == 400


# ----- pre-mortem: a cap on the boards one visitor makes in a day ------------------------------------------------
def test_one_visitor_makes_at_most_the_daily_number_of_boards(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(challenges, "BOARDS_PER_VISITOR_DAY", 3)
    assert [_post(api)[0] for _ in range(3)] == [201, 201, 201]
    status, err = _post(api)
    assert status == 429 and err["error"] == challenges.MSG_VISITOR_BOARDS
    assert _boards(api) == 3
    other = api.json("POST", "api/challenges", dict(BODY), {"Cf-Connecting-Ip": "203.0.113.9"})
    assert other[0] == 201  # a second visitor is counted on their own


def test_the_visitor_cap_counts_per_key_and_per_day_and_stays_private(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(challenges, "BOARDS_PER_VISITOR_DAY", 2)
    make = lambda who: challenges.create(tmp_path, entry_id="lateral-raise", title="T", creator_name="S", kind="friend", visitor=who)  # noqa: E731
    first = make("aaaa")
    make("aaaa")
    with pytest.raises(challenges.ChallengeError) as caught:
        make("aaaa")
    assert caught.value.status == 429
    assert make("bbbb")["id"]  # another visitor is not held back
    _age(tmp_path, first["id"], 1)  # yesterday's board does not count
    assert make("aaaa")["id"]
    stored = challenges.get(tmp_path, first["id"])
    assert stored["visitor"] == "aaaa"
    assert "visitor" not in challenges.view(stored) and "visitor" not in challenges.summary(stored)
    sponsor = {"name": "N", "tagline": "t", "url": "https://example.com", "prize": "p"}
    for _ in range(3):  # the operator's sponsored boards are not capped
        challenges.create(tmp_path, entry_id="lateral-raise", title="S", creator_name="N", kind="sponsored", sponsor=sponsor, allow_sponsored=True, visitor="aaaa")
