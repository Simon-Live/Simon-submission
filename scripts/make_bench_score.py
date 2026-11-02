"""`make bench-score`: how Part 5's score behaves when a joint is wrong and when a take is changed in a way that should not
matter (docs/specs/scoring-validity.md, TICKET-082).

    uv run python scripts/make_bench_score.py [--out out/bench-score] [--chart-copy docs/evaluation/dose-response.svg]

Runs, on the seed 5 takes only and through Part 5's own pipeline (no GPU, no other part):
- the dose-response: 0 to 30 degrees in steps of 2.5 planted on the knee, hip, elbow and trunk of the 6 correct good-light
  exercise takes (312 rows): the score, the grade and whether, and at what angle, the matching fault first fires;
- the skeleton-level invariance table: frame rate, mirror, trim, translation, yaw and scale on the 54 good-light takes
  of the exercise and dance sets, correct and faulted.
Writes `metrics.json` (`simon.part5.bench-score.v1`: sha, command, exit code and every row) and `dose-response.svg` under
`--out`, and a copy of the chart at `--chart-copy` (the committed one) with the two summaries beside it,
`first_fire.summary.json` and `invariance.summary.json`: the figures of the tables and the prose of docs/evaluation.md,
which tests/test_evaluation_doc.py holds the doc to (AC-SV09, TICKET-088 N2). They carry the score they were made with and no commit sha, so a
run on a later commit rewrites them byte for byte unless a figure moved. Failures are reported as found: a claim a
transform misses is a finding in `metrics.json` and on stdout, never a failed run.

Exit 0 when every row ran, 1 when a row could not run (recorded with its error), 2 for a usage error or an input that
is not the seed 5 set.
"""
import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import make_bench_score_chart as chart  # noqa: E402
import make_score_validity as sv  # noqa: E402
from part5 import score  # noqa: E402
from part5.detect import load_rules  # noqa: E402

ROOT = sv.ROOT
FORMAT = "simon.part5.bench-score.v1"
COMMAND = "uv run python scripts/make_bench_score.py"
OUT = ROOT / "out" / "bench-score"
CHART_COPY = ROOT / "docs" / "evaluation" / "dose-response.svg"
SCORE_AT = (0, 10, 20, 30)   # the steps the tables and the stdout summary read the score at
SUMMARY_FORMAT = "simon.part5.bench-score.summary.v1"
FIRST_FIRE_SUMMARY = "first_fire.summary.json"   # beside the chart copy: the dose-response tables of docs/evaluation.md
INVARIANCE_SUMMARY = "invariance.summary.json"   # beside the chart copy: its invariance table


def git(*args):
    r = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def check_inputs(takes):
    """The first problem with the pool, as the message `main` prints with exit 2, or None."""
    labels = json.loads(sv.retimed.LABELS.read_text())
    if labels.get("seed") != sv.SEED:
        return f"bench-score: seed {labels.get('seed')} is not the tuning set ({sv.SEED})"
    for take in takes:
        for key in ("expected", "follower"):
            if not (ROOT / take[key]).is_file():
                return f"bench-score: missing take {take[key]}"
    return None


def dose_findings(rows, summary):
    """Sentences for what the dose-response shows that a reader should not have to find: a score that rises with the error,
    a matching fault that never fires or stops firing, and a second fault that appears."""
    out = []
    for (joint, take_id), steps in _series(rows).items():
        for d0, v0, d1, v1 in sv.rises([(r["planted_deg"], r["value"]) for r in steps]):
            out.append(f"dose-response {joint} {take_id}: the score rises from {v0} at {d0} degrees to {v1} at {d1} degrees")
    for joint, s in summary.items():
        if s["never"]:
            out.append(f"dose-response {joint}: the matching fault never fires in {s['never']} of {s['takes']} takes up to "
                       f"{sv.GRID[-1]:g} degrees")
        if s["stable"] < s["takes"] - s["never"]:
            out.append(f"dose-response {joint}: the matching fault stops firing at a larger step in "
                       f"{s['takes'] - s['never'] - s['stable']} of {s['takes']} takes")
    for e in second_faults(rows):
        out.append(f"dose-response {e['joint']}: a second fault, {e['measure']} {e['side']} {e['direction']}, appears in "
                   f"{e['takes']} takes, from {e['from_deg']:g} degrees")
    return out


