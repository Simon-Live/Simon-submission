"""scripts/sync_contracts.py on a stale local checkout: a plain message and exit 2, never a traceback."""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "sync_contracts.py"


def run_check(part3, part4):
    env = dict(os.environ, PART3_DIR=str(part3), PART4_DIR=str(part4))
    return subprocess.run([sys.executable, str(SCRIPT), "--check"], capture_output=True, text=True,
                          env=env, cwd=ROOT)


def test_a_missing_upstream_file_exits_2_naming_it(tmp_path):
    part3, part4 = tmp_path / "part3", tmp_path / "part4"
    part3.mkdir()
    part4.mkdir()
    out = run_check(part3, part4)
    assert out.returncode == 2
    assert "Traceback" not in out.stderr
    assert "contracts/animation-part5.schema.json is missing" in out.stderr
    assert len(out.stderr.strip().splitlines()) == 1


def test_a_missing_pinned_upstream_file_exits_2(tmp_path):
    """Part 3 complete, Part 4 a stale checkout without the pinned dance clip."""
    part3 = tmp_path / "part3"
    for rel in ["contracts/animation-part5.schema.json", "contracts/skeleton.schema.json",
                "contracts/skeleton-part4.schema.json", "contracts/follower-labels.schema.json",
                "fixtures/conformance/followers/labels.json",
                "fixtures/conformance/followers/squat_front_correct/skeleton.native.json",
                "fixtures/conformance/golden/view-part4-every-10/skeleton.json"]:
        (part3 / rel).parent.mkdir(parents=True, exist_ok=True)
        (part3 / rel).write_text("{}")
    part4 = tmp_path / "part4"
    for rel in ["fixtures/output/exercise/animation.json", "contracts/animation.schema.json"]:
        (part4 / rel).parent.mkdir(parents=True, exist_ok=True)
        (part4 / rel).write_text("{}")
    out = run_check(part3, part4)
    assert out.returncode == 2
    assert "Traceback" not in out.stderr
    assert "fixtures/output/dance/animation.json is missing" in out.stderr
