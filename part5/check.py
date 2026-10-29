"""The Part 5 done-check (`make check-5`): analyse every labelled take, score it, gate it.

Prints one `simon.part5.check.v1` document (docs/specs/check-5.md, contracts/metrics.schema.json)
on stdout and a short summary on stderr. Exit 0 only when the gate passes, 1 when it fails,
2 when a labelled take can't be analysed or a set is missing or unusable.

The gate is the held-out set (`fixtures/input/heldout/`, whose labels.json names the seed: 29,
then 31, then 37; ADR-0003): good light at each angle separately must reach precision >= 0.85 and
recall >= 0.75 with no faults on correct takes, and no gated slice may be empty. Everything else
is reported and never gated: the seed 5 tuning slices, low light, the dropout variant, Part 3's
kit, the stock takes and the movement guard's refusals. Offline and deterministic.
"""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

from .detect import RULES_PATH
from .evaluate import evaluate_corpus
from .pipeline import analyse

ROOT = Path(__file__).resolve().parent.parent
FORMAT = "simon.part5.check.v1"
HELDOUT = ROOT / "fixtures" / "input" / "heldout"
TUNING = ROOT / "fixtures" / "input" / "followers"
ATTEMPTS = ROOT / "fixtures" / "heldout-attempts.json"
THRESHOLDS_DOC = ROOT / "docs" / "thresholds.md"
OUT_DIR = ROOT / "out" / "check-5"
HELDOUT_SEEDS = (29, 31, 37)  # ADR-0003: fixed now, scored in this order, once each
TUNING_SEED = 5
GATED = ("good/front", "good/45", "good/side")
MIN_PRECISION = 0.85
MIN_RECALL = 0.75
MAX_FAULTS_ON_CORRECT = 0
DATA_SOURCE = ("synthetic: held-out takes (seed {seed}, from {path}/labels.json) from "
               "scripts/make_dummy_followers.py; thresholds tuned on seed 5 only")


class CheckError(Exception):
    """The check can't run: a set is missing or unusable, or a take can't be analysed (exit 2)."""

    def __init__(self, messages):
        super().__init__("; ".join(messages))
        self.messages = list(messages)


def rel(path):
    path = Path(path).resolve()
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


# --- the gate ---
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
            why.append(f"precision {s['precision']} is below {MIN_PRECISION}")
        if s["recall"] < MIN_RECALL:
            why.append(f"recall {s['recall']} is below {MIN_RECALL}")
        if s["faults_on_correct_takes"] > MAX_FAULTS_ON_CORRECT:
            why.append(f"{s['faults_on_correct_takes']} fault(s) on correct takes")
        slices[name] = not why
        failures += [f"{name}: {w}" for w in why]
    return {"thresholds": {"precision": MIN_PRECISION, "recall": MIN_RECALL,
                           "faults_on_correct_takes": MAX_FAULTS_ON_CORRECT},
            "gated_slices": slices, "failures": failures, "passed": not failures}


# --- reading a labelled set ---
def load_labels(directory, what):
    """The set's labels.json, or a CheckError saying what is missing."""
    path = Path(directory) / "labels.json"
    if not path.is_file():
        raise CheckError([f"check-5: {rel(directory)} has no labels.json"
                          + (f"; generate it first: {what}" if what else "")])
    try:
        doc = json.loads(path.read_text())
        if not isinstance(doc.get("takes"), list) or not isinstance(doc.get("seed"), int):
            raise ValueError("needs an integer seed and a takes list")
    except (OSError, ValueError, AttributeError) as e:
        raise CheckError([f"check-5: {rel(path)}: {e}"]) from e
    return doc


def group_of(take):
    """The slice family of a take: its lighting, or "dropout" for a dropout copy."""
    return "dropout" if take.get("variant") == "dropout" else take["lighting"]


def slice_name(take):
    return f"{group_of(take)}/{take['angle']}"


def grouped(labels_doc):
    """The labels with each dropout copy's lighting set to "dropout", so evaluate keys its slices
    dropout/<angle> and the good-light slices stay clean takes only."""
    takes = [{**t, "lighting": group_of(t)} for t in labels_doc["takes"]]
    return {**labels_doc, "takes": takes}


def analyse_set(labels_doc, root=None):
    """Analyse every labelled take. Returns ({take_id: analysis}, errors): one message per take
    that can't be analysed, so the caller can name them all at once."""
    root, analyses, errors = Path(root or ROOT), {}, []
    for take in labels_doc["takes"]:
        take_id = take["take_id"]
        missing = [p for p in (take["expected"], take["follower"]) if not (root / p).is_file()]
        if missing:
            errors.append(f"check-5: {take_id}: {missing[0]} not found")
            continue
        try:
            analyses[take_id] = analyse({"path": str(root / take["expected"])},
                                        {"path": str(root / take["follower"]), "take_id": take_id})
        except ValueError as e:  # InputError, AnalysisError, OutputError
            errors.append(f"check-5: {take_id}: {e}")
    return analyses, errors


# --- scoring ---
def is_refused(analysis):
    return (analysis.get("status") or {}).get("code") == "different_movement"


