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
    # A missing analysis must never score as clean: it raises, naming the takes.
    try:
        evaluate_corpus(labels, {})
        raise AssertionError("expected ValueError for a missing analysis")
    except ValueError as e:
        assert "t1" in str(e)
    # ...unless the caller explicitly opts into a partial corpus.
    m2 = evaluate_corpus(labels, {}, allow_missing=True)
    assert m2["overall"]["fn"] == 1


def test_knee_caving_label_maps_to_the_knee_valgus_measure():
    caving = {"type": "knee_caving", "measure": "knee_valgus", "side": "left", "direction": "more",
              "body_part": "legs"}
    assert canonical_label(caving) == ("knee_valgus", "left", "more")
    # A hand-written label without a type is translated from its measure field.
    assert canonical_label({"measure": "knee_valgus", "side": "right", "direction": "more"}) == (
        "knee_valgus", "right", "more")
    assert matches(pred("knee_valgus", "left", "more"), caving)
    assert not matches(pred("knee_valgus", "right", "more"), caving)
    assert not matches(pred("knee_valgus", "left", "less"), caving)


def take(take_id, angle="front", lighting="good", labels=(), **extra):
    return {"take_id": take_id, "lighting": lighting, "angle": angle, "correct": not labels,
            "faults": list(labels), **extra}


REFUSED = {"status": {"code": "different_movement", "text": "x"}, "faults": []}


def test_ac_k04_a_refused_take_counts_in_refused_and_its_labels_are_misses():
    """AC-K04: the slice's `refused` is 1 and the take's labels count as misses."""
    labels = {"takes": [take("a", labels=[label()]), take("b", labels=[label()]), take("c")]}
    analyses = {"a": {"faults": [pred()]}, "b": REFUSED, "c": {"status": {"code": "ok", "text": "y"}, "faults": []}}
    s = evaluate_corpus(labels, analyses)["slices"]["good/front"]
    assert (s["tp"], s["fp"], s["fn"], s["takes"], s["refused"]) == (1, 0, 1, 3, 1)
    assert s["recall"] == 0.5 and s["precision"] == 1.0
    assert evaluate_corpus(labels, analyses)["overall"]["refused"] == 1


def test_a_refused_take_scores_no_predictions_even_if_faults_were_listed():
    s = score([{"predicted": [pred()], "labels": [], "lighting": "good", "angle": "front",
                "correct": True, "refused": True}])["slices"]["good/front"]
    assert (s["fp"], s["faults_on_correct_takes"], s["refused"]) == (0, 0, 1)


def test_dropout_takes_get_their_own_slice_and_stay_out_of_the_lighting_slices():
    labels = {"takes": [take("a", angle="side", labels=[label()]),
                        take("b", angle="side", labels=[label()], variant="dropout", label_source="synthetic", seed=29),
                        take("c", angle="45", variant="clean", seed=29)]}
    analyses = {"a": {"faults": [pred()]}, "b": {"faults": []}, "c": {"faults": []}}
    m = evaluate_corpus(labels, analyses)
    assert set(m["slices"]) == {"good/side", "dropout/side", "good/45"}
    assert (m["slices"]["good/side"]["tp"], m["slices"]["good/side"]["fn"]) == (1, 0)
    assert (m["slices"]["dropout/side"]["tp"], m["slices"]["dropout/side"]["fn"]) == (0, 1)
    assert m["good_light"]["takes"] == 2 and m["by_lighting"]["dropout"]["takes"] == 1
    assert m["overall"]["takes"] == 3


def test_real_labels_document_parses_into_records():
    labels = json.loads((ROOT / "fixtures/input/followers/labels.json").read_text())
    m = evaluate_corpus(labels, {}, allow_missing=True)
    assert m["overall"]["takes"] == 108
    assert m["overall"]["fn"] == 96 and m["overall"]["fp"] == 0 and m["overall"]["refused"] == 0
    assert set(m["slices"]) == {f"{li}/{an}" for li in ("good", "low") for an in ("front", "45", "side")}
