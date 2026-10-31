import json
from pathlib import Path

from part5.evaluate import (canonical_label, evaluate_corpus, is_refused, match_faults, match_pairs, matches,
                            score, slice_name)

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


def test_match_pairs_says_which_prediction_satisfies_which_label():
    """The pairs behind `match_faults`' counts: {label index: prediction index}, one prediction per label."""
    preds = [pred(side="left"), pred(side="right")]
    labs = [label(side="both"), label(side="right")]
    pairs = match_pairs(preds, labs)
    assert pairs == {0: 0, 1: 1}  # left takes the `both` label so right is free for the right-only label
    assert match_pairs([pred(), pred()], [label()]) == {0: 0}
    assert match_pairs([], [label()]) == {} and match_pairs([pred()], []) == {}
    tp, matched_preds, matched_labels = match_faults(preds, labs)
    assert (tp, matched_preds, matched_labels) == (len(pairs), set(pairs.values()), set(pairs))


def test_slice_name_and_is_refused_are_the_ones_score_and_check_use():
    assert slice_name({"lighting": "low", "angle": "45"}) == "low/45"
    assert slice_name({"lighting": "good", "angle": "side", "variant": "dropout"}) == "dropout/side"
    assert is_refused({"status": {"code": "different_movement"}}) and not is_refused({"status": {"code": "ok"}})
    assert not is_refused({"faults": []}) and not is_refused({"status": None})


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


WARNED = {"status": {"code": "ok", "text": "x"}, "warnings": [{"code": "low_match", "text": "y"}],
          "faults": [dict(pred(), confidence="low")]}


def test_ac_k04_is_refused_reads_the_warnings_of_an_analysis_with_status_ok():
    """ADR-0012: a take is written with status ok and the warnings say why it is graded F."""
    assert is_refused(WARNED) and is_refused(dict(WARNED, warnings=[{"code": "not_enough_visible", "text": "z"}]))
    assert not is_refused(dict(WARNED, warnings=[])) and not is_refused({k: v for k, v in WARNED.items() if k != "warnings"})
    assert is_refused({"warnings": [{"code": "low_match", "text": "y"}]})   # with no status at all


def test_ac_k04_a_warned_take_counts_in_refused_and_its_labels_are_misses_whatever_faults_it_lists():
    labels = {"takes": [take("a", labels=[label()]), take("b", labels=[label()]), take("c")]}
    analyses = {"a": {"faults": [pred()]}, "b": WARNED, "c": {"status": {"code": "ok", "text": "y"}, "faults": []}}
    s = evaluate_corpus(labels, analyses)["slices"]["good/front"]
    assert (s["tp"], s["fp"], s["fn"], s["takes"], s["refused"]) == (1, 0, 1, 3, 1)   # b's listed fault is no prediction


def test_ac_k04_a_warned_correct_take_is_one_fault_on_a_correct_take_not_one_per_listed_fault():
    labels = {"takes": [take("a")]}
    two_faults = dict(WARNED, faults=[dict(pred(), confidence="low"), dict(pred("knee_flexion", "left", "less"), confidence="low")])
    s = evaluate_corpus(labels, {"a": two_faults})["slices"]["good/front"]
    assert (s["fp"], s["faults_on_correct_takes"], s["refused"]) == (0, 1, 1)


def test_a_refused_take_scores_no_predictions_even_if_faults_were_listed():
    s = score([{"predicted": [pred(), pred()], "labels": [label()], "lighting": "good", "angle": "front",
                "correct": False, "refused": True}])["slices"]["good/front"]
    assert (s["tp"], s["fp"], s["fn"], s["faults_on_correct_takes"], s["refused"]) == (0, 0, 1, 0, 1)


def test_a_refused_correct_take_counts_once_in_faults_on_correct_takes():
    """A wrong verdict on a correct take must not pass the "0 faults on correct takes" rule."""
    refused = {"predicted": [], "labels": [], "lighting": "good", "angle": "front", "correct": True, "refused": True}
    s = score([refused])["slices"]["good/front"]
    assert (s["fp"], s["correct_takes"], s["faults_on_correct_takes"], s["refused"]) == (0, 1, 1, 1)
    listed = score([{**refused, "predicted": [pred(), pred()]}])["slices"]["good/front"]
    assert listed["faults_on_correct_takes"] == 1  # one refusal, never the faults it would have listed
    accepted = score([{**refused, "refused": False, "predicted": [pred(), pred()]}])["slices"]["good/front"]
    assert accepted["faults_on_correct_takes"] == 2


def test_a_refused_correct_take_through_the_corpus_adds_to_every_level():
    labels = {"takes": [take("a"), take("b")]}
    metrics = evaluate_corpus(labels, {"a": REFUSED, "b": {"status": {"code": "ok", "text": "y"}, "faults": []}})
    assert metrics["slices"]["good/front"]["faults_on_correct_takes"] == 1
    assert metrics["overall"]["faults_on_correct_takes"] == 1 == metrics["good_light"]["faults_on_correct_takes"]


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
