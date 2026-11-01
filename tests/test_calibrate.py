"""`python -m part5.calibrate` (docs/specs/calibration.md): the seed 5 sweep, the guard calibration and
docs/thresholds.md. Small subsets of the committed seed 5 takes keep these fast; no held-out seed is read."""
import json
import re
import shutil
from pathlib import Path

import pytest

from part5 import calibrate, sweep
from part5.detect import load_rules

ROOT = Path(__file__).resolve().parent.parent
LABELS = json.loads((ROOT / "fixtures/input/followers/labels.json").read_text())


KEEP = ("_00_correct", "_01_correct", "_03_foot_out", "_07_knee_caving")
SMALL_KEEP = KEEP[:1] + KEEP[2:]


def subset(tmp_path, keep=KEEP, prefixes=("exercise_front_good_", "dance_front_good_"), seed=5):
    """A tuning-set labels.json holding some takes of each prefix (paths stay the repo's)."""
    takes = [t for p in prefixes for t in LABELS["takes"] if t["take_id"].startswith(p) and any(k in t["take_id"] for k in keep)]
    d = tmp_path / "set"
    d.mkdir(exist_ok=True)
    (d / "labels.json").write_text(json.dumps({**LABELS, "seed": seed, "takes": takes}))
    return d


def run(capsys, *args):
    code = calibrate.main(list(args))
    out, err = capsys.readouterr()
    return code, out, err


# ----------------------------------------------------------------- AC-T01
@pytest.mark.parametrize("seed", [29, 31, 37, 6])
def test_ac_t01_refuses_a_set_that_is_not_seed_5(tmp_path, capsys, seed):
    code, out, err = run(capsys, "--set", str(subset(tmp_path, seed=seed)))
    assert code == 2 and out == ""
    assert err.strip() == f"calibrate: tuning reads seed 5 only (got {seed})"


def test_ac_t01_a_missing_set_exits_2(tmp_path, capsys):
    code, out, err = run(capsys, "--set", str(tmp_path / "nothing"))
    assert code == 2 and "labels.json missing" in err


def test_the_committed_tuning_set_is_seed_5():
    assert calibrate.load_set(calibrate.TUNING)["seed"] == calibrate.TUNING_SEED == 5


# ----------------------------------------------------------------- the objective and the grid
def cells(**by_angle):
    return {"slices": {f"good/{a}": {"precision": p, "recall": r, "faults_on_correct_takes": f}
                       for a, (p, r, f) in by_angle.items()}}


def test_grid_is_one_degree_steps_around_the_current_value():
    p = sweep.Param("foot_out threshold_deg", ("measures", "foot_out", "threshold_deg"), 1.0, 1.0, float("inf"), 6)
    assert sweep.grid(p, 6.0, 6) == [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 11.0, 12.0]
    assert sweep.grid(p, 9.0, 2) == [7.0, 8.0, 9.0, 10.0, 11.0]


def test_objective_is_precision_and_correct_takes_first_then_the_lowest_recall_across_angles():
    ok_low = sweep.objective(cells(front=(0.9, 0.7, 0), **{"45": (0.9, 0.9, 0)}, side=(0.9, 0.95, 0)))
    ok_high = sweep.objective(cells(front=(0.9, 0.8, 0), **{"45": (0.9, 0.8, 0)}, side=(0.9, 0.8, 0)))
    low_precision = sweep.objective(cells(front=(0.84, 1.0, 0), **{"45": (1.0, 1.0, 0)}, side=(1.0, 1.0, 0)))
    wrong_on_correct = sweep.objective(cells(front=(1.0, 1.0, 1), **{"45": (1.0, 1.0, 0)}, side=(1.0, 1.0, 0)))
    assert ok_low == (True, 0, 0.7) and ok_high == (True, 0, 0.8)
    assert ok_high > ok_low > low_precision and ok_low > wrong_on_correct
    assert low_precision[0] is False and wrong_on_correct[0] is False
    assert low_precision > wrong_on_correct  # 0.01 short beats a whole fault on a correct take


def plateau_rows(best_values, worse_values=()):
    rows = [{"value": float(v), "objective": (True, 0, 0.8)} for v in best_values]
    return rows + [{"value": float(v), "objective": (True, 0, 0.7)} for v in worse_values]


def test_the_middle_of_the_plateau_is_kept_not_its_edge():
    rows = plateau_rows([9, 10, 11, 12], worse_values=[8, 13, 14])
    assert sweep.best(rows)["value"] == 11.0  # middle 10.5, rounded up to the grid step
    assert sweep.best(plateau_rows([4, 5, 6], [3, 7]))["value"] == 5.0


def test_a_split_plateau_uses_its_longest_run_and_equal_runs_go_to_the_larger_values():
    longest = plateau_rows([3, 4, 8, 9, 10, 11], worse_values=[5, 6, 7])
    assert [r["value"] for r in sweep.plateau(longest)] == [8.0, 9.0, 10.0, 11.0]
    equal = plateau_rows([3, 4, 8, 9], worse_values=[5, 6, 7])
    assert sweep.best(equal)["value"] == 9.0


def test_a_flat_sweep_keeps_the_current_value():
    rows = [{"value": v, "objective": (True, 0, 0.8)} for v in (5.0, 6.0, 7.0)]
    chosen, note, span = sweep.choose(rows, 6.0)
    assert chosen["value"] == 6.0 and "flat" in note and span == (5.0, 7.0)


def test_a_best_value_on_the_grid_edge_extends_the_grid_once_and_says_so():
    rules = {"measures": {"foot_out": {"threshold_deg": 6.0}}}
    p = sweep.params(rules)[0]
    res = sweep.sweep_param(None, rules, p, lambda prepared, rules: cells(
        front=(1.0, min(1.0, rules["measures"]["foot_out"]["threshold_deg"] / 20), 0)), radius=3)
    values = [r["value"] for r in res["rows"]]
    assert values == [float(v) for v in range(1, 13)]  # 3..9 first, then 1..12 after one extension
    assert res["chosen"]["value"] == 12.0 and "still reaches the grid edge" in res["note"]
    assert res["plateau"] == (12.0, 12.0) and res["grid"] == (1.0, 12.0)


