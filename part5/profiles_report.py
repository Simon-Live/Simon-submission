"""The profile tooling on the seed 5 tuning set (docs/specs/profiles.md, ADR-0016).

    python -m part5.profiles_report [--set DIR] [--json-out PATH]     the per-profile report (make report-profiles)
    python -m part5.profiles_report --write-baseline [--out PATH]     the fitness baseline

The report analyses the seed 5 set under each profile and prints, per profile and slice, the precision, recall and
faults on correct takes (`evaluate.evaluate_corpus`, the same match rule as `make check-5`), the grade distribution, how
many faults the profile reported and how many of them `fitness` did not (must be 0: a profile only loosens), and the
seconds per take. It states what it measured and nothing else: no target, no pass or fail, no gate. The values in
part5/profiles.json are set by hand; this is how they behave on the synthetic faults, and changing one after reading it
needs an ADR-0016 amendment (the report must not become a tuning loop).

`--write-baseline` writes fixtures/profiles-fitness-baseline.json: the sha256 of the `fitness` analysis of every
seed 5 take, taken once before any profile wiring edit, so a test can show that wiring a profile in moved nothing
for `fitness` (AC-PROF-02). The hash covers the analysis without `profile`, `schema_version` and (TICKET-043)
`diagnostics.near_misses`, the only things the features add to a `fitness` document, and with paths made relative to
the repository so it is the same in every checkout; it is also the proof that the near misses changed no fault, score
or other field (docs/specs/near-misses.md AC-NM-01).

The seed 5 set only: any other set, a held-out one above all, is refused (exit 2) before anything is analysed.
`make check-5` never calls this module.
"""
import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

from . import profiles
from .evaluate import evaluate_corpus
from .score_report import analyse, distribution, entries_of, feet_kwargs, load_labels, report_lines

ROOT = Path(__file__).resolve().parent.parent
TUNING = ROOT / "fixtures" / "input" / "followers"
BASELINE = ROOT / "fixtures" / "profiles-fitness-baseline.json"
BASELINE_FORMAT = "simon.profiles.baseline.v1"
REPORT_FORMAT = "simon.part5.profiles.report.v1"
TUNING_SEED = 5
# What a profile adds to a document; the fitness baseline is taken without them.
ADDED_BY_PROFILES = ("profile", "schema_version")


class ReportError(Exception):
    """The set cannot be used for the profile tooling (missing, unreadable, or not the seed 5 tuning set)."""


def tuning_labels(directory=None):
    """The seed 5 labels, or a `ReportError`: the profile tooling runs on the tuning set only, never on a
    held-out seed (ADR-0003, ADR-0016)."""
    directory = Path(directory or TUNING)
    try:
        doc = load_labels(directory)
    except (OSError, ValueError) as e:
        raise ReportError(f"{directory} has no labels.json ({e})") from e
    if not isinstance(doc.get("takes"), list) or doc.get("seed") != TUNING_SEED:
        raise ReportError(f"the profile report runs on the tuning set only (seed {TUNING_SEED}), not seed {doc.get('seed')}")
    return doc


def analyse_take(take, root=ROOT, profile=None):
    """One labelled take analysed as `part5 analyse` would (score and insights included). `profile` is left out of
    the call when it is None, so the fitness path is the one the gate runs."""
    expected = {"path": str(Path(root) / take["expected"])}
    follower = {"path": str(Path(root) / take["follower"]), "take_id": take["take_id"]}
    extra = {} if profile is None else {"profile": profile}
    return analyse(expected, follower, **feet_kwargs(take, Path(root)), **extra)


