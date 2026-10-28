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
    assert "2 faults" in stdout and "left foot slightly too far out" in stdout


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


def test_far_too_fast_follower_exits_1(tmp_path, capsys):
    doc = json.loads((ROOT / EXPECTED).read_text())
    fast = tmp_path / "fast.json"
    _write_clip(fast, doc, range(0, len(doc["frames"]), 3))
    assert cli.main(["analyse", "--expected", str(ROOT / EXPECTED), "--follower", str(fast),
                     "--out", str(tmp_path / "a.json")]) == 1
    assert "cannot align" in capsys.readouterr().err


def test_far_too_slow_follower_warns(tmp_path, capsys):
    doc = json.loads((ROOT / EXPECTED).read_text())
    slow = tmp_path / "slow.json"
    _write_clip(slow, doc, [k for k in range(len(doc["frames"])) for _ in range(3)])
    out = tmp_path / "a.json"
    assert cli.main(["analyse", "--expected", str(ROOT / EXPECTED), "--follower", str(slow), "--out", str(out)]) == 0
    assert json.loads(out.read_text())["diagnostics"]["warnings"]
    assert "warning:" in capsys.readouterr().err


def test_follower_with_no_usable_joints_exits_1(tmp_path, capsys):
    doc = json.loads((ROOT / EXPECTED).read_text())
    for f in doc["frames"]:
        f["conf"] = {j: 0.0 for j in f["joints"]}
    blind = tmp_path / "blind.json"
    blind.write_text(json.dumps(doc))
    assert cli.main(["analyse", "--expected", str(ROOT / EXPECTED), "--follower", str(blind),
                     "--out", str(tmp_path / "a.json")]) == 1
    assert "could be measured" in capsys.readouterr().err


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
