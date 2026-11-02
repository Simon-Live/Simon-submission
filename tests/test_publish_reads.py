"""No published test reads or loads a file the publish keeps local (docs/specs/simon-publish.md AC-P25 (c); review B1 and
B2 of 1.13.0, TICKET-078).

`tests/test_publish_allowlist.py` collects the allowlisted tree, which finds a missing module but not a missing file a test
reads at run time: `tests/test_score_credit_history.py` read `docs/adr/ADR-0020-...md` (B1) and `tests/test_retimed.py`
loaded `scripts/score_credit_retime_noise.py` (B2), and both failed only in the published tree, where the publish refuses a
red suite. This scan reads every published test file (the workspace's tracked and not ignored `tests/**/*.py` that the
allowlist publishes and the denylist lets through) with `ast` and names each path literal the test builds from the
repository root that the published tree would not have:

- a path under the script's denylist (`DENY_PREFIXES`, `DENY_FILES`, `DENY_GLOBS`, with `DENY_EXCEPT` read as the script
  reads it), read from `scripts/simon-publish.sh` itself so the two cannot drift;
- a directory no published file lives in (`ROOT / "docs/specs"`), or a workspace file the allowlist leaves out;
- a module imported after `sys.path` gets a repository directory (`ROOT / "scripts"`), when that directory's file of the
  module's name is not published.

A path literal is `ROOT / "a/b"`, `ROOT / "a" / "b"`, `<x>.ROOT / ...`, `ROOT.joinpath("a", "b")`, `Path("a/b")`,
`open("a/b")` or an item of a `subprocess` argument list, where `ROOT` is any name bound to `Path(__file__)...parent.parent`
(or `parents[1]`), or any attribute named `ROOT`. A literal is allowed when the same file checks it before use: an
`.is_file()`, `.exists()` or `.is_dir()` (or `os.path.exists`, `isfile`, `isdir`) on the same literal, or on a name bound to
it (an assignment, or a `for` over a tuple of literals). The guard is looked for in the whole file, not per test: a weaker
rule than a run of the published tree, which is why the publish still runs the tests (`SIMON_PUBLISH_TEST_CMD`).

Workspace only, like `tests/test_publish_allowlist.py`: the published tree has neither `.simon-publish` nor the script.
"""
import ast
import fnmatch
import re
import shlex
from pathlib import Path

import pytest

from test_publish_allowlist import ALLOWLIST, ROOT, allow_globs, allowed, listing

PUBLISH_SCRIPT = ROOT / "scripts" / "simon-publish.sh"
DENY_ARRAYS = ("DENY_PREFIXES", "DENY_FILES", "DENY_GLOBS", "DENY_EXCEPT")
GUARDS = {"is_file", "exists", "is_dir"}
OS_GUARDS = {"exists", "isfile", "isdir"}
SUBPROCESS = {"run", "check_output", "check_call", "call", "Popen"}

pytestmark = pytest.mark.skipif(not (ALLOWLIST.is_file() and PUBLISH_SCRIPT.is_file()),
                                reason=".simon-publish and scripts/simon-publish.sh are workspace files: not in a published tree")


# ---------------------------------------------------------------------------------------------- the publish rules
def deny_lists(text=None):
    """The script's deny arrays, `{name: [item]}`, as bash reads them (an array may span lines; quotes are shell quotes)."""
    text = PUBLISH_SCRIPT.read_text() if text is None else text
    out = {}
    for name in DENY_ARRAYS:
        m = re.search(rf"^{name}=\((.*?)\)", text, re.M | re.S)
        assert m, f"scripts/simon-publish.sh has no {name}=(...) array"
        out[name] = shlex.split(m.group(1))
    return out


def denied(path, lists):
    """The script's `denied()` for the path rules: a file directly under `scripts/` matching `DENY_EXCEPT` passes the
    `scripts/` prefix only; `DENY_GLOBS` (`*` crosses slashes), `DENY_PREFIXES` and `DENY_FILES` refuse. The secret-name
    rules are not path rules and are left to the script."""
    excepted = path.rpartition("/")[0] == "scripts" and any(fnmatch.fnmatchcase(path, g) for g in lists["DENY_EXCEPT"])
    if any(fnmatch.fnmatchcase(path, g) for g in lists["DENY_GLOBS"]):
        return True
    if any(path.startswith(d) for d in lists["DENY_PREFIXES"] if not (excepted and d == "scripts/")):
        return True
    return path in lists["DENY_FILES"]


