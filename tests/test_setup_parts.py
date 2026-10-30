"""Tests for `part7.setup_parts` (TICKET-011, AC-H7)."""

from __future__ import annotations

from pathlib import Path
import sys

from part7 import pins, setup_parts


def _make_stub_lock(state: Path) -> pins.Lock:
    raw = {
        "schema": "part7.parts-lock/1",
        "pinned_at": "2026-10-29T14:52:00Z",
        "parts": {
            str(n): {
                "repo": f"https://example.com/part-{n}.git",
                "sha": f"{n}" * 40,
                "pinned_at": "2026-10-29T14:52:00Z",
                "status": "STATUS: DONE",
                "repin_due": False,
            }
            for n in range(1, 7)
        },
    }
    lk = pins.Lock(raw)
    for n in range(1, 7):
        lk.path(n, state=state).mkdir(parents=True, exist_ok=True)
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
