"""The shipped golden outputs (docs/specs/journey-followup.md AC-C03, AC-P02, AC-NFR-J02): `make output-examples`
builds them through the path the CLI uses, score hook included, so they carry what real output carries.
AC-P02 (the goldens do not change under the live switches) is tested in tests/test_no_live_calls.py."""
import importlib.util
import json
import os
from pathlib import Path

import jsonschema
import pytest

from part5 import cli, contract
from part5.output import validate_analysis

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "fixtures/output"
GOLDENS = ["analysis.example.json", "analysis.no-faults.example.json", "replay.example.json"]


def load_script():
    spec = importlib.util.spec_from_file_location("make_output_examples", ROOT / "scripts/make_output_examples.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def rebuilt(tmp_path_factory):
    """The goldens written by the script into a temp dir (cwd the repo root, as `make` runs it)."""
    out = tmp_path_factory.mktemp("goldens")
    cwd = os.getcwd()
    os.chdir(ROOT)
    try:
        load_script().main(out)
    finally:
        os.chdir(cwd)
    return out


def test_ac_c03_the_script_writes_the_three_goldens_and_they_equal_the_committed_files(rebuilt):
    assert sorted(p.name for p in rebuilt.glob("*.json")) == sorted(GOLDENS)
    for name in GOLDENS:
        assert (rebuilt / name).read_bytes() == (OUT / name).read_bytes(), name


def test_ac_nfr_j02_a_second_run_writes_the_same_bytes(rebuilt, tmp_path):
    cwd = os.getcwd()
    os.chdir(ROOT)
    try:
        load_script().main(tmp_path)
    finally:
        os.chdir(cwd)
    for name in GOLDENS:
        assert (tmp_path / name).read_bytes() == (rebuilt / name).read_bytes(), name


@pytest.mark.parametrize("name", ["analysis.example.json", "analysis.no-faults.example.json"])
def test_r11_a_golden_analysis_carries_what_a_real_run_carries(name):
    doc = json.loads((OUT / name).read_text())
    score = doc["score"]
    assert doc["schema_version"] == "1.9.0" and doc["status"]["code"] == "ok"
    assert score["version"] == "simon.score.v1" and 0 <= score["value"] <= 100 and score["grade"] in "ABCDF"
    assert score["basis"] in ("windows", "reps") and score["timeline"] and score["tempo"] is not None
    assert all("tempo" in w for w in score["timeline"] if w["compared"])
    assert isinstance(doc["insights"], list)
    assert doc["phrasing"]["requested"] == "template" and doc["phrasing"]["selected_by"] == "default"
    assert "warnings" not in doc and "capped_by" not in score   # a clean, matching take
    validate_analysis(doc)
    assert not list(jsonschema.Draft202012Validator(contract.load_schema("analysis")).iter_errors(doc))


def test_r11_the_double_fault_golden_has_timed_faults_cues_and_insights_with_points():
    doc = json.loads((OUT / "analysis.example.json").read_text())
    assert len(doc["faults"]) == 2 and doc["score"]["value"] < 90
    for f in doc["faults"]:
        assert f["text_timed"].endswith(f" at {f['at_s']:.1f} s") and f["coaching"] == f["text_timed"]
        assert f["cue"] and f["follower_runs"] and f["follower_t_s"]
    assert doc["insights"] and all(i["points"] is not None for i in doc["insights"] if i["kind"] != "tempo")
    misses = [m for w in doc["score"]["timeline"] for m in w["misses"]]
    assert {m["measure"] for m in misses} >= {f["measure"] for f in doc["faults"]}


def test_r11_the_correct_take_golden_is_an_a_with_no_faults():
    doc = json.loads((OUT / "analysis.no-faults.example.json").read_text())
    assert doc["faults"] == [] and doc["score"]["value"] == 100 and doc["score"]["grade"] == "A"


def test_the_golden_replay_is_the_replay_of_the_double_fault_golden_take():
    replay = json.loads((OUT / "replay.example.json").read_text())
    analysis = json.loads((OUT / contract.REPLAY_SOURCE).read_text())
    assert replay["format"] == "simon.replay.v1" and replay["schema_version"] == "1.0.0"
    assert len(replay["expected"]) == len(replay["expected_t"]) == len(replay["exp_to_fol"])
    assert len(replay["follower"]) == len(replay["follower_t"])
    follower = json.loads((ROOT / analysis["follower"]["path"]).read_text())
    assert len(replay["follower"]) == len(follower["frames"])
    assert not list(jsonschema.Draft202012Validator(contract.load_schema("replay")).iter_errors(replay))
    assert contract.replay_problems(replay) == []


def test_the_golden_and_the_cli_agree_on_the_same_take(tmp_path, monkeypatch):
    """`part5 analyse` on the golden's take writes the golden's bytes (the CLI's path is the golden's path)."""
    monkeypatch.delenv("SIMON5_LIVE", raising=False)
    monkeypatch.delenv("META_LIVE", raising=False)
    monkeypatch.chdir(ROOT)
    analysis = json.loads((OUT / "analysis.example.json").read_text())
    out, replay = tmp_path / "analysis.json", tmp_path / "replay.json"
    code = cli.main(["analyse", "--expected", analysis["expected"]["path"], "--follower", analysis["follower"]["path"],
                     "--out", str(out), "--replay", str(replay)])
    assert code == 0
    written = json.loads(out.read_text())
    for key in ("expected", "follower"):   # the golden also names the set, movement and take id
        written[key] = analysis[key]
    assert written == analysis
    assert replay.read_bytes() == (OUT / "replay.example.json").read_bytes()
