"""TICKET-349 guard: a test that launches the real Part 2 carries the `gpu_host` marker.

A source scan, not a run. Real Part 2 is reached through the real checkout (`modules.load()`, which resolves
modules/part-N and the host's venvs) and a Part 2 adapter call (`p2_pose.doctor`, `.run`, `.track`, `.frame_times`,
`p2_worker`, avatar or image3d). A test, or a helper in its file that it calls, doing both must be marked, so it skips
unless SIMON7_TEST_GPU=1 and never takes the host's shared lock from live staging takes.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import ci_skips

TESTS = Path(__file__).resolve().parent
ADAPTERS = {"p2_pose", "p2_worker", "p2_avatar", "p2_image3d", "p2_autorig"}


def _is_real_checkout(node: ast.AST) -> bool:
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "load"
            and isinstance(node.func.value, ast.Name) and node.func.value.id == "modules")


def _is_adapter_call(node: ast.AST) -> bool:
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name) and node.func.value.id in ADAPTERS)


def _calls(fn: ast.AST) -> set[str]:
    return {n.func.id for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}


def _launches(fn: ast.AST, helpers: dict[str, ast.AST], seen: frozenset[str] = frozenset()) -> bool:
    nodes = list(ast.walk(fn))
    if any(_is_real_checkout(n) for n in nodes) and any(_is_adapter_call(n) for n in nodes):
        return True
    return any(_launches(helpers[c], helpers, seen | {c}) for c in _calls(fn) if c in helpers and c not in seen)


def _marked(node: ast.AST) -> bool:
    """True for exactly `pytest.mark.gpu_host` (or a call or list holding it), never a substring of other text."""
    return any(ast.unparse(n) == "pytest.mark.gpu_host" for n in ast.walk(node))


def unmarked_launchers(source: str) -> list[str]:
    """Names of the test functions in `source` that launch the real Part 2 without the gpu_host marker."""
    tree = ast.parse(source)
    if any(isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "pytestmark" for t in n.targets) and _marked(n)
           for n in tree.body):
        return []
    fns = [n for n in tree.body if isinstance(n, ast.FunctionDef)]
    helpers = {f.name: f for f in fns}
    return [f.name for f in fns if f.name.startswith("test_") and _launches(f, helpers)
            and not any(_marked(d) for d in f.decorator_list)]


def test_every_test_that_launches_real_part_2_carries_the_marker() -> None:
    bad = {}
    for path in sorted(TESTS.rglob("test_*.py")):
        names = unmarked_launchers(path.read_text(encoding="utf-8"))
        if names:
            bad[str(path.relative_to(TESTS.parent))] = names
    assert not bad, f"mark these @pytest.mark.gpu_host (TICKET-349, docs/specs/gpu-host-tests.md): {bad}"


def test_the_scan_flags_an_unmarked_launcher_and_passes_a_marked_one() -> None:
    body = "def test_x():\n    lk = modules.load()\n    p2_pose.run(v, w, lock=lk)\n"
    assert unmarked_launchers(body) == ["test_x"]
    assert unmarked_launchers("import pytest\n@pytest.mark.gpu_host\n" + body) == []
    assert unmarked_launchers("import pytest\npytestmark = pytest.mark.gpu_host\n" + body) == []
    helper = "def _h():\n    p2_pose.frame_times(c, w, 10, modules.load())\ndef test_y():\n    _h()\n"
    assert unmarked_launchers(helper) == ["test_y"]
    assert unmarked_launchers("def test_z():\n    p2_pose.run(v, w, lock=make_lock())\n") == []  # a fake lock: no real Part 2


def test_the_marker_is_matched_exactly() -> None:
    body = "def test_x():\n    lk = modules.load()\n    p2_pose.run(v, w, lock=lk)\n"
    assert unmarked_launchers("import pytest\n@pytest.mark.skipif(True, reason='not gpu_host')\n" + body) == ["test_x"]


def test_the_opt_in_skip_follows_the_environment() -> None:
    assert ci_skips.gpu_opt_in_skip(True, {}) == ci_skips.GPU_OPT_IN_REASON
    assert ci_skips.gpu_opt_in_skip(True, {"SIMON7_TEST_GPU": "0"}) == ci_skips.GPU_OPT_IN_REASON
    assert ci_skips.gpu_opt_in_skip(True, {"SIMON7_TEST_GPU": "1"}) is None
    assert ci_skips.gpu_opt_in_skip(False, {}) is None
    assert "SIMON7_TEST_GPU=1" in ci_skips.GPU_OPT_IN_REASON and "staging is idle" in ci_skips.GPU_OPT_IN_REASON


def test_the_lock_env_stays_private_after_a_bare_monkeypatch_undo(monkeypatch: pytest.MonkeyPatch) -> None:
    import os

    host = str(Path.home() / ".local/state/simon-part-2/gpu.lock")
    monkeypatch.setenv("PART2_GPU_LOCK", "/somewhere/else")
    monkeypatch.undo()  # undoes the autouse setenv too
    for name in ("PART2_GPU_LOCK", "SIMON7_GPU_LOCK_PATH"):
        value = os.environ.get(name)
        assert value and value != host and "simon-part-2" not in Path(value).parts


def test_every_test_runs_with_a_private_part_2_lock(request: pytest.FixtureRequest) -> None:
    import os

    lock = Path(os.environ["PART2_GPU_LOCK"])
    assert "simon-part-2" not in lock.parts and lock != Path.home() / ".local/state/simon-part-2/gpu.lock"
    assert lock.parent.is_dir()
