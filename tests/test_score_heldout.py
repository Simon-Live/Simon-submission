"""`make score-heldout SEED=<n>` (docs/specs/journey-followup.md AC-S05, ADR-0007): a recorded seed is retired.

Nothing here generates or scores a seed set: the retired seeds are refused before any work, and the rest runs
against an injected runner."""
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
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


HELD_OUT = ["29", "31", "37", "67", "71", "73"]   # both series of detection seeds (ADR-0003, ADR-0017)


@pytest.mark.parametrize("seed", HELD_OUT)
def test_adr_0017_every_held_out_detection_seed_is_refused_before_any_work(seed, capsys, tmp_path):
    """A seed of either series is refused whether or not it was generated and scored: scoring it here would look at it
    before its attempt's freeze commit. Nothing is generated and the record is not even read."""
    calls = []
    code = script.main([seed], record=tmp_path / "missing.json", out_root=tmp_path, run=fake_runner(calls))
    err = capsys.readouterr().err
    assert code == 2 and calls == []
    assert f"seed {seed} is a held-out detection seed" in err and "ADR-0017" in err and "never here" in err


def test_the_refused_seeds_are_the_checks_own_list():
    from part5.check import HELDOUT_SEEDS
    assert script.detection_seeds() == HELDOUT_SEEDS == (29, 31, 37, 67, 71, 73)


def test_r8_run_directly_the_script_finds_the_package_without_an_install(monkeypatch):
    """Pre-freeze review R8: `python3 scripts/make_score_heldout.py 67` only worked through `uv run` (the editable install).
    The lazy import now puts the repo root on the path itself, so the refusal does not depend on the install."""
    import sys
    monkeypatch.setattr(sys, "path", [p for p in sys.path if Path(p or ".").resolve() != ROOT])
    assert script.detection_seeds() == (29, 31, 37, 67, 71, 73)
    assert str(ROOT) in sys.path


REPO_NOT_INSTALLED = """
import os, runpy, sys
root = os.path.realpath({root!r})
# the repo is on the path in this environment through the editable install's .pth file: take every such entry out, as
# on a machine where `part5` is not installed, so only the script's own sys.path insert can make `part5` importable
sys.path[:] = [p for p in sys.path if p and os.path.realpath(p) != root]
sys.argv = ["make_score_heldout.py", {seed!r}]
runpy.run_path({script!r}, run_name="__main__")
"""


def run_without_the_install(seed, cwd):
    """The script run as `python -I scripts/make_score_heldout.py <seed>` would on a checkout where `part5` is not
    installed: isolated mode (no PYTHON* variables, no user site, no script directory on the path) and the repo taken off
    the path. The dependencies stay importable."""
    code = REPO_NOT_INSTALLED.format(root=str(ROOT), seed=seed, script=str(ROOT / "scripts/make_score_heldout.py"))
    return subprocess.run([sys.executable, "-I", "-c", code], cwd=cwd, capture_output=True, text=True)


def test_r8_the_script_run_without_the_install_refuses_a_held_out_seed_with_exit_2_and_generates_nothing(tmp_path):
    """Recheck residual 6: this run fails without the `sys.path` insert of `detection_seeds` (the import of `part5.check`
    raises, exit 1, and the refusal never prints); with it, the refusal is the plain one and nothing is generated."""
    done = run_without_the_install("67", tmp_path)
    assert done.returncode == 2, done.stderr
    assert "seed 67 is a held-out detection seed" in done.stderr
    assert not (ROOT / "out" / "score-heldout" / "seed-67").exists()


def test_r8_the_stripped_environment_cannot_import_part5_on_its_own(tmp_path):
    """The check above means something only if `part5` is not importable without the script's insert."""
    code = REPO_NOT_INSTALLED.format(root=str(ROOT), seed="67", script=str(ROOT / "scripts/make_score_heldout.py"))
    probe = code.split("sys.argv")[0] + "import importlib.util\nsys.exit(0 if importlib.util.find_spec('part5') is None else 3)\n"
    done = subprocess.run([sys.executable, "-I", "-c", probe], cwd=tmp_path, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr


@needs_make
@pytest.mark.parametrize("seed", ["67", "71", "73"])
def test_adr_0017_make_refuses_a_seed_of_the_second_series_and_makes_no_directory(seed):
    target = ROOT / "out" / "score-heldout" / f"seed-{seed}"
    before = target.exists()
    result = subprocess.run(["make", "score-heldout", f"SEED={seed}"], capture_output=True, text=True, cwd=ROOT)
    assert result.returncode == 2
    assert f"seed {seed} is a held-out detection seed" in result.stderr
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
