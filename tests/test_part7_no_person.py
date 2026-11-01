"""TICKET-048 and Part 7 TICKET-155 in analysis 1.9.0: the optional top-level `source`, the `no_person` warning code that
only Part 7's own analysis carries, and `score.uncapped` (docs/schemas.md, CONTRACT.md, docs/specs/integration-contract.md)."""
import copy
import json
from pathlib import Path

import jsonschema
import pytest

import shipped_score

from part5 import cli, contract, pipeline
from part5.output import (NO_PERSON, READABLE_WARNING_CODES, SOURCE_PART5, WARNING_CODES, OutputError, load_analysis,
                          validate_analysis)

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "fixtures/input/contract/part7/analysis.no-person.json"
EXAMPLE = ROOT / "fixtures/output/analysis.example.json"
SCHEMA = contract.load_schema("analysis")
VALIDATOR = jsonschema.Draft202012Validator(SCHEMA)


def no_person_doc():
    return json.loads(FIXTURE.read_text())


def schema_problems(doc):
    return [f"{'/'.join(map(str, e.absolute_path))}: {e.message[:100]}" for e in VALIDATOR.iter_errors(doc)]


def doctor_part7(path, capsys):
    code = cli.main(["doctor", str(path), "--for", "part7"])
    return code, capsys.readouterr().out


# ---------------------------------------------------------------- the Part 7 no-person document (TICKET-048)
def test_the_part7_no_person_document_is_what_the_ticket_describes():
    doc = no_person_doc()
    assert doc["schema_version"] == "1.4.0" and doc["source"] == "part7" and doc["faults"] == []
    assert [w["code"] for w in doc["warnings"]] == ["no_person"] and "match" not in doc
    assert doc["status"]["code"] == "ok" and doc["score"]["value"] == 0 and doc["score"]["grade"] == "F"
    assert doc["expected"]["path"] and doc["follower"]["path"]


def test_the_no_person_document_validates_against_the_schema_and_part5_output():
    doc = no_person_doc()
    assert schema_problems(doc) == []
    assert validate_analysis(copy.deepcopy(doc), source=str(FIXTURE)) == doc
    assert load_analysis(FIXTURE) == doc


def test_part5_doctor_for_part7_accepts_the_no_person_document_and_says_what_it_means(capsys):
    code, out = doctor_part7(FIXTURE, capsys)
    assert code == 0 and "simon.analysis.v1 1.4.0; accepted for part7" in out
    assert "warning: no_person: Part 2 found no person in the take." in out
    assert "note: written by part7, not by Part 5 (source)" in out
    assert "nothing was looked at, not a clean take" in out
    assert "note: score 0 out of 100, grade F" in out


@pytest.mark.parametrize("change", [
    pytest.param({"score": {"version": "simon.score.v1", "value": 0, "grade": "F", "capped_by": ["no_person"]}},
                 id="score-names-the-code"),
    pytest.param({"match": {"quality": "low", "residual": None, "timing_corr": None, "limits": {}}}, id="with-a-match"),
    pytest.param({"profile": "fitness", "schema_version": "1.10.0"}, id="current-schema-version-with-its-profile"),
])
def test_the_no_person_document_also_validates_in_these_shapes(change, tmp_path, capsys):
    doc = {**no_person_doc(), **change}
    assert schema_problems(doc) == []
    validate_analysis(doc)
    path = tmp_path / "analysis.json"
    path.write_text(json.dumps(doc))
    assert doctor_part7(path, capsys)[0] == 0


def test_no_person_is_in_the_schema_enum_and_the_python_codes_agree_with_it():
    enum = SCHEMA["properties"]["warnings"]["items"]["properties"]["code"]["enum"]
    assert NO_PERSON == "no_person" and list(READABLE_WARNING_CODES) == enum


def test_a_document_without_a_source_is_part5s_and_source_is_optional():
    doc = no_person_doc()
    del doc["source"]
    assert schema_problems(doc) == [] and "source" not in SCHEMA["required"]
    validate_analysis(doc)
    assert SOURCE_PART5 == "part5"


