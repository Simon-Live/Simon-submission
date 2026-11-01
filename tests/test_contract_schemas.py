"""The published schemas agree with the loaders (docs/specs/integration-contract.md AC-C01, AC-C02): the analysis,
labels, input clip and metrics schemas against `validate_analysis`, `parse_clip` and the check-5 document, including the
additions of analysis 1.1.0 and metrics 1.1.0 to 1.4.0. The CLI, the check and the compatibility table are in
tests/test_contract_cli.py (split out of it to stay under 800 lines)."""
import copy
import json

import pytest

from part5 import contract
from part5.io import JOINTS, parse_clip
from part5.output import GENERIC_MEASURES, OutputError, SIDES, _joint_for, _spec, validate_analysis
from test_contract_cli import BASE, CORRECT, GOLDEN, ROOT, errors, validator   # one home for the shared constants


# ---------------------------------------------------------------- the schemas agree with the loaders
def golden():
    return json.loads(GOLDEN.read_text())


def test_analysis_schema_accepts_both_goldens():
    for path in (GOLDEN, CORRECT):
        assert errors("analysis", json.loads(path.read_text())) == []


def test_analysis_schema_measure_table_matches_part5_measures():
    schema = contract.load_schema("analysis")
    fault = schema["$defs"]["fault"]
    allowed = set(fault["properties"]["measure"]["enum"])
    assert set(GENERIC_MEASURES) <= allowed
    assert allowed - set(GENERIC_MEASURES) <= {"knee_valgus"}  # lands in M2 (ADR-0004)


def fault_for(measure, side):
    f = copy.deepcopy(golden()["faults"][0])
    spec = _spec(measure, side)
    f.update(measure=measure, side=side, measure_kind=spec.kind, body_part=spec.body_part,
             joint=_joint_for(measure, side))
    return f


def doc_with(fault):
    d = golden()
    d["faults"] = [fault]
    if "phrasing" in d:  # one phrasing entry per fault
        d["phrasing"]["faults"] = d["phrasing"]["faults"][:1]
    if "fault_cap" in (d.get("score") or {}):  # the ceiling in force for one fault (1.11.0, ADR-0019; the golden reports two)
        d["score"]["fault_cap"] = 89
    return d


def agrees(doc):
    """(schema accepts, loader accepts) for one document."""
    try:
        validate_analysis(doc)
        loader = True
    except OutputError:
        loader = False
    return not errors("analysis", doc), loader


@pytest.mark.parametrize("measure", GENERIC_MEASURES)
@pytest.mark.parametrize("side", SIDES)
def test_schema_and_loader_agree_on_every_measure_and_side(measure, side):
    spec = _spec(measure, side)
    if spec is None:  # a side that does not go with the measure
        base = fault_for("upper_arm_out", "left")
        base.update(measure=measure, side=side)
        assert agrees(doc_with(base)) == (False, False)
        return
    good = fault_for(measure, side)
    assert agrees(doc_with(good)) == (True, True)
    wrong_joint = dict(good, joint="nose")
    assert agrees(doc_with(wrong_joint)) == (False, False)
    wrong_part = dict(good, body_part="head" if good["body_part"] != "head" else "arms")
    assert agrees(doc_with(wrong_part)) == (False, False)
    wrong_kind = dict(good, measure_kind="direction" if good["measure_kind"] == "angle" else "angle")
    assert agrees(doc_with(wrong_kind)) == (False, False)


def test_schema_and_loader_agree_on_sign_and_ranges():
    good = golden()["faults"][0]
    cases = [dict(good, direction="less"), dict(good, magnitude_deg=-good["magnitude_deg"]),
             dict(good, unit="radians"), dict(good, threshold_deg=0), dict(good, coverage=1.5),
             dict(good, confidence=-0.1), dict(good, phase=[0.5, 1.2]), dict(good, text="")]
    for bad in cases:
        assert agrees(doc_with(bad)) == (False, False), bad


def test_start_after_end_is_for_the_loader_only():
    """A schema cannot compare two array items; part5.output does."""
    bad = dict(golden()["faults"][0], expected_frames=[5, 3])
    assert agrees(doc_with(bad)) == (True, False)


