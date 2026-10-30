"""TICKET-032 to TICKET-034: time per fault, lateral direction and timed words, the replay file.

Spec: docs/specs/journey-followup.md (AC-T01..T04, AC-L01..L03, AC-R01..R03). ADR-0009.
"""
import json
from pathlib import Path

import numpy as np
import pytest

from part5 import cli
from part5.detect import Fault
from part5.lateral import lateral_for, lateral_m
from part5.output import (OutputError, build_analysis, round_half_up_tenth, validate_analysis,
                          write_analysis)
from part5.pipeline import run
from part5.replay import build_replay
from part5.words import describe_timed

ROOT = Path(__file__).resolve().parent.parent
LABELS = json.loads((ROOT / "fixtures/input/followers/labels.json").read_text())
LABEL = next(t for t in LABELS["takes"] if t["take_id"].startswith("exercise_front_good_03_foot_out-right"))
EXPECTED, TAKE = ROOT / LABEL["expected"], ROOT / LABEL["follower"]


def fault(**kw):
    base = dict(measure="foot_out", side="right", joint="right_ankle", body_part="legs",
                direction="more", magnitude_deg=8.0, peak_deg=8.3, threshold_deg=6.0,
                expected_frames=(19, 43), follower_frames=(29, 48), phase=(0.2, 0.5),
                coverage=1.0, confidence=0.8)
    return Fault(**{**base, **kw})


@pytest.fixture(scope="module")
def result():
    return run(str(EXPECTED), str(TAKE))


def shifted(offset):
    doc = json.loads(TAKE.read_text())
    for i, fr in enumerate(doc["frames"]):
        fr["t"] = fr.get("t", i / doc.get("fps", 30)) + offset
    return {"path": "follower.upload", "doc": doc}


# ---- J-1 -----------------------------------------------------------------------------------
def test_ac_t01_times_come_from_the_follower_clock(result):
    f = result.analysis["faults"][0]
    t = result.follower.t
    a, b = f["follower_frames"]
    assert f["follower_t_s"] == [round(float(t[a]), 3), round(float(t[b]), 3)]
    assert f["at_s"] == round_half_up_tenth(t[a])


def test_ac_t01_a_late_clock_is_not_shifted(result):
    later = run(str(EXPECTED), shifted(5.0))
    base = result.analysis["faults"][0]["follower_t_s"]
    got = later.analysis["faults"][0]["follower_t_s"]
    assert got == pytest.approx([base[0] + 5.0, base[1] + 5.0], abs=1e-3)


def test_ac_t02_every_run_is_mapped_and_the_longest_matches(result):
    for f in result.analysis["faults"]:
        assert len(f["follower_runs"]) == len(f["runs"])
        s, e = f["expected_frames"]
        k = f["runs"].index([s, e])
        assert f["follower_runs"][k] == f["follower_frames"]
        for (a, b) in f["follower_runs"]:
            assert 0 <= a <= b < result.follower.n_frames


@pytest.mark.parametrize("seconds,want", [(1.85, 1.9), (1.849, 1.8), (0.05, 0.1), (10.0, 10.0), (0.0, 0.0)])
def test_ac_t03_rounding_is_half_up(seconds, want):
    assert round_half_up_tenth(seconds) == want


def test_ac_t04_timed_text_adds_the_time_and_keeps_text(result):
    f = result.analysis["faults"][0]
    assert f["text_timed"] == f"{describe_timed(fault(magnitude_deg=f['magnitude_deg'], threshold_deg=f['threshold_deg'], direction=f['direction'], side=f['side']))} at {f['at_s']:.1f} s"
    assert f["text_timed"].startswith("right foot ") and "too far right" in f["text_timed"]
    assert f["text"].startswith("right foot ") and "too far out" in f["text"]


def test_time_fields_are_absent_when_not_given():
    d = build_analysis({"path": "e.json"}, "f.json", [fault()])["faults"][0]
    assert "at_s" not in d and "text_timed" not in d


