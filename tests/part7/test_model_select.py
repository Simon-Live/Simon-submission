"""docs/specs/model-picker.md: the picker's node unit tests, its wiring into the three 3D views, and the copy rules."""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "web"
SKIN = WEB / "skin"
FILES = ["catalog.js", "picker.js", "import-dialog.js", "skin.css", "skin-css.js"]


def test_unit_tests_pass():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    r = subprocess.run([node, "--test", str(ROOT / "tests/part7/picker.unit.test.mjs")], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_no_dash_no_colour_literal_no_absolute_url():
    colour = re.compile(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(")
    for name in FILES:
        text = (SKIN / name).read_text(encoding="utf-8")
        assert chr(0x2014) not in text and chr(0x2013) not in text, name
        assert not colour.search(text), f"{name} holds a colour literal"
        assert not re.search(r"""["'`](https?:)?//""", text), name


def test_views_mount_the_picker_lazily():
    compare = (WEB / "compare.js").read_text(encoding="utf-8")
    assert 'import("./skin/picker.js")' in compare
    assert 'from "./skin/' not in compare, "the picker must stay a lazy import"
    assert "job = null" in compare and "gone = true" in compare
    assert 'compare.js", "multi' not in compare
    multi = (WEB / "multi-compare.js").read_text(encoding="utf-8")
    assert 'import("./skin/picker.js")' in multi and "role: u.id" in multi
    assert "job: jobId" in (WEB / "group-result.js").read_text(encoding="utf-8")
    result = (WEB / "result.js").read_text(encoding="utf-8")  # the client stage passes the job through one hook
    assert "mountCompareFor(host, m, { ...opts, job })" in result and 'mountCompare(slot, model, { testid: "compare", trainerLabel: referenceLabel(record) })' in result  # my-reference.md: the moving figure is named "Your reference" for an own-reference take


def test_draw_stats_carry_the_skin_columns():
    text = (WEB / "compare.js").read_text(encoding="utf-8")
    for attr in ("data-skin-kind", "data-skin-id", "data-skin-err"):
        assert attr in text, attr


def test_the_interface_other_lanes_code_against():
    picker = (SKIN / "picker.js").read_text(encoding="utf-8")
    assert "export async function mountModelPicker(toolsEl, stage" in picker
    assert 'KEY_PREFIX = "simon.model."' in picker
    for tid in ("model-select-", "model-attribution"):
        assert tid in picker, tid
    assert 'data-testid": "model-import-dialog"' in (SKIN / "import-dialog.js").read_text(encoding="utf-8")
    assert 'data-testid": "model-import-error"' in (SKIN / "import-dialog.js").read_text(encoding="utf-8")
    catalog = (SKIN / "catalog.js").read_text(encoding="utf-8")
    for name in ("export async function listModels", "export async function uploadModel", "export async function waitReady",
                 "export async function list("):
        assert name in catalog, name