def add_refused(metrics, labels_doc, analyses):
    """Set `refused` (takes the movement guard refused; their labels already score as misses) on
    every slice, lighting group and the overall line."""
    by_slice, by_group = {}, {}
    for take in labels_doc["takes"]:
        if is_refused(analyses[take["take_id"]]):
            by_slice[slice_name(take)] = by_slice.get(slice_name(take), 0) + 1
            by_group[group_of(take)] = by_group.get(group_of(take), 0) + 1
    for name, s in metrics["slices"].items():
        s["refused"] = by_slice.get(name, 0)
    for name, s in metrics.get("by_lighting", {}).items():
        s["refused"] = by_group.get(name, 0)
    if metrics.get("good_light"):
        metrics["good_light"]["refused"] = by_group.get("good", 0)
    metrics["overall"]["refused"] = sum(by_slice.values())


def score_set(labels_doc, analyses):
    metrics = evaluate_corpus(grouped(labels_doc), analyses)
    add_refused(metrics, labels_doc, analyses)
    return metrics


def slices_starting(metrics, prefix):
    return {k: v for k, v in metrics["slices"].items() if k.startswith(prefix)}


def take_report(set_name, labels_doc, analyses):
    """One row per take for out/check-5/takes.json (never part of the gate document)."""
    rows = []
    for take in labels_doc["takes"]:
        a = analyses[take["take_id"]]
        rows.append({"set": set_name, "take_id": take["take_id"], "slice": slice_name(take),
                     "refused": is_refused(a),
                     "predicted": [{k: f.get(k) for k in ("measure", "side", "direction", "magnitude_deg")}
                                   for f in a.get("faults", [])],
                     "labelled": [{k: f.get(k) for k in ("type", "side", "direction", "magnitude_deg")}
                                  for f in take["faults"]]})
    return rows


# --- attempts (ADR-0003) ---
def next_unused_seed(attempts):
    used = {a["seed"] for a in attempts}
    return next((s for s in HELDOUT_SEEDS if s not in used), None)


def load_attempts(path):
    path = Path(path)
    if not path.is_file():
        return []
    try:
        return list(json.loads(path.read_text())["attempts"])
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise CheckError([f"check-5: {rel(path)}: not a held-out attempts file ({e})"]) from e


def thresholds_record(seed, text):
    """The freeze commit, rules hash and approach family docs/thresholds.md records for a seed, or {}.

    The section is the heading that mentions `seed <n>`, up to the next heading; its lines read
    `Freeze commit: <sha>`, `rules_sha256: <hash>` and `Approach family: <words>`.
    """
    head = re.search(rf"^#+[^\n]*\bseed {seed}\b[^\n]*\n(.*?)(?=^#|\Z)", text, re.M | re.S | re.I)
    if not head:
        return {}
    body, found = head.group(1), {}
    for key, pattern in (("freeze_commit", r"freeze commit:?\s*`?([0-9a-f]{7,40})"),
                         ("rules_sha256", r"rules_sha256:?\s*`?([0-9a-f]{64})"),
                         ("approach", r"approach family:?\s*([^\n]+)")):
        m = re.search(pattern, body, re.I)
        if m:
            found[key] = m.group(1).strip()
    return found


def current_attempt(seed, passed, metrics, rules_sha, recorded):
    return {"seed": seed, "freeze_commit": recorded.get("freeze_commit", "not recorded"),
            "rules_sha256": rules_sha, "approach": recorded.get("approach", "not recorded"),
            "passed": passed, "slices": metrics["slices"]}


def attempts_list(seed, current, earlier):
    """Every attempt in seed order: the recorded earlier ones, then this run's (which replaces a
    recorded entry for the same seed, so a rerun of the current set never lists it twice)."""
    kept = [a for a in earlier if a["seed"] != seed] + [current]
    return sorted(kept, key=lambda a: HELDOUT_SEEDS.index(a["seed"]) if a["seed"] in HELDOUT_SEEDS else 99)


def check_seed(seed, attempts, directory):
    if seed not in HELDOUT_SEEDS:
        raise CheckError([f"check-5: {rel(directory)}/labels.json names seed {seed}; "
                          f"the held-out seeds are {', '.join(map(str, HELDOUT_SEEDS))}"])
    later = [a["seed"] for a in attempts
             if a["seed"] in HELDOUT_SEEDS and HELDOUT_SEEDS.index(a["seed"]) > HELDOUT_SEEDS.index(seed)]
    if later:
        raise CheckError([f"check-5: seed {seed} is retired: seed {later[0]} was already scored; "
                          f"generate the next unused seed ({next_unused_seed(attempts)})"])


def rules_hash(path=RULES_PATH):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# --- the real-take blocks ---
def real_blocks(root=None):
    """The kit and stock report blocks (real-takes.md). The adapter that scores them is TICKET-025."""
    stock = Path(root or ROOT) / "fixtures" / "input" / "eval" / "real"
    return {"kit": {"gated": False, "source": "Part 3 conformance kit", "takes": [],
                    "note": "the real-take adapter is not wired in yet (TICKET-025); run part5 report-real once it is"},
            "stock": {"gated": False, "source": "fixtures/input/eval/real", "takes": [],
                      "note": ("stock takes not delivered yet (TICKET-026)" if not stock.is_dir()
                               else "the real-take adapter is not wired in yet (TICKET-025)")}}