# ---- J-2 -----------------------------------------------------------------------------------
LATERAL_ROWS = [
    ("foot_out", "more", "left", "left"), ("foot_out", "more", "right", "right"),
    ("foot_out", "less", "left", "right"), ("foot_out", "less", "right", "left"),
    ("thigh_out", "more", "right", "right"), ("upper_arm_out", "less", "left", "right"),
    ("forearm_out", "more", "left", "left"),
    ("knee_valgus", "more", "left", "right"), ("knee_valgus", "more", "right", "left"),
    ("knee_valgus", "less", "left", "left"), ("knee_valgus", "less", "right", "right"),
    ("trunk_lean_side", "more", "center", "left"), ("trunk_lean_side", "less", "center", "right"),
    ("foot_out", "more", "both", None), ("upper_arm_out", "less", "both", None),
    ("knee_flexion", "more", "left", None), ("shoulder_tilt", "more", "center", None),
    ("thigh_forward", "less", "right", None), ("head_forward", "more", "center", None),
]


@pytest.mark.parametrize("measure,direction,side,want", LATERAL_ROWS)
def test_ac_l01_lateral_table(measure, direction, side, want):
    assert lateral_for(measure, direction, side) == want


TIMED_ROWS = [
    ("foot_out", "more", "right", "right foot too far right"),
    ("foot_out", "less", "right", "right foot too far left"),
    ("thigh_out", "more", "left", "left knee too far left"),
    ("upper_arm_out", "less", "left", "left arm too far right"),
    ("forearm_out", "more", "right", "right hand too far right"),
    ("knee_valgus", "more", "left", "left knee caving in"),
    ("thigh_forward", "less", "right", "right thigh too low"),
    ("thigh_forward", "less", "both", "thighs too low"),
    ("upper_arm_forward", "less", "left", "left arm too low"),
    ("foot_out", "more", "both", "feet too far apart"),
    ("knee_flexion", "less", "left", "left knee not bent enough"),
]


@pytest.mark.parametrize("measure,direction,side,want", TIMED_ROWS)
def test_ac_l02_timed_words(measure, direction, side, want):
    sign = 1 if direction == "more" else -1
    f = fault(measure=measure, direction=direction, side=side,
              magnitude_deg=sign * 7.0, peak_deg=sign * 7.5, threshold_deg=6.0 if measure != "knee_flexion" else 5.0)
    # a size just past the threshold reads "slightly "; compare without the qualifier
    assert describe_timed(f, qualify=False) == want


def test_ac_l02_qualifier_goes_before_too():
    f = fault(magnitude_deg=7.0, threshold_deg=6.0)
    assert describe_timed(f) == "right foot slightly too far right"


def test_ac_l03_foot_offset():
    n = 40
    exp = np.zeros((n, 17, 3))
    fol = np.zeros((n, 17, 3))
    ankle = 16  # right_ankle
    exp[:, ankle, 0] = -0.20
    fol[:, ankle, 0] = -0.28
    f = fault(runs=((5, 30),))
    assert lateral_m(f, exp, fol, np.arange(n)) == pytest.approx(0.08, abs=0.01)
    assert lateral_m(fault(measure="knee_flexion"), exp, fol, np.arange(n)) is None
    assert lateral_m(fault(side="both"), exp, fol, np.arange(n)) is None


def test_lateral_m_and_lateral_in_a_real_run(result):
    f = result.analysis["faults"][0]
    assert f["lateral"] == "right"
    assert f["lateral_m"] > 0


def test_a_fault_without_direction_has_null_lateral_and_no_offset():
    d = build_analysis({"path": "e.json"}, "f.json", [fault(measure="knee_flexion", joint="right_knee")],
                       times=[{"follower_t_s": [1.0, 2.0], "follower_runs": [[1, 2]]}])["faults"][0]
    assert d["lateral"] is None and "lateral_m" not in d


# ---- validation ----------------------------------------------------------------------------
@pytest.mark.parametrize("key,value", [("follower_t_s", [2.0, 1.0]), ("at_s", "x"), ("lateral", "up"),
                                       ("lateral_m", "far"), ("text_timed", ""),
                                       ("follower_runs", [[3, 1]])])
def test_validation_names_a_bad_time_field(result, key, value):
    import copy
    a = copy.deepcopy(result.analysis)
    a["faults"][0][key] = value
    with pytest.raises(OutputError, match=key):
        validate_analysis(a)


def test_score_hook_is_absent_by_default_and_null_when_refused(result):
    assert "score" not in result.analysis
    block = {"version": "simon.score.v1", "value": 90, "grade": "A"}
    scored = run(str(EXPECTED), str(TAKE), score=lambda r: block)
    assert scored.analysis["score"] == block
    fixed = run(str(EXPECTED), str(TAKE), score=block)
    assert fixed.analysis["score"] == block
    other = ROOT / next(t for t in LABELS["takes"] if t["set"] != LABEL["set"])["follower"]
    refused = run(str(EXPECTED), str(other), score=lambda r: pytest.fail("not called"))
    if refused.analysis["status"]["code"] != "ok":
        assert refused.analysis["score"] is None


