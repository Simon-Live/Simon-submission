"""TICKET-208: the fair score line. Facts marks, the digest, the guard's scale rule and the public take fields."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from history_support import ENTRY
from part7 import history_facts, history_guard, history_prompt, history_routes
from test_history_facts import _made


def _no_person(tmp_path: Path, take: int) -> dict[str, Any]:
    path = tmp_path / f"np{take}.json"
    doc = {"source": "part7", "faults": [], "score": {"version": "simon.score.v1", "value": 0, "grade": "F", "components": {}, "capped_by": ["no_person"]}}
    path.write_text(json.dumps(doc))
    return {"take": take, "analysis": path, "at": f"t{take}", "score": 0, "grade": "F", "duration_s": 5.0,
            "section_key": "full", "mode": "fitness", "score_version": "simon.score.v1"}


def _capped(tmp_path: Path, take: int, score: int, uncapped: int) -> dict[str, Any]:
    made = _made(tmp_path, take, score, [("knee", "left", 1.0, 20.0)])
    doc = json.loads(made["analysis"].read_text())
    doc["score"].update(fault_cap=89, uncapped={"value": uncapped, "grade": "A"})
    made["analysis"].write_text(json.dumps(doc))
    return made


def test_a_dance_take_that_scored_95_is_never_the_best_of_the_fitness_line(tmp_path: Path) -> None:  # AC-2
    dance = _made(tmp_path, 1, 95, [], mode="dance")
    fitness = [_made(tmp_path, 2, 70, []), _made(tmp_path, 3, 80, [])]
    facts = history_facts.build([dance, *fitness], ENTRY)
    assert facts["best"] == 3 and [t["in_group"] for t in facts["takes"]] == [False, True, True]
    assert "95" not in history_facts.fallback_summary(facts)["text"]


def test_no_person_takes_are_marked_and_never_in_the_line_or_the_group(tmp_path: Path) -> None:  # AC-5
    takes = [_made(tmp_path, 1, 60, []), _made(tmp_path, 2, 70, []), _no_person(tmp_path, 3)]
    facts = history_facts.build(takes, ENTRY)
    assert [t["no_person"] for t in facts["takes"]] == [False, False, True]
    assert facts["takes"][2]["in_group"] is False and facts["best"] == 2 and facts["latest"] == 3
    assert history_facts.fallback_summary(facts)["text"] == "Take 1 scored 60 and take 2 scored 70."
    assert all(t["score"] == 0 for t in facts["takes"] if t["no_person"])


def test_a_real_zero_from_part_5_is_not_no_person(tmp_path: Path) -> None:  # AC-5
    made = _made(tmp_path, 1, 0, [])
    doc = json.loads(made["analysis"].read_text())
    doc["source"] = "part5"
    made["analysis"].write_text(json.dumps(doc))
    assert history_facts.build([made], ENTRY)["takes"][0]["no_person"] is False


def test_uncapped_value_is_read_beside_the_capped_one(tmp_path: Path) -> None:  # AC-3
    facts = history_facts.build([_capped(tmp_path, 1, 89, 96), _made(tmp_path, 2, 80, [])], ENTRY)
    assert facts["takes"][0]["uncapped"] == {"value": 96, "grade": "A", "fault_cap": 89} and facts["takes"][1]["uncapped"] is None


def test_the_digest_carries_group_marks(tmp_path: Path) -> None:  # AC-6
    facts = history_facts.build([_made(tmp_path, 1, 60, [], score_version="simon.score.v1:aa"), _made(tmp_path, 2, 70, [], mode="dance")], ENTRY)
    for row in facts["takes"]:
        digest = json.loads(history_prompt._digest(row))
        assert {"section_key", "mode", "score_version", "in_group"} <= set(digest)
    assert json.loads(history_prompt._digest(facts["takes"][0]))["in_group"] is False


def _comparison(facts: dict[str, Any], text: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    answer = {"summary": {"text": text, "cites": [{"take": 1, "at_s": None}, {"take": 2, "at_s": None}]}, "trends": [], "observations": []}
    return history_guard.check(answer, facts, None, None)


def _table(**second: Any) -> dict[str, Any]:
    base = {"section_key": "full", "mode": "fitness", "score_version": "simon.score.v1:aa", "faults": [], "cues": []}
    return {"takes": [{**base, "take": 1, "score": 95, "duration_s": 5.0}, {**base, "take": 2, "score": 80, "duration_s": 5.0, **second}],
            "measures": [], "best": 1, "latest": 2}


def test_scale_rule_rejects_a_comparison_of_two_unlike_takes() -> None:  # AC-6 (-k scale)
    text = "Your score went from 95 in take 1 to 80 in take 2."
    for unlike in ({"mode": "dance"}, {"score_version": "simon.score.v3:bb"}, {"section_key": "s2of4"}, {"no_person": True}):
        kept, rejected = _comparison(_table(**unlike), text)
        assert kept["summary"]["source"] == "fact_table", unlike
        assert any(r["rule"] == 4 and "scored the same way" in r["reason"] for r in rejected), unlike


def test_scale_rule_keeps_a_comparison_of_like_takes_and_a_single_score() -> None:  # AC-6
    kept, rejected = _comparison(_table(), "Your score went from 95 in take 1 to 80 in take 2.")
    assert kept["summary"]["source"] == "model" and not rejected
    kept, _ = _comparison(_table(mode="dance"), "Take 2 scored 80.")
    assert kept["summary"]["source"] == "model"


def test_the_public_take_carries_the_marks_the_line_is_drawn_by(tmp_path: Path) -> None:  # AC-1
    facts = history_facts.build([_made(tmp_path, 1, 60, [], mode="dance"), _made(tmp_path, 2, 70, [])], ENTRY)
    take = {"take": 2, "job_id": "j" * 12, "at": "t2", "duration_s": 5.0, "score": 70, "grade": "B", "private": False, "clip": None}
    out = history_routes._public_take(ENTRY, take, facts["takes"][1])
    assert (out["section_key"], out["mode"], out["in_group"], out["no_person"], out["uncapped"]) == ("full", "fitness", True, False, None)
    assert "analysis" not in out and "path" not in json.dumps(out)
