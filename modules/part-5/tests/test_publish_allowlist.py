"""The publish allowlist guard (docs/specs/simon-publish.md AC-P25; TICKET-054 R6).

A test helper left out of `.simon-publish` is found only when a publish candidate fails to collect: it happened twice
(`tests/retimed.py`, `tests/shipped_score.py`). These two tests find it in the workspace instead:

- every `tests/**/*.py` outside the firm test directories (`tests/publish/`, `tests/staging/`, `tests/neighbour/`,
  `tests/lib/`, which the script's denylist keeps local on purpose) matches an allowlist line;
- the tree the allowlist builds (the tracked and the not yet tracked files that match, copied to a temporary
  directory) collects: `pytest --collect-only -q` there exits 0.

`.simon-publish` is a workspace file; the published tree has none, so the whole module skips there. The globs are read
the way `scripts/simon-publish.sh` reads them: a line ends at `#`, trailing blanks go, `**` is `*`, and `*` matches a
slash as well (bash `[[ == ]]`).
"""
import fnmatch
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ALLOWLIST = ROOT / ".simon-publish"
FIRM_TEST_DIRS = ("tests/publish/", "tests/staging/", "tests/neighbour/", "tests/lib/")
COLLECT_TIMEOUT_S = 300   # collecting takes seconds; this only stops a hang

pytestmark = pytest.mark.skipif(not ALLOWLIST.is_file(), reason=".simon-publish is a workspace file: not in a published tree")


def allow_globs(text=None):
    """The allowlist lines of `.simon-publish`, as the script reads them."""
    text = ALLOWLIST.read_text() if text is None else text
    lines = (re.sub(r"#.*", "", line).rstrip() for line in text.splitlines())
    return [line for line in lines if line]


def allowed(path, globs):
    """The script's `allowed()`: `**` is `*`, and `*` crosses slashes."""
    return any(fnmatch.fnmatchcase(path, glob.replace("**", "*")) for glob in globs)


def left_out(paths, globs):
    """The test modules and helpers (`tests/**/*.py`, firm test directories excepted) that no glob matches."""
    return [p for p in paths if p.startswith("tests/") and p.endswith(".py") and not p.startswith(FIRM_TEST_DIRS)
            and not allowed(p, globs)]


def listing():
    """Tracked and not yet tracked (not ignored) paths of this checkout, or None when it is not a git checkout (an archive)."""
    done = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                          capture_output=True, check=False)
    paths = sorted(p for p in done.stdout.decode().split("\0") if p and (ROOT / p).is_file()) if done.returncode == 0 else []
    return paths or None


def test_the_globs_are_read_as_the_script_reads_them():
    text = "# a comment\nMakefile   \n\npart5/**  # trailing note\ntests/test_*.py\n  indented\n"
    assert allow_globs(text) == ["Makefile", "part5/**", "tests/test_*.py", "  indented"]
    assert allowed("part5/a/b/c.py", ["part5/**"]) and allowed("tests/test_a.py", ["tests/test_*.py"])
    assert allowed("tests/test_dir/b.py", ["tests/test_*.py"])        # `*` crosses a slash
    assert not allowed("tests/other/test_a.py", ["tests/test_*.py"])  # the prefix still has to match
    assert not allowed("tests/retimed.py", ["tests/test_*.py", "tests/conftest.py"])


def test_the_guard_names_a_helper_the_allowlist_forgot():
    globs = ["tests/test_*.py", "tests/conftest.py"]
    paths = ["tests/test_a.py", "tests/helper.py", "tests/staging/test_stack.py", "tests/lib/harness.sh",
             "tests/publish/test_x.py", "tests/neighbour/test_n.py", "tests/sub/shared.py", "part5/x.py"]
    assert left_out(paths, globs) == ["tests/helper.py", "tests/sub/shared.py"]
    assert left_out(paths, globs + ["tests/helper.py", "tests/sub/*.py"]) == []


def test_every_test_module_outside_the_firm_directories_is_allowlisted():
    paths = listing()
    if paths is None:   # an archive without .git: look at the files themselves
        paths = sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / "tests").rglob("*.py") if "__pycache__" not in p.parts)
    checked = [p for p in paths if p.startswith("tests/") and p.endswith(".py") and not p.startswith(FIRM_TEST_DIRS)]
    assert "tests/conftest.py" in checked and len(checked) > 20   # the guard looks at the suite, not at nothing
    assert left_out(paths, allow_globs()) == [], \
        "not in .simon-publish, so a published tree would not have them (add a line there, or move a firm-only file " \
        "into tests/publish/, tests/staging/, tests/neighbour/ or tests/lib/)"


def test_the_allowlisted_tree_collects(tmp_path):
    paths = listing()
    if paths is None:
        pytest.skip("not a git checkout: nothing lists the files the allowlist would publish")
    globs = allow_globs()
    tree = tmp_path / "tree"
    for path in paths:
        if allowed(path, globs):
            (tree / path).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / path, tree / path)
    assert (tree / "tests" / "conftest.py").is_file() and not (tree / ".simon-publish").exists()
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(filter(None, [str(tree), os.environ.get("PYTHONPATH")])),
           "PYTHONDONTWRITEBYTECODE": "1"}
    done = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"], cwd=tree,
                          env=env, capture_output=True, text=True, timeout=COLLECT_TIMEOUT_S, check=False)
    assert done.returncode == 0, f"the allowlisted tree does not collect (pytest exit {done.returncode}):\n" \
        f"{done.stdout[-3000:]}\n{done.stderr[-1500:]}"
    assert re.search(r"\d+ tests? collected", done.stdout), done.stdout[-500:]
