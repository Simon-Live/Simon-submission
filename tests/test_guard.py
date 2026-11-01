"""The movement guard (ADR-0004): statistics, the refusal rule, AC-004, AC-005 and AC-011."""
import json
from pathlib import Path

import jsonschema
import numpy as np
import pytest

from part5.align import Alignment, align
from part5.detect import load_rules
from part5.guard import check_movement, diagnostics, movement_stats
from part5.io import load_clip
from part5.measures import compute
from part5.output import write_analysis
from part5.pipeline import run

ROOT = Path(__file__).resolve().parent.parent
LABELS = json.loads((ROOT / "fixtures/input/followers/labels.json").read_text())
OTHER = {"exercise": "dance", "dance": "exercise"}
SCHEMA = json.loads((ROOT / "contracts/analysis.schema.json").read_text())

# The plain-words warning text of a low match, locked here word for word (ADR-0012).
REFUSAL_TEXT = ("This take doesn't closely match the trainer's movement, so the grade is capped at F. "
                "Check that you picked the right movement and that the whole movement is in the take.")
# The status text of an analysed take, locked word for word (ADR-0012 note of 2026-11-01, AC-W07): a take with no warning
# keeps the first; a warned one says how many warnings cap the grade at F.
OK_TEXT = "Compared with the expected movement."
ONE_WARNING_TEXT = "Compared with the expected movement, with a warning that caps the grade at F."
TWO_WARNINGS_TEXT = "Compared with the expected movement, with 2 warnings that cap the grade at F."


def clip_path(name):
    return ROOT / f"fixtures/input/expected/{name}/animation.json"


def synthetic(n, residual, exp, fol):
    """An identity alignment over `n` frames with the given residual, plus measure dicts."""
    a = Alignment([(i, i) for i in range(n)], np.arange(n), np.linspace(0, 1, n), residual, list(exp))
    return a, exp, fol


def wave(n=60, phase=0.0):
    """One full period without its endpoint, so a wave and its quarter shift are uncorrelated."""
    return np.sin(np.arange(n) * 2 * np.pi / n + phase) * 30


def test_stats_of_a_clip_against_itself_are_perfect():
    p = load_clip(clip_path("exercise")).positions
    a, m = align(p, p), compute(p)
    s = movement_stats(a, m, m)
    assert s["residual"] == pytest.approx(0, abs=1e-6)
    assert s["timing_corr"] == pytest.approx(1.0)
    assert s["span_share"] == 1.0


def test_timing_corr_is_the_median_over_measures_and_skips_constant_series():
    n = 60
    exp = {"a": wave(n), "b": wave(n), "c": wave(n), "flat": wave(n)}
    fol = {"a": wave(n), "b": -wave(n), "c": wave(n), "flat": np.zeros(n)}
    a, exp, fol = synthetic(n, 0.1, exp, fol)
    s = movement_stats(a, exp, fol)
    assert s["timing_corr"] == pytest.approx(1.0)  # median of 1, -1, 1; the constant follower is skipped
    assert s["residual"] == 0.1


def test_timing_corr_ignores_frames_either_clip_is_missing():
    n = 60
    fol_a = wave(n)
    fol_a[10:30] = np.nan
    exp_a = wave(n)
    exp_a[40:50] = np.nan
    a, exp, fol = synthetic(n, 0.1, {"a": exp_a}, {"a": fol_a})
    assert movement_stats(a, exp, fol)["timing_corr"] == pytest.approx(1.0)


def test_timing_corr_is_nan_when_nothing_correlates():
    n = 60
    a, exp, fol = synthetic(n, 0.1, {"a": wave(n)}, {"a": np.zeros(n)})
    assert np.isnan(movement_stats(a, exp, fol)["timing_corr"])


