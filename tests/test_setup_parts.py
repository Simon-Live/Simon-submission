"""Tests for `part7.setup_parts` (TICKET-011, AC-H7)."""

from __future__ import annotations

from pathlib import Path
import sys

from part7 import modules, setup_parts
from support import stub_modules


def _make_stub_lock(state: Path) -> modules.Modules:
    lk = stub_modules(state / "modules")
    for n in range(1, 7):
        lk.path(n).mkdir(parents=True, exist_ok=True)
    return lk


def test_setup_all_and_doctor_parts_success(state_dir: Path) -> None:
    lk = _make_stub_lock(state_dir)
    setup_cmds = {
        str(n): [[sys.executable, "-c", f"print('setup {n} ok')"]]
        for n in range(1, 7)
    }
    res_setup = setup_parts.setup_all(lock=lk, state=state_dir, commands=setup_cmds)
    assert res_setup["ok"] is True
    for n in ("1", "2", "3", "4", "5", "6"):
        assert res_setup["parts"][n]["ok"] is True

    doc_cmds = {
        str(n): [sys.executable, "-c", f"print('doctor {n} ok')"]
        for n in range(1, 7)
    }
    res_doc = setup_parts.doctor_parts(lock=lk, state=state_dir, commands=doc_cmds)
    assert res_doc["ok"] is True
    for n in ("1", "2", "3", "4", "5", "6"):
        assert res_doc["parts"][n]["ok"] is True


def test_doctor_parts_reports_missing_command_with_part_and_sha12(state_dir: Path) -> None:
    """AC-H7 Error Case: Command missing at the pin -> `part <n>: <command> not found at <sha12>`."""
    lk = _make_stub_lock(state_dir)
    doc_cmds = {
        str(n): [sys.executable, "-c", "import sys; sys.exit(0)"]
        for n in range(1, 7)
    }
    doc_cmds["5"] = [sys.executable, "-c", "import sys; sys.exit(1)"]

    res_doc = setup_parts.doctor_parts(lock=lk, state=state_dir, commands=doc_cmds)
    assert res_doc["ok"] is False
    assert res_doc["parts"]["5"]["ok"] is False
    err = res_doc["parts"]["5"]["error"]
    assert err is not None
    assert err.startswith("part 5:")
    assert f"not found at {lk.sha12('5')}" in err


def test_setup_runs_once_per_sha_and_again_for_a_new_sha(state_dir: Path) -> None:
    lk = _make_stub_lock(state_dir)
    marker = state_dir / "ran.txt"
    cmds = {
        n: [[sys.executable, "-c", f"open({str(marker)!r}, 'a').write('{n}')"]] for n in ("1", "2", "3", "4", "5", "6")
    }
    first = setup_parts.setup_all(lock=lk, state=state_dir, commands=cmds)
    assert first["ok"] and marker.read_text() == "123456"
    again = setup_parts.setup_all(lock=lk, state=state_dir, commands=cmds)
    assert again["ok"] and marker.read_text() == "123456"
    assert all(p["skipped"] for p in again["parts"].values())

    moved = modules.Modules(root=lk.root, shas={**{str(n): str(n) * 40 for n in range(1, 7)}, "3": "f" * 40})
    third = setup_parts.setup_all(lock=moved, state=state_dir, commands=cmds)
    assert third["ok"] and marker.read_text() == "1234563"
    assert third["parts"]["3"]["commit"] == "f" * 12 and "skipped" not in third["parts"]["3"]


def test_failed_setup_names_the_part_and_leaves_no_stamp(state_dir: Path) -> None:
    lk = _make_stub_lock(state_dir)
    cmds = {"2": [[sys.executable, "-c", "raise SystemExit(5)"]]}
    res = setup_parts.setup_all(lock=lk, state=state_dir, commands=cmds)
    assert res["ok"] is False and "part 2: setup command" in res["parts"]["2"]["error"]
    assert not setup_parts._stamp("2", lk.sha12("2"), state_dir, lk.path("2")).exists()


def test_missing_module_is_named(state_dir: Path) -> None:
    lk = modules.Modules(root=state_dir / "nowhere", shas={"1": "1" * 40})
    res = setup_parts.setup_all(lock=lk, state=state_dir, commands={})
    assert "part 1: module missing" in res["parts"]["1"]["error"]
    assert "part 6: module missing" in res["parts"]["6"]["error"]


def test_stamp_is_per_checkout(tmp_path: Path) -> None:
    """A second checkout at the same sha gets its own marker, so its venv is set up too."""
    a = setup_parts._stamp("3", "abc123def456", tmp_path, tmp_path / "one" / "part-3")
    b = setup_parts._stamp("3", "abc123def456", tmp_path, tmp_path / "two" / "part-3")
    assert a != b and a.parent == b.parent
    assert a == setup_parts._stamp("3", "abc123def456", tmp_path, tmp_path / "one" / "part-3")


def test_setup_all_only_runs_the_named_parts(state_dir: Path) -> None:
    lk = _make_stub_lock(state_dir)
    cmds = {str(n): [[sys.executable, "-c", "pass"]] for n in range(1, 7)}
    res = setup_parts.setup_all(lock=lk, state=state_dir, commands=cmds, only=("3", "5"))
    assert res["ok"] is True
    assert sorted(res["parts"]) == ["3", "5"]


def test_doctor_parts_names_a_missing_venv_not_a_missing_test(state_dir: Path) -> None:
    """A checkout where setup never ran has no `.venv`: the error says so instead of blaming `schema_test`."""
    lk = _make_stub_lock(state_dir)
    doc_cmds = {str(n): [sys.executable, "-c", "pass"] for n in range(2, 7)}
    res_doc = setup_parts.doctor_parts(lock=lk, state=state_dir, commands=doc_cmds)
    err = res_doc["parts"]["1"]["error"]
    assert res_doc["parts"]["1"]["ok"] is False
    assert err == (f"part 1: {lk.path('1') / '.venv' / 'bin' / 'python'} not found at {lk.sha12('1')}"
                   " (setup has not run in this checkout: part7 setup-parts)")
    assert "schema_test not found" not in err
