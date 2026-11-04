"""One score on a board (docs/specs/score-consistency.md S7, TICKET-394): the number that ranks is the number shown,
the grade comes from it, and the old points never decide a rank. The fixture is the real case on the dumbbell lateral
raise board (prod, 4 Nov): a B with fewer points ranked above a C with more, both at the normal level."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from part7 import challenges, shown_score
from support import Api
from test_challenges import _add, _analysis as _job_analysis, _create, _job

GRADES = [[95, "S"], [85, "A"], [75, "B"], [65, "C"], [55, "D"], [40, "E"], [0, "F"]]
ORDER = "FEDCBAS"


def _credit(levels: dict[str, tuple[float, int, int]], scored: str = "normal") -> dict[str, Any]:
    pct, pts, most = levels[scored]
    return {"version": "simon.credit.v1", "percent": pct, "grade": "?", "points": pts, "max_points": most, "tolerance": scored,
            "levels": {k: {"percent": p, "points": a, "max_points": m} for k, (p, a, m) in levels.items()}, "grades": GRADES}


def _analysis(levels: dict[str, tuple[float, int, int]], value: int, grade: str, scored: str = "normal") -> dict[str, Any]:
    return {"status": {"code": "ok"}, "score": {"value": value, "grade": grade, "credit": _credit(levels, scored)}}


# P1: 4.9 s follow, every measure seen. P2: 9.7 s follow, 10 of 22 measures hidden (joints out of the picture).
P1 = _analysis({"easy": (83.0, 9361, 11275), "normal": (72.3, 10865, 15033), "hard": (65.1, 14680, 22550)}, 49, "F")
P2 = _analysis({"easy": (86.4, 7875, 9120), "normal": (76.1, 9249, 12160), "hard": (66.4, 12106, 18240)}, 84, "B")


def _row(name: str, analysis: dict[str, Any], at: str, board: bool = True) -> dict[str, Any]:
    shown = shown_score.for_board(analysis) if board else shown_score.of_analysis(analysis)
    return {"name": name, "score": analysis["score"]["value"], "grade": analysis["score"]["grade"], "shown": shown, "created_at": at}


def test_real_case_old_board_ranked_by_percent_and_showed_points() -> None:
    """The defect: the old stored block ranks 76.1 over 72.3 and shows 9,249 under 10,865."""
    rows = challenges.ranked([_row("P1", P1, "2026-11-04T05:19:21Z", False), _row("P2", P2, "2026-11-04T05:25:11Z", False)])
    assert [r["name"] for r in rows] == ["P2", "P1"]
    first, second = (int(r["shown"]["figures"].replace(",", "")) for r in rows)
    assert first < second  # 9,249 ranked above 10,865: the contradiction the operator saw
    assert shown_score.for_board(P1)["points"]["points"] > shown_score.for_board(P2)["points"]["points"]


def test_real_case_board_shows_the_number_it_ranks() -> None:
    rows = challenges.ranked([_row("P1", P1, "2026-11-04T05:19:21Z"), _row("P2", P2, "2026-11-04T05:25:11Z")])
    assert [(r["name"], r["rank"], r["shown"]["figures"], r["shown"]["letter"]) for r in rows] == [
        ("P2", 1, "76.1%", "B"), ("P1", 2, "72.3%", "C")]
    assert all(r["shown"]["unit"] == "percent" and r["shown"]["level"] == "normal" for r in rows)


def test_a_higher_rank_never_shows_a_lower_number_or_grade() -> None:
    percents = [99.4, 95.0, 94.9, 85.0, 84.95, 76.1, 76.1, 75.0, 74.9, 72.3, 65.0, 64.9, 55.0, 54.9, 40.0, 39.9, 0.0]
    rows = [_row(f"N{i}", _analysis({"normal": (p, int(p * 100), 10000)}, 50, "D"), f"2026-11-04T05:{i:02d}:00Z") for i, p in enumerate(percents)]
    ranked = challenges.ranked(list(reversed(rows)))
    for above, below in zip(ranked, ranked[1:]):
        a, b = above["shown"], below["shown"]
        assert float(a["figures"][:-1]) >= float(b["figures"][:-1]) and ORDER.index(a["letter"]) >= ORDER.index(b["letter"])


@pytest.mark.parametrize("percent,letter", [
    (100.0, "S"), (95.0, "S"), (94.9, "A"), (85.0, "A"), (84.9, "B"), (75.0, "B"), (74.9, "C"), (65.0, "C"), (64.9, "D"),
    (55.0, "D"), (54.9, "E"), (40.0, "E"), (39.9, "F"), (0.0, "F"),
])
def test_grade_boundaries(percent: float, letter: str) -> None:
    s = shown_score.for_board(_analysis({"normal": (percent, 1, 2)}, 50, "D"))
    assert (s["letter"], s["measure"], s["figures"]) == (letter, percent, f"{percent:.1f}%")


def test_the_board_table_is_part_5s() -> None:
    assert [list(g) for g in shown_score.BOARD_GRADES] == GRADES


@pytest.mark.parametrize("scored", ["easy", "normal", "hard"])
def test_level_taken_is_read_at_the_board_level(scored: str) -> None:
    """A take scored at easy or hard is ranked on its normal numbers, so a level choice is no advantage."""
    levels = {"easy": (83.0, 9361, 11275), "normal": (72.3, 10865, 15033), "hard": (65.1, 14680, 22550)}
    s = shown_score.for_board(_analysis(levels, 49, "F", scored))
    assert (s["measure"], s["level"], s["points"]) == (72.3, "normal", {"points": 10865, "max_points": 15033})


def test_a_take_without_the_board_level_says_its_own() -> None:
    only_hard = {"hard": (65.1, 14680, 22550)}
    s = shown_score.for_board(_analysis(only_hard, 49, "F", "hard"))
    assert (s["measure"], s["level"]) == (65.1, "hard")


def test_more_points_from_a_longer_take_do_not_win() -> None:
    long_take = _analysis({"normal": (60.0, 40000, 66667)}, 70, "C")
    short_take = _analysis({"normal": (80.0, 4000, 5000)}, 70, "C")
    rows = challenges.ranked([_row("Long", long_take, "2026-11-04T05:00:00Z"), _row("Short", short_take, "2026-11-04T05:01:00Z")])
    assert [r["name"] for r in rows] == ["Short", "Long"]


def test_old_scale_entries_rank_below_credit_entries() -> None:
    old = {"status": {"code": "ok"}, "score": {"value": 90, "grade": "A"}}
    rows = challenges.ranked([_row("Old", old, "2026-11-04T05:00:00Z"), _row("New", P1, "2026-11-04T05:01:00Z")])
    assert [r["name"] for r in rows] == ["New", "Old"] and rows[1]["shown"]["unit"] == "score"


def test_tie_goes_to_the_earlier_post() -> None:
    a = _analysis({"normal": (72.3, 1, 2)}, 50, "D")
    rows = challenges.ranked([_row("Late", a, "2026-11-04T05:09:00Z"), _row("Early", a, "2026-11-04T05:01:00Z")])
    assert [r["name"] for r in rows] == ["Early", "Late"]


def _board(state: Path, entries: list[dict[str, Any]]) -> str:
    doc = challenges.create(state, entry_id="lateral-raise", title="T", creator_name="C", kind="friend",
                            entries=[{"name": "x", "score": 1, "grade": "F", "job_id": "a" * 12, "pid": None}])
    stored = challenges.get(state, doc["id"])
    stored["entries"] = entries
    challenges._write(state, stored)
    return doc["id"]


def test_rescale_recomputes_from_the_analysis_and_keeps_the_original(tmp_path: Path) -> None:
    old = [{"name": n, "score": a["score"]["value"], "grade": a["score"]["grade"], "job_id": j * 12, "pid": None,
            "shown": shown_score.of_analysis(a), "created_at": at}
           for n, a, j, at in (("P1", P1, "a", "2026-11-04T05:19:21Z"), ("P2", P2, "b", "2026-11-04T05:25:11Z"))]
    old.append({"name": "Gone", "score": 40, "grade": "F", "job_id": "c" * 12, "pid": None, "created_at": "2026-11-04T05:30:00Z"})
    board = _board(tmp_path, old)
    docs = {"a" * 12: P1, "b" * 12: P2}
    read = lambda e: (docs[e["job_id"]], None, None) if e["job_id"] in docs else None  # noqa: E731
    assert challenges.rescale(tmp_path, read, apply=False) == {"changed": 2, "kept": 0, "missing": 1, "superseded": 0}
    assert challenges.get(tmp_path, board)["entries"] == old  # a dry run writes nothing
    assert challenges.rescale(tmp_path, read) == {"changed": 2, "kept": 0, "missing": 1, "superseded": 0}
    after = challenges.get(tmp_path, board)["entries"]
    assert [(e["name"], e["shown"]["figures"]) for e in after[:2]] == [("P1", "72.3%"), ("P2", "76.1%")]
    assert after[0]["shown_before"] == old[0]["shown"] and after[0]["score"] == 49 and after[0]["grade"] == "F"
    assert "shown_before" not in after[2] and json.dumps(after[2]) == json.dumps(old[2])
    assert challenges.rescale(tmp_path, read) == {"changed": 0, "kept": 2, "missing": 1, "superseded": 0}  # idempotent
    assert after == challenges.get(tmp_path, board)["entries"]


def _partial(share: float) -> dict[str, Any]:
    a = _analysis({"normal": (80.0, 1, 2)}, 50, "D")
    a["quality"] = {"signals": {"hidden_measure_share": share}}
    return a


@pytest.mark.parametrize("share,partial,note", [
    (0.0, False, "Standard level"), (0.25, False, "Standard level, 75% of measures seen"),
    (0.26, True, "Standard level, 74% of measures seen"), (0.45, True, "Standard level, 55% of measures seen"),
])
def test_coverage_is_shown_and_a_low_one_is_partial(share: float, partial: bool, note: str) -> None:
    s = shown_score.for_board(_partial(share))
    assert (s["partial"], s["note"]) == (partial, note)


def test_hiding_hard_measures_cannot_lift_an_entry_over_a_full_one() -> None:
    """P2 from the prod case (76.1%, 45% hidden) against a full 72.3%: the full take ranks first, and says why."""
    p2 = {**P2, "quality": {"signals": {"hidden_measure_share": 0.4545}}}
    rows = challenges.ranked([_row("P2", p2, "2026-11-04T05:25:11Z"), _row("P1", P1, "2026-11-04T05:19:21Z")])
    assert [r["name"] for r in rows] == ["P1", "P2"] and rows[1]["shown"]["partial"] is True


def test_public_score_and_grade_say_what_the_board_shows() -> None:
    e = {**_row("P2", P2, "2026-11-04T05:25:11Z"), "job_id": "a" * 12, "owner": "u1", "shown_before": {"x": 1}}
    out = challenges.public_entry(e)
    assert (out["score"], out["grade"]) == (76.1, "B") and not {"job_id", "owner", "shown_before"} & out.keys()
    assert e["score"] == 84  # Part 5's own pair stays on disk


def _owned(name: str, analysis: dict[str, Any], job: str, at: str = "x") -> dict[str, Any]:
    return {**_row(name, analysis, at), "job_id": job * 12, "pid": None, "owner": "u1"}


def test_one_row_per_account_best_kept(tmp_path: Path) -> None:
    doc = challenges.create(tmp_path, entry_id="lateral-raise", title="T", creator_name="C", kind="friend", entries=[_owned("Sam", P1, "a")])
    weaker = _analysis({"normal": (60.0, 1, 2)}, 40, "F")
    with pytest.raises(challenges.ChallengeError) as err:
        challenges.add_entries(tmp_path, doc["id"], [_owned("Sam", weaker, "b")])
    assert err.value.status == 409 and err.value.args[0] == challenges.MSG_BETTER_HELD
    stored = challenges.add_entries(tmp_path, doc["id"], [_owned("Sam", P2, "c")])
    assert [(e["job_id"][0], e["shown"]["measure"]) for e in stored["entries"]] == [("c", 76.1)]
    again = challenges.add_entries(tmp_path, doc["id"], [{**_row("Ann", P1, "x"), "job_id": "d" * 12, "pid": None}])  # no account: not merged
    assert len(again["entries"]) == 2


def test_same_job_twice_is_still_a_duplicate(tmp_path: Path) -> None:
    doc = challenges.create(tmp_path, entry_id="lateral-raise", title="T", creator_name="C", kind="friend", entries=[_owned("Sam", P1, "a")])
    with pytest.raises(challenges.ChallengeError) as err:
        challenges.add_entries(tmp_path, doc["id"], [_owned("Sam", P1, "a")])
    assert err.value.args[0] == challenges.MSG_DUPLICATE


def test_rescale_reads_the_owner_and_keeps_the_best_row(tmp_path: Path) -> None:
    rows = [{**_row(n, a, at), "job_id": j * 12, "pid": None} for n, a, j, at in (("Sam", P1, "a", "1"), ("Sam", P2, "b", "2"), ("Sam", P1, "c", "3"))]
    board = _board(tmp_path, rows)
    docs = {"a" * 12: P1, "b" * 12: P2, "c" * 12: P1}
    out = challenges.rescale(tmp_path, lambda e: (docs[e["job_id"]], None, "u1"))
    assert out["superseded"] == 2
    doc = challenges.get(tmp_path, board)
    assert [e["job_id"][0] for e in doc["entries"]] == ["b"] and [e["job_id"][0] for e in doc["superseded"]] == ["a", "c"]
    assert "superseded" not in challenges.view(doc) and "owner" not in challenges.view(doc)["entries"][0]


def test_a_section_take_is_refused_on_a_board(api: Api) -> None:
    cid = _create(api)["id"]
    whole = _job(api, "bbbbbbbbbbb1", analysis=_job_analysis({"value": 60, "grade": "D"}))
    part = _job(api, "bbbbbbbbbbb2", analysis=_job_analysis({"value": 95, "grade": "A"}), section={"start_s": 0.0, "end_s": 2.0})
    status, body = _add(api, cid, job_id=part, name="Part")
    assert status == 409 and "practice section" in str(body)
    assert _add(api, cid, job_id=whole, name="Full")[0] == 201  # negative: the whole movement still joins
    assert [e["name"] for e in api.json("GET", f"api/challenges/{cid}")[1]["entries"]] == ["Full"]


def test_a_superseded_row_and_a_crew_row_go_with_the_account(tmp_path: Path) -> None:
    """Review of release 10: `superseded` kept a replaced score after Delete my data; a crew's rows have no owner and outlived it."""
    made = challenges.create(tmp_path, entry_id="lateral-raise", title="T", creator_name="S", kind="friend")
    row = {"name": "Ann", "score": 50, "grade": "C", "job_id": "cccccccccccc", "pid": None}
    challenges.add_entries(tmp_path, made["id"], [{**row, "owner": "u1"}, {**row, "name": "Crew", "job_id": "dddddddddddd", "pid": "1", "poster": "u1"},
                                                  {**row, "name": "Other", "job_id": "eeeeeeeeeeee", "owner": "u2"}])
    stored = challenges.get(tmp_path, made["id"])
    path = tmp_path / "challenges" / f"{made['id']}.json"
    path.write_text(json.dumps({**stored, "superseded": [{**row, "name": "Ann Second", "job_id": "ffffffffffff", "owner": "u1"}]}))
    assert "poster" not in challenges.public_entry({**row, "poster": "u1"}), "negative: the poster is never public"
    assert [d["id"] for d in challenges.involving(tmp_path, "u1")] == [made["id"]]
    assert challenges.remove_account(tmp_path, "u1")["entries"] == 2
    text = path.read_text()
    assert "Ann" not in text and "Crew" not in text and "u1" not in text and "Other" in text
