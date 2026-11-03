"""One take, one letter, part 2 (docs/specs/one-letter.md L3, L5 to L7): a rank or a best follows the shown measure,
capped takes are never featured, and the history report's model reads the score the page shows.

A credit take 37 F whose shown result is C at 72.6% (the MM-Fit take 42a02415127e, CC BY 4.0) now ranks above a plain
50 F take; a take a warning capped ranks by its capped score and is never the leader, the hero or a featured pick.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from part7 import (challenges, group, history_ask_guard, history_facts, history_guard, history_prompt, history_recap,
                   history_since, judge_view, shown_score)

VECTORS = json.loads((Path(__file__).parent / "fixtures" / "shown-score-vectors.json").read_text(encoding="utf-8"))["cases"]
TRIGGER = VECTORS[0]["analysis"]["score"]
CAPPED = VECTORS[4]["analysis"]["score"]
CREDIT = {"letter": "C", "figures": "16,239", "caption": "of 22,367", "unit": "points", "capped": False, "warning": [], "measure": 72.6}
CAPPED_SHOWN = {"letter": "F", "figures": "37", "caption": "score out of 100", "unit": "score", "capped": True,
                "warning": ["low_match"], "measure": 37}
PLAIN50 = {"letter": "F", "figures": "50", "caption": "out of 100", "unit": "score", "capped": False, "warning": [], "measure": 50}
AT = "2026-11-02T10:00:00Z"


def _entry(name: str, score: int, shown: dict[str, Any] | None, at: str = AT) -> dict[str, Any]:
    return {"name": name, "score": score, "grade": "F", "created_at": at, **({"shown": shown} if shown else {})}


# ----- L3: a rank follows the shown measure -----------------------------------------------------------------------------
def test_the_shown_block_carries_the_measure() -> None:
    assert shown_score.public(shown_score.shown({"score": TRIGGER})) == CREDIT
    assert shown_score.rank_of({"score": 37, "shown": CREDIT}) == 72.6
    assert shown_score.rank_of({"score": 37, "shown": CAPPED_SHOWN}) == 37
    assert shown_score.rank_of({"score": 50}) == 50   # an old row: its score
    assert shown_score.rank_of({"score": None}) is None


def test_a_50_f_take_ranks_below_a_37_take_shown_as_c_72() -> None:
    board = challenges.ranked([_entry("Fifty", 50, PLAIN50), _entry("Credit", 37, CREDIT, "2026-11-02T11:00:00Z")])
    assert [e["name"] for e in board] == ["Credit", "Fifty"]
    old = challenges.ranked([_entry("Old", 50, None), _entry("Credit", 37, CREDIT, "2026-11-02T11:00:00Z")])
    assert [e["name"] for e in old] == ["Credit", "Old"]   # a stored entry without the block ranks by its score


def test_a_capped_take_ranks_by_its_capped_score_and_ties_keep_the_earlier_post() -> None:
    board = challenges.ranked([_entry("Capped", 37, CAPPED_SHOWN), _entry("Forty", 40, {**PLAIN50, "figures": "40", "measure": 40})])
    assert [e["name"] for e in board] == ["Forty", "Capped"]
    tie = challenges.ranked([_entry("Later", 37, CREDIT, "2026-11-02T12:00:00Z"), _entry("Earlier", 30, CREDIT, AT)])
    assert [e["name"] for e in tie] == ["Earlier", "Later"]


def test_group_order_follows_the_shown_measure() -> None:
    people = [{"id": "1", "score": 50, "shown": PLAIN50}, {"id": "2", "score": 37, "shown": CREDIT}, {"id": "3", "score": None}]
    assert [p["id"] for p in group.order(people)] == ["2", "1", "3"]


def _job(root: Path, job_id: str, score: dict[str, Any], **analysis: Any) -> None:
    folder = root / job_id
    (folder / "work" / "follower").mkdir(parents=True)
    record = {"id": job_id, "kind": "follow", "status": "done", "entry_id": "squat-real-people", "finished_at": AT,
              "result": {"score": score["value"], "grade": score["grade"], "light": {"level": "ok"}}}
    (folder / "job.json").write_text(json.dumps(record), encoding="utf-8")
    doc = {"status": {"code": "ok"}, "score": score, **analysis}
    (folder / "work" / "follower" / "analysis.json").write_text(json.dumps(doc), encoding="utf-8")


def test_the_hero_auto_pick_follows_the_shown_measure_and_never_a_capped_take(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(judge_view.HERO_ENV, raising=False)
    monkeypatch.setattr(judge_view.mesh_files, "index", lambda root, job_id: {"follower": True, "trainer": True})
    _job(tmp_path, "aaaaaaaaaaaa", {"value": 50, "grade": "F"})
    _job(tmp_path, "bbbbbbbbbbbb", TRIGGER)
    _job(tmp_path, "cccccccccccc", {**TRIGGER, "value": 95, "grade": "A", "capped_by": ["low_match"],
                                    "credit": {**TRIGGER["credit"], "percent": 99.0}}, warnings=[{"code": "low_match"}])
    assert judge_view.hero(tmp_path, tmp_path)["job_id"] == "bbbbbbbbbbbb"


# ----- L6: a capped take is never featured --------------------------------------------------------------------------
def test_a_board_leader_is_never_a_capped_take() -> None:
    doc = {"id": "x", "entries": [_entry("Capped", 95, {**CAPPED_SHOWN, "figures": "95", "measure": 95}), _entry("Credit", 37, CREDIT)]}
    lead = challenges.summary(doc)["leader"]
    assert lead["name"] == "Credit" and lead["shown"] == CREDIT
    only = challenges.summary({"id": "y", "entries": [_entry("Capped", 37, CAPPED_SHOWN)]})
    assert only["leader"] is None and only["entry_count"] == 1   # the board still counts it; it is just not the headline


# ----- L3 in the history: best, since last time, records, clip order and the guards ------------------------------------
def _take(tmp: Path, n: int, score: dict[str, Any]) -> dict[str, Any]:
    path = tmp / f"t{n}.json"
    path.write_text(json.dumps({"status": {"code": "ok"}, "score": {"version": "simon.score.v3", **score}}), encoding="utf-8")
    return {"take": n, "job_id": f"job{n:09d}", "at": f"2026-11-0{n}T10:00:00Z", "score": score["value"], "grade": score["grade"],
            "duration_s": 10.0, "section_key": "full", "mode": "fitness", "score_version": "simon.score.v3", "analysis": path}


def _facts(tmp: Path, *scores: dict[str, Any]) -> dict[str, Any]:
    return history_facts.table([_take(tmp, n, s) for n, s in enumerate(scores, start=1)], "squat")


def test_history_best_follows_the_shown_measure(tmp_path: Path) -> None:
    facts = _facts(tmp_path, TRIGGER, {"value": 50, "grade": "F"})
    assert facts["best"] == 1   # C at 72.6% beats the plain 50 F


def test_since_last_time_compares_and_words_the_shown_score(tmp_path: Path) -> None:
    better = {**TRIGGER, "credit": {**TRIGGER["credit"], "percent": 80.0, "points": 17894}}
    facts = _facts(tmp_path, TRIGGER, better)
    since = history_since.since_last_time(facts, "job000000002")
    assert since is not None
    assert "score 16,239 to 17,894" in since["line"]   # the shown figures, not "score 37, the same"
    assert [b["text"] for b in since["bests"] if b["kind"] == "best"] == ["New best: 17,894"]


def test_a_month_record_follows_the_shown_measure(tmp_path: Path) -> None:
    facts = _facts(tmp_path, {"value": 50, "grade": "F"}, TRIGGER)
    records = history_recap._records({"entry_id": "squat", "name": "Squat", "facts": facts}, "2026-11")
    assert [(r["take"], r["shown"]["figures"]) for r in records] == [(2, "16,239")]


def test_clip_order_best_and_worst_follow_the_shown_measure() -> None:
    plain = lambda n: {**PLAIN50, "figures": str(n), "measure": n}  # noqa: E731
    rows = [{"take": 1, "score": 50, "shown": plain(50)}, {"take": 2, "score": 37, "shown": CREDIT},
            {"take": 3, "score": 70, "shown": plain(70)}, {"take": 4, "score": 40, "shown": plain(40)}]
    assert history_prompt.clip_order(rows) == [1, 4, 2, 3]   # first, latest, best (72.6% beats 70), then the rest newest first


def test_the_report_guard_accepts_the_cited_takes_shown_figures(tmp_path: Path) -> None:
    facts = _facts(tmp_path, TRIGGER)
    ctx = history_guard._Context(facts, None, None)
    cite = [{"take": 1}]
    assert history_guard._rule4("Take 1 earned 16,239 of 22,367 points.", cite, ctx) is None
    assert history_guard._rule4("Take 1 scored 37.", cite, ctx) is None   # Part 5's own score stays allowed
    assert history_guard._rule4("Take 1 earned 16,240 points.", cite, ctx) is not None   # negative: a figure not shown


def test_the_ask_guard_reads_score_up_from_the_shown_measure() -> None:
    a = {"take": 1, "score": 50, "shown": PLAIN50, "section_key": "full", "mode": "fitness", "score_version": "v3"}
    b = {"take": 2, "score": 37, "shown": CREDIT, "section_key": "full", "mode": "fitness", "score_version": "v3"}
    assert history_ask_guard._score_moved(a, b) == "up"
    assert history_ask_guard._score_moved(b, a) == "down"


# ----- L7: the history report's model reads the shown score ------------------------------------------------------------
def test_the_built_prompt_input_carries_the_shown_score(tmp_path: Path) -> None:
    facts = _facts(tmp_path, {"value": 50, "grade": "F"}, TRIGGER)
    rows = [{"take": t["take"], "job_id": t["job_id"], "duration_s": 10.0, "score": t["score"], "private": False, "clip": None} for t in facts["takes"]]
    packed = history_prompt.pack("squat", facts, rows)
    digests = [json.loads(i["text"].split(": ", 1)[1]) for i in packed["content"] if i["type"] == "text" and " digest (JSON): " in i["text"]]
    latest = next(d for d in digests if d["take"] == 2)
    assert latest["shown"] == {"letter": "C", "figures": "16,239", "unit": "points", "capped": False}
    assert (latest["score"], latest["grade"]) == (37, "F")   # beside Part 5's own value and grade
    assert "shown" in packed["manifest"]["fields"]
    assert "A digest's shown is the score the student's page shows" in packed["content"][0]["text"]  # the instructions say what it is
