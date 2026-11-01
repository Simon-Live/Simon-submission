"""`make check-7` leaves the command's own exit in CHECK_RC_FILE, because make exits 2 on any failure (TICKET-188, AC-K13)."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess

import pytest

REPO = Path(__file__).resolve().parents[2]


def _make_check(tmp_path: Path, uv_exit: int) -> tuple[int, str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    uv = bin_dir / "uv"
    uv.write_text(f'#!/bin/sh\necho \'{{"part": 7, "pass": false}}\'\nexit {uv_exit}\n', encoding="utf-8")
    uv.chmod(0o755)
    rc_file = tmp_path / "rc"
    # The Makefile prepends ~/.local/bin to PATH; a command-line PATH wins over that assignment, so the fake `uv` runs.
    path = f"PATH={bin_dir}:{os.environ['PATH']}"
    done = subprocess.run(["make", "-s", "check-7", f"CHECK_RC_FILE={rc_file}", path], cwd=REPO,
                          capture_output=True, text=True, check=False, timeout=60)
    return done.returncode, rc_file.read_text(encoding="utf-8").strip() if rc_file.exists() else "", done.stdout


@pytest.mark.skipif(shutil.which("make") is None, reason="make is not installed")
@pytest.mark.parametrize("exit_code", [0, 1, 2])
def test_make_check_7_records_the_real_exit(tmp_path: Path, exit_code: int) -> None:
    make_rc, recorded, out = _make_check(tmp_path, exit_code)
    assert recorded == str(exit_code)  # a finished run with pass:false is 1; 2 stays for missing or deferred
    assert make_rc == (0 if exit_code == 0 else 2)  # make's own code is not the contract
    assert '"part": 7' in out
