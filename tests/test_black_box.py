"""Black-box isolation tests (AC-007, AC-H9, AC-H11)."""

from __future__ import annotations

import ast
from pathlib import Path
import re

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
# ADR-0008 (superseded in practice at Part 5 d655d50): the one file that runs inside Part 5's own interpreter and
# imports Part 5 internals; kept only as the fallback for a pin without `analyse --profile`.
BRIDGE_FILES = {"p5_mode_runner.py"}
FORBIDDEN_ENV_VARS =("SAM3D_REPO", "SAM3D_CKPT")


def _iter_part7_py_files() -> list[Path]:
    part7_dir = config.REPO_ROOT / "part7"
    if not part7_dir.exists():
        return []
    return sorted(p for p in part7_dir.rglob("*.py") if p.name not in BRIDGE_FILES)


def test_the_bridge_is_never_imported_by_part7() -> None:
    """Part 7's own process must not import the file that imports Part 5 internals; it only runs it as a script."""
    pattern = re.compile(r"(?:import|from)\s+(?:part7\.|part7\s+import\s+|\.)?[\w, ]*p5_mode_runner")
    for path in _iter_part7_py_files():
        assert not pattern.search(path.read_text(encoding="utf-8")), path


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


def test_no_sam3d_env_vars_set_in_part7() -> None:
    py_files = _iter_part7_py_files()
    hits: list[str] = []
    for path in py_files:
        text = path.read_text(encoding="utf-8")
        for var in FORBIDDEN_ENV_VARS:
            if var in text:
                hits.append(f"{path.relative_to(config.REPO_ROOT)} mentions {var}")
    assert not hits, f"Forbidden SAM3D environment variables referenced in part7/: {hits}"
