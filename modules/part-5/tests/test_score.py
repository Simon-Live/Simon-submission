"""simon.score.v1 (ADR-0007, docs/specs/journey-followup.md J-4): the formula, the bands, the refusal,
the params hash, the detection freeze hash and the seed 5 calibration."""
import copy
import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from part5 import calibrate, check, score, score_report
from part5.detect import load_rules
from part5.measures import MEASURES
from shipped_score import DETECTION_SHA, SHIPPED, frozen_v1

ROOT = Path(__file__).resolve().parent.parent
N = 10
PARAMS = {"version": "simon.score.v1", "z0": 0.0, "z1": 1.0, "s_max": 4.0, "base": 10, "slope": 5.0, "cap": 30.0,
          "bands": [[90, "A"], [80, "B"], [70, "C"], [60, "D"], [0, "F"]], "calibrated_on": "test"}


@pytest.fixture
def rules():
    return {**load_rules(), "score": copy.deepcopy(PARAMS)}


def aligned(z=0.0, n=N, nan=False):
    """Every measure off by `z` times its threshold on every frame (identity alignment)."""
    base = load_rules()
    exp = {m: np.zeros(n) for m in MEASURES}
    fol = {m: np.full(n, z * score.threshold_of(m, base)) for m in MEASURES}
    if nan:
        fol = {m: np.full(n, np.nan) for m in MEASURES}
    return {"expected": exp, "follower": fol, "exp_to_fol": list(range(n))}


def fault(mag=20.0, thr=10.0, runs=((0, 4),), cov=1.0):
    return {"magnitude_deg": mag, "threshold_deg": thr, "runs": [list(r) for r in runs], "coverage": cov,
            "expected_frames": list(runs[0])}


def analysis(faults=(), code="ok"):
    return {"status": {"code": code}, "faults": list(faults)}


def test_a_take_with_no_faults_and_no_error_is_100_a(rules):
    s = score.compute(analysis(), aligned(0.0), rules)
    assert (s["value"], s["grade"]) == (100, "A") and s["components"] == {"faults": 0.0, "similarity": 0.0}
    assert s["version"] == "simon.score.v1"


def test_ac_s02_formula_faults_and_similarity(rules):
    # r = 2: penalty 10 + 5 * 1 = 15; dur 0.5: weight 0.75 -> F 11.25; mean_z 0.5 -> S 2.0; 100 - 13.25 = 86.75
    s = score.compute(analysis([fault()]), aligned(0.5), rules)
    assert s["components"] == {"faults": 11.25, "similarity": 2.0}
    assert (s["value"], s["grade"]) == (87, "B")


def test_ac_s02_the_penalty_is_capped(rules):
    s = score.compute(analysis([fault(mag=100.0, runs=((0, 9),))]), aligned(0.0), rules)
    assert s["components"]["faults"] == 30.0 and s["value"] == 70


def test_ac_s02_coverage_and_every_run_count(rules):
    s = score.compute(analysis([fault(mag=10.0, runs=((0, 1), (5, 6)), cov=0.5)]), aligned(0.0), rules)
    # r = 1: penalty 10, dur 0.4: weight 0.7, coverage 0.5 -> 3.5; 96.5 rounds half up to 97
    assert s["components"]["faults"] == 3.5 and s["value"] == 97


def test_ac_s02_a_signed_magnitude_counts_by_size(rules):
    a = score.compute(analysis([fault(mag=-20.0)]), aligned(), rules)
    b = score.compute(analysis([fault(mag=20.0)]), aligned(), rules)
    assert a == b


def test_ac_s02_round_half_up_at_a_half(rules):
    # F = 10 * 1.0 * 0.75 = 7.5 -> 92.5 -> 93 (half up, not banker's 92)
    s = score.compute(analysis([fault(mag=10.0, runs=((0, 9),), cov=0.75)]), aligned(), rules)
    assert s["value"] == 93
    assert [float(score.round_half_up(*a)) for a in ((2.675, 2), (0.5,), (1.5,))] == [2.68, 1, 2]


