"""`make score-fallback` (ADR-0018 and ADR-0019, "Reversal"; pre-freeze review R1 and R2): the recipe for "v2 failed on seed 59" and
for "v3 failed on seed 61".

The script is tested on a small tree built here (rules, the samples, the score record, the goldens' inputs left out); the
full proof, a copy of the repository with the fallback applied and `make test` green on it, is in docs/thresholds.md."""
import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from part5 import check, score
from part5.detect import load_rules
from shipped_score import DETECTION_SHA, IS_CAPPED, V1_SHA, V2, V2_SHA, V3, frozen_v1, v2_block, v3_block

ROOT = Path(__file__).resolve().parent.parent
BLOCKS = {V2: v2_block, V3: v3_block}
SAMPLES = {V2: ("analysis.fault-capped.example.json",), V3: ("analysis.fault-capped.example.json", "analysis.double-capped.example.json")}
VERSIONS = pytest.mark.parametrize("version", [V2, V3])   # a tree that ships v2 (before 59 was scored) or v3 (before 61 is)


def load_script():
    spec = importlib.util.spec_from_file_location("make_score_fallback", ROOT / "scripts/make_score_fallback.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


script = load_script()


def tree(tmp_path, version):
    """A tree that ships `version` (the rules file as `part5.calibrate` writes it, plus its samples and a record)."""
    rules = load_rules()
    rules["score"] = BLOCKS[version]()
    (tmp_path / "part5").mkdir()
    (tmp_path / "part5" / "rules.json").write_text(json.dumps(rules, indent=2) + "\n")
    (tmp_path / "fixtures" / "output").mkdir(parents=True)
    for name in SAMPLES[version]:
        (tmp_path / "fixtures" / "output" / name).write_text("{}")
    (tmp_path / "fixtures" / "score-heldout.json").write_text(json.dumps(record_after(version)))
    return tmp_path


def record_after(version, holds=False, scored=True):
    """The record after the planned steps: the v1 attempts of seeds 47 and 53, the v2 freeze and its failed attempt for seed 59
    and, for a v3 tree, the v3 freeze and (with `scored`) a v3 attempt for seed 61 that holds or not."""
    v2 = score.params_sha256(v2_block())
    attempts = [{"seed": 47, "params_sha256": V1_SHA}, {"seed": 53, "params_sha256": V1_SHA}]
    freezes = [{"version": V2, "freeze_commit": "abc1234", "params_sha256": v2, "seed": 59}]
    if version == V2:
        return {"format": "simon.part5.score-heldout.v1", "attempts": [*attempts, {"seed": 59, "version": V2, "params_sha256": v2}],
                "freezes": freezes}
    v3 = score.params_sha256(v3_block())
    attempts.append({"seed": 59, "version": V2, "params_sha256": v2, "holds": False})
    if scored:
        attempts.append({"seed": 61, "version": V3, "params_sha256": v3, "holds": holds})
    return {"format": "simon.part5.score-heldout.v1", "attempts": attempts,
            "freezes": [*freezes, {"version": V3, "freeze_commit": "def5678", "params_sha256": v3, "seed": 61}]}


class Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, command, root):
        self.calls.append((command, root))


# ---------------------------------------------------------------- the rules file
@VERSIONS
def test_the_score_section_becomes_the_frozen_v1_block_and_nothing_else_in_the_rules_file_moves(tmp_path, version):
    root = tree(tmp_path, version)
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
    assert script.detection_hash(rules) == check.detection_hash() == DETECTION_SHA


@VERSIONS
def test_the_samples_are_removed_and_the_goldens_and_the_baseline_are_written_again(tmp_path, version):
    root, run = tree(tmp_path, version), Recorder()
    lines = script.fall_back(root, regenerate=True, runner=run)
    assert not [n for n in SAMPLES[V3] if (root / "fixtures/output" / n).exists()]
    assert sum(f"removed fixtures/output/{n} (a {version} sample)" in "\n".join(lines) for n in SAMPLES[version]) == len(SAMPLES[version])
    commands = [c[0] for c in run.calls]
    assert commands[0][1] == str(root / "scripts" / "make_output_examples.py")
    assert commands[1][1:] == ["-m", "part5.profiles_report", "--write-baseline"]
    assert all(c[1] == root for c in run.calls) and any("goldens and the fitness baseline" in x for x in lines)


@VERSIONS
def test_no_regenerate_stops_after_the_rules_and_the_samples(tmp_path, version):
    root, run = tree(tmp_path, version), Recorder()
    script.fall_back(root, regenerate=False, runner=run)
    assert run.calls == [] and not [n for n in SAMPLES[V3] if (root / "fixtures/output" / n).exists()]


@VERSIONS
def test_the_score_record_is_not_touched(tmp_path, version):
    root = tree(tmp_path, version)
    record = root / "fixtures" / "score-heldout.json"
    before = record.read_bytes()
    script.fall_back(root, regenerate=False)
    assert record.read_bytes() == before


def test_a_v3_tree_loses_its_kept_v2_block_with_the_rest_of_the_section_and_the_record_still_has_its_hash(tmp_path):
    root = tree(tmp_path, V3)
    kept = json.loads((root / "part5" / "rules.json").read_text())["score"]["v2"]
    assert score.params_sha256(kept) == V2_SHA
    script.fall_back(root, regenerate=False)
    assert "v2" not in json.loads((root / "part5" / "rules.json").read_text())["score"]
    assert json.loads((root / "fixtures" / "score-heldout.json").read_text())["freezes"][0]["params_sha256"] == V2_SHA


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


