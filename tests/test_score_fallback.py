"""`make score-fallback` (ADR-0018, "Reversal"; pre-freeze review R1 and R2): the recipe for "v2 failed on seed 59".

The script is tested on a small tree built here (rules, the v2 sample, the score record, the goldens' inputs left out); the
full proof, a copy of the repository with the fallback applied and `make test` green on it, is in docs/thresholds.md."""
import hashlib
import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from part5 import check, score
from part5.detect import load_rules
from shipped_score import FLOOR, IS_V2, frozen_v1, v2_block

ROOT = Path(__file__).resolve().parent.parent
V1_SHA = "e818635bb46b7062f57e335f2940edd35d01835edaaaffed9339fdbfb79eaa62"   # recorded for seeds 47 and 53


def load_script():
    spec = importlib.util.spec_from_file_location("make_score_fallback", ROOT / "scripts/make_score_fallback.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


script = load_script()


def v2_tree(tmp_path):
    """A tree that ships v2 (the rules file as `part5.calibrate` writes it, plus the v2 sample and a record)."""
    rules = load_rules()
    rules["score"] = v2_block()
    (tmp_path / "part5").mkdir()
    (tmp_path / "part5" / "rules.json").write_text(json.dumps(rules, indent=2) + "\n")
    (tmp_path / "fixtures" / "output").mkdir(parents=True)
    (tmp_path / "fixtures" / "output" / "analysis.fault-capped.example.json").write_text("{}")
    (tmp_path / "fixtures" / "score-heldout.json").write_text(json.dumps(record_after_59()))
    return tmp_path


def record_after_59(extra_attempt=True):
    """The record after the planned steps: the v1 attempts of seeds 47 and 53, the v2 freeze and a v2 attempt for seed 59."""
    v2 = score.params_sha256(v2_block())
    attempts = [{"seed": 47, "params_sha256": V1_SHA}, {"seed": 53, "params_sha256": V1_SHA}]
    if extra_attempt:
        attempts.append({"seed": 59, "version": "simon.score.v2", "params_sha256": v2})
    return {"format": "simon.part5.score-heldout.v1", "attempts": attempts,
            "freezes": [{"version": "simon.score.v2", "freeze_commit": "abc1234", "params_sha256": v2, "seed": 59}]}


class Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, command, root):
        self.calls.append((command, root))


# ---------------------------------------------------------------- the rules file
def test_the_score_section_becomes_the_frozen_v1_block_and_nothing_else_in_the_rules_file_moves(tmp_path):
    root = v2_tree(tmp_path)
    path = root / "part5" / "rules.json"
    before = path.read_text()
    lines = script.fall_back(root, regenerate=False)
    after = path.read_text()
    assert json.loads(after)["score"] == frozen_v1() and score.params_sha256(json.loads(after)["score"]) == V1_SHA
    head = '  "score": {'
    assert before[:before.index(head)] == after[:after.index(head)]      # every key before `score`, byte for byte
    assert after == json.dumps(json.loads(after), indent=2) + "\n"        # written as part5.calibrate writes it
    assert lines[0].startswith("score-fallback: part5/rules.json ships simon.score.v1")
    assert script.detection_hash(json.loads(before)) == script.detection_hash(json.loads(after))


def test_the_detection_hash_is_the_one_check_5_records(tmp_path):
    rules = load_rules()
    assert script.detection_hash(rules) == check.detection_hash() == "c92ae9a8524c559741cdaebcd14bb5305e91479d19123e15c3a5e14efb1337fb"


def test_the_v2_sample_is_removed_and_the_goldens_and_the_baseline_are_written_again(tmp_path):
    root, run = v2_tree(tmp_path), Recorder()
    lines = script.fall_back(root, regenerate=True, runner=run)
    assert not (root / "fixtures/output/analysis.fault-capped.example.json").exists()
    commands = [c[0] for c in run.calls]
    assert commands[0][1] == str(root / "scripts" / "make_output_examples.py")
    assert commands[1][1:] == ["-m", "part5.profiles_report", "--write-baseline"]
    assert all(c[1] == root for c in run.calls) and any("goldens and the fitness baseline" in x for x in lines)


def test_no_regenerate_stops_after_the_rules_and_the_sample(tmp_path):
    root, run = v2_tree(tmp_path), Recorder()
    script.fall_back(root, regenerate=False, runner=run)
    assert run.calls == [] and not (root / "fixtures/output/analysis.fault-capped.example.json").exists()


def test_the_score_record_is_not_touched(tmp_path):
    root = v2_tree(tmp_path)
    record = root / "fixtures" / "score-heldout.json"
    before = record.read_bytes()
    script.fall_back(root, regenerate=False)
    assert record.read_bytes() == before


