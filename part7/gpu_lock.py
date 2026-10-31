"""GPU lock and free-VRAM check for serializing Part 2 calls (TICKET-009, AC-H6)."""

from __future__ import annotations

import contextlib
import fcntl
import logging
import os
from pathlib import Path
import shutil
import subprocess
import threading
import time
from typing import Callable, Iterator

from part7 import applog, config

_THREAD_LOCK = threading.Lock()
_ADMIT_LOCK = threading.Lock()  # guards `_last_admit`; admission itself holds `_THREAD_LOCK` and the file lock
_last_admit = float("-inf")
_active = 0  # admitted concurrent calls still running
ADMIT_SETTLE_S = 20.0  # a new job's model takes this long to show in free memory, so admissions are spaced
BUSY_MESSAGE = "failed:pose: the GPU is busy, try again later"
WSL_NVIDIA_SMI = "/usr/lib/wsl/lib/nvidia-smi"  # WSL2 keeps it here; a service PATH often lacks the directory
UNKNOWN_MESSAGE = "gpu free memory unknown (nvidia-smi not found or failed); admitting without the memory wait"
_warned_unknown = False
WAIT_LOG_S = 1.0  # TICKET-067: an admission wait longer than this is logged with its reason


class _Waits:
    """Seconds spent in each admission phase and the last free-memory reading, for the `gpu wait` log line."""

    def __init__(self, min_free_mib: int) -> None:
        self.t0 = time.monotonic()
        self.phases: dict[str, float] = {}
        self.min_free_mib = min_free_mib
        self.free_mib: int | None = None

    def add(self, phase: str, since: float) -> None:
        self.phases[phase] = self.phases.get(phase, 0.0) + time.monotonic() - since

    def reason(self) -> str:
        phase = max(self.phases, key=lambda k: self.phases[k]) if self.phases else "thread"
        if phase == "memory":
            return f"free {self.free_mib} MiB < {self.min_free_mib} MiB"
        return {"thread": "another Part 7 call admitting", "flock": "flock held", "settle": "settle"}[phase]

    def log(self, job_dir: Path | str | None, timed_out: bool = False) -> None:
        waited = time.monotonic() - self.t0
        if waited <= WAIT_LOG_S and not timed_out:
            return
        job = applog.job_id_of(job_dir) if job_dir is not None else None
        end = ", timed out" if timed_out else ""
        applog.log(f"gpu wait {waited:.1f} s (reason: {self.reason()}{end})", job, job_dir)


def nvidia_smi_path() -> str | None:
    """The `nvidia-smi` binary: on PATH, else the WSL2 location, else None (TICKET-069). The one resolver."""
    found = shutil.which("nvidia-smi")
    if found:
        return found
    if os.path.isfile(WSL_NVIDIA_SMI) and os.access(WSL_NVIDIA_SMI, os.X_OK):
        return WSL_NVIDIA_SMI
    return None


def free_gpu_memory_mib() -> int | None:
    """Return free GPU memory in MiB from `nvidia-smi`, or None if unavailable."""
    smi = nvidia_smi_path()
    if smi is None:
        return None
    try:
        res = subprocess.run(
            [
                smi,
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


def _take_thread_lock(deadline: float, step_sleep: float, waits: _Waits) -> None:
    since = time.monotonic()
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            waits.add("thread", since)
            raise TimeoutError(BUSY_MESSAGE)
        if _THREAD_LOCK.acquire(timeout=min(step_sleep, remaining)):
            waits.add("thread", since)
            return


def _take_flock(fd: int, deadline: float, step_sleep: float, waits: _Waits) -> bool:
    since = time.monotonic()
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return True
            except BlockingIOError as exc:
                if time.monotonic() >= deadline:
                    raise TimeoutError(BUSY_MESSAGE) from exc
                time.sleep(min(step_sleep, max(0.001, deadline - time.monotonic())))
    finally:
        waits.add("flock", since)


def _warn_unknown(job_dir: Path | str | None) -> None:
    """Log the unknown-reading warning once per process, and into every affected job's log (TICKET-069)."""
    global _warned_unknown
    if job_dir is None and _warned_unknown:
        return
    _warned_unknown = True
    job = applog.job_id_of(job_dir) if job_dir is not None else None
    applog.log(UNKNOWN_MESSAGE, job, job_dir, level=logging.WARNING)


def _wait_memory(min_free_mib: int, mem_check: Callable[[], int | None], poll_s: float, deadline: float,
                 waits: _Waits, job_dir: Path | str | None = None) -> None:
    """Poll free GPU memory until `min_free_mib` (0: no wait, the CPU backend holds the lock only).

    No reading (None: tool missing, nonzero exit, unparsable) is "unknown", not "short": the call is admitted at
    once with a warning, because waiting cannot make the reading appear (TICKET-069). A real reading below the
    minimum still waits until the deadline.
    """
    since = time.monotonic()
    try:
        while min_free_mib > 0:
            free_mib = mem_check()
            if free_mib is None:
                _warn_unknown(job_dir)
                return
            if free_mib >= min_free_mib:
                return
            waits.free_mib = free_mib  # the last reading that was short is the reason
            if time.monotonic() >= deadline:
                raise TimeoutError(BUSY_MESSAGE)
            time.sleep(min(poll_s, max(0.001, deadline - time.monotonic())))
    finally:
        waits.add("memory", since)


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
    job_dir: Path | str | None = None,
) -> Iterator[None]:
    """Acquire the GPU file lock and wait until at least `min_free_mib` MiB is free (0 skips the wait).

    `hold_flock=False` drops the file lock once the wait is over and keeps the in-process lock for the
    call: Part 2's own CLI takes the same file lock for its inference (gpu_guard at the pin) and would
    otherwise wait for Part 7 forever.

    `concurrent=True` is admission only (ADR-0003 two GPU jobs at once): the locks are held while the wait for
    `min_free_mib` runs and for `settle_s` after the previous admission, then released before the call body, so
    two jobs run together when free memory covers both. A job that holds a warm worker passes `min_free_mib=0`.

    A wait over `WAIT_LOG_S` is logged once admitted (or on timeout) as `gpu wait <s> s (reason: ...)`, naming the
    phase that took longest; `job_dir` (any folder of a job) puts the line in that job's log too (TICKET-067).
    """
    lpath = Path(lock_path) if lock_path is not None else config.gpu_lock_path()
    lpath.parent.mkdir(parents=True, exist_ok=True)
    mem_check = memory_fn or free_gpu_memory_mib
    deadline = time.monotonic() + timeout_s
    step_sleep = max(0.005, min(poll_s, 0.05 if timeout_s < 5.0 else poll_s))

    waits = _Waits(min_free_mib)
    try:
        _take_thread_lock(deadline, step_sleep, waits)
    except TimeoutError:
        waits.log(job_dir, timed_out=True)
        raise

    fd = os.open(str(lpath), os.O_CREAT | os.O_RDWR, 0o666)
    flocked = False
    released = False
    counted = False
    try:
        try:
            flocked = _take_flock(fd, deadline, step_sleep, waits)
            _wait_memory(min_free_mib, mem_check, poll_s, deadline, waits, job_dir)
            if concurrent:
                since = time.monotonic()
                _wait_settle(settle_s, deadline)
                waits.add("settle", since)
                counted = True
        except TimeoutError:
            waits.log(job_dir, timed_out=True)
            raise
        waits.log(job_dir)
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
