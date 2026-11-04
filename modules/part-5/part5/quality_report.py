"""The quality block on the takes we have, per slice (docs/specs/quality.md AC-Q12, ADR-0021).

    python -m part5.quality_report [--heldout DIR] [--part7 DIR] [--part7-example PATH] [--json-out PATH]   (make report-quality)

It analyses every take as `part5 analyse` would and counts the levels `ok`, `degraded` and `major` per light, condition (clean or
the dropout copy) and angle, for seed 5 (the tuning set: the committed takes, and the dropout copies regenerated into a temporary
directory, never committed) and for the held-out set on disk (seed 73), and reads the committed real lateral raise and Part 7's
dark take and its clean twin as slices of their own. It states what it measured and nothing else: no target, no pass or fail, no
gate. The limits in part5/quality.json were fitted on seed 5 only; the held-out set, the real takes and Part 7's takes are read to
report, and a miss there is a finding, not a retune.

The earlier held-out seeds, retired (29, 31, 37, 67, 71), are refused (exit 2) before anything is read: a retired seed is never
read again. Seed 73, the live gate seed that `make check-5` scores on every run, is the held-out set this report reads.
`make check-5` never calls this module and does not read `quality`.
"""
import argparse
import importlib.util
import json
import statistics
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

from . import quality
from .io import InputError, load_clip
from .output import QUALITY_LEVELS
from .pipeline import analyse
from .profiles import file_sha256
from .profiles_report import ReportError, tuning_labels
from .score_report import load_labels, resolve

ROOT = Path(__file__).resolve().parent.parent
HELDOUT = ROOT / "fixtures" / "input" / "heldout"
PART7 = ROOT / "fixtures" / "input" / "real" / "part7-check-20261102T021153Z"
REAL_RAISE = ROOT / "fixtures" / "input" / "real" / "lateral-raise"
GENERATOR = ROOT / "scripts" / "make_dummy_followers.py"
REPORT_FORMAT = "simon.part5.quality.report.v1"
USED_HELDOUT = (29, 31, 37, 67, 71)   # the retired held-out seeds; 73 is the live gate seed (docs/thresholds.md)
PART7_TAKES = ("dark", "clean")


def relative(path):
    """`path` relative to the repository as given, unresolved (`check.rel` resolves it first, which turns a symlinked temporary
    path such as macOS's /var into /private/var, so it is not used here)."""
    path = Path(path)
    return str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)


# ---------------------------------------------------------------------------------------------- the takes
def take_block(take, base=ROOT):
    """The `quality` block of one labelled take, from the whole pipeline (so the visibility warnings count)."""
    expected, follower = resolve(take["expected"], base), resolve(take["follower"], base)
    return analyse(str(expected), {"path": str(follower), "take_id": take["take_id"]})["quality"]


def heldout_labels(directory):
    """The held-out labels on disk, or a `ReportError` when its seed was used by `make check-5`; None without a set."""
    if not (Path(directory) / "labels.json").is_file():
        return None
    doc = load_labels(directory)
    if doc.get("seed") in USED_HELDOUT or not isinstance(doc.get("seed"), int):
        raise ReportError(f"{directory} holds seed {doc.get('seed')!r}, which make check-5 has used; a used held-out seed is "
                          f"never read again")
    return doc


def dropout_copies(seed, directory):
    """The dropout copies of the tuning seed, regenerated into `directory` (a temporary one) with the same generator
    `make dummy-data` runs: [label]. Empty when the generator is not in this checkout."""
    if not GENERATOR.is_file():
        return []
    spec = importlib.util.spec_from_file_location("make_dummy_followers", GENERATOR)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # feet=True, as `make dummy-data` runs it, so the takes are the committed seed 5 takes and their copies; the expected feet
    # files go into the temporary directory too, never into fixtures/input/expected-feet
    labels = module.generate(seed, Path(directory) / "followers", dropout_variant=True, feet=True,
                             expected_feet_dir=Path(directory) / "expected-feet")
    return [t for t in labels["takes"] if t["variant"] == "dropout"]


# ---------------------------------------------------------------------------------------------- the counts
def _reading_range(blocks, name):
    """`{min, median, max}` of one signal over `blocks`, None when no block has a reading of it."""
    values = [b["signals"].get(name) for b in blocks if b["signals"].get(name) is not None]
    return {"min": min(values), "median": round(statistics.median(values), 1), "max": max(values)} if values else None


