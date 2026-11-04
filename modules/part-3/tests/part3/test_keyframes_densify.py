"""`--keyframes-densify every:<n>` (docs/specs/journey-followup.md, TICKET-036): AC-D01 to AC-D08, AC-NFR-D01."""

import json
import os
import subprocess
import sys
import time

import pytest

from clipkit import real_skeleton
from conftest import REAL_CLIP, ROOT
from part3 import config as config_file
from part3 import keyframes as kf
from part3 import views
from part3.schema import ContractError

COUNT = 213
T_LAST = (COUNT - 1) * 1000 / 30
PART1 = ROOT / "fixtures" / "conformance" / "inputs" / "keyframes.part1.json"


def part4_doc(names):
    """A Part 4 keyframes file with {index: name}."""
    return {"format": "simon.keyframes.v1", "fps": 30, "duration_s": 7.066667, "frame_count": COUNT,
            "keyframes": [{"index": i, "t": round(i / 30, 6), "name": n} for i, n in sorted(names.items())]}


def timeline(names):
    return kf.load(part4_doc(names), 0.0, T_LAST)


def run(*args, env=None):
    """`part3 run` with every PART3_ variable stripped, then `env` set."""
    clean = {k: v for k, v in os.environ.items() if not k.startswith("PART3_")}
    return subprocess.run([sys.executable, "-m", "part3", "run", *map(str, args)], cwd=ROOT, capture_output=True,
                          text=True, env={**clean, **(env or {})})


def out_doc(tmp_path, *args, env=None):
    out = tmp_path / "skeleton.json"
    result = run("--in", REAL_CLIP, "--out", out, "--view", "part4", "--keyframes", PART1, *args, env=env)
    return result, (json.loads(out.read_text()) if result.returncode == 0 else None)


def test_d01_named_keys_kept_and_fillers_restart_at_each_anchor():
    dense = kf.densify(timeline({60: "a", 75: "b", 90: "c"}), 10, "flag")
    ticks = [i for i, _ in dense.keys]
    assert ticks == [0, 10, 20, 30, 40, 50, 60, 70, 75, 85, 90, *range(100, 211, 10), 212]
    names = dict(dense.keys)
    assert (names[60], names[75], names[90]) == ("a", "b", "c") and names[85] == "key_85" and names[0] == "key_0"
    assert dense.densify == {"every": 10, "selected_by": "flag", "added": len(ticks) - 3}


def test_d02_no_tick_twice_and_the_named_key_wins():
    dense = kf.densify(timeline({0: "start", 30: "mid", 60: "two", 212: "end"}), 10, "env")
    ticks = [i for i, _ in dense.keys]
    assert ticks == sorted(set(ticks)) and dict(dense.keys)[0] == "start" and dict(dense.keys)[212] == "end"
    assert dense.densify["added"] == len(ticks) - 4


def test_d03_dropped_keys_stay_dropped_and_are_not_anchors():
    doc = {"video": "v.mp4", "fps": 60.0, "people": [{"id": 0, "repetitions": [{"rep": 1, "keyframes": [
        {"name": "a", "t_ms": 1000.0}, {"name": "dup", "t_ms": 1000.0}, {"name": "late", "t_ms": 99000.0}]}]}]}
    sparse = kf.load(doc, 0.0, T_LAST)
    dense = kf.densify(sparse, 10, "flag")
    assert dense.dropped == sparse.dropped and len(dense.dropped) == 2
    assert dict(dense.keys)[30] == "a" and max(i for i, _ in dense.keys) == COUNT - 1


def test_edge_cases_one_named_key_n_1_n_beyond_every_gap_and_a_one_tick_clip():
    assert [i for i, _ in kf.densify(timeline({100: "x"}), 100, "api").keys] == [0, 100, 200, 212]
    assert len(kf.densify(timeline({100: "x"}), 1, "api").keys) == COUNT
    assert [i for i, _ in kf.densify(timeline({100: "x"}), 300, "api").keys] == [0, 100, 212]
    one = kf.load(part4_doc({0: "only"}), 0.0, 0.0)
    assert kf.densify(one, 5, "api").densify["added"] == 0


@pytest.mark.parametrize("value", ["every:0", "every:301", "every:x"])
def test_d04_bad_n_on_the_flag_exits_2(tmp_path, value):
    result, _ = out_doc(tmp_path, "--keyframes-densify", value)
    assert result.returncode == 2
    assert result.stderr.strip() == f"--keyframes-densify {value}: n must be a whole number from 1 to 300"


def test_d04_off_equals_no_option(tmp_path):
    _, plain = out_doc(tmp_path)
    _, off = out_doc(tmp_path, "--keyframes-densify", "off", env={"PART3_KEYFRAMES_DENSIFY": "every:10"})
    assert off == plain and "densify" not in plain["timeline"]


