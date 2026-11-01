"""Score a labelled set and report the grade distribution (docs/specs/journey-followup.md J-4, ADR-0007, ADR-0018).

    python -m part5.score_report --set <dir with labels.json> [--json]
    python -m part5.score_report --calibrate-v2 [--set <seed 5 dir>]
    python -m part5.score_report --params-sha256

Prints, per `<lighting>/<labelled faults>` slice, `{n, min, median, max, grades}` and the verdict of each
target (correct good-light takes all A; single faults B or C; double faults D or F, C, D or F from v2; the sweep never
rises). Under `simon.score.v2` it also prints ADR-0018's five targets, judged on the takes that report exactly their
labelled faults, and the takes that do not. `--calibrate-v2` runs ADR-0018's rule for `range_floor` on seed 5 and
prints the v2 `score` block; `--params-sha256` prints the hash the orchestrator records at the freeze.
The same functions feed `make check-5` (the gate and the report) and `python -m part5.calibrate --score`.
A report is never a tuning step: the targets are printed as measured.
"""
import argparse
import json
import random
import statistics
import sys
import tempfile
from pathlib import Path


import numpy as np

from . import profiles, score
from .detect import load_rules
from .evaluate import match_faults
from .insights import insights_of
from .measures import FOOT_MEASURES
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
TARGETS_V1 = {"good/0": "A", "good/1": "BC", "good/2": "DF"}   # ADR-0007: slice -> the grades that meet the target
TARGETS_V2 = {"good/0": "A", "good/1": "BC", "good/2": "CDF"}  # ADR-0018: double faults C, D or F
TUNING_SEED = 5   # the only set the score is tuned on (ADR-0003, ADR-0007, ADR-0018)
# ADR-0018, printed beside the strict good/1 verdict of a score report so a pass is not read as more than it shows:
COMPARABILITY = ("comparability: by the recorded v1 numbers (fixtures/score-heldout.json, seeds 47 and 53, measured under earlier "
                 "detection rules) v1 itself would have met targets 1, 3, 4 and 5 (every good/1 A there was a fault not "
                 "detected, every good/1 minimum was 72 or more, every good/2 grade was D or F); a pass here shows that v2 does "
                 "not break those targets, not that it fixes v1's recorded misses")


def targets_of(version):
    """The slice targets of a score version: ADR-0007's for v1, ADR-0018's otherwise."""
    return TARGETS_V1 if version == score.VERSION_V1 else TARGETS_V2


# --- one take ---
def trainer_feet(result):
    """The trainer's foot series the pair was compared on, for the range weight of a foot fault (ADR-0018): a
    `PipelineResult` carries them on the expected clip's own frames (`foot_expected`, from `pipeline._foot_series`); a
    `RepResult` holds its reference rep's inside the reference measures it was detected on. `{}` without feet files."""
    if getattr(result, "measures", None):
        return {k: v for k, v in result.measures[0].items() if k in FOOT_MEASURES}
    return dict(getattr(result, "foot_expected", None) or {})