@VERSIONS
def test_a_block_without_a_v1_block_is_refused_with_exit_2(tmp_path, capsys, version):
    rules = load_rules()
    rules["score"] = {k: v for k, v in BLOCKS[version]().items() if k != "v1"}
    (tmp_path / "part5").mkdir()
    (tmp_path / "part5" / "rules.json").write_text(json.dumps(rules))
    assert script.main(["--root", str(tmp_path)]) == 2
    assert "no simon.score.v1 'v1' block to go back to" in capsys.readouterr().err


@VERSIONS
def test_check_says_whether_the_tree_can_go_back_and_changes_nothing(tmp_path, capsys, version):
    root = tree(tmp_path, version)
    before = (root / "part5" / "rules.json").read_bytes()
    assert script.main(["--root", str(root), "--check"]) == 0
    assert f"ships {version} and holds the simon.score.v1 block" in capsys.readouterr().out
    assert (root / "part5" / "rules.json").read_bytes() == before and (root / "fixtures/output/analysis.fault-capped.example.json").exists()


def test_a_missing_rules_file_is_refused_not_a_traceback(tmp_path, capsys):
    assert script.main(["--root", str(tmp_path)]) == 2
    assert "cannot read" in capsys.readouterr().err


@VERSIONS
def test_a_failing_step_exits_1_naming_it(tmp_path, capsys, version):
    def broken(command, root):
        raise script.Refused("failed: make_output_examples.py", 1)
    assert script.main(["--root", str(tree(tmp_path, version))], runner=broken) == 1
    assert "failed: make_output_examples.py" in capsys.readouterr().err


# ---------------------------------------------------------------- R2: the check, after the fallback, with the later versions' record
@VERSIONS
def test_after_the_fallback_check_5_finds_the_v1_hash_whatever_was_appended_after(tmp_path, version):
    """The record holds the freezes and the failed attempts (versions v2 and v3); the rules ship v1 again. The lookup is by the
    version the rules ship, so it finds e818635b and not the newest attempt's hash (the old `attempts[-1]`)."""
    root = tree(tmp_path, version)
    script.fall_back(root, regenerate=False)
    rules_path, record = root / "part5" / "rules.json", root / "fixtures" / "score-heldout.json"
    shipped = check.score_version(rules_path)
    assert shipped == "simon.score.v1"
    assert check.recorded_score_hash(record, shipped) == V1_SHA == check.score_params_hash(rules_path)
    assert json.loads(record.read_text())["attempts"][-1]["params_sha256"] != V1_SHA   # the newest attempt is a later version's
    check.require_score_frozen(check.score_params_hash(rules_path), check.recorded_score_hash(record, shipped), shipped)
    check.require_held(record, shipped)   # and a v1 block is never judged by the failed attempts


@VERSIONS
def test_a_tree_with_the_record_after_the_seed_finds_its_versions_freeze(tmp_path, version):
    root = tree(tmp_path, version)
    rules_path, record = root / "part5" / "rules.json", root / "fixtures" / "score-heldout.json"
    assert check.recorded_score_hash(record, version) == check.score_params_hash(rules_path)
    assert check.recorded_score_hash(record, "simon.score.v1") == V1_SHA


# ---------------------------------------------------------------- R1: a recorded seed does not break the committed record's tests
@pytest.mark.parametrize("version, seed", [(V2, 59), (V3, 61)])
def test_a_score_seed_once_recorded_is_retired_in_the_simulated_record(tmp_path, version, seed):
    root = tree(tmp_path, version)
    check_seed = importlib.util.spec_from_file_location("make_score_heldout", ROOT / "scripts/make_score_heldout.py")
    heldout = importlib.util.module_from_spec(check_seed)
    check_seed.loader.exec_module(heldout)
    with pytest.raises(heldout.Refused, match=f"seed {seed} is already recorded"):
        heldout.check_seed(str(seed), root / "fixtures" / "score-heldout.json", root / "part5" / "rules.json")
    assert heldout.recorded_seeds(root / "fixtures" / "score-heldout.json")[-1] == seed


@pytest.mark.parametrize("holds", [True, False])
def test_the_committed_trees_tests_survive_a_recorded_seed_61_attempt_either_way(tmp_path, holds):
    """AC-V3-12: with the v3 freeze and a seed 61 attempt in the record, whether v3 held or not, the lookups the suite and
    `make check-5` use still answer: the v3 hash by the freeze, v1's by the 47 and 53 attempts, and a v3 block is refused
    exactly when the attempt says it did not hold."""
    root = tree(tmp_path, V3)
    record = root / "fixtures" / "score-heldout.json"
    record.write_text(json.dumps(record_after(V3, holds=holds)))
    assert check.recorded_score_hash(record, V3) == score.params_sha256(v3_block()) and check.recorded_score_hash(record, "simon.score.v1") == V1_SHA
    if holds:
        check.require_held(record, V3)
    else:
        with pytest.raises(check.CheckError, match="did not hold"):
            check.require_held(record, V3)
    with pytest.raises(check.CheckError, match="seed 59 \\(holds false\\)"):   # v2's failed attempt still refuses a v2 block
        check.require_held(record, V2)


# ---------------------------------------------------------------- the make target
@pytest.mark.skipif(shutil.which("make") is None, reason="make is not installed")
def test_make_score_fallback_is_a_target_that_runs_the_script_and_only_listing_it_changes_nothing():
    """Only `-n`: a real run rewrites part5/rules.json."""
    out = subprocess.run(["make", "-n", "score-fallback"], capture_output=True, text=True, cwd=ROOT)
    assert out.returncode == 0 and "scripts/make_score_fallback.py" in out.stdout


def test_the_script_check_on_this_tree_exits_0_when_it_ships_v2_or_v3_and_3_when_it_ships_v1():
    done = subprocess.run(["python3", str(ROOT / "scripts/make_score_fallback.py"), "--check"], capture_output=True, text=True)
    assert done.returncode == (0 if IS_CAPPED else 3), done.stderr
