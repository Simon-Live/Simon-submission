"""`make score-heldout SEED=<n>` (docs/specs/journey-followup.md AC-S05, ADR-0007): a recorded seed is retired.

Nothing here generates or scores a seed set: the retired seeds are refused before any work, and the rest runs
against an injected runner."""
import hashlib
import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
RECORD = ROOT / "fixtures/score-heldout.json"
needs_make = pytest.mark.skipif(shutil.which("make") is None or shutil.which("uv") is None,
                                reason="the make target runs through make and uv")


def load_script():
    spec = importlib.util.spec_from_file_location("make_score_heldout", ROOT / "scripts/make_score_heldout.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


script = load_script()


def fake_runner(calls, fail_on=None):
    class Done:
        def __init__(self, code):
            self.returncode = code

    def run(command, cwd=None):
        calls.append(command)
        return Done(1 if fail_on is not None and len(calls) == fail_on else 0)
    return run


def record_with(tmp_path, seeds):
    path = tmp_path / "score-heldout.json"
    path.write_text(json.dumps({"format": "simon.part5.score-heldout.v1", "attempts": [{"seed": s} for s in seeds]}))
    return path


def test_the_committed_record_holds_47_and_53():
    assert script.recorded_seeds(RECORD) == [47, 53]


@pytest.mark.parametrize("seed", ["47", "53"])
def test_ac_s05_a_recorded_seed_is_refused_with_exit_2_before_any_work(seed, capsys):
    calls = []
    code = script.main([seed], run=fake_runner(calls))
    err = capsys.readouterr().err
    assert code == 2 and calls == []
    assert f"seed {seed} is already recorded in fixtures/score-heldout.json" in err
    assert "recorded seeds are retired" in err


@needs_make
@pytest.mark.parametrize("seed", ["47", "53"])
def test_ac_s05_make_refuses_a_recorded_seed_with_exit_2_and_makes_no_directory(seed):
    target = ROOT / "out" / "score-heldout" / f"seed-{seed}"
    before = target.exists()
    result = subprocess.run(["make", "score-heldout", f"SEED={seed}"], capture_output=True, text=True, cwd=ROOT)
    assert result.returncode == 2
    assert f"seed {seed} is already recorded" in result.stderr and "retired" in result.stderr
    assert target.exists() == before   # the refusal generated nothing


@needs_make
@pytest.mark.parametrize("args,words", [([], "SEED is required"), (["SEED=4x7"], "must be a whole number"),
                                        (["SEED=-3"], "must be a whole number"), (["SEED=1;2"], "must be a whole number")])
def test_ac_s05_make_needs_a_whole_number_seed(args, words):
    result = subprocess.run(["make", "score-heldout", *args], capture_output=True, text=True, cwd=ROOT)
    assert result.returncode == 2 and words in result.stderr


@needs_make
def test_make_dry_run_shows_the_recipe_without_running_it():
    result = subprocess.run(["make", "-n", "score-heldout", "SEED=99"], capture_output=True, text=True, cwd=ROOT)
    assert result.returncode == 0 and "scripts/make_score_heldout.py 99" in result.stdout


def test_a_new_seed_runs_the_recorded_commands_in_order_and_prints_the_labels_hash(tmp_path, capsys):
    calls, out_root = [], tmp_path / "out"
    (out_root / "seed-99").mkdir(parents=True)
    (out_root / "seed-99" / "labels.json").write_bytes(b"{}\n")
    code = script.main(["99"], record=record_with(tmp_path, [47, 53]), out_root=out_root, run=fake_runner(calls))
    out = capsys.readouterr().out
    assert code == 0 and len(calls) == 2
    generator, scorer = calls
    assert generator[1].endswith("scripts/make_dummy_followers.py")
    assert generator[2:] == ["--seed", "99", "--out", str(out_root / "seed-99"), "--dropout-variant"]
    assert scorer[1:] == ["-m", "part5.score_report", "--set", str(out_root / "seed-99")]
    assert f"labels.json sha256 {hashlib.sha256(b'{}' + bytes([10])).hexdigest()}" in out
    assert "scored once" in out and "then it is retired" in out


def test_the_commands_are_the_ones_the_47_and_53_records_name():
    attempts = json.loads(RECORD.read_text())["attempts"]
    generator, scorer, out = script.commands(47, Path("<temp dir>"))
    assert attempts[0]["generator"] == "python3 scripts/make_dummy_followers.py --seed 47 --out <temp dir>/seed-47 --dropout-variant"
    assert generator[2:] == ["--seed", "47", "--out", "<temp dir>/seed-47", "--dropout-variant"]
    assert attempts[0]["scorer"] == "python -m part5.score_report --set <temp dir>/seed-47"
    assert scorer[1:] == ["-m", "part5.score_report", "--set", "<temp dir>/seed-47"] and str(out) == "<temp dir>/seed-47"


def test_a_failing_generator_stops_the_run_with_exit_1(tmp_path, capsys):
    calls = []
    code = script.main(["99"], record=record_with(tmp_path, [47]), out_root=tmp_path, run=fake_runner(calls, fail_on=1))
    assert code == 1 and len(calls) == 1 and "failed: python3" in capsys.readouterr().err


def test_a_failing_scorer_exits_1(tmp_path, capsys):
    (tmp_path / "seed-99").mkdir()
    (tmp_path / "seed-99" / "labels.json").write_text("{}")
    calls = []
    code = script.main(["99"], record=record_with(tmp_path, [47]), out_root=tmp_path, run=fake_runner(calls, fail_on=2))
    assert code == 1 and len(calls) == 2 and "failed: python3 -m part5.score_report" in capsys.readouterr().err


def test_dry_run_prints_the_two_commands_and_runs_nothing(tmp_path, capsys):
    calls = []
    code = script.main(["99", "--dry-run"], record=record_with(tmp_path, [47]), out_root=tmp_path, run=fake_runner(calls))
    out = capsys.readouterr().out
    assert code == 0 and calls == [] and out.count("score-heldout: python3 ") == 2


def test_an_unreadable_record_refuses_rather_than_guessing(tmp_path, capsys):
    code = script.main(["99"], record=tmp_path / "missing.json", out_root=tmp_path, run=fake_runner([]))
    assert code == 2 and "cannot read" in capsys.readouterr().err


def test_a_seed_that_is_not_a_number_is_refused(capsys):
    assert script.main(["forty-seven"], run=fake_runner([])) == 2
    assert "must be a whole number" in capsys.readouterr().err
