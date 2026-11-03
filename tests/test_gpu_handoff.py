"""TICKET-317: a staging take's ticket stays until the admitted Part 2 child holds the flock."""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from part7 import applog, gpu_handoff, gpu_lock

CHILD = """
import fcntl, os, sys, time
time.sleep(float(sys.argv[2]))
fd = os.open(sys.argv[1], os.O_CREAT | os.O_RDWR)
while True:
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB); break
    except BlockingIOError:
        time.sleep(0.02)
open(sys.argv[3], "w").write(repr(time.time()))
time.sleep(float(sys.argv[4]))
"""


def _tickets(lock: Path) -> list[Path]:
    folder = gpu_lock.waiters_dir(lock)
    return list(folder.iterdir()) if folder.exists() else []


def _child(lock: Path, delay: float, mark: Path, hold: float = 1.0) -> subprocess.Popen[bytes]:
    return subprocess.Popen([sys.executable, "-c", CHILD, str(lock), str(delay), str(mark), str(hold)])


def _admit_high(lock: Path):
    return gpu_lock.acquire(lock_path=lock, min_free_mib=0, hold_flock=False, concurrent=True, settle_s=0.0,
                            priority=gpu_lock.HIGH, timeout_s=10.0, poll_s=0.05)


def test_low_does_not_take_the_lock_before_the_slow_child(tmp_path: Path) -> None:
    lock, mark = tmp_path / "gpu.lock", tmp_path / "child-at"
    low_at: list[float] = []

    def low() -> None:
        with gpu_lock.acquire(lock_path=lock, min_free_mib=0, priority=gpu_lock.LOW, timeout_s=15.0, poll_s=0.05):
            low_at.append(time.time())

    with _admit_high(lock):
        child = _child(lock, 2.0, mark)
        time.sleep(0.5)
        thread = threading.Thread(target=low)
        thread.start()
        deadline = time.time() + 10
        while not mark.exists() and time.time() < deadline:
            time.sleep(0.05)
    thread.join(20)
    child.wait(10)
    assert low_at and mark.exists() and low_at[0] >= float(mark.read_text())


def test_ticket_is_gone_once_the_child_holds_the_lock(tmp_path: Path) -> None:
    lock, mark = tmp_path / "gpu.lock", tmp_path / "child-at"
    with _admit_high(lock):
        child = _child(lock, 0.5, mark, hold=2.0)
        assert len(_tickets(lock)) == 1  # during the gap
        deadline = time.time() + 10
        while _tickets(lock) and time.time() < deadline:
            time.sleep(0.05)
        assert _tickets(lock) == []  # child holds, no lingering ticket
        assert gpu_lock.lock_holder_pid(lock) == child.pid
    child.wait(10)
    assert _tickets(lock) == []


def test_child_that_never_takes_the_lock_drops_the_ticket_at_the_grace(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lock = tmp_path / "gpu.lock"
    lines: list[str] = []
    monkeypatch.setattr(gpu_handoff, "HANDOFF_GRACE_S", 0.4)
    monkeypatch.setattr(applog, "log", lambda msg, *a, **k: lines.append(msg))
    with _admit_high(lock):
        assert len(_tickets(lock)) == 1
        deadline = time.time() + 5
        while _tickets(lock) and time.time() < deadline:
            time.sleep(0.05)
        assert _tickets(lock) == []  # dropped while the body still runs
    assert len([m for m in lines if "gpu handoff" in m]) == 1


def test_exception_in_the_body_removes_the_ticket(tmp_path: Path) -> None:
    lock = tmp_path / "gpu.lock"
    with pytest.raises(RuntimeError):
        with _admit_high(lock):
            assert len(_tickets(lock)) == 1
            raise RuntimeError("child launch failed")
    assert _tickets(lock) == []


def test_exit_without_a_child_removes_the_ticket_at_once(tmp_path: Path) -> None:
    lock = tmp_path / "gpu.lock"
    start = time.monotonic()
    with _admit_high(lock):
        pass
    assert _tickets(lock) == [] and time.monotonic() - start < 5


def test_hold_flock_true_drops_the_ticket_at_admission(tmp_path: Path) -> None:
    lock = tmp_path / "gpu.lock"
    with gpu_lock.acquire(lock_path=lock, min_free_mib=0, priority=gpu_lock.HIGH, timeout_s=5.0):
        assert _tickets(lock) == []
