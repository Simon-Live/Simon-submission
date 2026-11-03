"""check-7's quality gates on Part 5 1.13.0's block: level and score_cap (docs/specs/quality-cap.md AC-5)."""

from __future__ import annotations

import json
from typing import Any

from part7 import check7
import test_check7 as base

CLIPS, _analysis, _fault, _run = base.CLIPS, base._analysis, base._fault, base._run
_ignore_real_staging, clip_files = base._ignore_real_staging, base.clip_files  # the base file's autouse fixtures


def block(level: str, cap: int | None = None) -> dict[str, Any]:
    reasons = [] if level == "ok" else [{"code": "joints_unseen", "words": "Your left knee was out of view.", "value": 0.4, "threshold": 0.3}]
    return {"version": "simon.quality.v1", "level": level, "reasons": reasons, "signals": {}, "score_cap": cap}


def with_block(res: dict[str, Any], level: str, cap: int | None) -> dict[str, Any]:
    return {**res, "quality": block(level, cap)}


def good() -> dict[str, dict[str, Any]]:
    """The base takes, every follower `ok`, the degraded one a real major block that Part 7 caps."""
    out = {k: v for k, v in base._good().items() if k != "q.mp4"}
    for name in ("f1.mp4", "f2.mp4"):
        out[name] = with_block(out[name], "ok", None)
    out["q.mp4"] = with_block(_analysis([], score=88), "major", 59)
    return out


def twin(res: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(res))


def test_a_real_major_block_on_the_degraded_take_passes_every_quality_gate() -> None:
    m = _run(good(), twin(good()))
    assert m["gates"]["quality_degraded_major_capped"] and m["gates"]["quality_level_equal"] and m["gates"]["quality_cap_equal"]
    assert m["gates"]["quality_good_no_major"] and m["pass"] is True
    take = m["takes"][-1]
    assert take["quality_level_app"] == "major" and take["quality_score_cap_app"] == 59 and take["quality_cap_valid_level_app"]


def test_a_degraded_take_whose_block_is_ok_or_absent_fails_the_gate() -> None:
    for res in (with_block(_analysis([], score=88), "ok", None), _analysis([], score=88), with_block(_analysis([], score=88), "degraded", None)):
        a = good()
        a["q.mp4"] = res
        m = _run(a, twin(a))
        assert not m["gates"]["quality_degraded_major_capped"] and not m["pass"]


def test_a_major_block_with_a_wrong_cap_fails() -> None:
    a = good()
    a["q.mp4"] = with_block(_analysis([], score=88), "major", 60)
    m = _run(a, twin(a))
    assert not m["gates"]["quality_degraded_major_capped"] and not m["pass"]


def test_levels_that_differ_between_paths_fail() -> None:
    d = good()
    d["q.mp4"] = with_block(_analysis([], score=88), "degraded", None)
    m = _run(good(), d)
    assert not m["gates"]["quality_level_equal"] and not m["pass"]


def test_a_major_block_on_a_good_follower_fails_the_false_alarm_gate() -> None:
    a = good()
    a["f1.mp4"] = with_block(a["f1.mp4"], "major", 59)
    m = _run(a, twin(a))
    assert not m["gates"]["quality_good_no_major"] and not m["pass"]


def test_check7_keeps_the_gate_names_the_report_has_always_had() -> None:
    gates = _run(good(), twin(good()))["gates"]
    assert {"quality_major_codes_equal", "quality_cap_equal", "quality_good_no_major", "quality_degraded_major_capped"} <= set(gates)
    assert check7.passes(gates)
