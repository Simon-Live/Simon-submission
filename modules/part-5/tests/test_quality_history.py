"""TICKET-079, AC-Q10: the contract says what `quality` is (ADR-0021, docs/specs/quality.md).

`contracts/history-fields.json` 1.2.0 lists every `quality` path from 1.13.0 (the version stays 1.2.0: the unpublished
`score.credit` work set it and both ship together in schema 1.13.0), the schema, CONTRACT.md and docs/schemas.md say the block is
detected by presence, that absent means not assessed and that the cap is reported only.

Like the files it sits beside (tests/test_contract_history_fields.py, tests/test_score_credit_history.py), it reads the files and
imports nothing from `part5`."""
import re
from pathlib import Path

import jsonschema
import pytest

from test_contract_history_fields import BY_PATH, HISTORY, schema_node
from test_contract_part7_history import SCHEMA

ROOT = Path(__file__).resolve().parent.parent
CONTRACT_MD = (ROOT / "CONTRACT.md").read_text(encoding="utf-8")
SCHEMAS_MD = (ROOT / "docs/schemas.md").read_text(encoding="utf-8")
BLOCK_KEYS = ("version", "level", "reasons", "signals", "score_cap")
SIGNALS = ("unseen_joint_share", "missing_joint_share", "missing_frame_share", "hidden_measure_share", "position_jitter_mm")
HEADING = "heading_offset_deg"   # 1.14.0 (TICKET-086): in the schema's properties, not its required list; dated 1.14.0
REASON_KEYS = ("code", "words", "value", "threshold", "joint")
CODES = ("not_enough_visible", "moving_part_out_of_frame", "no_usable_measures", "joints_unseen", "joints_missing",
         "frames_missing", "measures_hidden", "position_jitter", "heading_offset")
# Every path the history file lists for the block: the block, its keys, a reason and its keys, and each signal.
QUALITY_PATHS = {"quality", *(f"quality.{k}" for k in BLOCK_KEYS), "quality.reasons[]",
                 *(f"quality.reasons[].{k}" for k in REASON_KEYS), *(f"quality.signals.{s}" for s in (*SIGNALS, HEADING))}
VALIDATOR = jsonschema.Draft202012Validator(SCHEMA)
GOOD = {"version": "simon.quality.v1", "level": "major", "score_cap": 59,
        "reasons": [{"code": "joints_unseen", "words": "29 percent of the joint readings were outside the picture.",
                     "value": 0.2941, "threshold": 0.2, "joint": "nose"}],
        "signals": {"unseen_joint_share": 0.2941, "missing_joint_share": 0.0, "missing_frame_share": 0.0,
                    "hidden_measure_share": None, "position_jitter_mm": 14.2}}


def test_the_schema_holds_exactly_the_block_keys_and_codes_pinned_here():
    """A new key, signal or code fails here until it is listed in the history file and added above."""
    block = schema_node("quality")
    assert set(block["properties"]) == set(BLOCK_KEYS) and block["required"] == list(BLOCK_KEYS)
    assert set(schema_node("quality.signals")["properties"]) == {*SIGNALS, HEADING}
    assert schema_node("quality.signals")["required"] == list(SIGNALS)
    assert set(schema_node("quality.reasons[]")["properties"]) == set(REASON_KEYS)
    assert schema_node("quality.reasons[]")["required"] == ["code", "words", "value", "threshold"]
    assert tuple(schema_node("quality.reasons[].code")["enum"]) == CODES


def test_the_block_is_optional_in_the_schema():
    """Detect it by presence: the schema does not require it, and a document without it still validates."""
    assert "quality" not in SCHEMA["required"] and "quality" in SCHEMA["properties"]
    assert SCHEMA["version"] == "1.14.0"   # the block arrived in 1.13.0 with score.credit (no bump of its own)


def test_low_match_is_not_a_reason_code():
    assert "low_match" not in schema_node("quality.reasons[].code")["enum"]


def test_the_file_lists_every_quality_path_from_1_13_0_and_keeps_its_version():
    assert QUALITY_PATHS <= set(BY_PATH), sorted(QUALITY_PATHS.difference(BY_PATH))
    assert {p for p in BY_PATH if p == "quality" or p.startswith("quality.")} == QUALITY_PATHS
    assert len(QUALITY_PATHS) == 18
    assert {BY_PATH[p]["since"] for p in QUALITY_PATHS} - {BY_PATH[f"quality.signals.{HEADING}"]["since"]} == {"1.13.0"}
    assert BY_PATH[f"quality.signals.{HEADING}"]["since"] == "1.14.0"
    others = {p for p, f in BY_PATH.items() if f["since"] == "1.13.0" and p not in QUALITY_PATHS}
    assert all(p.startswith("score.credit") for p in others), sorted(others)   # the other 1.13.0 addition is the credit
    assert HISTORY["version"] == "1.3.0" and HISTORY["analysis_schema_version"] == "1.14.0" == SCHEMA["version"]


