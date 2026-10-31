"""Run the browser quality detector's pure Node tests as part of make test."""
import shutil
import subprocess
from pathlib import Path

import pytest


def test_prerecord_quality_unit():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    script = Path(__file__).with_name("quality-check.unit.test.mjs")
    result = subprocess.run([node, "--test", str(script)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