def test_a_best_value_inside_the_grid_is_not_extended():
    rules = {"measures": {"foot_out": {"threshold_deg": 6.0}}}
    res = sweep.sweep_param(None, rules, sweep.params(rules)[0], lambda prepared, rules: cells(
        front=(1.0, 1.0 - abs(rules["measures"]["foot_out"]["threshold_deg"] - 7.0) / 10, 0)), radius=3)
    assert [r["value"] for r in res["rows"]] == [3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0]
    assert res["chosen"]["value"] == 7.0 and res["note"] == ""


# ----------------------------------------------------------------- reading the rules generically
def test_params_cover_every_body_measure_and_the_persistence_keys_that_exist_and_not_the_foot_thresholds():
    rules = load_rules()
    names = [p.name for p in sweep.params(rules)]
    body = [g for g in rules["measures"] if g not in calibrate.FOOT_MEASURES]
    assert names[:len(body)] == [f"{g} threshold_deg" for g in body]
    assert names[len(body):] == ["min_frames_floor_body", "min_fraction", "min_run_frames", "min_overlap"]   # the foot floor is held
    assert not [n for n in names if n == "min_frames_floor"]
    assert not [n for n in names if n.split()[0] in calibrate.FOOT_MEASURES]   # `--feet` owns them (TICKET-040)
    assert calibrate.FOOT_MEASURES == ("foot_rotation", "ankle_inversion")
    top = {"default": {"threshold_deg": 10.0, "min_fraction": 0.2}, "measures": {"a": {"threshold_deg": 5.0}},
           "min_run_frames": 4, "min_overlap": 0.5}
    found = {p.name: p.path for p in sweep.params(top)}
    assert found == {"a threshold_deg": ("measures", "a", "threshold_deg"), "min_fraction": ("default", "min_fraction"),
                     "min_run_frames": ("min_run_frames",), "min_overlap": ("min_overlap",)}
    assert [p.name for p in sweep.params(top, only={"a", "min_overlap"})] == ["a threshold_deg", "min_overlap"]
    assert sweep.locate({"default": {}, "measures": {}}, "min_overlap") is None


def test_with_value_leaves_the_original_rules_alone():
    rules = load_rules()
    changed = sweep.with_value(rules, ("measures", "foot_out", "threshold_deg"), 99.0)
    assert changed["measures"]["foot_out"]["threshold_deg"] == 99.0
    assert rules["measures"]["foot_out"]["threshold_deg"] != 99.0


# ----------------------------------------------------------------- the sweep on real takes
SWEEP_ARGS = ("--only", "foot_out,min_fraction", "--radius", "1", "--workers", "1")


def test_the_sweep_prints_a_table_the_chosen_values_and_recall_by_type(tmp_path, capsys):
    code, out, err = run(capsys, "--set", str(subset(tmp_path)), *SWEEP_ARGS)
    assert code == 0 and err == ""
    assert out.startswith("calibrate: seed 5, 8 takes; objective on good light")
    assert "== foot_out threshold_deg (current 6) ==" in out and "== min_fraction (current " in out
    assert "== chosen values ==" in out and "== seed 5 slices at the chosen values ==" in out
    assert "== recall by fault type, set and lighting ==" in out and "knee_caving" in out
    assert out.count("<") == 2  # one chosen row per key


def test_ac_t05_two_sweeps_print_the_same_table(tmp_path, capsys):
    d = str(subset(tmp_path))
    first = run(capsys, "--set", d, *SWEEP_ARGS)[1]
    second = run(capsys, "--set", d, *SWEEP_ARGS)[1]
    assert first == second and "chosen" in first


def test_the_sweep_does_not_touch_rules_json(tmp_path, capsys):
    before = (ROOT / "part5/rules.json").read_bytes()
    run(capsys, "--set", str(subset(tmp_path)), *SWEEP_ARGS)
    assert (ROOT / "part5/rules.json").read_bytes() == before


# ----------------------------------------------------------------- attempt 4: the sweep runs the pipeline (ADR-0017)
def test_ac_cal_01_the_sweep_runs_every_take_through_the_pipeline_the_foot_takes_and_their_labels_included(tmp_path, capsys):
    d = subset(tmp_path, keep=("_00_correct", "_09_foot_turned_out"), prefixes=("dance_front_good_",))
    code, out, err = run(capsys, "--set", str(d), "--only", "min_frames_floor_body", "--workers", "1")
    assert code == 0 and err == "" and out.startswith("calibrate: seed 5, 2 takes;")
    assert "foot_turned_out dance     good  1/1" in out        # the foot label is in the recall table, found rep by rep
    assert "== min_frames_floor_body (current 8) ==" in out


def test_ac_cal_01_the_sweep_scores_what_the_pipeline_reports(tmp_path):
    """`evaluate` is the pipeline's faults scored against the labels: the dance take with a planted foot fault, run the
    way `make check-5` runs it, is a true positive; the correct one a clean take."""
    d = calibrate.load_set(subset(tmp_path, keep=("_00_correct", "_09_foot_turned_out"), prefixes=("dance_front_good_",)))
    takes = calibrate.prepare_feet(d, required=False)
    m = calibrate.evaluate(takes, load_rules())
    s = m["slices"]["good/front"]
    assert (s["tp"], s["fp"], s["fn"], s["takes"], s["correct_takes"], s["faults_on_correct_takes"]) == (1, 0, 0, 2, 1, 0)