def test_span_share_is_the_matched_share_of_the_follower_frames():
    n = 60
    a = Alignment([(i, i + 10) for i in range(n)], np.arange(n) + 10, np.full(100, np.nan), 0.1, ["a"])
    exp = {"a": wave(n)}
    fol = {"a": np.concatenate([np.zeros(10), wave(n), np.zeros(30)])}
    assert movement_stats(a, exp, fol)["span_share"] == pytest.approx(0.6)


@pytest.mark.parametrize("residual, corr, ok", [
    (0.50, 0.90, True),
    (0.60, 0.80, True),
    (0.65, 0.90, False),   # residual above the limit
    (0.50, 0.70, False),   # timing correlation below the limit
])
def test_check_movement_refuses_on_residual_or_on_timing_correlation(residual, corr, ok):
    rules = {"guard": {"max_residual": 0.63, "min_timing_corr": 0.78}}
    n = 60
    # A follower that is `corr` correlated with the expected series: mix the wave with its quarter-shift.
    mix = corr * wave(n) + np.sqrt(1 - corr ** 2) * wave(n, np.pi / 2)
    a, exp, fol = synthetic(n, residual, {"a": wave(n)}, {"a": mix})
    r = check_movement(a, exp, fol, rules)
    assert r.ok is ok
    assert r.code == ("ok" if ok else "different_movement")   # the guard's verdict; the document's status stays ok
    assert (r.text == REFUSAL_TEXT) is (not ok)
    assert r.stats["timing_corr"] == pytest.approx(corr, abs=1e-6)


def test_check_movement_limits_are_inclusive_and_a_flat_follower_is_refused():
    rules = {"guard": {"max_residual": 0.63, "min_timing_corr": 0.78}}
    n = 60
    a, exp, fol = synthetic(n, 0.63, {"a": wave(n)}, {"a": wave(n)})
    assert check_movement(a, exp, fol, rules).ok
    a, exp, fol = synthetic(n, 0.1, {"a": wave(n)}, {"a": np.zeros(n)})
    r = check_movement(a, exp, fol, rules)
    assert not r.ok and r.code == "different_movement"


def test_diagnostics_round_the_stats_and_leave_out_a_missing_timing_correlation():
    rules = load_rules()
    n = 60
    a, exp, fol = synthetic(n, 0.123456, {"a": wave(n)}, {"a": np.zeros(n)})
    d = diagnostics(check_movement(a, exp, fol, rules), rules)
    assert d["residual"] == 0.1235 and d["span_share"] == 1.0 and "timing_corr" not in d
    assert d["limits"] == {"max_residual": rules["guard"]["max_residual"],
                           "min_timing_corr": rules["guard"]["min_timing_corr"]}
    json.dumps(d, allow_nan=False)


def seed5_run(take, expected):
    return run(str(ROOT / expected), {"path": str(ROOT / take["follower"]), "take_id": take["take_id"]})


def test_ac005_every_seed_5_take_is_accepted_against_its_own_expected_clip():
    """AC-005: none of the 108 tuning takes (low light and double faults included) is refused."""
    limits = load_rules()["guard"]
    residuals, corrs = [], []
    for t in LABELS["takes"]:
        res = seed5_run(t, t["expected"])
        assert res.guard.ok, (t["take_id"], res.guard.stats)
        # OK_TEXT is the text of a take with no warning only (AC-W07); none of the tuning takes is warned
        assert not res.analysis.get("warnings"), t["take_id"]
        assert res.analysis["status"] == {"code": "ok", "text": OK_TEXT}
        residuals.append(res.guard.stats["residual"])
        corrs.append(res.guard.stats["timing_corr"])
    assert max(residuals) < limits["max_residual"] and min(corrs) > limits["min_timing_corr"]


