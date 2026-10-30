"""Tests for `part7.gpu_lock` (TICKET-009, AC-H6)."""

from __future__ import annotations

import fcntl
import os
from pathlib import Path
import threading
import time
import pytest

from part7 import gpu_lock


def test_two_gpu_lock_calls_never_overlap(tmp_path: Path) -> None:
    """AC-H6: Two Part 2 calls never overlap (test with two threads recording intervals)."""
    lpath = tmp_path / "gpu.lock"
    intervals: list[tuple[int, float, float]] = []
    rec_lock = threading.Lock()

    def worker(idx: int) -> None:
        with gpu_lock.acquire(
            lock_path=lpath,
            min_free_mib=12288,
            poll_s=0.01,
            timeout_s=5.0,
            memory_fn=lambda: 16384,
        ):
            t0 = time.monotonic()
            time.sleep(0.08)
            t1 = time.monotonic()
            with rec_lock:
                intervals.append((idx, t0, t1))

    t_a = threading.Thread(target=worker, args=(1,))
    t_b = threading.Thread(target=worker, args=(2,))
    t_a.start()
    t_b.start()
    t_a.join(timeout=5.0)
    t_b.join(timeout=5.0)

    assert len(intervals) == 2
    assert lpath.is_file()  # never deleted
    intervals.sort(key=lambda item: item[1])
    _, _, first_end = intervals[0]
    _, second_start, _ = intervals[1]
    assert second_start >= first_end


def test_gpu_lock_waits_for_free_memory_and_times_out(tmp_path: Path) -> None:
    """AC-H6: Polls free memory until >= 12 GiB; raises TimeoutError when busy too long."""
    lpath = tmp_path / "gpu.lock"
    readings = [4096, 8192, 14000]

    def mem_seq() -> int:
        return readings.pop(0) if len(readings) > 1 else readings[0]

    with gpu_lock.acquire(
        lock_path=lpath,
        min_free_mib=12288,
        poll_s=0.01,
        timeout_s=2.0,
        memory_fn=mem_seq,
    ):
        assert readings == [14000]

    # Timeout when memory stays below threshold
    with pytest.raises(TimeoutError, match="failed:pose: the GPU is busy, try again later"):
        with gpu_lock.acquire(
            lock_path=lpath,
            min_free_mib=12288,
            poll_s=0.02,
            timeout_s=0.1,
            memory_fn=lambda: 2048,
        ):
            pass


def test_gpu_lock_times_out_when_flock_held_externally(tmp_path: Path) -> None:
    """AC-H6: Times out if another process holds `flock` on `gpu.lock` past `timeout_s`."""
    lpath = tmp_path / "gpu.lock"
    fd = os.open(str(lpath), os.O_CREAT | os.O_RDWR, 0o666)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(TimeoutError, match="failed:pose: the GPU is busy, try again later"):
            with gpu_lock.acquire(
                lock_path=lpath,
                min_free_mib=12288,
                poll_s=0.02,
                timeout_s=0.1,
                memory_fn=lambda: 16384,
            ):
                pass
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def test_concurrent_admission_lets_two_calls_overlap_when_memory_allows(tmp_path: Path) -> None:
    """Two jobs at once: admission is serialized, the call bodies overlap."""
    lpath = tmp_path / "gpu.lock"
    live, peak, mu = [0], [0], threading.Lock()

    def worker() -> None:
        with gpu_lock.acquire(
            lock_path=lpath, poll_s=0.01, timeout_s=5.0, memory_fn=lambda: 20000, concurrent=True, settle_s=0.0
        ):
            with mu:
                live[0] += 1
                peak[0] = max(peak[0], live[0])
            time.sleep(0.15)
            with mu:
                live[0] -= 1

    threads = [threading.Thread(target=worker) for _ in range(2)]
    [t.start() for t in threads]
    [t.join(5) for t in threads]
    assert peak[0] == 2


def test_concurrent_admission_waits_for_12_gib_and_settles_between_admissions(tmp_path: Path) -> None:
    lpath = tmp_path / "gpu.lock"
    free = [4000]
    stamps: list[float] = []

    def second() -> None:
        with gpu_lock.acquire(
            lock_path=lpath, poll_s=0.01, timeout_s=5.0, memory_fn=lambda: free[0], concurrent=True, settle_s=0.2
        ):
            stamps.append(time.monotonic())

    with gpu_lock.acquire(
        lock_path=lpath, poll_s=0.01, timeout_s=5.0, memory_fn=lambda: 20000, concurrent=True, settle_s=0.2
    ):
        first = time.monotonic()
        t = threading.Thread(target=second)
        t.start()
        time.sleep(0.1)
        assert stamps == []  # 4 GiB free is below the 12 GiB admission line
        free[0] = 13000
        t.join(5)
    assert stamps and stamps[0] - first >= 0.2
    with pytest.raises(TimeoutError):  # still too little free memory: the job waits, then gives up
        with gpu_lock.acquire(
            lock_path=lpath, poll_s=0.01, timeout_s=0.1, memory_fn=lambda: 11000, concurrent=True, settle_s=0.0
        ):
            pass
