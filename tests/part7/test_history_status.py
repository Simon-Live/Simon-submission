"""TICKET-214: improved and fixed only after 3 takes beyond the noise band; 'fixed but still close' from near misses."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from history_support import ENTRY
from part7 import history_facts as hf, history_guard
from test_history_facts import _made

KNEE = "knee"


def _series(tmp_path: Path, sizes: list[float | None]) -> dict[str, Any]:
    """One knee fault per take at 2 s with the given size (None = no fault, compared)."""
    takes = [_made(tmp_path, n, 60 + n, [] if size is None else [(KNEE, "left", 2.0, size)]) for n, size in enumerate(sizes, 1)]
    return hf.build(takes, ENTRY)


def status(facts: dict[str, Any]) -> str | None:
    return next((m["status"] for m in facts["measures"] if m["measure"] == KNEE), None)


@pytest.mark.parametrize("sizes, expected", [
    ([20, 10, 8], "improved"),           # last two both more than the band below the first
    ([20, 12, 11.5], "improved"),
    ([20, 10], "too_few"),               # only two takes: a drop is not proven
    ([20, 20, 10], "too_few"),           # the second to last did not drop yet
    ([20, 18, 17.5], "persistent"),      # noise just under the band stays persistent
    ([20, 17.01, 17.01], "persistent"),
    ([20, 20, 20], "persistent"),
    ([20, 10, None], "fixed"),           # gone, and the take before it was well below the first
    ([20, None, None], "fixed"),
    ([20, None], "too_few"),
    ([20, 20, None], "too_few"),
    ([20, 18, None], "too_few"),         # 18 is inside the band of 20
    ([20, None, 15], "came_back"),
    ([2, None, None], "too_few"),        # a first size inside the band can never be called fixed
])
def test_the_status_rule(tmp_path: Path, sizes: list[float | None], expected: str) -> None:  # AC-1, AC-4, AC-5
    assert status(_series(tmp_path, sizes)) == expected


def test_the_noise_band_is_one_constant_per_unit() -> None:  # AC-2
    assert set(hf.NOISE_BAND) == {"deg", "m"} and hf.NOISE_BAND["deg"] > 0 and hf.NOISE_BAND["m"] > 0 and hf.MIN_GROUP_TAKES == 3


def _lateral(tmp_path: Path, n: int, metres: float | None, degrees: float | None = None) -> dict[str, Any]:
    made = _made(tmp_path, n, 70, [])
    fault: dict[str, Any] = {"measure": "foot_out", "side": "left", "at_s": 2.0, "follower_t_s": [2.0, 3.0], "text_timed": "x", "cue": "c"}
    if metres is not None:
        fault["lateral_m"] = metres
    if degrees is not None:
        fault["magnitude_deg"] = degrees
    doc = json.loads(made["analysis"].read_text())
    doc["faults"] = [fault] if (metres is not None or degrees is not None or n == 1) else []
    made["analysis"].write_text(json.dumps(doc))
    return made


def test_a_lateral_fault_uses_metres(tmp_path: Path) -> None:  # AC-2
    facts = hf.build([_lateral(tmp_path, 1, 0.20), _lateral(tmp_path, 2, 0.10), _lateral(tmp_path, 3, 0.08)], ENTRY)
    assert facts["measures"][0]["status"] == "improved" and facts["measures"][0]["first"]["unit"] == "m"
    near = hf.build([_lateral(tmp_path, 1, 0.20), _lateral(tmp_path, 2, 0.19), _lateral(tmp_path, 3, 0.18)], ENTRY)
    assert near["measures"][0]["status"] == "persistent"


def test_a_fault_with_no_size_is_never_improved_or_fixed(tmp_path: Path) -> None:  # AC-2
    gone = hf.build([_lateral(tmp_path, 1, None), _lateral(tmp_path, 2, None), _lateral(tmp_path, 3, None)], ENTRY)
    assert gone["measures"][0]["status"] == "unverified"  # present then absent: present or absent is all it can say
    assert hf.fallback_trends(gone) == []


def _close(made: dict[str, Any], measure: str, side: str) -> dict[str, Any]:
    doc = json.loads(made["analysis"].read_text())
    doc["diagnostics"] = {"near_misses": {"total": 1, "omitted": 0, "items": [{"measure": measure, "side": side}]}}
    made["analysis"].write_text(json.dumps(doc))
    return made


def test_fixed_but_still_close_names_the_take_and_time(tmp_path: Path) -> None:  # AC-3
    takes = [_made(tmp_path, 1, 61, [(KNEE, "left", 2.0, 20.0)]), _made(tmp_path, 2, 62, []), _close(_made(tmp_path, 3, 63, []), KNEE, "left")]
    facts = hf.build(takes, ENTRY)
    (measure,) = facts["measures"]
    assert measure["status"] == "fixed" and measure["still_close"] == {"take": 3, "at_s": 2.0}
    (trend,) = hf.fallback_trends(facts)
    assert trend["kind"] == "fixed" and trend["still_close"] is True and trend["cites"] == [{"take": 3, "at_s": 2.0}]
    assert "came close" in trend["text"]


def test_a_near_miss_of_another_side_or_measure_does_not_count(tmp_path: Path) -> None:  # AC-3
    for measure, side in ((KNEE, "right"), ("hip", "left")):
        takes = [_made(tmp_path, 1, 61, [(KNEE, "left", 2.0, 20.0)]), _made(tmp_path, 2, 62, []), _close(_made(tmp_path, 3, 63, []), measure, side)]
        assert "still_close" not in hf.build(takes, ENTRY)["measures"][0]


def test_a_near_miss_without_a_fixed_fault_adds_nothing(tmp_path: Path) -> None:  # AC-3
    takes = [_made(tmp_path, 1, 61, [(KNEE, "left", 2.0, 20.0)]), _made(tmp_path, 2, 62, [(KNEE, "left", 2.0, 20.0)]),
             _close(_made(tmp_path, 3, 63, [(KNEE, "left", 2.0, 19.0)]), KNEE, "left")]
    assert "still_close" not in hf.build(takes, ENTRY)["measures"][0]


def test_the_guard_rejects_a_claim_that_contradicts_the_status(tmp_path: Path) -> None:  # AC-6
    facts = _series(tmp_path, [20, 10])           # too_few
    trend = {"kind": "improved", "measure": KNEE, "side": "left", "text": "The knee fault is smaller in take 2.", "cites": [{"take": 2, "at_s": 2.0}]}
    kept, rejected = history_guard.check({"summary": None, "trends": [trend]}, facts, None, None)
    assert kept["trends"] == [] and any(r["rule"] == 3 for r in rejected)
    ok = _series(tmp_path, [20, 10, 8])           # improved
    kept, _ = history_guard.check({"summary": None, "trends": [trend]}, ok, None, None)
    assert [t["kind"] for t in kept["trends"]] == ["improved"]