def test_ac004_every_take_of_the_other_movement_is_a_low_match_graded_f():
    """AC-004 on the synthetic mismatch pairs (ADR-0012): each dance take against the exercise clip and each
    exercise take against the dance clip is analysed with a `low_match` warning, grade F and low-confidence
    faults; AC-011: the document validates against contracts/analysis.schema.json."""
    limits = load_rules()["guard"]
    validator = jsonschema.Draft202012Validator(SCHEMA)
    residuals, corrs = [], []
    for t in LABELS["takes"]:
        res = seed5_run(t, f"fixtures/input/expected/{OTHER[t['set']]}/animation.json")
        a = res.analysis
        assert a["status"]["code"] == "ok", t["take_id"]
        assert a["warnings"] == [{"code": "low_match", "text": REFUSAL_TEXT}], t["take_id"]
        assert a["match"]["quality"] == "low" and all(f["confidence"] == "low" for f in a["faults"]), t["take_id"]
        assert res.guard.ok is False
        assert sorted(a["diagnostics"]["guard"]) == ["limits", "residual", "span_share", "timing_corr"]
        assert not list(validator.iter_errors(a)), t["take_id"]
        residuals.append(res.guard.stats["residual"])
        corrs.append(res.guard.stats["timing_corr"])
    assert min(residuals) > limits["max_residual"] or max(corrs) < limits["min_timing_corr"]


def head_only_follower():
    """A ref to an exercise take with everything but the head marked outside the image: `not_enough_visible` and
    `no_usable_measures`, two warnings (the take cannot be aligned)."""
    from part5.io import JOINTS
    path = next((ROOT / "fixtures/input/followers/exercise").glob("exercise_45_good_00*/skeleton.json"))
    doc = json.loads(path.read_text())
    seen = ("nose", "left_eye", "right_eye")
    for frame in doc.get("frames") or doc["keyframes"]:
        frame["conf"] = {j: (1.0 if j in seen else 0.3) for j in JOINTS}
    return {"path": str(path), "doc": doc}


def blind_follower(tmp_path):
    doc = json.loads(clip_path("exercise").read_text())
    for f in doc["frames"]:
        f["conf"] = {j: 0.0 for j in f["joints"]}
        f["joints"] = {j: None for j in f["joints"]}
    path = tmp_path / "blind.json"
    path.write_text(json.dumps(doc))
    return str(path)


def test_ac_w07_a_take_with_one_warning_says_the_warning_caps_the_grade_at_f():
    take = next(t for t in LABELS["takes"] if t["set"] == "dance")
    a = seed5_run(take, "fixtures/input/expected/exercise/animation.json").analysis   # a low match, an aligned take
    assert [w["code"] for w in a["warnings"]] == ["low_match"]
    assert a["status"] == {"code": "ok", "text": ONE_WARNING_TEXT}
    assert not list(jsonschema.Draft202012Validator(SCHEMA).iter_errors(a))


def test_ac_w07_a_take_that_cannot_be_aligned_gets_the_same_text(tmp_path):
    a = run(str(clip_path("exercise")), blind_follower(tmp_path)).analysis   # _unaligned: no_usable_measures only
    assert [w["code"] for w in a["warnings"]] == ["no_usable_measures"]
    assert a["status"] == {"code": "ok", "text": ONE_WARNING_TEXT}


def test_ac_w07_a_take_with_more_warnings_says_how_many():
    a = run(str(clip_path("exercise")), head_only_follower()).analysis
    assert [w["code"] for w in a["warnings"]] == ["not_enough_visible", "no_usable_measures"]
    assert a["status"] == {"code": "ok", "text": TWO_WARNINGS_TEXT}
    assert not list(jsonschema.Draft202012Validator(SCHEMA).iter_errors(a))


def test_ac_w07_the_count_in_the_text_is_the_number_of_warnings():
    from part5.pipeline import _status_text
    assert _status_text([]) == OK_TEXT
    assert _status_text([{"code": "a"}]) == ONE_WARNING_TEXT
    assert _status_text([{"code": c} for c in "abc"]) == "Compared with the expected movement, with 3 warnings that cap the grade at F."


def test_ac_w07_a_take_with_no_warning_keeps_its_text_byte_for_byte():
    take = LABELS["takes"][0]
    a = seed5_run(take, take["expected"]).analysis
    assert "warnings" not in a and a["status"] == {"code": "ok", "text": OK_TEXT}
    assert json.dumps(a["status"]) == '{"code": "ok", "text": "Compared with the expected movement."}'


