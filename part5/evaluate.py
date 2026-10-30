"""Fault precision/recall: score predicted faults against labels, per angle × lighting slice.

Predicted faults are `analysis.json` fault objects (see docs/schemas.md); labels are
`labels.json` fault objects. The match rule, decided 2026-10-28 (#13):

- a prediction matches a label on **measure + side + direction**;
- a label with `side: "both"` accepts a prediction on either side (or `both`);
- trunk faults match at body-part level (side is ignored);
- matching is one-to-one (maximum cardinality), so one prediction can satisfy one label.

Two edges of the one-way `both` rule, so nobody is surprised later: a `both` label satisfied
by a left-only prediction does not count the missed right side (lenient), while a `both`
prediction against a one-sided label scores 0 (an FP and an FN) even though detection only
emits `both` when both sides fired (harsh). Changing either is a rule change, not a bug fix.

This module only scores; producing the analyses over a corpus is #10/#14's job, and the
thresholds that gate `make check-5` live in #14, not here.

A take analysed with a warning (ADR-0012: it is graded F and its faults carry low confidence) counts in
its slice's `refused` (the key keeps its name; the meaning is "analysed with a warning and grade F"), and its
labels score as misses. Such a take with no labels (a correct take) is a wrong verdict, so it counts once in
`faults_on_correct_takes`: a correct take that earns a warning must not satisfy the "no faults on correct
takes" rule. Takes labelled `variant: "dropout"` are
scored in their own `dropout/<angle>` slices so they never mix into the lighting slices.
"""

METRICS_FORMAT = "simon.part5.metrics.v1"

# labels.json speaks its own measure vocabulary; predictions speak the side-less #6 one.
# Keyed by the generator's fault `type`, which is unambiguous (its `foot_out` label says
# measure `thigh_direction`, but detection reports that fault as `foot_out`).
LABEL_TYPE_TO_MEASURE = {
    "arms_wider": "upper_arm_out",
    "foot_out": "foot_out",
    "knees_shallow": "knee_flexion",
    "elbow_bent": "elbow_flexion",
    "trunk_lean": "trunk_lean_forward",
    "knee_caving": "knee_valgus",
}
# Fallback for labels without a known type (e.g. hand-written labels for real takes):
# translate the label `measure` field instead.
LABEL_MEASURE_TO_MEASURE = {
    "upper_arm_direction": "upper_arm_out",
    "thigh_direction": "thigh_out",
    "knee_flexion": "knee_flexion",
    "elbow_flexion": "elbow_flexion",
    "trunk_lean_forward": "trunk_lean_forward",
    "knee_valgus": "knee_valgus",
}


def canonical_label(label_fault):
    """A labels.json fault → (measure, side, direction) in prediction vocabulary."""
    measure = LABEL_TYPE_TO_MEASURE.get(label_fault.get("type"))
    if measure is None:
        measure = LABEL_MEASURE_TO_MEASURE.get(label_fault.get("measure"), label_fault.get("measure"))
    return measure, label_fault.get("side"), label_fault.get("direction")


def _is_trunk(measure, body_part=None):
    return body_part == "torso" or (measure or "").startswith("trunk_")


def matches(pred, label):
    """Does a predicted fault dict match a labels.json fault? (decided rule, see module doc)"""
    lm, ls, ld = canonical_label(label)
    if pred.get("measure") != lm or pred.get("direction") != ld:
        return False
    if _is_trunk(lm, label.get("body_part")):
        return True
    return ls == "both" or pred.get("side") == ls


def match_pairs(predicted, labels):
    """Maximum one-to-one matching as {label index: prediction index}."""
    adj = [[j for j, lab in enumerate(labels) if matches(p, lab)] for p in predicted]
    owner = [-1] * len(labels)  # label j -> prediction index

    def augment(i, seen):
        for j in adj[i]:
            if seen[j]:
                continue
            seen[j] = True
            if owner[j] == -1 or augment(owner[j], seen):
                owner[j] = i
                return True
        return False

    for i in range(len(predicted)):
        augment(i, [False] * len(labels))
    return {j: i for j, i in enumerate(owner) if i != -1}


def match_faults(predicted, labels):
    """Maximum one-to-one matching. Returns (tp, matched_pred_idx, matched_label_idx)."""
    pairs = match_pairs(predicted, labels)
    return len(pairs), set(pairs.values()), set(pairs)


DROPOUT = "dropout"


