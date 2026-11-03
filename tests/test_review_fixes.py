"""Fixes from the consolidated review of `92aba12..HEAD`: the score leaves out what the camera did not see (B5),
only the expected alignment failure is caught (R2), a bad `conf` is a plain input error (R3), rep mode is bounded
like the whole pair (R4), rep-mode faults and the rep replay sit on the expected file's frames and times (R5), and
`_unaligned` reports the caller's rules (R6).

Specs: docs/specs/part5-fault-analysis.md (AC-VIS-2, "Repetitions"), ADR-0011, ADR-0012, ADR-0013.
"""
import copy
import json
from pathlib import Path

import numpy as np
import pytest

from part5 import cli, pipeline, repwise, score
from part5.align import AlignmentError
from part5.detect import Fault, load_rules, overlaps_side
from part5.io import JOINTS, InputError
from part5.measures import MEASURES
from part5.measures import compute as plain_measures
from part5.pipeline import AnalysisError, run
from part5.replay import build_replay
from part5.score_report import aligned_of, score_block
from part5.visibility import UNSEEN_CONF, load_conf, measures_of

ROOT = Path(__file__).resolve().parent.parent
EXPECTED = ROOT / "fixtures/input/expected/exercise/animation.json"
FOLLOWERS = ROOT / "fixtures/input/followers/exercise"
LATERAL = ROOT / "fixtures/input/real/lateral-raise"
TRAINER, FAST, SLOW = (LATERAL / n / "animation.json" for n in ("pexels-5319084", "pexels-40297504", "pexels-8836968"))
HIPS_AND_LEGS = ["left_hip", "right_hip", "left_knee", "right_knee", "left_ankle", "right_ankle"]


def follower(name):
    return next(FOLLOWERS.glob(f"{name}*/skeleton.json"))


# --- B5: the score leaves out the measures the camera did not see ----------------------------------------------

def legs_unseen_in_a_third_of_the_frames(name="exercise_45_good_04"):
    """Hips and legs outside the image in the first 30% of the frames: seen in 70% (under the 80% rule), so
    their measures are excluded (AC-VIS-2), yet in 70% of the frames the joints are there and `compute` reads them."""
    path = follower(name)
    doc = json.loads(path.read_text())
    frames = doc["frames"]
    for i, fr in enumerate(frames):
        gone = i < 0.3 * len(frames)
        fr["conf"] = {j: (UNSEEN_CONF if gone and j in HIPS_AND_LEGS else 1.0) for j in JOINTS}
    return {"path": str(path), "doc": doc}


@pytest.fixture(scope="module")
def partial():
    return run(str(EXPECTED), legs_unseen_in_a_third_of_the_frames(), score=score_block)


def mean_z_over(names, aligned, rules):
    """The similarity input computed by hand from only `names`: the measures that were seen."""
    idx = np.asarray(aligned["exp_to_fol"])
    errs = [np.abs(np.asarray(aligned["follower"][n])[idx] - np.asarray(aligned["expected"][n]))
            / score.threshold_of(n, rules) for n in names]
    e = np.vstack(errs)
    return float(np.mean(np.minimum(e[np.isfinite(e)], score.CLIP_Z)))


def test_b5_the_fixture_excludes_the_leg_measures_but_still_computes_them_in_most_frames(partial):
    assert not partial.vis.full and "left_knee_flexion" in partial.vis.excluded
    leaked = plain_measures(partial.follower_positions)["left_knee_flexion"]
    assert np.isfinite(leaked).mean() > 0.5   # what the old score read, though the measure is excluded


def test_b5_excluded_measures_are_nan_in_the_scores_input(partial):
    aligned = aligned_of(partial)
    excluded = [m for m in MEASURES if m in partial.vis.excluded]
    assert excluded and all(np.isnan(aligned[side][m]).all() for side in ("expected", "follower") for m in excluded)
    kept = [m for m in MEASURES if m in partial.vis.usable]
    assert kept and all(np.isfinite(aligned["follower"][m]).any() for m in kept)