@pytest.mark.parametrize("bad", ["", 7, None, ["part7"]])
def test_a_source_that_is_not_a_non_empty_string_is_rejected_by_the_schema_and_the_loader(bad):
    doc = {**no_person_doc(), "source": bad}
    assert schema_problems(doc)
    with pytest.raises(OutputError, match="source must be a non-empty string"):
        validate_analysis(doc)


def test_an_unknown_warning_code_is_still_rejected():
    doc = no_person_doc()
    doc["warnings"][0]["code"] = "nobody_there"
    assert schema_problems(doc)
    with pytest.raises(OutputError, match="warnings\\[0\\].code must be one of"):
        validate_analysis(doc)


def test_a_part5_warning_still_needs_its_match_even_beside_no_person():
    doc = no_person_doc()
    doc["warnings"].append({"code": "low_match", "text": "x"})
    with pytest.raises(OutputError, match="match must be an object"):
        validate_analysis(doc)
    solo = {**no_person_doc(), "warnings": [{"code": "low_match", "text": "x"}]}
    with pytest.raises(OutputError, match="match must be an object"):
        validate_analysis(solo)


def test_a_malformed_match_on_a_no_person_document_is_still_checked():
    with pytest.raises(OutputError, match="match must be an object"):
        validate_analysis({**no_person_doc(), "match": {"quality": "unknown", "limits": {}}})


def test_part5_itself_never_writes_no_person_or_a_source():
    assert NO_PERSON not in WARNING_CODES and NO_PERSON not in pipeline.WARNING_ORDER
    for name in sorted((ROOT / "fixtures/output").glob("analysis*.json")):
        doc = json.loads(name.read_text())
        assert "source" not in doc and NO_PERSON not in [w["code"] for w in doc.get("warnings", [])], name


def test_the_contract_table_has_a_part7_no_person_row_and_the_part5_row_names_the_new_fields():
    rows = contract.table_rows()
    part7 = next(r for r in rows if r["producer"].startswith("Part 7 own analysis"))
    assert "`no_person`" in part7["fix"] and "`part5 doctor <file> --for part7`" in part7["fix"]
    assert part7["verdict"] == "works" and "source" in part7["file"]
    part5 = next(r for r in rows if r["producer"] == "Part 5" and r["file"] == "`analysis.json`")
    assert "`score.uncapped`" in part5["fix"] and "`source`" in part5["fix"] and "`no_person`" in part5["fix"]


def test_docs_schemas_and_contract_md_name_the_new_fields():
    for name in ("docs/schemas.md", "CONTRACT.md"):
        text = (ROOT / name).read_text()
        assert "`source`" in text and "`no_person`" in text and "`score.uncapped`" in text, name


def test_make_check_5_contract_validates_and_loads_the_no_person_example():
    summary = contract.check(ROOT)
    assert summary["failures"] == []
    assert "fixtures/input/contract/part7/analysis.no-person.json" not in summary["rebuilt_identical"]   # not a golden


# ---------------------------------------------------------------- score.uncapped (Part 7 TICKET-155)
def capped_doc():
    """The golden two-fault example as a low_match take: the score of 73 C capped at 59 F, with the value it lost."""
    doc = json.loads(EXAMPLE.read_text())
    doc["warnings"] = [{"code": "low_match", "text": "This take doesn't closely match the trainer's movement."}]
    doc["match"] = {"quality": "low", "residual": 0.6122, "timing_corr": 0.4998, "limits": {}}
    doc["score"].update(value=59, grade="F", capped_by=["low_match"], uncapped={"value": 73, "grade": "C"})
    return doc


def test_a_capped_score_with_uncapped_validates_and_the_doctor_says_what_the_cap_cost(tmp_path, capsys):
    doc = capped_doc()
    assert schema_problems(doc) == []
    validate_analysis(doc)
    path = tmp_path / "analysis.json"
    path.write_text(json.dumps(doc))
    code, out = doctor_part7(path, capsys)
    assert code == 0
    assert "note: score 59 out of 100, grade F, capped at F by low_match" in out
    assert "it was 73 (C) before the cap (score.uncapped)" in out


