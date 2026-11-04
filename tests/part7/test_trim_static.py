"""Static checks for the trim editor and labels (recorder.md TICKET-053, TICKET-054)."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "web"
TRIM_IDS = ["trim", "trim-start", "trim-end", "trim-play", "trim-set-start", "trim-set-end",
            "trim-length", "trim-error", "trim-continue"]


def src(name: str) -> str:
    return (WEB / name).read_text(encoding="utf-8")


@pytest.mark.parametrize("tid", TRIM_IDS)
def test_trim_testids(tid):
    assert f'"{tid}"' in src("trim.js")


def test_labels_testids_and_limits():
    t = src("labels.js")
    for tid in ["tags", "tag-input", "notes"]:
        assert f'"{tid}"' in t
    assert "MAX_TAGS = 8" in t and "MAX_TAG_LEN = 24" in t and "MAX_NOTES = 280" in t
    assert "export function mountLabels" in t


def test_watch_and_catalog_use_labels():
    assert "entry-tags" in src("watch.js") and "entry-notes" in src("watch.js")
    assert "getEntryLabels" in src("watch.js")
    assert "api/labels" in src("labels.js") and "getLabels" in src("catalog.js")
    assert "tags" in src("catalog.js")


def test_trim_follows_spec():
    t = src("trim.js")
    assert "export function openTrimEditor" in t
    for frag in ["createObjectURL", "releaseSharedMediaUrl([video, probe], url)", "85000000", "STEP_MS = 100", "MIN_MS = 1000", "MAX_MS = 60000",
                 "clamp(Math.round(durationMs / 3000), 8, 12)", "1e101", "pointerdown", "setPointerCapture",
                 "ArrowLeft", "ArrowRight", "aria-label"]:
        assert frag in t, frag
    assert "fetch(" not in t, "nothing is uploaded from the editor"
    assert "URL.revokeObjectURL" in src("media-url.js"), "the shared release revokes the clip URL (recorder.md Object URL lifetime)"


def test_handles_are_sliders_with_a_touch_target():
    """a11y-copy R3: each handle is a focusable slider (role, value range); the 44 px target stays."""
    css, js = src("styles.css"), src("trim.js")
    assert 'role: "slider", tabindex: "0"' in js and '"aria-valuenow"' in js and '"aria-valuetext"' in js
    assert "touch-action: none" in css and "inset: 0 -10px" in css


def test_urls_relative_and_no_dashes():
    for n in ["trim.js", "labels.js", "catalog.js", "watch.js", "styles.css"]:
        text = src(n)
        assert "—" not in text and "–" not in text, n
        assert not re.search(r"""["'`](https?:)?//""", text), n


def test_unit_tests_pass():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    r = subprocess.run([node, "--test", str(ROOT / "tests/part7/trim.unit.test.mjs")], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