def aligned_of(result, vis=None):
    """The `aligned` input of `score.compute` from a `PipelineResult` or a `RepResult` (the shape part5/score.py
    documents). `vis` (the pair's `Visibility`, ADR-0011; a `PipelineResult` carries its own) leaves the measures
    the camera did not see as NaN, so they never reach the similarity term; a full-body pair is unchanged. The expected
    side also holds the trainer's foot series (`trainer_feet`); the similarity term reads the body measures only."""
    vis = vis or getattr(result, "vis", None)
    return {"expected": {**measures_of(result.expected.positions, vis), **trainer_feet(result)},
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
    the take reports), and on the faults the take reports that it shows at `min_fraction` of itself without the floor
    (`RepResult.continued`, ADR-0017); a rep that did not match the example is shown but not scored. `per_rep` stays
    (1.3.0)."""
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
        for f in [*r.faults, *r.continued]:
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
    block = score.timeline_block(windows, "reps", rules, float(np.median(timed)) if timed else None,
                                 reports_fault=bool(result.analysis.get("faults")))
    block["per_rep"] = [{"value": w["value"], "grade": w["grade"]} for w in block["timeline"] if w["compared"]]
    return block


FEET_KEYS = ("expected_feet", "follower_feet")


def feet_kwargs(take, base=ROOT):
    """The foot side files a labelled take names, as keyword arguments for `pipeline.run` (ADR-0015).

    A take in labels.json may carry `expected_feet` and `follower_feet`, paths from the repository root (`base`) like
    `expected` and `follower`; the person is the default, id 0. A take that names none gets {} and is analysed as before."""
    return {key: str(resolve(take[key], base)) for key in FEET_KEYS if take.get(key)}


def feet_diagnostics(block, names):
    """`diagnostics.feet` with each side's `source` as the path from the repository root (`names`, the form `expected`
    and `follower` have), not the absolute path `pipeline.run` was given, so a report or a response does not depend on
    where the repository is checked out. A side with no file keeps its null source; `block` is not edited in place."""
    out = dict(block)
    for key, side in zip(FEET_KEYS, ("expected", "follower")):
        if names.get(key) and out[side].get("source"):
            out[side] = {**out[side], "source": names[key]}
    return out


def analyse(expected, follower, rules=None, **feet):
    """`pipeline.analyse` plus the score under `analysis["score"]` (never None), unless the pipeline already set it.
    `feet` is `feet_kwargs(take)`: the side files `pipeline.run` takes."""
    result = run(expected, follower, rules, **feet)
    analysis = result.analysis
    if "score" not in analysis:
        analysis["score"] = score_block(result, rules)
        analysis["insights"] = insights_of(analysis)   # ranked by the timeline's points (ADR-0014)
    return analysis


def rep_mean_z(result, rules):
    """The mean z of a take compared rep by rep: the mean over its accepted reps' frames, each rep against its own
    reference (None when no rep could be measured)."""
    parts = [(score.mean_z(aligned_of(r, result.vis), rules), len(r.expected.t)) for r in result.reps if r.ok]
    parts = [(z, n) for z, n in parts if z is not None]
    return sum(z * n for z, n in parts) / sum(n for _, n in parts) if parts else None


def take_row(label, result, rules):
    """Calibration features of one take. `mean_z` is taken for every aligned take, refused ones included. A take compared
    rep by rep (ADR-0017: any take of a multi-rep example) has its faults measured against the whole example and its
    `mean_z` over its reps; the shipped score parameters were calibrated on the whole-clip rows and stay frozen."""
    if result.reps:
        return {"take_id": label["take_id"], "lighting": label["lighting"], "n_labelled": len(label["faults"]),
                "faults": [score.fault_features(f, result.expected.n_frames) for f in result.analysis["faults"]],
                "mean_z": rep_mean_z(result, rules)}
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


def shipped_targets(rules=None):
    """The slice targets of the score the rules ship (`targets_of` their `score.version`)."""
    return targets_of(score.params_of(rules or load_rules())["version"])


def verdicts(dist, targets=None):
    """Target verdicts of the good-light slices, as measured: pass, fail or 'no takes'. `targets` defaults to the
    shipped score's (ADR-0007 for a v1 block, ADR-0018 for v2): the whole slice, takes that miss their labels included."""
    out = {}
    for key, ok in (targets or shipped_targets()).items():
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
def report_lines(dist, verdict, targets=None):
    targets = targets or shipped_targets()
    lines = []
    for key, d in dist.items():
        lines.append(f"{key:7s} n {d['n']:3d}  min {d['min']}  median {d['median']}  max {d['max']}  {d['grades']}"
                     + (f"  target {targets[key]}: {verdict[key]}" if key in verdict else "  (reported, no target)"))
    return lines