class Published:
    """What the published tree holds, from the workspace listing, the allowlist and the denylist."""

    def __init__(self, paths, globs, lists):
        self.lists = lists
        self.workspace = set(paths)
        self.files = {p for p in paths if allowed(p, globs) and not denied(p, lists)}

    def lacks(self, path):
        """True when the published tree would not have `path` (a file or a directory, repository-relative)."""
        path = path.strip("/")
        if denied(path, self.lists):
            return True
        if path in self.workspace:
            return path not in self.files
        under = path + "/"
        if any(p.startswith(under) for p in self.workspace):
            return not any(p.startswith(under) for p in self.files)
        return any(d.rstrip("/") == path for d in self.lists["DENY_PREFIXES"]) and not any(
            g.startswith(under) for g in self.lists["DENY_EXCEPT"])


# ---------------------------------------------------------------------------------------------- the scan
def _is_root_expr(node):
    text = ast.unparse(node)
    return "__file__" in text and re.search(r"(\.parent\.parent|\.parents\[1\])$", text) is not None


class Scan(ast.NodeVisitor):
    """The path literals of one module, the names bound to them and the guards on them."""

    def __init__(self, tree):
        self.roots = {"ROOT"} | {t.id for n in ast.walk(tree) if isinstance(n, ast.Assign) and _is_root_expr(n.value)
                                 for t in n.targets if isinstance(t, ast.Name)}
        self.inner = {id(n.left) for n in ast.walk(tree) if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Div)}
        self.literals, self.bound, self.guarded_paths, self.guarded_names = [], {}, set(), set()
        self.path_dirs, self.imports = set(), []
        self.visit(tree)

    def _root(self, node):
        return ((isinstance(node, ast.Name) and node.id in self.roots) or (isinstance(node, ast.Attribute) and node.attr == "ROOT")
                or _is_root_expr(node))

    def path_of(self, node):
        """The repository-relative text of a path literal, or None."""
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            parts = []
            while isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div) and isinstance(node.right, ast.Constant) \
                    and isinstance(node.right.value, str):
                parts.insert(0, node.right.value)
                node = node.left
            return "/".join(parts) if parts and self._root(node) else None
        if isinstance(node, ast.Call):
            f, args = node.func, node.args
            strings = [a.value for a in args if isinstance(a, ast.Constant) and isinstance(a.value, str)]
            if isinstance(f, ast.Attribute) and f.attr == "joinpath" and self._root(f.value) and strings and len(strings) == len(args):
                return "/".join(strings)
            name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None
            if name in ("Path", "open") and args and isinstance(args[0], ast.Constant) and isinstance(args[0].value, str):
                return args[0].value if not args[0].value.startswith(("/", "~")) else None
        return None

    def generic_visit(self, node):
        if id(node) not in self.inner:
            path = self.path_of(node)
            if path:
                self.literals.append((node.lineno, path.removeprefix("./")))
        super().generic_visit(node)

    def visit_Assign(self, node):
        path = self.path_of(node.value)
        for t in node.targets:
            if isinstance(t, ast.Name) and path:
                self.bound.setdefault(t.id, set()).add(path)
        self.generic_visit(node)

    def visit_For(self, node):
        if isinstance(node.target, ast.Name) and isinstance(node.iter, (ast.Tuple, ast.List)):
            for item in node.iter.elts:
                if self.path_of(item):
                    self.bound.setdefault(node.target.id, set()).add(self.path_of(item))
        self.generic_visit(node)

    def _guard(self, node):
        """A check on a literal guards it; a check on a name, or on a file under it (`(SALUTE / "a.json").exists()`),
        guards the paths bound to that name."""
        path = self.path_of(node)
        if path:
            self.guarded_paths.add(path)
            return
        while isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            node = node.left
        if isinstance(node, ast.Name):
            self.guarded_names.add(node.id)

    def visit_Call(self, node):
        f = node.func
        if isinstance(f, ast.Attribute) and f.attr in GUARDS and not node.args:
            self._guard(f.value)
        if isinstance(f, ast.Attribute) and f.attr in OS_GUARDS and ast.unparse(f.value) == "os.path" and node.args:
            self._guard(node.args[0])
        if isinstance(f, ast.Attribute) and f.attr in ("insert", "append") and ast.unparse(f.value) == "sys.path" and node.args:
            for arg in ast.walk(node.args[-1]):
                if self.path_of(arg):
                    self.path_dirs.add(self.path_of(arg))
        if isinstance(f, ast.Attribute) and f.attr in SUBPROCESS and node.args and isinstance(node.args[0], (ast.List, ast.Tuple)):
            for item in node.args[0].elts:
                if isinstance(item, ast.Constant) and isinstance(item.value, str) and "/" in item.value:
                    self.literals.append((node.lineno, item.value.removeprefix("./")))
        self.generic_visit(node)

    def visit_Import(self, node):
        self.imports += [(node.lineno, a.name.split(".")[0]) for a in node.names]

    def visit_ImportFrom(self, node):
        if node.module and not node.level:
            self.imports.append((node.lineno, node.module.split(".")[0]))

    def guarded(self, path):
        return path in self.guarded_paths or any(path in self.bound.get(n, ()) for n in self.guarded_names)


