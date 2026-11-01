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

from shipped_score import IS_V2, V2, frozen_v1, v2_block

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


def v2_report(holds=True):
    """The JSON report `score_report --json-out` writes for a v2 seed, as far as the script reads it."""
    verdict = lambda v: {"verdict": v, "n": 3, "breaks": []}   # noqa: E731
    return {"seed": 59, "version": "simon.score.v2", "distribution": {"good/0": {"n": 20, "grades": {"A": 20}}},
            "targets_v2": {"correct_all_a": verdict("pass"), "no_reported_fault_grades_a": verdict("pass"),
                           "single_b_or_c": verdict("pass" if holds else "fail"), "double_c_d_or_f": verdict("pass"),
                           "not_judged": [], "sweep_failures": [], "holds": holds}}


def v2_runner(out_root, calls, holds=True, report=True):
    """A `run` that writes what the generator and the scorer of seed 59 write: `labels.json`, then `report.json`."""
    class Done:
        returncode = 0

    def run(command, cwd=None):
        calls.append(command)
        out = Path(out_root) / "seed-59"
        if command[1].endswith("make_dummy_followers.py"):
            out.mkdir(parents=True)
            (out / "labels.json").write_text("{}")
        elif report:
            (out / "report.json").write_text(json.dumps(v2_report(holds)))
        return Done()
    return run


def record_with(tmp_path, seeds):
    path = tmp_path / "score-heldout.json"
    path.write_text(json.dumps({"format": "simon.part5.score-heldout.v1", "attempts": [{"seed": s} for s in seeds]}))
    return path


def test_the_committed_record_holds_47_and_53():
    assert script.recorded_seeds(RECORD)[:2] == [47, 53]   # and 59 once it is scored (ADR-0018); never 61


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


# ---------------------------------------------------------------- score v2 (ADR-0018): seed 59 needs the freeze, 61 is reserved
def git_stub(freeze_known=True, dirty="", untracked="", changed="", head="0123456789abcdef"):
    """A `git(root, *args)` answering as a repository would: the freeze commit known or not, `dirty` and `untracked` the
    porcelain lines, `changed` the files that differ from the freeze commit under part5, scripts and contracts."""
    def git(root, *args):
        if args[0] == "rev-parse" and "--verify" in args:
            return (0 if freeze_known else 1), ""
        if args[0] == "rev-parse":
            return 0, head + "\n"
        if args[0] == "status":
            return 0, untracked if "--untracked-files=all" in args else dirty
        if args[0] == "diff":
            return 0, changed
        raise AssertionError(args)
    return git


CLEAN = git_stub()


def v2_world(tmp_path, freeze_hash="shipped", seeds=(47, 53), version_block=None):
    """(record, rules): a temp copy of the shipped rules and a record with `seeds` as attempts and, unless `freeze_hash` is
    None, a v2 freeze with that hash ("shipped": the hash of the copy's `score` block)."""
    rules = tmp_path / "rules.json"
    doc = json.loads((ROOT / "part5/rules.json").read_text())
    doc["score"] = version_block if version_block is not None else v2_block()
    rules.write_text(json.dumps(doc))
    shipped = hashlib.sha256(json.dumps(json.loads(rules.read_text())["score"], sort_keys=True,
                                        separators=(",", ":")).encode()).hexdigest()
    freezes = [] if freeze_hash is None else [{"version": V2, "freeze_commit": "abc1234", "seed": 59,
                                               "params_sha256": shipped if freeze_hash == "shipped" else freeze_hash}]
    record = tmp_path / "score-heldout.json"
    record.write_text(json.dumps({"format": "simon.part5.score-heldout.v1",
                                  "attempts": [{"seed": s} for s in seeds], "freezes": freezes}))
    return record, rules


def test_adr_0018_seed_59_is_refused_with_exit_2_until_the_v2_freeze_is_recorded(tmp_path, capsys):
    record, rules = v2_world(tmp_path, freeze_hash=None)
    calls = []
    code = script.main(["59"], record=record, rules=rules, out_root=tmp_path, run=fake_runner(calls), git=CLEAN)
    err = capsys.readouterr().err
    assert code == 2 and calls == []
    assert "seed 59 needs the simon.score.v2 freeze" in err and "has no `freezes` entry" in err and "ADR-0018" in err
    assert "--params-sha256" in err


def test_adr_0018_seed_59_is_refused_when_the_freeze_is_of_other_params(tmp_path, capsys):
    record, rules = v2_world(tmp_path, freeze_hash="f" * 64)
    calls = []
    code = script.main(["59"], record=record, rules=rules, out_root=tmp_path, run=fake_runner(calls), git=CLEAN)
    err = capsys.readouterr().err
    assert code == 2 and calls == [] and "seed 59 needs the score params frozen" in err and "ffffffffffff" in err


