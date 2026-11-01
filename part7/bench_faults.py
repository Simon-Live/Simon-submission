"""Fault agreement benchmark: pipeline analysis.json per take against human fault labels (TICKET-150).

Spec: docs/specs/bench-faults.md. Stdlib only.

    python -m part7.bench_faults --make-split            # once, before anything is scored
    python -m part7.bench_faults                         # held-out report (default)
    python -m part7.bench_faults --set dev|all

Labels: one JSON file per take in --labels (default bench/labels), shape in bench/labels.schema.json.
Analyses: --analyses (default bench/analyses) holds `<clip_sha256>.json` or `<clip_sha256>/analysis.json`,
the file Part 5 writes for that take. A predicted fault matches a labelled fault when type and side are
equal and the follower times differ by at most MATCH_WINDOW_S; each fault matches at most once.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import statistics
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / "bench"
SCHEMA = "simon.bench.labels/1"
MATCH_WINDOW_S = 0.5
HOLDOUT_FRACTION = 0.5
SPLIT_SEED = "simon-part-7-bench-faults-1"
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
SIDES = ("left", "right", "both", "center")


class BenchError(ValueError):
    """A label, split or analysis file that cannot be scored. The message names the file."""


def validate_label(doc: dict, source: str = "label") -> dict:
    """Return `doc` when it is a well formed label file, else raise BenchError naming `source`."""
    def need(cond: bool, msg: str) -> None:
        if not cond:
            raise BenchError(f"{source}: {msg}")

    need(isinstance(doc, dict), "not a JSON object")
    need(doc.get("schema") == SCHEMA, f"schema must be {SCHEMA!r}")
    need(isinstance(doc.get("clip_sha256"), str) and SHA_RE.match(doc["clip_sha256"]),
         "clip_sha256 must be 64 lowercase hex characters")
    for key in ("movement", "labeller"):
        need(isinstance(doc.get(key), str) and doc[key].strip(), f"{key} must be a non-empty string")
    try:
        date.fromisoformat(str(doc.get("labelled_on")))
    except ValueError:
        need(False, "labelled_on must be an ISO date (YYYY-MM-DD)")
    need(isinstance(doc.get("faults"), list), "faults must be a list (empty when the take is clean)")
    for i, f in enumerate(doc["faults"]):
        need(isinstance(f, dict), f"faults[{i}] must be an object")
        need(isinstance(f.get("type"), str) and f["type"], f"faults[{i}].type must be a non-empty string")
        need(f.get("side") in SIDES, f"faults[{i}].side must be one of {', '.join(SIDES)}")
        at = f.get("at_s")
        need(isinstance(at, (int, float)) and not isinstance(at, bool) and at >= 0 and math.isfinite(at),
             f"faults[{i}].at_s must be a number of seconds >= 0")
    need("synthetic" not in doc or isinstance(doc["synthetic"], bool), "synthetic must be a boolean")
    return doc


def load_labels(labels_dir: Path, allow_synthetic: bool = False) -> dict[str, dict]:
    """All label files in the directory keyed by clip sha. Duplicates and synthetic labels are errors
    unless `allow_synthetic` (tests only)."""
    labels: dict[str, dict] = {}
    for path in sorted(Path(labels_dir).glob("*.json")):
        try:
            doc = json.loads(path.read_text())
        except json.JSONDecodeError as e:
            raise BenchError(f"{path.name}: not valid JSON ({e.msg})") from None
        validate_label(doc, path.name)
        if doc.get("synthetic") and not allow_synthetic:
            raise BenchError(f"{path.name}: synthetic labels cannot be scored as a real benchmark")
        if doc["clip_sha256"] in labels:
            raise BenchError(f"{path.name}: duplicate label for clip {doc['clip_sha256'][:12]}")
        labels[doc["clip_sha256"]] = doc
    return labels


def make_split(shas, seed: str = SPLIT_SEED, fraction: float = HOLDOUT_FRACTION) -> dict:
    """Deterministic split: shas ordered by sha256(seed + sha), the first ceil(fraction * n) held out."""
    shas = sorted(set(shas))
    if len(shas) < 2:
        raise BenchError("a split needs at least 2 labelled takes")
    ordered = sorted(shas, key=lambda s: hashlib.sha256((seed + s).encode()).hexdigest())
    n_hold = min(len(shas) - 1, max(1, math.ceil(fraction * len(shas))))
    return {"schema": "simon.bench.split/1", "seed": seed, "created_on": date.today().isoformat(),
            "holdout": sorted(ordered[:n_hold]), "dev": sorted(ordered[n_hold:])}


def write_split_once(path: Path, labels: dict[str, dict]) -> dict:
    """Write the split file; refuse to overwrite so the held-out set cannot drift after scores are seen."""
    path = Path(path)
    if path.exists():
        raise BenchError(f"{path.name} already exists; the held-out split is recorded once")
    split = make_split(labels)
    path.write_text(json.dumps(split, indent=2) + "\n")
    return split


def load_analysis(analyses_dir: Path, sha: str) -> dict:
    for cand in (Path(analyses_dir) / f"{sha}.json", Path(analyses_dir) / sha / "analysis.json"):
        if cand.exists():
            try:
                doc = json.loads(cand.read_text())
            except json.JSONDecodeError as e:
                raise BenchError(f"{cand.name}: not valid JSON ({e.msg})") from None
            if not isinstance(doc.get("faults"), list):
                raise BenchError(f"{cand.name}: no faults list; not an analysis.json")
            return doc
    raise BenchError(f"no analysis for clip {sha[:12]} in {analyses_dir}")


def predicted_faults(analysis: dict) -> list[dict]:
    out = []
    for f in analysis["faults"]:
        at = f.get("at_s")
        if at is None and f.get("follower_t_s"):
            at = f["follower_t_s"][0]
        if at is None:
            raise BenchError(f"fault {f.get('measure')!r} has no at_s")
        out.append({"type": f["measure"], "side": f["side"], "at_s": float(at)})
    return out


def match(labelled: list[dict], predicted: list[dict], window: float = MATCH_WINDOW_S) -> dict:
    """Greedy one to one matching, closest pairs first, same type and side, within `window` seconds."""
    pairs = sorted(
        ((abs(p["at_s"] - lab["at_s"]), i, j) for i, lab in enumerate(labelled)
         for j, p in enumerate(predicted)
         if lab["type"] == p["type"] and lab["side"] == p["side"] and abs(p["at_s"] - lab["at_s"]) <= window),
    )
    used_l: set[int] = set()
    used_p: set[int] = set()
    errors = []
    for err, i, j in pairs:
        if i in used_l or j in used_p:
            continue
        used_l.add(i)
        used_p.add(j)
        errors.append(err)
    return {"tp": len(errors), "fp": len(predicted) - len(used_p), "fn": len(labelled) - len(used_l),
            "timing_errors_s": errors}


def score(takes: list[dict], window: float = MATCH_WINDOW_S) -> dict:
    """Aggregate over takes: each take is {"labelled": [...], "predicted": [...]}."""
    tp = fp = fn = 0
    errors: list[float] = []
    for t in takes:
        m = match(t["labelled"], t["predicted"], window)
        tp, fp, fn = tp + m["tp"], fp + m["fp"], fn + m["fn"]
        errors += m["timing_errors_s"]
    return {"takes": len(takes), "match_window_s": window, "tp": tp, "fp": fp, "fn": fn,
            "precision": tp / (tp + fp) if tp + fp else None,
            "recall": tp / (tp + fn) if tp + fn else None,
            "timing_error_mean_s": statistics.fmean(errors) if errors else None,
            "timing_error_median_s": statistics.median(errors) if errors else None}


def run(labels_dir: Path, analyses_dir: Path, split_path: Path, which: str = "holdout",
        allow_synthetic: bool = False, window: float = MATCH_WINDOW_S) -> dict:
    labels = load_labels(labels_dir, allow_synthetic)
    if not labels:
        raise BenchError(f"no label files in {labels_dir}; the benchmark needs labelled takes")
    if which == "all":
        shas = sorted(labels)
    else:
        if not Path(split_path).exists():
            raise BenchError(f"{Path(split_path).name} is missing; run --make-split once first")
        split = json.loads(Path(split_path).read_text())
        if set(split["holdout"]) | set(split["dev"]) != set(labels):
            raise BenchError("the labels changed since the split was recorded; the split is not rewritten")
        shas = split[which]
    takes = [{"labelled": labels[s]["faults"], "predicted": predicted_faults(load_analysis(analyses_dir, s))}
             for s in shas]
    out = score(takes, window)
    out.update({"set": which, "movements": sorted({labels[s]["movement"] for s in shas}),
                "synthetic": any(labels[s].get("synthetic") for s in shas)})
    return out


def format_report(r: dict) -> str:
    def pct(v):
        return "n/a" if v is None else f"{v * 100:.0f}%"

    def sec(v):
        return "n/a" if v is None else f"{v:.2f} s"

    tag = " (SYNTHETIC LABELS, not a result)" if r["synthetic"] else ""
    return (f"{r['set']} set{tag}: {r['takes']} takes, matching window {r['match_window_s']} s\n"
            f"precision {pct(r['precision'])} (tp {r['tp']}, fp {r['fp']}), recall {pct(r['recall'])} "
            f"(fn {r['fn']})\n"
            f"timing error mean {sec(r['timing_error_mean_s'])}, median {sec(r['timing_error_median_s'])}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--labels", type=Path, default=BENCH / "labels")
    ap.add_argument("--analyses", type=Path, default=BENCH / "analyses")
    ap.add_argument("--split", type=Path, default=BENCH / "split.json")
    ap.add_argument("--set", dest="which", choices=("holdout", "dev", "all"), default="holdout")
    ap.add_argument("--window", type=float, default=MATCH_WINDOW_S)
    ap.add_argument("--make-split", action="store_true", help="record the held-out split once, then exit")
    ap.add_argument("--json", action="store_true", help="print the report as JSON")
    args = ap.parse_args(argv)
    try:
        if args.make_split:
            split = write_split_once(args.split, load_labels(args.labels))
            print(f"split recorded: {len(split['holdout'])} held out, {len(split['dev'])} dev ({args.split})")
            return 0
        report = run(args.labels, args.analyses, args.split, args.which, window=args.window)
    except BenchError as e:
        print(f"bench-faults: {e}", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2) if args.json else format_report(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