def test_knee_valgus_is_an_allowed_measure_now():
    f = fault_for("elbow_flexion", "left")
    f.update(measure="knee_valgus", measure_kind="direction", body_part="legs", joint="left_knee")
    assert errors("analysis", doc_with(f)) == []
    assert errors("analysis", doc_with(dict(f, measure_kind="angle")))
    assert errors("analysis", doc_with(dict(f, joint="left_hip")))
    f.update(body_part="arms")
    assert errors("analysis", doc_with(f))


# ---------------------------------------------------------------- the additions of schema 1.1.0
def doc_1_1():
    d = golden()
    d["schema_version"] = "1.1.0"
    d["status"] = {"code": "ok", "text": "Analysed."}
    d["phrasing"] = {"requested": "muse-spark", "backend": "template", "model": None,
                     "fallback_reason": "no key",
                     "faults": [{"backend": "template", "fallback_reason": "no key"}] * len(d["faults"])}
    for f in d["faults"]:
        f["joints"] = ["left_hip", "left_knee"]
        f["runs"] = [f["expected_frames"]]
        f["coaching"] = f["text"]
    d["diagnostics"]["guard"] = {"residual": 0.4, "timing_corr": 0.9, "span_share": 0.8,
                                 "limits": {"max_residual": 1.0, "min_timing_corr": 0.5}}
    return d


def test_a_1_1_document_validates_in_both_validators():
    d = doc_1_1()
    assert errors("analysis", d) == []
    validate_analysis(d)


def test_a_refused_analysis_validates_and_a_refusal_with_faults_does_not():
    d = json.loads(CORRECT.read_text())
    d["schema_version"] = "1.1.0"
    d["status"] = {"code": "different_movement", "text": "This does not look like a squat."}
    d["score"] = None   # a refused take of 1.3.0 or earlier had no score; from 1.4.0 none is refused
    assert errors("analysis", d) == []
    validate_analysis(d)
    refused_with_faults = dict(doc_1_1(), status={"code": "different_movement", "text": "No."})
    assert errors("analysis", refused_with_faults)


@pytest.mark.parametrize("change", [
    lambda d: d.pop("format"),
    lambda d: d.update(format="simon.analysis.v2"),
    lambda d: d.update(status={"code": "maybe", "text": "x"}),
    lambda d: d.update(status={"code": "ok"}),
    lambda d: d.update(schema_version="2.0.0"),
    lambda d: d.update(phrasing={"backend": "gpt"}),
    lambda d: d["faults"][0].update(joints=["spine"]),
    lambda d: d["faults"][0].update(joints=[]),
    lambda d: d["faults"][0].update(runs=[[1]]),
    lambda d: d["diagnostics"].update(follower_span=[1]),
])
def test_analysis_schema_rejects_malformed_additions(change):
    d = doc_1_1()
    change(d)
    assert errors("analysis", d)


def test_analysis_allows_unknown_extra_fields():
    d = doc_1_1()
    d["extra"] = {"anything": 1}
    d["faults"][0]["note"] = "x"
    assert errors("analysis", d) == []


# ---------------------------------------------------------------- labels
def labels_doc():
    take = {"take_id": "exercise_side_good_09_knee_caving-left", "set": "exercise", "movement": "squat",
            "angle": "side", "lighting": "good", "variant": "dropout", "label_source": "synthetic", "seed": 29,
            "correct": False, "faults": [{"type": "knee_caving", "measure": "knee_valgus", "body_part": "legs",
                                          "joints": ["left_knee"], "side": "left", "direction": "more",
                                          "magnitude_deg": 18.0}]}
    correct = {"take_id": "exercise_side_good_00_correct", "correct": True, "faults": []}
    return {"format": "simon.part5.labels.v1", "seed": 29, "label_source": "synthetic", "takes": [take, correct]}


def test_labels_schema_takes_the_new_label_type_and_optional_fields():
    assert errors("labels", labels_doc()) == []


def test_labels_schema_takes_real_take_labels():
    d = labels_doc()
    d.update(label_source="visual", labeller="agent")
    d["takes"][0].update(label_source="visual", expected="fixtures/input/eval/real/side/skeleton.json")
    assert errors("labels", d) == []


