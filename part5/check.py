"""The Part 5 done-check (`make check-5`): analyse every labelled take, score it, gate it.

Prints one `simon.part5.check.v1` document (docs/specs/check-5.md, contracts/metrics.schema.json)
on stdout and a short summary on stderr. Exit 0 only when the gate passes, 1 when it fails,
2 when a labelled take can't be analysed, a set is missing or unusable, or part5/rules.json is not
the file frozen for the seed (no freeze record, or another hash, in docs/thresholds.md), or its `score`
params are not the ones frozen in fixtures/score-heldout.json.

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

from . import real
from .detect import RULES_PATH
from .evaluate import evaluate_corpus, is_refused, slice_name
from .score import params_sha256
from .score_report import (FEET_KEYS, analyse, correct_good_failures, distribution, entries_of, feet_kwargs, run_sweep,
                           sweep_failures, verdicts)

ROOT = Path(__file__).resolve().parent.parent
FORMAT = "simon.part5.check.v1"
HELDOUT = ROOT / "fixtures" / "input" / "heldout"
TUNING = ROOT / "fixtures" / "input" / "followers"
ATTEMPTS = ROOT / "fixtures" / "heldout-attempts.json"
SCORE_RECORD = ROOT / "fixtures" / "score-heldout.json"
THRESHOLDS_DOC = ROOT / "docs" / "thresholds.md"
OUT_DIR = ROOT / "out" / "check-5"
HELDOUT_SEEDS = (29, 31, 37)  # ADR-0003: fixed now, scored in this order, once each
TUNING_SEED = 5
GATED = ("good/front", "good/45", "good/side")
MIN_PRECISION = 0.85
MIN_RECALL = 0.75
MAX_FAULTS_ON_CORRECT = 0
# The stderr words for a score target's verdict (`verdicts()`: pass, fail, no takes). A missed target is reported, never
# gated, so a line above `check-5: PASS` must not read like a failure.
TARGET_WORDS = {"pass": "target met", "fail": "target missed (reported, not gated)",
                "no takes": "target not judged (no takes)"}
DETECTION_SHA_PATTERN = r"detection_sha256:?\s*`?([0-9a-f]{64})"
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


def analyse_set(labels_doc, root=None):
    """Analyse every labelled take. Returns ({take_id: analysis}, errors): one message per take
    that can't be analysed, so the caller can name them all at once."""
    root, analyses, errors = Path(root or ROOT), {}, []
    for take in labels_doc["takes"]:
        take_id = take["take_id"]
        named = [take[key] for key in FEET_KEYS if take.get(key)]   # TICKET-040: Part 2 shaped foot side files
        missing = [p for p in (take["expected"], take["follower"], *named) if not (root / p).is_file()]
        if missing:
            errors.append(f"check-5: {take_id}: {missing[0]} not found")
            continue
        expected = {"path": str(root / take["expected"])}
        follower = {"path": str(root / take["follower"]), "take_id": take_id}
        try:
            analyses[take_id] = analyse(expected, follower, **feet_kwargs(take, root))   # {} for a take naming none
        except ValueError as e:  # InputError, AnalysisError, OutputError
            errors.append(f"check-5: {take_id}: {e}")
    return analyses, errors


# --- scoring (`part5.evaluate`: dropout copies get their own `dropout/<angle>` slices, and every slice,
# lighting group and the overall line carries `refused`) ---
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
            "rules_sha256": recorded.get("rules_sha256", rules_sha), "approach": recorded.get("approach", "not recorded"),
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


