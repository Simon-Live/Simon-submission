import copy
import json
from pathlib import Path

import pytest

from part5.detect import Fault
from part5.evaluate import LABEL_TYPE_TO_MEASURE
from part5.output import (GENERIC_MEASURES, OutputError, build_analysis, fault_to_dict,
                          load_analysis, validate_analysis, write_analysis)

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "fixtures" / "output"


def make_fault(**kw):
    base = dict(measure="foot_out", side="left", joint="left_ankle", body_part="legs",
                direction="more", magnitude_deg=8.0, peak_deg=8.3, threshold_deg=6.0,
                expected_frames=(19, 43), follower_frames=(29, 48), phase=(0.211, 0.478),
                coverage=1.0, confidence=0.832)
    return Fault(**{**base, **kw})


def doc(faults=()):
    return build_analysis({"path": "expected.json"}, "follower.json", list(faults))


def test_shipped_examples_validate_and_match_their_labels():
    labels = json.loads((ROOT / "fixtures/input/followers/labels.json").read_text())
    by_id = {t["take_id"]: t for t in labels["takes"]}
    for name in ("analysis.example.json", "analysis.no-faults.example.json"):
        a = load_analysis(OUT / name)  # raises OutputError if the fixture breaks the contract
        take = by_id[a["follower"]["take_id"]]
        assert a["expected"]["path"] == take["expected"]
        assert a["follower"]["path"] == take["follower"]
        got = {(f["measure"], f["side"], f["direction"]) for f in a["faults"]}
        want = {(LABEL_TYPE_TO_MEASURE[f["type"]], f["side"], f["direction"]) for f in take["faults"]}
        assert got == want, name


def test_no_faults_example_is_an_empty_list():
    a = load_analysis(OUT / "analysis.no-faults.example.json")
    assert a["faults"] == []


def test_fault_dict_carries_text_and_signed_magnitude():
    d = fault_to_dict(make_fault())
    assert d["text"] == "left foot slightly too far out"
    assert d["measure_kind"] == "direction"
    assert d["magnitude_deg"] == 8.0 and d["unit"] == "degrees"
    d2 = fault_to_dict(make_fault(measure="knee_flexion", side="both", joint="knee",
                                  direction="less", magnitude_deg=-18.0, peak_deg=-25.0,
                                  threshold_deg=10.0))
    assert d2["measure_kind"] == "angle"
    assert d2["magnitude_deg"] == -18.0  # signed: follower − expected
    assert d2["text"] == "knees not bent enough"


def test_measure_vocabulary_matches_detect_generics():
    assert "foot_out" in GENERIC_MEASURES and "trunk_lean_forward" in GENERIC_MEASURES
    assert "knee_valgus" in GENERIC_MEASURES and len(GENERIC_MEASURES) == 13


def test_knee_valgus_fault_builds_validates_and_reads_in_plain_words():
    for side, joint, text in (("left", "left_knee", "left knee caving in"), ("both", "knee", "knees caving in")):
        d = doc([make_fault(measure="knee_valgus", side=side, joint=joint, body_part="legs", direction="more",
                            magnitude_deg=14.0, peak_deg=18.0, threshold_deg=8.0)])
        f = d["faults"][0]
        assert (f["measure"], f["measure_kind"], f["joint"], f["text"]) == ("knee_valgus", "direction", joint, text)
        assert validate_analysis(d)
    with pytest.raises(OutputError, match="joint must be"):
        validate_analysis(doc([make_fault(measure="knee_valgus", side="left", joint="left_ankle",
                                          body_part="legs", direction="more")]))


def test_fault_dict_lists_every_run_and_the_document_names_its_schema_version():
    d = doc([make_fault(runs=((19, 30), (35, 43)))])
    assert d["faults"][0]["runs"] == [[19, 30], [35, 43]]
    assert d["schema_version"] == "1.2.0"
    assert doc([make_fault()])["faults"][0]["runs"] == [[19, 43]]  # a single run is the fault's frames
    assert list(d)[:2] == ["format", "schema_version"]


def test_status_is_optional_and_a_refusal_has_no_faults():
    ok = {"code": "ok", "text": "Compared with the expected movement."}
    refused = {"code": "different_movement", "text": "This take does not look like the expected movement."}
    assert "status" not in doc([make_fault()])
    assert build_analysis("e.json", "f.json", [make_fault()], status=ok)["status"] == ok
    assert build_analysis("e.json", "f.json", [], status=refused)["faults"] == []
    with pytest.raises(OutputError, match="goes with faults"):
        build_analysis("e.json", "f.json", [make_fault()], status=refused)