def test_the_runner_caches_a_rules_variant_and_tells_two_variants_apart_by_all_the_rules(tmp_path):
    d = calibrate.load_set(subset(tmp_path, keep=("_00_correct",), prefixes=("dance_front_good_",)))
    takes, calls = calibrate.prepare_feet(d, required=False), []

    def counting(task):
        calls.append(task[3]["default"]["min_frames_floor"])
        return []
    runs = calibrate.PipelineRuns(1, counting)
    base = load_rules()
    runs.faults(takes, base), runs.faults(takes, base)
    other = sweep.with_value(base, ("default", "min_frames_floor"), 20)
    runs.faults(takes, other)
    assert calls == [32, 20]


def test_a_take_that_names_no_foot_file_is_analysed_without_feet_but_a_named_missing_file_is_an_error(tmp_path):
    labels = {"seed": 5, "takes": [{**LABELS["takes"][0], "expected_feet": None, "follower_feet": None}]}
    [t] = calibrate.prepare_feet(labels, required=False)
    assert t.feet == {}
    with pytest.raises(calibrate.CalibrateError, match="has no expected_feet file"):
        calibrate.prepare_feet({"seed": 5, "takes": [{**LABELS["takes"][0], "expected_feet": "nowhere.json"}]},
                               required=False)


def test_a_key_that_still_has_the_best_objective_keeps_its_value_in_a_re_sweep_and_not_in_a_first_calibration():
    rows = plateau_rows([28, 32, 36], worse_values=[24, 40])
    kept, note, span = sweep.choose(rows, 32.0, keep_fitting=True)
    assert kept["value"] == 32.0 and "inside its plateau" in note and span == (28.0, 36.0)
    assert sweep.choose(rows, 32.0)[0]["value"] == 32.0            # the middle is where a first calibration puts it too
    off_middle = plateau_rows([24, 28, 32, 36, 40], worse_values=[20, 44])
    assert sweep.choose(off_middle, 28.0, keep_fitting=True)[0]["value"] == 28.0    # inside, not at the middle: kept
    assert sweep.choose(off_middle, 28.0)[0]["value"] == 32.0                       # a first calibration recentres it
    moved = sweep.choose(rows, 24.0, keep_fitting=True)            # 24 is worse: it moves to the middle
    assert moved[0]["value"] == 32.0 and moved[1] == ""


def test_a_current_value_at_either_end_of_its_plateau_goes_to_the_middle_in_a_re_sweep():
    """Stakeholder-proxy ruling 2026-11-01: a tied current value is kept only strictly inside the longest run."""
    rows = plateau_rows([28, 32, 36], worse_values=[24, 40])
    for end in (28.0, 36.0):
        chosen, note, span = sweep.choose(rows, end, keep_fitting=True)
        assert chosen["value"] == 32.0 and note == "" and span == (28.0, 36.0), end
    two = plateau_rows([30, 31], worse_values=[29, 32])           # a run of two has no inside: the plateau middle
    assert sweep.choose(two, 30.0, keep_fitting=True)[0]["value"] == 31.0
    one = plateau_rows([30], worse_values=[29, 31])
    assert sweep.choose(one, 30.0, keep_fitting=True)[0]["value"] == 30.0   # the middle of a single value is itself


def test_a_current_value_on_a_shorter_tied_run_goes_to_the_middle_of_the_longest_one():
    rows = plateau_rows([3, 4, 8, 9, 10, 11, 12], worse_values=[5, 6, 7])    # two tied runs: 3..4 and 8..12
    chosen, note, span = sweep.choose(rows, 4.0, keep_fitting=True)          # 4 ties at the best but is on the short run
    assert chosen["value"] == 10.0 and note == "" and span == (8.0, 12.0)
    assert sweep.choose(rows, 9.0, keep_fitting=True)[0]["value"] == 9.0     # strictly inside the long run: kept
    assert sweep.choose(rows, 8.0, keep_fitting=True)[0]["value"] == 10.0    # at its start: moved


FLOOR = sweep.Param("min_frames_floor_body", ("default", "min_frames_floor_body"), 4, 4, 120, 6)


def floor_sweep(current, good, **kw):
    """`sweep_param` of the body floor from `current`, with `good(value)` saying whether a value has the best recall."""
    return sweep.sweep_param(None, {"default": {"min_frames_floor_body": current}}, kw.pop("param", FLOOR),
                             lambda prepared, rules: cells(front=(1.0, 1.0 if good(rules["default"]["min_frames_floor_body"]) else 0.5, 0)),
                             keep_fitting=True, **kw)


def test_the_sweep_reports_what_the_plain_rule_would_choose():
    res = floor_sweep(28, lambda v: 24 <= v <= 32)
    assert res["chosen"]["value"] == 28.0 and res["plain"] == 28.0         # 28 is the middle of 24..32: kept and equal
    at_end = floor_sweep(24, lambda v: 24 <= v <= 32)
    assert at_end["chosen"]["value"] == 28.0 and at_end["plain"] == 28.0
    text = "\n".join(sweep.sweep_lines([at_end]) + sweep.change_lines([at_end]))
    assert "plain rule 28" in text and "plain rule 28" in text.splitlines()[-1]


def test_r2_a_plateau_at_the_grid_edge_extends_the_grid_once_before_a_value_is_kept():
    """Recheck residual 2: the extension used to be skipped whenever the current value was kept, so the plateau ends were the
    ends of a grid that stopped too early. Now 32 is evaluated on the grid 8..56 (28 and up tie), the plateau reaches 56,
    the grid is extended once to 4..80, and the plateau is 28..80: 32 is strictly inside it and is kept, on the longer grid."""
    res = floor_sweep(32, lambda v: v >= 28)
    assert res["chosen"]["value"] == 32.0 and "kept" in res["note"] and "grid extended once" not in res["note"]
    assert res["grid"] == (4.0, 80.0) and res["plateau"] == (28.0, 80.0)
    assert "plateau still reaches the grid edge after one extension" in res["note"]      # 80 is not a bound of the key
    assert res["plain"] == 56.0        # (28 + 80) / 2 = 54, rounded up to the grid step: the plain rule would move it


