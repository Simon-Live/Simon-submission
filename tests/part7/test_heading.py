"""TICKET-246 (docs/specs/heading-note.md): Part 5's heading signal, the judge view's hero rule and the quoted limit."""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest

from part7 import heading, judge_view, quality_cap

ROOT = Path(__file__).resolve().parents[2]
PART5 = ROOT / "modules" / "part-5"
needs_part5 = pytest.mark.skipif(not (PART5 / "part5" / "quality.json").is_file(), reason="modules/part-5 not checked out")


def block(deg: float | None, reason: bool | None = None) -> dict:
    reason = deg is not None and deg >= 5 if reason is None else reason
    reasons = [{"code": "heading_offset", "words": "The body was turned.", "value": deg, "threshold": 5.0}] if reason else []
    return {"version": "simon.quality.v1", "level": "degraded" if reasons else "ok", "reasons": reasons,
            "signals": {"heading_offset_deg": deg}, "score_cap": None}


@pytest.mark.parametrize("deg,rough", [(0.0, False), (2.9, False), (4.9, False), (5.0, True), (7.4, True), (41.5, True), (None, False)])
def test_rough_from_the_signal(deg: float | None, rough: bool) -> None:
    assert heading.is_rough(block(deg)) is rough


def test_the_reason_alone_is_rough_and_a_missing_block_is_not() -> None:
    assert heading.is_rough(block(None, reason=True)) is True
    assert heading.offset_of({"reasons": [{"code": "heading_offset", "value": 8.0}]}) == 8.0
    for nothing in (None, {}, {"signals": {"heading_offset_deg": True}}, "x"):
        assert heading.is_rough(nothing) is False


@pytest.mark.parametrize("deg,warned", [(0.0, False), (2.9, False), (7.4, True), (17.1, True)])
def test_a_take_from_another_angle_is_never_the_hero(tmp_path: Path, deg: float, warned: bool) -> None:
    # level "ok" on purpose: the heading alone decides, so a block whose level does not say it still keeps the take out
    quality = {**block(deg), "level": "ok"}
    assert judge_view._warned(tmp_path, {"score": 90, "quality": quality}) is warned  # negative: same angle, still a hero


def test_the_analysis_file_heading_also_warns(tmp_path: Path) -> None:
    doc = {"status": {"code": "ok"}, "score": {"value": 90}, "quality": {**block(9.0), "level": "ok"}}
    (tmp_path / "analysis.json").write_text(json.dumps(doc), encoding="utf-8")
    assert judge_view._warned(tmp_path, {"score": 90, "analysis": "analysis.json"}) is True


def test_a_note_not_a_cap() -> None:
    summary = {"score": 84, "grade": "B", "quality": block(41.5)}
    assert quality_cap.apply(summary) == summary  # the shown score and grade are Part 5's, unchanged


@needs_part5
def test_the_limits_are_part5s() -> None:
    limits = json.loads((PART5 / "part5" / "quality.json").read_text(encoding="utf-8"))
    found = [v for k, v in _walk(limits) if k == "heading_offset_deg" and isinstance(v, dict)]
    assert found == [{"degraded": heading.ROUGH_DEG, "major": None}]
    web = (ROOT / "web" / "heading-note.js").read_text(encoding="utf-8")
    assert re.search(r"export const ROUGH_DEG = 5;", web) and re.search(r"export const FAR_DEG = 15;", web)
    assert heading.FAR_DEG == 15.0


@needs_part5
def test_the_evaluation_quote_is_part5s_unchanged() -> None:
    spec = importlib.util.spec_from_file_location("eval_report", ROOT / "tools" / "eval_report.py")
    report = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(report)
    part5_doc = " ".join((PART5 / "docs" / "evaluation.md").read_text(encoding="utf-8").split())
    assert report.PART5_YAW_QUOTE in part5_doc
    for row in ("| `yaw_5` | all | 54 | 0 | 18 | 10 | -10 to 8 | 2 |", "| `yaw_15` | all | 54 | 0 | 43 | 34 | -34 to 11 | 29 |"):
        assert row in part5_doc
    assert report.HEADING_LIMIT in (ROOT / "docs" / "evaluation.md").read_text(encoding="utf-8")


def _walk(node):
    if isinstance(node, dict):
        for k, v in node.items():
            yield k, v
            yield from _walk(v)