# --- the fitness baseline ---
def analysis_digest(analysis, root=ROOT):
    """sha256 of the analysis without `profile`, `schema_version`, `diagnostics.near_misses` and the 1.9.0 additions
    (`second_opinion`, `phrasing.lang`, `phrasing.lang_requested`, `phrasing.faults[].text` and `.lang`; TICKET-045,
    TICKET-046; `score.uncapped`, Part 7 TICKET-155), as canonical JSON with the checkout's path taken off every file
    path, so the value does not depend on where the repository lives."""
    doc = {k: v for k, v in analysis.items() if k not in ADDED_BY_PROFILES and k != "second_opinion"}
    if isinstance(doc.get("score"), dict):
        doc["score"] = {k: v for k, v in doc["score"].items() if k != "uncapped"}
    if "diagnostics" in doc:
        doc["diagnostics"] = {k: v for k, v in doc["diagnostics"].items() if k != "near_misses"}
    if isinstance(doc.get("phrasing"), dict):
        record = {k: v for k, v in doc["phrasing"].items() if k not in ("lang", "lang_requested")}
        record["faults"] = [{k: v for k, v in e.items() if k not in ("text", "lang")} for e in record.get("faults", [])]
        doc["phrasing"] = record
    text = json.dumps(doc, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(text.replace(f"{Path(root)}/", "").encode()).hexdigest()


def fitness_digests(labels_doc, root=ROOT, profile=None):
    """{take_id: digest} of every take of the set analysed with no profile named (or `profile`)."""
    return {t["take_id"]: analysis_digest(analyse_take(t, root, profile), root) for t in labels_doc["takes"]}


def baseline_document(labels_doc, root=ROOT):
    return {"format": BASELINE_FORMAT,
            "_comment": ("Written by `python -m part5.profiles_report --write-baseline` before any profile wiring "
                         "edit (docs/specs/profiles.md, AC-PROF-02) and taken again at attempt 4 (TICKET-044, "
                         "ADR-0017), which moves the dance takes (rep by rep) and the similarity of some exercise "
                         "takes (the trunk's new side lean), and once more at its pre-freeze review, which reports a "
                         "fault on both sides once and moves 4 dance takes, and once more at its recheck, which splits "
                         "the persistence floor by measure class (the body floor 8, the foot floor 32), re-sweeps "
                         "two thresholds under it and keeps a rep's two-sided fault in its window when the take "
                         "reports either side, and once more at attempt 5 (TICKET-040, ADR-0015 Amendment 4), "
                         "whose steadiness gate leaves out a foot measure that jitters and so moves the "
                         "`diagnostics.feet` and the faults of the takes with such a foot. Do not regenerate it "
                         "otherwise: a test "
                         "compares the fitness analysis of every seed 5 take with these hashes."),
            "seed": labels_doc["seed"],
            "hashed": "sha256 of the analysis with the checkout path removed, as sorted compact JSON, "
                      "without `profile` and `schema_version`",
            "takes": fitness_digests(labels_doc, root)}


def write_baseline(path=BASELINE, directory=None):
    doc = baseline_document(tuning_labels(directory))
    Path(path).write_text(json.dumps(doc, indent=1) + "\n")
    return doc


# --- covered faults (the loosen-only invariant, docs/specs/profiles.md) ---
def _key(fault):
    return fault["measure"], fault["side"], fault["direction"]


def covered(fault, fitness_faults):
    """Is a profile `fault` (an analysis `faults` entry) covered by the `fitness` faults of the same take? The
    definition is `profiles.covered_by`, the one repetition mode also applies to a take's faults."""
    return profiles.covered_by(_key(fault), [_key(f) for f in fitness_faults])


def uncovered(faults, fitness_faults):
    """The faults of a profile's analysis that `fitness` does not report; always empty if the profile only loosens."""
    return [f for f in faults if not covered(f, fitness_faults)]


# --- the report ---
def run_profile(labels_doc, name, root=ROOT):
    """`({take_id: analysis}, [seconds per take])` of the set analysed under the profile `name`."""
    analyses, seconds = {}, []
    for take in labels_doc["takes"]:
        started = time.perf_counter()
        analyses[take["take_id"]] = analyse_take(take, root, name)
        seconds.append(time.perf_counter() - started)
    return analyses, seconds


def profile_entry(labels_doc, analyses, seconds, fitness_analyses):
    """What the report says about one profile: metrics per slice, the grade distribution, fault counts, timing."""
    metrics = evaluate_corpus(labels_doc, analyses)
    faults = sum(len(a["faults"]) for a in analyses.values())
    missing = sum(len(uncovered(a["faults"], fitness_analyses[take_id]["faults"])) for take_id, a in analyses.items())
    return {"metrics": metrics, "grades": distribution(entries_of(labels_doc, analyses)),
            "faults": faults, "not_in_fitness": missing,
            "seconds_per_take": {"mean": round(sum(seconds) / len(seconds), 4), "max": round(max(seconds), 4)}}


def build_report(labels_doc, root=ROOT, names=None):
    """The per-profile numbers for the seed 5 set. `fitness` is always run (the others are compared with it)."""
    names = names or profiles.names()
    runs = {name: run_profile(labels_doc, name, root) for name in dict.fromkeys([*names, profiles.IDENTITY])}
    fitness = runs[profiles.IDENTITY][0]
    return {"format": REPORT_FORMAT, "seed": labels_doc["seed"], "takes": len(labels_doc["takes"]),
            "note": "values set by hand and not tuned on any seed; reported as measured, no target, never gated",
            "profiles": {name: profile_entry(labels_doc, *runs[name], fitness) for name in names}}


def _slice_line(key, s):
    return (f"  {key:12s} takes {s['takes']:3d}  precision {s['precision']:.2f}  recall {s['recall']:.2f}  "
            f"tp {s['tp']:3d} fp {s['fp']:3d} fn {s['fn']:3d}  faults on correct takes {s['faults_on_correct_takes']}")


def report_text(report):
    lines = [f"profiles_report: seed {report['seed']}, {report['takes']} takes, {report['note']}"]
    for name, entry in report["profiles"].items():
        metrics = entry["metrics"]
        lines += ["", f"profile {name}"]
        lines += [_slice_line(key, s) for key, s in metrics["slices"].items()]
        lines += [_slice_line("good light", metrics["good_light"]), _slice_line("overall", metrics["overall"])]
        lines += ["  grades"] + [f"  {line}" for line in report_lines(entry["grades"], {})]
        lines.append(f"  faults reported {entry['faults']}, not reported by fitness {entry['not_in_fitness']}")
        lines.append(f"  seconds per take: mean {entry['seconds_per_take']['mean']}, max {entry['seconds_per_take']['max']}")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m part5.profiles_report", description=__doc__.splitlines()[0])
    ap.add_argument("--set", default=None, help="the seed 5 set (default fixtures/input/followers); any other seed is refused")
    ap.add_argument("--json-out", default=None, help="also write the report as JSON here")
    ap.add_argument("--write-baseline", action="store_true", help="write the fitness baseline and stop")
    ap.add_argument("--out", default=None, help="where --write-baseline writes (default the committed baseline)")
    args = ap.parse_args(argv)
    try:
        if args.write_baseline:
            doc = write_baseline(args.out or BASELINE, args.set)
            print(f"profiles_report: wrote {len(doc['takes'])} take hashes to {args.out or BASELINE}")
            return 0
        report = build_report(tuning_labels(args.set))
    except ReportError as e:
        print(f"profiles_report: {e}", file=sys.stderr)
        return 2
    print(report_text(report))
    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_out).write_text(json.dumps(report, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
