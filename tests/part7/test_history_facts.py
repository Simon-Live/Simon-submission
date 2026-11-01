"""The fact table (docs/specs/history.md "Facts", TICKET-180 AC-1), on real stored analyses and small made ones."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from history_support import ENTRY, FIRST, FIXTURES, SECOND
from part7 import history_facts


def _real(job: str, take: int) -> dict[str, Any]:
    return {"take": take, "analysis": FIXTURES / job / "analysis.json", "at": f"t{take}", "score": None, "grade": None,
            "duration_s": 9.9, "entry_id": ENTRY}


def _made(tmp_path: Path, take: int, score: int, faults: list[tuple[str, str, float, float]], cue: str = "Keep your chest up") -> dict[str, Any]:
    path = tmp_path / f"a{take}.json"
    doc = {"faults": [{"measure": m, "side": s, "at_s": at, "magnitude_deg": mag, "follower_t_s": [at, at + 1], "text_timed": f"{m} at {at} s", "cue": cue}
                      for m, s, at, mag in faults],
           "score": {"value": score, "timeline": [{"misses": [{"cue": cue}]}] if faults else [{"misses": []}]}}
    path.write_text(json.dumps(doc))
    return {"take": take, "analysis": path, "at": f"t{take}", "score": score, "grade": "B", "duration_s": 5.0}


def test_build_on_two_real_takes() -> None:  # AC-1
    first, second = _real(FIRST, 1), _real(SECOND, 2)
    first.update(score=100, grade="A")
    second.update(score=77, grade="C")
    facts = history_facts.build([first, second])
    assert facts["format"] == "simon.history.facts.v1" and facts["entry_id"] == ENTRY
    assert [t["faults"] for t in facts["takes"]][0] == []  # the 100 take has no fault
    (fault,) = facts["takes"][1]["faults"]
    assert (fault["measure"], fault["side"], fault["at_s"], fault["span"]) == ("trunk_lean_forward", "center", 0.9, [0.9, 3.2])
    assert fault["text_timed"] == "leaning forward more than the example at 0.9 s" and fault["cue"] == "Keep your chest up"
    assert facts["takes"][1]["cues"] == ["Keep your chest up"] and facts["takes"][0]["cues"] == []
    (measure,) = facts["measures"]
    assert (measure["measure"], measure["side"], measure["present_in"], measure["status"]) == ("trunk_lean_forward", "center", [2], "new")
    assert measure["first"]["take"] == measure["last"]["take"] == 2 and measure["first"]["magnitude"] == 21.4
    assert facts["best"] == 1 and facts["latest"] == 2


def test_status_improved_persistent_fixed_new(tmp_path: Path) -> None:  # AC-1
    takes = [
        _made(tmp_path, 1, 50, [("knee", "left", 1.0, 30.0), ("hip", "center", 2.0, 10.0), ("arm", "right", 3.0, 8.0)]),
        _made(tmp_path, 2, 60, [("knee", "left", 1.2, 20.0), ("hip", "center", 2.1, 10.0), ("arm", "right", 3.0, 8.0)]),
        _made(tmp_path, 3, 80, [("knee", "left", 1.1, 12.0), ("hip", "center", 2.0, 9.0), ("neck", "center", 4.0, 5.0)]),
    ]
    facts = history_facts.build(takes, ENTRY)
    got = {(m["measure"], m["side"]): m for m in facts["measures"]}
    assert got[("knee", "left")]["status"] == "improved" and got[("knee", "left")]["present_in"] == [1, 2, 3]
    assert got[("hip", "center")]["status"] == "persistent"
    assert got[("arm", "right")]["status"] == "fixed" and got[("arm", "right")]["last"]["take"] == 2
    assert got[("neck", "center")]["status"] == "new" and got[("neck", "center")]["first"]["at_s"] == 4.0
    assert facts["best"] == 3


def test_one_fault_per_measure_and_side_the_largest(tmp_path: Path) -> None:  # edge
    take = _made(tmp_path, 1, 70, [("knee", "left", 1.0, 5.0), ("knee", "left", 2.0, 9.0), ("knee", "right", 3.0, 4.0)])
    faults = history_facts.build([take], ENTRY)["takes"][0]["faults"]
    assert [(f["side"], f["at_s"]) for f in faults] == [("left", 2.0), ("right", 3.0)]


def test_bad_or_missing_analysis_gives_an_empty_row(tmp_path: Path) -> None:  # edge
    bad = tmp_path / "bad.json"
    bad.write_text("not json")
    row = history_facts.build([{"take": 1, "analysis": bad, "score": 3}, {"take": 2, "analysis": tmp_path / "gone.json", "score": None}], ENTRY)
    assert [t["faults"] for t in row["takes"]] == [[], []] and row["measures"] == []
    assert row["best"] == 1
    empty = history_facts.build([], ENTRY)
    assert empty["takes"] == [] and empty["best"] is None and empty["latest"] is None


def test_fallback_summary_and_trends(tmp_path: Path) -> None:  # AC-6 support
    takes = [_made(tmp_path, 1, 90, [("hip", "center", 2.0, 10.0)]), _made(tmp_path, 2, 60, [("hip", "center", 2.0, 10.0), ("neck", "center", 4.0, 5.0)]),
             _made(tmp_path, 3, 70, [("hip", "center", 2.5, 10.0)])]
    facts = history_facts.build(takes, ENTRY)
    summary = history_facts.fallback_summary(facts)
    assert summary["text"] == "Take 1 scored 90 and take 3 scored 70."  # the best take is the first, so no extra line
    assert summary["source"] == "fact_table" and summary["label"] == history_facts.SUMMARY_LABEL
    trends = history_facts.fallback_trends(facts)
    assert [(t["kind"], t["measure"]) for t in trends] == [("persistent", "hip"), ("fixed", "neck")]
    assert trends[0]["cites"] == [{"take": 3, "at_s": 2.5}] and "first showed in take 1" in trends[0]["text"]
    assert all(t["source"] == "fact_table" for t in trends)
    assert len(history_facts.fallback_trends({"measures": [{"measure": f"m{i}", "side": "center", "status": "new",
                                                            "first": {"take": 1, "at_s": None}, "last": {"take": 1, "at_s": None}} for i in range(9)]})) == 5
