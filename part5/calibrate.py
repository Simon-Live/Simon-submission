"""Offline calibration on the seed 5 tuning set (docs/specs/calibration.md, ADR-0003, ADR-0004).

    python -m part5.calibrate --set fixtures/input/followers [--guard] [--write-thresholds]
                              [--radius N] [--only NAME,NAME]

Threshold sweep: for each key of part5/rules.json, one at a time and in file order, re-run fault
detection over every cached take at each candidate value, and keep the best by the objective of
the spec: on the good-light slices, first precision >= 0.85 and 0 faults on correct takes at every
angle, then the highest minimum recall across the angles. The values tied at the best objective form
a plateau; the middle of its longest contiguous run is kept, rounded up to the grid step (equal runs:
the one with the larger values), so the frozen value has margin on both sides (stakeholder-proxy
decision, 2026-10-29, `docs/specs/calibration.md` Sweeps). Alignment and measures are computed once
per take. Low light is printed, never used to choose. The table is the
same on every run (AC-T05).

--guard: `residual`, `timing_corr` and `span_share` (from `part5.guard.movement_stats`) for every
seed 5 take against its own clip (matched) and for the mismatch pairs, the limits at the midpoint
of the gap, and the overlap named when the populations meet.

--write-thresholds: writes docs/thresholds.md above its attempts marker; the attempts below it are
kept as they are (a red attempt is never dropped).

This tool reads the tuning set only: a set whose labels.json seed is not 5 exits 2 (AC-T01).
"""
import argparse
import copy
import json
import math
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path

from .align import align
from .check import MIN_PRECISION, MAX_FAULTS_ON_CORRECT, rel
from .detect import RULES_PATH, detect, load_rules
from .evaluate import matches, score
from .guard import movement_stats
from .io import load_clip
from .measures import compute
from .normalise import normalise
from .pipeline import clip_fps, resample
from . import score_report

ROOT = Path(__file__).resolve().parent.parent
TUNING_SEED = 5
TUNING = ROOT / "fixtures" / "input" / "followers"
MISMATCH_DIR = ROOT / "fixtures" / "input" / "mismatch"
THRESHOLDS_DOC = ROOT / "docs" / "thresholds.md"
SOURCES = ROOT / "contracts" / "sources.json"
ANGLES = ("front", "45", "side")
RADIUS_DEG = 6          # threshold grid: this many 1 degree steps each side of the current value
PERSISTENCE = (         # key, step, low, high, steps each side
    ("min_fraction", 0.05, 0.05, 0.9, 3),
    ("min_run_frames", 1, 1, 30, 3),
    ("min_overlap", 0.1, 0.1, 1.0, 3),
)
ATTEMPTS_MARKER = "<!-- attempts:begin -->"
GUARD_STATS = ("residual", "timing_corr", "span_share")


class CalibrateError(Exception):
    """Calibration can't run (exit 2): a refused set or a missing fixture."""


# --- loading and caching ---
class Clips:
    """Each expected clip is loaded and measured once; a pair adds the follower's alignment."""

    def __init__(self):
        self._expected = {}

    def expected(self, path):
        path = str(path)
        if path not in self._expected:
            clip = normalise(self._load(path))
            self._expected[path] = (clip, compute(clip.positions))
        return self._expected[path]

    @staticmethod
    def _load(path):
        if not Path(path).is_file():
            raise CalibrateError(f"calibrate: {rel(path)} missing; run the neighbour check or TICKET-015 fixtures")
        try:
            return load_clip(path)
        except ValueError as e:
            raise CalibrateError(f"calibrate: {e}") from e

    def pair(self, expected_path, follower_path):
        """(expected measures, follower measures on the expected clock, alignment)."""
        exp, exp_m = self.expected(expected_path)
        fol = normalise(self._load(str(follower_path)))
        # No availability or frame-count check as in pipeline.run: calibration reads committed fixtures only.
        positions, _ = resample(fol.positions, fol.t, clip_fps(exp))
        return exp_m, compute(positions), align(exp.positions, positions)


@dataclass
class Prepared:
    take: dict
    exp_m: dict
    fol_m: dict
    alignment: object