def calibrate_set(labels_doc, rules=None, base=ROOT):
    """The `score` block calibrated on the seed 5 set (the caller checks the seed). Rules that ship the v2 form (a v2
    block holding the frozen `v1` block) get a v2 block back: v1 stays as frozen and `range_floor` is fitted by ADR-0018's
    rule. Any other rules get the v1 calibration (`score.calibrate`), as ADR-0007 states it."""
    rules = rules or load_rules()
    shipped = rules.get("score") or {}
    if shipped.get("version") == score.VERSION and isinstance(shipped.get("v1"), dict):
        return calibrate_v2_set(labels_doc, rules, base)[0]
    return score.calibrate(rows_of_set(labels_doc, rules, base), rules["default"]["min_fraction"])


def scored_results(labels_doc, rules=None, base=ROOT, results=None):
    """[(label, PipelineResult, score block or None)] for the set, one pipeline run per take (`results`, the output of
    `run_set`, when the caller already has them)."""
    rules = rules or load_rules()
    results = run_set(labels_doc, rules, base) if results is None else results
    return [(t, r, score_block(r, rules) if r.alignment is not None else None) for t, r in results]


# --- score v2 (ADR-0018): the five targets and the floor's rule ---
def reports_exactly(take, analysis):
    """Does the analysis report exactly the faults the take is labelled with: every label found, nothing else
    (`evaluate.match_faults`)? The takes ADR-0018's targets 4 and 5 are judged on."""
    predicted = analysis.get("faults", [])
    return match_faults(predicted, take["faults"])[0] == len(take["faults"]) == len(predicted)


def split_good(entries):
    """The groups ADR-0018's targets and its floor rule read, from `[(label, analysis, score block or None)]`: the good-light
    takes that were scored (`good`), those with no labelled fault (`correct`), those that report a fault (`reporting`),
    those with one or two labels that report exactly them (`single`, `double`) and those with one or two labels whose
    reported faults differ from them (`not_judged`, a detection result)."""
    good = [(t, a, b) for t, a, b in entries if t["lighting"] == "good" and b]
    labelled = lambda n: [x for x in good if len(x[0]["faults"]) == n]   # noqa: E731
    exact = lambda n: [x for x in labelled(n) if reports_exactly(x[0], x[1])]   # noqa: E731
    return {"good": good, "correct": labelled(0), "reporting": [x for x in good if x[1].get("faults")],
            "single": exact(1), "double": exact(2),
            "not_judged": [x for n in (1, 2) for x in labelled(n) if not reports_exactly(x[0], x[1])]}


def _judged(items, ok):
    """{verdict, n, breaks}: the takes of `items` (label, analysis, block) whose grade is not in `ok` break the target."""
    breaks = [f"{t['take_id']}: scored {b['value']} ({b['grade']})" for t, _, b in items if b["grade"] not in ok]
    return {"verdict": "no takes" if not items else ("fail" if breaks else "pass"), "n": len(items), "breaks": breaks}


TARGET_KEYS = ("correct_all_a", "no_reported_fault_grades_a", "single_b_or_c", "double_c_d_or_f")   # targets 1, 3, 4, 5


def targets_v2(entries):
    """ADR-0018's targets 1, 3, 4 and 5 on `[(label, analysis, score block or None)]` (2, the sweep, is run apart).

    Judged on the good-light takes that were scored: every correct take an A (1); no take that reports a fault graded A
    (3); a take with one labelled fault that reports exactly it, B or C (4); a take with two that reports exactly them,
    C, D or F (5). A take with one or two labels whose reported faults differ from them is a detection result and is
    listed in `not_judged` with its grade, not judged by 4 and 5 (the strict slice verdicts, `verdicts`, are printed beside)."""
    g = split_good(entries)
    return {"correct_all_a": _judged(g["correct"], "A"), "no_reported_fault_grades_a": _judged(g["reporting"], "BCDF"),
            "single_b_or_c": _judged(g["single"], "BC"), "double_c_d_or_f": _judged(g["double"], "CDF"),
            "not_judged": [{"take_id": t["take_id"], "labelled": len(t["faults"]), "reported": len(a.get("faults", [])),
                            "value": b["value"], "grade": b["grade"]} for t, a, b in g["not_judged"]]}


