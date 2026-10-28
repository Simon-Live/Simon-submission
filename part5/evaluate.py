"""Fault precision/recall: score predicted faults against labels, per angle × lighting slice.

Predicted faults are `analysis.json` fault objects (see docs/schemas.md); labels are
`labels.json` fault objects. The match rule, decided 2026-10-28 (#13):

- a prediction matches a label on **measure + side + direction**;
- a label with `side: "both"` accepts a prediction on either side (or `both`);
- trunk faults match at body-part level (side is ignored);
- matching is one-to-one (maximum cardinality), so one prediction can satisfy one label.

This module only scores; producing the analyses over a corpus is #10/#14's job, and the
thresholds that gate `make check-5` live in #14, not here.
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
}
# Fallback for labels without a known type (e.g. hand-written labels for real takes):
# translate the label `measure` field instead.
LABEL_MEASURE_TO_MEASURE = {
    "upper_arm_direction": "upper_arm_out",
    "thigh_direction": "thigh_out",
    "knee_flexion": "knee_flexion",
    "elbow_flexion": "elbow_flexion",
    "trunk_lean_forward": "trunk_lean_forward",
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


def match_faults(predicted, labels):
    """Maximum one-to-one matching. Returns (tp, matched_pred_idx, matched_label_idx)."""
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
    matched_labels = {j for j, i in enumerate(owner) if i != -1}
    matched_preds = {i for i in owner if i != -1}
    return len(matched_labels), matched_preds, matched_labels


def _blank():
    return {"tp": 0, "fp": 0, "fn": 0, "takes": 0, "correct_takes": 0,
            "faults_on_correct_takes": 0}


def _finalise(s):
    """Add precision/recall. An empty denominator scores 1.0 (nothing predicted/labelled,
    nothing wrong); it never hides misses, which live in the other ratio."""
    s = dict(s)
    s["precision"] = round(s["tp"] / (s["tp"] + s["fp"]), 4) if s["tp"] + s["fp"] else 1.0
    s["recall"] = round(s["tp"] / (s["tp"] + s["fn"]), 4) if s["tp"] + s["fn"] else 1.0
    return s


def score(records):
    """Score a corpus. Each record: {"predicted": [fault dicts], "labels": [label faults],
    "lighting": str, "angle": str, "correct": bool (a take with no labelled faults)}.

    Returns the metrics document (JSON-ready): one entry per lighting × angle slice,
    per-lighting aggregates, the good-light aggregate #14 gates on, and the overall line.
    """
    slices, by_lighting, overall = {}, {}, _blank()
    for r in records:
        predicted, labels = r.get("predicted", []), r.get("labels", [])
        tp, _, _ = match_faults(predicted, labels)
        counts = {"tp": tp, "fp": len(predicted) - tp, "fn": len(labels) - tp, "takes": 1,
                  "correct_takes": 1 if not labels else 0,
                  "faults_on_correct_takes": len(predicted) if not labels else 0}
        for bucket in (slices.setdefault(f'{r["lighting"]}/{r["angle"]}', _blank()),
                       by_lighting.setdefault(r["lighting"], _blank()), overall):
            for k, v in counts.items():
                bucket[k] += v
    return {"format": METRICS_FORMAT,
            "slices": {k: _finalise(v) for k, v in sorted(slices.items())},
            "by_lighting": {k: _finalise(v) for k, v in sorted(by_lighting.items())},
            "good_light": _finalise(by_lighting["good"]) if "good" in by_lighting else None,
            "overall": _finalise(overall)}


def records_from_corpus(labels_doc, analyses_by_take_id):
    """Pair a labels.json document with analysis documents keyed by take_id → score records."""
    records = []
    for take in labels_doc["takes"]:
        analysis = analyses_by_take_id.get(take["take_id"], {"faults": []})
        records.append({"predicted": analysis.get("faults", []), "labels": take["faults"],
                        "lighting": take["lighting"], "angle": take["angle"],
                        "correct": take["correct"]})
    return records


def evaluate_corpus(labels_doc, analyses_by_take_id):
    return score(records_from_corpus(labels_doc, analyses_by_take_id))
