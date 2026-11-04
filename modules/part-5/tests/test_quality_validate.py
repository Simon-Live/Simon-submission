"""TICKET-079, AC-Q01 and AC-Q11: `output.validate_analysis` accepts a well-formed `quality` block, leaves a document without one
exactly as it was (absent means not assessed), and refuses every block that contradicts itself (ADR-0021)."""
import copy
import json
from pathlib import Path

import jsonschema
import pytest

from part5 import output
from part5.output import OutputError, build_analysis, validate_analysis

ROOT = Path(__file__).resolve().parent.parent
GOLDEN = json.loads((ROOT / "fixtures/output/analysis.no-faults.example.json").read_text())
SCHEMA_VALIDATOR = jsonschema.Draft202012Validator(json.loads((ROOT / "contracts/analysis.schema.json").read_text()))
SIGNALS = {"unseen_joint_share": None, "missing_joint_share": 0.0, "missing_frame_share": 0.0, "hidden_measure_share": None,
           "position_jitter_mm": 12.3, "heading_offset_deg": 1.2}   # the last from 1.14.0 (TICKET-086)
OK = {"version": "simon.quality.v1", "level": "ok", "reasons": [], "signals": SIGNALS, "score_cap": None}
JITTER = {"code": "position_jitter", "words": "Joint positions shook by about 50 mm from one frame to the next.",
          "value": 50.0, "threshold": 42.0, "joint": "left_wrist"}
MAJOR = {**OK, "level": "major", "reasons": [JITTER], "score_cap": 59}
DEGRADED = {**OK, "level": "degraded", "reasons": [{**JITTER, "value": 25.0, "threshold": 21.0}]}


def with_quality(block, **extra):
    doc = copy.deepcopy(GOLDEN)
    doc.update(extra)
    doc.pop("quality", None)
    if block is not None:
        doc["quality"] = copy.deepcopy(block)
    return doc


def refused(block, message, **extra):
    with pytest.raises(OutputError, match=message):
        validate_analysis(with_quality(block, **extra), source="t")


@pytest.mark.parametrize("block", [OK, DEGRADED, MAJOR], ids=["ok", "degraded", "major"])
def test_a_well_formed_block_is_accepted(block):
    assert validate_analysis(with_quality(block))["quality"] == block


def test_a_document_without_the_block_is_accepted_and_left_alone():
    """AC-Q01: absent means not assessed; nothing is added."""
    doc = with_quality(None)
    assert "quality" not in validate_analysis(doc)
    assert "quality" not in build_analysis("e.json", "f.json", [])


def test_build_analysis_writes_the_block_after_the_warnings_and_before_the_diagnostics():
    doc = build_analysis("e.json", "f.json", [], diagnostics={"warnings": []}, quality=MAJOR,
                         warnings=[{"code": "low_match", "text": "x"}], match={"quality": "low", "limits": {}})
    keys = list(doc)
    assert keys.index("match") < keys.index("quality") < keys.index("diagnostics")
    assert doc["quality"] == MAJOR


@pytest.mark.parametrize("name,block,message", [
    ("not an object", [], "quality must be an object"),
    ("unknown version", {**OK, "version": "simon.quality.v2"}, "quality.version"),
    ("unknown level", {**OK, "level": "bad"}, "quality.level must be one of"),
    ("reasons not a list", {**OK, "reasons": {}}, "quality.reasons must be a list"),
    ("ok with a reason", {**OK, "reasons": [JITTER]}, "does not agree"),
    ("degraded with no reason", {**DEGRADED, "reasons": []}, "does not agree"),
    ("major with no cap", {**MAJOR, "score_cap": None}, "score_cap must be 59"),
    ("degraded with a cap", {**DEGRADED, "score_cap": 59}, "score_cap must be None"),
    ("ok with a cap", {**OK, "score_cap": 59}, "score_cap must be None"),
    ("a cap that is not 59", {**MAJOR, "score_cap": 60}, "score_cap must be 59"),
    ("a boolean cap", {**MAJOR, "score_cap": True}, "score_cap must be 59"),
    ("unknown code", {**MAJOR, "reasons": [{**JITTER, "code": "low_match"}]}, "reasons\\[0\\].code"),
    ("no words", {**MAJOR, "reasons": [{**JITTER, "words": ""}]}, "reasons\\[0\\].words"),
    ("words not text", {**MAJOR, "reasons": [{**JITTER, "words": 3}]}, "reasons\\[0\\].words"),
    ("value missing", {**MAJOR, "reasons": [{k: v for k, v in JITTER.items() if k != "value"}]}, "reasons\\[0\\].value"),
    ("value negative", {**MAJOR, "reasons": [{**JITTER, "value": -1}]}, "reasons\\[0\\].value"),
    ("value a string", {**MAJOR, "reasons": [{**JITTER, "value": "5"}]}, "reasons\\[0\\].value"),
    ("threshold missing", {**MAJOR, "reasons": [{k: v for k, v in JITTER.items() if k != "threshold"}]}, "reasons\\[0\\].threshold"),
    ("joint not canonical", {**MAJOR, "reasons": [{**JITTER, "joint": "head"}]}, "reasons\\[0\\].joint"),
    ("a reason that is not an object", {**MAJOR, "reasons": ["x"]}, "reasons\\[0\\] must be an object"),
    ("signals missing", {k: v for k, v in OK.items() if k != "signals"}, "quality.signals must be an object"),
    ("a signal missing", {**OK, "signals": {k: v for k, v in SIGNALS.items() if k != "position_jitter_mm"}}, "quality.signals"),
    ("a share over 1", {**OK, "signals": {**SIGNALS, "missing_joint_share": 1.5}}, "missing_joint_share"),
    ("a negative jitter", {**OK, "signals": {**SIGNALS, "position_jitter_mm": -0.1}}, "position_jitter_mm"),
    ("a signal that is text", {**OK, "signals": {**SIGNALS, "missing_frame_share": "0"}}, "missing_frame_share"),
    ("a signal that is a boolean", {**OK, "signals": {**SIGNALS, "missing_frame_share": False}}, "missing_frame_share"),
])
def test_a_block_that_contradicts_itself_is_refused(name, block, message):
    refused(block, message)