def test_ac_s02_clamped_at_0_and_100(rules):
    many = [fault(mag=100.0, runs=((0, 9),)) for _ in range(6)]
    assert score.compute(analysis(many), aligned(2.0), rules)["value"] == 0
    assert score.compute(analysis(), aligned(0.0), rules)["value"] == 100


@pytest.mark.parametrize("value, letter", [(100, "A"), (90, "A"), (89, "B"), (80, "B"), (79, "C"), (70, "C"),
                                           (69, "D"), (60, "D"), (59, "F"), (0, "F")])
def test_ac_s02_band_edges(value, letter):
    assert score.grade(value) == letter == score.grade(value, PARAMS["bands"])


def test_similarity_is_clipped_per_value_and_bounded_by_s_max(rules):
    s = score.compute(analysis(), aligned(50.0), rules)  # every error clipped to 2 thresholds: S capped at s_max
    assert s["components"]["similarity"] == 4.0 and s["value"] == 96


def test_a_measure_missing_everywhere_is_skipped_not_scored_zero(rules):
    assert score.compute(analysis(), aligned(nan=True), rules) == score.zero_block(rules)
    al = aligned(0.5)
    al["follower"]["elbow_flexion"] = np.full(N, np.nan)
    assert score.compute(analysis(), al, rules)["components"]["similarity"] == 2.0


def test_adr_0012_nothing_measurable_scores_zero_grade_f_never_null(rules):
    zero = score.zero_block(rules)
    assert zero["value"] == 0 and zero["grade"] == "F" and zero["components"] == {"faults": 0.0, "similarity": 0.0}
    assert score.compute(analysis(code="different_movement"), aligned(), rules) == zero   # a pre-ADR-0012 refusal


def test_adr_0012_any_warning_caps_the_value_at_59_and_names_the_codes(rules):
    good = score.compute(analysis(), aligned(), rules)
    assert good["value"] >= 90
    assert score.cap_by_warnings(good, analysis(), rules) == good   # no warnings: byte for byte what it was
    capped = score.cap_by_warnings(good, dict(analysis(), warnings=[{"code": "low_match", "text": "x"},
                                                                     {"code": "not_enough_visible", "text": "y"}]), rules)
    assert capped["value"] == 59 and capped["grade"] == "F" and capped["capped_by"] == ["low_match", "not_enough_visible"]
    assert capped["components"] == good["components"]
    low = score.zero_block(rules)
    assert score.cap_by_warnings(low, dict(analysis(), warnings=[{"code": "no_usable_measures", "text": "x"}]),
                                 rules)["value"] == 0


def test_score_cap_records_the_uncapped_value_given_a_warning_lowers_it(rules):
    # Part 7 TICKET-155: a one-fault take scored 73 C and the low_match cap made it 59 F; the reader needs the 73.
    good = score.compute(analysis(), aligned(), rules)
    capped = score.cap_by_warnings(good, dict(analysis(), warnings=[{"code": "low_match", "text": "x"}]), rules)
    assert capped["uncapped"] == {"value": good["value"], "grade": good["grade"]}
    assert "uncapped" not in score.cap_by_warnings(good, analysis(), rules)        # no warnings: unchanged
    low = score.cap_by_warnings(score.zero_block(rules), dict(analysis(), warnings=[{"code": "low_match", "text": "x"}]),
                                rules)
    assert "uncapped" not in low and low["capped_by"] == ["low_match"]            # already under the cap