def test_adr_0018_seed_59_runs_once_the_freeze_of_the_shipped_params_is_recorded(tmp_path, capsys):
    record, rules = v2_world(tmp_path)
    calls = []
    code = script.main(["59"], record=record, rules=rules, out_root=tmp_path, run=v2_runner(tmp_path, calls), git=CLEAN)
    out = capsys.readouterr().out
    assert code == 0 and len(calls) == 2
    assert calls[0][2:] == ["--seed", "59", "--out", str(tmp_path / "seed-59"), "--dropout-variant"]
    assert calls[1][-2:] == ["--json-out", str(tmp_path / "seed-59" / "report.json")]   # the v2 seed's scorer writes its JSON
    assert "seed 59 scored once" in out and "the line to append to `attempts`" in out
    assert "scored_at 0123456789abcdef" in out and "holds true" in out


def test_adr_0018_seed_59_is_refused_when_the_rules_do_not_ship_v2(tmp_path, capsys):
    record, rules = v2_world(tmp_path, version_block=frozen_v1())
    code = script.main(["59"], record=record, rules=rules, out_root=tmp_path, run=fake_runner([]), git=CLEAN)
    assert code == 2 and "ships simon.score.v1" in capsys.readouterr().err


def test_adr_0018_seed_59_once_recorded_is_retired_whatever_the_freeze(tmp_path, capsys):
    record, rules = v2_world(tmp_path, seeds=(47, 53, 59))
    code = script.main(["59"], record=record, rules=rules, out_root=tmp_path, run=fake_runner([]), git=CLEAN)
    assert code == 2 and "seed 59 is already recorded" in capsys.readouterr().err


@pytest.mark.parametrize("freeze", [None, "shipped"])
def test_adr_0018_seed_61_is_reserved_with_or_without_a_freeze(tmp_path, capsys, freeze):
    record, rules = v2_world(tmp_path, freeze_hash=freeze)
    calls = []
    code = script.main(["61"], record=record, rules=rules, out_root=tmp_path, run=fake_runner(calls), git=CLEAN)
    err = capsys.readouterr().err
    assert code == 2 and calls == [] and "seed 61 is reserved" in err and "new approach family" in err


def test_adr_0018_other_seeds_are_as_before_and_need_no_freeze(tmp_path):
    record, rules = v2_world(tmp_path, freeze_hash=None)
    def no_git(root, *args):
        raise AssertionError("only seed 59 asks git")
    assert script.check_seed("99", record, rules, git=no_git) == 99


def test_adr_0018_the_committed_record_refuses_seed_59_until_the_orchestrator_records_the_v2_freeze(tmp_path):
    """`freezes` is the orchestrator's: this change commits an empty list, so seed 59 is refused until it is filled.
    `check_seed` only reads; it generates and scores nothing."""
    doc = json.loads(RECORD.read_text())
    assert all(f["version"] == V2 and len(f["params_sha256"]) == 64 for f in doc["freezes"])
    scored = {a["seed"] for a in doc["attempts"]}
    if 59 in scored:   # R1: once seed 59 is scored (the publication commit) it is retired, pass or fail
        with pytest.raises(script.Refused, match="seed 59 is already recorded"):
            script.check_seed("59", out_root=tmp_path)
    elif not IS_V2:
        with pytest.raises(script.Refused, match="ships simon.score.v1"):
            script.check_seed("59", out_root=tmp_path)
    elif not doc["freezes"]:
        with pytest.raises(script.Refused, match="needs the simon.score.v2 freeze"):
            script.check_seed("59", out_root=tmp_path)
    else:   # recorded and not yet scored: 59 is accepted exactly when the freeze is the shipped block's (git stubbed)
        assert script.check_seed("59", git=CLEAN, out_root=tmp_path) == 59


@needs_make
def test_adr_0018_make_refuses_the_reserved_seed_and_makes_no_directory():
    target = ROOT / "out" / "score-heldout" / "seed-61"
    before = target.exists()
    result = subprocess.run(["make", "score-heldout", "SEED=61"], capture_output=True, text=True, cwd=ROOT)
    assert result.returncode == 2 and "seed 61 is reserved" in result.stderr and target.exists() == before