@pytest.mark.parametrize("path", sorted(QUALITY_PATHS))
def test_a_quality_path_is_conditional_and_additive_and_says_when(path):
    entry = BY_PATH[path]
    assert entry["presence"] == "conditional" and entry["stability"] == "additive"
    assert entry["present_when"].strip()
    assert entry["since"] == ("1.14.0" if path == f"quality.signals.{HEADING}" else "1.13.0")


def test_the_block_entry_says_absent_means_not_assessed_and_reported_only():
    entry = BY_PATH["quality"]
    assert "Absent means not assessed" in entry["present_when"] and "Detect it by presence" in entry["present_when"]
    assert "Reported only" in entry["notes"] and "Part 7 applies score_cap" in entry["notes"]
    assert "never adds a warnings entry" in entry["notes"]
    assert "do not read it as ok" in entry["notes"]


def test_the_cap_entry_is_59_reported_only_and_not_applied_by_part_5():
    entry = BY_PATH["quality.score_cap"]
    assert "59 when level is major, else null" in entry["meaning"]
    assert "Reported only" in entry["notes"] and "Part 5 does not apply it" in entry["notes"]


def test_the_code_entry_names_the_codes_of_the_schema_and_says_low_match_is_not_one():
    meaning = BY_PATH["quality.reasons[].code"]["meaning"]
    assert [c for c in re.findall(r"[a-z_]+", meaning) if c in CODES] == list(CODES)
    assert "low_match is never a reason" in BY_PATH["quality.reasons[].code"]["notes"]


def test_a_signal_entry_says_null_means_not_measurable_and_never_zero():
    for s in (*SIGNALS, HEADING):
        assert "never 0" in BY_PATH[f"quality.signals.{s}"]["notes"], s
    assert BY_PATH["quality.signals.position_jitter_mm"]["units"] == "millimetres"


def test_the_jitter_entry_says_per_frame_so_it_compares_only_at_one_frame_rate():
    assert "per frame" in BY_PATH["quality.signals.position_jitter_mm"]["notes"]


def test_contract_md_gives_the_duty_and_says_the_cap_is_reported_only():
    duty = re.search(r"^12\. \*\*Read `quality`.*$", CONTRACT_MD, re.M).group(0)
    for phrase in ("detect it by presence", "read a document without it as not assessed", "The cap is reported only.",
                   "`score_cap` is 59 when `level` is `major` and `null` otherwise", "never adds a `warnings` entry",
                   "`low_match` is not a quality reason", "apply `score_cap` yourself", "`part5/quality.json`"):
        assert phrase in duty, phrase
    assert all(f"`{code}`" in duty for code in CODES)


def test_contract_md_lists_the_row_and_the_doctor_note():
    assert "| Part 5 `analysis.json` `quality` |" in CONTRACT_MD
    assert "The same command notes `quality`" in CONTRACT_MD and "not assessed" in CONTRACT_MD


def test_schemas_md_has_the_section_with_the_same_rules():
    section = SCHEMAS_MD.split("## Quality: `quality`", 1)[1].split("\n## ", 1)[0]
    for phrase in ("detect it by presence", "**not assessed**", "**reported only**", "never adds a `warnings` entry",
                   "`low_match` is never a reason", "names no cause", "`part5/quality.json`", "never 0"):
        assert phrase in section, phrase
    assert all(f"`{code}`" in section for code in CODES)


def test_a_hand_built_block_validates_and_the_schema_refuses_a_bad_one():
    doc = {"format": "simon.analysis.v1", "expected": {"path": "e"}, "follower": {"path": "f"}, "faults": []}
    assert list(VALIDATOR.iter_errors(dict(doc, quality=GOOD))) == []
    assert list(VALIDATOR.iter_errors(doc)) == []   # absent: not assessed
    for bad in (dict(GOOD, score_cap=None), dict(GOOD, level="degraded"), dict(GOOD, reasons=[]), dict(GOOD, level="ok"),
                dict(GOOD, version="simon.quality.v2"), dict(GOOD, level="bad"),
                dict(GOOD, reasons=[dict(GOOD["reasons"][0], code="low_match")]),
                dict(GOOD, reasons=[dict(GOOD["reasons"][0], words="")]),
                dict(GOOD, reasons=[dict(GOOD["reasons"][0], joint="head")]),
                dict(GOOD, signals={k: v for k, v in GOOD["signals"].items() if k != "position_jitter_mm"}),
                dict(GOOD, signals=dict(GOOD["signals"], missing_joint_share=1.5))):
        assert list(VALIDATOR.iter_errors(dict(doc, quality=bad))), bad
