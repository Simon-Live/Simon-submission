"""The threshold sweep and the rule that picks a value from it (docs/specs/calibration.md, ADR-0003, ADR-0017).

Split out of `calibrate.py` (pre-freeze review R1, docs/specs/rep-persistence.md Files); no behaviour moved except the
selection rule below. `calibrate.py` owns the pipeline runs, the guard and `docs/thresholds.md`, and passes this module
the function that evaluates one rules variant.

For each key, one at a time, every grid value is evaluated and the best is the one with the best objective on the
good-light slices of seed 5: first precision >= 0.85 and 0 faults on correct takes at every angle, then the highest
minimum recall across the angles. The values tied at the best objective form a plateau.

Selection (`choose`): the middle of the longest contiguous run of the plateau, rounded up to the grid step (equal runs:
the one with the larger values), so the frozen value has margin on both sides (stakeholder-proxy, 2026-10-29). A key
that is flat (every value ties) keeps its current value, a grid bound included: the flat rule is tried first and wins.
On a re-sweep (`keep_fitting`, attempt 4, stakeholder-proxy 2026-11-01) a current value is kept only when it ties at the
best objective AND lies strictly inside that longest run, not at either end of it; otherwise the key goes to the plateau
middle. A plateau that reaches an end of the grid extends the grid once before any of this is decided (`sweep_param`).
Every sweep also reports `plain`, what the plain rule (the flat rule, else the plateau middle, on the same rows) would
have chosen, so the effect of the re-sweep rule is on the record.
"""
import copy
import math
from dataclasses import dataclass, replace

from .check import MAX_FAULTS_ON_CORRECT, MIN_PRECISION

ANGLES = ("front", "45", "side")
RADIUS_DEG = 6          # threshold grid: this many 1 degree steps each side of the current value
FOOT_MEASURES = ("foot_rotation", "ankle_inversion")   # ADR-0015: swept by --feet only, never by the default sweep
# Recheck N2 (stakeholder-proxy): the floor splits by measure class. The foot measures keep `min_frames_floor` at 32 (held,
# not swept: the ruling fixes it). The body measures have their own floor of the same form (a duration, written as frames
# at 30 fps, at most `floor_share` of a rep), swept only inside the values that keep the 27 retimed seed 5 takes at 24
# of 24 labelled faults found in every one of the six rows (tests/retimed.py; `python scripts/retimed_floor.py KEY` prints
# the range of a key). The same bar holds for the other keys the sweep moves: a key whose plateau reaches a value that loses
# a fault is capped at the top of the values that keep them, measured with the other keys at their shipped values. These
# are those tops: the floor's (4 to 20 on the step-4 grid; 24 loses one fault of the 1.5 s squat at 30 fps),
# `upper_arm_out`'s (a threshold of 12 loses one arms_wider fault of the 5 fps squat) and `min_fraction`'s (0.43 loses one
# of the 5 fps squat). tests/test_retimed.py pins the rows at the shipped rules for every key, and the tops: the value above
# each loses a fault.
RETIMED_TOPS = {"min_frames_floor_body": 20, "upper_arm_out threshold_deg": 11, "min_fraction": 0.38}
PERSISTENCE = (         # key, step, low, high, steps each side
    # ADR-0017: persistence is judged in each rep of the example, which is shorter than the clip, so the floor (a duration,
    # written as frames at 30 fps, that a deviation must hold whatever the rep's length) decides what noise survives in
    # a short rep.
    ("min_frames_floor_body", 4, 4, 120, 6),
    ("min_fraction", 0.05, 0.05, 0.9, 3),
    ("min_run_frames", 1, 1, 30, 3),
    ("min_overlap", 0.1, 0.1, 1.0, 3),
)


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


def params(rules, only=None, capped=True):
    """The keys of the default sweep, in file order, thresholds then persistence. The foot thresholds are not among them
    (ADR-0017): they are TICKET-040's, calibrated by `--feet` against a go/no-go, and attempt 4 holds them. A key in
    `RETIMED_TOPS` has its top as `high` (`capped`; `scripts/retimed_floor.py` asks for the keys as they are)."""
    found = [Param(f"{g} threshold_deg", ("measures", g, "threshold_deg"), 1.0, 1.0, math.inf, RADIUS_DEG)
             for g in rules["measures"] if "threshold_deg" in rules["measures"][g] and g not in FOOT_MEASURES]
    for key, step, low, high, steps in PERSISTENCE:
        path = locate(rules, key)
        if path:
            found.append(Param(key, path, step, low, high, steps))
    if capped:
        found = [replace(p, high=min(p.high, RETIMED_TOPS.get(p.name, math.inf))) for p in found]
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


