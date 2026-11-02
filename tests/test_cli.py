import json
from pathlib import Path

import pytest

from part5 import cli

ROOT = Path(__file__).resolve().parent.parent
EXPECTED = "fixtures/input/expected/exercise/animation.json"
EXAMPLE = ROOT / "fixtures/output/analysis.example.json"


def test_help_lists_analyse(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--help"])
    assert exc.value.code == 0
    assert "analyse" in capsys.readouterr().out


def test_analyse_requires_inputs():
    with pytest.raises(SystemExit) as exc:
        cli.main(["analyse"])
    assert exc.value.code == 2


def test_analyse_reproduces_the_shipped_example(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(ROOT)
    example = json.loads(EXAMPLE.read_text())
    out = tmp_path / "analysis.json"
    assert cli.main(["analyse", "--expected", example["expected"]["path"],
                     "--follower", example["follower"]["path"], "--out", str(out)]) == 0
    got = json.loads(out.read_text())
    # The CLI only knows the paths; the example script also passes ids through.
    assert got["expected"]["path"] == example["expected"]["path"]
    assert got["follower"]["path"] == example["follower"]["path"]
    assert got["faults"] == example["faults"]
    assert got["diagnostics"] == example["diagnostics"]
    stdout = capsys.readouterr().out
    n = len(example["faults"])
    assert f"{n} fault" in stdout and all(f["text"] in stdout for f in example["faults"])


def test_ok_take_exits_0_and_the_file_says_ok(tmp_path, monkeypatch):
    monkeypatch.chdir(ROOT)
    example = json.loads(EXAMPLE.read_text())
    out = tmp_path / "analysis.json"
    assert cli.main(["analyse", "--expected", example["expected"]["path"],
                     "--follower", example["follower"]["path"], "--out", str(out)]) == 0
    assert json.loads(out.read_text())["status"]["code"] == "ok"


def test_ac004_a_take_of_another_movement_exits_0_with_a_low_match_warning_and_grade_f(tmp_path, monkeypatch, capsys):
    """AC-004, ADR-0012: status ok, a `low_match` warning, grade F, exit 0; the warning text is printed."""
    monkeypatch.chdir(ROOT)
    out = tmp_path / "analysis.json"
    code = cli.main(["analyse", "--expected", EXPECTED,
                     "--follower", "fixtures/input/followers/dance/dance_front_good_00_correct/skeleton.json",
                     "--out", str(out)])
    assert code == 0
    doc = json.loads(out.read_text())
    assert doc["status"]["code"] == "ok" and doc["schema_version"] == "1.12.0"
    assert [w["code"] for w in doc["warnings"]] == ["low_match"] and doc["match"]["quality"] == "low"
    assert doc["score"]["grade"] == "F" and doc["score"]["value"] <= 59
    assert all(f["confidence"] == "low" for f in doc["faults"])
    assert doc["warnings"][0]["text"] in capsys.readouterr().out
    from part5.output import load_analysis
    assert load_analysis(out) == doc  # a valid analysis.json was written


def test_bad_input_exits_1_with_the_file_named(tmp_path, capsys):
    bad = tmp_path / "skeleton.json"
    bad.write_text('{"format": "simon.animation.v1"}')
    assert cli.main(["analyse", "--expected", str(ROOT / EXPECTED), "--follower", str(bad),
                     "--out", str(tmp_path / "a.json")]) == 1
    err = capsys.readouterr().err
    assert str(bad) in err
    assert not (tmp_path / "a.json").exists()


def test_missing_file_exits_1(tmp_path, capsys):
    assert cli.main(["analyse", "--expected", str(ROOT / EXPECTED), "--follower", str(tmp_path / "nope.json"),
                     "--out", str(tmp_path / "a.json")]) == 1
    assert "nope.json" in capsys.readouterr().err


def _write_clip(path, doc, keep):
    doc = dict(doc)
    doc["frames"] = [dict(f, index=i, t=i / doc["fps"]) for i, f in enumerate(doc["frames"][k] for k in keep)]
    doc["frame_count"] = len(doc["frames"])
    doc["duration_s"] = doc["frame_count"] / doc["fps"]
    path.write_text(json.dumps(doc))


def test_far_too_fast_follower_is_analysed_unaligned_with_grade_f(tmp_path, capsys):
    doc = json.loads((ROOT / EXPECTED).read_text())
    fast = tmp_path / "fast.json"
    _write_clip(fast, doc, range(0, len(doc["frames"]), 3))
    out = tmp_path / "a.json"
    assert cli.main(["analyse", "--expected", str(ROOT / EXPECTED), "--follower", str(fast), "--out", str(out)]) == 0
    doc = json.loads(out.read_text())
    assert [w["code"] for w in doc["warnings"]] == ["low_match"] and doc["faults"] == []
    assert doc["match"]["residual"] is None and doc["score"]["value"] == 0 and doc["score"]["grade"] == "F"


def test_far_too_slow_follower_warns_and_is_a_low_match(tmp_path, capsys):
    """Three times slower than the example is past what the alignment can follow: the span
    warning is still written, and the take is a low match graded F (exit 0, ADR-0012)."""
    doc = json.loads((ROOT / EXPECTED).read_text())
    slow = tmp_path / "slow.json"
    _write_clip(slow, doc, [k for k in range(len(doc["frames"])) for _ in range(3)])
    out = tmp_path / "a.json"
    assert cli.main(["analyse", "--expected", str(ROOT / EXPECTED), "--follower", str(slow), "--out", str(out)]) == 0
    written = json.loads(out.read_text())
    assert written["diagnostics"]["warnings"] and written["status"]["code"] == "ok"
    assert written["score"]["grade"] == "F" and "low_match" in [w["code"] for w in written["warnings"]]
    assert "warning:" in capsys.readouterr().err


def test_a_follower_twice_as_slow_is_still_compared(tmp_path):
    doc = json.loads((ROOT / EXPECTED).read_text())
    slow = tmp_path / "slow.json"
    _write_clip(slow, doc, [k for k in range(len(doc["frames"])) for _ in range(2)])
    out = tmp_path / "a.json"
    assert cli.main(["analyse", "--expected", str(ROOT / EXPECTED), "--follower", str(slow), "--out", str(out)]) == 0
    assert json.loads(out.read_text())["status"]["code"] == "ok"


def test_follower_with_no_usable_joints_is_analysed_with_no_usable_measures(tmp_path, capsys):
    doc = json.loads((ROOT / EXPECTED).read_text())
    for f in doc["frames"]:
        f["conf"] = {j: 0.0 for j in f["joints"]}
        f["joints"] = {j: None for j in f["joints"]}
    blind = tmp_path / "blind.json"
    blind.write_text(json.dumps(doc))
    out = tmp_path / "a.json"
    assert cli.main(["analyse", "--expected", str(ROOT / EXPECTED), "--follower", str(blind), "--out", str(out)]) == 0
    doc = json.loads(out.read_text())
    assert [w["code"] for w in doc["warnings"]] == ["no_usable_measures"] and doc["faults"] == []
    assert doc["score"]["value"] == 0 and doc["score"]["grade"] == "F"


def test_unwritable_out_exits_1(tmp_path, capsys):
    example = json.loads(EXAMPLE.read_text())
    assert cli.main(["analyse", "--expected", str(ROOT / example["expected"]["path"]),
                     "--follower", str(ROOT / example["follower"]["path"]), "--out", str(tmp_path)]) == 1
    assert "cannot write" in capsys.readouterr().err


@pytest.mark.parametrize("ref", [42, ["a"], {"take_id": "x"}, {"path": ""}, {"path": 3}, None])
def test_bad_refs_raise_analysis_error(ref):
    from part5.pipeline import AnalysisError, analyse
    with pytest.raises(AnalysisError, match="expected must be"):
        analyse(ref, str(ROOT / EXPECTED))



def test_analyse_takes_a_phrasing_backend_and_refuses_an_unknown_one(tmp_path):
    """AC-010 error case: an unknown --phrasing exits 2 (argparse); template writes coaching = text."""
    fol = ROOT / "fixtures/input/followers/exercise/exercise_45_good_02_arms_wider-left/skeleton.json"
    args = ["analyse", "--expected", str(ROOT / EXPECTED), "--follower", str(fol)]
    with pytest.raises(SystemExit) as exc:
        cli.main(args + ["--out", str(tmp_path / "a.json"), "--phrasing", "nope"])
    assert exc.value.code == 2
    out = tmp_path / "b.json"
    assert cli.main(args + ["--out", str(out), "--phrasing", "template"]) == 0
    doc = json.loads(out.read_text())
    assert doc["phrasing"]["backend"] == "template"
    assert all(f["coaching"] == f["text_timed"] for f in doc["faults"])  # ADR-0008: the template line is timed
