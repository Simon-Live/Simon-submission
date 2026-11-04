"""part5.score_report: the grade distribution, the target verdicts, the gate sentences, the monotonic sweep."""
import json
from pathlib import Path

from part5 import score, score_report
from part5.detect import load_rules
from part5.evaluate import match_pairs
from shipped_score import IS_CAPPED

ROOT = Path(__file__).resolve().parent.parent


def blk(value):
    return {"value": value, "grade": score.grade(value)}


def take(light, n, tid="t"):
    return {"take_id": tid, "lighting": light, "faults": [{}] * n}


def test_distribution_counts_grades_per_light_and_labelled_faults():
    entries = [(take("good", 0), blk(100)), (take("good", 0), blk(95)), (take("good", 1), blk(85)),
               (take("good", 1), blk(72)), (take("good", 2), blk(63)), (take("low", 1), blk(30)),
               (take("low", 1), None)]  # a refused take is left out of n
    d = score_report.distribution(entries)
    assert d["good/0"] == {"n": 2, "min": 95, "median": 97.5, "max": 100, "grades": {"A": 2}}
    assert d["good/1"]["grades"] == {"B": 1, "C": 1} and d["low/1"]["n"] == 1 and d["low/1"]["grades"] == {"F": 1}
    assert d["low/0"] == {"n": 0, "min": None, "median": None, "max": None, "grades": {}}


def test_verdicts_follow_the_targets_as_measured():
    d = score_report.distribution([(take("good", 0), blk(100)), (take("good", 1), blk(85)), (take("good", 1), blk(100)),
                                   (take("good", 2), blk(40)), (take("good", 2), blk(65))])
    assert score_report.verdicts(d) == {"good/0": "pass", "good/1": "fail", "good/2": "pass"}
    assert score_report.verdicts(score_report.distribution([]))["good/0"] == "no takes"


def test_correct_good_failures_name_a_take_below_a_and_an_ok_take_without_a_score():
    labels = {"takes": [take("good", 0, "a"), take("good", 0, "b"), take("good", 0, "c"), take("good", 0, "d"),
                        take("low", 0, "e"), take("good", 1, "f")]}
    ok = {"status": {"code": "ok"}}
    analyses = {"a": {**ok, "score": {**blk(100)}}, "b": {**ok, "score": blk(89)}, "c": {**ok, "score": None},
                "d": {"status": {"code": "different_movement"}, "score": None}, "e": {**ok, "score": blk(10)},
                "f": {**ok, "score": blk(10)}}
    assert score_report.correct_good_failures(labels, analyses) == [
        "b: scored 89 (B), a correct good-light take must be an A", "c: no score (refused or not scored)"]


def test_monotone_failures_name_every_rising_step_and_flat_is_fine():
    sweeps = {"foot_out right": [(0, 100), (4, 100), (8, 90), (12, 91), (16, 80)]}
    assert score_report.monotone_failures(sweeps) == [
        "sweep foot_out right: score rises from 90 at 8 degrees to 91 at 12 degrees"]
    assert score_report.monotone_failures({"x": [(0, 100), (5, 90), (10, 90)]}) == []


def test_sweep_failures_flag_a_step_with_no_score():
    out = score_report.sweep_failures({"x": [(0, 100), (5, None), (10, 90)]})
    assert out == ["sweep x: no score at 5 degrees"]


def test_the_real_sweep_never_rises_and_writes_only_under_its_directory(tmp_path):
    sweeps = score_report.run_sweep(tmp_path / "sweep")
    assert set(sweeps) == {"foot_out right", "arms_wider both", "trunk_lean center"}
    assert score_report.sweep_failures(sweeps) == []
    for points in sweeps.values():
        values = [v for _, v in points]
        assert values[0] == 100 and values[-1] < values[0]  # a growing fault ends lower than a clean take
    assert len(list((tmp_path / "sweep").glob("*.json"))) == 8 + 8 + 7


