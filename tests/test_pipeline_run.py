"""part5.pipeline.run: the analysis plus the clips and alignment the replay needs."""
import json
from pathlib import Path

import numpy as np
import pytest

from part5.pipeline import AnalysisError, PipelineResult, analyse, run

ROOT = Path(__file__).resolve().parent.parent
EXPECTED = ROOT / "fixtures/input/expected/exercise/animation.json"
TAKE = ROOT / "fixtures/input/followers/exercise/exercise_45_good_02_arms_wider-left/skeleton.json"


def test_run_returns_the_same_analysis_as_analyse():
    res = run(str(EXPECTED), str(TAKE))
    assert isinstance(res, PipelineResult)
    assert res.analysis == analyse(str(EXPECTED), str(TAKE))
    assert res.alignment is not None
    assert len(res.alignment.exp_to_fol) == res.expected.n_frames
    assert len(res.to_original) == len(res.follower_positions)
    assert res.to_original.max() < res.follower.n_frames


def test_an_in_memory_doc_gives_the_same_faults_and_never_reaches_the_output():
    doc = json.loads(TAKE.read_text())
    res = run(str(EXPECTED), {"path": "upload:follower", "doc": doc})
    assert res.analysis["faults"] == analyse(str(EXPECTED), str(TAKE))["faults"]
    assert res.analysis["follower"] == {"path": "upload:follower"}


def test_an_unknown_phrasing_backend_is_an_analysis_error():
    with pytest.raises(AnalysisError, match="phrasing"):
        run(str(EXPECTED), str(TAKE), phrasing="nope")


DANCE_TAKE = ROOT / "fixtures/input/followers/dance/dance_front_good_00_correct/skeleton.json"
WARNING_TEXT = ("This take doesn't closely match the trainer's movement, so the grade is capped at F. "
                "Check that you picked the right movement and that the whole movement is in the take.")


def test_an_accepted_take_carries_the_schema_version_status_runs_and_guard():
    res = run(str(EXPECTED), str(TAKE))
    a = res.analysis
    assert a["schema_version"] == "1.8.0"
    assert a["status"] == {"code": "ok", "text": "Compared with the expected movement."}
    assert res.guard is not None and res.guard.ok
    g = a["diagnostics"]["guard"]
    assert set(g) == {"residual", "timing_corr", "span_share", "limits"}
    assert set(g["limits"]) == {"max_residual", "min_timing_corr"}
    assert g["residual"] == pytest.approx(res.guard.stats["residual"], abs=1e-4)
    assert a["faults"] and all(f["runs"] and f["expected_frames"] in f["runs"] for f in a["faults"])
    assert all(f["joints"] and f["coaching"] == f["text_timed"] for f in a["faults"])  # ADR-0008
    assert a["phrasing"]["backend"] == "template" and len(a["phrasing"]["faults"]) == len(a["faults"])


def test_ac009_every_fault_names_canonical_joints():
    from part5.io import JOINTS
    for follower in (TAKE, ROOT / "fixtures/input/followers/exercise/exercise_front_good_08_arms_wider-both+elbow_bent-right/skeleton.json"):
        if follower.exists():
            for f in run(str(EXPECTED), str(follower)).analysis["faults"]:
                assert f["joints"] and set(f["joints"]) <= set(JOINTS)


def test_ac010_muse_spark_without_a_key_falls_back_and_scores_the_same(monkeypatch, tmp_path):
    """AC-010: no key file, so template phrases every fault; scored fields equal a template run."""
    monkeypatch.setenv("PART5_BASETEN_KEY_FILE", str(tmp_path / "missing-key"))
    plain = run(str(EXPECTED), str(TAKE)).analysis
    muse = run(str(EXPECTED), str(TAKE), phrasing="muse-spark").analysis
    assert muse["phrasing"]["requested"] == "muse-spark" and muse["phrasing"]["backend"] == "template"
    assert muse["phrasing"]["fallback_reason"] == "no key"
    strip = lambda doc: [{k: v for k, v in f.items() if k != "coaching"} for f in doc["faults"]]
    assert strip(muse) == strip(plain) and muse["status"] == plain["status"]