def detection_hash(path=RULES_PATH):
    """sha256 of the detection rules: part5/rules.json without its `score` key, serialised with sorted
    keys and compact separators (ADR-0007). The score params are not detection rules."""
    rules = {k: v for k, v in json.loads(Path(path).read_text()).items() if k != "score"}
    return hashlib.sha256(json.dumps(rules, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def recorded_detection_hash(text):
    """The `detection_sha256` docs/thresholds.md records under "Score", or None."""
    section = re.search(r"^##\s+Score\b[^\n]*\n(.*?)(?=^#{1,2}\s|\Z)", text, re.M | re.S)
    m = re.search(DETECTION_SHA_PATTERN, section.group(1), re.I) if section else None
    return m.group(1) if m else None


def require_frozen(seed, sha, frozen, detection=None, recorded_detection=None):
    """A seed is scored only against the rules frozen for it (ADR-0003): docs/thresholds.md must
    record a rules_sha256 for the seed and it must equal the hash of part5/rules.json now, or (ADR-0007)
    the detection rules, without the `score` key, must equal the `detection_sha256` recorded under "Score"."""
    if not frozen.get("rules_sha256"):
        raise CheckError([f"check-5: docs/thresholds.md has no freeze record (rules_sha256) for seed {seed}; "
                          "freeze part5/rules.json and record its hash there before scoring the seed"])
    if detection is not None and detection == recorded_detection:
        return
    if frozen["rules_sha256"] != sha:
        raise CheckError([f"check-5: part5/rules.json differs from the hash frozen for seed {seed} in "
                          "docs/thresholds.md; a seed is scored once, against the rules frozen for it"])


def score_params_hash(path=RULES_PATH):
    """sha256 of the `score` block of part5/rules.json, as `score.params_sha256` writes it into every score."""
    return params_sha256(json.loads(Path(path).read_text()).get("score"))


def recorded_score_hash(path):
    """The `params_sha256` the newest attempt in the held-out score record (fixtures/score-heldout.json) froze,
    or None when the record is missing or has none."""
    try:
        return json.loads(Path(path).read_text())["attempts"][-1]["params_sha256"]
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        return None


def require_score_frozen(current, recorded):
    """The score params are frozen when the held-out score report is recorded (ADR-0007): the `score` block of
    part5/rules.json must still hash to what fixtures/score-heldout.json recorded. The detection freeze above
    deliberately leaves that block out, so without this check a score edit would pass unseen."""
    if not recorded:
        raise CheckError(["check-5: fixtures/score-heldout.json has no frozen score params (params_sha256); "
                          "record the score freeze there before scoring"])
    if current != recorded:
        raise CheckError([f"check-5: the score params in part5/rules.json (sha256 {current[:12]}) differ from the "
                          f"ones frozen in fixtures/score-heldout.json (sha256 {recorded[:12]}); the score params "
                          "are frozen once the held-out score report is recorded (ADR-0007)"])


# --- the score (ADR-0007): the gate adds correct good-light takes at A and a monotonic sweep ---
def score_gate(g, labels_doc, analyses, sweeps):
    """`g` (the precision and recall gate) with the score criteria added to its failures; `passed` needs all."""
    failures = g["failures"] + correct_good_failures(labels_doc, analyses) + sweep_failures(sweeps)
    return {**g, "failures": failures, "passed": not failures, "sweep": {k: [list(p) for p in v] for k, v in sweeps.items()}}


def real_grades(block):
    """{grade: count} of the scored real takes in a kit or stock block."""
    grades = {}
    for t in block.get("takes", []):
        if t.get("score"):
            grades[t["score"]["grade"]] = grades.get(t["score"]["grade"], 0) + 1
    return grades


def score_block(held, held_analyses, tune, tune_analyses, real_report):
    """The reported (never gated beyond `gate`) grade distribution per slice of every set: held-out, seed 5,
    kit and stock. Low light is reported, never graded against a target."""
    held_dist = distribution(entries_of(held, held_analyses))
    return {"gated": False, "version": "simon.score.v1",
            "heldout": {"seed": held["seed"], "slices": held_dist, "targets": verdicts(held_dist)},
            "tuning": {"seed": tune["seed"], "slices": distribution(entries_of(tune, tune_analyses))},
            "kit": {"grades": real_grades(real_report["kit"])}, "stock": {"grades": real_grades(real_report["stock"])}}


# --- the real-take blocks ---
def require_unchanged_scores(seed, metrics, attempts):
    """A scored seed is retired (ADR-0003): rerunning it only verifies, so its slices must equal the
    recorded attempt. A difference means scoring code changed after the freeze, which needs a new
    attempt on the next seed, so the check refuses instead of publishing the new numbers."""
    rec = next((a for a in attempts if a["seed"] == seed), None)
    if rec is None or rec.get("slices") == metrics["slices"]:
        return
    names = set(rec.get("slices", {})) | set(metrics["slices"])
    changed = sorted(n for n in names if rec.get("slices", {}).get(n) != metrics["slices"].get(n))
    raise CheckError([f"check-5: seed {seed} scores differently from its recorded attempt in "
                      f"fixtures/heldout-attempts.json ({', '.join(changed)}); scoring changed after the "
                      "freeze, which needs a new attempt on the next seed (docs/specs/calibration.md)"])


def real_blocks(root=None):
    """The kit and stock report blocks (real-takes.md), from `part5.real`. Reported and never gated:
    fixtures that are missing or malformed leave the blocks empty with the reason, never a failed check."""
    try:
        return real.check_blocks(real.build_report(Path(root or ROOT)))
    except real.RealError as e:
        return real.unavailable_blocks(e)


# --- the document ---
def run_check(heldout=None, tuning=None, attempts_path=None, thresholds_path=None, rules_path=None, root=None,
              score_record_path=None):
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
    sha, detection = rules_hash(rules_path), detection_hash(rules_path)
    text = thresholds_path.read_text() if thresholds_path.is_file() else ""
    frozen = thresholds_record(held["seed"], text)
    require_frozen(held["seed"], sha, frozen, detection, recorded_detection_hash(text))
    require_score_frozen(score_params_hash(rules_path), recorded_score_hash(score_record_path or SCORE_RECORD))
    (held_analyses, held_errors), (tune_analyses, tune_errors) = analyse_set(held, root), analyse_set(tune, root)
    if held_errors or tune_errors:
        raise CheckError(held_errors + tune_errors)
    real_report = real_blocks(root)
    held_metrics, tune_metrics = evaluate_corpus(held, held_analyses), evaluate_corpus(tune, tune_analyses)
    require_unchanged_scores(held["seed"], held_metrics, attempts)

    g = score_gate(gate(held_metrics), held, held_analyses, run_sweep(OUT_DIR / "sweep"))
    recorded = {**frozen, **{k: v for a in attempts if a["seed"] == held["seed"] for k, v in a.items()}}
    current = current_attempt(held["seed"], g["passed"], held_metrics, sha, recorded)
    doc = {
        "format": FORMAT,
        "data_source": DATA_SOURCE.format(seed=held["seed"], path=rel(heldout)),
        "gate": {"set": rel(heldout), "seed": held["seed"], "slices": list(GATED),
                 "thresholds": g["thresholds"], "passed": g["passed"], "failures": g["failures"], "sweep": g["sweep"],
                 "metrics": held_metrics},
        "attempts": attempts_list(held["seed"], current, attempts),
        "tuning": {"set": rel(tuning), "seed": tune["seed"], "gated": False, "metrics": tune_metrics},
        "report": {"low_light": {"gated": False, "slices": slices_starting(held_metrics, "low/")},
                   "dropout": {"gated": False, "slices": slices_starting(held_metrics, "dropout/")},
                   **real_report,
                   "refusals": {"gated": False, **{k: v["refused"] for k, v in held_metrics["slices"].items()}},
                   "score": score_block(held, held_analyses, tune, tune_analyses, real_report)},
        "rules_sha256": sha,
        "detection_sha256": detection,
    }
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
    sc = doc["report"]["score"]["heldout"]
    for key, d in sc["slices"].items():
        grades = ", ".join(f"{g} {c}" for g, c in d["grades"].items())
        target = f"  {TARGET_WORDS.get(sc['targets'][key], sc['targets'][key])}" if key in sc["targets"] else "  (reported)"
        lines.append(f"check-5: score {key:7s} n {d['n']:3d}  min {d['min']}  median {d['median']}  max {d['max']}  "
                     f"{grades}{target}")
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
