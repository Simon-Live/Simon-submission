"""Black-box isolation tests (AC-007, AC-H9, AC-H11)."""

from __future__ import annotations

import ast
from pathlib import Path
import re

import pytest

from part7 import config

FORBIDDEN_IMPORT_RE = re.compile(
    r"^\s*(?:import|from)\s+(?:part[1-6]|keyframe_finder|simon_anim)\b",
    re.MULTILINE,
)
FORBIDDEN_MODULES = {
    "part1",
    "part2",
    "part3",
    "part4",
    "part5",
    "part6",
    "keyframe_finder",
    "simon_anim",
}
# Dynamic imports of a part by name: importlib.import_module("part2.x"), __import__("part2"), import_module('part3').
DYNAMIC_IMPORT_RE = re.compile(
    r"""(?:import_module|__import__)\s*\(\s*[rbuf]*["'](?:part[1-6]|keyframe_finder|simon_anim)\b"""
)
# ADR-0002 "Amendment: the warm tracker bridge" is closed (TICKET-128): no file may reach a part by name.
DYNAMIC_IMPORT_ALLOWLIST: set[str] = set()
FORBIDDEN_ENV_VARS =("SAM3D_REPO", "SAM3D_CKPT")


def _iter_part7_py_files() -> list[Path]:
    part7_dir = config.REPO_ROOT / "part7"
    if not part7_dir.exists():
        return []
    return sorted(p for p in part7_dir.rglob("*.py"))


def test_no_other_part_imported_in_part7() -> None:
    py_files = _iter_part7_py_files()
    assert py_files, "part7/ must contain Python modules"
    hits: list[str] = []
    for path in py_files:
        text = path.read_text(encoding="utf-8")
        for m in FORBIDDEN_IMPORT_RE.finditer(text):
            hits.append(f"{path.relative_to(config.REPO_ROOT)}: {m.group(0).strip()}")
        tree = ast.parse(text, filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    if top in FORBIDDEN_MODULES:
                        hits.append(f"{path.relative_to(config.REPO_ROOT)}:{node.lineno} import {alias.name}")
            elif isinstance(node, ast.ImportFrom) and node.module:
                top = node.module.split(".")[0]
                if top in FORBIDDEN_MODULES:
                    hits.append(f"{path.relative_to(config.REPO_ROOT)}:{node.lineno} from {node.module}")
    assert not hits, f"Forbidden cross-part imports found: {hits}"


def test_no_dynamic_part_imports_in_part7() -> None:
    hits: list[str] = []
    for path in _iter_part7_py_files():
        rel = str(path.relative_to(config.REPO_ROOT))
        if rel in DYNAMIC_IMPORT_ALLOWLIST:
            continue
        for m in DYNAMIC_IMPORT_RE.finditer(path.read_text(encoding="utf-8")):
            hits.append(f"{rel}: {m.group(0)}")
    assert not hits, f"Dynamic cross-part imports found: {hits}"


def test_dynamic_import_pattern_catches_strings() -> None:
    for text in ('importlib.import_module("part2.trackers")', "__import__('part3')", "import_module('keyframe_finder.x')"):
        assert DYNAMIC_IMPORT_RE.search(text), text
    assert not DYNAMIC_IMPORT_RE.search('importlib.import_module("part7.config")')


def test_no_file_in_part7_imports_a_part_dynamically() -> None:
    users = [p for p in _iter_part7_py_files()
             if DYNAMIC_IMPORT_RE.search(p.read_text(encoding="utf-8"))]
    assert DYNAMIC_IMPORT_ALLOWLIST == set()
    assert not users, f"dynamic part imports: {[str(p) for p in users]}"
    assert not (config.REPO_ROOT / "part7" / "trackwarm").exists()


def test_the_bridge_is_recorded_as_closed_in_adr_0002() -> None:
    adr_path = config.REPO_ROOT / "docs/adr/ADR-0002-black-box-by-process-and-pins.md"
    if not adr_path.is_file():
        pytest.skip("the published tree carries no firm ADRs (docs/adr is not published); checked in the workspace")
    adr = adr_path.read_text(encoding="utf-8")
    assert "warm tracker bridge" in adr and "Exit condition" in adr and "Closed 2026-11-01" in adr


def test_no_sam3d_env_vars_set_in_part7() -> None:
    py_files = _iter_part7_py_files()
    hits: list[str] = []
    for path in py_files:
        text = path.read_text(encoding="utf-8")
        for var in FORBIDDEN_ENV_VARS:
            if var in text:
                hits.append(f"{path.relative_to(config.REPO_ROOT)} mentions {var}")
    assert not hits, f"Forbidden SAM3D environment variables referenced in part7/: {hits}"
