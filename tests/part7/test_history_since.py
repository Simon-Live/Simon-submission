"""TICKET-207: \"Since last time\" and personal bests, on the fact table (docs/specs/history.md \"Since last time\").

The pure functions run on small made analyses; the route runs on the two real cleared takes of history_support.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from history_support import ENTRY, FIRST, OTHER, SECOND, USER, World, job_record, record_two, seed_job, world  # noqa: F401
from part7 import history_facts, history_since, history_store
from support import Api
from test_history_facts import _made

KNEE = ("knee_flexion", "left", 2.0, 20.0)
ELBOW = ("elbow_flexion", "right", 3.0, 15.0)


def _facts(tmp_path: Path, *rows: dict[str, Any]) -> dict[str, Any]:
    takes = [{**r, "job_id": f"{n:012x}", "at": f"2026-10-{27 + n}T10:00:00Z"} for n, r in enumerate(rows, 1)]
    return history_facts.build(takes, ENTRY)


def _since(facts: dict[str, Any], take: int) -> dict[str, Any] | None:
    return history_since.since_last_time(facts, f"{take:012x}")


def test_the_line_names_the_score_and_each_cue_with_a_link_to_the_earlier_take(tmp_path: Path) -> None:
    facts = _facts(tmp_path, _made(tmp_path, 1, 77, [KNEE]), _made(tmp_path, 2, 84, [ELBOW]))
    doc = _since(facts, 2)
    assert doc["line"] == "Since last time (28 Oct): score 77 to 84; the left knee flexion cue is gone; the right elbow flexion cue is new"
    assert doc["previous"] == {"take": 1, "job_id": f"{1:012x}", "at": "2026-10-28T10:00:00Z"} and doc["take"] == 2
    assert [(f["kind"], f["link"]) for f in doc["facts"]] == [
        ("score", {"take": 1, "job_id": f"{1:012x}", "at_s": None}),
        ("gone", {"take": 1, "job_id": f"{1:012x}", "at_s": 2.0}),
        ("new", {"take": 1, "job_id": f"{1:012x}", "at_s": 3.0})]
    assert [b["text"] for b in doc["bests"]] == ["New best: 84", "First take without the left knee flexion cue"]


def test_joint_names_a_cue_when_the_analysis_has_one(tmp_path: Path) -> None:
    path = tmp_path / "j.json"
    path.write_text('{"status": {"code": "ok"}, "faults": [{"measure": "knee_valgus", "side": "left", "joint": "left_knee", "at_s": 1.0, "magnitude_deg": 9,'
                    ' "follower_t_s": [1, 2]}], "score": {"value": 60, "timeline": [{"t_s": [0, 9], "misses": []}]}}')
    one = {**_made(tmp_path, 1, 60, []), "analysis": path}
    facts = _facts(tmp_path, one, _made(tmp_path, 2, 70, []))
    assert "the left knee cue is gone" in _since(facts, 2)["line"]


def test_a_cue_is_gone_or_new_only_where_the_other_take_compared_that_moment(tmp_path: Path) -> None:
    short = _made(tmp_path, 2, 80, [], window=(0.0, 1.0))          # never looked at 2 s: the knee cue may still be there
    facts = _facts(tmp_path, _made(tmp_path, 1, 60, [KNEE]), short)
    doc = _since(facts, 2)
    assert [f["kind"] for f in doc["facts"]] == ["score"] and "gone" not in doc["line"]
    assert [b["kind"] for b in doc["bests"]] == ["best"]            # no "first take without": it was not compared
    new = _made(tmp_path, 2, 80, [ELBOW])
    facts = _facts(tmp_path, _made(tmp_path, 1, 60, [], window=(0.0, 1.0)), new)   # take 1 never compared 3 s: not "new"
    assert [f["kind"] for f in _since(facts, 2)["facts"]] == ["score"]


def test_back_and_unchanged_score(tmp_path: Path) -> None:
    facts = _facts(tmp_path, _made(tmp_path, 1, 70, [KNEE]), _made(tmp_path, 2, 70, []), _made(tmp_path, 3, 70, [KNEE]))
    doc = _since(facts, 3)
    assert doc["line"].endswith("score 70, the same; the left knee flexion cue is back")
    assert doc["bests"] == []                                        # equal is not a new best


def test_first_take_without_a_cue_happens_once(tmp_path: Path) -> None:
    rows = [_made(tmp_path, 1, 60, [KNEE]), _made(tmp_path, 2, 70, []), _made(tmp_path, 3, 75, [])]
    facts = _facts(tmp_path, *rows)
    assert [b["kind"] for b in _since(facts, 2)["bests"]] == ["best", "first_without"]
    assert [b["kind"] for b in _since(facts, 3)["bests"]] == ["best"]


def test_nothing_for_a_first_take_or_an_unknown_job(tmp_path: Path) -> None:
    facts = _facts(tmp_path, _made(tmp_path, 1, 60, [KNEE]), _made(tmp_path, 2, 70, []))
    assert _since(facts, 1) is None
    assert history_since.since_last_time(facts, "f" * 12) is None
    assert history_since.since_last_time({"takes": []}, "a" * 12) is None


def test_only_the_same_section_mode_and_score_version_count(tmp_path: Path) -> None:
    rows = [_made(tmp_path, 1, 95, [KNEE], section_key="s1of3"), _made(tmp_path, 2, 50, [], mode="dance"),
            _made(tmp_path, 3, 99, [], section_key=None, mode=None, score_version=None), _made(tmp_path, 4, 70, [ELBOW])]
    facts = _facts(tmp_path, *rows)
    assert _since(facts, 4) is None                                  # the first full fitness take: others are different
    assert _since(facts, 3) is None                                  # unknown section and mode: no claims at all
    rows.append(_made(tmp_path, 5, 80, [], score_version="simon.score.v1:zzzzzzzz"))
    doc = _since(_facts(tmp_path, *rows), 5)
    assert [f["kind"] for f in doc["facts"]] == ["gone"] and doc["bests"][0]["kind"] == "first_without"   # no score line: other scale
    assert "score" not in doc["line"]


def test_an_older_result_reads_as_it_did_and_a_lone_score_still_says_something(tmp_path: Path) -> None:
    facts = _facts(tmp_path, _made(tmp_path, 1, 60, []), _made(tmp_path, 2, 70, []), _made(tmp_path, 3, 50, []))
    assert _since(facts, 2)["line"] == "Since last time (28 Oct): score 60 to 70"
    assert _since(facts, 3)["line"] == "Since last time (29 Oct): score 70 to 50" and _since(facts, 3)["bests"] == []


def test_unreadable_time_drops_the_date() -> None:
    assert history_since._date("not a time") == "" and history_since._date("2026-11-01T08:00:00Z") == "1 Nov"


# ----- the route ------------------------------------------------------------------------------------------
BASE = "api/me/since-last-time"


@pytest.fixture()
def seeded(api: Api, world: World, monkeypatch: pytest.MonkeyPatch) -> Api:  # noqa: F811
    record_two(api.app.state, world)
    return api


def _get(api: Api, job: str, user: str | None = USER) -> tuple[int, Any]:
    return api.json("GET", f"{BASE}/{job}", headers={"X-Test-User": user} if user else {})


def test_route_owner_gets_the_line_with_a_playable_link(seeded: Api) -> None:
    status, doc = _get(seeded, SECOND)
    since = doc["since"]
    assert status == 200 and since["entry_id"] == ENTRY and since["previous"]["job_id"] == FIRST
    assert since["line"].startswith("Since last time (31 Oct): score 100 to 77")
    assert since["facts"][0]["link"]["clip"] == f"api/me/history/{ENTRY}/takes/{FIRST}/clip.mp4"
    assert since["bests"] == [] or all(b["link"]["job_id"] == FIRST for b in since["bests"])


def test_route_first_take_says_nothing(seeded: Api) -> None:
    status, doc = _get(seeded, FIRST)
    assert (status, doc) == (200, {"since": None})


def test_route_is_owner_only(seeded: Api) -> None:
    assert _get(seeded, SECOND, user=None)[0] == 401                  # nobody signed in: the page does not even ask
    assert _get(seeded, SECOND, user=OTHER)[0] == 404                 # someone else's take looks like no take
    assert _get(seeded, "0" * 12)[0] == 404 and _get(seeded, "not-a-job")[0] == 404
    status, _, _ = seeded.request("POST", f"{BASE}/{SECOND}", headers={"X-Test-User": USER})
    assert status in (403, 405)


def test_route_a_take_of_another_mode_is_not_compared(api: Api, world: World) -> None:  # noqa: F811
    world.opted_in.add(USER)
    for job, mode in ((FIRST, "dance"), (SECOND, "fitness")):
        folder = seed_job(api.app.state, job, mode=mode)
        world.owners[job] = USER
        assert history_store.record_take(api.app.state, job_record(api.app.state, job), folder)
    assert _get(api, SECOND) == (200, {"since": None})
