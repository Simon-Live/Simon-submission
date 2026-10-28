import json
from pathlib import Path

from part5.evaluate import canonical_label, evaluate_corpus, match_faults, matches, score

ROOT = Path(__file__).resolve().parent.parent


def pred(measure="foot_out", side="left", direction="more", **kw):
    return {"measure": measure, "side": side, "direction": direction, **kw}


def label(type="foot_out", side="left", direction="more", **kw):
    return {"type": type, "measure": "thigh_direction", "side": side,
            "direction": direction, "body_part": "legs", **kw}


def test_label_vocabulary_maps_to_prediction_vocabulary():
    assert canonical_label(label()) == ("foot_out", "left", "more")
    assert canonical_label({"measure": "upper_arm_direction", "side": "right",
                            "direction": "more"}) == ("upper_arm_out", "right", "more")


def test_match_rule_measure_side_direction():
    assert matches(pred(), label())
    assert not matches(pred(side="right"), label())
    assert not matches(pred(direction="less"), label())
    assert not matches(pred(measure="thigh_out"), label())


def test_both_label_accepts_either_side_but_not_the_reverse():
    both = label(type="arms_wider", side="both")
    assert matches(pred("upper_arm_out", "left"), both)
    assert matches(pred("upper_arm_out", "right"), both)
    assert matches(pred("upper_arm_out", "both"), both)
    # Decided rule is one-way: a "both" prediction does not satisfy a one-sided label.
    assert not matches(pred(side="both"), label())


def test_trunk_matches_at_body_part_level():
    trunk = {"type": "trunk_lean", "measure": "trunk_lean_forward", "side": "center",
             "direction": "more", "body_part": "torso"}
    assert matches(pred("trunk_lean_forward", "center"), trunk)


def test_matching_is_one_to_one_and_maximal():
    # Two identical predictions, one label: only one true positive.
    tp, mp, ml = match_faults([pred(), pred()], [label()])
    assert (tp, len(mp), len(ml)) == (1, 1, 1)
    # A greedy first-fit would fail here: left can take either label, right only the second.
    preds = [pred(side="left"), pred(side="right")]
    labs = [label(side="both"), label(side="right")]
    tp, _, _ = match_faults(preds, labs)
    assert tp == 2


def toy_records():
    return [
        # good/front: 1 TP, 1 FP on a correct take
        {"predicted": [pred()], "labels": [label()], "lighting": "good", "angle": "front", "correct": False},
        {"predicted": [pred("knee_flexion", "left", "less")], "labels": [], "lighting": "good", "angle": "front", "correct": True},
        # good/side: 1 FN
        {"predicted": [], "labels": [label()], "lighting": "good", "angle": "side", "correct": False},
        # low/front: perfect
        {"predicted": [pred()], "labels": [label()], "lighting": "low", "angle": "front", "correct": False},
        {"predicted": [], "labels": [], "lighting": "low", "angle": "front", "correct": True},
    ]


def test_slices_and_aggregates():
    m = score(toy_records())
    assert m["format"] == "simon.part5.metrics.v1"
    gf = m["slices"]["good/front"]
    assert (gf["tp"], gf["fp"], gf["fn"]) == (1, 1, 0)
    assert gf["precision"] == 0.5 and gf["recall"] == 1.0
    assert gf["correct_takes"] == 1 and gf["faults_on_correct_takes"] == 1
    gs = m["slices"]["good/side"]
    assert (gs["precision"], gs["recall"]) == (1.0, 0.0)
    assert m["by_lighting"]["low"]["precision"] == 1.0
    assert m["good_light"]["tp"] == 1 and m["good_light"]["fn"] == 1
    assert m["overall"]["takes"] == 5


def test_empty_corpus_scores_vacuously():
    m = score([])
    assert m["overall"]["precision"] == 1.0 and m["overall"]["recall"] == 1.0
    assert m["good_light"] is None


def test_evaluate_corpus_pairs_analyses_with_labels_by_take():
    labels = {"takes": [{"take_id": "t1", "lighting": "good", "angle": "front",
                         "correct": False, "faults": [label()]}]}
    m = evaluate_corpus(labels, {"t1": {"faults": [pred()]}})
    assert m["overall"]["tp"] == 1
    m2 = evaluate_corpus(labels, {})  # missing analysis = no predictions
    assert m2["overall"]["fn"] == 1


def test_real_labels_document_parses_into_records():
    labels = json.loads((ROOT / "fixtures/input/followers/labels.json").read_text())
    m = evaluate_corpus(labels, {})
    assert m["overall"]["takes"] == 96
    assert m["overall"]["fn"] == 84 and m["overall"]["fp"] == 0
    assert set(m["slices"]) == {f"{li}/{an}" for li in ("good", "low") for an in ("front", "45", "side")}