def test_build_and_write_never_leak_or_write_invalid_json(tmp_path):
    with pytest.raises(OutputError, match="expected must be a path"):
        build_analysis(42, "follower.json", [])
    with pytest.raises(OutputError, match="cannot build a fault object"):
        build_analysis("e.json", "f.json", [object()])
    p = tmp_path / "analysis.json"
    p.write_text("previous good file")
    d = doc([make_fault()])
    d["diagnostics"] = {"alignment_residual": float("nan")}
    with pytest.raises(OutputError, match="not JSON-serialisable"):
        write_analysis(p, d)
    assert p.read_text() == "previous good file"  # failed writes leave the old file intact


def test_write_then_load_round_trips(tmp_path):
    d = doc([make_fault()])
    p = tmp_path / "sub" / "analysis.json"
    write_analysis(p, d)
    assert load_analysis(p) == d


@pytest.mark.parametrize("edit,msg", [
    (lambda d: d.update(format="simon.analysis.v2"), "format must be"),
    (lambda d: d.update(expected={"set": "x"}), "expected must be"),
    (lambda d: d.update(faults={}), "faults must be a list"),
    (lambda d: d["faults"].__setitem__(0, "oops"), r"faults\[0\] must be an object"),
    (lambda d: d["faults"][0].update(measure="toe_angle"), "measure must be one of"),
    (lambda d: d["faults"][0].update(measure_kind="angle"), "measure_kind must be"),
    (lambda d: d["faults"][0].update(joint="right_ankle"), "joint must be"),
    (lambda d: d["faults"][0].update(body_part="arms"), "body_part must be"),
    (lambda d: d["faults"][0].update(side="middle"), "side must be one of"),
    (lambda d: d["faults"][0].update(direction="wider"), "direction must be one of"),
    (lambda d: d["faults"][0].update(direction="less"), "direction .* disagrees with the signed"),
    (lambda d: d["faults"][0].update(peak_deg=-8.3), "direction .* disagrees with the signed"),
    (lambda d: d.update(diagnostics={"alignment_residual": float("nan")}), "not JSON-serialisable"),
    (lambda d: d["faults"][0].update(unit="radians"), "unit must be"),
    (lambda d: d["faults"][0].update(magnitude_deg="8"), "magnitude_deg must be a finite number"),
    (lambda d: d["faults"][0].update(magnitude_deg=float("nan")), "finite number"),
    (lambda d: d["faults"][0].update(magnitude_deg=True), "finite number"),
    (lambda d: d["faults"][0].update(threshold_deg=0), "threshold_deg must be positive"),
    (lambda d: d["faults"][0].update(confidence=1.2), "confidence must be a number in 0..1"),
    (lambda d: d["faults"][0].update(expected_frames=[43, 19]), "start <= end"),
    (lambda d: d["faults"][0].update(expected_frames=[19.0, 43]), "integer frames"),
    (lambda d: d["faults"][0].update(phase=[0.2, 1.4]), "phase must satisfy"),
    (lambda d: d["faults"][0].update(text=""), "text must be a non-empty string"),
    (lambda d: d.update(schema_version="2.0.0"), "schema_version must look like"),
    (lambda d: d.update(schema_version=1.1), "schema_version must look like"),
    (lambda d: d.update(status="ok"), "status must be an object"),
    (lambda d: d.update(status={"code": "maybe", "text": "x"}), "status.code must be one of"),
    (lambda d: d.update(status={"code": "ok", "text": ""}), "status.text must be a non-empty string"),
    (lambda d: d["faults"][0].update(runs=[]), "runs must be a non-empty list"),
    (lambda d: d["faults"][0].update(runs=[[3, 1]]), "runs must be a non-empty list"),
    (lambda d: d["faults"][0].update(runs=[[1.5, 4]]), "runs must be a non-empty list"),
    (lambda d: d["faults"][0].update(runs=[[1, 2, 3]]), "runs must be a non-empty list"),
])
def test_malformed_analyses_fail_clearly(edit, msg):
    d = doc([make_fault()])
    edit(d)
    with pytest.raises(OutputError, match=msg):
        validate_analysis(d, source="probe")


def test_extra_fields_are_allowed_for_forward_compatibility():
    d = doc([make_fault()])
    d["future_field"] = {"anything": 1}
    d["faults"][0]["future_field"] = 2
    assert validate_analysis(copy.deepcopy(d))["future_field"] == {"anything": 1}