def test_r2_the_extension_shows_where_a_plateau_that_reached_the_edge_really_ends():
    """The first grid 4..52 ties from 28 up to its edge; the extension to 4..76 shows the plateau ends at 60. The plateau
    ends are the extended grid's, not the first grid's edge, and the middle is taken of them (28 is at the start of the run
    and moves to 44)."""
    res = floor_sweep(28, lambda v: 28 <= v <= 60)
    assert res["grid"] == (4.0, 76.0) and res["plateau"] == (28.0, 60.0) and res["chosen"]["value"] == 44.0
    assert res["note"] == "grid extended once"                       # and the plateau no longer reaches the edge


def test_r1_the_plain_rule_is_the_flat_rule_and_then_the_middle_after_the_same_extension():
    """Recheck residual 1: the plain column was the middle of the tied run even for a flat key (min_overlap 0.4 where the
    plain rule keeps the flat key at 0.3), and was computed on the grid before the extension (min_fraction 0.33 where the
    extended plateau runs 0.08 to 0.43 and its middle is 0.28)."""
    overlap = sweep.Param("min_overlap", ("default", "min_overlap"), 0.1, 0.1, 1.0, 3)
    flat = sweep.sweep_param(None, {"default": {"min_overlap": 0.3}}, overlap, lambda p, r: cells(front=(1.0, 1.0, 0)),
                             keep_fitting=True)
    assert flat["grid"] == (0.1, 0.6) and flat["chosen"]["value"] == 0.3 and flat["plain"] == 0.3
    assert sweep.best(flat["rows"])["value"] == 0.4        # the old column: the middle of 0.1..0.6, which the rule never uses
    fraction = sweep.Param("min_fraction", ("default", "min_fraction"), 0.05, 0.05, 0.9, 3)
    res = sweep.sweep_param(None, {"default": {"min_fraction": 0.38}}, fraction, lambda p, r: cells(
        front=(1.0, 1.0 if r["default"]["min_fraction"] <= 0.43 else 0.5, 0)), keep_fitting=True)
    assert res["grid"][0] == 0.08 and res["plateau"] == (0.08, 0.43)     # 0.23 to 0.53 first, 0.08 to 0.68 after one extension
    assert res["chosen"]["value"] == 0.38 and res["plain"] == 0.28      # (0.08 + 0.43) / 2 = 0.255, up to the grid step


def test_r3_a_flat_key_whose_current_value_is_a_grid_bound_is_kept_whichever_rule_would_move_it():
    """Recheck residual 3: a flat key keeps its current value first (2026-10-29), also at a bound of the grid, where the
    re-sweep rule alone ("strictly inside the longest run") would move it to the middle. The flat rule wins; the re-sweep
    rule applies to a key that is not flat."""
    lowest = sweep.Param("min_run_frames", ("default", "min_run_frames"), 1, 1, 30, 3)
    for current, expected in ((1, 1.0), (4, 4.0), (30, 30.0)):
        res = sweep.sweep_param(None, {"default": {"min_run_frames": current}}, lowest, lambda p, r: cells(front=(1.0, 1.0, 0)),
                                keep_fitting=True)
        assert res["chosen"]["value"] == expected and "flat" in res["note"], current
        assert res["grid"][0] == max(1.0, current - 3) and res["grid"][1] == min(30.0, current + 3)   # not extended: flat
    rows = plateau_rows([5, 6, 7])
    assert sweep.choose(rows, 5.0, keep_fitting=True)[0]["value"] == 5.0            # flat: kept at the start of the grid
    assert sweep.choose(rows, 7.0, keep_fitting=True)[0]["value"] == 7.0            # and at its end
    not_flat = plateau_rows([5, 6, 7], worse_values=[4, 8])
    assert sweep.choose(not_flat, 5.0, keep_fitting=True)[0]["value"] == 6.0        # the same run, not flat: moved to the middle
    assert sweep.choose(not_flat, 6.0, keep_fitting=True)[0]["value"] == 6.0


def test_a_flat_grid_is_not_extended_and_a_bound_of_the_key_is_not_an_edge():
    flat = floor_sweep(32, lambda v: True)
    assert flat["grid"] == (8.0, 56.0) and flat["note"] == "flat on seed 5, current value kept"
    capped = sweep.Param("min_frames_floor_body", ("default", "min_frames_floor_body"), 4, 4, 20, 6)
    res = floor_sweep(8, lambda v: True, param=capped)
    assert res["grid"] == (4.0, 20.0) and res["chosen"]["value"] == 8.0             # the key's own bounds clip the grid


def test_n2_a_key_with_a_retimed_top_is_clipped_to_it_and_the_plateau_at_the_top_is_not_an_edge():
    rules = {"default": {"min_frames_floor_body": 8, "min_fraction": 0.38}, "measures": {"upper_arm_out": {"threshold_deg": 10.0}}}
    named = {p.name: p for p in sweep.params(rules)}
    assert named["min_frames_floor_body"].high == 20 and named["upper_arm_out threshold_deg"].high == 11
    assert named["min_fraction"].high == 0.38
    assert {p.name: p.high for p in sweep.params(rules, capped=False)}["upper_arm_out threshold_deg"] == float("inf")
    res = sweep.sweep_param(None, rules, named["upper_arm_out threshold_deg"], lambda p, r: cells(
        front=(1.0, 1.0 if r["measures"]["upper_arm_out"]["threshold_deg"] >= 10 else 0.5, 0)), keep_fitting=True)
    assert res["grid"][1] == 11.0 and res["plateau"] == (10.0, 11.0) and res["chosen"]["value"] == 11.0   # not extended past 11


