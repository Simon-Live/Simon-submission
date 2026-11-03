"""The fault series (docs/specs/history-series.md, TICKET-218), on small made analyses."""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

from part7 import history_series

KNOWN = {"section_key": "full", "mode": "fitness", "score_version": "simon.score.v1:e818635b"}
ENTRY = "body-squat-19b06562"
Fault = tuple[str, str, float]  # measure, side, size in degrees


def _take(tmp_path: Path, n: int, faults: list[Fault] | None = None, *, day: int | None = None, near: list[tuple[str, str]] | None = None,
          tempo: float | None | str = "none", reps: list[Any] | None = None, extra: dict[str, Any] | None = None, **known: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "status": {"code": "ok"},
        "faults": [{"measure": m, "side": s, "at_s": 2.0, "magnitude_deg": size, "follower_t_s": [2.0, 3.0]} for m, s, size in faults or []],
        "score": {"value": 70, "timeline": [{"t_s": [0.0, 9.0], "compared": True, "misses": []}]},
    }
    if tempo != "none":
        doc["score"]["tempo"] = {"ratio": tempo, "cue": None}
    if near is not None:
        doc["diagnostics"] = {"near_misses": {"total": len(near), "omitted": 0, "items": [{"measure": m, "side": s} for m, s in near]}}
    if reps is not None:
        doc.setdefault("diagnostics", {})["guard"] = {"reps": reps}
    doc.update(extra or {})
    path = tmp_path / f"a{n}.json"
    path.write_text(json.dumps(doc))
    day = day if day is not None else n
    return {"take": n, "analysis": path, "at": f"2026-10-{day:02d}T10:00:00Z", "score": 70, "grade": "C", "private": False,
            "duration_s": 9.0, "entry_id": ENTRY, **{**KNOWN, **known}}


def _series(tmp_path: Path, sizes: list[float], **kw: Any) -> list[dict[str, Any]]:
    return [_take(tmp_path, i + 1, [("hip", "center", s)], **kw) for i, s in enumerate(sizes)]


def test_hidden_under_four_takes(tmp_path: Path) -> None:  # AC-1
    out = history_series.build(_series(tmp_path, [10, 10, 10]))
    assert out["format"] == "simon.history.series.v1" and out["hidden"] is True and out["entry_id"] == ENTRY
    assert out["measures"] == [] and out["plateaus"] == [] and out["tempo"] == {"hidden": True, "points": []}
    assert history_series.build([])["hidden"] is True


def test_series_has_a_point_per_take(tmp_path: Path) -> None:  # AC-1
    takes = _series(tmp_path, [20, 15, 12, 6])
    takes[2] = _take(tmp_path, 3)  # a take without the fault that compared its moment
    out = history_series.build(takes)
    assert out["hidden"] is False and out["takes"] == [1, 2, 3, 4]
    (measure,) = out["measures"]
    (line,) = measure["lines"]
    assert measure["measure"] == "hip" and line["side"] == "center" and line["unit"] == "deg"
    assert [p["value"] for p in line["points"]] == [20, 15, 0.0, 6] and line["present_in"] == [1, 2, 4]


def test_plateau_needs_four_takes_two_days_and_the_band(tmp_path: Path) -> None:  # AC-1
    flat = history_series.build(_series(tmp_path, [30, 12, 11, 13, 12]))
    (plateau,) = flat["plateaus"]
    assert plateau["takes"] == [2, 3, 4, 5] and plateau["days"] == 4 and plateau["unit"] == "deg" and plateau["cites"] == [{"take": t} for t in (2, 3, 4, 5)]
    assert flat["measures"][0]["lines"][0]["plateau"] is True
    assert history_series.build(_series(tmp_path, [12, 12, 12, 12 + history_series.NOISE_DEG]))["plateaus"] != []  # on the band edge
    assert history_series.build(_series(tmp_path, [12, 12, 12, 12 + history_series.NOISE_DEG + 0.5]))["plateaus"] == []  # beyond it
    assert history_series.build(_series(tmp_path, [20, 15, 10, 5]))["plateaus"] == []  # still falling


def test_plateau_on_one_day_is_not_a_plateau(tmp_path: Path) -> None:  # AC-1
    same_day = [_take(tmp_path, i, [("hip", "center", 12)], day=5) for i in range(1, 5)]
    assert history_series.build(same_day)["plateaus"] == []
    two_days = [_take(tmp_path, i, [("hip", "center", 12)], day=5 if i < 4 else 6) for i in range(1, 5)]
    assert history_series.build(two_days)["plateaus"][0]["days"] == 2