# ---------------------------------------------------------------- refusals and --check
def test_a_tree_that_ships_v1_is_refused_with_exit_3_and_nothing_is_written(tmp_path, capsys):
    rules = load_rules()
    rules["score"] = frozen_v1()
    (tmp_path / "part5").mkdir()
    (tmp_path / "part5" / "rules.json").write_text(json.dumps(rules, indent=2) + "\n")
    before = (tmp_path / "part5" / "rules.json").read_bytes()
    assert script.main(["--root", str(tmp_path)]) == 3
    assert "already ships simon.score.v1" in capsys.readouterr().err
    assert (tmp_path / "part5" / "rules.json").read_bytes() == before


def test_a_v2_block_without_a_v1_block_is_refused_with_exit_2(tmp_path, capsys):
    rules = load_rules()
    rules["score"] = {k: v for k, v in v2_block().items() if k != "v1"}
    (tmp_path / "part5").mkdir()
    (tmp_path / "part5" / "rules.json").write_text(json.dumps(rules))
    assert script.main(["--root", str(tmp_path)]) == 2
    assert "no simon.score.v1 'v1' block to go back to" in capsys.readouterr().err


def test_check_says_whether_the_tree_can_go_back_and_changes_nothing(tmp_path, capsys):
    root = v2_tree(tmp_path)
    before = (root / "part5" / "rules.json").read_bytes()
    assert script.main(["--root", str(root), "--check"]) == 0
    assert "ships simon.score.v2 and holds the simon.score.v1 block" in capsys.readouterr().out
    assert (root / "part5" / "rules.json").read_bytes() == before and (root / "fixtures/output/analysis.fault-capped.example.json").exists()


def test_a_missing_rules_file_is_refused_not_a_traceback(tmp_path, capsys):
    assert script.main(["--root", str(tmp_path)]) == 2
    assert "cannot read" in capsys.readouterr().err


def test_a_failing_step_exits_1_naming_it(tmp_path, capsys):
    def broken(command, root):
        raise script.Refused("failed: make_output_examples.py", 1)
    assert script.main(["--root", str(v2_tree(tmp_path))], runner=broken) == 1
    assert "failed: make_output_examples.py" in capsys.readouterr().err


# ---------------------------------------------------------------- R2: the check, after the fallback, with the v2 record
def test_after_the_fallback_check_5_finds_the_v1_hash_whatever_was_appended_after(tmp_path):
    """The record holds the v2 freeze and the seed 59 attempt (version v2); the rules ship v1 again. The lookup is by the
    version the rules ship, so it finds e818635b and not the newest attempt's v2 hash (the old `attempts[-1]`)."""
    root = v2_tree(tmp_path)
    script.fall_back(root, regenerate=False)
    rules_path, record = root / "part5" / "rules.json", root / "fixtures" / "score-heldout.json"
    version = check.score_version(rules_path)
    assert version == "simon.score.v1"
    assert check.recorded_score_hash(record, version) == V1_SHA == check.score_params_hash(rules_path)
    assert json.loads(record.read_text())["attempts"][-1]["params_sha256"] != V1_SHA   # the newest attempt is v2's
    check.require_score_frozen(check.score_params_hash(rules_path), check.recorded_score_hash(record, version), version)


def test_a_v2_tree_with_the_record_after_59_finds_the_v2_freeze(tmp_path):
    root = v2_tree(tmp_path)
    rules_path, record = root / "part5" / "rules.json", root / "fixtures" / "score-heldout.json"
    assert check.recorded_score_hash(record, "simon.score.v2") == check.score_params_hash(rules_path)
    assert check.recorded_score_hash(record, "simon.score.v1") == V1_SHA


# ---------------------------------------------------------------- R1: the seed 59 record does not break the committed record's tests
def test_seed_59_once_recorded_is_retired_in_the_simulated_record(tmp_path):
    root = v2_tree(tmp_path)
    check_seed = importlib.util.spec_from_file_location("make_score_heldout", ROOT / "scripts/make_score_heldout.py")
    heldout = importlib.util.module_from_spec(check_seed)
    check_seed.loader.exec_module(heldout)
    with pytest.raises(heldout.Refused, match="seed 59 is already recorded"):
        heldout.check_seed("59", root / "fixtures" / "score-heldout.json", root / "part5" / "rules.json")
    assert heldout.recorded_seeds(root / "fixtures" / "score-heldout.json") == [47, 53, 59]


# ---------------------------------------------------------------- the make target
@pytest.mark.skipif(shutil.which("make") is None, reason="make is not installed")
def test_make_score_fallback_is_a_target_that_runs_the_script_and_only_listing_it_changes_nothing():
    """Only `-n`: a real run rewrites part5/rules.json."""
    out = subprocess.run(["make", "-n", "score-fallback"], capture_output=True, text=True, cwd=ROOT)
    assert out.returncode == 0 and "scripts/make_score_fallback.py" in out.stdout


def test_the_script_check_on_this_tree_exits_0_when_it_ships_v2_and_3_when_it_ships_v1():
    done = subprocess.run(["python3", str(ROOT / "scripts/make_score_fallback.py"), "--check"], capture_output=True, text=True)
    assert done.returncode == (0 if IS_V2 else 3), done.stderr
