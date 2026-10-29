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
REFUSAL_TEXT = ("This take does not look like the expected movement, so no faults are listed. "
                "Check that you picked the right movement and that the whole movement is in the take.")


def test_an_accepted_take_carries_the_schema_version_status_runs_and_guard():
    res = run(str(EXPECTED), str(TAKE))
    a = res.analysis
    assert a["schema_version"] == "1.1.0"
    assert a["status"] == {"code": "ok", "text": "Compared with the expected movement."}
    assert res.guard is not None and res.guard.ok
    g = a["diagnostics"]["guard"]
    assert set(g) == {"residual", "timing_corr", "span_share", "limits"}
    assert set(g["limits"]) == {"max_residual", "min_timing_corr"}
    assert g["residual"] == pytest.approx(res.guard.stats["residual"], abs=1e-4)
    assert a["faults"] and all(f["runs"] and f["expected_frames"] in f["runs"] for f in a["faults"])
    assert all(f["joints"] and f["coaching"] == f["text"] for f in a["faults"])
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
    assert [f["text"] for f in muse["faults"]] == [f["coaching"] for f in muse["faults"]]
    assert [f["magnitude_deg"] for f in muse["faults"]] == [f["magnitude_deg"] for f in plain["faults"]]
    assert "sentinel-key-value" not in json.dumps(muse)


def test_a_take_of_another_movement_is_refused_before_detection():
    res = run(str(EXPECTED), str(DANCE_TAKE))
    a = res.analysis
    assert a["status"] == {"code": "different_movement", "text": REFUSAL_TEXT}
    assert a["faults"] == [] and res.guard.ok is False
    assert a["diagnostics"]["guard"]["residual"] > a["diagnostics"]["guard"]["limits"]["max_residual"]
    assert a["schema_version"] == "1.1.0"


def test_the_guard_limits_come_from_the_rules_passed_in():
    from part5.detect import load_rules
    strict = load_rules()
    strict["guard"]["max_residual"] = 0.01
    res = run(str(EXPECTED), str(TAKE), strict)
    assert res.analysis["status"]["code"] == "different_movement" and res.analysis["faults"] == []
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
    assert run(str(EXPECTED), str(DANCE_TAKE)).analysis["status"]["code"] == "different_movement"
    assert cli.main(["analyse", "--expected", str(EXPECTED), "--follower", str(DANCE_TAKE),
                     "--out", str(tmp_path / "a.json")]) == 3


def test_follower_frames_index_the_original_follower_file():
    res = run(str(EXPECTED), str(TAKE))
    for f in res.analysis["faults"]:
        assert 0 <= f["follower_frames"][0] <= f["follower_frames"][1] < res.follower.n_frames
    assert np.all(np.diff(res.to_original) >= 0)