def test_ac010_an_injected_client_phrases_through_the_pipeline_and_never_changes_scored_fields(monkeypatch, tmp_path):
    key = tmp_path / "key"
    key.write_text("sentinel-key-value\n")
    monkeypatch.setenv("PART5_BASETEN_KEY_FILE", str(key))
    monkeypatch.setenv("PART5_BASETEN_USAGE_FILE", str(tmp_path / "usage.jsonl"))
    monkeypatch.setenv("META_LIVE", "1")

    def client(request):
        raise TimeoutError("timed out")

    plain = run(str(EXPECTED), str(TAKE)).analysis
    muse = run(str(EXPECTED), str(TAKE), phrasing="muse-spark", phrasing_client=client).analysis
    assert all(r["fallback_reason"] for r in muse["phrasing"]["faults"])
    assert [f["text_timed"] for f in muse["faults"]] == [f["coaching"] for f in muse["faults"]]  # fallback is the timed template line
    assert [f["magnitude_deg"] for f in muse["faults"]] == [f["magnitude_deg"] for f in plain["faults"]]
    assert "sentinel-key-value" not in json.dumps(muse)


def test_a_take_of_another_movement_is_analysed_with_a_low_match_warning():
    """ADR-0012: status ok, a low_match warning, every fault listed with confidence "low", never refused."""
    res = run(str(EXPECTED), str(DANCE_TAKE))
    a = res.analysis
    assert a["status"]["code"] == "ok" and res.guard.ok is False
    assert a["warnings"] == [{"code": "low_match", "text": WARNING_TEXT}]
    assert a["match"]["quality"] == "low" and a["match"]["residual"] == a["diagnostics"]["guard"]["residual"]
    assert a["match"]["limits"] == a["diagnostics"]["guard"]["limits"]
    assert a["diagnostics"]["guard"]["residual"] > a["diagnostics"]["guard"]["limits"]["max_residual"]
    assert all(f["confidence"] == "low" for f in a["faults"])
    assert a["schema_version"] == "1.8.0"


def test_the_guard_limits_come_from_the_rules_passed_in():
    from part5.detect import load_rules
    strict = load_rules()
    strict["guard"]["max_residual"] = 0.01
    res = run(str(EXPECTED), str(TAKE), strict)
    assert res.analysis["status"]["code"] == "ok" and res.analysis["match"]["quality"] == "low"
    assert res.analysis["diagnostics"]["guard"]["limits"]["max_residual"] == 0.01


def test_ac012_two_runs_write_byte_identical_analyses(tmp_path):
    """AC-012: same inputs, same bytes, for an accepted and a refused take."""
    from part5.output import write_analysis
    for follower in (TAKE, DANCE_TAKE):
        for name in ("a.json", "b.json"):
            write_analysis(tmp_path / name, analyse(str(EXPECTED), str(follower)))
        assert (tmp_path / "a.json").read_bytes() == (tmp_path / "b.json").read_bytes()


