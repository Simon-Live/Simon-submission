"""The Part 5 done-check (`make check-5`): analyse every labelled take, score it, gate it.

Prints one `simon.part5.check.v1` document (docs/specs/check-5.md, contracts/metrics.schema.json)
on stdout and a short summary on stderr. Exit 0 only when the gate passes, 1 when it fails,
2 when a labelled take can't be analysed, a set is missing or unusable, or part5/rules.json is not
the file frozen for the seed (no freeze record, or another hash, in docs/thresholds.md), or its `score`
params are not the ones frozen in fixtures/score-heldout.json.

The gate is the held-out set (`fixtures/input/heldout/`, whose labels.json names the seed: 29, then 31,
then 37, then the second series 67, 71, 73; ADR-0003, ADR-0017): good light at each angle separately must reach
precision >= 0.85 and recall >= 0.75 with no faults on correct takes, and no gated slice may be empty. Everything else
is reported and never gated: the seed 5 tuning slices, low light, the dropout variant, Part 3's
kit, the stock takes and the movement guard's refusals. Offline and deterministic.

Every take is analysed with no profile named, which is `fitness`, the rules unchanged (ADR-0016): `dance` and `rehab`
are never run here. The document carries `profiles_sha256`, the hash of part5/profiles.json, for information only.
"""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

from . import profiles, real
from .detect import RULES_PATH
from .evaluate import evaluate_corpus, is_refused, slice_name
from .score import SCORE_SEEDS, VERSION_V1, params_sha256
from .score_report import (FEET_KEYS, TUNING_SEED, analyse, correct_good_failures, distribution, entries_of, feet_kwargs,
                           run_sweep, sweep_failures, targets_of, verdicts)

ROOT = Path(__file__).resolve().parent.parent
FORMAT = "simon.part5.check.v1"
HELDOUT = ROOT / "fixtures" / "input" / "heldout"
TUNING = ROOT / "fixtures" / "input" / "followers"
ATTEMPTS = ROOT / "fixtures" / "heldout-attempts.json"
SCORE_RECORD = ROOT / "fixtures" / "score-heldout.json"
THRESHOLDS_DOC = ROOT / "docs" / "thresholds.md"
OUT_DIR = ROOT / "out" / "check-5"
# ADR-0003: fixed before any tuning, scored in this order, once each. ADR-0017 appended the second series (67, 71, 73)
# before any detection change of attempt 4; 59 and 61 are the score seeds of v2 and v3 (ADR-0018, ADR-0019), not seeds here.
HELDOUT_SEEDS = (29, 31, 37, 67, 71, 73)
# The second series (ADR-0017): a scored seed of it must carry its own `detection_sha256` line in its attempt record
# (recheck residual 4), so `require_frozen` never judges it by the one global line under "Score".
SECOND_SERIES = HELDOUT_SEEDS[3:]
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
    `Freeze commit: <sha>`, `rules_sha256: <hash>`, `detection_sha256: <hash>` (the detection rules of that freeze,
    so a scored seed is checked against its own attempt, pre-freeze review B3) and `Approach family: <words>`.
    """
    head = re.search(rf"^#+[^\n]*\bseed {seed}\b[^\n]*\n(.*?)(?=^#|\Z)", text, re.M | re.S | re.I)
    if not head:
        return {}
    body, found = head.group(1), {}
    for key, pattern in (("freeze_commit", r"freeze commit:?\s*`?([0-9a-f]{7,40})"),
                         ("rules_sha256", r"rules_sha256:?\s*`?([0-9a-f]{64})"),
                         ("detection_sha256", DETECTION_SHA_PATTERN),
                         ("approach", r"approach family:?\s*([^\n]+)")):
        m = re.search(pattern, body, re.I)
        if m:
            found[key] = m.group(1).strip()
    return found


def current_attempt(seed, passed, metrics, rules_sha, recorded, record=None):
    """This run's attempt entry. `recorded` is the freeze section of docs/thresholds.md merged with the seed's record;
    `record` is the seed's entry in fixtures/heldout-attempts.json, or None for a seed not scored yet (TICKET-058 R4a).
    A recorded seed carries every other field of its record verbatim (`scored`, `scored_at`, `command`, `exit`, as the
    earlier attempts are published); `passed` stays this run's gate and `slices` this run's numbers, which
    `require_unchanged_scores` has already made equal to the record's. A seed with no record gets the six fields only."""
    entry = {"seed": seed, "freeze_commit": recorded.get("freeze_commit", "not recorded"),
             "rules_sha256": recorded.get("rules_sha256", rules_sha), "approach": recorded.get("approach", "not recorded"),
             "passed": passed, "slices": metrics["slices"]}
    return {**entry, **{k: v for k, v in (record or {}).items() if k not in entry}}