def unpublished_reads(source, published, workspace_root=ROOT):
    """`[(line, path)]`: the path literals of `source` the published tree lacks and the module does not check first, and
    the modules it imports from a `sys.path` directory whose file of that name is not published."""
    scan = Scan(ast.parse(source))
    found = [(line, path) for line, path in scan.literals if published.lacks(path) and not scan.guarded(path)]
    for line, module in scan.imports:
        for directory in sorted(scan.path_dirs):
            path = f"{directory}/{module}.py"
            if (workspace_root / path).is_file() and published.lacks(path) and not scan.guarded(path):
                found.append((line, path))
    return sorted(set(found))


# ---------------------------------------------------------------------------------------------- the tests
@pytest.fixture(scope="module")
def published():
    paths = listing()
    if paths is None:
        pytest.skip("not a git checkout: nothing lists the files the allowlist would publish")
    return Published(paths, allow_globs(), deny_lists())


def test_the_deny_arrays_are_read_from_the_script_as_bash_reads_them():
    text = "X=1\nDENY_PREFIXES=(.claude/ tasks/\n  docs/adr/ scripts/)\nDENY_FILES=(STATUS.md)\nDENY_GLOBS=('tests/test-*.sh')\n" \
           "DENY_EXCEPT=('scripts/make_*.py' 'scripts/sync_contracts.py')\n"
    lists = deny_lists(text)
    assert lists == {"DENY_PREFIXES": [".claude/", "tasks/", "docs/adr/", "scripts/"], "DENY_FILES": ["STATUS.md"],
                     "DENY_GLOBS": ["tests/test-*.sh"], "DENY_EXCEPT": ["scripts/make_*.py", "scripts/sync_contracts.py"]}
    real = deny_lists()
    assert {"docs/adr/", "docs/specs/", "scripts/", "progress/"} <= set(real["DENY_PREFIXES"]) and "scripts/make_*.py" in real["DENY_EXCEPT"]
    assert denied("scripts/score_credit_retime_noise.py", real) and not denied("scripts/make_score_credit_retime_noise.py", real)
    assert denied("scripts/sub/make_x.py", real)            # the exception is for a file directly under scripts/
    assert denied("docs/adr/ADR-0020-score-credit-ddr-display.md", real) and denied("tests/test-oneshot-watch.sh", real)
    assert not denied("docs/design/adr/ADR-0020-score-credit-ddr-display.md", real) and denied(".simon-publish", real)


B1_AS_IT_WAS = '''
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent


def test_the_credit_grade_is_called_informational_wherever_it_is_described():
    adr = (ROOT / "docs/adr/ADR-0020-score-credit-ddr-display.md").read_text(encoding="utf-8")
'''

