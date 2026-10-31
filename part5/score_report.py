"""Score a labelled set and report the grade distribution (docs/specs/journey-followup.md J-4, ADR-0007).

    python -m part5.score_report --set <dir with labels.json> [--json]

Prints, per `<lighting>/<labelled faults>` slice, `{n, min, median, max, grades}` and the verdict of each
target (correct good-light takes all A; single faults B or C; double faults D or F; the sweep never rises).
The same functions feed `make check-5` (the gate and the report) and `python -m part5.calibrate --score`.
A report is never a tuning step: the targets are printed as measured.
"""
import argparse
import json
import random
import statistics
import sys
from pathlib import Path


import numpy as np

from . import profiles, score
from .detect import load_rules
from .insights import insights_of
from .output import fault_to_dict
from .pipeline import _fault_times, run
from .visibility import measures_of

ROOT = Path(__file__).resolve().parent.parent
EXERCISE_EXPECTED = ROOT / "fixtures" / "input" / "expected" / "exercise" / "animation.json"
GRADES = [g for _, g in score.BANDS]
SWEEP_SEED = 1234
SWEEPS = (("foot_out", "right", range(0, 29, 4)),
          ("arms_wider", "both", range(0, 36, 5)),
          ("trunk_lean", "center", range(0, 31, 5)))
TARGETS = {"good/0": "A", "good/1": "BC", "good/2": "DF"}   # slice -> the grades that meet the target


# --- one take ---
def aligned_of(result, vis=None):
    """The `aligned` input of `score.compute` from a `PipelineResult` or a `RepResult` (the shape part5/score.py
    documents). `vis` (the pair's `Visibility`, ADR-0011; a `PipelineResult` carries its own) leaves the measures
    the camera did not see as NaN, so they never reach the similarity term; a full-body pair is unchanged."""
    vis = vis or getattr(result, "vis", None)
    return {"expected": measures_of(result.expected.positions, vis),
            "follower": measures_of(result.follower_positions, vis),
            "exp_to_fol": result.alignment.exp_to_fol}


def score_block(result, rules=None):
    """The `score` hook for `pipeline.run` (ADR-0007, ADR-0013): the take scored window by window with the
    `score.compute` formula, and the mean of the windows. A take compared rep by rep (ADR-0010) has one window
    per rep, scored on that rep's own misses; a take compared as a whole has windows of about 5 s.
    Never None (ADR-0012): a take with no alignment scores 0, and any warning caps the value at 59.

    `rules` defaults to the rules the take was analysed with (`result.rules`), so a profile's thresholds and tempo
    block reach the score (ADR-0016)."""
    rules = result.rules if rules is None else rules
    if result.guard is None:   # not aligned: nothing to score
        block = score.zero_block(rules)
    elif result.reps:
        block = _rep_timeline(result, rules)
    else:
        aligned = aligned_of(result)
        frame_times = result.follower.t[np.asarray(result.to_original)[np.asarray(aligned["exp_to_fol"])]]
        block = score.compute_timeline(result.analysis, aligned, frame_times, rules,
                                       expected_times=result.expected.t[:len(aligned["exp_to_fol"])])
    return score.cap_by_warnings(block, result.analysis, rules)


def _rep_timeline(result, rules):
    """One window per follower rep: an accepted rep is scored on every miss found in it (not only the ones
    the take reports), a rep that did not match the example is shown but not scored. `per_rep` stays (1.3.0)."""
    rules = rules or load_rules()
    p = score.params_of(rules)
    tempo = profiles.tempo_of(rules)   # ADR-0016: the profile's tempo words and, for dance, its charge
    fol, windows, ratios = result.follower, [], []
    for r in result.reps:
        span = (float(fol.t[r.span[0]]), float(fol.t[r.span[1]]))
        if not r.ok:
            windows.append({"t_s": span, "compared": False})
            continue
        ratio = score.span_ratio(span, (float(r.expected.t[0]), float(r.expected.t[-1])))   # ADR-0014: rep over example rep
        faults = []
        for f in r.faults:
            # the take's coaching line carries the first rep's time, so each rep says its own (text_timed)
            faults.append(fault_to_dict(f, _fault_times(f, r.expected, fol, r.follower_positions, r.alignment,
                                                        r.to_original)))
        aligned = aligned_of(r, result.vis)
        window = score.timeline_window(span, {"status": {"code": "ok"}, "faults": faults}, aligned,
                                       np.arange(len(aligned["exp_to_fol"])), rules, p, tempo, ratio)
        if window.get("compared", True):
            ratios.append(ratio)
        windows.append(window)
    timed = [x for x in ratios if x is not None]
    block = score.timeline_block(windows, "reps", rules, float(np.median(timed)) if timed else None)
    block["per_rep"] = [{"value": w["value"], "grade": w["grade"]} for w in block["timeline"] if w["compared"]]
    return block


