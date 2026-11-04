"""Runs the model skin tests (docs/specs/model-skin.md): the node unit file always, the browser file when its inputs exist."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
NODE = shutil.which("node")
SLOT = Path.home() / "claude-template/scripts/with-browser-slot.sh"


@pytest.mark.skipif(NODE is None, reason="node is not available")
def test_skin_unit_tests_pass():
    r = subprocess.run([NODE, "--test", str(ROOT / "tests/part7/skin.unit.test.mjs")], capture_output=True, text=True, cwd=ROOT, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr


def test_skin_browser_checks_pass_on_real_models():
    """Real models and a real take stay on the machine; without them the browser file prints SKIP and exits 0."""
    if not NODE or not SLOT.is_file() or not (ROOT / "node_modules/playwright").is_dir():
        pytest.skip("node, the browser slot script or playwright is not available")
    r = subprocess.run(["bash", str(SLOT), NODE, str(ROOT / "tests/part7/skin.browser.mjs")], capture_output=True, text=True, cwd=ROOT, timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "FAIL" not in r.stdout


def test_stage_framing_keeps_every_skin_in_shot():
    """docs/specs/model-skin.md AC16: every built-in model and the Person, three viewports, three views, framing on and off."""
    if not NODE or not SLOT.is_file() or not (ROOT / "node_modules/playwright").is_dir():
        pytest.skip("node, the browser slot script or playwright is not available")
    r = subprocess.run(["bash", str(SLOT), NODE, str(ROOT / "tests/part7/framing.browser.mjs")], capture_output=True, text=True, cwd=ROOT, timeout=900)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "FAIL" not in r.stdout


@pytest.mark.skipif(NODE is None, reason="node is not available")
def test_take_extent_unit_tests_pass():
    """docs/specs/model-skin.md AC16c: the frames the stage scans and the projected box of a take."""
    r = subprocess.run([NODE, "--test", str(ROOT / "tests/part7/stage-extent.unit.test.mjs")], capture_output=True, text=True, cwd=ROOT, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr


def test_take_framing_holds_the_first_play():
    """docs/specs/model-skin.md AC16c: with the take given, every frame of the first play in shot and the camera still."""
    if not NODE or not SLOT.is_file() or not (ROOT / "node_modules/playwright").is_dir():
        pytest.skip("node, the browser slot script or playwright is not available")
    r = subprocess.run(["bash", str(SLOT), NODE, str(ROOT / "tests/part7/take-framing.browser.mjs")], capture_output=True, text=True, cwd=ROOT, timeout=900)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "FAIL" not in r.stdout


def test_skin_files_follow_the_repo_rules():
    text = (ROOT / "web/skin/character.js").read_text()
    assert "—" not in text and "–" not in text
    assert not re.search(r"0x[0-9a-fA-F]{3,8}|#[0-9a-fA-F]{3,8}\b", text)  # no literal colour: colours live in tokens
    assert "from \"../vendor/three/three.module.min.js\"" in text
