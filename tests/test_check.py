import copy
import json

from part5 import check

SLICE = {"tp": 9, "fp": 1, "fn": 2, "takes": 8, "correct_takes": 2, "faults_on_correct_takes": 0,
         "precision": 0.9, "recall": 0.8182}


def metrics(**overrides):
    m = {"slices": {name: dict(SLICE) for name in check.GATED + ("low/side",)}}
    for name, fields in overrides.items():
        m["slices"][name.replace("_", "/")].update(fields)
    return m


def test_all_good_slices_passing_passes_even_if_low_light_is_bad():
    g = check.gate(metrics(low_side={"precision": 0.1, "recall": 0.1, "faults_on_correct_takes": 9}))
    assert g["passed"] and g["failures"] == []


def test_each_gated_slice_and_criterion_can_fail_on_its_own():
    for name in check.GATED:
        key = name.replace("/", "_")
        for fields, word in (({"precision": 0.84}, "precision"), ({"recall": 0.74}, "recall"),
                             ({"faults_on_correct_takes": 1}, "correct takes")):
            g = check.gate(metrics(**{key: fields}))
            assert not g["passed"]
            assert g["gated_slices"][name] is False
            assert len(g["failures"]) == 1 and name in g["failures"][0] and word in g["failures"][0]


def test_thresholds_are_inclusive():
    g = check.gate(metrics(good_front={"precision": 0.85, "recall": 0.75}))
    assert g["passed"]


def test_a_missing_gated_slice_fails():
    m = metrics()
    del m["slices"]["good/45"]
    g = check.gate(m)
    assert not g["passed"] and "good/45: no takes" in g["failures"]


def test_an_unanalysable_take_fails_the_check(tmp_path):
    labels = json.loads(check.LABELS.read_text())
    labels = copy.deepcopy(labels)
    labels["takes"] = labels["takes"][:2]
    labels["takes"][1]["follower"] = "does/not/exist.json"
    p = tmp_path / "labels.json"
    p.write_text(json.dumps(labels))
    metrics_doc, errors = check.run(p)
    assert metrics_doc is None and len(errors) == 1 and labels["takes"][1]["take_id"] in errors[0]


def test_a_slice_with_no_labelled_faults_fails_instead_of_scoring_recall_1():
    g = check.gate(metrics(good_side={"tp": 0, "fn": 0, "fp": 0, "precision": 1.0, "recall": 1.0}))
    assert not g["passed"] and g["failures"] == ["good/side: no labelled faults, so recall can't be measured"]


def test_a_slice_with_no_correct_takes_fails():
    g = check.gate(metrics(good_45={"correct_takes": 0}))
    assert not g["passed"]
    assert g["failures"] == ["good/45: no correct takes, so faults on correct takes can't be measured"]
