"""Tests for `part7.runner` (TICKET-009, AC-H3, AC-H4, AC-008)."""

from __future__ import annotations

import os
from pathlib import Path
import sys
import time
import pytest

from part7 import keys, runner


def test_runner_normal_execution_and_attr_access(tmp_path: Path) -> None:
    log_file = tmp_path / "steps" / "step1.log"
    step = runner.run(
        part=3,
        argv=[sys.executable, "-c", "print('hello part 3')"],
        cwd=tmp_path,
        timeout_s=10.0,
        log_path=log_file,
    )
    assert step.part == 3
    assert step["part"] == 3
    assert step.exit == 0
    assert step.timed_out is False
    assert isinstance(step.duration_s, float)
    assert log_file.is_file()
    assert "hello part 3" in log_file.read_text(encoding="utf-8")


def test_runner_timeout_kills_process_group(tmp_path: Path) -> None:
    """AC-H3: The runner kills the whole process group on timeout and records `exit: null, timed_out: true`."""
    child_pid_file = tmp_path / "child.pid"
    script = (
        "import subprocess, sys, time, pathlib\n"
        "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        f"pathlib.Path({str(child_pid_file)!r}).write_text(str(p.pid))\n"
        "time.sleep(60)\n"
    )
    log_file = tmp_path / "timeout.log"
    step = runner.run(
        part=2,
        argv=[sys.executable, "-c", script],
        cwd=tmp_path,
        timeout_s=0.5,
        log_path=log_file,
        kill_grace_s=0.3,
    )
    assert step["exit"] is None
    assert step.exit is None
    assert step["timed_out"] is True
    assert step.timed_out is True
    assert "part 2 timed out after 0.5 s" in log_file.read_text(encoding="utf-8")

    # Verify the grandchild in the process group was also killed
    if child_pid_file.is_file():
        child_pid = int(child_pid_file.read_text(encoding="utf-8").strip())
        for _ in range(20):
            try:
                os.kill(child_pid, 0)
                time.sleep(0.05)
            except ProcessLookupError:
                break
        with pytest.raises(ProcessLookupError):
            os.kill(child_pid, 0)


def test_runner_redacts_keys_from_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-H4, AC-008: A key read through `keys.py` never appears in a step log."""
    kdir = tmp_path / "keys"
    kdir.mkdir()
    monkeypatch.setenv("SIMON7_KEYS_DIR", str(kdir))
    fake_secret = "super-secret-meta-token-5544332211"
    (kdir / "MODEL_API_KEY").write_text(fake_secret, encoding="utf-8")

    assert keys.read_key("MODEL_API_KEY") == fake_secret
    log_file = tmp_path / "secret.log"
    step = runner.run(
        part=1,
        argv=[sys.executable, "-c", f"print('using token {fake_secret} now')"],
        cwd=tmp_path,
        timeout_s=10.0,
        log_path=log_file,
    )
    assert step.exit == 0
    written = log_file.read_text(encoding="utf-8")
    assert fake_secret not in written
    assert "using token <redacted> now" in written
    assert fake_secret not in step.stdout