def load_set(directory):
    """The tuning set's labels, or a CalibrateError (AC-T01: seed 5 only)."""
    path = Path(directory) / "labels.json"
    if not path.is_file():
        raise CalibrateError(f"calibrate: {rel(path)} missing; run make dummy-data")
    labels = json.loads(path.read_text())
    if labels.get("seed") != TUNING_SEED:
        raise CalibrateError(f"calibrate: tuning reads seed {TUNING_SEED} only (got {labels.get('seed')})")
    return labels


def prepare_set(labels, clips):
    return [Prepared(t, *clips.pair(ROOT / t["expected"], ROOT / t["follower"])) for t in labels["takes"]]


# --- scoring one rules variant ---
def records(prepared, rules):
    return [{"predicted": [f.to_dict() for f in detect(p.exp_m, p.fol_m, p.alignment, rules)],
             "labels": p.take["faults"], "lighting": p.take["lighting"], "angle": p.take["angle"],
             "correct": p.take["correct"]} for p in prepared]


def evaluate(prepared, rules):
    return score(records(prepared, rules))


def angle_cells(metrics, light):
    """Per angle: (precision, recall, faults on correct takes), or None when the slice is absent."""
    out = {}
    for a in ANGLES:
        s = metrics["slices"].get(f"{light}/{a}")
        out[a] = (s["precision"], s["recall"], s["faults_on_correct_takes"]) if s else None
    return out


def objective(metrics):
    """(feasible, -shortfall, min recall): higher is better. Feasible means precision >= 0.85 and
    0 faults on correct takes at every good-light angle; otherwise the shortfall ranks the rest."""
    cells = [c for c in angle_cells(metrics, "good").values() if c]
    shortfall = sum(max(0.0, MIN_PRECISION - p) + max(0, f - MAX_FAULTS_ON_CORRECT) for p, _, f in cells)
    return (shortfall == 0, -round(shortfall, 6), min((r for _, r, _ in cells), default=0.0))


# --- the sweep ---
@dataclass(frozen=True)
class Param:
    name: str
    path: tuple
    step: float
    low: float
    high: float
    steps: int


def get_path(rules, path):
    node = rules
    for key in path:
        node = node[key]
    return node


def with_value(rules, path, value):
    out = copy.deepcopy(rules)
    node = out
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    return out


def locate(rules, key):
    """Where a persistence key lives in rules: under "default" or at the top level; None if absent."""
    for scope in (("default",), ()):
        node = rules
        for k in scope:
            node = node.get(k, {})
        if key in node:
            return scope + (key,)
    return None


def params(rules, only=None):
    found = [Param(f"{g} threshold_deg", ("measures", g, "threshold_deg"), 1.0, 1.0, math.inf, RADIUS_DEG)
             for g in rules["measures"] if "threshold_deg" in rules["measures"][g]]
    for key, step, low, high, steps in PERSISTENCE:
        path = locate(rules, key)
        if path:
            found.append(Param(key, path, step, low, high, steps))
    if only:
        found = [p for p in found if p.name in only or p.name.split()[0] in only]
    return found


def grid(param, current, steps):
    values = {round(current + k * param.step, 4) for k in range(-steps, steps + 1)}
    return sorted(v for v in values if param.low <= v <= param.high)


def row(value, metrics):
    return {"value": value, "good": angle_cells(metrics, "good"), "low": angle_cells(metrics, "low"),
            "objective": objective(metrics)}


def plateau(rows):
    """The longest contiguous run of grid values tied at the best objective (`rows` sorted by
    value); equal runs go to the one with the larger values."""
    top = max(r["objective"] for r in rows)
    runs, run = [], []
    for r in sorted(rows, key=lambda r: r["value"]):
        if r["objective"] == top:
            run.append(r)
        elif run:
            runs.append(run)
            run = []
    if run:
        runs.append(run)
    return max(runs, key=lambda run: (len(run), run[-1]["value"]))


def best(rows):
    """The middle of the plateau, rounded up to the grid step."""
    run = plateau(rows)
    middle = (run[0]["value"] + run[-1]["value"]) / 2
    return next(r for r in run if r["value"] >= middle - 1e-9)