def is_flat(rows):
    """Does every candidate tie at the same objective? Then the data says nothing about this key."""
    return len({r["objective"] for r in rows}) == 1


def choose(rows, current, keep_fitting=False):
    """(chosen row, note, plateau ends). Three rules, tried in this order:

    1. **Flat** (every candidate ties; stakeholder-proxy, 2026-10-29): the data says nothing about the key, so it keeps
       its current value, wherever that sits on the grid, a bound included. This rule wins over the next one: a flat
       plateau is the whole grid, whose ends are the limits of the search and not drops of the objective, so "strictly
       inside the plateau" has no meaning for it and never moves a flat key to the middle.
    2. **Kept** (only with `keep_fitting`: a re-sweep, ADR-0017, calibration.md "Re-sweeps"; stakeholder-proxy,
       2026-11-01): a current value that ties at the best objective and lies strictly inside the longest contiguous run
       of the plateau, not at either end of it. A key that still fits with margin on both sides is not moved, so a
       re-sweep changes only what the new rules made wrong.
    3. Otherwise the middle of the longest run, rounded up to the grid step: a first calibration or `--feet` (no
       `keep_fitting`), a value that is worse, one at the end of its run or on a shorter tied run."""
    run = plateau(rows)
    span = (run[0]["value"], run[-1]["value"])
    if is_flat(rows):
        return next(r for r in rows if r["value"] == current), "flat on seed 5, current value kept", span
    at_current = next((r for r in rows if r["value"] == current), None)
    if keep_fitting and at_current is not None and at_current in run and span[0] < current < span[1]:
        return at_current, "current value ties at the best objective inside its plateau, kept", span
    return best(rows), "", span


def reaches_edge(rows, span, param):
    """Does the plateau reach an end of the grid that is not a bound of the key itself (`param.low`, `param.high`)? Then
    values beyond it are untried and the plateau's end is only where the search stopped."""
    return (span[0] == min(rows) and span[0] != param.low) or (span[1] == max(rows) and span[1] != param.high)


def sweep_param(prepared, rules, param, evaluate_fn, radius=None, keep_fitting=False):
    """Evaluate every grid value of one key; extend the grid once if the plateau reaches its edge, and only then choose.
    `evaluate_fn(prepared, rules)` returns the metrics of one rules variant. `keep_fitting` is `choose`'s.

    The extension comes before the choice, whichever way the choice goes (a current value that would be kept included),
    so the plateau ends, and with them "strictly inside", are not cut short by a grid that stopped too early. A flat grid
    is not extended: nothing on it moves the objective, the key keeps its current value, and more of the same would only
    cost evaluations. The result carries `plain`, the value the plain rule picks from the same rows (the flat rule, else
    the plateau middle, no `keep_fitting`)."""
    current = get_path(rules, param.path)
    steps = radius if radius is not None and param.name.endswith("threshold_deg") else param.steps
    rows = {}
    for attempt in (1, 2):
        for v in grid(param, current, steps * attempt):
            if v not in rows:
                rows[v] = row(v, evaluate_fn(prepared, with_value(rules, param.path, v)))
        found = list(rows.values())
        run = plateau(found)
        edge = reaches_edge(rows, (run[0]["value"], run[-1]["value"]), param)
        if attempt == 2 or is_flat(found) or not edge:
            break
    ordered = [rows[v] for v in sorted(rows)]
    chosen, note, span = choose(ordered, current, keep_fitting)
    notes = [note] if note else []
    if attempt == 2:
        notes.insert(0, "plateau still reaches the grid edge after one extension" if edge else "grid extended once")
    return {"param": param, "current": current, "rows": ordered, "chosen": chosen, "note": "; ".join(notes),
            "plateau": span, "grid": (min(rows), max(rows)), "plain": choose(ordered, current)[0]["value"]}


def run_sweep(prepared, rules, evaluate_fn, only=None, radius=None, keep_fitting=False):
    """Sweep each key in turn on the rules chosen so far. Returns (results, final rules)."""
    results = []
    for param in params(rules, only):
        result = sweep_param(prepared, rules, param, evaluate_fn, radius, keep_fitting)
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
                     f"grid {res['grid'][0]:g}..{res['grid'][1]:g}, plain rule {res['plain']:g}"
                     + (f" ({res['note']})" if res["note"] else ""))
    return lines


def change_lines(results):
    lines = ["== chosen values =="]
    for res in results:
        mark = "" if res["chosen"]["value"] == res["current"] else "  changed"
        lines.append(f"  {res['param'].name}: {res['current']:g} -> {res['chosen']['value']:g}"
                     f"  minR {res['chosen']['objective'][2]:.2f}  plain rule {res['plain']:g}{mark}")
    return lines