def test_d05_misuse_is_refused_on_the_flag_only(tmp_path):
    out = tmp_path / "s.json"
    other = run("--in", REAL_CLIP, "--out", out, "--view", "part5", "--keyframes-densify", "every:10")
    every = run("--in", REAL_CLIP, "--out", out, "--view", "part4", "--keyframes", "every:5",
                "--keyframes-densify", "every:10")
    assert (other.returncode, other.stderr.strip()) == (2, "--keyframes-densify only applies to --view part4")
    assert every.returncode == 2 and every.stderr.strip() == (
        "--keyframes-densify only applies to a keyframes file (every:<n> already keys every n ticks)")
    plain = run("--in", REAL_CLIP, "--out", tmp_path / "a.json", "--view", "part5")
    with_env = run("--in", REAL_CLIP, "--out", tmp_path / "b.json", "--view", "part5",
                   env={"PART3_KEYFRAMES_DENSIFY": "every:x"})
    assert plain.returncode == with_env.returncode == 0
    assert (tmp_path / "a.json").read_bytes() == (tmp_path / "b.json").read_bytes()


def test_d05_the_api_ignores_the_keyword_for_other_views_and_every():
    skeleton = real_skeleton()
    assert views.render(skeleton, "native", keyframes_densify="every:10", env={}) is skeleton
    dense = views.render(skeleton, "part4", keyframes="every:10", keyframes_densify="every:3", env={})
    assert "densify" not in dense["timeline"]


def test_d06_precedence_and_selected_by(tmp_path):
    toml = tmp_path / "part3.toml"
    toml.write_text('[keyframes]\ndensify = "every:30"\n')
    cfg = config_file.load(str(toml), {})
    env = {"PART3_KEYFRAMES_DENSIFY": "every:20"}
    assert kf.resolve_densify("every:10", "every:40", env, cfg) == (10, "flag")
    assert kf.resolve_densify(None, "every:40", env, cfg) == (20, "env")
    assert kf.resolve_densify(None, "every:40", {}, cfg) == (30, "config")
    assert kf.resolve_densify(None, "every:40", {}, None) == (40, "api")
    assert kf.resolve_densify(None, None, {}, None) == (None, None)
    assert kf.resolve_densify("off", "every:40", env, cfg) == (None, None)


def test_d06_a_bad_value_names_its_channel(tmp_path):
    toml = tmp_path / "part3.toml"
    toml.write_text('[keyframes]\ndensify = "every:0"\n')
    cfg = config_file.load(str(toml), {})
    with pytest.raises(ContractError, match=r"^PART3_KEYFRAMES_DENSIFY: n must be a whole number from 1 to 300"):
        kf.resolve_densify(env={"PART3_KEYFRAMES_DENSIFY": "every:301"})
    with pytest.raises(ContractError, match=rf"^{toml}: keyframes.densify: n must be a whole number"):
        kf.resolve_densify(env={}, config=cfg)
    odd = config_file.Config(toml, str(toml), tmp_path, densify="ten")
    with pytest.raises(ContractError, match=rf"^{toml}: keyframes.densify: expected every:<n> or off"):
        kf.resolve_densify(env={}, config=odd)
    result, _ = out_doc(tmp_path, env={"PART3_KEYFRAMES_DENSIFY": "every:x"})
    assert result.returncode == 2 and result.stderr.startswith("PART3_KEYFRAMES_DENSIFY: ")


def test_d06_environment_and_config_reach_a_cli_run(tmp_path):
    toml = tmp_path / "part3.toml"
    toml.write_text('[keyframes]\ndensify = "every:30"\n')
    _, by_config = out_doc(tmp_path, "--config", toml)
    _, by_env = out_doc(tmp_path, "--config", toml, env={"PART3_KEYFRAMES_DENSIFY": "every:20"})
    assert by_config["timeline"]["densify"]["selected_by"] == "config"
    assert by_config["timeline"]["densify"]["every"] == 30
    assert by_env["timeline"]["densify"]["selected_by"] == "env"


def test_d07_default_output_has_no_densify_block(tmp_path):
    _, plain = out_doc(tmp_path)
    assert "densify" not in plain["timeline"]


def test_d08_the_densified_file_passes_part4_rules(tmp_path):
    out, side = tmp_path / "skeleton.json", tmp_path / "keyframes.json"
    result = run("--in", REAL_CLIP, "--out", out, "--view", "part4", "--keyframes", PART1,
                 "--keyframes-densify", "every:10", "--keyframes-out", side)
    assert result.returncode == 0, result.stderr
    doc = json.loads(out.read_text())
    ticks = [k["index"] for k in doc["keyframes"]]
    assert ticks == sorted(set(ticks)) and all(abs(k["t"] - k["index"] / 30) < 1e-6 for k in doc["keyframes"])
    assert [k["index"] for k in json.loads(side.read_text())["keyframes"]] == ticks
    assert doc["timeline"]["densify"]["added"] == sum(k["name"] == f"key_{k['index']}" for k in doc["keyframes"])
    check = subprocess.run([sys.executable, "-m", "part3", "doctor", out, "--for", "part4"], cwd=ROOT,
                           capture_output=True, text=True)
    assert check.returncode == 0, check.stdout


def test_nfr_d01_densify_is_fast_on_the_squat():
    base = timeline({60: "a", 75: "b", 90: "c"})
    start = time.perf_counter()
    kf.densify(base, 1, "flag")
    assert time.perf_counter() - start < 0.5