def choose(rows, current):
    """(best row, note, plateau ends). When every candidate ties, the data says nothing about this
    key: keep the current value."""
    run = plateau(rows)
    span = (run[0]["value"], run[-1]["value"])
    if len({r["objective"] for r in rows}) == 1:
        return next(r for r in rows if r["value"] == current), "flat on seed 5, current value kept", span
    return best(rows), "", span


def sweep_param(prepared, rules, param, radius=None):
    """Evaluate every grid value of one key; extend the grid once if the plateau reaches its edge."""
    current = get_path(rules, param.path)
    steps = radius if radius is not None and param.name.endswith("threshold_deg") else param.steps
    rows, note = {}, ""
    for attempt in (1, 2):
        for v in grid(param, current, steps * attempt):
            if v not in rows:
                rows[v] = row(v, evaluate(prepared, with_value(rules, param.path, v)))
        chosen, note, span = choose(list(rows.values()), current)
        edge = ((span[0] == min(rows) and span[0] != param.low)
                or (span[1] == max(rows) and span[1] != param.high))
        if not edge or note:
            break
        note = "grid extended once" if attempt == 1 else "plateau still reaches the grid edge after one extension"
    ordered = [rows[v] for v in sorted(rows)]
    return {"param": param, "current": current, "rows": ordered, "chosen": chosen, "note": note,
            "plateau": span, "grid": (min(rows), max(rows))}


def run_sweep(prepared, rules, only=None, radius=None):
    """Sweep each key in turn on the rules chosen so far. Returns (results, final rules)."""
    results = []
    for param in params(rules, only):
        result = sweep_param(prepared, rules, param, radius)
        rules = with_value(rules, param.path, result["chosen"]["value"])
        results.append(result)
    return results, rules


# --- printing the table ---
def cells_text(cells):
    return "  ".join(f"{a} " + (f"{c[0]:.2f}/{c[1]:.2f}/{c[2]}" if c else "none") for a, c in cells.items())


def row_text(r, chosen):
    ok = "ok" if r["objective"][0] else f"short {-r['objective'][1]:.2f}"
    mark = "<" if r is chosen else " "
    return (f"  {r['value']:>7g}  good {cells_text(r['good'])}  minR {r['objective'][2]:.2f} {ok:<10}"
            f" low {cells_text(r['low'])} {mark}")


def sweep_lines(results):
    lines = ["columns: value, then per angle precision/recall/faults on correct takes (good light chooses, low light is shown)"]
    for res in results:
        lines.append(f"== {res['param'].name} (current {res['current']:g}) ==")
        lines += [row_text(r, res["chosen"]) for r in res["rows"]]
        lines.append(f"  chosen {res['chosen']['value']:g}, plateau {res['plateau'][0]:g}..{res['plateau'][1]:g}, "
                     f"grid {res['grid'][0]:g}..{res['grid'][1]:g}" + (f" ({res['note']})" if res["note"] else ""))
    return lines


def change_lines(results):
    lines = ["== chosen values =="]
    for res in results:
        mark = "" if res["chosen"]["value"] == res["current"] else "  changed"
        lines.append(f"  {res['param'].name}: {res['current']:g} -> {res['chosen']['value']:g}"
                     f"  minR {res['chosen']['objective'][2]:.2f}{mark}")
    return lines


def slice_lines(metrics):
    lines = ["== seed 5 slices at the chosen values =="]
    for name, s in metrics["slices"].items():
        lines.append(f"  {name:11s} tp {s['tp']:3d} fp {s['fp']:3d} fn {s['fn']:3d}  P {s['precision']:.2f}  "
                     f"R {s['recall']:.2f}  faults on correct takes {s['faults_on_correct_takes']}")
    return lines


def recall_by_type(prepared, rules):
    """Good-light and low-light recall per fault type and set, so a weak type isn't averaged away."""
    hits = {}
    for p, rec in zip(prepared, records(prepared, rules)):
        for lab in p.take["faults"]:
            key = (lab["type"], p.take["set"], p.take["lighting"])
            hit = any(matches(pred, lab) for pred in rec["predicted"])
            got, total = hits.get(key, (0, 0))
            hits[key] = (got + hit, total + 1)
    return hits


