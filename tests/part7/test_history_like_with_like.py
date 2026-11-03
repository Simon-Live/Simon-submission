"""TICKET-206 (a): the fact table compares like with like (docs/specs/history.md "Like with like").

Takes are made small analyses, not model output; the section, mode and score version are what `history_store` records.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from history_support import ENTRY
from part7 import history_facts
from test_history_facts import _made


def _status_of(facts: dict[str, Any], measure: str, side: str = "center") -> str | None:
    return next((m["status"] for m in facts["measures"] if (m["measure"], m["side"]) == (measure, side)), None)


def test_fixed_needs_a_later_take_that_compared_the_moment(tmp_path: Path) -> None:
    fault = [("knee", "left", 6.0, 20.0)]
    short = _made(tmp_path, 2, 80, [], window=(0.0, 3.0))   # compared only the first 3 s: it never looked at 6 s
    full = _made(tmp_path, 3, 85, [], window=(0.0, 9.0))
    assert _status_of(history_facts.build([_made(tmp_path, 1, 60, fault), short], ENTRY), "knee", "left") == "unverified"
    assert _status_of(history_facts.build([_made(tmp_path, 1, 60, fault), short, full], ENTRY), "knee", "left") == "too_few"  # take 2 never looked
    assert _status_of(history_facts.build([_made(tmp_path, 1, 60, fault), _made(tmp_path, 2, 80, []), full], ENTRY), "knee", "left") == "fixed"
    none = _made(tmp_path, 2, 80, [], window=None)  # a take with no compared window says nothing
    assert _status_of(history_facts.build([_made(tmp_path, 1, 60, fault), none], ENTRY), "knee", "left") == "unverified"


def test_unverified_is_not_a_trend_and_not_fixed(tmp_path: Path) -> None:
    facts = history_facts.build([_made(tmp_path, 1, 60, [("knee", "left", 6.0, 20.0)]), _made(tmp_path, 2, 80, [], window=(0.0, 3.0))], ENTRY)
    assert history_facts.fallback_trends(facts) == []


def test_came_back_after_a_compared_absence(tmp_path: Path) -> None:
    fault = [("knee", "left", 2.0, 20.0)]
    takes = [_made(tmp_path, 1, 60, fault), _made(tmp_path, 2, 80, []), _made(tmp_path, 3, 70, fault)]
    facts = history_facts.build(takes, ENTRY)
    assert _status_of(facts, "knee", "left") == "came_back"
    (trend,) = history_facts.fallback_trends(facts)
    assert trend["kind"] == "came_back" and "showed in take 1" in trend["text"] and "back in take 3" in trend["text"]
    # present, then absent in a take that did not compare the moment, then present: persistent, not came_back
    takes = [_made(tmp_path, 1, 60, fault), _made(tmp_path, 2, 80, [], window=(5.0, 9.0)), _made(tmp_path, 3, 70, fault)]
    assert _status_of(history_facts.build(takes, ENTRY), "knee", "left") == "persistent"


def test_other_sections_and_modes_never_pool(tmp_path: Path) -> None:
    fault = [("knee", "left", 2.0, 20.0)]
    s1 = _made(tmp_path, 1, 90, fault, section_key="s1of3")
    dance = _made(tmp_path, 2, 40, [], mode="dance")
    old = _made(tmp_path, 3, 99, [], section_key=None, mode=None, score_version=None)  # a record from before TICKET-206
    full_a, full_b, full_c = _made(tmp_path, 4, 70, fault), _made(tmp_path, 5, 75, []), _made(tmp_path, 6, 72, [])
    facts = history_facts.build([s1, dance, old, full_a, full_b, full_c], ENTRY)
    assert facts["group"] == {"section": "full", "mode": "fitness"}
    assert [t["in_group"] for t in facts["takes"]] == [False, False, False, True, True, True]
    assert _status_of(facts, "knee", "left") == "fixed" and facts["measures"][0]["present_in"] == [4]
    assert facts["best"] == 5 and facts["latest"] == 6   # not the 99 of the unknown record, not the 90 of another section
    assert history_facts.fallback_summary(facts)["text"] == "Take 4 scored 70 and take 6 scored 72. The best was take 5, 75."


def test_unknown_latest_take_makes_no_claims(tmp_path: Path) -> None:
    unknown = _made(tmp_path, 2, 80, [], section_key=None, mode=None, score_version=None)
    facts = history_facts.build([_made(tmp_path, 1, 60, [("knee", "left", 2.0, 20.0)]), unknown], ENTRY)
    assert facts["group"] is None and facts["measures"] == [] and facts["best"] is None
    assert history_facts.fallback_summary(facts)["text"] == "Take 2 scored 80."


def test_a_changed_score_version_is_not_one_score_line(tmp_path: Path) -> None:
    old = _made(tmp_path, 1, 90, [], score_version="simon.score.v1:aaaaaaaa")
    facts = history_facts.build([old, _made(tmp_path, 2, 70, [])], ENTRY)
    assert facts["best"] == 2 and history_facts.fallback_summary(facts)["text"] == "Take 2 scored 70."
