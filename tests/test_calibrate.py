"""`python -m part5.calibrate` (docs/specs/calibration.md): the seed 5 sweep, the guard calibration and
docs/thresholds.md. Small subsets of the committed seed 5 takes keep these fast; no held-out seed is read."""
import json
import shutil
import sys
import types
from pathlib import Path

import numpy as np
import pytest

from part5 import calibrate
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


def fake_guard(monkeypatch):
    """A stand-in for part5.guard.movement_stats (the guard lane provides the real one)."""
    mod = types.ModuleType("part5.guard")

    def movement_stats(alignment, exp_m, fol_m):
        j, cors = alignment.exp_to_fol, []
        for name in alignment.measures:
            e, f = np.asarray(exp_m[name]), np.asarray(fol_m[name])[j]
            ok = np.isfinite(e) & np.isfinite(f)
            if ok.sum() > 3 and e[ok].std() > 0 and f[ok].std() > 0:
                cors.append(float(np.corrcoef(e[ok], f[ok])[0, 1]))
        start, end = alignment.follower_span
        return {"residual": float(alignment.residual), "timing_corr": float(np.median(cors)),
                "span_share": (end - start + 1) / len(fol_m["left_knee_flexion"])}

    mod.movement_stats = movement_stats
    monkeypatch.setitem(sys.modules, "part5.guard", mod)


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
    p = calibrate.Param("foot_out threshold_deg", ("measures", "foot_out", "threshold_deg"), 1.0, 1.0, float("inf"), 6)
    assert calibrate.grid(p, 6.0, 6) == [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 11.0, 12.0]
    assert calibrate.grid(p, 9.0, 2) == [7.0, 8.0, 9.0, 10.0, 11.0]


def test_objective_is_precision_and_correct_takes_first_then_the_lowest_recall_across_angles():
    ok_low = calibrate.objective(cells(front=(0.9, 0.7, 0), **{"45": (0.9, 0.9, 0)}, side=(0.9, 0.95, 0)))
    ok_high = calibrate.objective(cells(front=(0.9, 0.8, 0), **{"45": (0.9, 0.8, 0)}, side=(0.9, 0.8, 0)))
    low_precision = calibrate.objective(cells(front=(0.84, 1.0, 0), **{"45": (1.0, 1.0, 0)}, side=(1.0, 1.0, 0)))
    wrong_on_correct = calibrate.objective(cells(front=(1.0, 1.0, 1), **{"45": (1.0, 1.0, 0)}, side=(1.0, 1.0, 0)))
    assert ok_low == (True, 0, 0.7) and ok_high == (True, 0, 0.8)
    assert ok_high > ok_low > low_precision and ok_low > wrong_on_correct
    assert low_precision[0] is False and wrong_on_correct[0] is False
    assert low_precision > wrong_on_correct  # 0.01 short beats a whole fault on a correct take


def plateau_rows(best_values, worse_values=()):
    rows = [{"value": float(v), "objective": (True, 0, 0.8)} for v in best_values]
    return rows + [{"value": float(v), "objective": (True, 0, 0.7)} for v in worse_values]


def test_the_middle_of_the_plateau_is_kept_not_its_edge():
    rows = plateau_rows([9, 10, 11, 12], worse_values=[8, 13, 14])
    assert calibrate.best(rows)["value"] == 11.0  # middle 10.5, rounded up to the grid step
    assert calibrate.best(plateau_rows([4, 5, 6], [3, 7]))["value"] == 5.0


def test_a_split_plateau_uses_its_longest_run_and_equal_runs_go_to_the_larger_values():
    longest = plateau_rows([3, 4, 8, 9, 10, 11], worse_values=[5, 6, 7])
    assert [r["value"] for r in calibrate.plateau(longest)] == [8.0, 9.0, 10.0, 11.0]
    equal = plateau_rows([3, 4, 8, 9], worse_values=[5, 6, 7])
    assert calibrate.best(equal)["value"] == 9.0


def test_a_flat_sweep_keeps_the_current_value():
    rows = [{"value": v, "objective": (True, 0, 0.8)} for v in (5.0, 6.0, 7.0)]
    chosen, note, span = calibrate.choose(rows, 6.0)
    assert chosen["value"] == 6.0 and "flat" in note and span == (5.0, 7.0)


def test_a_best_value_on_the_grid_edge_extends_the_grid_once_and_says_so(monkeypatch):
    monkeypatch.setattr(calibrate, "evaluate", lambda prepared, rules: cells(
        front=(1.0, min(1.0, rules["measures"]["foot_out"]["threshold_deg"] / 20), 0)))
    rules = {"measures": {"foot_out": {"threshold_deg": 6.0}}}
    p = calibrate.params(rules)[0]
    res = calibrate.sweep_param(None, rules, p, radius=3)
    values = [r["value"] for r in res["rows"]]
    assert values == [float(v) for v in range(1, 13)]  # 3..9 first, then 1..12 after one extension
    assert res["chosen"]["value"] == 12.0 and "still reaches the grid edge" in res["note"]
    assert res["plateau"] == (12.0, 12.0) and res["grid"] == (1.0, 12.0)