def second_faults(rows):
    """`[{joint, measure, side, direction, takes, from_deg}]`: each fault other than the matching one that a planted joint
    brings, in how many takes, and the smallest angle it appears at in any of them."""
    extra = {}
    for r in sv.measured(rows):
        for measure, side, direction, _ in r["extra_faults"]:
            seen = extra.setdefault((r["joint"], measure, side, direction), {})
            seen[r["take_id"]] = min(r["planted_deg"], seen.get(r["take_id"], r["planted_deg"]))
    return [{"joint": joint, "measure": measure, "side": side, "direction": direction, "takes": len(seen),
             "from_deg": min(seen.values())} for (joint, measure, side, direction), seen in extra.items()]


def _series(rows):
    """`{(joint, take_id): [row]}` of the measured dose rows, each series in growing angle."""
    out = {}
    for r in sv.measured(rows):
        out.setdefault((r["joint"], r["take_id"]), []).append(r)
    return {key: sorted(series, key=lambda r: r["planted_deg"]) for key, series in out.items()}


def dose_figures(rows):
    """The figures the prose of section 1 of docs/evaluation.md states (TICKET-088 N2): the rows, the series that never rise,
    the rows without the matching fault (their values and other faults) and with it (their range and grades), the drop on
    the step a take first fires, the cost of each later step (apart: the steps where a second fault appears), the second
    faults, and per joint the largest gap between the realised change of its measure and the planted degrees."""
    ok = sv.measured(rows)
    without, fired = [r for r in ok if not r["matching"]], [r for r in ok if r["matching"]]
    series = _series(rows)
    drops, costs, costs_second = [], [], []
    for steps in series.values():
        for a, b in zip(steps, steps[1:]):
            if b["matching"] and not a["matching"]:
                drops.append(a["value"] - b["value"])
            elif a["matching"] and b["matching"]:
                second = len(b["extra_faults"]) > len(a["extra_faults"])
                (costs_second if second else costs).append(a["value"] - b["value"])
    letters = [g for _, g in score.BANDS]
    return {
        "rows": len(rows), "series": len(series),
        "series_never_rising": sum(not sv.rises([(r["planted_deg"], r["value"]) for r in s]) for s in series.values()),
        "without_matching": {"rows": len(without), "values": sorted({r["value"] for r in without}),
                             "other_faults": sum(r["n_faults"] for r in without)},
        "with_matching": {"rows": len(fired), "min": min((r["value"] for r in fired), default=None),
                          "max": max((r["value"] for r in fired), default=None),
                          "grades": sorted({r["grade"] for r in fired}, key=letters.index)},
        "first_fire_drop": {"min": min(drops, default=None), "max": max(drops, default=None)},
        "later_step_cost": {"max": max(costs, default=None), "max_where_a_second_fault_appears": max(costs_second, default=None)},
        "second_faults": second_faults(rows),
        "realised_gap_deg": {joint: round(max((abs(r["realised_deg"] - r["planted_deg"]) for r in ok if r["joint"] == joint),
                                              default=0.0), 2) for joint in sv.PLANTED},
    }


def _fault_list(faults):
    """A fault set as sorted `[measure, side, direction]` lists, for JSON."""
    return sorted([list(f) for f in faults])