def attempts_list(seed, current, earlier):
    """Every attempt in seed order: the recorded earlier ones, then this run's (which replaces a
    recorded entry for the same seed, so a rerun of the current set never lists it twice)."""
    kept = [a for a in earlier if a["seed"] != seed] + [current]
    return sorted(kept, key=lambda a: HELDOUT_SEEDS.index(a["seed"]) if a["seed"] in HELDOUT_SEEDS else 99)


def check_seed(seed, attempts, directory):
    """The seed in `directory`'s labels must be a held-out seed that is not retired and does not skip one: the seed
    after the last one scored (the next unused), or a scored seed that is the latest (a rerun only verifies it)."""
    if seed not in HELDOUT_SEEDS:
        raise CheckError([f"check-5: {rel(directory)}/labels.json names seed {seed}; "
                          f"the held-out seeds are {', '.join(map(str, HELDOUT_SEEDS))}"])
    later = [a["seed"] for a in attempts
             if a["seed"] in HELDOUT_SEEDS and HELDOUT_SEEDS.index(a["seed"]) > HELDOUT_SEEDS.index(seed)]
    if later:
        raise CheckError([f"check-5: seed {seed} is retired: seed {later[0]} was already scored; "
                          f"generate the next unused seed ({next_unused_seed(attempts)})"])
    wanted = next_unused_seed(attempts)
    if seed not in {a["seed"] for a in attempts} and seed != wanted:
        raise CheckError([f"check-5: seed {seed} skips seed {wanted}, which is not scored yet; the held-out seeds are "
                          f"scored in order (ADR-0003): generate the next unused seed ({wanted})"])


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


def require_frozen(seed, sha, frozen, detection=None, recorded_detection=None, scored=False):
    """A seed is scored only against the rules frozen for it (ADR-0003): docs/thresholds.md must
    record a rules_sha256 for the seed and it must equal the hash of part5/rules.json now, or (ADR-0007) the detection
    rules, without the `score` key, must equal the detection hash frozen for the seed. That is the seed's own
    `detection_sha256` line when its section has one, else (a seed not scored yet) the one recorded under "Score". A
    seed that is already `scored` (it has an attempt) is judged by its own record alone: the "Score" hash is for the
    current freeze, and letting it stand for a retired seed would let `make check-5` analyse that seed again under
    rules it was never frozen for (pre-freeze review B3). A scored seed of the second series (`SECOND_SERIES`, seeds 67,
    71, 73) must have its own `detection_sha256` line whichever way the rules compare (recheck residual 4): without it
    the record cannot say what the seed was frozen with, and the check refuses, before any take is analysed.

    What this does not cover (a known limit, stakeholder-proxy ruling on recheck residual 4): the line holds the hash of
    the detection rules, not of the code. A deliberate revert of rules.json to a retired attempt's bytes, under later
    code, passes this check; the guard against it is `require_unchanged_scores`, which after the analysis refuses a
    scored seed whose numbers differ from its recorded attempt. There is no requirement on a `git diff` of `part5/`."""
    if not frozen.get("rules_sha256"):
        raise CheckError([f"check-5: docs/thresholds.md has no freeze record (rules_sha256) for seed {seed}; "
                          "freeze part5/rules.json and record its hash there before scoring the seed"])
    if scored and seed in SECOND_SERIES and not frozen.get("detection_sha256"):
        raise CheckError([f"check-5: docs/thresholds.md has no detection_sha256 line in the attempt record of seed {seed}, "
                          "which is scored; a scored seed of the second series is checked against its own freeze "
                          "(recheck residual 4), so the record must carry the hash of the detection rules it was scored with"])
    if frozen["rules_sha256"] == sha:
        return
    own = frozen.get("detection_sha256") or (None if scored else recorded_detection)
    if detection is not None and detection == own:
        return
    retired = f" (seed {seed} is scored and retired: generate the next unused seed)" if scored else ""
    raise CheckError([f"check-5: part5/rules.json differs from the hash frozen for seed {seed} in "
                      f"docs/thresholds.md; a seed is scored once, against the rules frozen for it{retired}"])