@pytest.mark.parametrize("change", [
    lambda d: d["takes"][0].update(variant="noisy"),
    lambda d: d["takes"][0].update(label_source="guess"),
    lambda d: d["takes"][0]["faults"][0].update(type="knee_wobble"),
    lambda d: d["takes"][1].update(faults=d["takes"][0]["faults"]),
    lambda d: d["takes"][0].update(faults=[]),
    lambda d: d["takes"][0]["faults"][0].update(side="middle"),
    lambda d: d.pop("takes"),
    lambda d: d.update(format="simon.part5.labels.v2"),
])
def test_labels_schema_rejects_malformed_labels(change):
    d = labels_doc()
    change(d)
    assert errors("labels", d)


# ---------------------------------------------------------------- input clips
def clip_doc(frames=3, **over):
    doc = {"format": "simon.animation.v1", "fps": 30, "frames": [
        {"index": i, "t": i / 30, "interpolated": False, "joints": {n: [0.01 * j, 0.1 * j, 0.0]
                                                                    for j, n in enumerate(JOINTS)}}
        for i in range(frames)]}
    for f in doc["frames"]:  # keep the hip midpoint at the origin
        f["joints"]["left_hip"], f["joints"]["right_hip"] = [0.1, 0, 0], [-0.1, 0, 0]
    doc.update(over)
    return doc


def test_input_animation_accepts_null_joints_conf_and_a_clip_without_fps_when_t_is_given():
    d = clip_doc()
    d["frames"][1]["joints"]["left_wrist"] = None
    d["frames"][1]["conf"] = {"left_ankle": 0.2, "nose": 1.0}
    assert errors("input-animation", d) == []
    parse_clip(d)
    no_fps = clip_doc()
    del no_fps["fps"]
    assert errors("input-animation", no_fps) == []
    parse_clip(no_fps)


@pytest.mark.parametrize("change", [
    lambda d: d.pop("fps") and [f.pop("t") for f in d["frames"]],
    lambda d: d.update(format="simon.skeleton.v1"),
    lambda d: d.update(fps=0),
    lambda d: d.update(frames=[]),
    lambda d: d.update(joints=["nose"]),
    lambda d: d.update(coordinate_frame={"x": "subject_right"}),
    lambda d: d["frames"][0]["joints"].update(left_toe=[0, 0, 0]),
    lambda d: d["frames"][0]["joints"].update(nose=[0, 0]),
    lambda d: d["frames"][0].update(conf={"nose": 1.5}),
    lambda d: d["frames"][0].pop("joints"),
])
def test_input_animation_rejects_what_part5_io_rejects(change):
    d = clip_doc()
    change(d)
    assert errors("input-animation", d)
    with pytest.raises(ValueError):
        parse_clip(d)


def test_input_skeleton_reads_keyframes_only():
    d = {"format": "simon.skeleton.v1", "fps": 30, "frames": "ignored", "keyframes": [
        {"index": 0, "t": 0.0, "name": "start", "joints": clip_doc(1)["frames"][0]["joints"]}]}
    assert errors("input-skeleton", d) == []
    parse_clip(d)
    del d["keyframes"]
    assert errors("input-skeleton", d)


# ---------------------------------------------------------------- the check-5 document
def metrics_doc():
    sl = {"tp": 4, "fp": 0, "fn": 1, "takes": 9, "correct_takes": 2, "faults_on_correct_takes": 0,
          "precision": 1.0, "recall": 0.8, "refused": 0}
    slices = {"good/front": sl, "good/45": sl, "good/side": sl}
    m = {"format": "simon.part5.metrics.v1", "slices": slices}
    sha = "0" * 64
    return {
        "format": "simon.part5.check.v1", "data_source": "synthetic: held-out takes", "rules_sha256": sha,
        "gate": {"set": "fixtures/input/heldout", "seed": 29, "slices": list(slices),
                 "thresholds": {"precision": 0.85, "recall": 0.75, "faults_on_correct_takes": 0},
                 "passed": True, "failures": [], "metrics": m},
        "attempts": [{"seed": 29, "freeze_commit": "abc1234", "rules_sha256": sha, "approach": "rules",
                      "passed": True, "slices": {}}],
        "tuning": {"set": "fixtures/input/followers", "seed": 5, "gated": False, "metrics": m},
        "report": {"low_light": {"gated": False, "slices": {}}, "dropout": {"gated": False, "slices": {}},
                   "kit": {"gated": False, "source": "Part 3 conformance kit", "takes": []},
                   "stock": {"gated": False, "source": "fixtures/input/eval/real", "takes": [],
                             "note": "not delivered yet"},
                   "refusals": {"good/front": 0}},
    }