@needs_make
def test_adr_0018_make_dry_run_for_seed_59_is_only_a_listing():
    """Only `-n`: a real `make score-heldout SEED=59` generates and scores the seed, which happens once, after the freeze."""
    result = subprocess.run(["make", "-n", "score-heldout", "SEED=59"], capture_output=True, text=True, cwd=ROOT)
    assert result.returncode == 0 and "scripts/make_score_heldout.py 59" in result.stdout


# ---------------------------------------------------------------- N3: the score code is frozen with the params
def test_n3_the_freeze_commit_must_be_named_and_known(tmp_path, capsys):
    record, rules = v2_world(tmp_path)
    doc = json.loads(record.read_text())
    del doc["freezes"][0]["freeze_commit"]
    record.write_text(json.dumps(doc))
    with pytest.raises(script.Refused, match="name its freeze_commit"):
        script.check_seed("59", record, rules, out_root=tmp_path, git=CLEAN)
    other = tmp_path / "other"
    other.mkdir()
    record, rules = v2_world(other)
    with pytest.raises(script.Refused, match="is not in this repository's history"):
        script.check_seed("59", record, rules, out_root=tmp_path, git=git_stub(freeze_known=False))


def test_n3_a_tree_with_uncommitted_changes_is_refused_naming_them(tmp_path):
    record, rules = v2_world(tmp_path)
    with pytest.raises(script.Refused, match=r"clean tree only.*part5/score.py"):
        script.check_seed("59", record, rules, out_root=tmp_path, git=git_stub(dirty=" M part5/score.py\n"))


def test_n3_an_untracked_file_under_the_code_paths_is_refused(tmp_path):
    record, rules = v2_world(tmp_path)
    with pytest.raises(script.Refused, match=r"clean tree only.*scripts/new.py"):
        script.check_seed("59", record, rules, out_root=tmp_path, git=git_stub(untracked="?? scripts/new.py\n"))


def test_n3_code_that_differs_from_the_freeze_commit_is_refused_naming_the_files(tmp_path):
    record, rules = v2_world(tmp_path)
    with pytest.raises(script.Refused, match=r"frozen with the code of abc1234.*2 file\(s\).*part5/score.py.*contracts/a.json"):
        script.check_seed("59", record, rules, out_root=tmp_path, git=git_stub(changed="part5/score.py\ncontracts/a.json\n"))


def test_n3_a_clean_tree_at_the_freeze_code_is_accepted(tmp_path):
    record, rules = v2_world(tmp_path)
    assert script.check_seed("59", record, rules, out_root=tmp_path, git=CLEAN) == 59


def test_n3_the_main_path_asks_git_for_the_diff_of_the_code_paths_only(tmp_path):
    seen = []
    record, rules = v2_world(tmp_path)

    def git(root, *args):
        seen.append(args)
        return CLEAN(root, *args)
    script.check_seed("59", record, rules, out_root=tmp_path, git=git)
    diff = next(a for a in seen if a[0] == "diff")
    assert diff == ("diff", "--name-only", "abc1234", "HEAD", "--", "part5", "scripts", "contracts", "fixtures/input/expected",
                    "fixtures/input/expected-feet", "pyproject.toml", "uv.lock")


needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