def targets_hold(targets, sweep_failures_found):
    """ADR-0018's fail-closed clause (stakeholder-proxy ruling of 2026-11-01T05:45Z): all five targets hold only when each of
    1, 3, 4 and 5 judged at least one take and none broke it, and the sweep (2) was run and never rose. A target with no
    judged take (`n` 0, verdict "no takes") does not hold. `sweep_failures_found` is the sweep's failure list, None when the
    sweep was not run."""
    return all(targets[k]["verdict"] == "pass" for k in TARGET_KEYS) and sweep_failures_found == []


def targets_v2_lines(targets, sweep_failed=None):
    """The five targets as measured, one line each, then the takes not judged."""
    names = (("1", "correct good-light takes all A", "correct_all_a"),
             ("3", "no take that reports a fault grades A", "no_reported_fault_grades_a"),
             ("4", "single faults B or C (reported exactly)", "single_b_or_c"),
             ("5", "double faults C, D or F (reported exactly)", "double_c_d_or_f"))
    lines = []
    for number, text, key in names:
        t = targets[key]
        lines.append(f"  {number} {text}: {t['verdict']} (n {t['n']})" + "".join(f"\n      {b}" for b in t["breaks"]))
        if number == "1" and sweep_failed is not None:
            lines.append(f"  2 the sweep never rises: {'fail' if sweep_failed else 'pass'}"
                         + "".join(f"\n      {f}" for f in sweep_failed))
    out = [x["take_id"] + f" ({x['labelled']} labelled, {x['reported']} reported, {x['value']} {x['grade']})"
           for x in targets["not_judged"]]
    lines.append(f"  not judged by 4 and 5 (reported faults differ from the labels): {len(out)}"
                 + "".join(f"\n      {o}" for o in out))
    return lines


def v1_of(rules):
    """The frozen v1 block of the score section `rules` ship: the section itself when it is v1, else its `v1`."""
    block = score.params_of(rules)
    return block if block["version"] == score.VERSION_V1 else score.rules_v1(rules)["score"]


def rules_with_floor(rules, floor):
    """`rules` with the v2 block built from their v1 block and `floor` (what ADR-0018's rule tries on seed 5)."""
    return {**rules, "score": score.block_v2(v1_of(rules), floor)}


def measure_floor(results, rules, sweep=True):
    """ADR-0018's four conditions for the v2 `rules` on seed 5 `results` (`run_set`'s output), as
    `score.floor_holds` reads them: every correct good-light take an A, the lowest score of a good-light take that reports
    exactly its one labelled fault, the highest of one that reports exactly its two, and whether the sweep rises."""
    g = split_good([(t, r.analysis, b) for t, r, b in scored_results(None, rules, results=results)])
    rises = False
    if sweep:
        with tempfile.TemporaryDirectory() as tmp:
            rises = bool(sweep_failures(run_sweep(tmp, rules, analyse_fn=lambda e, f: analyse(e, f, rules))))
    return {"correct_all_a": all(b["grade"] == "A" for _, _, b in g["correct"]),
            "single_min": min((b["value"] for _, _, b in g["single"]), default=None),
            "double_max": max((b["value"] for _, _, b in g["double"]), default=None), "sweep_rises": rises}


def measure_floors(results, rules, sweep=True):
    """{floor: measurement} over `score.FLOOR_GRID`: the data `score.choose_floor` reads."""
    return {f: measure_floor(results, rules_with_floor(rules, f), sweep) for f in score.FLOOR_GRID}


def calibrate_v2_set(labels_doc, rules=None, base=ROOT, results=None, sweep=True):
    """`(v2 score block, measurements)` for the seed 5 set: the frozen v1 block of `rules` and the floor ADR-0018's rule
    picks from the measurements of every floor of the grid."""
    rules = rules or load_rules()
    results = run_set(labels_doc, rules, base) if results is None else results
    measured = measure_floors(results, rules, sweep)
    return score.block_v2(v1_of(rules), score.choose_floor(measured)), measured