def test_the_limits_sit_in_the_gap_between_the_matched_and_the_other_movement_populations():
    """The starting limits are the midpoints of the gap on seed 5 (calibration retunes them)."""
    limits = load_rules()["guard"]
    matched, cross = [], []
    for t in LABELS["takes"][::4]:  # every fourth take: the gap is wide, the full sweep is above
        matched.append(seed5_run(t, t["expected"]).guard.stats)
        cross.append(seed5_run(t, f"fixtures/input/expected/{OTHER[t['set']]}/animation.json").guard.stats)
    assert max(s["residual"] for s in matched) < limits["max_residual"] < min(s["residual"] for s in cross)
    assert max(s["timing_corr"] for s in cross) < limits["min_timing_corr"] < min(s["timing_corr"] for s in matched)


def test_ac011_a_low_match_analysis_is_written_and_validates(tmp_path):
    take = next(t for t in LABELS["takes"] if t["set"] == "dance")
    res = seed5_run(take, "fixtures/input/expected/exercise/animation.json")
    out = tmp_path / "analysis.json"
    write_analysis(out, res.analysis)
    doc = json.loads(out.read_text())
    assert not list(jsonschema.Draft202012Validator(SCHEMA).iter_errors(doc))
    assert doc["schema_version"] == "1.11.0" and doc["status"]["code"] == "ok"
    assert doc["warnings"][0]["code"] == "low_match" and "diagnostics" in doc


def test_a_mostly_idle_take_gets_the_span_warning_and_is_not_refused(tmp_path):
    """Edge case: a follower standing still for most of the take warns, never refuses."""
    src = clip_path("exercise")
    doc = json.loads(src.read_text())
    n = len(doc["frames"])
    keep = [0] * 90 + list(range(n)) + [n - 1] * 90
    doc["frames"] = [dict(doc["frames"][k], index=i, t=i / doc["fps"]) for i, k in enumerate(keep)]
    doc["frame_count"] = len(keep)
    doc["duration_s"] = len(keep) / doc["fps"]
    idle = tmp_path / "idle.json"
    idle.write_text(json.dumps(doc))
    res = run(str(src), str(idle))
    assert res.guard.ok and res.analysis["status"]["code"] == "ok"
    assert res.guard.stats["span_share"] < 0.4 and res.analysis["diagnostics"]["warnings"]


def test_a_refused_take_still_returns_the_alignment_and_clips_for_the_replay():
    take = next(t for t in LABELS["takes"] if t["set"] == "exercise")
    res = seed5_run(take, "fixtures/input/expected/dance/animation.json")
    assert res.alignment is not None and res.guard is not None
    assert len(res.alignment.exp_to_fol) == res.expected.n_frames


MISMATCH = json.loads((ROOT / "fixtures/input/mismatch/manifest.json").read_text())["fixtures"]


@pytest.mark.parametrize("name", sorted(MISMATCH))
def test_ac004_part2_clips_through_part3_follow_the_manifest_against_the_squat(name):
    """AC-004 on real takes: Part 2 class (cat-cow yoga) and dance through Part 3 --view part5 are
    refused against part3-squat; the provisional squat `single` is a matched pair and is accepted
    (stakeholder-proxy decision, STATUS.md Decisions)."""
    entry = MISMATCH[name]
    res = run(str(ROOT / entry["against"]), str(ROOT / f"fixtures/input/mismatch/{name}/skeleton.json"))
    if entry["population"] == "mismatch":
        assert res.analysis["status"]["code"] == "ok" and res.analysis["match"]["quality"] == "low"
        assert [w["code"] for w in res.analysis["warnings"]] == ["low_match"]
    else:
        assert "warnings" not in res.analysis
        assert res.analysis["status"]["code"] == "ok", res.guard.stats
