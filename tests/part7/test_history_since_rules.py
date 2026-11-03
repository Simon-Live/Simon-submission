"""TICKET-213 AC-4 to AC-7: private takes, rehab, no retention, and a take whose history copy is not written yet."""

from __future__ import annotations

from pathlib import Path
from typing import Any


from history_support import FIRST, OTHER, SECOND, USER, World, job_record, seed_job, world  # noqa: F401
from part7 import history_store
from support import Api
from test_history_facts import _made
from test_history_since import ELBOW, KNEE, _facts, _since

BASE = "api/me/since-last-time"


def _get(api: Api, job: str, user: str | None = USER) -> tuple[int, Any]:
    return api.json("GET", f"{BASE}/{job}", headers={"X-Test-User": user} if user else {})


def test_a_private_take_shows_no_line_and_is_not_counted(tmp_path: Path) -> None:
    rows = [_made(tmp_path, 1, 60, [KNEE]), {**_made(tmp_path, 2, 99, []), "private": True}, _made(tmp_path, 3, 70, [])]
    facts = _facts(tmp_path, *rows)
    assert _since(facts, 2) is None
    doc = _since(facts, 3)
    assert doc["previous"]["take"] == 1 and "99" not in doc["line"]     # compared with take 1: the private 99 is not a best to beat
    assert [b["text"] for b in doc["bests"]][0] == "New best: 70"


def test_rehab_shows_cues_but_no_score_or_best(tmp_path: Path) -> None:
    rows = [_made(tmp_path, 1, 60, [KNEE], mode="rehab"), _made(tmp_path, 2, 80, [ELBOW], mode="rehab")]
    doc = _since(_facts(tmp_path, *rows), 2)
    assert "score" not in doc["line"] and [f["kind"] for f in doc["facts"]] == ["gone", "new"]
    assert [b["kind"] for b in doc["bests"]] == ["first_without"]
    only_score = _since(_facts(tmp_path, _made(tmp_path, 1, 60, [], mode="rehab"), _made(tmp_path, 2, 80, [], mode="rehab")), 2)
    assert only_score is None                                            # nothing but a score: nothing is shown


def test_the_line_has_no_praise_or_banned_word(tmp_path: Path) -> None:
    from part7 import history_guard
    doc = _since(_facts(tmp_path, _made(tmp_path, 1, 77, [KNEE]), _made(tmp_path, 2, 84, [ELBOW])), 2)
    words = history_guard.load_words()
    text = " ".join([doc["line"], *(b["text"] for b in doc["bests"])])
    assert not history_guard._Words(words).praise.search(text)
    assert not history_guard._Words(words).banned.search(text)
    assert chr(0x2014) not in text and chr(0x2013) not in text


def test_route_no_retention_consent_shows_nothing(api: Api, world: World) -> None:  # noqa: F811
    world.opted_in.add(USER)
    for job in (FIRST, SECOND):
        folder = seed_job(api.app.state, job)
        world.owners[job] = USER
        assert history_store.record_take(api.app.state, job_record(api.app.state, job), folder)
    world.opted_in.discard(USER)                                         # consent withdrawn
    assert _get(api, SECOND) == (200, {"since": None})


def test_route_before_the_history_copy_exists_it_reads_the_job_folder(api: Api, world: World) -> None:  # noqa: F811
    world.opted_in.add(USER)
    folder = seed_job(api.app.state, FIRST)
    world.owners[FIRST] = USER
    assert history_store.record_take(api.app.state, job_record(api.app.state, FIRST), folder)
    seed_job(api.app.state, SECOND)                                      # finished, owned, not copied yet
    world.owners[SECOND] = USER
    assert not list((api.app.state / "history" / USER).glob("*/takes/" + SECOND))
    status, doc = _get(api, SECOND)
    assert status == 200 and doc["since"]["line"].startswith("Since last time (31 Oct): score 100 to 77")
    assert doc["since"]["previous"]["job_id"] == FIRST
    assert _get(api, SECOND, user=OTHER)[0] == 404                       # not theirs
    assert not list((api.app.state / "history" / USER).glob("*/takes/" + SECOND))   # reading wrote nothing


def test_route_private_job_is_not_shown(api: Api, world: World) -> None:  # noqa: F811
    world.opted_in.add(USER)
    for job, extra in ((FIRST, {}), (SECOND, {"private": True})):
        folder = seed_job(api.app.state, job, **extra)
        world.owners[job] = USER
        assert history_store.record_take(api.app.state, job_record(api.app.state, job), folder)
    assert _get(api, SECOND) == (200, {"since": None})


def test_pending_take_needs_the_owner_a_finished_follow_take_and_consent(tmp_path: Path, world: World) -> None:  # noqa: F811
    world.opted_in.add(USER)
    seed_job(tmp_path, SECOND)
    assert history_store.pending_take(tmp_path, USER, SECOND) is None    # nobody owns it
    world.owners[SECOND] = USER
    row = history_store.pending_take(tmp_path, USER, SECOND)
    assert row["score"] == 77 and row["clip"] is None and (row["section_key"], row["mode"]) == ("full", "fitness")
    assert history_store.pending_take(tmp_path, OTHER, SECOND) is None
    assert history_store.pending_take(tmp_path, USER, "../x") is None
    world.opted_in.clear()
    assert history_store.pending_take(tmp_path, USER, SECOND) is None
    world.opted_in.add(USER)
    folder = tmp_path / "jobs" / SECOND
    (folder / "job.json").write_text('{"id": "%s", "kind": "follow", "status": "running", "entry_id": "x"}' % SECOND)
    assert history_store.pending_take(tmp_path, USER, SECOND) is None