def invariance_figures(rows, summary):
    """Per row group of `summary`, in its order, the figures the prose of section 2 of docs/evaluation.md states beyond the
    table (TICKET-088 N2): the correct takes (how many ran, how many changed value, how many gained a fault), each set's
    takes and how many of them changed value, and, when exactly one take changed value or its fault set, that take and
    what changed."""
    out = []
    for e in summary:
        transform = sv.TRANSFORMS[e["transform"]]
        mine = [r for r in rows if (r["transform"], r["group"]) == (e["transform"], e["group"])]
        ran = [r for r in mine if r["refused"] is None and "error" not in r]

        def expected(r):
            return sv.mirrored_set(sv.fault_set(r["base"])) if transform.mirrors else sv.fault_set(r["base"])

        correct = [r for r in ran if r["correct"]]
        entry = {"transform": e["transform"], "group": e["group"],
                 "correct": {"takes": len(correct), "value_changed": sum(bool(r["delta"]) for r in correct),
                             "gained_a_fault": sum(bool(sv.fault_set(r["variant"]) - expected(r)) for r in correct)},
                 "by_set": {name: {"takes": sum(r["set"] == name for r in mine),
                                   "value_changed": sum(r["set"] == name and bool(r["delta"]) for r in ran)}
                            for name in sv.SETS}}
        moved, changed = [r for r in ran if r["delta"]], [r for r in ran if not r["fault_set_equal"]]
        if len(moved) == 1:
            entry["only_value_change"] = {"take_id": moved[0]["take_id"], "from": moved[0]["base"]["value"],
                                          "to": moved[0]["variant"]["value"]}
        if len(changed) == 1:
            entry["only_fault_set_change"] = {"take_id": changed[0]["take_id"], "from": _fault_list(expected(changed[0])),
                                              "to": _fault_list(sv.fault_set(changed[0]["variant"]))}
        out.append(entry)
    return out


def invariance_findings(summary):
    """One sentence for each row group whose claim (the transform's, where the group is claimed) the numbers miss."""
    out = []
    for e in summary:
        claim = sv.claimed(e["transform"], e["group"])
        if (claim == "exact" and e["verdict"] != "exact") or (claim == "refused" and e["verdict"] != "refused"):
            out.append(f"invariance {e['transform']} ({e['group']}): {e['verdict']}, {e['value_changed']} of {e['takes']} "
                       f"takes changed value (largest {e['max_abs_delta']} points), {e['fault_set_changed']} changed the fault set")
    return out


def shown(path):
    """`path` as the repository-relative text a log should hold (the absolute path when it lies outside the repository)."""
    path = Path(path).resolve()
    return str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)


def row_errors(rows):
    return [f"bench-score: row {r.get('transform') or r['joint']} {r['take_id']}: {r['error']}" for r in rows if "error" in r]


def score_of():
    """The shipped score the numbers were made with: its version and the hash of its params."""
    block = score.params_of(load_rules())
    return {"version": block["version"], "params_sha256": score.params_sha256(block)}


def metrics_doc(dose, dose_takes, inv, summary, curves, fires, summary_fires, findings, exit_code):
    return {
        "format": FORMAT, "sha": git("rev-parse", "HEAD") or "unknown", "dirty": bool(git("status", "--porcelain")),
        "command": COMMAND, "exit_code": exit_code, "seed": sv.SEED, "score": score_of(),
        "grid_deg": sv.GRID, "dose_response_takes": [t["take_id"] for t in dose_takes],
        "dose_response": {"rows": dose, "first_fire": {"summary": summary_fires, "takes": fires},
                          "mean_curve": {j: [list(p) for p in series] for j, series in curves.items()}},
        "invariance": {"transforms": {n: {"text": t.text, "claim": t.claim} for n, t in sv.TRANSFORMS.items()},
                       "summary": summary, "rows": inv},
        "findings": findings}


def score_at(rows):
    """`{joint: {deg: {mean, min, max, grades}}}` over the takes at the SCORE_AT steps: the score cells of the dose-response
    table (the mean, its range and the grades the takes got, best first)."""
    letters = [g for _, g in score.BANDS]
    cells = {}
    for r in sv.measured(rows):
        if r["planted_deg"] in SCORE_AT:
            cells.setdefault(r["joint"], {}).setdefault(f"{r['planted_deg']:g}", []).append(r)
    return {joint: {deg: {"mean": sum(r["value"] for r in rs) / len(rs), "min": min(r["value"] for r in rs),
                          "max": max(r["value"] for r in rs), "grades": sorted({r["grade"] for r in rs}, key=letters.index)}
                    for deg, rs in by_deg.items()}
            for joint, by_deg in cells.items()}