def test_a_rising_score_in_the_sweep_is_detected_with_injected_scores(tmp_path):
    values = iter([100, 90, 95, 80, 80, 70, 60, 50] + [100] * 20)

    def fake(expected, follower):
        return {"score": {"value": next(values)}}

    sweeps = score_report.run_sweep(tmp_path / "sweep", analyse_fn=fake)
    assert any("rises from 90 at 4 degrees to 95 at 8 degrees" in f for f in score_report.sweep_failures(sweeps))


def test_analyse_adds_the_score_to_the_analysis_and_a_low_match_is_capped_at_f():
    labels = json.loads((ROOT / "fixtures/input/followers/labels.json").read_text())
    t = next(x for x in labels["takes"] if x["lighting"] == "good" and not x["faults"])
    a = score_report.analyse({"path": str(ROOT / t["expected"])}, {"path": str(ROOT / t["follower"])})
    assert a["score"]["grade"] == "A" and a["score"]["params_sha256"] == score.params_sha256(load_rules()["score"])
    other = ROOT / "fixtures/input/expected/dance/animation.json"
    refused = score_report.analyse({"path": str(other)}, {"path": str(ROOT / t["follower"])})
    assert refused["status"]["code"] == "ok" and refused["match"]["quality"] == "low"
    assert refused["score"]["grade"] == "F" and refused["score"]["capped_by"] == ["low_match"]
    assert "capped_by" not in a["score"] and "warnings" not in a


def test_the_cli_prints_the_distribution_and_the_verdicts(capsys):
    assert score_report.main(["--set", str(ROOT / "fixtures/input/followers"), "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["seed"] == 5 and doc["distribution"]["good/0"]["grades"] == {"A": 12}
    assert doc["verdicts"]["good/0"] == "pass" and doc["verdicts"]["good/2"] == "pass"
    # good/1 is covered by the next test: on seed 5 it misses its target for the foot faults that are not found


def test_every_good_light_single_fault_take_outside_b_or_c_has_a_cause_the_spec_names():
    """Seed 5 `good/1` and its target (B or C). Under v1 six takes were outside it: two scored A because their one foot fault
    is missed (docs/specs/foot-keypoints.md "Seed 5 result") and four dance takes scored A (92 or 93) because their foot fault
    is found in one rep of two and the other rep is scored clean. Under v2 (ADR-0018) a take that reports a fault is at most a
    B, so those four are B now; the one take outside B or C reports no fault at all, and the second missed foot fault
    reports a different one and is capped. This pins the causes, so a take outside B or C for any other reason fails."""
    labels = score_report.load_labels(ROOT / "fixtures/input/followers")
    labels["takes"] = [t for t in labels["takes"] if t["lighting"] == "good" and len(t["faults"]) == 1]
    assert len(labels["takes"]) == 60
    outside, missed_takes = [], []
    for t, result in score_report.run_set(labels):
        block = score_report.score_block(result) if result.alignment is not None else None
        missed = len(t["faults"]) - len(match_pairs(result.analysis["faults"], t["faults"]))
        if missed:
            missed_takes.append(t["take_id"])
        if block and block["grade"] not in score_report.shipped_targets()["good/1"]:
            accepted = len([r for r in result.reps or [] if r.ok])
            partial = any(len(f.get("reps", [])) < accepted for f in result.analysis["faults"])
            outside.append((t["take_id"], block["grade"], missed, partial, bool(result.analysis["faults"])))
    assert sorted(missed_takes) == ["dance_side_good_11_ankle_rolled_in-right",
                                    "exercise_front_good_12_ankle_rolled_out-both"], missed_takes   # the two missed foot faults
    if IS_CAPPED:   # nothing reported, nothing to cap
        assert outside == [("exercise_front_good_12_ankle_rolled_out-both", "A", 1, False, False)], outside
    else:       # simon.score.v1: the two missed faults and the four found in one rep of two
        assert all(missed >= 1 or partial for _, _, missed, partial, _ in outside), outside
        assert len([o for o in outside if o[2] >= 1]) == 2 and len(outside) == 6, outside


def test_the_cli_text_report_marks_low_light_as_reported(capsys):
    assert score_report.main(["--set", str(ROOT / "fixtures/input/followers")]) == 0
    out = capsys.readouterr().out
    assert "good/0" in out and "target A: pass" in out and "low/1" in out and "(reported, no target)" in out