def type_lines(hits):
    lines = ["== recall by fault type, set and lighting =="]
    for (ftype, set_name, light), (got, total) in sorted(hits.items()):
        lines.append(f"  {ftype:14s} {set_name:9s} {light:5s} {got}/{total}")
    return lines


# --- the guard (ADR-0004) ---
def manifest(directory=None):
    path = Path(directory or MISMATCH_DIR) / "manifest.json"
    if not path.is_file():
        raise CalibrateError(f"calibrate: {rel(path)} missing; run the neighbour check or TICKET-015 fixtures")
    return json.loads(path.read_text())["fixtures"]


def stats_row(label, stats_fn, pair):
    stats = stats_fn(pair[2], pair[0], pair[1])
    return {"label": label, **{k: float(stats[k]) for k in GUARD_STATS}}


def guard_populations(prepared, clips, stats_fn, directory=None):
    """Matched takes, mismatch pairs and the matched reference, each a list of stat rows."""
    directory = Path(directory or MISMATCH_DIR)
    expected = sorted({p.take["expected"] for p in prepared})
    matched = [stats_row(p.take["take_id"], stats_fn, (p.exp_m, p.fol_m, p.alignment)) for p in prepared]
    mismatch = []
    for p in prepared:
        for other in expected:
            if other != p.take["expected"]:
                pair = clips.pair(ROOT / other, ROOT / p.take["follower"])
                mismatch.append(stats_row(f"{p.take['take_id']} vs {Path(other).parent.name}", stats_fn, pair))
    reference, excluded = [], []
    for name, entry in sorted(manifest(directory).items()):
        pair = clips.pair(ROOT / entry["against"], directory / name / "skeleton.json")
        r = stats_row(f"{name} vs {Path(entry['against']).parent.name}", stats_fn, pair)
        if entry["population"] == "mismatch":
            mismatch.append(r)
        else:
            reference.append(r)
            excluded.append(f"{name} ({entry['content']}): {entry['reason']}")
    return {"matched": matched, "mismatch": mismatch, "reference": reference, "excluded": excluded}


def rounded(value, up):
    return (math.ceil if up else math.floor)(value * 10000) / 10000


def residual_limit(matched_max, mismatch_min):
    """Refuse above this: the midpoint of the gap, or the matched maximum when the populations meet."""
    if matched_max >= mismatch_min:
        return rounded(matched_max, up=True)
    return min(max(round((matched_max + mismatch_min) / 2, 4), matched_max), mismatch_min)


def timing_limit(matched_min, mismatch_max):
    """Refuse below this: the midpoint of the gap, or the matched minimum when the populations meet."""
    if mismatch_max >= matched_min:
        return rounded(matched_min, up=False)
    return max(min(round((matched_min + mismatch_max) / 2, 4), matched_min), mismatch_max)


def guard_limits(pops):
    m_res = max(r["residual"] for r in pops["matched"])
    x_res = min(r["residual"] for r in pops["mismatch"])
    m_corr = min(r["timing_corr"] for r in pops["matched"])
    x_corr = max(r["timing_corr"] for r in pops["mismatch"])
    return {"max_residual": residual_limit(m_res, x_res), "min_timing_corr": timing_limit(m_corr, x_corr),
            "gap_residual": [m_res, x_res], "gap_timing_corr": [m_corr, x_corr]}


def refused(r, limits):
    return r["residual"] > limits["max_residual"] or r["timing_corr"] < limits["min_timing_corr"]


def guard_overlap(pops, limits):
    return {"matched_refused": [r["label"] for r in pops["matched"] if refused(r, limits)],
            "mismatch_passed": [r["label"] for r in pops["mismatch"] if not refused(r, limits)]}


def population_text(name, rows):
    if not rows:
        return [f"  {name}: none"]
    out = [f"  {name}: {len(rows)} pairs"]
    for k in GUARD_STATS:
        v = [r[k] for r in rows]
        out.append(f"    {k:12s} min {min(v):.4f}  median {statistics.median(v):.4f}  max {max(v):.4f}")
    return out