FEET_KEYS = ("expected_feet", "follower_feet")


def feet_kwargs(take, base=ROOT):
    """The foot side files a labelled take names, as keyword arguments for `pipeline.run` (ADR-0015).

    A take in labels.json may carry `expected_feet` and `follower_feet`, paths from the repository root (`base`) like
    `expected` and `follower`; the person is the default, id 0. A take that names none gets {} and is analysed as before."""
    return {key: str(resolve(take[key], base)) for key in FEET_KEYS if take.get(key)}


def analyse(expected, follower, rules=None, **feet):
    """`pipeline.analyse` plus the score under `analysis["score"]` (never None), unless the pipeline already set it.
    `feet` is `feet_kwargs(take)`: the side files `pipeline.run` takes."""
    result = run(expected, follower, rules, **feet)
    analysis = result.analysis
    if "score" not in analysis:
        analysis["score"] = score_block(result, rules)
        analysis["insights"] = insights_of(analysis)   # ranked by the timeline's points (ADR-0014)
    return analysis


def take_row(label, result, rules):
    """Calibration features of one take. `mean_z` is taken for every aligned take, refused ones included."""
    aligned = aligned_of(result)
    n = len(aligned["exp_to_fol"])
    return {"take_id": label["take_id"], "lighting": label["lighting"], "n_labelled": len(label["faults"]),
            "faults": [score.fault_features(f, n) for f in result.analysis["faults"]],
            "mean_z": score.mean_z(aligned, rules)}


def resolve(path, base):
    p = Path(path)
    return p if p.is_absolute() else Path(base) / p


def load_labels(directory):
    return json.loads((Path(directory) / "labels.json").read_text())


def run_set(labels_doc, rules=None, base=ROOT):
    """[(label, PipelineResult)] for every take of the set (paths in the labels resolve against `base`; a take's
    `expected_feet` and `follower_feet` go to `run`, so a take with foot side files is analysed with its feet)."""
    out = []
    for t in labels_doc["takes"]:
        exp, fol = resolve(t["expected"], base), resolve(t["follower"], base)
        out.append((t, run(str(exp), {"path": str(fol), "take_id": t["take_id"]}, rules, **feet_kwargs(t, base))))
    return out


def rows_of_set(labels_doc, rules=None, base=ROOT):
    rules = rules or load_rules()
    return [take_row(t, r, rules) for t, r in run_set(labels_doc, rules, base) if r.alignment is not None]


# --- the distribution ---
def slice_key(label):
    return f"{label['lighting']}/{len(label['faults'])}"


def distribution(entries):
    """{"<light>/<n labelled>": {n, min, median, max, grades}} from [(label, score block or None)]; refused takes are left out of n."""
    out = {}
    for light in ("good", "low"):
        for n in (0, 1, 2):
            vals = [s["value"] for t, s in entries if t["lighting"] == light and len(t["faults"]) == n and s]
            if not vals:
                out[f"{light}/{n}"] = {"n": 0, "min": None, "median": None, "max": None, "grades": {}}
                continue
            grades = {g: sum(score.grade(v) == g for v in vals) for g in GRADES}
            out[f"{light}/{n}"] = {"n": len(vals), "min": min(vals), "median": statistics.median(vals),
                                   "max": max(vals), "grades": {g: c for g, c in grades.items() if c}}
    return out


def entries_of(labels_doc, analyses):
    return [(t, analyses[t["take_id"]].get("score")) for t in labels_doc["takes"]]


def verdicts(dist):
    """Target verdicts of the good-light slices, as measured: pass, fail or 'no takes'."""
    out = {}
    for key, ok in TARGETS.items():
        d = dist[key]
        out[key] = "no takes" if not d["n"] else ("pass" if set(d["grades"]) <= set(ok) else "fail")
    return out