def test_plateau_needs_the_fault_in_every_one_of_the_four(tmp_path: Path) -> None:  # edge
    takes = _series(tmp_path, [12, 12, 12, 12])
    takes[1] = _take(tmp_path, 2)
    assert history_series.build(takes)["plateaus"] == []


def test_metres_unit_and_no_unit(tmp_path: Path) -> None:  # edge
    lateral = []
    for i in range(1, 5):
        take = _take(tmp_path, i, [("sway", "center", 0)])
        doc = json.loads(take["analysis"].read_text())
        doc["faults"][0] = {"measure": "sway", "side": "center", "at_s": 2.0, "lateral_m": 0.2 + 0.01 * i}
        take["analysis"].write_text(json.dumps(doc))
        lateral.append(take)
    (line,) = history_series.build(lateral)["measures"][0]["lines"]
    assert line["unit"] == "m" and history_series.build(lateral)["plateaus"][0]["unit"] == "m"
    bare = []
    for i in range(1, 5):
        take = _take(tmp_path, i + 10, [])
        take["analysis"].write_text(json.dumps({"faults": [{"measure": "x", "side": "center", "at_s": 1.0}], "score": {"timeline": []}}))
        bare.append(take)
    out = history_series.build(bare)
    assert out["measures"][0]["lines"][0]["unit"] is None and out["plateaus"] == []


def test_early_sign_cites_both_takes(tmp_path: Path) -> None:  # AC-2
    takes = [_take(tmp_path, 1, near=[("knee", "left")]), _take(tmp_path, 2, [("knee", "left", 9)], near=[("knee", "left")]),
             _take(tmp_path, 3, [("knee", "left", 9)])]
    (sign,) = history_series.build(takes)["early_signs"]  # shown under 4 takes
    assert (sign["measure"], sign["side"], sign["near_take"], sign["fault_take"]) == ("knee", "left", 1, 2)
    assert sign["cites"] == [{"take": 1}, {"take": 2, "at_s": 2.0}] and "take 1" in sign["text"] and "take 2" in sign["text"]
    assert history_series.build(takes[:1] + [_take(tmp_path, 2)])["early_signs"] == []  # no fault follows
    other_side = [_take(tmp_path, 1, near=[("knee", "left")]), _take(tmp_path, 2, [("knee", "right", 9)])]
    assert history_series.build(other_side)["early_signs"] == []


def test_early_sign_skips_another_section_and_private_takes(tmp_path: Path) -> None:  # AC-2
    takes = [_take(tmp_path, 1, near=[("knee", "left")]), _take(tmp_path, 2, [("knee", "left", 9)], private=True),
             _take(tmp_path, 3, [("knee", "left", 9)], section_key="s1of2")]
    assert history_series.build(takes)["early_signs"] == []


def test_tempo_points_leave_out_reps_with_null_timing(tmp_path: Path) -> None:  # AC-3
    reps = [{"span_s": [0, 1], "ok": True, "timing_corr": 0.9}, {"span_s": [1, 2], "ok": False, "timing_corr": None}]
    takes = [_take(tmp_path, 1, tempo=1.0), _take(tmp_path, 2, tempo=1.3, reps=reps),
             _take(tmp_path, 3, tempo=1.4, reps=[{"span_s": [0, 1], "ok": False, "timing_corr": None}]), _take(tmp_path, 4), _take(tmp_path, 5, tempo=0.7)]
    points = history_series.build(takes)["tempo"]["points"]
    assert [p["ratio"] for p in points] == [1.0, 1.3, None, None, 0.7]
    assert [p["note"] for p in points] == [None, "slow", None, None, "fast"]
    assert (points[1]["reps_used"], points[1]["reps_total"]) == (1, 2) and points[0]["reps_used"] is None and points[2]["reps_used"] == 0


def test_rehab_never_gets_a_slow_tempo_note(tmp_path: Path) -> None:  # AC-3
    slow = [_take(tmp_path, i, tempo=1.5, mode="rehab") for i in range(1, 5)]
    assert {p["note"] for p in history_series.build(slow)["tempo"]["points"]} == {None}
    by_profile = [_take(tmp_path, i + 10, tempo=1.5, extra={"profile": "rehab"}) for i in range(1, 5)]
    assert {p["note"] for p in history_series.build(by_profile)["tempo"]["points"]} == {None}
    assert {p["ratio"] for p in history_series.build(slow)["tempo"]["points"]} == {1.5}  # the size is still drawn
    fitness = [_take(tmp_path, i + 20, tempo=1.5) for i in range(1, 5)]
    assert {p["note"] for p in history_series.build(fitness)["tempo"]["points"]} == {"slow"}