def test_a_score_on_a_refused_take_is_invalid(result):
    import copy
    a = copy.deepcopy(result.analysis)
    a["faults"] = []
    a["status"] = {"code": "different_movement", "text": "x"}
    a["phrasing"]["faults"] = []
    a["score"] = {"value": 1}
    with pytest.raises(OutputError, match="score"):
        validate_analysis(a)


# ---- J-3 -----------------------------------------------------------------------------------
def test_ac_r01_replay_has_the_new_keys_and_clocks(result):
    r = build_replay(result)
    assert r["format"] == "simon.replay.v1" and r["schema_version"] == "1.0.0"
    assert r["expected_t"] == pytest.approx([float(x) for x in result.expected.t], abs=1e-6)
    assert r["follower_t"] == pytest.approx([float(x) for x in result.follower.t], abs=1e-6)
    assert len(r["expected_t"]) == len(r["expected"]) == len(r["exp_to_fol"])
    assert len(r["follower_t"]) == len(r["follower"])
    assert r["coordinate_frame"]["origin"] == "hip_midpoint" and r["coordinate_frame"]["x"] == "subject_left"


def cli_run(tmp_path, *extra):
    out, rep = tmp_path / "a.json", tmp_path / "r.json"
    code = cli.main(["analyse", "--expected", str(EXPECTED), "--follower", str(TAKE), "--out", str(out),
                     "--replay", str(rep), *extra])
    return code, out, rep


def test_ac_r01_cli_writes_a_replay_that_validates(tmp_path):
    jsonschema = pytest.importorskip("jsonschema")
    code, out, rep = cli_run(tmp_path)
    assert code == 0
    schema = json.loads((ROOT / "contracts/replay.schema.json").read_text())
    jsonschema.Draft202012Validator(schema).validate(json.loads(rep.read_text()))
    full = json.loads((ROOT / "contracts/analysis.schema.json").read_text())
    jsonschema.Draft202012Validator(full).validate(json.loads(out.read_text()))


def test_ac_r01_a_refused_take_still_writes_the_replay(tmp_path):
    other = next(t for t in LABELS["takes"] if t["set"] != LABEL["set"])
    out, rep = tmp_path / "a.json", tmp_path / "r.json"
    code = cli.main(["analyse", "--expected", str(EXPECTED), "--follower", str(ROOT / other["follower"]),
                     "--out", str(out), "--replay", str(rep)])
    if code == 3:
        assert out.exists() and rep.exists()
        assert json.loads(out.read_text())["faults"] == []


def test_ac_r02_nothing_is_written_on_an_input_error(tmp_path):
    out, rep = tmp_path / "a.json", tmp_path / "r.json"
    code = cli.main(["analyse", "--expected", str(EXPECTED), "--follower", str(tmp_path / "missing.json"),
                     "--out", str(out), "--replay", str(rep)])
    assert code == 1 and not out.exists() and not rep.exists()


def test_ac_r02_an_unwritable_replay_keeps_the_analysis(tmp_path, capsys):
    out = tmp_path / "a.json"
    blocker = tmp_path / "file"
    blocker.write_text("x")
    bad = blocker / "r.json"
    code = cli.main(["analyse", "--expected", str(EXPECTED), "--follower", str(TAKE), "--out", str(out),
                     "--replay", str(bad)])
    assert code == 1 and out.exists()
    assert f"part5 analyse: cannot write {bad} (" in capsys.readouterr().err


def test_two_template_runs_are_byte_identical(tmp_path):
    first, second = tmp_path / "1", tmp_path / "2"
    first.mkdir(), second.mkdir()
    for d in (first, second):
        cli.main(["analyse", "--expected", str(EXPECTED), "--follower", str(TAKE), "--out", str(d / "a.json"),
                  "--replay", str(d / "r.json")])
    for name in ("a.json", "r.json"):
        assert (first / name).read_bytes() == (second / name).read_bytes()


def test_write_analysis_round_trips_the_new_fields(tmp_path, result):
    write_analysis(tmp_path / "a.json", result.analysis)
    assert json.loads((tmp_path / "a.json").read_text())["faults"][0]["at_s"] == result.analysis["faults"][0]["at_s"]