@pytest.mark.parametrize("words,accepted", [("", False), (" ", False), ("\t\n ", False), (" x", True), (JITTER["words"], True)])
def test_the_validator_and_the_schema_agree_on_blank_words(words, accepted):
    """Review R9 of 1.13.0: the validator refused whitespace-only `words` while the schema (`minLength` 1) accepted them; the
    schema's `pattern` `\\S` now refuses them too, so the two agree on every case."""
    doc = with_quality({**MAJOR, "reasons": [{**JITTER, "words": words}]})
    schema_accepts = not list(SCHEMA_VALIDATOR.iter_errors(doc))
    try:
        validate_analysis(doc, source="t")
        validator_accepts = True
    except OutputError:
        validator_accepts = False
    assert schema_accepts == validator_accepts == accepted


def test_a_signal_that_is_null_is_accepted_and_a_measured_zero_is_accepted_too():
    """Null is a reading that cannot be made; 0.0 is a measured zero. Both are valid, and they are not the same value."""
    both = {**OK, "signals": {**SIGNALS, "unseen_joint_share": None, "missing_joint_share": 0.0}}
    assert validate_analysis(with_quality(both))["quality"]["signals"]["unseen_joint_share"] is None
    assert validate_analysis(with_quality(both))["quality"]["signals"]["missing_joint_share"] == 0.0


@pytest.mark.parametrize("code", output.QUALITY_WARNING_CODES)
def test_a_take_with_a_visibility_warning_must_be_major_with_that_reason(code):
    """AC-Q05: not_enough_visible, moving_part_out_of_frame and no_usable_measures are major reasons."""
    warning = {"warnings": [{"code": code, "text": "x"}], "match": {"quality": "ok", "limits": {}}}
    reason = {"code": code, "words": "x", "value": None, "threshold": None}
    good = {**OK, "level": "major", "reasons": [reason], "score_cap": 59}
    assert validate_analysis(with_quality(good, **warning))
    refused(OK, "must be quality.level 'major'", **warning)
    refused(DEGRADED, "must be quality.level 'major'", **warning)
    refused(MAJOR, "with that reason", **warning)   # major, but for another reason


def test_low_match_alone_does_not_force_a_level():
    """AC-Q05: low_match is not a quality reason, so a block that is ok validates beside it."""
    warning = {"warnings": [{"code": "low_match", "text": "x"}], "match": {"quality": "low", "limits": {}}}
    assert validate_analysis(with_quality(OK, **warning))["quality"]["level"] == "ok"
    assert "low_match" not in output.QUALITY_CODES


def test_the_cap_is_the_warning_cap_of_the_score():
    from part5.score import WARNING_CAP
    assert output.QUALITY_CAP == WARNING_CAP == 59


def test_the_codes_are_the_schemas_codes_in_the_schemas_order():
    schema = json.loads((ROOT / "contracts/analysis.schema.json").read_text())
    block = schema["$defs"]["quality"]
    assert tuple(block["properties"]["reasons"]["items"]["properties"]["code"]["enum"]) == output.QUALITY_CODES
    assert tuple(block["properties"]["signals"]["properties"]) == output.QUALITY_SIGNALS
    # the schema requires the 1.13.0 signals; the validator requires heading_offset_deg from 1.14.0 (TICKET-086)
    assert tuple(block["properties"]["signals"]["required"]) == tuple(s for s in output.QUALITY_SIGNALS
                                                                      if s not in output.QUALITY_SIGNAL_SINCE)
    assert tuple(block["properties"]["level"]["enum"]) == output.QUALITY_LEVELS
