"""The Part 5 done-check (`make check-5`): analyse every labelled take, score it, gate it.

Prints the metrics JSON (#13's `simon.part5.metrics.v1` plus a `gate` block) on stdout and
exits 0 only when every gated slice passes. Gating as decided in #18: good light at each
angle separately must reach precision ≥ 0.85 and recall ≥ 0.75 with no faults on correct
takes; low light is reported, not gated. Offline and deterministic.
"""
import json
import sys
from pathlib import Path

from .evaluate import evaluate_corpus
from .pipeline import analyse

ROOT = Path(__file__).resolve().parent.parent
LABELS = ROOT / "fixtures" / "input" / "followers" / "labels.json"
GATED = ("good/front", "good/45", "good/side")
MIN_PRECISION = 0.85
MIN_RECALL = 0.75
MAX_FAULTS_ON_CORRECT = 0


def gate(metrics, gated=GATED):
    """Pass/fail per gated slice. A slice with no takes, no labelled faults or no correct takes
    fails: it can't be shown to pass."""
    slices, failures = {}, []
    for name in gated:
        s = metrics["slices"].get(name)
        if s is None:
            slices[name] = False
            failures.append(f"{name}: no takes")
            continue
        why = []
        # Empty denominators score 1.0 in the metrics; a gate must not pass on nothing.
        if s["tp"] + s["fn"] == 0:
            why.append("no labelled faults, so recall can't be measured")
        if s["correct_takes"] == 0:
            why.append("no correct takes, so faults on correct takes can't be measured")
        if s["precision"] < MIN_PRECISION:
            why.append(f"precision {s['precision']} < {MIN_PRECISION}")
        if s["recall"] < MIN_RECALL:
            why.append(f"recall {s['recall']} < {MIN_RECALL}")
        if s["faults_on_correct_takes"] > MAX_FAULTS_ON_CORRECT:
            why.append(f"{s['faults_on_correct_takes']} fault(s) on correct takes")
        slices[name] = not why
        failures += [f"{name}: {w}" for w in why]
    return {"thresholds": {"precision": MIN_PRECISION, "recall": MIN_RECALL,
                           "faults_on_correct_takes": MAX_FAULTS_ON_CORRECT},
            "gated_slices": slices, "failures": failures, "passed": not failures}


def run(labels_path=LABELS, root=ROOT):
    labels = json.loads(Path(labels_path).read_text())
    analyses, errors = {}, []
    for take in labels["takes"]:
        try:
            analyses[take["take_id"]] = analyse(
                {"path": str(root / take["expected"])},
                {"path": str(root / take["follower"]), "take_id": take["take_id"]})
        except ValueError as e:  # InputError, AnalysisError, OutputError
            errors.append(f"{take['take_id']}: {e}")
    if errors:
        return None, errors
    metrics = evaluate_corpus(labels, analyses)
    metrics["gate"] = gate(metrics)
    return metrics, []


def main(argv=None):
    metrics, errors = run()
    if errors:
        print("check-5: FAIL, could not analyse every take:", file=sys.stderr)
        for e in errors:
            print(f"  {e}", file=sys.stderr)
        return 1
    print(json.dumps(metrics, indent=2))
    g = metrics["gate"]
    for name in GATED:
        s = metrics["slices"].get(name)
        if s:
            print(f"check-5: {name:11s} P {s['precision']:.2f}  R {s['recall']:.2f}  "
                  f"faults on correct takes {s['faults_on_correct_takes']}  "
                  f"{'pass' if g['gated_slices'][name] else 'FAIL'}", file=sys.stderr)
    print("check-5: PASS" if g["passed"] else "check-5: FAIL\n  " + "\n  ".join(g["failures"]),
          file=sys.stderr)
    return 0 if g["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