# ----------------------------------------------------------------- the guard
def test_guard_prints_both_populations_the_limits_and_the_single_exclusion(tmp_path, capsys, monkeypatch):
    code, out, err = run(capsys, "--set", str(subset(tmp_path, SMALL_KEEP)), "--guard", "--only", "foot_out", "--radius", "1")
    assert code == 0, err
    assert "== movement guard ==" in out and "matched: 6 pairs" in out
    assert "mismatch: 9 pairs" in out  # 6 exercise vs dance and dance vs exercise, plus Part 2 class, dance, stretch
    for stat in calibrate.GUARD_STATS:
        assert stat in out
    assert "excluded from the mismatch population: part2-single (provisional barbell back squat" in out
    assert "matched reference (never tuned on) part2-single vs part3-squat" in out
    assert "limits: max_residual" in out and ("separation:" in out or "OVERLAP:" in out)


def test_ac_t04_the_limits_sit_at_the_midpoint_of_the_gap():
    pops = {"matched": [{"label": "m1", "residual": 0.4, "timing_corr": 0.95, "span_share": 1.0},
                        {"label": "m2", "residual": 0.5, "timing_corr": 0.90, "span_share": 1.0}],
            "mismatch": [{"label": "x1", "residual": 0.7, "timing_corr": 0.30, "span_share": 1.0},
                         {"label": "x2", "residual": 0.9, "timing_corr": 0.10, "span_share": 1.0}]}
    limits = calibrate.guard_limits(pops)
    assert limits["max_residual"] == 0.6 and limits["min_timing_corr"] == 0.6
    assert calibrate.guard_overlap(pops, limits) == {"matched_refused": [], "mismatch_passed": []}


def test_ac_t04_with_overlap_every_matched_take_still_passes_and_the_overlap_is_named():
    pops = {"matched": [{"label": "m1", "residual": 0.4, "timing_corr": 0.95, "span_share": 1.0},
                        {"label": "m2", "residual": 0.66, "timing_corr": 0.80, "span_share": 1.0}],
            "mismatch": [{"label": "x1", "residual": 0.6, "timing_corr": 0.85, "span_share": 1.0},
                         {"label": "x2", "residual": 0.9, "timing_corr": 0.10, "span_share": 1.0}]}
    limits = calibrate.guard_limits(pops)
    assert limits["max_residual"] == 0.66 and limits["min_timing_corr"] == 0.8  # the matched edge, not the midpoint
    overlap = calibrate.guard_overlap(pops, limits)
    assert overlap["matched_refused"] == [] and overlap["mismatch_passed"] == ["x1"]
    assert "OVERLAP" in "\n".join(calibrate.guard_lines({**pops, "reference": [], "excluded": []}, limits, overlap))


def test_the_limit_rounds_so_that_a_matched_edge_still_passes():
    assert calibrate.residual_limit(0.52314, 0.50) == 0.5232 > 0.52314
    assert calibrate.timing_limit(0.91106, 0.95) == 0.9110 < 0.91106