def test_b5_a_partially_visible_take_scores_the_same_as_with_those_measures_removed(partial):
    rules = load_rules()
    aligned = aligned_of(partial)
    usable = [m for m in MEASURES if m in partial.vis.usable]
    plain = {"expected": plain_measures(partial.expected.positions),
             "follower": plain_measures(partial.follower_positions), "exp_to_fol": aligned["exp_to_fol"]}
    assert score.mean_z(aligned, rules) == pytest.approx(mean_z_over(usable, plain, rules))
    assert mean_z_over(list(MEASURES), plain, rules) != pytest.approx(mean_z_over(usable, plain, rules))   # it did leak
    block = partial.analysis["score"]
    p = score.params_of(rules)
    similarity = p["s_max"] * min(1.0, max(0.0, (mean_z_over(usable, plain, rules) - p["z0"]) / (p["z1"] - p["z0"])))
    assert block["components"]["similarity"] == pytest.approx(similarity, abs=0.011)


def test_b5_a_full_body_take_is_scored_exactly_as_before():
    res = run(str(EXPECTED), str(follower("exercise_45_good_04")), score=score_block)
    assert res.vis.full
    aligned = aligned_of(res)
    for side, positions in (("expected", res.expected.positions), ("follower", res.follower_positions)):
        for name, series in plain_measures(positions).items():
            np.testing.assert_array_equal(aligned[side][name], series)


def test_b5_the_view_measures_a_partial_pair_adds_never_reach_the_similarity(partial):
    assert set(MEASURES) <= set(aligned_of(partial)["expected"])   # extra keys are allowed, mean_z reads MEASURES
    assert measures_of(partial.expected.positions, partial.vis).keys() >= set(MEASURES)


def test_b5_a_rep_by_rep_take_passes_its_visibility_to_every_rep(monkeypatch):
    res = run(str(TRAINER), str(SLOW))   # partially visible (its knees and ankles are outside the image) and rep mode
    assert res.reps and not res.vis.full
    seen, masks, original = [], [], aligned_of

    def spy(result, vis=None, mask=None):   # TICKET-084: each rep also gets the take's declared mask (None here)
        seen.append(vis)
        masks.append(mask)
        return original(result, vis, mask)

    monkeypatch.setattr("part5.score_report.aligned_of", spy)
    score_block(res)
    assert len(seen) == sum(r.ok for r in res.reps) and all(v is res.vis for v in seen)
    assert masks == [None] * len(seen)


# --- R2: only the expected alignment failure is caught ----------------------------------------------------------

def test_r2_an_alignment_error_is_a_low_match_with_a_score_of_zero(monkeypatch):
    def too_fast(*args, **kwargs):
        raise AlignmentError("follower clip is too short to align")

    monkeypatch.setattr("part5.pipeline.align", too_fast)
    a = run(str(EXPECTED), str(follower("exercise_45_good_02")), score=score_block).analysis
    assert [w["code"] for w in a["warnings"]] == ["low_match"] and a["faults"] == []
    assert a["score"]["value"] == 0 and a["status"]["code"] == "ok"


def test_r2_any_other_value_error_from_the_alignment_surfaces(monkeypatch):
    def bug(*args, **kwargs):
        raise ValueError("an internal bug")

    monkeypatch.setattr("part5.pipeline.align", bug)
    with pytest.raises(ValueError, match="an internal bug"):
        run(str(EXPECTED), str(follower("exercise_45_good_02")))


def test_r2_a_rep_that_cannot_be_aligned_does_not_pass(monkeypatch):
    def refuse_every_rep(*args, **kwargs):
        raise AlignmentError("no alignment")

    monkeypatch.setattr("part5.repwise.align", refuse_every_rep)
    res = run(str(TRAINER), str(FAST))
    assert "low_match" in [w["code"] for w in res.analysis["warnings"]] and res.reps is None


def test_r2_any_other_value_error_in_a_rep_surfaces(monkeypatch):
    def bug(*args, **kwargs):
        raise ValueError("an internal bug")

    monkeypatch.setattr("part5.repwise.align", bug)
    with pytest.raises(ValueError, match="an internal bug"):
        run(str(TRAINER), str(FAST))