def test_a_best_value_inside_the_grid_is_not_extended(monkeypatch):
    monkeypatch.setattr(calibrate, "evaluate", lambda prepared, rules: cells(
        front=(1.0, 1.0 - abs(rules["measures"]["foot_out"]["threshold_deg"] - 7.0) / 10, 0)))
    rules = {"measures": {"foot_out": {"threshold_deg": 6.0}}}
    res = calibrate.sweep_param(None, rules, calibrate.params(rules)[0], radius=3)
    assert [r["value"] for r in res["rows"]] == [3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0]
    assert res["chosen"]["value"] == 7.0 and res["note"] == ""


# ----------------------------------------------------------------- reading the rules generically
def test_params_cover_every_measure_and_the_persistence_keys_that_exist():
    rules = load_rules()
    names = [p.name for p in calibrate.params(rules)]
    assert names[:len(rules["measures"])] == [f"{g} threshold_deg" for g in rules["measures"]]
    assert "min_fraction" in names
    top = {"default": {"threshold_deg": 10.0, "min_fraction": 0.2}, "measures": {"a": {"threshold_deg": 5.0}},
           "min_run_frames": 4, "min_overlap": 0.5}
    found = {p.name: p.path for p in calibrate.params(top)}
    assert found == {"a threshold_deg": ("measures", "a", "threshold_deg"), "min_fraction": ("default", "min_fraction"),
                     "min_run_frames": ("min_run_frames",), "min_overlap": ("min_overlap",)}
    assert [p.name for p in calibrate.params(top, only={"a", "min_overlap"})] == ["a threshold_deg", "min_overlap"]
    assert calibrate.locate({"default": {}, "measures": {}}, "min_overlap") is None


def test_with_value_leaves_the_original_rules_alone():
    rules = load_rules()
    changed = calibrate.with_value(rules, ("measures", "foot_out", "threshold_deg"), 99.0)
    assert changed["measures"]["foot_out"]["threshold_deg"] == 99.0
    assert rules["measures"]["foot_out"]["threshold_deg"] != 99.0


# ----------------------------------------------------------------- the sweep on real takes
SWEEP_ARGS = ("--only", "foot_out,min_fraction", "--radius", "1")


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


# ----------------------------------------------------------------- the guard
def test_guard_without_movement_stats_exits_2_with_a_plain_message(tmp_path, capsys, monkeypatch):
    monkeypatch.setitem(sys.modules, "part5.guard", None)  # an import of it now fails
    code, out, err = run(capsys, "--set", str(subset(tmp_path)), "--guard", *SWEEP_ARGS)
    assert code == 2 and out == ""
    assert err.strip() == ("calibrate: part5.guard.movement_stats is missing; the guard (TICKET-015) "
                           "provides it, so --guard can't run yet")


def test_guard_prints_both_populations_the_limits_and_the_single_exclusion(tmp_path, capsys, monkeypatch):
    fake_guard(monkeypatch)
    code, out, err = run(capsys, "--set", str(subset(tmp_path, SMALL_KEEP)), "--guard", "--only", "foot_out", "--radius", "1")
    assert code == 0, err
    assert "== movement guard ==" in out and "matched: 6 pairs" in out
    assert "mismatch: 8 pairs" in out  # 6 exercise vs dance and dance vs exercise, plus Part 2 class and dance
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
    fake_guard(monkeypatch)
    monkeypatch.setattr(calibrate, "MISMATCH_DIR", tmp_path / "no-mismatch")
    code, out, err = run(capsys, "--set", str(subset(tmp_path, KEEP[:2])), "--guard", "--only", "foot_out", "--radius", "1")
    assert code == 2 and "manifest.json missing; run the neighbour check or TICKET-015 fixtures" in err


def test_a_missing_mismatch_skeleton_exits_2_naming_the_file(tmp_path, capsys, monkeypatch):
    fake_guard(monkeypatch)
    copy = tmp_path / "mismatch"
    shutil.copytree(ROOT / "fixtures/input/mismatch", copy)
    (copy / "part2-class" / "skeleton.json").unlink()
    monkeypatch.setattr(calibrate, "MISMATCH_DIR", copy)
    code, out, err = run(capsys, "--set", str(subset(tmp_path, KEEP[:2])), "--guard", "--only", "foot_out", "--radius", "1")
    assert code == 2 and "part2-class/skeleton.json missing; run the neighbour check or TICKET-015 fixtures" in err


def test_single_joins_the_mismatch_population_when_the_manifest_says_it_is_a_stretch(tmp_path, capsys, monkeypatch):
    fake_guard(monkeypatch)
    copy = tmp_path / "mismatch"
    shutil.copytree(ROOT / "fixtures/input/mismatch", copy)
    doc = json.loads((copy / "manifest.json").read_text())
    doc["fixtures"]["part2-single"]["population"] = "mismatch"
    (copy / "manifest.json").write_text(json.dumps(doc))
    monkeypatch.setattr(calibrate, "MISMATCH_DIR", copy)
    code, out, err = run(capsys, "--set", str(subset(tmp_path, SMALL_KEEP)), "--guard", "--only", "foot_out", "--radius", "1")
    assert code == 0, err
    assert "mismatch: 9 pairs" in out and "excluded from the mismatch population" not in out


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
    fake_guard(monkeypatch)
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
    assert sorted(manifest) == ["part2-class", "part2-dance", "part2-single"]
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
