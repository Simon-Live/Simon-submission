"""`run --out` creates its parent folder; the README follower example (TICKET-037, AC-O01, AC-O02)."""

import json
import subprocess
import sys

from conftest import REAL_CLIP, ROOT
from part3 import jsonschema_lite

PART1 = ROOT / "fixtures" / "conformance" / "inputs" / "keyframes.part1.json"


def run(*args):
    return subprocess.run([sys.executable, "-m", "part3", "run", *map(str, args)], cwd=ROOT,
                          capture_output=True, text=True)


def test_o01_out_and_keyframes_out_folders_are_created(tmp_path):
    out, side = tmp_path / "a" / "b" / "skeleton.json", tmp_path / "k" / "keyframes.json"
    result = run("--in", REAL_CLIP, "--out", out, "--view", "part4", "--keyframes", PART1, "--keyframes-out", side)
    assert result.returncode == 0, result.stderr
    assert out.is_file() and side.is_file()


def test_o01_a_parent_that_is_a_file_exits_1_and_writes_nothing(tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("x")
    result = run("--in", REAL_CLIP, "--out", blocker / "skeleton.json")
    assert result.returncode == 1
    assert result.stderr.startswith(f"{blocker / 'skeleton.json'}: cannot write (")
    assert blocker.read_text() == "x" and not list(tmp_path.glob("**/skeleton.json"))


def test_o02_the_readme_follower_line_carries_fps_30_and_runs(tmp_path):
    readme = (ROOT / "README.md").read_text()
    assert "--out follower/skeleton.json --view part5 --fps 30" in readme
    out = tmp_path / "follower" / "skeleton.json"
    result = run("--in", REAL_CLIP, "--out", out, "--view", "part5", "--fps", "30")
    assert result.returncode == 0, result.stderr
    doc = json.loads(out.read_text())
    schema = json.loads((ROOT / "contracts" / "animation-part5.schema.json").read_text())
    assert jsonschema_lite.validate(doc, schema) == []
    assert doc["fps"] == 30 and all(abs(f["t"] - f["index"] / 30) < 1e-5 for f in doc["frames"])
