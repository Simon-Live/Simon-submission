"""docs/ARCHITECTURE.md matches the code, and tools/arch_check.py catches drift (TICKET-277 AC-2, AC-3, AC-4).

The doc is published with the code (`.simon-publish` lists docs/ARCHITECTURE.md and tools/arch_check.py), so a
missing doc fails here; nothing in this file is skipped.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import re
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs" / "ARCHITECTURE.md"
TOOL = ROOT / "tools" / "arch_check.py"


def _load():
    spec = importlib.util.spec_from_file_location("arch_check", TOOL)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


arch = _load()


@pytest.fixture()
def tree(tmp_path: Path) -> Path:
    """A copy of what the check reads: the doc, part7/, web/api.js, the converter supervisor, .gitmodules and the
    part contracts."""
    (tmp_path / "docs").mkdir()
    shutil.copy(DOC, tmp_path / "docs" / "ARCHITECTURE.md")
    shutil.copytree(ROOT / "part7", tmp_path / "part7", ignore=shutil.ignore_patterns("__pycache__"))
    (tmp_path / "web").mkdir()
    shutil.copy(ROOT / "web" / "api.js", tmp_path / "web" / "api.js")
    shutil.copytree(ROOT / "tools" / "model-converter", tmp_path / "tools" / "model-converter")
    shutil.copy(ROOT / ".gitmodules", tmp_path / ".gitmodules")
    for schema in ROOT.glob("modules/part-*/contracts/**/*.json"):
        dest = tmp_path / schema.relative_to(ROOT)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(schema, dest)
    return tmp_path


def doc_of(tree: Path) -> Path:
    return tree / "docs" / "ARCHITECTURE.md"


def edit(tree: Path, old: str, new: str) -> None:
    doc = doc_of(tree)
    text = doc.read_text(encoding="utf-8")
    assert old in text, old
    doc.write_text(text.replace(old, new, 1), encoding="utf-8")


# ----- the real doc ----------------------------------------------------------------------------------------
def test_the_published_doc_matches_the_code() -> None:
    assert DOC.is_file(), "docs/ARCHITECTURE.md is published and must exist"
    assert arch.check(DOC, ROOT) == []


def test_the_command_line_exits_0_on_the_real_doc() -> None:
    run = subprocess.run([sys.executable, str(TOOL)], capture_output=True, text=True, check=False)
    assert run.returncode == 0, run.stderr


def test_three_mermaid_diagrams_each_under_a_heading() -> None:
    found = arch.sections(DOC.read_text(encoding="utf-8"))
    assert [h for h, _, _ in found] == ["System view", "One follow job", "Trust boundaries"]
    assert found[1][1].lstrip().startswith("sequenceDiagram")


def test_every_linked_path_exists() -> None:
    """AC-2: every relative link in the doc resolves to a file in this checkout."""
    links = re.findall(r"\]\((?!https?:)([^)#]+)(?:#L\d+)?\)", DOC.read_text(encoding="utf-8"))
    assert len(links) > 20
    for link in links:
        assert (DOC.parent / link).resolve().is_file(), link


def test_readme_links_the_doc_in_its_first_10_lines() -> None:
    head = (ROOT / "README.md").read_text(encoding="utf-8").splitlines()[:10]
    assert any("(docs/ARCHITECTURE.md)" in line for line in head)


def test_ci_runs_the_check() -> None:
    assert "python3 tools/arch_check.py" in (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")


# ----- AC-3 planted mismatches fail ------------------------------------------------------------------------
def test_the_copy_passes_before_anything_is_planted(tree: Path) -> None:
    assert arch.check(doc_of(tree), tree) == []


def test_a_missing_file_fails(tree: Path) -> None:
    (tree / "part7" / "gpu_lock.py").unlink()
    errors = arch.check(doc_of(tree), tree)
    assert any("part7/gpu_lock.py" in e and "does not exist" in e for e in errors), errors


def test_a_moved_symbol_fails_and_fix_moves_the_link(tree: Path) -> None:
    target = tree / "part7" / "runner.py"
    target.write_text("# planted\n# lines\n" + target.read_text(encoding="utf-8"), encoding="utf-8")
    errors = arch.check(doc_of(tree), tree)
    assert any("part7/runner.py" in e and "`run` is not defined there" in e for e in errors), errors
    assert arch.fix(doc_of(tree), tree) >= 1
    assert arch.check(doc_of(tree), tree) == []


def test_a_renamed_symbol_fails(tree: Path) -> None:
    target = tree / "part7" / "gpu_lock.py"
    target.write_text(target.read_text(encoding="utf-8").replace("def acquire(", "def take("), encoding="utf-8")
    errors = arch.check(doc_of(tree), tree)
    assert any("`acquire`" in e and "not found" in e for e in errors), errors


def test_a_part_the_code_does_not_have_fails(tree: Path) -> None:
    edit(tree, 'P6["Part 6: catalog and player"]', 'P6["Part 8: catalog and player"]')
    errors = arch.check(doc_of(tree), tree)
    assert any("Part 8" in e for e in errors) and any("Part 6 is missing" in e for e in errors), errors


def test_a_part_dropped_from_the_code_fails(tree: Path) -> None:
    mods = tree / "part7" / "modules.py"
    mods.write_text(mods.read_text(encoding="utf-8").replace(
        'PART_IDS = ("1", "2", "3", "4", "5", "6")', 'PART_IDS = ("1", "2", "3", "4", "5")'), encoding="utf-8")
    errors = arch.check(doc_of(tree), tree)
    assert any("names Part 6" in e for e in errors), errors


def test_a_part_missing_from_gitmodules_fails(tree: Path) -> None:
    gm = tree / ".gitmodules"
    gm.write_text(gm.read_text(encoding="utf-8").replace("path = modules/part-4", "path = modules/part-four"),
                  encoding="utf-8")
    errors = arch.check(doc_of(tree), tree)
    assert any("modules/part-4" in e for e in errors), errors


def test_an_unknown_contract_file_fails(tree: Path) -> None:
    edit(tree, '|"pose3d.json"|', '|"pose4d.json"|')
    errors = arch.check(doc_of(tree), tree)
    assert any("pose4d.json" in e for e in errors), errors


def test_an_unknown_format_string_fails(tree: Path) -> None:
    edit(tree, "simon.skeleton/1", "simon.skeleton/9")
    errors = arch.check(doc_of(tree), tree)
    assert any("simon.skeleton/9" in e for e in errors), errors


def test_a_node_without_a_row_fails(tree: Path) -> None:
    edit(tree, '  BT[("Baseten: Muse Spark Open")]\n', '  BT[("Baseten: Muse Spark Open")]\n  NEW["Unlinked"]\n')
    errors = arch.check(doc_of(tree), tree)
    assert any("node NEW has no file:line row" in e for e in errors), errors


def test_a_fourth_block_fails(tree: Path) -> None:
    doc = doc_of(tree)
    doc.write_text(doc.read_text(encoding="utf-8") + "\n## Extra\n\n```mermaid\nflowchart LR\n  A --> B\n```\n",
                   encoding="utf-8")
    errors = arch.check(doc, tree)
    assert len(errors) == 1 and "expected 3 mermaid blocks" in errors[0], errors


def test_a_missing_doc_fails_and_does_not_skip(tree: Path) -> None:
    doc_of(tree).unlink()
    assert arch.check(doc_of(tree), tree) == [f"{doc_of(tree)}: missing"]
    run = subprocess.run([sys.executable, str(TOOL), "--doc", str(doc_of(tree)), "--root", str(tree)],
                         capture_output=True, text=True, check=False)
    assert run.returncode == 1


def test_the_command_line_exits_1_on_drift(tree: Path) -> None:
    (tree / "part7" / "runner.py").unlink()
    run = subprocess.run([sys.executable, str(TOOL), "--doc", str(doc_of(tree)), "--root", str(tree)],
                         capture_output=True, text=True, check=False)
    assert run.returncode == 1 and "part7/runner.py" in run.stderr


# ----- TICKET-244: CI without the part repos ---------------------------------------------------------------
def _run(tree: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(TOOL), "--doc", str(doc_of(tree)), "--root", str(tree), *args],
                          capture_output=True, text=True, check=False)


def test_without_parts_lists_the_part_formats_as_not_checked_and_exits_0(tree: Path) -> None:
    shutil.rmtree(tree / "modules", ignore_errors=True)  # a clone without the submodules
    assert _run(tree).returncode == 1  # the plain check still fails: it never skips
    run = _run(tree, "--without-parts")
    assert run.returncode == 0, run.stderr
    assert "not checked, modules/part-* not checked out (PARTS_READ_TOKEN not set)" in run.stdout
    assert "simon.skeleton/1" in run.stdout


def test_without_parts_still_fails_on_drift_the_code_alone_shows(tree: Path) -> None:
    shutil.rmtree(tree / "modules", ignore_errors=True)
    (tree / "part7" / "runner.py").unlink()
    run = _run(tree, "--without-parts")
    assert run.returncode == 1 and "part7/runner.py" in run.stderr