def slice_entry(blocks):
    """Counts of each level, how often each reason fired, and the ranges of the jitter and the heading offset (TICKET-086)."""
    levels = Counter(b["level"] for b in blocks)
    reasons = Counter(r["code"] for b in blocks for r in b["reasons"])
    return {"takes": len(blocks), **{level: levels.get(level, 0) for level in QUALITY_LEVELS}, "reasons": dict(sorted(reasons.items())),
            "position_jitter_mm": _reading_range(blocks, "position_jitter_mm"),
            "heading_offset_deg": _reading_range(blocks, "heading_offset_deg")}


def sliced(rows):
    """`{"light/condition/angle": entry}` and `{"light/condition": entry}` from [(label, block)]."""
    by_slice, by_condition = defaultdict(list), defaultdict(list)
    for label, block in rows:
        condition = f"{label['lighting']}/{label['variant']}"
        by_slice[f"{condition}/{label['angle']}"].append(block)
        by_condition[condition].append(block)
    return ({k: slice_entry(v) for k, v in sorted(by_slice.items())}, {k: slice_entry(v) for k, v in sorted(by_condition.items())})


def set_entry(role, labels_doc, rows):
    slices, conditions = sliced(rows)
    good_not_ok = [{"take_id": label["take_id"], "level": block["level"], "reasons": [r["code"] for r in block["reasons"]],
                    "signals": block["signals"]}
                   for label, block in rows if label["lighting"] == "good" and label["variant"] == "clean" and block["level"] != "ok"]
    return {"seed": labels_doc["seed"], "role": role, "takes": len(rows), "conditions": conditions, "slices": slices,
            "clean_good_light_not_ok": good_not_ok}


# ---------------------------------------------------------------------------------------------- the real takes
def real_entry(directory=REAL_RAISE):
    """The committed real lateral raise: each follower through the whole pipeline against its trainer, and whether the trainer says
    what it sees (a Part 4 animation without `conf` has unknown visibility, so every joint of the follower counts)."""
    manifest = Path(directory) / "manifest.json"
    if not manifest.is_file():
        return None
    doc = json.loads(manifest.read_text())
    expected = resolve(doc["expected"], ROOT)
    out = {"expected": relative(expected), "expected_has_conf": load_clip(expected).conf is not None, "takes": {}}
    for take in doc["takes"]:
        result = analyse(str(expected), {"path": str(resolve(take["follower"], ROOT)), "take_id": take["take_id"]})
        out["takes"][take["take_id"]] = {"quality": result["quality"], "warnings": [w["code"] for w in result.get("warnings", [])]}
    return out


# ---------------------------------------------------------------------------------------------- Part 7's takes
def part7_entry(directory, example=None):
    """Part 7's dark take and its clean twin: the block of the follower file alone (no example needed), and the block of the
    whole pipeline against `example` when it is given. Read once, after the limits were frozen; never tuned on."""
    out = {"directory": relative(directory), "example": None if example is None else str(example), "takes": {}}
    for name in PART7_TAKES:
        path = Path(directory) / name / "follower.json"
        if not path.is_file():
            continue
        entry = {"follower": relative(path), "sha256": file_sha256(path), "alone": quality.of_clip(load_clip(path))}
        if example is not None:
            analysis = analyse(str(example), {"path": str(path), "take_id": f"part7-{name}"})
            entry["with_example"] = {"quality": analysis["quality"], "warnings": [w["code"] for w in analysis.get("warnings", [])]}
        out["takes"][name] = entry
    return out


# ---------------------------------------------------------------------------------------------- the report
def build_report(tuning_dir=None, heldout_dir=HELDOUT, part7_dir=PART7, part7_example=None, real_dir=REAL_RAISE, root=ROOT):
    tuning = tuning_labels(tuning_dir)
    held = heldout_labels(heldout_dir)   # refused before anything is analysed when its seed was used
    rows = [(t, take_block(t, root)) for t in tuning["takes"]]
    with tempfile.TemporaryDirectory() as tmp:
        copies = dropout_copies(tuning["seed"], tmp)
        rows += [(t, take_block(t, root)) for t in copies]
    role = "tuning (the limits were fitted here)" + ("; the dropout copies are regenerated, not committed" if copies else "")
    sets = {f"seed {tuning['seed']}": set_entry(role, tuning, rows)}
    if held is not None:
        sets[f"seed {held['seed']}"] = set_entry("held-out, read to report and never tuned on", held,
                                                 [(t, take_block(t, root)) for t in held["takes"]])
    return {"format": REPORT_FORMAT, "thresholds_sha256": file_sha256(quality.THRESHOLDS_PATH),
            "limits": json.loads(quality.THRESHOLDS_PATH.read_text())["signals"],
            "note": "reported as measured; no target, never gated; the limits were fitted on seed 5 only", "sets": sets,
            "real_lateral_raise": real_entry(real_dir) if real_dir is not None else None,
            "part7": part7_entry(part7_dir, part7_example) if Path(part7_dir).is_dir() else None}