def test_r2_the_dtw_raises_the_dedicated_error_for_its_expected_cases():
    from part5.align import dtw
    with pytest.raises(AlignmentError, match="too short"):
        dtw(np.ones((10, 3)))
    assert issubclass(AlignmentError, ValueError)


# --- R3: a non-numeric conf is a plain input error ---------------------------------------------------------------

@pytest.mark.parametrize("conf", ["high", None, [1.0], {"x": 1}])
def test_r3_load_conf_names_the_file_for_a_conf_that_is_not_a_number(tmp_path, conf):
    path = tmp_path / "trainer.json"
    path.write_text(json.dumps({"frames": [{"conf": {"left_knee": conf}}]}))
    with pytest.raises(InputError, match=rf"{path.name}: expected-visibility conf must be a number"):
        load_conf(path)


def test_r3_a_people_style_file_with_a_text_conf_is_an_input_error_too(tmp_path):
    path = tmp_path / "pose3d.json"
    path.write_text(json.dumps({"frames": [{"people": [{"joints": {"left_knee": {"conf": "high"}}}]}]}))
    with pytest.raises(InputError, match="must be a number"):
        load_conf(path)


def test_r3_a_conf_that_is_no_object_is_an_input_error(tmp_path):
    path = tmp_path / "trainer.json"
    path.write_text(json.dumps({"frames": [{"conf": [0.3, 1.0]}]}))
    with pytest.raises(InputError, match="must be a number"):
        load_conf(path)


def test_r3_the_cli_prints_the_plain_line_and_exits_1(tmp_path, capsys):
    path = tmp_path / "trainer.json"
    path.write_text(json.dumps({"frames": [{"conf": {"left_knee": "high"}}]}))
    out = tmp_path / "a.json"
    code = cli.main(["analyse", "--expected", str(EXPECTED), "--follower", str(follower("exercise_45_good_00")),
                     "--expected-visibility", str(path), "--out", str(out)])
    err = capsys.readouterr().err
    assert code == 1 and not out.exists()
    assert err.startswith(f"part5 analyse: {path}: expected-visibility conf must be a number") and "Traceback" not in err


def test_r3_a_numeric_conf_still_loads(tmp_path):
    path = tmp_path / "trainer.json"
    path.write_text(json.dumps({"frames": [{"conf": {"left_knee": 0.3, "right_knee": "1"}}]}))
    conf = load_conf(path)
    assert conf.shape == (1, len(JOINTS)) and conf[0, JOINTS.index("left_knee")] == 0.3


# --- R4: rep mode is bounded like the whole pair -----------------------------------------------------------------

@pytest.fixture(scope="module")
def fast_pair():
    return run(str(TRAINER), str(FAST))


def compare_with(res, max_cells):
    return repwise.compare(res.expected, res.follower, measures_of(res.expected.positions, res.vis),
                           res.follower_positions, res.to_original, pipeline.clip_fps(res.expected), load_rules(),
                           pipeline._fault_times, res.vis, max_cells=max_cells)


def test_r4_the_reps_together_may_use_exactly_the_limit(fast_pair):
    n, k = fast_pair.reps[0].expected.n_frames, len(fast_pair.reps)
    assert len(compare_with(fast_pair, k * n * n).reps) == k
    with pytest.raises(repwise.TooManyPairs) as e:
        compare_with(fast_pair, k * n * n - 1)
    assert (e.value.follower_frames, e.value.expected_frames) == (k * n, n)


def test_r4_no_limit_given_means_no_bound(fast_pair):
    assert compare_with(fast_pair, None).guard.ok


def _whole_clip_unalignable(*a, **k):
    raise AlignmentError("scripted: the whole pair cannot be aligned")


def test_r4_reps_over_the_limit_keep_the_whole_clip_comparison_when_it_fits(monkeypatch):
    """1.14.4: the reps' total over the limit no longer refuses a take whose whole pair was aligned; it is analysed on the
    whole clip, as a rep verdict that does not accept the take is (AC-RP-16). Long dance follows were refused this way."""
    monkeypatch.setattr("part5.pipeline.MAX_CELLS", 50_000)
    # the whole pair (about 97,000 pairs) would trip the same limit first; here only the reps' total is under test
    monkeypatch.setattr("part5.pipeline._bounded_fps", lambda exp, exp_ref, fol, fol_ref: pipeline.clip_fps(exp))
    res = run(str(TRAINER), {"path": "fast.upload", "doc": json.loads(FAST.read_text())})
    assert res.reps is None and score_block(res)["basis"] == "windows"