# --- the document ---
def run_check(heldout=None, tuning=None, attempts_path=None, thresholds_path=None, rules_path=None, root=None):
    """Analyse and score both sets. Returns (document, per-take rows); raises CheckError.
    Each default is the module constant, read when called."""
    heldout, tuning = Path(heldout or HELDOUT), Path(tuning or TUNING)
    thresholds_path, rules_path = Path(thresholds_path or THRESHOLDS_DOC), Path(rules_path or RULES_PATH)
    root = Path(root or ROOT)
    attempts = load_attempts(attempts_path or ATTEMPTS)
    wanted = next_unused_seed(attempts)
    hint = f"make heldout-data SEED={wanted}" if wanted else "every held-out seed has been scored"
    held = load_labels(heldout, hint)
    check_seed(held["seed"], attempts, heldout)
    tune = load_labels(tuning, "make dummy-data")
    if tune["seed"] != TUNING_SEED:
        raise CheckError([f"check-5: {rel(tuning)}/labels.json names seed {tune['seed']}; "
                          f"the tuning set is seed {TUNING_SEED}"])
    (held_analyses, held_errors), (tune_analyses, tune_errors) = analyse_set(held, root), analyse_set(tune, root)
    if held_errors or tune_errors:
        raise CheckError(held_errors + tune_errors)
    held_metrics, tune_metrics = score_set(held, held_analyses), score_set(tune, tune_analyses)

    g = gate(held_metrics)
    sha = rules_hash(rules_path)
    text = thresholds_path.read_text() if thresholds_path.is_file() else ""
    recorded = {**thresholds_record(held["seed"], text),
                **{k: v for a in attempts if a["seed"] == held["seed"] for k, v in a.items()}}
    current = current_attempt(held["seed"], g["passed"], held_metrics, sha, recorded)
    doc = {
        "format": FORMAT,
        "data_source": DATA_SOURCE.format(seed=held["seed"], path=rel(heldout)),
        "gate": {"set": rel(heldout), "seed": held["seed"], "slices": list(GATED),
                 "thresholds": g["thresholds"], "passed": g["passed"], "failures": g["failures"],
                 "metrics": held_metrics},
        "attempts": attempts_list(held["seed"], current, attempts),
        "tuning": {"set": rel(tuning), "seed": tune["seed"], "gated": False, "metrics": tune_metrics},
        "report": {"low_light": {"gated": False, "slices": slices_starting(held_metrics, "low/")},
                   "dropout": {"gated": False, "slices": slices_starting(held_metrics, "dropout/")},
                   **real_blocks(root),
                   "refusals": {k: v["refused"] for k, v in held_metrics["slices"].items()}},
        "rules_sha256": sha,
    }
    frozen = recorded.get("rules_sha256")
    if frozen and frozen != sha:
        print(f"check-5: warning: part5/rules.json differs from the hash frozen for seed {held['seed']} "
              f"in docs/thresholds.md", file=sys.stderr)
    rows = take_report("heldout", held, held_analyses) + take_report("tuning", tune, tune_analyses)
    return doc, rows


def write_outputs(doc, rows, json_out):
    text = json.dumps(doc, indent=2) + "\n"
    out = Path(json_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text)
    (out.parent / "takes.json").write_text(json.dumps(rows, indent=1) + "\n")
    return text


def summary(doc):
    lines = []
    for name in doc["gate"]["slices"]:
        s = doc["gate"]["metrics"]["slices"].get(name)
        if s:
            ok = not any(f.startswith(f"{name}:") for f in doc["gate"]["failures"])
            lines.append(f"check-5: {name:11s} P {s['precision']:.2f}  R {s['recall']:.2f}  "
                         f"faults on correct takes {s['faults_on_correct_takes']}  "
                         f"refused {s.get('refused', 0)}  {'pass' if ok else 'FAIL'}")
    failures = doc["gate"]["failures"]
    if failures:
        lines += [f"  {f}" for f in failures]
        lines.append(f"check-5: FAIL ({len(failures)} criteria)")
    else:
        lines.append("check-5: PASS")
    return lines


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m part5.check", description=__doc__.splitlines()[0])
    ap.add_argument("--set", default=None, help="the held-out set (default fixtures/input/heldout)")
    ap.add_argument("--json-out", default=None, help="also write the JSON here (default out/check-5/metrics.json)")
    args = ap.parse_args(argv)
    try:
        doc, rows = run_check(heldout=args.set)
    except CheckError as e:
        print("\n".join(e.messages), file=sys.stderr)
        return 2
    sys.stdout.write(write_outputs(doc, rows, args.json_out or OUT_DIR / "metrics.json"))
    print("\n".join(summary(doc)), file=sys.stderr)
    return 0 if doc["gate"]["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