@pytest.mark.parametrize("bad", [{"value": 120, "grade": "A"}, {"value": 73, "grade": "E"}, {"value": 73}, {"grade": "C"}])
def test_a_malformed_uncapped_is_rejected_by_the_schema(bad):
    doc = capped_doc()
    doc["score"]["uncapped"] = bad
    assert schema_problems(doc)


def test_the_fitness_baseline_digest_leaves_out_uncapped_and_nothing_else_of_the_score():
    from part5 import profiles_report
    capped = capped_doc()
    plain = copy.deepcopy(capped)
    del plain["score"]["uncapped"]
    assert profiles_report.analysis_digest(capped) == profiles_report.analysis_digest(plain)
    other = copy.deepcopy(plain)
    other["score"]["value"] = 58
    assert profiles_report.analysis_digest(other) != profiles_report.analysis_digest(plain)


def test_a_score_without_uncapped_has_no_such_note(tmp_path, capsys):
    doc = capped_doc()
    del doc["score"]["uncapped"]
    path = tmp_path / "analysis.json"
    path.write_text(json.dumps(doc))
    assert "score.uncapped" not in doctor_part7(path, capsys)[1]


# ---------------------------------------------------------------- score.fault_cap and the wider uncapped (1.10.0, ADR-0018)
FAULT_CAPPED = ROOT / "fixtures/output/analysis.fault-capped.example.json"
v2_only = shipped_score.v2_only   # the sample is a simon.score.v2 document, written only while the rules ship v2


@v2_only
def test_a_faulted_take_the_fault_cap_lowered_has_uncapped_and_no_capped_by_and_the_doctor_says_so(tmp_path, capsys):
    """Part 7's answer: `capped_by` is the low-match warning cap only; `uncapped` is the value before every cap."""
    doc = json.loads(FAULT_CAPPED.read_text())
    assert schema_problems(doc) == []
    validate_analysis(doc)
    assert "capped_by" not in doc["score"] and "warnings" not in doc
    code, out = doctor_part7(FAULT_CAPPED, capsys)
    assert code == 0
    assert "note: score 89 out of 100, grade B; the take reports a fault, so its score is at most 89 (score.fault_cap)" in out
    assert "it was 94 (A) before the cap (score.uncapped)" in out
    assert "capped at F" not in out


@v2_only
def test_a_take_with_both_caps_names_the_warning_in_capped_by_only(tmp_path, capsys):
    doc = json.loads(FAULT_CAPPED.read_text())
    doc["warnings"] = [{"code": "low_match", "text": "This take doesn't closely match the trainer's movement."}]
    doc["match"] = {"quality": "low", "residual": 0.6, "timing_corr": 0.5, "limits": {}}
    doc["score"].update(value=59, grade="F", capped_by=["low_match"])
    assert schema_problems(doc) == []
    path = tmp_path / "analysis.json"
    path.write_text(json.dumps(doc))
    out = doctor_part7(path, capsys)[1]
    assert "capped at F by low_match" in out and "fault_cap" in out and "it was 94 (A) before the cap" in out
    assert doc["score"]["capped_by"] == ["low_match"]   # the fault cap is never listed there


@v2_only
@pytest.mark.parametrize("bad", [89.5, "89", -1, 101, True])
def test_a_malformed_fault_cap_is_rejected_by_the_schema(bad):
    doc = json.loads(FAULT_CAPPED.read_text())
    doc["score"]["fault_cap"] = bad
    assert schema_problems(doc)


def test_a_take_with_no_fault_has_no_fault_cap_note(tmp_path, capsys):
    path = tmp_path / "analysis.json"
    path.write_text((ROOT / "fixtures/output/analysis.no-faults.example.json").read_text())
    assert "fault_cap" not in doctor_part7(path, capsys)[1]