def test_ac_nfr_002_analysis_makes_no_network_call(monkeypatch, tmp_path):
    """AC-NFR-002: loading, aligning, guarding, detecting and writing use no socket."""
    import socket

    from part5 import cli

    def no_network(*args, **kwargs):
        raise AssertionError("a network call was attempted")

    monkeypatch.setattr(socket, "socket", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    assert run(str(EXPECTED), str(TAKE)).analysis["status"]["code"] == "ok"
    assert run(str(EXPECTED), str(DANCE_TAKE)).analysis["match"]["quality"] == "low"
    assert cli.main(["analyse", "--expected", str(EXPECTED), "--follower", str(DANCE_TAKE),
                     "--out", str(tmp_path / "a.json")]) == 0


def test_follower_frames_index_the_original_follower_file():
    res = run(str(EXPECTED), str(TAKE))
    for f in res.analysis["faults"]:
        assert 0 <= f["follower_frames"][0] <= f["follower_frames"][1] < res.follower.n_frames
    assert np.all(np.diff(res.to_original) >= 0)


def _follower_over(span_s, frames=3):
    doc = json.loads(TAKE.read_text())
    doc["frames"] = doc["frames"][:frames]
    for i, frame in enumerate(doc["frames"]):
        frame["t"] = span_s * i / (frames - 1)
    return {"path": "upload:follower", "doc": doc}


def test_the_resampled_follower_length_is_bounded_before_resampling(monkeypatch):
    called = []
    monkeypatch.setattr("part5.pipeline.resample", lambda *args: called.append(args))
    with pytest.raises(AnalysisError, match=r"upload:follower: 30001 frames .* the limit is 6000"):
        run(str(EXPECTED), _follower_over(1000.0))
    assert called == []


def test_the_length_bound_counts_the_frames_resample_would_make():
    from part5.pipeline import MAX_FRAMES, resampled_length
    assert resampled_length(np.array([0.0, (MAX_FRAMES - 1) / 30]), 30.0) == MAX_FRAMES
    assert resampled_length(np.array([0.0, MAX_FRAMES / 30]), 30.0) == MAX_FRAMES + 1


def test_the_length_bound_holds_for_a_span_too_big_for_a_float():
    follower = _follower_over(1.0)
    for frame, t in zip(follower["doc"]["frames"], (-1e308, 0.0, 1e308)):
        frame["t"] = t
    with pytest.raises(AnalysisError, match="the limit is 6000"):
        run(str(EXPECTED), follower)


def test_an_expected_clip_over_the_frame_rate_limit_is_refused_naming_it():
    doc = json.loads(EXPECTED.read_text())
    doc["fps"] = 1e6
    with pytest.raises(AnalysisError, match=r"upload:expected: 1e\+06 frames per second, the limit is 240"):
        run({"path": "upload:expected", "doc": doc}, str(TAKE))


def test_the_committed_clips_are_well_inside_the_bounds():
    from part5.io import load_clip
    from part5.pipeline import MAX_FPS, MAX_FRAMES, clip_fps, resampled_length
    for path in (*(ROOT / "fixtures/input/followers").rglob("skeleton.json"), EXPECTED):
        assert resampled_length(load_clip(path).t, 30.0) < MAX_FRAMES / 4, path
    assert clip_fps(load_clip(EXPECTED)) <= MAX_FPS


def test_an_expected_clip_whose_frame_times_overflow_is_refused_not_a_crash():
    """Frame times of +-1.7e308 increase but their step overflows: no usable frame rate, an AnalysisError
    (the API answers 400 with it), never a ZeroDivisionError."""
    doc = json.loads(EXPECTED.read_text())
    doc.pop("fps", None)
    doc["frames"] = doc["frames"][:3]
    for frame, t in zip(doc["frames"], (-1.7e308, 0.0, 1.7e308)):
        frame["t"] = t
    with pytest.raises(AnalysisError, match="no usable frame rate"):
        run({"path": "upload:expected", "doc": doc}, str(TAKE))


def test_a_pair_too_long_to_compare_together_is_refused_before_resampling(monkeypatch):
    """Each clip under MAX_FRAMES, but expected x follower frames over MAX_CELLS: refused, since the
    alignment's cost arrays grow with that product (delivery review residual 1)."""
    from part5.pipeline import MAX_CELLS, MAX_FRAMES
    exp = json.loads(EXPECTED.read_text())
    n = 2100  # 2100 x 2100 frame pairs is over MAX_CELLS while each clip is under MAX_FRAMES
    assert n < MAX_FRAMES and n * n > MAX_CELLS
    frames = exp["frames"]
    exp["frames"] = [dict(frames[i % len(frames)], index=i, t=i / exp["fps"]) for i in range(n)]
    called = []
    monkeypatch.setattr("part5.pipeline.resample", lambda *args: called.append(args))
    with pytest.raises(AnalysisError, match="too long to compare together"):
        run({"path": "upload:expected", "doc": exp}, _follower_over((n - 1) / exp["fps"]))
    assert called == []


def test_one_analysis_of_a_300_frame_pair_is_well_under_two_seconds():
    """The master spec's NFR (Performance: one analysis under 2 s on a 300-frame take)."""
    import time
    doc = json.loads(TAKE.read_text())
    frames = doc["frames"]
    doc["frames"] = [dict(frames[i % len(frames)], t=i / 30) for i in range(300)]
    start = time.perf_counter()
    run(str(EXPECTED), {"path": "upload:follower", "doc": doc})
    assert time.perf_counter() - start < 2.0