def test_left_and_right_are_two_lines_and_a_note_needs_three_takes(tmp_path: Path) -> None:  # AC-4
    two = [_take(tmp_path, i, [("knee", "left", 10)] if i < 3 else []) for i in range(1, 5)]
    (measure,) = history_series.build(two)["measures"]
    assert [line["side"] for line in measure["lines"]] == ["left", "right"] and measure["side_note"] is None
    assert [p["value"] for p in measure["lines"][1]["points"]] == [None] * 4  # never showed on the right

    (tmp_path / "three").mkdir()
    three = [_take(tmp_path / "three", i, [("knee", "left", 10)] if i < 4 else [("knee", "right", 8)]) for i in range(1, 6)]
    (measure,) = history_series.build(three)["measures"]
    assert measure["side_note"]["side"] == "left" and measure["side_note"]["cites"] == [{"take": 1}, {"take": 2}, {"take": 3}]
    assert "differs more from the example" in measure["side_note"]["text"]

    (tmp_path / "both").mkdir()
    both = [_take(tmp_path / "both", i, [("knee", "left", 10), ("knee", "right", 9)]) for i in range(1, 5)]
    assert history_series.build(both)["measures"][0]["side_note"] is None  # both persist: no one-sided note
    center = history_series.build(_series(tmp_path, [5, 5, 5, 5]))["measures"][0]
    assert [line["side"] for line in center["lines"]] == ["center"] and center["side_note"] is None


def test_never_private_or_other_scale_takes(tmp_path: Path) -> None:  # constraints
    takes = _series(tmp_path, [10, 10, 10, 10, 10])
    takes[1]["private"] = True
    takes[2]["mode"] = "dance"
    takes[3]["score_version"] = "simon.score.v2:aaaaaaaa"
    out = history_series.build(takes)
    assert out["takes"] == [1, 5] and out["hidden"] is True
    unknown = _series(tmp_path, [10, 10, 10, 10], section_key=None)
    assert history_series.build(unknown)["takes"] == [] and history_series.build(unknown)["group"] is None


def test_older_analysis_without_new_fields(tmp_path: Path) -> None:  # edge
    takes = [_take(tmp_path, i, [("hip", "center", 10)]) for i in range(1, 5)]
    for take in takes:
        take["analysis"].write_text(json.dumps({"faults": [{"measure": "hip", "side": "center", "at_s": 2.0, "magnitude_deg": 10}]}))
    out = history_series.build(takes)
    assert {p["ratio"] for p in out["tempo"]["points"]} == {None} and out["early_signs"] == []
    bad = tmp_path / "bad.json"
    bad.write_text("nope")
    takes.append({**takes[0], "take": 5, "analysis": bad, "at": "2026-10-09T00:00:00Z"})
    assert history_series.build(takes)["takes"] == [1, 2, 3, 4, 5]


FORBIDDEN = re.compile(r"symmetr|percent|%|\bready\b|readiness|clearance|\bcleared\b|\b90\b|target", re.I)


def test_no_symmetry_percentage_target_line_or_ready_state(tmp_path: Path) -> None:  # AC-4
    takes = [_take(tmp_path, i, [("knee", "left", 12), ("hip", "center", 9)] + ([("knee", "right", 4)] if i < 3 else []), near=[("neck", "center")], tempo=1.3)
             for i in range(1, 7)]
    out = history_series.build(takes)
    assert out["plateaus"] and out["measures"][0]["side_note"] is not None
    text = json.dumps(out)
    assert not FORBIDDEN.search(text), FORBIDDEN.search(text)

    def keys(node: Any) -> set[str]:
        if isinstance(node, dict):
            return set(node) | {k for v in node.values() for k in keys(v)}
        return {k for v in node for k in keys(v)} if isinstance(node, list) else set()

    assert not [k for k in keys(out) if FORBIDDEN.search(k)]
    assert not re.search(r"[\u2013\u2014]| - ", text)  # writer rules: no em dash, en dash or spaced hyphen