def test_metrics_schema_accepts_the_check_document():
    assert errors("metrics", metrics_doc()) == []


@pytest.mark.parametrize("change", [
    lambda d: d.pop("gate"),
    lambda d: d["gate"].update(passed="yes"),
    lambda d: d["gate"]["metrics"]["slices"]["good/front"].update(precision=1.5),
    lambda d: d["report"]["low_light"].update(gated=True),
    lambda d: d["report"]["refusals"].update(gated=True),
    lambda d: d["report"]["refusals"].update(gated="no"),
    lambda d: d["tuning"].update(gated=True),
    lambda d: d.update(rules_sha256="abc"),
    lambda d: d.update(format="simon.part5.metrics.v1"),
])
def test_metrics_schema_rejects_a_malformed_check_document(change):
    d = metrics_doc()
    change(d)
    assert errors("metrics", d)


def test_metrics_1_2_0_accepts_the_refusals_flag_beside_the_slice_counts():
    """AC-K12: report.refusals is slice -> count plus `gated: false`; a 1.1.0 document without it still validates."""
    d = metrics_doc()
    assert "gated" not in d["report"]["refusals"] and errors("metrics", d) == []
    d["report"]["refusals"] = {"gated": False, "good/front": 0, "good/side": 2}
    assert errors("metrics", d) == []


# ---------------------------------------------------------------- metrics 1.1.0: the score report
def metrics_with_score():
    d = metrics_doc()
    sl = {"n": 12, "min": 100, "median": 100.0, "max": 100, "grades": {"A": 12}}
    empty = {"n": 0, "min": None, "median": None, "max": None, "grades": {}}
    d["gate"]["sweep"] = {"foot_out right": [[0, 100], [4, 100], [8, 100], [12, 86]],
                          "trunk_lean center": [[0, 100], [5, None]]}
    d["detection_sha256"] = "1" * 64
    d["report"]["score"] = {
        "gated": False, "version": "simon.score.v1",
        "heldout": {"seed": 31, "slices": {"good/0": sl, "low/2": empty},
                    "targets": {"good/0": "pass", "good/1": "fail", "good/2": "no takes"}},
        "tuning": {"seed": 5, "slices": {"good/0": sl}},
        "kit": {"grades": {"B": 3, "F": 1}}, "stock": {"grades": {}}}
    return d


def test_metrics_1_1_0_accepts_the_score_report_check_5_writes():
    assert errors("metrics", metrics_with_score()) == []


def test_metrics_1_1_0_still_accepts_a_1_0_0_document():
    assert errors("metrics", metrics_doc()) == []


@pytest.mark.parametrize("version", ["simon.score.v1", "simon.score.v2", "simon.score.v3"])
def test_metrics_1_5_0_accepts_the_score_version_the_rules_ship(version):
    """ADR-0018, ADR-0019: a v1 report (a 1.3.0 document), a v2 report (1.4.0) and a v3 report (1.5.0) all validate."""
    d = metrics_with_score()
    d["report"]["score"]["version"] = version
    assert errors("metrics", d) == []


@pytest.mark.parametrize("change", [
    lambda d: d["report"]["score"]["heldout"]["slices"]["good/0"]["grades"].update(E=1),
    lambda d: d["report"]["score"]["heldout"]["slices"]["good/0"]["grades"].update(A=-1),
    lambda d: d["report"]["score"]["heldout"]["slices"]["good/0"].pop("median"),
    lambda d: d["report"]["score"]["heldout"]["targets"].update({"good/0": "maybe"}),
    lambda d: d["report"]["score"].update(gated=True),
    lambda d: d["report"]["score"].update(version="simon.score.v4"),
    lambda d: d["report"]["score"].pop("kit"),
    lambda d: d["gate"]["sweep"]["foot_out right"].append([16]),
    lambda d: d["gate"]["sweep"]["foot_out right"].append([16, "high"]),
    lambda d: d.update(detection_sha256="abc"),
])
def test_metrics_1_1_0_rejects_a_malformed_score_report(change):
    d = metrics_with_score()
    change(d)
    assert errors("metrics", d)