def real_repo(tmp_path):
    """A small repository: the code frozen at one commit, then the record in a second that touches only
    fixtures/score-heldout.json and docs/thresholds.md. Returns (root, record, rules, freeze_commit, git helper)."""
    repo = tmp_path / "repo"
    for d in ("part5", "scripts", "contracts", "fixtures/input/expected/exercise", "fixtures/input/expected-feet/exercise",
              "fixtures/input/heldout", "docs"):
        (repo / d).mkdir(parents=True)

    def git(*args):
        done = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false",
                               "-C", str(repo), *args], capture_output=True, text=True)
        assert done.returncode == 0, done.stderr
        return done.stdout.strip()
    git("init", "-q")
    rules = repo / "part5" / "rules.json"
    rules.write_text(json.dumps({"score": v2_block()}))
    (repo / "part5" / "score.py").write_text("x = 1\n")
    (repo / "scripts" / "run.py").write_text("y = 1\n")
    (repo / "contracts" / "c.json").write_text("{}")
    (repo / "fixtures/input/expected/exercise/animation.json").write_text("{}")
    (repo / "fixtures/input/expected-feet/exercise/feet.json").write_text("{}")
    (repo / "fixtures/input/heldout/labels.json").write_text("{}")
    (repo / "pyproject.toml").write_text("[project]\n")
    (repo / "uv.lock").write_text("lock = 1\n")
    git("add", "-A")
    git("commit", "-q", "-m", "freeze")
    commit = git("rev-parse", "HEAD")
    sha = hashlib.sha256(json.dumps(v2_block(), sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    record = repo / "fixtures" / "score-heldout.json"
    record.write_text(json.dumps({"attempts": [{"seed": 47}, {"seed": 53}],
                                  "freezes": [{"version": V2, "freeze_commit": commit, "params_sha256": sha, "seed": 59}]}))
    (repo / "docs" / "thresholds.md").write_text("freeze recorded\n")
    git("add", "-A")
    git("commit", "-q", "-m", "record the freeze")
    return repo, record, rules, commit, git


@needs_git
def test_n3_real_git_the_freeze_records_own_commit_is_allowed_and_a_clean_tree_is_accepted(tmp_path):
    repo, record, rules, commit, git = real_repo(tmp_path)
    assert script.check_seed("59", record, rules, repo, out_root=tmp_path) == 59


@needs_git
def test_n3_real_git_a_code_commit_after_the_freeze_is_refused(tmp_path):
    repo, record, rules, commit, git = real_repo(tmp_path)
    (repo / "part5" / "score.py").write_text("x = 2\n")
    git("commit", "-q", "-am", "edit the score code after the freeze")
    with pytest.raises(script.Refused, match=r"frozen with the code of .*part5/score.py"):
        script.check_seed("59", record, rules, repo, out_root=tmp_path)


@needs_git
def test_n3_real_git_a_later_commit_that_touches_only_the_record_and_the_docs_is_allowed(tmp_path):
    repo, record, rules, commit, git = real_repo(tmp_path)
    (repo / "docs" / "thresholds.md").write_text("more\n")
    record.write_text(record.read_text() + " ")
    git("commit", "-q", "-am", "docs and record only")
    assert script.check_seed("59", record, rules, repo, out_root=tmp_path) == 59


@needs_git
def test_n3_real_git_an_uncommitted_edit_and_an_untracked_code_file_are_refused(tmp_path):
    repo, record, rules, commit, git = real_repo(tmp_path)
    (repo / "scripts" / "run.py").write_text("y = 2\n")
    with pytest.raises(script.Refused, match=r"clean tree only.*scripts/run.py"):
        script.check_seed("59", record, rules, repo, out_root=tmp_path)
    git("checkout", "--", "scripts/run.py")
    (repo / "part5" / "extra.py").write_text("z = 1\n")
    with pytest.raises(script.Refused, match=r"clean tree only.*part5/extra.py"):
        script.check_seed("59", record, rules, repo, out_root=tmp_path)


@needs_git
def test_n3_real_git_a_freeze_commit_that_is_not_in_the_history_is_refused(tmp_path):
    repo, record, rules, commit, git = real_repo(tmp_path)
    doc = json.loads(record.read_text())
    doc["freezes"][0]["freeze_commit"] = "f" * 40
    record.write_text(json.dumps(doc))
    git("commit", "-q", "-am", "a freeze commit that does not exist")
    with pytest.raises(script.Refused, match="is not in this repository's history"):
        script.check_seed("59", record, rules, repo, out_root=tmp_path)


# ---------------------------------------------------------------- N4: the scorer reports holds, and a failed seed 59 is on the record
def test_n4_a_v2_seed_with_holds_false_is_printed_with_the_way_back(tmp_path, capsys):
    record, rules = v2_world(tmp_path)
    code = script.main(["59"], record=record, rules=rules, out_root=tmp_path, run=v2_runner(tmp_path, [], holds=False), git=CLEAN)
    out = capsys.readouterr().out
    assert code == 0 and "holds false" in out and "make score-fallback" in out


def test_n4_a_report_without_holds_fails_the_run_so_the_attempt_cannot_be_recorded_without_it(tmp_path, capsys):
    record, rules = v2_world(tmp_path)
    code = script.main(["59"], record=record, rules=rules, out_root=tmp_path, run=v2_runner(tmp_path, [], report=False), git=CLEAN)
    assert code == 1 and "cannot read `holds`" in capsys.readouterr().err


# ---------------------------------------------------------------- R-b: data and dependencies are frozen with the code
@needs_git
@pytest.mark.parametrize("path", ["uv.lock", "pyproject.toml", "fixtures/input/expected/exercise/animation.json",
                                  "fixtures/input/expected-feet/exercise/feet.json"])
def test_rb_real_git_a_change_to_the_trainers_clips_or_the_dependencies_after_the_freeze_is_refused(tmp_path, path):
    repo, record, rules, commit, git = real_repo(tmp_path)
    (repo / path).write_text("changed after the freeze\n")
    git("commit", "-q", "-am", f"change {path}")
    with pytest.raises(script.Refused, match=rf"frozen with the code of .*{path}"):
        script.check_seed("59", record, rules, repo, out_root=tmp_path)


@needs_git
def test_rb_real_git_a_change_to_a_set_that_is_not_the_scores_input_is_allowed(tmp_path):
    repo, record, rules, commit, git = real_repo(tmp_path)
    (repo / "fixtures/input/heldout/labels.json").write_text('{"seed": 73}')
    git("commit", "-q", "-am", "the detection held-out set is not a score input")
    assert script.check_seed("59", record, rules, repo, out_root=tmp_path) == 59


def test_rb_the_code_paths_name_the_data_and_the_dependencies():
    assert {"part5", "scripts", "contracts", "fixtures/input/expected", "fixtures/input/expected-feet", "pyproject.toml",
            "uv.lock"} == set(script.CODE_PATHS)


# ---------------------------------------------------------------- R-a: one freeze, one generation
def test_ra_a_record_with_two_v2_freezes_refuses_seed_59(tmp_path):
    record, rules = v2_world(tmp_path)
    doc = json.loads(record.read_text())
    doc["freezes"].append({**doc["freezes"][0], "freeze_commit": "def5678"})   # a re-freeze after seeing the seed
    record.write_text(json.dumps(doc))
    with pytest.raises(script.Refused, match=r"holds 2 simon.score.v2 freeze entries.*re-freeze"):
        script.check_seed("59", record, rules, out_root=tmp_path, git=CLEAN)


def test_ra_a_v1_freeze_beside_the_v2_one_is_not_a_second_v2_freeze(tmp_path):
    record, rules = v2_world(tmp_path)
    doc = json.loads(record.read_text())
    doc["freezes"].insert(0, {"version": "simon.score.v1", "params_sha256": "c" * 64, "seed": 47})
    record.write_text(json.dumps(doc))
    assert script.check_seed("59", record, rules, out_root=tmp_path, git=CLEAN) == 59


def test_ra_a_seed_59_directory_that_already_exists_refuses_seed_59(tmp_path, capsys):
    record, rules = v2_world(tmp_path)
    (tmp_path / "seed-59").mkdir()
    calls = []
    code = script.main(["59"], record=record, rules=rules, out_root=tmp_path, run=v2_runner(tmp_path, calls), git=CLEAN)
    err = capsys.readouterr().err
    assert code == 2 and calls == [] and "seed 59 was already generated here" in err and "once" in err


def test_ra_another_seeds_directory_is_not_checked(tmp_path):
    record, rules = v2_world(tmp_path, freeze_hash=None)
    (tmp_path / "seed-99").mkdir()
    assert script.check_seed("99", record, rules, out_root=tmp_path, git=CLEAN) == 99


# ---------------------------------------------------------------- R-c: the line to append
def test_rc_seed_59_prints_the_exact_attempt_line_with_version_scored_at_and_holds(tmp_path, capsys):
    record, rules = v2_world(tmp_path)
    code = script.main(["59"], record=record, rules=rules, out_root=tmp_path, run=v2_runner(tmp_path, []), git=CLEAN)
    lines = capsys.readouterr().out.splitlines()
    assert code == 0
    i = next(k for k, line in enumerate(lines) if "the line to append to `attempts`" in line)
    attempt = json.loads(lines[i + 1])
    shipped = hashlib.sha256(json.dumps(json.loads(rules.read_text())["score"], sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert (attempt["seed"], attempt["version"], attempt["scored_at"], attempt["holds"]) == (59, V2, "0123456789abcdef", True)
    assert attempt["freeze_commit"] == "abc1234" and attempt["params_sha256"] == shipped
    assert attempt["labels_sha256"] == hashlib.sha256(b"{}").hexdigest() and "--json-out" in attempt["scorer"]
    assert attempt["targets"]["single_b_or_c"] == "pass" and attempt["targets"]["sweep"] == "pass" and "good/0" in attempt["slices"]


def test_rc_a_failed_seed_prints_holds_false_in_the_line(tmp_path, capsys):
    record, rules = v2_world(tmp_path)
    script.main(["59"], record=record, rules=rules, out_root=tmp_path, run=v2_runner(tmp_path, [], holds=False), git=CLEAN)
    lines = capsys.readouterr().out.splitlines()
    attempt = json.loads(lines[next(k for k, line in enumerate(lines) if "the line to append" in line) + 1])
    assert attempt["holds"] is False and attempt["targets"]["single_b_or_c"] == "fail" and attempt["version"] == V2


def test_rc_the_seed_the_script_and_the_check_name_are_the_same():
    from part5 import check
    assert script.V2_SEED == check.V2_SEED == 59