def _line(name, e):
    reasons = ", ".join(f"{code} {n}" for code, n in e["reasons"].items()) or "none"
    jitter = e["position_jitter_mm"]
    shake = f"jitter {jitter['min']}..{jitter['max']} (median {jitter['median']})" if jitter else "jitter not measured"
    heading = e.get("heading_offset_deg")
    turn = f"heading {heading['min']}..{heading['max']} (median {heading['median']})" if heading else "heading not measured"
    return (f"  {name:<22} takes {e['takes']:3d}  ok {e['ok']:3d}  degraded {e['degraded']:3d}  major {e['major']:3d}  "
            f"{shake}; {turn}; reasons: {reasons}")


def _block_lines(label, block):
    s = block["signals"]
    return [f"    {label}: {block['level']}, score_cap {block['score_cap']}, "
            + ", ".join(f"{k} {v}" for k, v in s.items())] + [f"      {r['code']}: {r['words']}" for r in block["reasons"]]


def report_text(report):
    lines = [f"quality_report: {report['note']}", f"  limits ({report['thresholds_sha256'][:12]}): "
             + "; ".join(f"{k} {v['degraded']}/{v['major']}" for k, v in report["limits"].items())]
    for name, s in report["sets"].items():
        lines += ["", f"{name}: {s['role']}, {s['takes']} takes", "  by light and condition"]
        lines += [_line(k, v) for k, v in s["conditions"].items()] + ["  by slice"] + [_line(k, v) for k, v in s["slices"].items()]
        lines.append(f"  clean good-light takes above ok: {len(s['clean_good_light_not_ok'])}")
        lines += [f"    {t['take_id']}: {t['level']} {t['reasons']} {t['signals']}" for t in s["clean_good_light_not_ok"]]
    real = report["real_lateral_raise"]
    if real:
        known = "carries conf" if real["expected_has_conf"] else "carries no conf, so its visibility is unknown and every joint counts"
        lines += ["", f"The committed real lateral raise ({real['expected']} {known}), read to report, never tuned on"]
        for name, t in real["takes"].items():
            lines += [f"  {name}"] + _block_lines("the pipeline", t["quality"]) + [f"    warnings: {t['warnings'] or 'none'}"]
    p7 = report["part7"]
    if p7:
        lines += ["", f"Part 7's takes ({p7['directory']}), read once, never tuned on"]
        for name, t in p7["takes"].items():
            lines += [f"  {name} ({t['sha256'][:12]})"] + _block_lines("the file alone", t["alone"])
            if "with_example" in t:
                lines += _block_lines("against the example", t["with_example"]["quality"])
                lines.append(f"    warnings: {t['with_example']['warnings'] or 'none'}")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m part5.quality_report", description=__doc__.splitlines()[0])
    ap.add_argument("--set", default=None, help="the seed 5 set (default fixtures/input/followers); any other seed is refused")
    ap.add_argument("--heldout", default=str(HELDOUT), help="the held-out set on disk (default fixtures/input/heldout)")
    ap.add_argument("--part7", default=str(PART7), help="Part 7's two takes (default fixtures/input/real/part7-check-...)")
    ap.add_argument("--part7-example", default=None, help="the example Part 7 compared them with, for the pipeline's block")
    ap.add_argument("--json-out", default=None, help="also write the report as JSON here")
    args = ap.parse_args(argv)
    try:
        report = build_report(args.set, args.heldout, args.part7, args.part7_example)
    except (ReportError, InputError, quality.QualityError) as e:
        print(f"quality_report: {e}", file=sys.stderr)
        return 2
    print(report_text(report))
    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_out).write_text(json.dumps(report, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