def test_r4_the_pipeline_turns_it_into_the_plain_error_naming_the_follower_when_nothing_fits(monkeypatch):
    monkeypatch.setattr("part5.pipeline.MAX_CELLS", 50_000)
    monkeypatch.setattr("part5.pipeline._bounded_fps", lambda exp, exp_ref, fol, fol_ref: pipeline.clip_fps(exp))
    monkeypatch.setattr("part5.pipeline.align", _whole_clip_unalignable)
    with pytest.raises(AnalysisError, match=r"fast\.upload: 824 follower frames against 103 expected frames "
                                           r"are too long to compare together \(the limit is 50,000 frame pairs\)"):
        run(str(TRAINER), {"path": "fast.upload", "doc": json.loads(FAST.read_text())})


def test_r4_the_cli_exits_1_with_the_plain_message(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr("part5.pipeline.MAX_CELLS", 50_000)
    monkeypatch.setattr("part5.pipeline._bounded_fps", lambda exp, exp_ref, fol, fol_ref: pipeline.clip_fps(exp))
    monkeypatch.setattr("part5.pipeline.align", _whole_clip_unalignable)
    out = tmp_path / "a.json"
    code = cli.main(["analyse", "--expected", str(TRAINER), "--follower", str(FAST), "--out", str(out)])
    err = capsys.readouterr().err
    assert code == 1 and not out.exists() and "too long to compare together" in err and err.startswith("part5 analyse: ")


def test_r4_the_whole_pair_bound_keeps_its_message(monkeypatch):
    monkeypatch.setattr("part5.pipeline.MAX_CELLS", 1000)
    with pytest.raises(AnalysisError, match=r"315 follower frames against 309 expected frames are too long to "
                                           r"compare together \(the limit is 1,000 frame pairs\)"):
        run(str(TRAINER), str(FAST))


# --- R5: rep-mode faults and the rep replay are on the expected file's frames and times --------------------------

@pytest.fixture(scope="module")
def offset_pair():
    """The slow take as the example (its first rep starts at frame 38 of 525) and the fast one as the follower."""
    return run(str(SLOW), str(FAST), score=score_block)


def test_r5_the_fixture_has_reps_faults_and_a_reference_that_does_not_start_at_zero(offset_pair):
    ref = offset_pair.analysis["diagnostics"]["expected_reference"]
    assert offset_pair.reps and ref["frames"][0] > 0 and offset_pair.analysis["faults"]


def test_r5_expected_frames_runs_and_phase_are_on_the_expected_files_frames(offset_pair):
    a = offset_pair.analysis
    first, last = a["diagnostics"]["expected_reference"]["frames"]
    n_file = offset_pair.expected.n_frames
    for f in a["faults"]:
        start, end = f["expected_frames"]
        assert first <= start <= end <= last                      # inside the reference rep, in the file's frames
        assert f["expected_frames"] in f["runs"] and all(first <= s <= e <= last for s, e in f["runs"])
        assert f["phase"] == [round(start / (n_file - 1), 3), round(end / (n_file - 1), 3)]


def test_r5_a_fault_is_the_first_reps_local_one_shifted_by_the_references_start(offset_pair):
    a, shift = offset_pair.analysis, offset_pair.analysis["diagnostics"]["expected_reference"]["frames"][0]
    for f in a["faults"]:
        # a fault on both sides may have been found on one side in its first rep (aggregate_faults counts that toward it)
        local = next(x for x in offset_pair.reps[f["reps"][0]].faults
                     if overlaps_side([(x.measure, x.side, x.direction)], (f["measure"], f["side"], f["direction"])))
        assert f["expected_frames"] == [local.expected_frames[0] + shift, local.expected_frames[1] + shift]
        assert f["runs"] == [[s + shift, e + shift] for s, e in local.runs]


def test_r5_the_followers_clock_and_the_scores_windows_are_not_shifted(offset_pair):
    a = offset_pair.analysis
    for f in a["faults"]:
        rep = offset_pair.reps[f["reps"][0]]
        assert rep.span[0] <= f["follower_frames"][0] <= rep.span[1]
        assert f["follower_t_s"][0] == pytest.approx(float(offset_pair.follower.t[f["follower_frames"][0]]), abs=1e-3)
    assert a["score"]["basis"] == "reps" and len(a["score"]["timeline"]) == len(offset_pair.reps)


def test_r5_on_expected_file_shifts_the_runs_and_derives_the_phase_from_the_whole_file():
    f = Fault(measure="knee_flexion", side="both", joint="knee", body_part="legs", direction="less",
              magnitude_deg=-12.0, peak_deg=-15.0, threshold_deg=9.0, expected_frames=(2, 9), follower_frames=(3, 20),
              phase=(0.1, 0.4), coverage=1.0, confidence=0.8, runs=((2, 9), (15, 18)))
    moved = repwise._on_expected_file(f, 30, 100)
    assert moved.expected_frames == (32, 39) and moved.runs == ((32, 39), (45, 48))
    assert moved.phase == (round(32 / 99, 3), round(39 / 99, 3))
    assert moved.follower_frames == f.follower_frames and f.expected_frames == (2, 9)   # the original is untouched


def test_r5_the_rep_replays_first_copy_carries_the_example_files_own_times(offset_pair):
    r = build_replay(offset_pair)
    ref = offset_pair.reps[0].expected
    n, k = ref.n_frames, len(offset_pair.reps)
    assert r["expected_t"][:n] == pytest.approx([float(t) for t in ref.t], abs=1e-6)
    assert r["expected_t"][0] > 0 and len(r["expected_t"]) == n * k == len(r["expected"])
    assert all(b > a for a, b in zip(r["expected_t"], r["expected_t"][1:]))        # strictly increasing
    assert r["expected_t"][n] == pytest.approx(float(ref.t[0]) + float(ref.t[-1] - ref.t[0]) + 1 / r["fps"], abs=1e-5)


def test_r5_a_reference_that_starts_at_zero_keeps_its_times_from_zero(fast_pair):
    r = build_replay(fast_pair)
    assert fast_pair.reps[0].expected.t[0] == 0.0
    assert r["expected_t"][0] == 0.0 and r["expected_t"][:5] == pytest.approx([float(t) for t in fast_pair.expected.t[:5]])


# --- R6: the unaligned path reports the caller's rules ------------------------------------------------------------

def custom_rules():
    rules = copy.deepcopy(load_rules())
    rules["guard"]["max_residual"], rules["guard"]["min_timing_corr"] = 0.123, 0.456
    return rules


def test_r6_a_take_with_no_usable_measures_reports_the_callers_guard_limits(blind_follower):
    a = run(str(EXPECTED), blind_follower(), rules=custom_rules()).analysis
    assert [w["code"] for w in a["warnings"]] == ["no_usable_measures"]
    assert a["match"]["limits"] == {"max_residual": 0.123, "min_timing_corr": 0.456}


def test_r6_a_take_that_cannot_be_aligned_reports_the_callers_guard_limits(monkeypatch):
    def too_fast(*args, **kwargs):
        raise AlignmentError("follower clip is too short to align")

    monkeypatch.setattr("part5.pipeline.align", too_fast)
    a = run(str(EXPECTED), str(follower("exercise_45_good_02")), rules=custom_rules()).analysis
    assert [w["code"] for w in a["warnings"]] == ["low_match"]
    assert a["match"]["limits"] == {"max_residual": 0.123, "min_timing_corr": 0.456}


def test_r6_without_rules_the_frozen_limits_are_reported(blind_follower):
    a = run(str(EXPECTED), blind_follower()).analysis
    assert a["match"]["limits"] == {k: load_rules()["guard"][k] for k in ("max_residual", "min_timing_corr")}
