"""Static checks for the follower reference panel (recorder.md "Reference")."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "web"


def src(name: str) -> str:
    return (WEB / name).read_text(encoding="utf-8")


@pytest.mark.parametrize("tid", ["reference", "reference-video", "reference-mirror", "reference-swap", "reference-offset"])
def test_reference_testids(tid):
    assert f'"{tid}"' in src("reference.js")


def test_hooks_are_wired_for_the_follower_only():
    flow = src("take-flow.js")
    assert 'trainer || resume ? null : mountReference(entry)' in flow
    # sound is asked for on a trainer take only (not a group take, nothing transcribes it): a follower take has no audio
    assert 'mountCapture(capBox, limits, { reference, countdownDefault, audio: () => trainer && mode !== "group" })' in flow
    assert "editTake(editBox, take, info, reference)" in flow
    assert "entry: full" in src("follow.js")  # the catalog entry (with its id) is the take flow's reference
    cap = src("capture.js")
    assert "reference.startRecording()" in cap and "reference.stopRecording()" in cap and "showFirstFrame" in cap
    assert "reference.follow(" in src("trim.js") and "reference.dock(refRow" in src("trim.js")


def test_defaults_and_fallback():
    ref = src("reference.js")
    assert "mirrored = true" in ref and "loop: true" in ref and "video.muted = true" in ref
    assert "mountViewer" in ref and "entryFileUrl(entry.id, entry.video_uri)" in ref
    assert "reference.css" in ref and (WEB / "reference.css").exists()


def test_css_has_pip_and_desktop_side_by_side():
    css = src("reference.css")
    assert re.search(r"@media \(min-width: 720px\)", css) and "scaleX(-1)" in css


@pytest.mark.skipif(not shutil.which("node"), reason="node missing")
def test_reference_time_loops_with_offset():
    code = (
        "import {referenceTime as r} from '%s';"
        "const a=[r(1000,0,6),r(7000,0,6),r(500,-1000,6),r(2000,500,0)];console.log(JSON.stringify(a))"
    ) % (WEB / "reference.js").as_uri()
    # reference.js imports api.js and ui.js (no DOM at import time except ui helpers), so import is safe
    out = subprocess.run(["node", "--input-type=module", "-e", code], capture_output=True, text=True, check=True).stdout
    assert out.strip() == "[1,1,5.5,2.5]"