def test_a_missing_mismatch_manifest_exits_2_with_the_plain_message(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(calibrate, "MISMATCH_DIR", tmp_path / "no-mismatch")
    code, out, err = run(capsys, "--set", str(subset(tmp_path, KEEP[:2])), "--guard", "--only", "foot_out", "--radius", "1")
    assert code == 2 and "manifest.json missing; run the neighbour check or TICKET-015 fixtures" in err


def test_a_missing_mismatch_skeleton_exits_2_naming_the_file(tmp_path, capsys, monkeypatch):
    copy = tmp_path / "mismatch"
    shutil.copytree(ROOT / "fixtures/input/mismatch", copy)
    (copy / "part2-class" / "skeleton.json").unlink()
    monkeypatch.setattr(calibrate, "MISMATCH_DIR", copy)
    code, out, err = run(capsys, "--set", str(subset(tmp_path, KEEP[:2])), "--guard", "--only", "foot_out", "--radius", "1")
    assert code == 2 and "part2-class/skeleton.json missing; run the neighbour check or TICKET-015 fixtures" in err


def test_single_joins_the_mismatch_population_when_the_manifest_says_it_is_a_stretch(tmp_path, capsys, monkeypatch):
    copy = tmp_path / "mismatch"
    shutil.copytree(ROOT / "fixtures/input/mismatch", copy)
    doc = json.loads((copy / "manifest.json").read_text())
    doc["fixtures"]["part2-single"]["population"] = "mismatch"
    (copy / "manifest.json").write_text(json.dumps(doc))
    monkeypatch.setattr(calibrate, "MISMATCH_DIR", copy)
    code, out, err = run(capsys, "--set", str(subset(tmp_path, SMALL_KEEP)), "--guard", "--only", "foot_out", "--radius", "1")
    assert code == 0, err
    assert "mismatch: 10 pairs" in out and "excluded from the mismatch population" not in out


# ----------------------------------------------------------------- docs/thresholds.md
def test_write_thresholds_replaces_the_head_and_keeps_every_attempt(tmp_path):
    doc = tmp_path / "thresholds.md"
    attempts = (f"{calibrate.ATTEMPTS_MARKER}\n## Held-out attempts\n\n### Attempt 1: seed 29\n"
                "Freeze commit: `abc1234`\nrules_sha256: `" + "c" * 64 + "`\nAPPROACH: red result stays\n")
    doc.write_text("# old head\n\n" + attempts)
    calibrate.write_thresholds(doc, "# new head\n")
    text = doc.read_text()
    assert text.startswith("# new head\n") and "# old head" not in text
    assert text.endswith(attempts) and "red result stays" in text


def test_write_thresholds_creates_the_file_with_an_attempts_marker(tmp_path):
    doc = tmp_path / "t.md"
    calibrate.write_thresholds(doc, "# head\n")
    assert doc.read_text().startswith("# head\n") and calibrate.ATTEMPTS_MARKER in doc.read_text()


def test_write_thresholds_flag_writes_the_chosen_values_the_guard_and_the_statement(tmp_path, capsys, monkeypatch):
    doc = tmp_path / "thresholds.md"
    monkeypatch.setattr(calibrate, "THRESHOLDS_DOC", doc)
    code, out, err = run(capsys, "--set", str(subset(tmp_path, SMALL_KEEP)), "--guard", "--write-thresholds",
                         "--only", "foot_out", "--radius", "1")
    text = doc.read_text()
    assert code == 0 and "wrote" in err
    assert "Held-out numbers were not used to tune any value here" in text
    assert "| foot_out threshold_deg | 6 |" in text and "## Guard limits" in text and "| max_residual |" in text
    assert "Part 4 commit dc3d9f2e70a0d3e95efb60bea1e5ab7fc307d284" in text
    assert "part2-single" in text and calibrate.ATTEMPTS_MARKER in text


def test_r11_the_generated_text_takes_the_floor_from_the_data_and_hard_codes_no_history(tmp_path, capsys, monkeypatch):
    """Pre-freeze review R11: the generated head said "it was 8 until attempt 4" whatever the rules and the sweep were. It
    now describes the floor and quotes its value from the sweep when the floor was swept."""
    doc = tmp_path / "thresholds.md"
    monkeypatch.setattr(calibrate, "THRESHOLDS_DOC", doc)
    run(capsys, "--set", str(subset(tmp_path, SMALL_KEEP)), "--write-thresholds", "--only", "min_frames_floor_body", "--workers", "1")
    swept = doc.read_text()
    assert "until attempt 4" not in swept and "it was 8" not in swept and "moved it to" not in swept
    assert "A persistence floor is a duration, written as frames at 30 fps" in swept
    value = re.search(r"It is (\d+) for the body measures here, (\d\.\d\d) s\.", swept)
    assert value and float(value.group(2)) == round(int(value.group(1)) / 30, 2)       # the sweep's value, as a time
    assert "The foot measures keep `min_frames_floor` 32 (1.07 s)." in swept           # held, from the rules
    assert "| min_frames_floor_body | 8 | " in swept and "| plain rule |" in swept and "plain plateau middle" not in swept
    assert "foot floor min_frames_floor 32" in swept       # in the held-not-swept line beside the foot thresholds
    run(capsys, "--set", str(subset(tmp_path, SMALL_KEEP)), "--write-thresholds", "--only", "foot_out", "--radius", "1", "--workers", "1")
    head = doc.read_text().split("Expected clips")[0]
    assert "is a duration, written as frames at 30 fps" in head and "for the body measures here" not in head   # not swept: no value quoted


def test_the_committed_skeleton_has_the_sections_and_the_attempts_marker():
    text = (ROOT / "docs/thresholds.md").read_text()
    for heading in ("## Chosen values (seed 5)", "## Guard limits", "## Seed 5 per-slice table at the chosen values",
                    "## Held-out attempts"):
        assert heading in text
    assert calibrate.ATTEMPTS_MARKER in text and "ADR-0003" in text
    assert chr(0x2014) not in text and chr(0x2013) not in text


# ----------------------------------------------------------------- the mismatch fixtures
def test_the_mismatch_fixtures_and_their_provenance_are_committed():
    base = ROOT / "fixtures/input/mismatch"
    manifest = json.loads((base / "manifest.json").read_text())["fixtures"]
    assert sorted(manifest) == ["part2-class", "part2-dance", "part2-single", "part2-stretch"]
    for name, entry in manifest.items():
        assert (base / name / "skeleton.json").is_file() and (ROOT / entry["against"]).is_file()
    assert manifest["part2-single"]["population"] == "matched_reference"
    assert manifest["part2-class"]["population"] == manifest["part2-dance"]["population"] == "mismatch"
    source = (base / "SOURCE.md").read_text()
    for needle in ("9c4f82b62e6a3df8203c1e8060f7592d4b449b91", "65a5aad69010bc8d84b1d7cb5b4f2e5eecf2e265",
                   "python3 -m part3 run", "--view part5", "433ae2ed"):
        assert needle in source


def test_the_expected_clips_are_pinned_to_the_part_4_commit_in_sources():
    sources = json.loads((ROOT / "contracts/sources.json").read_text())
    pinned = {p["to"]: p["commit"] for p in sources["pinned"]}
    commit = "dc3d9f2e70a0d3e95efb60bea1e5ab7fc307d284"
    assert pinned == {f"fixtures/input/expected/{s}/animation.json": commit for s in ("exercise", "dance", "part3-squat")}
    assert json.loads((ROOT / "contracts/sources.lock.json").read_text())["upstreams"]["part4"]["commit"] == commit
    assert commit in (ROOT / "fixtures/input/expected/SOURCE.md").read_text()
    assert calibrate.expected_commit() == commit


# ----------------------------------------------------------------- --feet (TICKET-040)
# The foot sweep runs takes through pipeline.run with their foot side files. These tests give it a stand-in for the
# pipeline: each take has the size of the difference its measure shows, and a measure raises a fault when the size
# reaches the threshold in the rules, so every number below is worked out by hand from the sizes.
def label(ftype, measure, side, direction):
    return {"type": ftype, "measure": measure, "body_part": "legs", "joints": [f"{side}_ankle"], "side": side,
            "direction": direction}


FOOT_LABELS = {"out": label("foot_turned_out", "foot_rotation", "left", "more"),
               "in": label("foot_turned_in", "foot_rotation", "right", "less"),
               "roll_in": label("ankle_rolled_in", "ankle_inversion", "left", "more"),
               "roll_out": label("ankle_rolled_out", "ankle_inversion", "right", "less")}
ARMS = {"type": "arms_wider", "measure": "upper_arm_direction", "body_part": "arms", "joints": ["left_shoulder"],
        "side": "left", "direction": "more"}


def world(tmp_path, roll_out_size=17):
    """(labels, sizes): per angle at good light two correct takes (the first shows a foot_rotation difference of 8
    degrees, noise), one take per foot fault type (sizes 20, 18, 22 and `roll_out_size`) and one old-fault take whose
    leg shows an ankle_inversion difference of 10 (a co-fire). Every take points at the same four dummy files."""
    for name in ("e.json", "f.json", "ef.json", "ff.json"):
        (tmp_path / name).write_text("{}")
    paths = {"expected": "e.json", "follower": "f.json", "expected_feet": "ef.json", "follower_feet": "ff.json"}
    takes, sizes = [], {}

    def add(take_id, angle, faults, shown):
        takes.append({"take_id": take_id, "set": "exercise", "angle": angle, "lighting": "good", "variant": "clean",
                      "correct": not faults, "faults": faults, **paths})
        sizes[take_id] = shown

    for angle in ("front", "45", "side"):
        add(f"{angle}_c0", angle, [], [("foot_rotation", "left", "more", 8)])
        add(f"{angle}_c1", angle, [], [])
        add(f"{angle}_out", angle, [FOOT_LABELS["out"]], [("foot_rotation", "left", "more", 20)])
        add(f"{angle}_in", angle, [FOOT_LABELS["in"]], [("foot_rotation", "right", "less", 18)])
        add(f"{angle}_roll_in", angle, [FOOT_LABELS["roll_in"]], [("ankle_inversion", "left", "more", 22)])
        add(f"{angle}_roll_out", angle, [FOOT_LABELS["roll_out"]], [("ankle_inversion", "right", "less", roll_out_size)])
        add(f"{angle}_arms", angle, [ARMS], [("ankle_inversion", "left", "more", 10)])
    return {"seed": 5, "takes": takes}, sizes


def stand_in(sizes):
    """A pipeline stand-in: the faults of a take under the rules in the task (take id from its dummy follower)."""
    def run_fn(task):
        _, _, feet, rules = task
        return [{"measure": m, "side": s, "direction": d, "magnitude_deg": size}
                for m, s, d, size in sizes[feet["take_id"]] if size >= rules["measures"][m]["threshold_deg"]]
    return run_fn


@pytest.fixture
def feet_world(tmp_path, monkeypatch):
    labels, sizes = world(tmp_path)
    # prepare_feet puts the foot paths in the task; carry the take id with them so the stand-in can find its sizes
    prepare = calibrate.prepare_feet
    monkeypatch.setattr(calibrate, "prepare_feet", lambda lab, base: [
        calibrate.FootTake(p.take, p.expected, p.follower, {**p.feet, "take_id": p.take["take_id"]})
        for p in prepare(lab, base)])
    rules = {"measures": {"foot_rotation": {"threshold_deg": 12.0}, "ankle_inversion": {"threshold_deg": 15.0}}}
    return labels, sizes, rules


def test_a_foot_take_is_one_labelled_with_a_foot_measure():
    assert calibrate.is_foot_take({"faults": [FOOT_LABELS["roll_out"]]})
    assert not calibrate.is_foot_take({"faults": [ARMS]}) and not calibrate.is_foot_take({"faults": []})
    foot = [t for t in LABELS["takes"] if calibrate.is_foot_take(t)]
    assert len(foot) == 48 and len(LABELS["takes"]) - len(foot) == 108   # the guard's matched population keeps its 108


def test_foot_slices_count_only_the_measures_faults_and_list_the_co_fires():
    a, b, c, d = (dict(take_id=i, angle="front", lighting="good", variant="clean") for i in "ABCD")
    takes = [{**a, "correct": True, "faults": []}, {**b, "correct": False, "faults": [FOOT_LABELS["out"]]},
             {**c, "correct": False, "faults": [FOOT_LABELS["in"]]}, {**d, "correct": False, "faults": [ARMS]}]
    found = [[{"measure": "foot_rotation", "side": "left", "direction": "more"}],
             [{"measure": "foot_rotation", "side": "left", "direction": "more"},
              {"measure": "ankle_inversion", "side": "left", "direction": "more"}],   # not this measure: ignored
             [],
             [{"measure": "foot_rotation", "side": "right", "direction": "less"}]]
    s = calibrate.foot_slices(takes, found, "foot_rotation")["slices"]["good/front"]
    assert (s["tp"], s["fp"], s["fn"], s["takes"], s["correct_takes"], s["faults_on_correct_takes"]) == (1, 2, 1, 4, 1, 1)
    assert s["precision"] == pytest.approx(1 / 3, abs=1e-4) and s["recall"] == 0.5
    assert s["directions"] == {"more": 1, "less": 0} and s["cofires"] == ["D: right less"]


def metrics_for(**by_angle):
    """Foot metrics with a given (precision, recall, faults on correct takes, directions found) per good angle."""
    return {"slices": {f"good/{a}": {"precision": p, "recall": r, "faults_on_correct_takes": f, "tp": 4, "fn": 0,
                                     "correct_takes": 2, "directions": dict(zip(calibrate.DIRECTIONS, found))}
                       for a, (p, r, f, found) in by_angle.items()}}


def test_go_needs_every_angle_and_both_directions():
    good = {"front": (1.0, 1.0, 0, (2, 2)), "45": (0.9, 0.75, 0, (2, 2)), "side": (0.85, 1.0, 0, (1, 1))}
    assert calibrate.go_no_go(metrics_for(**good)) == (True, [])
    for angle, cell, why in (("45", (0.84, 1.0, 0, (2, 2)), "good/45: precision 0.84 is below 0.85"),
                             ("side", (1.0, 0.74, 0, (2, 2)), "good/side: recall 0.74 is below 0.75"),
                             ("front", (1.0, 1.0, 1, (2, 2)), "good/front: 1 fault(s) on correct takes")):
        go, reasons = calibrate.go_no_go(metrics_for(**{**good, angle: cell}))
        assert go is False and reasons == [why]
    never_less = {a: (1.0, 1.0, 0, (2, 0)) for a in good}   # perfect everywhere, but only one direction ever found
    go, reasons = calibrate.go_no_go(metrics_for(**never_less))
    assert go is False and reasons == ["direction less is never found at good light"]


def test_go_no_go_says_when_an_angle_has_nothing_to_judge():
    metrics = metrics_for(front=(1.0, 1.0, 0, (1, 1)), side=(1.0, 1.0, 0, (1, 1)))
    go, reasons = calibrate.go_no_go(metrics)
    assert go is False and reasons == ["good/45: needs labelled faults and correct takes"]


def test_the_foot_sweep_keeps_the_middle_of_the_plateau_and_both_measures_are_a_go(tmp_path, feet_world):
    labels, sizes, rules = feet_world
    lines, chosen, verdicts = calibrate.calibrate_feet(labels, rules, run_fn=stand_in(sizes), base=tmp_path)
    # foot_rotation: noise of 8 fires below 9, the weakest fault (18) is lost above 18: plateau 9..18, which reaches
    # the grid edge (12 +- 6), so the grid extends once (to 1..24); the middle is 13.5, rounded up to the grid step: 14.
    # ankle_inversion: the co-fire of 10 fires below 11, the weakest fault (17) is lost above 17: plateau 11..17, which
    # is inside its grid (15 +- 6), middle 14.
    assert chosen == {"foot_rotation": 14.0, "ankle_inversion": 14.0}
    assert verdicts == {"foot_rotation": (True, []), "ankle_inversion": (True, [])}
    text = "\n".join(lines)
    assert "== foot_rotation threshold_deg (current 12) ==" in text and "== ankle_inversion threshold_deg (current 15) ==" in text
    assert "chosen 14, plateau 9..18, grid 1..24" in text and "chosen 14, plateau 11..17, grid 9..21" in text
    assert "foot_rotation: GO" in text and "ankle_inversion: GO" in text
    assert rules["measures"]["foot_rotation"]["threshold_deg"] == 12.0   # the rules passed in are never changed


def test_a_measure_that_misses_a_direction_is_a_no_go_and_nothing_is_written_for_it(tmp_path, feet_world):
    labels, sizes, rules = feet_world
    labels, sizes = world(tmp_path, roll_out_size=5)   # rolled_out shows 5 degrees: only a threshold that fires on the co-fire finds it
    lines, chosen, verdicts = calibrate.calibrate_feet(labels, rules, run_fn=stand_in(sizes), base=tmp_path)
    assert verdicts["foot_rotation"] == (True, [])
    go, reasons = verdicts["ankle_inversion"]
    assert go is False and any("recall" in r or "precision" in r or "never found" in r for r in reasons)
    path = tmp_path / "rules.json"
    full = {"version": 1, "measures": {"foot_rotation": {"threshold_deg": 12.0, "x": 1},
                                       "ankle_inversion": {"threshold_deg": 15.0}}, "tail": [1]}
    path.write_text(json.dumps(full, indent=2) + "\n")
    written = calibrate.write_foot_thresholds(path, chosen, verdicts)
    after = json.loads(path.read_text())
    assert after["measures"]["foot_rotation"] == {"threshold_deg": chosen["foot_rotation"], "x": 1}
    assert after["measures"]["ankle_inversion"] == {"threshold_deg": 15.0} and after["tail"] == [1]
    assert any("ankle_inversion is NO-GO" in w for w in written) and any("wrote measures.foot_rotation" in w for w in written)


def test_nothing_is_written_when_no_measure_is_a_go(tmp_path):
    path = tmp_path / "rules.json"
    path.write_text('{"measures": {"foot_rotation": {"threshold_deg": 12.0}, "ankle_inversion": {"threshold_deg": 15.0}}}')
    before = path.read_bytes()
    calibrate.write_foot_thresholds(path, {"foot_rotation": 9.0, "ankle_inversion": 9.0},
                                    {m: (False, ["no"]) for m in calibrate.FOOT_MEASURES})
    assert path.read_bytes() == before


def test_the_rules_file_round_trips_through_the_writer():
    text = (ROOT / "part5/rules.json").read_text()
    assert json.dumps(json.loads(text), indent=2) + "\n" == text   # --write changes nothing but the values it writes


def test_feet_says_plainly_when_the_rules_have_no_foot_threshold():
    with pytest.raises(calibrate.CalibrateError, match=r"has no measures.foot_rotation.threshold_deg"):
        calibrate.feet_ready({"measures": {"ankle_inversion": {"threshold_deg": 15.0}}})
    with pytest.raises(calibrate.CalibrateError, match=r"has no measures.ankle_inversion.threshold_deg"):
        calibrate.feet_ready({"measures": {"foot_rotation": {"threshold_deg": 12.0}}})


def test_feet_needs_the_foot_files_the_labels_name(tmp_path):
    take = {"take_id": "t", "expected": "e.json", "follower": "f.json"}
    (tmp_path / "e.json").write_text("{}")
    (tmp_path / "f.json").write_text("{}")
    with pytest.raises(calibrate.CalibrateError, match="t has no expected_feet file; regenerate the tuning set"):
        calibrate.prepare_feet({"takes": [take]}, tmp_path)


def test_write_belongs_to_feet(capsys):
    code, out, err = run(capsys, "--write")
    assert code == 2 and "--write belongs to --feet" in err


def test_the_committed_seed_5_labels_name_the_foot_files():
    takes = [calibrate.FootTake(t, str(ROOT / t["expected"]), str(ROOT / t["follower"]),
                                {k: str(ROOT / t[k]) for k in ("expected_feet", "follower_feet")})
             for t in LABELS["takes"]]
    assert len(takes) == 156 and all(Path(p).is_file() for ft in takes for p in (ft.expected, ft.follower, *ft.feet.values()))
