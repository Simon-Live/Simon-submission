"""Old readers (docs/specs/journey-followup.md AC-C01, AC-T04; ADR-0012).

`tests/fixtures/` holds the 1.1.0 schema and the two example documents exactly as they were at `28d20ef`.
A document of the current version must still validate against that schema, with one deliberate exception: a take
analysed with a `low_match` warning lists its faults with `confidence: "low"` (ADR-0012), which a 1.1.0 reader
rejects. So a reader older than 1.4.0 cannot show a different movement as a normal result, and Part 7 reads the
literal. These tests pin that exception to `faults[*].confidence` and nothing else.
"""
import copy
import json
from pathlib import Path

import jsonschema
import pytest

from part5.detect import load_rules
from part5.pipeline import analyse, run
from part5.score_report import score_block

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"
OLD_SCHEMA = json.loads((FIXTURES / "analysis-1.1.0.schema.json").read_text())
SCHEMA = json.loads((ROOT / "contracts" / "analysis.schema.json").read_text())
LABELS = json.loads((ROOT / "fixtures/input/followers/labels.json").read_text())
LATERAL = ROOT / "fixtures/input/real/lateral-raise"
EXPECTED = ROOT / "fixtures/input/expected/exercise/animation.json"
GOLDENS = ("analysis.example.json", "analysis.no-faults.example.json")
OLD_GOLDENS = {"analysis.example.json": "analysis-1.1.0.example.json",
               "analysis.no-faults.example.json": "analysis-1.1.0.no-faults.example.json"}


def violations(schema, doc):
    return list(jsonschema.Draft202012Validator(schema).iter_errors(doc))


def where(errors):
    """The places in the document the errors point at, with list indices folded to `*`."""
    return {tuple("*" if isinstance(p, int) else p for p in e.absolute_path) for e in errors}


@pytest.fixture(scope="module")
def unwarned():
    take = next(t for t in LABELS["takes"] if t["take_id"].startswith("exercise_45_good_02"))
    refs = ({"path": take["expected"], "set": take["set"], "movement": take["movement"]},
            {"path": take["follower"], "take_id": take["take_id"]})
    return run(str(ROOT / take["expected"]), str(ROOT / take["follower"]), score=score_block).analysis, refs


@pytest.fixture(scope="module")
def warned():
    """A low match that still lists a fault: the real fast lateral raise as the example, the slow take as the follower."""
    fast, slow = LATERAL / "pexels-40297504/animation.json", LATERAL / "pexels-8836968/animation.json"
    return run(str(fast), str(slow), score=score_block).analysis


@pytest.fixture(scope="module")
def blind(blind_follower):
    """A follower with no usable joints: warned, with no faults."""
    return run(str(EXPECTED), blind_follower(), score=score_block).analysis


# --- AC-C01: an unwarned document validates against the 1.1.0 schema -------------------------------------

def test_the_vendored_schema_is_the_1_1_0_one():
    assert OLD_SCHEMA["version"] == "1.1.0"
    assert OLD_SCHEMA["properties"]["faults"]["items"] == {"$ref": "#/$defs/fault"}
    assert OLD_SCHEMA["$defs"]["fault"]["properties"]["confidence"]["type"] == "number"


def test_ac_c01_a_fresh_unwarned_document_with_a_score_validates_against_both_schemas(unwarned):
    doc, _ = unwarned
    assert "warnings" not in doc and doc["schema_version"] == "1.9.0" and doc["score"] and doc["faults"]
    assert violations(OLD_SCHEMA, doc) == [] and violations(SCHEMA, doc) == []


@pytest.mark.parametrize("name", GOLDENS)
def test_ac_c01_the_golden_outputs_validate_against_the_1_1_0_schema(name):
    doc = json.loads((ROOT / "fixtures/output" / name).read_text())
    assert doc["schema_version"] == "1.9.0"
    assert violations(OLD_SCHEMA, doc) == [] and violations(SCHEMA, doc) == []


# --- AC-C01: a warned document fails 1.1.0 on faults[*].confidence only ------------------------------------

def test_ac_c01_a_low_match_with_faults_fails_the_1_1_0_schema_only_on_confidence(warned):
    assert [w["code"] for w in warned["warnings"]] == ["low_match"] and warned["faults"]
    assert {f["confidence"] for f in warned["faults"]} == {"low"}
    errors = violations(OLD_SCHEMA, warned)
    assert errors and where(errors) == {("faults", "*", "confidence")}


def test_ac_c01_a_low_match_validates_against_the_current_schema(warned):
    assert violations(SCHEMA, warned) == []


def test_ac_c01_the_literal_is_the_only_thing_an_old_reader_cannot_take(warned):
    """Put a number back in place of "low" and the same document validates against 1.1.0."""
    numeric = copy.deepcopy(warned)
    for fault in numeric["faults"]:
        fault["confidence"] = 0.5
    assert violations(OLD_SCHEMA, numeric) == []


def test_ac_c01_a_warning_that_lists_no_fault_validates_against_the_1_1_0_schema(blind):
    assert [w["code"] for w in blind["warnings"]] == ["no_usable_measures"] and blind["faults"] == []
    assert violations(OLD_SCHEMA, blind) == [] and violations(SCHEMA, blind) == []


# --- AC-T04: text is the 1.1.0 text, byte for byte --------------------------------------------------------

@pytest.mark.parametrize("name", GOLDENS)
def test_ac_t04_text_and_every_scored_field_equal_the_1_1_0_golden(name):
    old = json.loads((FIXTURES / OLD_GOLDENS[name]).read_text())
    assert old["schema_version"] == "1.1.0"
    # What this pins is that a schema bump leaves the text and the scored fields alone, not the calibration of the
    # thresholds: a re-sweep (attempt 4's recheck moved `upper_arm_out` to 11) changes `threshold_deg` and, with it, the
    # size word ("slightly") of a fault near its threshold. So the pair is analysed with the thresholds the golden recorded.
    rules = load_rules()
    for fault in old["faults"]:
        rules["measures"][fault["measure"]]["threshold_deg"] = fault["threshold_deg"]
    new = analyse(old["expected"], old["follower"], rules)
    assert len(new["faults"]) == len(old["faults"])
    for was, now in zip(old["faults"], new["faults"]):
        assert now["text"].encode() == was["text"].encode()
        # ADR-0008 changed `coaching` (it is the timed line now); every other 1.1.0 field is as it was
        assert {k: v for k, v in now.items() if k in was and k != "coaching"} == {k: v for k, v in was.items() if k != "coaching"}
    # 1.8.0 (TICKET-043) added `diagnostics.near_misses`; every other diagnostics field is as it was
    assert (new["status"], {k: v for k, v in new["diagnostics"].items() if k != "near_misses"}) == (
        old["status"], old["diagnostics"])
