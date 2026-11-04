"""Shared test setup: repo root on sys.path and fixture paths."""

import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

REAL_CLIP = ROOT / "fixtures" / "input" / "part2-single" / "pose3d.json"
SYNTH_DIR = ROOT / "fixtures" / "input" / "synthetic-4take"


@pytest.fixture(scope="session")
def real_doc():
    return json.loads(REAL_CLIP.read_text())
