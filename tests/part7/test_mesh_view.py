"""TICKET-143 (docs/specs/mesh-view.md): web/mesh-view.js unit tests through node, the C6 contract text, the demo
page's wiring and the committed real Part 2 output it shows."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "web"
DEMO = WEB / "mesh-demo"


def test_unit_tests_pass():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    r = subprocess.run([node, "--test", str(ROOT / "tests/part7/mesh.unit.test.mjs")], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_contract_c6_is_documented_at_the_top_and_exported():
    text = (WEB / "mesh-view.js").read_text()
    head = text[:3000]
    for word in ("Contract C6", "mountMeshView(container", "trainerMeshUrl", "followerMeshUrl", "faults", "fps",
                 "setTime(t)", "destroy()", "null"):
        assert word in head, word
    assert "export async function mountMeshView(container, ctx" in text


def test_no_part2_import_no_absolute_urls_no_dashes():
    for name in ("mesh-view.js", "mesh-demo.html"):
        text = (WEB / name).read_text()
        assert "\u2014" not in text and "\u2013" not in text, name
        assert not re.search(r"""["'`](https?:)?//""", text), name
        assert "part2" not in re.sub(r"part2\.mesh3d|Part 2|part2 run", "", text), name


def test_the_demo_page_says_when_its_data_is_not_in_the_repo():
    page = (WEB / "mesh-demo.html").read_text()
    assert "Demo data not included in this repo." in page and "faultRes.ok" in page


@pytest.mark.skipif(not (DEMO / "faults.json").is_file(), reason="mesh demo data is not published (R13)")
def test_the_demo_shows_real_part2_output_for_both_people():
    page = (WEB / "mesh-demo.html").read_text()
    assert 'from "./mesh-view.js"' in page and "mountMeshView(" in page
    for role in ("trainer", "follower"):
        header = json.loads((DEMO / role / "mesh3d.json").read_text())
        assert header["format"].startswith("part2.mesh3d/")
        assert (DEMO / role / header["bin"]).stat().st_size == header["bin_bytes"]
        assert f"mesh-demo/{role}/mesh3d.json" in page
    faults = json.loads((DEMO / "faults.json").read_text())
    assert faults["source"] and all({"at_s", "joints"} <= set(f) for f in faults["faults"])


def test_mesh_view_takes_every_colour_from_css_custom_properties():
    text = (WEB / "mesh-view.js").read_text()
    assert not re.search(r"0x[0-9a-fA-F]{3,8}|#[0-9a-fA-F]{3,8}\b", text)  # no literal hex colour
    for name in ("--mesh-trainer", "--mesh-you", "--mesh-fault", "--mesh-bg", "--mesh-light", "--mesh-ground"):
        assert name in text, name
    assert "getComputedStyle" in text


def test_the_demo_page_without_its_data_shows_the_fallback_and_no_console_error():
    """TICKET-109: a browser loads mesh-demo.html with the data request answered 404 (the published repo)."""
    node, slot = shutil.which("node"), Path.home() / "claude-template/scripts/with-browser-slot.sh"
    if not node or not slot.is_file() or not (ROOT / "node_modules/playwright").is_dir():
        pytest.skip("node, the browser slot script or playwright is not available")
    r = subprocess.run(["bash", str(slot), node, str(ROOT / "tests/part7/mesh-fallback.browser.mjs")],
                       capture_output=True, text=True, cwd=ROOT, timeout=180)
    assert r.returncode == 0, r.stdout + r.stderr