def test_the_params_hash_is_the_sha256_of_the_score_block(rules):
    want = hashlib.sha256(json.dumps(PARAMS, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert score.compute(analysis(), aligned(), rules)["params_sha256"] == want == score.params_sha256(PARAMS)


def test_the_shipped_rules_have_a_score_block_and_compute_reads_it():
    rules = load_rules()
    assert score.params_of(rules)["version"] == SHIPPED   # simon.score.v3 (ADR-0019) with the frozen v1 and v2 params as rules["score"]["v1"] and ["v2"]
    assert score.compute(analysis(), aligned())["params_sha256"] == score.params_sha256(rules["score"])
    with pytest.raises(ValueError, match="no simon.score.v1, simon.score.v2 or simon.score.v3 'score' block"):   # TICKET-054 R8
        score.params_of({"default": {}})


def test_a_bigger_fault_never_scores_higher(rules):
    values = [score.compute(analysis([fault(mag=m)]), aligned(0.3), rules)["value"] for m in range(10, 80, 5)]
    assert values == sorted(values, reverse=True) and values[0] > values[-1]


def test_a_longer_fault_never_scores_higher(rules):
    values = [score.compute(analysis([fault(runs=((0, e),))]), aligned(), rules)["value"] for e in range(0, 10)]
    assert values == sorted(values, reverse=True)


def test_fault_features_use_expected_frames_without_runs():
    f = {"magnitude_deg": -12.0, "threshold_deg": 6.0, "expected_frames": [2, 5], "coverage": 0.9}
    assert score.fault_features(f, 20) == {"r": 2.0, "dur": 0.2, "cov": 0.9}


# --- calibration (AC-S01) ---
def rows():
    r = [{"lighting": "good", "n_labelled": 0, "faults": [], "mean_z": z} for z in np.linspace(0.1, 0.3, 20)]
    r += [{"lighting": "good", "n_labelled": 1, "faults": [{"r": 3.0, "dur": 0.5, "cov": 1.0}], "mean_z": 0.5},
          {"lighting": "low", "n_labelled": 0, "faults": [], "mean_z": 0.9}]
    return r


def test_calibrate_follows_the_stated_rules():
    p = score.calibrate(rows(), 0.4)
    assert p["z1"] == 0.9 and p["z0"] == pytest.approx(0.29, abs=0.02) and p["s_max"] == 4.0
    assert p["base"] == 16  # ceil(10.5 / (0.5 + 0.5 * 0.4)) in floating point (15.000000000000002)
    assert p["calibrated_on"] == "seed 5" and p["version"] == "simon.score.v1"


def test_calibrated_worst_single_fault_lands_at_70_or_more():
    p = score.calibrate(rows(), 0.4)
    feats = {"faults": [{"r": 3.0, "dur": 0.5, "cov": 1.0}], "mean_z": p["z1"]}
    f, s = score.components(feats, p)
    assert 100 - f - s >= 70 - 1e-9
    smallest = {"faults": [{"r": 1.0, "dur": 0.4, "cov": 1.0}], "mean_z": 0.0}
    assert 100 - score.components(smallest, p)[0] < 90  # the smallest counted fault is never an A


@pytest.fixture
def attempt3_detection(monkeypatch):
    """Seed 5 analysed by the detection the score parameters were calibrated on and frozen with (attempts 1 to 3): the
    trunk's side lean as the frontal projection, no rep mode for a pair the whole-clip guard accepts, persistence over
    the whole clip, the floor of 8 frames for every measure and the thresholds of that freeze (`knee_flexion` 9,
    `upper_arm_out` 10; the recheck of attempt 4 re-swept them under the split floor to 10 and 11). Attempt 4 (ADR-0017)
    changes that detection and does not touch the parameters, so their reproduction is shown on the path they came from."""
    from part5 import measures, pipeline
    monkeypatch.setattr(measures, "_sideways", measures._lateral)
    monkeypatch.setattr(pipeline, "compare", lambda *a, **k: None)     # no seed 5 take is refused by the whole-clip guard
    real = pipeline.detect_full
    monkeypatch.setattr(pipeline, "detect_full", lambda *a, **k: real(*a, **{**k, "rep_spans": None}))
    rules = load_rules()
    rules["default"]["min_frames_floor"] = rules["default"]["min_frames_floor_body"] = 8
    rules["measures"]["knee_flexion"]["threshold_deg"] = 9.0
    rules["measures"]["upper_arm_out"]["threshold_deg"] = 10.0
    return rules


def test_ac_s01_seed_5_reproduces_the_research_prototype_and_the_shipped_block(attempt3_detection):
    labels = json.loads((ROOT / "fixtures/input/followers/labels.json").read_text())
    block = score_report.calibrate_set(labels, {**attempt3_detection, "score": {}})   # rules that ship no v2 form: the v1 calibration
    assert {k: block[k] for k in ("z0", "z1", "s_max", "base", "slope", "cap")} == {
        "z0": 0.289, "z1": 0.732, "s_max": 4.0, "base": 16, "slope": 5.9, "cap": 31.1}
    assert block == frozen_v1()   # frozen at attempt 3 and kept verbatim by v2 (ADR-0018)


def test_calibrate_score_writes_only_the_score_key(tmp_path, attempt3_detection):
    rules_path = tmp_path / "rules.json"
    original = {k: v for k, v in attempt3_detection.items() if k != "score"}     # the rules the parameters came from
    rules_path.write_text(json.dumps(original, indent=2) + "\n")
    labels = json.loads((ROOT / "fixtures/input/followers/labels.json").read_text())
    assert calibrate.write_score_block(labels, rules_path) == 0
    written = json.loads(rules_path.read_text())
    assert {k: v for k, v in written.items() if k != "score"} == original and written["score"] == frozen_v1()


def test_the_score_calibration_still_runs_on_a_take_compared_rep_by_rep():
    """Attempt 4 makes every dance take a rep-by-rep one; the calibration rows must exist for it (a reference of 43 frames
    against an example of 121 was a shape error) and the shipped parameters stay as they are, frozen."""
    labels = json.loads((ROOT / "fixtures/input/followers/labels.json").read_text())
    labels["takes"] = [t for t in labels["takes"] if t["take_id"] in ("dance_front_good_00_correct",
                                                                     "dance_front_good_02_arms_wider-left")]
    rows = score_report.rows_of_set(labels)
    assert [r["take_id"] for r in rows] == [t["take_id"] for t in labels["takes"]]
    assert all(r["mean_z"] is not None and 0 <= r["mean_z"] < 1 for r in rows)
    assert rows[0]["faults"] == [] and len(rows[1]["faults"]) == 1


# --- the freeze hash for the detection rules (AC-S06) ---
# DETECTION_SHA (the hash of the detection rules, with its history) is written once, in tests/shipped_score.py


def test_ac_s06_the_detection_hash_ignores_the_score_block_and_equals_the_recorded_one():
    assert check.detection_hash() == DETECTION_SHA
    text = (ROOT / "docs/thresholds.md").read_text()
    assert check.recorded_detection_hash(text) == DETECTION_SHA


def test_ac_s06_any_detection_key_changes_the_hash_and_the_score_block_does_not(tmp_path):
    rules = load_rules()
    path = tmp_path / "rules.json"
    path.write_text(json.dumps({**rules, "score": {"version": "other"}}))
    assert check.detection_hash(path) == DETECTION_SHA
    rules["default"]["threshold_deg"] += 1
    path.write_text(json.dumps(rules))
    assert check.detection_hash(path) != DETECTION_SHA


def test_the_recorded_hash_is_read_from_the_score_section_only():
    sha = "a" * 64
    assert check.recorded_detection_hash(f"## Score\n\n### Freeze\ndetection_sha256: `{sha}`\n## Next\n") == sha
    assert check.recorded_detection_hash(f"## Other\ndetection_sha256: `{sha}`\n") is None
    assert check.recorded_detection_hash(f"## Score\nx\n## Next\ndetection_sha256: `{sha}`\n") is None