def correct_good_failures(labels_doc, analyses):
    """One sentence per correct good-light take that is not an A, or is ok but has no score."""
    out = []
    for t in labels_doc["takes"]:
        if t["lighting"] != "good" or t["faults"]:
            continue
        a = analyses[t["take_id"]]
        if (a.get("status") or {}).get("code") != "ok":
            continue  # a refused correct take already fails the precision gate (faults on correct takes)
        s = a.get("score")
        if s is None:
            out.append(f"{t['take_id']}: no score (refused or not scored)")
        elif s["grade"] != "A":
            out.append(f"{t['take_id']}: scored {s['value']} ({s['grade']}), a correct good-light take must be an A")
    return out


# --- monotonicity ---
def monotone_failures(sweeps):
    """sweeps: {"<type> <side>": [(size, value)]} in growing size. A step that rises is a failure sentence."""
    out = []
    for name, points in sweeps.items():
        for (d0, v0), (d1, v1) in zip(points, points[1:]):
            if v1 > v0:
                out.append(f"sweep {name}: score rises from {v0} at {d0} degrees to {v1} at {d1} degrees")
    return out


def run_sweep(out_dir, rules=None, analyse_fn=None):
    """Score one fault type at growing size on an otherwise fixed take (the same `random.Random(1234)`), takes
    written under `out_dir`. Returns {"<type> <side>": [(size, value)]}."""
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import make_dummy_followers as gen
    finally:
        sys.path.pop(0)
    analyse_fn = analyse_fn or analyse
    expected = json.loads(EXERCISE_EXPECTED.read_text())
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    result = {}
    for ftype, side, sizes in SWEEPS:
        points, spec = [], gen.FAULTS[ftype]
        old = spec["deg"]
        for d in sizes:
            spec["deg"] = (d, d)
            try:
                doc, _ = gen.build_take(expected, f"sweep_{ftype}_{d}", "front", "good",
                                        [(ftype, side)] if d else [], random.Random(SWEEP_SEED))
            finally:
                spec["deg"] = old
            path = out_dir / f"{ftype}_{d}.json"
            path.write_text(json.dumps(doc))
            s = analyse_fn(str(EXERCISE_EXPECTED), str(path)).get("score")
            points.append((d, s["value"] if s else None))
        result[f"{ftype} {side}"] = points
    return result


def sweep_failures(sweeps):
    """Monotonicity failures, plus one sentence per step that has no score to compare."""
    missing = [f"sweep {n}: no score at {d} degrees" for n, pts in sweeps.items() for d, v in pts if v is None]
    clean = {n: [(d, v) for d, v in pts if v is not None] for n, pts in sweeps.items()}
    return missing + monotone_failures(clean)


# --- the command ---
def report_lines(dist, verdict):
    lines = []
    for key, d in dist.items():
        lines.append(f"{key:7s} n {d['n']:3d}  min {d['min']}  median {d['median']}  max {d['max']}  {d['grades']}"
                     + (f"  target {TARGETS[key]}: {verdict[key]}" if key in verdict else "  (reported, no target)"))
    return lines


def calibrate_set(labels_doc, rules=None, base=ROOT):
    """The `score` block calibrated on the seed 5 set (score.calibrate; the caller checks the seed)."""
    rules = rules or load_rules()
    return score.calibrate(rows_of_set(labels_doc, rules, base), rules["default"]["min_fraction"])


def scored_set(labels_doc, rules=None, base=ROOT):
    """{take_id: score block or None} for the set, one pipeline run per take."""
    rules = rules or load_rules()
    out = {}
    for t, r in run_set(labels_doc, rules, base):
        out[t["take_id"]] = score_block(r, rules) if r.alignment is not None else None
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m part5.score_report", description=__doc__.splitlines()[0])
    ap.add_argument("--set", required=True, help="a directory with labels.json and the takes it names")
    ap.add_argument("--json", action="store_true", help="print the distribution as JSON")
    args = ap.parse_args(argv)
    labels = load_labels(args.set)
    scores = scored_set(labels)
    dist = distribution([(t, scores[t["take_id"]]) for t in labels["takes"]])
    verdict = verdicts(dist)
    if args.json:
        print(json.dumps({"seed": labels["seed"], "distribution": dist, "verdicts": verdict}, indent=1))
    else:
        print(f"score_report: seed {labels['seed']}, {len(labels['takes'])} takes")
        print("\n".join(report_lines(dist, verdict)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