def profiles_hash(path=profiles.PROFILES_PATH):
    """sha256 of part5/profiles.json, printed as `profiles_sha256` for information only (ADR-0016): the gate runs the
    fitness profile, which is the rules unchanged, so this file never decides the exit code. It hashes bytes and parses
    nothing; a missing file is exit 2, like a missing set."""
    try:
        return profiles.file_sha256(path)
    except OSError as e:
        raise CheckError([f"check-5: {rel(path)} not found"]) from e


def score_params_hash(path=RULES_PATH):
    """sha256 of the `score` block of part5/rules.json, as `score.params_sha256` writes it into every score."""
    return params_sha256(json.loads(Path(path).read_text()).get("score"))


def score_version(path=RULES_PATH):
    """The `version` the `score` block of part5/rules.json names (None when it names none)."""
    block = json.loads(Path(path).read_text()).get("score")
    return block.get("version") if isinstance(block, dict) else None


def recorded_freeze(path, version):
    """The newest `freezes` entry of fixtures/score-heldout.json that names the score `version` (ADR-0018:
    `{version, freeze_commit, params_sha256, seed}`), or None when the record is missing or has none. A record holds one
    freeze per version: `require_held` refuses a second, so the newest is the only one `make check-5` ever accepts."""
    try:
        return [f for f in json.loads(Path(path).read_text())["freezes"] if f.get("version") == version][-1]
    except (OSError, ValueError, KeyError, IndexError, TypeError, AttributeError):
        return None


def attempts_of(doc, version):
    """The attempts of a parsed fixtures/score-heldout.json that belong to the score `version` (v2 or v3, ADR-0018,
    ADR-0019): the attempt says so (`version`), is for the seed that version is scored on (`SCORE_SEEDS`) or carries the hash
    a freeze of that version froze, so an attempt recorded without its `version` is caught all the same."""
    frozen = {f.get("params_sha256") for f in doc.get("freezes", []) if f.get("version") == version} - {None, ""}
    seed = SCORE_SEEDS.get(version)
    return [a for a in doc["attempts"]
            if a.get("version") == version or (seed is not None and a.get("seed") == seed) or a.get("params_sha256") in frozen]


def recorded_score_hash(path, version=None):
    """The `params_sha256` fixtures/score-heldout.json froze for the score `version` the rules ship, or None when
    the record is missing or has none. A v2 or v3 block (ADR-0018, ADR-0019) is frozen by the newest entry of the record's
    `freezes` list that names that version; a v1 block by the newest attempt that is not a later version's (ADR-0007: the
    attempts for seeds 47 and 53 carry no version; an attempt for seed 59 or 61, or with a freeze's hash, is v2's or v3's
    whether or not it names its version). With no `version`, the newest attempt, as before."""
    if version in SCORE_SEEDS:
        entry = recorded_freeze(path, version)
        return entry.get("params_sha256") if entry else None
    try:
        doc = json.loads(Path(path).read_text())
        later = [a for v in SCORE_SEEDS for a in attempts_of(doc, v)]
        attempts = doc["attempts"] if version is None else [a for a in doc["attempts"] if a.get("version", VERSION_V1) == version
                                                              and not any(a is b for b in later)]
        return attempts[-1]["params_sha256"]
    except (OSError, ValueError, KeyError, IndexError, TypeError, AttributeError):
        return None


ADR_OF = {"simon.score.v2": "ADR-0018", "simon.score.v3": "ADR-0019"}   # the ADR that fixed the targets a version is judged on


def require_held(path, version, shipped=None):
    """ADR-0018, ADR-0019: the record judges a v2 or v3 block. It is refused once the record says that version did not hold
    on its score seed (59, 61), and a record of that attempt that does not say it fails closed. Without this a reverted
    fallback would hash to the freeze again and `make check-5` would accept a score that failed its targets. v2 and v3 only:
    v1 shipped with its misses on record (ADR-0007), so a v1 block is never judged by an attempt's `holds`, and a version is
    judged by its own attempts only (`attempts_of`). Each attempt must carry `holds`, the report's `targets_v2.holds`.

    Two more refusals close a retune after the seed was scored (pre-freeze review R1). A record holds one freeze per version,
    as `make score-heldout` requires: a second one is a re-freeze, and with two the newest would let a block that was never
    scored pass. And with `shipped`, the `params_sha256` of the block in part5/rules.json, an attempt must have been scored
    with exactly that block."""
    if version not in SCORE_SEEDS:
        return
    try:
        doc = json.loads(Path(path).read_text())
        attempts = attempts_of(doc, version)
        freezes = [f for f in doc.get("freezes", []) if f.get("version") == version]
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return
    adr = ADR_OF[version]
    if len(freezes) > 1:
        raise CheckError([f"check-5: fixtures/score-heldout.json holds {len(freezes)} {version} freeze entries; a score is "
                          f"frozen once and scored once, and a re-freeze after seeing the seed is refused ({adr})"])
    for a in attempts:
        if a.get("holds") is False:
            raise CheckError([f"check-5: fixtures/score-heldout.json records that {version} did not hold every target on seed "
                              f"{a.get('seed')} (holds false); v1 stays: run make score-fallback ({adr})"])
        if a.get("holds") is not True:
            raise CheckError([f"check-5: the {version} attempt for seed {a.get('seed')} in fixtures/score-heldout.json does not "
                              "record `holds` (true or false, the report's targets_v2.holds); record it, and make "
                              f"score-fallback if it is false ({adr})"])
        if shipped is not None and a.get("params_sha256") != shipped:
            scored = str(a.get("params_sha256"))[:12]
            raise CheckError([f"check-5: the {version} attempt for seed {a.get('seed')} in fixtures/score-heldout.json was "
                              f"scored with the score params of sha256 {scored}, and the ones in part5/rules.json are "
                              f"{shipped[:12]}; a block that differs from the one scored on its seed is refused ({adr})"])