def guard_lines(pops, limits, overlap):
    lines = ["== movement guard =="]
    for name in ("matched", "mismatch", "reference"):
        lines += population_text(name, pops[name])
    lines += [f"  excluded from the mismatch population: {e}" for e in pops["excluded"]]
    lines += [f"  residual: matched max {limits['gap_residual'][0]:.4f}, mismatch min {limits['gap_residual'][1]:.4f}",
              f"  timing_corr: matched min {limits['gap_timing_corr'][0]:.4f}, mismatch max {limits['gap_timing_corr'][1]:.4f}",
              f"  limits: max_residual {limits['max_residual']:.4f}  min_timing_corr {limits['min_timing_corr']:.4f}"]
    for r in pops["reference"]:
        verdict = "refused" if refused(r, limits) else "passes"
        lines.append(f"  matched reference (never tuned on) {r['label']}: residual {r['residual']:.4f} "
                     f"timing_corr {r['timing_corr']:.4f} span_share {r['span_share']:.4f} {verdict}")
    if overlap["matched_refused"] or overlap["mismatch_passed"]:
        lines.append("  OVERLAP: populations meet; the limits keep every matched take passing")
        lines += [f"    matched take refused: {t}" for t in overlap["matched_refused"]]
        lines += [f"    mismatch pair passes: {t}" for t in overlap["mismatch_passed"]]
    else:
        lines.append("  separation: every matched take passes and every mismatch pair is refused")
    return lines


# --- docs/thresholds.md ---
def expected_commit():
    pinned = json.loads(SOURCES.read_text()).get("pinned", [])
    commits = sorted({p["commit"] for p in pinned if p["to"].startswith("fixtures/input/expected/")})
    return ", ".join(commits) or "not recorded"


def chosen_table(results):
    lines = ["| key | before | plateau | grid | chosen | the sweep row that chose it (good light, minimum recall) |",
             "| --- | ---: | --- | --- | ---: | --- |"]
    for res in results:
        c = res["chosen"]
        note = f" ({res['note']})" if res["note"] else ""
        lines.append(f"| {res['param'].name} | {res['current']:g} | {res['plateau'][0]:g} to {res['plateau'][1]:g} | "
                     f"{res['grid'][0]:g} to {res['grid'][1]:g} | {c['value']:g} | "
                     f"min recall {c['objective'][2]:.2f}; {cells_text(c['good'])}{note} |")
    return lines


def guard_section(pops, limits, overlap):
    if pops is None:
        return ["Not computed in this run (`--guard`)."]
    lines = ["| limit | value | matched | mismatch |", "| --- | ---: | --- | --- |",
             f"| max_residual | {limits['max_residual']:.4f} | max {limits['gap_residual'][0]:.4f} | "
             f"min {limits['gap_residual'][1]:.4f} |",
             f"| min_timing_corr | {limits['min_timing_corr']:.4f} | min {limits['gap_timing_corr'][0]:.4f} | "
             f"max {limits['gap_timing_corr'][1]:.4f} |", ""]
    lines += [f"- Excluded from the mismatch population: {e}" for e in pops["excluded"]]
    bad = overlap["matched_refused"] + overlap["mismatch_passed"]
    lines.append("- Overlap, takes named: " + ("; ".join(
        [f"matched take refused: {t}" for t in overlap["matched_refused"]]
        + [f"mismatch pair passes: {t}" for t in overlap["mismatch_passed"]]) if bad else "none"))
    return lines


