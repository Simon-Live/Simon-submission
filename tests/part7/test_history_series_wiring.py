"""TICKET-218 wiring: the series in the fact table, the guard's plateau and early_sign kinds, the prompt digest, the reel pick,
and Part 5's corrections (the simon.score.v1 rescale of 2026-10-30; an absent fault counts only from a take with status ok).

Answers below are HAND-WRITTEN TEST FIXTURE text, not model output.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from part7 import history_facts, history_guard, history_prompt, history_reel
from test_history_series import _take

WORDS = history_guard.DEFAULT_WORDS
HIP = [("hip", "center", 10.0)]


def _facts(tmp_path: Path, takes: list[dict[str, Any]]) -> dict[str, Any]:
    return history_facts.build(takes, "body-squat-19b06562")


def _plateau_takes(tmp_path: Path) -> list[dict[str, Any]]:
    """Five takes: hip 20, then 10 four times on four days (a plateau, and the table calls it `improved`)."""
    return [_take(tmp_path, i + 1, [("hip", "center", size)]) for i, size in enumerate([20.0, 10.0, 10.0, 10.0, 10.0])]


def _early_takes(tmp_path: Path) -> list[dict[str, Any]]:
    return [_take(tmp_path, 1, near=[("hip", "center")]), _take(tmp_path, 2, HIP), _take(tmp_path, 3, HIP)]


def _trend(kind: str, text: str, cites: list[dict[str, Any]]) -> dict[str, Any]:
    return {"trends": [{"kind": kind, "measure": "hip", "side": "center", "text": text, "cites": cites}]}


def _kept(answer: dict[str, Any], facts: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    kept, rejected = history_guard.check(answer, facts, None, WORDS)
    return kept["trends"], [r for r in rejected if r["item"].startswith("trends")]


# ----- 1: facts.build carries the series ---------------------------------------------------------------
def test_the_fact_table_carries_the_series(tmp_path: Path) -> None:
    facts = _facts(tmp_path, _plateau_takes(tmp_path))
    assert facts["series"]["format"] == "simon.history.series.v1" and facts["series"]["plateaus"][0]["takes"] == [2, 3, 4, 5]
    assert "series" not in history_facts.table(_plateau_takes(tmp_path))  # the table alone is what the series reads
    assert history_facts.build([])["series"]["hidden"] is True


# ----- 2: the guard ---------------------------------------------------------------------------------------
def test_guard_keeps_a_plateau_the_series_lists(tmp_path: Path) -> None:
    facts = _facts(tmp_path, _plateau_takes(tmp_path))
    assert next(m for m in facts["measures"] if m["measure"] == "hip")["status"] == "improved"
    trends, rejected = _kept(_trend("plateau", "Hip has stayed about the same in takes 2, 3, 4 and 5.", [{"take": 2, "at_s": 2.0}, {"take": 3}, {"take": 4}, {"take": 5, "at_s": 2.0}]), facts)
    assert [t["kind"] for t in trends] == ["plateau"] and rejected == []


def test_guard_keeps_a_plateau_on_a_persistent_fault(tmp_path: Path) -> None:  # an unchanged fault is a plateau
    facts = _facts(tmp_path, [_take(tmp_path, i + 1, HIP) for i in range(4)])
    assert next(m for m in facts["measures"] if m["measure"] == "hip")["status"] == "persistent"
    text = "Hip has stayed about the same in takes 1, 2, 3 and 4."
    trends, rejected = _kept(_trend("plateau", text, [{"take": 1}, {"take": 2}, {"take": 3}, {"take": 4, "at_s": 2.0}]), facts)
    assert [t["kind"] for t in trends] == ["plateau"] and rejected == []
    other_side = _kept({"trends": [{**_trend("plateau", text, [{"take": 1}, {"take": 4}])["trends"][0], "side": "left"}]}, facts)
    assert other_side[0] == [] and other_side[1][0]["rule"] == 3  # negative: the series lists no left hip plateau


def test_guard_rejects_a_plateau_the_series_does_not_list(tmp_path: Path) -> None:  # negative
    facts = _facts(tmp_path, [_take(tmp_path, i + 1, [("hip", "center", s)]) for i, s in enumerate([30.0, 20.0, 10.0, 5.0, 2.0])])
    trends, rejected = _kept(_trend("plateau", "Hip has stayed about the same across takes 1 to 5.", [{"take": 1}, {"take": 5}]), facts)
    assert trends == [] and rejected[0]["rule"] == 3
    other = _facts(tmp_path, _plateau_takes(tmp_path))
    trends, rejected = _kept(_trend("plateau", "Hip has stayed about the same across takes 1 to 5.", [{"take": 1}, {"take": 5}]), other)
    assert trends == [] and rejected[0]["rule"] == 3  # take 1 is not one of the plateau's takes


def test_guard_keeps_an_early_sign_citing_a_near_miss_without_a_time(tmp_path: Path) -> None:
    facts = _facts(tmp_path, _early_takes(tmp_path))
    assert facts["series"]["early_signs"][0]["near_take"] == 1
    text = "Hip was a close call in take 1 and shows in take 2."
    trends, rejected = _kept(_trend("early_sign", text, [{"take": 1, "at_s": None}, {"take": 2, "at_s": 2.0}]), facts)
    assert [t["kind"] for t in trends] == ["early_sign"] and rejected == []
    assert trends[0]["cites"] == [{"take": 1}, {"take": 2, "at_s": 2.0}]


def test_guard_rejects_an_early_sign_with_a_time_on_the_near_miss_or_no_such_pair(tmp_path: Path) -> None:  # negative
    facts = _facts(tmp_path, _early_takes(tmp_path))
    text = "Hip was a close call in take 1 and shows in take 2."
    timed = _kept(_trend("early_sign", text, [{"take": 1, "at_s": 2.0}, {"take": 2, "at_s": 2.0}]), facts)
    assert timed[0] == [] and timed[1][0]["rule"] in (2, 3)
    wrong = _kept(_trend("early_sign", "Hip was a close call in take 2 and shows in take 3.", [{"take": 2}, {"take": 3, "at_s": 2.0}]), facts)
    assert wrong[0] == [] and wrong[1][0]["rule"] == 3


def test_guard_still_rejects_an_unknown_kind(tmp_path: Path) -> None:
    facts = _facts(tmp_path, _early_takes(tmp_path))
    assert _kept(_trend("progress", "Hip is better in take 3.", [{"take": 3, "at_s": 2.0}]), facts)[0] == []


# ----- 3: the prompt ------------------------------------------------------------------------------------
def _packed(tmp_path: Path, takes: list[dict[str, Any]]) -> list[str]:
    facts = _facts(tmp_path, takes)
    rows = [{"take": t["take"], "job_id": f"job{t['take']:09d}", "duration_s": 9.0, "score": 70, "private": False, "clip": None} for t in takes]
    packed = history_prompt.pack("e1", facts, rows)
    return [c["text"] for c in packed["content"] if c["type"] == "text"]


def test_prompt_version_enum_and_series_digest_before_the_latest_take(tmp_path: Path) -> None:
    assert history_prompt.PROMPT_VERSION == "history.v6"
    assert history_prompt.SCHEMA["properties"]["trends"]["items"]["properties"]["kind"]["enum"][-2:] == ["plateau", "early_sign"]
    texts = _packed(tmp_path, _plateau_takes(tmp_path))
    at = next(i for i, t in enumerate(texts) if t.startswith("Series (JSON): "))
    assert texts[at + 1] == history_prompt.LATEST_MARK and texts[-1] == history_prompt.TASK
    assert json.loads(texts[at][len("Series (JSON): "):])["plateaus"][0]["takes"] == [2, 3, 4, 5]


def test_prompt_has_no_series_item_when_there_is_nothing_to_say(tmp_path: Path) -> None:  # negative
    texts = _packed(tmp_path, [_take(tmp_path, 1, HIP), _take(tmp_path, 2, HIP)])
    assert not any(t.startswith("Series (JSON): ") for t in texts)


# ----- 7: the reel ----------------------------------------------------------------------------------------
def test_reel_pick_includes_the_ends_of_a_plateau() -> None:
    rows = [{"take": n, "job_id": f"job{n:09d}", "duration_s": 10.0, "score": 70, "private": False, "clip": f"/c/{n}.mp4"} for n in range(1, 11)]
    facts = {"measures": [], "series": {"plateaus": [{"takes": [4, 5, 6, 7]}]}}
    assert {4, 7} <= set(history_reel.select_takes(rows, facts))
    assert not {4, 7} <= set(history_reel.select_takes(rows, {"measures": []}))  # without the series the spare slots go elsewhere


# ----- 6: Part 5's corrections ------------------------------------------------------------------------------
def _v1(tmp_path: Path, scores: list[int], days: list[int]) -> list[dict[str, Any]]:
    takes = []
    for i, (score, day) in enumerate(zip(scores, days)):
        # the analysis carries the take's own score, as a real copy does (one-letter.md L3: the best reads the shown measure)
        analysis_score = {"value": score, "timeline": [{"t_s": [0.0, 9.0], "compared": True, "misses": []}]}
        take = _take(tmp_path, i + 1, [], score=score, extra={"score": analysis_score})
        takes.append({**take, "score": score, "at": f"2026-{day // 100:02d}-{day % 100:02d}T10:00:00Z"})
    return takes


def test_v1_takes_split_at_the_rescale(tmp_path: Path) -> None:
    takes = _v1(tmp_path, [60, 62, 80, 82], [1027, 1029, 1030, 1101])
    rows = history_facts.build(takes)["takes"]
    assert [r["score_scale"].endswith("@before-rescale") for r in rows] == [True, True, False, False]
    assert history_facts.same_scale(rows[0], rows[1]) and history_facts.same_scale(rows[2], rows[3])
    assert not history_facts.same_scale(rows[1], rows[2])
    facts = history_facts.build(takes)
    assert facts["best"] == 4 and "from 80" in history_facts.fallback_summary(facts)["text"].replace("scored 80", "from 80")
    assert history_guard.fact_summary(facts)["cites"] == [{"take": 3}, {"take": 4}]  # the line is the new scale only
    assert history_facts.build(takes)["series"]["takes"] == [3, 4]


def test_v1_takes_on_one_side_of_the_rescale_stay_one_line(tmp_path: Path) -> None:  # negative
    takes = _v1(tmp_path, [60, 62, 64], [1101, 1102, 1103])
    rows = history_facts.build(takes)["takes"]
    assert all(history_facts.same_scale(rows[0], r) for r in rows)
    assert [c["take"] for c in history_guard.fact_summary(history_facts.build(takes))["cites"]] == [1, 2, 3]


def test_other_score_versions_are_not_split_by_date(tmp_path: Path) -> None:  # negative
    takes = [{**t, "score_version": "simon.score.v2:abcd1234"} for t in _v1(tmp_path, [60, 62, 80], [1027, 1029, 1101])]
    rows = history_facts.build(takes)["takes"]
    assert rows[0]["score_scale"] == "simon.score.v2:abcd1234" and history_facts.same_scale(rows[0], rows[2])


def _status_take(tmp_path: Path, n: int, code: str | None, faults: bool) -> dict[str, Any]:
    take = _take(tmp_path, n, [("hip", "center", 20.0)] if faults else [], day=10 + n, extra={"status": {"code": code}} if code else None)
    if code is None:
        doc = json.loads(Path(take["analysis"]).read_text())
        doc.pop("status", None)
        Path(take["analysis"]).write_text(json.dumps(doc))
    return take


def test_absent_fault_counts_as_fixed_only_when_the_later_takes_status_is_ok(tmp_path: Path) -> None:
    first = [_take(tmp_path, i + 1, [("hip", "center", s)], day=10 + i) for i, s in enumerate([20.0, 10.0])]
    gone = [*first[:2], _take(tmp_path, 3, [], day=13), _take(tmp_path, 4, [], day=14)]
    assert next(m for m in history_facts.build(gone)["measures"])["status"] == "fixed"
    for code in ("not_ok", None):
        bad = [*gone[:2], _status_take(tmp_path, 3, code, False), _status_take(tmp_path, 4, code, False)]
        assert next(m for m in history_facts.build(bad)["measures"])["status"] == "unverified"  # negative: nothing was compared


def test_a_take_that_is_not_ok_gives_a_series_point_of_none_not_zero(tmp_path: Path) -> None:
    takes = [_take(tmp_path, i + 1, HIP, day=10 + i) for i in range(3)] + [_status_take(tmp_path, 4, "failed", False)]
    (line,) = history_facts.build(takes)["series"]["measures"][0]["lines"]
    assert [p["value"] for p in line["points"]] == [10.0, 10.0, 10.0, None]


# ----- Part 5 absent_means: warnings, visibility, feet ------------------------------------------------------------------
def _gone_with(tmp_path: Path, extra: dict[str, Any], measure: str = "hip", side: str = "center") -> str:
    """Status of a fault of `measure` that was 20, 10, then absent in two takes whose analysis carries `extra`."""
    base = [_take(tmp_path, i + 1, [(measure, side, s)], day=10 + i) for i, s in enumerate([20.0, 10.0])]
    gone = [_take(tmp_path, n, [], day=10 + n, extra=extra) for n in (3, 4)]
    return next(m for m in history_facts.build(base + gone)["measures"])["status"]


def test_a_take_with_warnings_does_not_prove_a_fault_gone(tmp_path: Path) -> None:
    assert _gone_with(tmp_path, {}) == "fixed"
    assert _gone_with(tmp_path, {"warnings": []}) == "fixed"
    assert _gone_with(tmp_path, {"warnings": [{"code": "low_match", "text": "x"}]}) == "unverified"


def test_a_measure_excluded_for_visibility_is_not_gone(tmp_path: Path) -> None:
    other = {"diagnostics": {"visibility": {"usable_measures": 5, "excluded": ["right_knee_valgus"]}}}
    mine = {"diagnostics": {"visibility": {"usable_measures": 5, "excluded": ["left_knee_valgus"]}}}
    assert _gone_with(tmp_path, other, "knee_valgus", "left") == "fixed"
    assert _gone_with(tmp_path, mine, "knee_valgus", "left") == "unverified"
    centred = {"diagnostics": {"visibility": {"usable_measures": 5, "excluded": ["trunk_lean_forward"]}}}
    assert _gone_with(tmp_path, centred, "trunk_lean_forward", "center") == "unverified"


def test_a_foot_measure_is_gone_only_when_the_feet_were_compared(tmp_path: Path) -> None:
    assert _gone_with(tmp_path, {"diagnostics": {"feet": {"compared": ["left_foot_rotation"]}}}, "foot_rotation", "left") == "fixed"
    assert _gone_with(tmp_path, {"diagnostics": {"feet": {"compared": ["right_foot_rotation"]}}}, "foot_rotation", "left") == "unverified"
    assert _gone_with(tmp_path, {}, "foot_rotation", "left") == "unverified"      # no feet file: no foot measure was compared
    assert _gone_with(tmp_path, {}, "knee_valgus", "left") == "fixed"            # the feet list only matters for foot measures


def test_the_series_reads_the_same_rule(tmp_path: Path) -> None:
    takes = [_take(tmp_path, i + 1, [("hip", "center", 10.0)], day=10 + i) for i in range(3)]
    takes.append(_take(tmp_path, 4, [], day=14, extra={"warnings": [{"code": "low_match", "text": "x"}]}))
    (line,) = history_facts.build(takes)["series"]["measures"][0]["lines"]
    assert line["points"][-1]["value"] is None