def require_score_frozen(current, recorded, version=None):
    """The score params are frozen when the held-out score report is recorded (ADR-0007), or for a v2 block when the
    orchestrator records its freeze (ADR-0018): the `score` block of part5/rules.json must still hash to what
    fixtures/score-heldout.json recorded for its version. The detection freeze above deliberately leaves that block out,
    so without this check a score edit would pass unseen."""
    named = f" for {version}" if version else ""
    if not recorded:
        raise CheckError([f"check-5: fixtures/score-heldout.json has no frozen score params (params_sha256){named}; "
                          "record the score freeze there before scoring"])
    if current != recorded:
        raise CheckError([f"check-5: the score params in part5/rules.json (sha256 {current[:12]}) differ from the "
                          f"ones frozen in fixtures/score-heldout.json (sha256 {recorded[:12]}); the score params "
                          "are frozen once the held-out score report is recorded (ADR-0007, ADR-0018)"])


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


def score_block(held, held_analyses, tune, tune_analyses, real_report, version):
    """The reported (never gated beyond `gate`) grade distribution per slice of every set: held-out, seed 5,
    kit and stock. Low light is reported, never graded against a target. `version` is the score the rules ship: it
    names the report and picks the slice targets (ADR-0007 for v1, ADR-0018 for v2)."""
    held_dist = distribution(entries_of(held, held_analyses))
    return {"gated": False, "version": version,
            "heldout": {"seed": held["seed"], "slices": held_dist, "targets": verdicts(held_dist, targets_of(version))},
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
              score_record_path=None, profiles_path=None):
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
    profiles_sha = profiles_hash(profiles_path or profiles.PROFILES_PATH)
    text = thresholds_path.read_text() if thresholds_path.is_file() else ""
    frozen = thresholds_record(held["seed"], text)
    # before any take is analysed: a scored seed under changed detection rules is refused here, not after the rescore
    require_frozen(held["seed"], sha, frozen, detection, recorded_detection_hash(text),
                   scored=any(a["seed"] == held["seed"] for a in attempts))
    version = score_version(rules_path)
    require_score_frozen(score_params_hash(rules_path), recorded_score_hash(score_record_path or SCORE_RECORD, version),
                         version)
    require_held(score_record_path or SCORE_RECORD, version, score_params_hash(rules_path))
    (held_analyses, held_errors), (tune_analyses, tune_errors) = analyse_set(held, root), analyse_set(tune, root)
    if held_errors or tune_errors:
        raise CheckError(held_errors + tune_errors)
    real_report = real_blocks(root)
    held_metrics, tune_metrics = evaluate_corpus(held, held_analyses), evaluate_corpus(tune, tune_analyses)
    require_unchanged_scores(held["seed"], held_metrics, attempts)

    g = score_gate(gate(held_metrics), held, held_analyses, run_sweep(OUT_DIR / "sweep"))
    record = next((a for a in attempts if a["seed"] == held["seed"]), None)
    recorded = {**frozen, **(record or {})}
    current = current_attempt(held["seed"], g["passed"], held_metrics, sha, recorded, record)
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
                   "score": score_block(held, held_analyses, tune, tune_analyses, real_report, version)},
        "rules_sha256": sha,
        "detection_sha256": detection,
        "profiles_sha256": profiles_sha,   # information only (ADR-0016); the gate above is the fitness profile
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