def _blank():
    return {"tp": 0, "fp": 0, "fn": 0, "takes": 0, "correct_takes": 0,
            "faults_on_correct_takes": 0, "refused": 0}


def _group(record):
    """(lighting bucket, slice key) of a record: dropout takes get their own, else lighting/angle."""
    lighting = DROPOUT if record.get("variant") == DROPOUT else record["lighting"]
    return lighting, f"{lighting}/{record['angle']}"


def slice_name(record):
    """The slice a labelled take or score record is counted in, e.g. "good/side" or "dropout/45"."""
    return _group(record)[1]


def is_refused(analysis):
    """Was this analysis written with a warning (so graded F, ADR-0012)? A document before ADR-0012 that was
    refused (status other than ok) counts the same."""
    return bool(analysis.get("warnings")) or (analysis.get("status") or {}).get("code", "ok") != "ok"


def _finalise(s):
    """Add precision/recall. An empty denominator scores 1.0 (nothing predicted/labelled,
    nothing wrong); it never hides misses, which live in the other ratio."""
    s = dict(s)
    s["precision"] = round(s["tp"] / (s["tp"] + s["fp"]), 4) if s["tp"] + s["fp"] else 1.0
    s["recall"] = round(s["tp"] / (s["tp"] + s["fn"]), 4) if s["tp"] + s["fn"] else 1.0
    return s


def _wrong_verdicts(predicted, refused):
    """What a correct take is charged: each fault listed on it, or one for the refusal."""
    return 1 if refused else len(predicted)


def score(records):
    """Score a corpus. Each record: {"predicted": [fault dicts], "labels": [label faults],
    "lighting": str, "angle": str, "correct": bool (a take with no labelled faults),
    optional "variant": "dropout", optional "refused": bool (the guard refused the take)}.

    Returns the metrics document (JSON-ready): one entry per lighting × angle slice
    (`dropout/<angle>` for dropout takes), per-lighting aggregates, the good-light aggregate
    #14 gates on, and the overall line. A refused take has no predictions, so its labels are
    misses, and it is counted in `refused`; a refused correct take also counts once in
    `faults_on_correct_takes`.
    """
    slices, by_lighting, overall = {}, {}, _blank()
    for r in records:
        refused = bool(r.get("refused"))
        predicted, labels = ([] if refused else r.get("predicted", [])), r.get("labels", [])
        tp, _, _ = match_faults(predicted, labels)
        counts = {"tp": tp, "fp": len(predicted) - tp, "fn": len(labels) - tp, "takes": 1,
                  "correct_takes": 1 if not labels else 0,
                  "faults_on_correct_takes": _wrong_verdicts(predicted, refused) if not labels else 0,
                  "refused": 1 if refused else 0}
        lighting, key = _group(r)
        for bucket in (slices.setdefault(key, _blank()),
                       by_lighting.setdefault(lighting, _blank()), overall):
            for k, v in counts.items():
                bucket[k] += v
    return {"format": METRICS_FORMAT,
            "slices": {k: _finalise(v) for k, v in sorted(slices.items())},
            "by_lighting": {k: _finalise(v) for k, v in sorted(by_lighting.items())},
            "good_light": _finalise(by_lighting["good"]) if "good" in by_lighting else None,
            "overall": _finalise(overall)}


def records_from_corpus(labels_doc, analyses_by_take_id, allow_missing=False):
    """Pair a labels.json document with analysis documents keyed by take_id → score records.

    A take with no analysis raises `ValueError` listing the missing take_ids: scoring it as
    "no predictions" would let a crashed pipeline pass the correct-takes criterion.
    `allow_missing=True` is the explicit opt-in for tooling over a partial corpus.
    """
    missing = [t["take_id"] for t in labels_doc["takes"] if t["take_id"] not in analyses_by_take_id]
    if missing and not allow_missing:
        raise ValueError(f"missing analysis for {len(missing)} take(s): {missing}")
    records = []
    for take in labels_doc["takes"]:
        analysis = analyses_by_take_id.get(take["take_id"], {"faults": []})
        records.append({"predicted": analysis.get("faults", []), "labels": take["faults"],
                        "lighting": take["lighting"], "angle": take["angle"],
                        "correct": take["correct"], "variant": take.get("variant"),
                        "refused": is_refused(analysis)})
    return records


def evaluate_corpus(labels_doc, analyses_by_take_id, allow_missing=False):
    return score(records_from_corpus(labels_doc, analyses_by_take_id, allow_missing))