B2_AS_IT_WAS = '''
import importlib.util
import retimed

NOISE_SCRIPT = retimed.ROOT / "scripts" / "score_credit_retime_noise.py"     # the script that retimes the takes to measure credit


def _load_noise_script():
    spec = importlib.util.spec_from_file_location("score_credit_retime_noise", NOISE_SCRIPT)
'''


def test_the_scan_names_b1_and_b2_as_they_were(published):
    """The old lines of review B1 and B2 of 1.13.0, copied: each is named with its line and path."""
    assert unpublished_reads(B1_AS_IT_WAS, published) == [(7, "docs/adr/ADR-0020-score-credit-ddr-display.md")]
    assert unpublished_reads(B2_AS_IT_WAS, published) == [(5, "scripts/score_credit_retime_noise.py")]
    fixed = B1_AS_IT_WAS.replace("docs/adr/", "docs/design/adr/") + B2_AS_IT_WAS.replace('"score_credit', '"make_score_credit')
    assert unpublished_reads(fixed, published) == []


def test_the_scan_reads_every_spelling_of_a_path_and_every_guard(published):
    names = '''
import os, subprocess, sys
from pathlib import Path
root = Path(__file__).resolve().parents[1]
A = root.joinpath("docs", "specs", "x.md")
B = Path("progress/log.md")
C = open("STATUS.md")
subprocess.run(["bash", "scripts/dev.sh"])
D = root / "docs/specs"
'''
    assert [p for _, p in unpublished_reads(names, published)] == ["docs/specs/x.md", "progress/log.md", "STATUS.md",
                                                                   "scripts/dev.sh", "docs/specs"]
    guarded = '''
import os, pytest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts/import-stock-takes.sh"
skip = pytest.mark.skipif(not (ROOT / "docs/specs/x.md").is_file(), reason="workspace")
source = ROOT / "docs/specs/y.md"
text = (source if source.is_file() else ROOT / "docs/design/specs/y.md").read_text()
for path in (ROOT / "part5/real.py", ROOT / "progress/z.md"):
    if path.exists():
        path.read_text()
if os.path.exists(ROOT / "goals/brief.md") and SCRIPT.exists():
    (ROOT / "goals/brief.md").read_text()
SALUTE = ROOT / "tests/local/selfie-salute"
needs_salute = pytest.mark.skipif(not (SALUTE / "follower.json").exists(), reason="local only")
'''
    assert unpublished_reads(guarded, published) == []
    assert unpublished_reads(guarded.replace("(SALUTE / ", "(ROOT / "), published) == [(14, "tests/local/selfie-salute")]


def test_the_scan_names_a_module_imported_from_a_directory_put_on_sys_path(published):
    source = '''
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import make_score_validity
from make_bench_score import main
import qa_recipe_lint_shim
'''
    published_script = "scripts/make_score_validity.py"
    assert (ROOT / published_script).is_file() and not published.lacks(published_script)
    local = sorted(p for p in published.workspace if p.startswith("scripts/") and p.endswith(".py") and published.lacks(p)
                   and "/" not in p.removeprefix("scripts/") and Path(p).stem.isidentifier())
    assert local, "the workspace has a scripts/*.py the publish keeps local"
    module = Path(local[0]).stem
    found = unpublished_reads(source.replace("qa_recipe_lint_shim", module), published)
    assert found == [(8, local[0])]


def test_no_published_test_reads_or_loads_a_file_the_published_tree_lacks(published):
    globs, lists = allow_globs(), published.lists
    tests = sorted(p for p in published.workspace if p.startswith("tests/") and p.endswith(".py")
                   and allowed(p, globs) and not denied(p, lists))
    assert "tests/test_retimed.py" in tests and len(tests) > 20   # the scan reads the suite, not nothing
    found = [f"{p}:{line}: {path}" for p in tests for line, path in unpublished_reads((ROOT / p).read_text(), published)]
    assert found == [], "a published test reads or loads a path the publish keeps local (read the published copy, " \
        "rename a script make_*, or skip when the file is absent):\n" + "\n".join(found)