def floor_table(measured, chosen):
    lines = ["floor  correct all A  single min  double max  sweep rises  holds"]
    for f, m in measured.items():
        lines.append(f"{f:5.2f}  {str(m['correct_all_a']):13s}  {str(m['single_min']):10s}  {str(m['double_max']):10s}  "
                     f"{str(m['sweep_rises']):11s}  {'yes' if score.floor_holds(m) else 'no'}{'  <- chosen' if f == chosen else ''}")
    return lines


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m part5.score_report", description=__doc__.splitlines()[0])
    ap.add_argument("--set", default=None, help="a directory with labels.json and the takes it names")
    ap.add_argument("--json", action="store_true", help="print the distribution as JSON")
    ap.add_argument("--json-out", default=None, metavar="PATH",
                    help="also write the report as JSON here (the text report is still printed); `make score-heldout` reads "
                         "`targets_v2.holds` from it to name what the v2 attempt records")
    ap.add_argument("--calibrate-v2", action="store_true",
                    help="run ADR-0018's rule for range_floor on --set (default: seed 5) and print the v2 score block")
    ap.add_argument("--params-sha256", action="store_true",
                    help="print the sha256 of the score block of part5/rules.json (what the freeze records)")
    args = ap.parse_args(argv)
    if args.params_sha256:
        print(score.params_sha256(score.params_of(load_rules())))
        return 0
    if args.calibrate_v2:
        return _print_calibration(args.set or str(ROOT / "fixtures" / "input" / "followers"))
    if not args.set:
        ap.error("--set is required")
    labels = load_labels(args.set)
    rules = load_rules()
    scored = scored_results(labels, rules)
    dist = distribution([(t, b) for t, _, b in scored])
    verdict = verdicts(dist)
    v2 = score.params_of(rules)["version"] == score.VERSION
    targets = targets_v2([(t, r.analysis, b) for t, r, b in scored]) if v2 else None
    sweep_failed = _sweep_failures() if v2 else None
    holds = targets_hold(targets, sweep_failed) if v2 else None
    doc = {"seed": labels["seed"], "version": score.params_of(rules)["version"], "distribution": dist, "verdicts": verdict}
    if v2:
        doc["targets_v2"] = {**targets, "sweep_failures": sweep_failed, "holds": holds}
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(doc, indent=1) + "\n")
    if args.json:
        print(json.dumps(doc, indent=1))
    else:
        print(f"score_report: seed {labels['seed']}, {len(labels['takes'])} takes, {score.params_of(rules)['version']}")
        print("\n".join(report_lines(dist, verdict)))
        if v2:
            print("ADR-0018 targets (good-light takes; the strict slice verdicts above are reported beside them):")
            print("\n".join(targets_v2_lines(targets, sweep_failed)))
            print(f"  all five hold: {'yes' if holds else 'no'}  (a target with no judged take does not hold)")
            print(f"  {COMPARABILITY}")
    return 0


def _sweep_failures():
    with tempfile.TemporaryDirectory() as tmp:
        return sweep_failures(run_sweep(tmp))


def _print_calibration(directory):
    """`--calibrate-v2`: the rule's table on stderr and the v2 block on stdout. Seed 5 only, like `calibrate.py` (ADR-0003)."""
    labels = load_labels(directory)
    if labels.get("seed") != TUNING_SEED:
        print(f"score_report: --calibrate-v2 runs on the seed {TUNING_SEED} tuning set only, not seed {labels.get('seed')} "
              f"({directory}); the floor is tuned on seed 5 alone (ADR-0003, ADR-0018)", file=sys.stderr)
        return 2
    rules = load_rules()
    block, measured = calibrate_v2_set(labels, rules)
    print("\n".join(floor_table(measured, block["range_floor"])), file=sys.stderr)
    print(json.dumps(block, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