def summaries(dose, dose_takes, fires, summary_fires, inv, summary):
    """`{file name: document}`: the two summaries written beside the chart copy, the figures of docs/evaluation.md's tables
    and prose (AC-SV09). `first_fire.summary.json` holds `dose_response.first_fire` (its summary, and per take), the score
    cells and the figures of section 1's prose (`dose_figures`); `invariance.summary.json` holds `invariance.summary` and the
    figures of section 2's prose (`invariance_figures`). No sha, so they change only when a figure does."""
    head = {"format": SUMMARY_FORMAT, "command": COMMAND, "seed": sv.SEED, "score": score_of()}
    return {FIRST_FIRE_SUMMARY: {**head, "of": "dose_response.first_fire", "grid_deg": sv.GRID,
                                 "takes": [t["take_id"] for t in dose_takes], "summary": summary_fires, "per_take": fires,
                                 "score_at": score_at(dose), "figures": dose_figures(dose)},
            INVARIANCE_SUMMARY: {**head, "of": "invariance.summary", "summary": summary,
                                 "figures": invariance_figures(inv, summary)}}


def print_summary(curves, summary_fires, summary, findings):
    print("bench-score: dose-response (mean score of the takes; first fire in planted degrees)")
    for joint, series in curves.items():
        f = summary_fires[joint]
        at = " ".join(f"{d:g}:{m:.1f}" for d, m, _, _ in series if d in SCORE_AT)
        print(f"  {joint:6} first fire median {f['median_low']} (min {f['min']}, max {f['max']}, never {f['never']}/{f['takes']})  "
              f"score at {at}")
    print("bench-score: invariance (score change against the untransformed take)")
    for e in summary:
        print(f"  {e['transform']:16} {e['group']:27} takes {e['takes']:3} refused {e['refused']:3} value changed "
              f"{e['value_changed']:3} largest {e['max_abs_delta']} fault set changed {e['fault_set_changed']:3} -> {e['verdict']}")
    print(f"bench-score: {len(findings)} findings")
    for line in findings:
        print(f"  {line}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="make_bench_score.py", description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=OUT, help="directory for metrics.json and dose-response.svg")
    ap.add_argument("--chart-copy", default=str(CHART_COPY),
                    help="where the committed copy of the chart goes, with the two table summaries beside it ('' for none)")
    args = ap.parse_args(argv)
    try:
        takes = sv.pool()
    except ValueError as e:
        print(f"bench-score: {e}", file=sys.stderr)
        return 2
    problem = check_inputs(takes)
    if problem:
        print(problem, file=sys.stderr)
        return 2
    dose_takes = sv.correct_exercise(takes)
    dose = sv.dose_rows(dose_takes)
    with tempfile.TemporaryDirectory() as tmp:
        inv = sv.invariance_rows(takes, tmp=tmp)
    fires = sv.first_fire(dose)
    summary_fires = sv.fire_summary(fires)
    curves = sv.mean_curves(dose)
    summary = sv.summarise(inv)
    findings = dose_findings(dose, summary_fires) + invariance_findings(summary)
    errors = row_errors(dose) + row_errors(inv)
    exit_code = 1 if errors else 0
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "metrics.json").write_text(
        json.dumps(metrics_doc(dose, dose_takes, inv, summary, curves, fires, summary_fires, findings, exit_code), indent=1) + "\n")
    svg = chart.dose_response_svg(curves, summary_fires, score.BANDS)
    (args.out / "dose-response.svg").write_text(svg)
    written = []
    if args.chart_copy:
        copy = Path(args.chart_copy)
        copy.parent.mkdir(parents=True, exist_ok=True)
        copy.write_text(svg)
        for name, doc in summaries(dose, dose_takes, fires, summary_fires, inv, summary).items():
            (copy.parent / name).write_text(json.dumps(doc, indent=1) + "\n")
            written.append(shown(copy.parent / name))
    print_summary(curves, summary_fires, summary, findings)
    for line in errors:
        print(line, file=sys.stderr)
    if written:
        print(f"bench-score: wrote the table summaries {' and '.join(written)}")
    print(f"bench-score: wrote {shown(args.out / 'metrics.json')} and {shown(args.out / 'dose-response.svg')}; exit {exit_code}")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