def render_thresholds(results, metrics, pops, limits, overlap, hits):
    head = ["# Thresholds and guard limits", "",
            "Written by `python -m part5.calibrate --set fixtures/input/followers --write-thresholds` from the",
            "seed 5 tuning set only. Held-out numbers were not used to tune any value here (ADR-0003).", "",
            f"Expected clips: Part 4 commit {expected_commit()} (`fixtures/input/expected/SOURCE.md`).", "",
            "## Chosen values (seed 5)", ""] + chosen_table(results)
    head += ["", "## Guard limits", ""] + guard_section(pops, limits, overlap)
    head += ["", "## Seed 5 per-slice table at the chosen values", "",
             "| slice | tp | fp | fn | precision | recall | faults on correct takes |",
             "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    head += [f"| {n} | {s['tp']} | {s['fp']} | {s['fn']} | {s['precision']:.2f} | {s['recall']:.2f} | "
             f"{s['faults_on_correct_takes']} |" for n, s in metrics["slices"].items()]
    head += ["", "Recall by fault type, set and lighting:", ""]
    head += [f"- {t} {s} {light}: {g}/{n}" for (t, s, light), (g, n) in sorted(hits.items())]
    return "\n".join(head) + "\n"


def write_thresholds(path, text):
    """Replace everything above the attempts marker, keep the attempts below it."""
    path = Path(path)
    old = path.read_text() if path.is_file() else ""
    kept = old[old.index(ATTEMPTS_MARKER):] if ATTEMPTS_MARKER in old else ATTEMPTS_MARKER + "\n"
    path.write_text(text + "\n" + kept)


# --- the command ---
def calibrate(labels, rules, guard=False, only=None, radius=None, mismatch_dir=None):
    """Run the sweep (and the guard). Returns (stdout lines, thresholds.md text)."""
    clips = Clips()
    prepared = prepare_set(labels, clips)
    stats_fn = movement_stats if guard else None
    results, final = run_sweep(prepared, rules, only, radius)
    metrics = evaluate(prepared, final)
    hits = recall_by_type(prepared, final)
    lines = [f"calibrate: seed {labels['seed']}, {len(prepared)} takes; objective on good light: precision >= "
             f"{MIN_PRECISION} and {MAX_FAULTS_ON_CORRECT} faults on correct takes at every angle, then the highest "
             f"minimum recall; the middle of the plateau tied at the best objective is kept"]
    lines += sweep_lines(results) + change_lines(results) + slice_lines(metrics) + type_lines(hits)
    pops = limits = overlap = None
    if guard:
        pops = guard_populations(prepared, clips, stats_fn, mismatch_dir)
        limits = guard_limits(pops)
        overlap = guard_overlap(pops, limits)
        lines += guard_lines(pops, limits, overlap)
    return lines, render_thresholds(results, metrics, pops, limits, overlap, hits)


def write_score_block(labels, rules_path=RULES_PATH):
    """--score: calibrate the score params (ADR-0007) and write them under "score" in the rules file."""
    rules = load_rules(rules_path)
    block = score_report.calibrate_set(labels, rules)
    Path(rules_path).write_text(json.dumps({**rules, "score": block}, indent=2) + "\n")
    print(f"calibrate: seed {labels['seed']}, wrote the score block to {rel(rules_path)}: "
          + json.dumps({k: v for k, v in block.items() if k != "bands"}))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m part5.calibrate", description=__doc__.splitlines()[0])
    ap.add_argument("--set", default=str(TUNING), help="the tuning set (default fixtures/input/followers)")
    ap.add_argument("--guard", action="store_true", help="also calibrate the movement guard limits")
    ap.add_argument("--write-thresholds", action="store_true", help="write docs/thresholds.md")
    ap.add_argument("--radius", type=int, default=None, help=f"threshold grid half-width in degrees (default {RADIUS_DEG})")
    ap.add_argument("--score", action="store_true",
                    help="calibrate the simon.score.v1 params on this set and write the score block of part5/rules.json")
    ap.add_argument("--only", default="", help="comma-separated keys to sweep (default all)")
    args = ap.parse_args(argv)
    try:
        labels = load_set(args.set)
        if args.score:
            return write_score_block(labels)
        only = {x for x in args.only.split(",") if x}
        lines, doc = calibrate(labels, load_rules(RULES_PATH), args.guard, only, args.radius)
    except CalibrateError as e:
        print(e, file=sys.stderr)
        return 2
    print("\n".join(lines))
    if args.write_thresholds:
        write_thresholds(THRESHOLDS_DOC, doc)
        print(f"calibrate: wrote {rel(THRESHOLDS_DOC)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
