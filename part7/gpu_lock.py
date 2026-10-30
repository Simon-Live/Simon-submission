"""GPU lock and free-VRAM check for serializing Part 2 calls (TICKET-009, AC-H6)."""

from __future__ import annotations

import contextlib
import fcntl
import os
from pathlib import Path
import subprocess
import threading
import time
from typing import Callable, Iterator

from part7 import config

_THREAD_LOCK = threading.Lock()
_ADMIT_LOCK = threading.Lock()  # guards `_last_admit`; admission itself holds `_THREAD_LOCK` and the file lock
_last_admit = float("-inf")
_active = 0  # admitted concurrent calls still running
ADMIT_SETTLE_S = 20.0  # a new job's model takes this long to show in free memory, so admissions are spaced
BUSY_MESSAGE = "failed:pose: the GPU is busy, try again later"


def free_gpu_memory_mib() -> int | None:
    """Return free GPU memory in MiB from `nvidia-smi`, or None if unavailable."""
    try:
        res = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=memory.free",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if res.returncode != 0 or not res.stdout.strip():
        return None
    first_line = res.stdout.strip().splitlines()[0].strip()
    try:
        return int(first_line)
    except ValueError:
        return None


def _wait_settle(settle_s: float | None, deadline: float) -> None:
    """Sleep until `settle_s` after the previous admission; record this admission. Called under the locks."""
    global _last_admit, _active
    gap = ADMIT_SETTLE_S if settle_s is None else settle_s
    with _ADMIT_LOCK:
        wait = _last_admit + gap - time.monotonic() if _active else 0.0
        if wait > 0:
            if time.monotonic() + wait > deadline:
                raise TimeoutError(BUSY_MESSAGE)
            time.sleep(wait)
        _last_admit = time.monotonic()
        _active += 1


def _leave() -> None:
    global _active
    with _ADMIT_LOCK:
        _active = max(0, _active - 1)


@contextlib.contextmanager
def acquire(
    lock_path: Path | str | None = None,
    min_free_mib: int = 12288,
    poll_s: float = 15.0,
    timeout_s: float = 1800.0,
    memory_fn: Callable[[], int | None] | None = None,
    hold_flock: bool = True,
    concurrent: bool = False,
    settle_s: float | None = None,
) -> Iterator[None]:
    """Acquire the GPU file lock and wait until at least `min_free_mib` MiB is free (0 skips the wait).

    `hold_flock=False` drops the file lock once the wait is over and keeps the in-process lock for the
    call: Part 2's own CLI takes the same file lock for its inference (gpu_guard at the pin) and would
    otherwise wait for Part 7 forever.

    `concurrent=True` is admission only (ADR-0003 two GPU jobs at once): the locks are held while the wait for
    `min_free_mib` runs and for `settle_s` after the previous admission, then released before the call body, so
    two jobs run together when free memory covers both. A job that holds a warm worker passes `min_free_mib=0`.
    """
    lpath = Path(lock_path) if lock_path is not None else config.gpu_lock_path()
    lpath.parent.mkdir(parents=True, exist_ok=True)
    mem_check = memory_fn or free_gpu_memory_mib
    deadline = time.monotonic() + timeout_s
    step_sleep = max(0.005, min(poll_s, 0.05 if timeout_s < 5.0 else poll_s))

    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(BUSY_MESSAGE)
        if _THREAD_LOCK.acquire(timeout=min(step_sleep, remaining)):
            break

    fd = os.open(str(lpath), os.O_CREAT | os.O_RDWR, 0o666)
    flocked = False
    released = False
    counted = False
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                flocked = True
                break
            except BlockingIOError as exc:
                if time.monotonic() >= deadline:
                    raise TimeoutError(BUSY_MESSAGE) from exc
                time.sleep(min(step_sleep, max(0.001, deadline - time.monotonic())))

        while min_free_mib > 0:  # the CPU backend holds the lock only, it needs no free GPU memory
            free_mib = mem_check()
            if free_mib is not None and free_mib >= min_free_mib:
                break
            if time.monotonic() >= deadline:
                raise TimeoutError(BUSY_MESSAGE)
            time.sleep(min(poll_s, max(0.001, deadline - time.monotonic())))

        if concurrent:
            _wait_settle(settle_s, deadline)
            counted = True
        if not hold_flock or concurrent:
            fcntl.flock(fd, fcntl.LOCK_UN)
            flocked = False
        if concurrent:
            _THREAD_LOCK.release()
            released = True
        yield
    finally:
        if flocked:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
        try:
            os.close(fd)
        except OSError:
            pass
        if counted:
            _leave()
        if not released:
            _THREAD_LOCK.release()
