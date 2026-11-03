"""GPU lock and free-VRAM check for serializing Part 2 calls (TICKET-009, AC-H6).

Priority classes (GPU guard). Every `acquire` waits as one of two classes:

- `staging` (HIGH): a wait from the staging server (`config.is_staging_server`), which runs the live takes, or any
  caller that passes `priority=HIGH` or sets SIMON7_GPU_PRIORITY=staging (a live take run elsewhere).
- `low` (LOW): everything else: lane and dev servers, evals, avatar builds (`avatar_jobs` passes LOW even on
  staging), SIMON7_GPU_PRIORITY=low.

A HIGH waiter writes a ticket file `<pid>-<thread>-<ns>` into `<lock>.waiters/` beside the lock file while it waits
and removes it once admitted. A LOW waiter that sees a live ticket (its pid still in /proc; a dead one's ticket is
removed) steps back: it drops whatever it took while waiting (in-process lock, flock) and waits until no ticket is
left, so the HIGH waiter is admitted first even when the LOW one queued earlier. Admission is the only point where
class counts: a holder of either class is never preempted, and a HIGH waiter still waits for a LOW holder to finish.

Part 2 takes the same lock file with a plain `flock(LOCK_EX | LOCK_NB)` poll (`part2.trackers.gpu_lock`). The lock
file and its flock are unchanged, so Part 2 stays compatible: it ignores the `.waiters` folder, and a Part 2 process
run on its own is an unranked waiter that can neither yield nor be held back. Part 2 children started by Part 7
take the flock only after Part 7 admitted them (`hold_flock=False`), so they inherit their parent's place. For that
call the HIGH ticket stays until the child (or a descendant) holds the flock, at most `gpu_handoff.HANDOFF_GRACE_S`
(TICKET-317), so Part 2's own yield sees it through the gap.
"""

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

from part7 import applog, config, gpu_handoff, job_gpu

_THREAD_LOCK = threading.Lock()
_ADMIT_LOCK = threading.Lock()  # guards `_last_admit`; admission itself holds `_THREAD_LOCK` and the file lock
_last_admit = float("-inf")
_active = 0  # admitted concurrent calls still running
_inside = 0  # TICKET-289: calls of this process past admission, still in their body (any mode)
_open = 0  # TICKET-320: `acquire` calls of this process from their start to their end (waiting or admitted)
_events = 0  # TICKET-320: counts every `acquire` start and end, so a measurement window can tell one happened
_ACTIVITY_LOCK = threading.Lock()  # guards `_open` and `_events` only: never held across a sleep (`_wait_settle`)
ADMIT_SETTLE_S = 20.0  # a new job's model takes this long to show in free memory, so admissions are spaced
BUSY_MESSAGE = "failed:pose: the GPU is busy, try again later"
WSL_NVIDIA_SMI = "/usr/lib/wsl/lib/nvidia-smi"  # WSL2 keeps it here; a service PATH often lacks the directory
UNKNOWN_MESSAGE = "gpu free memory unknown (nvidia-smi not found or failed); admitting without the memory wait"
_warned_unknown = False
WAIT_LOG_S = 1.0  # TICKET-067: an admission wait longer than this is logged with its reason
HOLDER_LOG_S = 60.0  # TICKET-089: a flock wait this long names the holder, once per call
HOLDER_RELOG_S = 300.0  # TICKET-101: a wait this long that now has a different holder names it once more
PROC_ROOT = "/proc"
PROC_LOCKS = f"{PROC_ROOT}/locks"
HIGH = "staging"  # priority class of the staging server and live takes
LOW = "low"  # lane, dev, eval and avatar jobs
PRIORITY_ENV = "SIMON7_GPU_PRIORITY"
WAITERS_SUFFIX = ".waiters"
NOTE_AFTER_S = 2.0  # TICKET-289: an admission wait this long shows on the job record (job_gpu.waiting)
NOTE_POLL_S = 1.0  # how often the job's wait reason is looked at again while it waits


class _Yield(Exception):
    """A LOW waiter saw a HIGH ticket: it drops what it took and waits for its turn again."""


def default_priority() -> str:
    """SIMON7_GPU_PRIORITY (`staging`/`high` or `low`) when set, else HIGH on the staging server and LOW elsewhere."""
    raw = os.environ.get(PRIORITY_ENV, "").strip().lower()
    if raw in (HIGH, "high"):
        return HIGH
    if raw == LOW:
        return LOW
    return HIGH if config.is_staging_server() else LOW


def waiters_dir(lock_path: Path | str) -> Path:
    """The folder of HIGH waiter tickets beside the lock file (`<lock>.waiters`)."""
    lpath = Path(lock_path)
    return lpath.parent / (lpath.name + WAITERS_SUFFIX)


def _register(lock_path: Path, priority: str) -> Path | None:
    """Write this HIGH waiter's ticket; None for LOW (it has none)."""
    if priority != HIGH:
        return None
    folder = waiters_dir(lock_path)
    folder.mkdir(parents=True, exist_ok=True)
    ticket = folder / f"{os.getpid()}-{threading.get_ident()}-{time.time_ns()}"
    ticket.write_text("", encoding="utf-8")
    return ticket


def _drop_ticket(ticket: Path | None) -> None:
    if ticket is not None:
        with contextlib.suppress(OSError):
            ticket.unlink()


def high_waiting(lock_path: Path | str) -> bool:
    """True while a live HIGH waiter has a ticket for `lock_path`. A ticket whose pid is gone is removed."""
    try:
        entries = list(waiters_dir(lock_path).iterdir())
    except OSError:
        return False
    for entry in entries:
        pid = entry.name.split("-", 1)[0]
        if pid.isdigit() and Path(f"{PROC_ROOT}/{pid}").exists():
            return True
        with contextlib.suppress(OSError):
            entry.unlink()
    return False


class _Waits:
    """Seconds spent in each admission phase and the last free-memory reading, for the `gpu wait` log line."""

    def __init__(self, min_free_mib: int) -> None:
        self.t0 = time.monotonic()
        self.phases: dict[str, float] = {}
        self.min_free_mib = min_free_mib
        self.free_mib: int | None = None
        self.current = "thread"  # the phase the waiter is in now (TICKET-289)

    def add(self, phase: str, since: float) -> None:
        self.phases[phase] = self.phases.get(phase, 0.0) + time.monotonic() - since

    def reason(self) -> str:
        phase = max(self.phases, key=lambda k: self.phases[k]) if self.phases else "thread"
        if phase == "memory":
            return f"free {self.free_mib} MiB < {self.min_free_mib} MiB"
        return {"thread": "another Part 7 call admitting", "flock": "flock held", "settle": "settle",
                "priority": "a staging wait goes first"}[phase]

    def log(self, job_dir: Path | str | None, timed_out: bool = False) -> None:
        waited = time.monotonic() - self.t0
        if waited <= WAIT_LOG_S and not timed_out:
            return
        job = applog.job_id_of(job_dir) if job_dir is not None else None
        end = ", timed out" if timed_out else ""
        applog.log(f"gpu wait {waited:.1f} s (reason: {self.reason()}{end})", job, job_dir)


def _read_proc_locks() -> str:
    try:
        return Path(PROC_LOCKS).read_text(encoding="utf-8")
    except OSError:
        return ""


def _read_cmdline(pid: int, limit: int = 120) -> str:
    try:
        raw = Path(f"{PROC_ROOT}/{pid}/cmdline").read_bytes()
    except OSError:
        return ""
    return raw.replace(b"\0", b" ").decode("utf-8", "replace").strip()[:limit]


def _read_cwd(pid: int) -> str:
    try:
        return os.readlink(f"{PROC_ROOT}/{pid}/cwd")
    except OSError:
        return ""


def _read_ppid_and_age(pid: int) -> tuple[int | None, float | None]:
    """Parent pid and seconds since start from `/proc/<pid>/stat` (fields after the `(comm)`) and `/proc/uptime`."""
    try:
        stat = Path(f"{PROC_ROOT}/{pid}/stat").read_text(encoding="utf-8", errors="replace")
        rest = stat[stat.rindex(")") + 2:].split()  # rest[0] is field 3 (state)
        ppid = int(rest[1])
        start_ticks = int(rest[19])  # field 22
        uptime = float(Path(f"{PROC_ROOT}/uptime").read_text(encoding="utf-8").split()[0])
        return ppid, max(0.0, uptime - start_ticks / os.sysconf("SC_CLK_TCK"))
    except (OSError, ValueError, IndexError):
        return None, None


def _under(path: str, root: Path | str) -> bool:
    root_s = str(root).rstrip("/")
    return path == root_s or path.startswith(root_s + "/")


def holder_owner(cwd: str, cmd: str, ppid: int | None, lock_path: Path | str) -> str:
    """Guess who started the holder (TICKET-101): `staging`, `part7-other`, `part2`, else `other`."""
    state = config.state_root()
    here = [cwd, *cmd.split()]
    if any(_under(x, config.staging_dir() / "jobs") for x in here) and ppid == os.getpid():
        return "staging"
    if any(_under(x, state) for x in here):
        return "part7-other"
    part2_roots = (Path(lock_path).parent, config.part_dir(2))
    if any(_under(x, r) for x in here for r in part2_roots) or "part2" in cmd:
        return "part2"
    return "other"


def describe_holder(pid: int, lock_path: Path | str) -> str:
    """One line that identifies a holder after it has exited: owner, cwd, parent, age and command. Read only."""
    cmd = _read_cmdline(pid)
    cwd = _read_cwd(pid)
    ppid, age = _read_ppid_and_age(pid)
    parent = _read_cmdline(ppid, 160) if ppid else ""
    age_text = f"{age:.1f}" if age is not None else "?"
    owner = holder_owner(cwd, cmd, ppid, lock_path)
    return (f"pid {pid} owner={owner} cwd={cwd or '?'} ppid={ppid if ppid is not None else '?'} "
            f"parent={parent or '?'} elapsed={age_text} s cmd={cmd}").rstrip()


def lock_holder_pid(lock_path: Path | str) -> int | None:
    """Pid of the process holding a flock on `lock_path` other than this one, or None. Reads only (TICKET-089).

    `/proc/locks` lines read `1: FLOCK  ADVISORY  WRITE <pid> <major>:<minor>:<inode> 0 EOF`.
    """
    try:
        inode = os.stat(lock_path).st_ino
    except OSError:
        return None
    for line in _read_proc_locks().splitlines():
        fields = line.split()
        if len(fields) < 6 or fields[1] != "FLOCK" or not fields[4].isdigit():
            continue
        if fields[5].rsplit(":", 1)[-1] == str(inode) and int(fields[4]) != os.getpid():
            return int(fields[4])
    return None


def lock_holder(lock_path: Path | str) -> str | None:
    """`pid <n> owner=... cwd=... ppid=... parent=... elapsed=... s cmd=...` of the flock holder, or None. Never signals."""
    pid = lock_holder_pid(lock_path)
    return None if pid is None else describe_holder(pid, lock_path)


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


def _no_yield() -> bool:
    return False


def _wait_turn(must_yield: Callable[[], bool], deadline: float, step_sleep: float, waits: _Waits) -> None:
    """A LOW waiter sleeps here while a HIGH waiter has a ticket (the HIGH one never does)."""
    since = time.monotonic()
    waits.current = "priority"
    try:
        while must_yield():
            if time.monotonic() >= deadline:
                raise TimeoutError(BUSY_MESSAGE)
            time.sleep(min(step_sleep, max(0.001, deadline - time.monotonic())))
    finally:
        waits.add("priority", since)


def _take_thread_lock(deadline: float, step_sleep: float, waits: _Waits,
                      must_yield: Callable[[], bool] = _no_yield) -> None:
    since = time.monotonic()
    waits.current = "thread"
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            waits.add("thread", since)
            raise TimeoutError(BUSY_MESSAGE)
        if _THREAD_LOCK.acquire(timeout=min(step_sleep, remaining)):
            waits.add("thread", since)
            return
        if must_yield():
            waits.add("thread", since)
            raise _Yield()


def _take_flock(fd: int, deadline: float, step_sleep: float, waits: _Waits,
                lock_path: Path | None = None, job_dir: Path | str | None = None,
                must_yield: Callable[[], bool] = _no_yield) -> bool:
    since = time.monotonic()
    waits.current = "flock"
    named_pid: int | None = None
    relogged = False
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return True
            except BlockingIOError as exc:
                waited = time.monotonic() - since
                if lock_path is not None and waited >= HOLDER_LOG_S and not relogged:
                    pid = lock_holder_pid(lock_path)
                    again = named_pid is not None and waited >= HOLDER_RELOG_S and pid not in (None, named_pid)
                    if pid is not None and (named_pid is None or again):
                        relogged = again
                        named_pid = pid
                        job = applog.job_id_of(job_dir) if job_dir is not None else None
                        applog.log(f"gpu wait: lock held by {describe_holder(pid, lock_path)}", job, job_dir)
                if time.monotonic() >= deadline:
                    raise TimeoutError(BUSY_MESSAGE) from exc
                if must_yield():
                    raise _Yield() from exc
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
                 waits: _Waits, job_dir: Path | str | None = None,
                 must_yield: Callable[[], bool] = _no_yield) -> None:
    """Poll free GPU memory until `min_free_mib` (0: no wait, the CPU backend holds the lock only).

    No reading (None: tool missing, nonzero exit, unparsable) is "unknown", not "short": the call is admitted at
    once with a warning, because waiting cannot make the reading appear (TICKET-069). A real reading below the
    minimum still waits until the deadline.
    """
    since = time.monotonic()
    waits.current = "memory"
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
            if must_yield():
                raise _Yield()
            time.sleep(min(poll_s, max(0.001, deadline - time.monotonic())))
    finally:
        waits.add("memory", since)


def wait_free(lock_path: Path | str | None = None, timeout_s: float = 30.0, poll_s: float = 0.1) -> bool:
    """True once no process holds the GPU file lock (taken and dropped at once); False when `timeout_s` passes first.

    Used after a worker was killed (TICKET-129): a child that inherited the lock's descriptor keeps it held, and the
    next GPU call should not start before it is free.
    """
    lpath = Path(lock_path) if lock_path is not None else config.gpu_lock_path()
    lpath.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + max(0.0, timeout_s)
    fd = os.open(str(lpath), os.O_CREAT | os.O_RDWR, 0o666)
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(fd, fcntl.LOCK_UN)
                return True
            except OSError:
                if time.monotonic() >= deadline:
                    return False
                time.sleep(poll_s)
    finally:
        os.close(fd)


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
    priority: str | None = None,
    wait_since: float | None = None,
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

    `priority` is HIGH or LOW (None: `default_priority()`); see the module docstring for the classes.

    `wait_since` (epoch seconds) is when the job's GPU wait began, for a caller that admits again in the same wait
    (TICKET-320: a take that goes on waiting for the warm worker); the job record keeps that start. None: now.
    """
    lpath = Path(lock_path) if lock_path is not None else config.gpu_lock_path()
    lpath.parent.mkdir(parents=True, exist_ok=True)
    mem_check = memory_fn or free_gpu_memory_mib
    deadline = time.monotonic() + timeout_s
    step_sleep = max(0.005, min(poll_s, 0.05 if timeout_s < 5.0 else poll_s))

    waits = _Waits(min_free_mib)
    prio = priority or default_priority()
    must_yield = (lambda: high_waiting(lpath)) if prio == LOW else _no_yield
    ticket = _register(lpath, prio)
    flocked = False
    released = False
    counted = False
    inside = False
    fd = -1
    handoff: gpu_handoff.Handoff | None = None
    watch = _Watch(lpath, waits, job_dir, wait_since)
    _note(1)
    try:
        fd, flocked = _admit(lpath, min_free_mib, mem_check, poll_s, deadline, step_sleep, waits, job_dir, must_yield)
        if ticket is not None and not hold_flock:
            # TICKET-317: the Part 2 child takes the flock after this; Part 2's yield needs the ticket until then.
            handoff = gpu_handoff.Handoff(ticket, lambda: _child_holds(lpath), job_dir)
        else:
            _drop_ticket(ticket)
        try:
            if concurrent:
                since = time.monotonic()
                waits.current = "settle"
                _wait_settle(settle_s, deadline)
                waits.add("settle", since)
                counted = True
        except TimeoutError:
            waits.log(job_dir, timed_out=True)
            raise
        waits.log(job_dir)
        watch.stop()
        if not hold_flock or concurrent:
            fcntl.flock(fd, fcntl.LOCK_UN)
            flocked = False
        if concurrent:
            _THREAD_LOCK.release()
            released = True
        inside = _enter()
        yield
    finally:
        _note(-1)
        watch.stop()
        if inside:
            _exit()
        if handoff is not None:
            handoff.stop()
        _drop_ticket(ticket)
        if fd >= 0:
            _close(fd, flocked)
            if counted:
                _leave()
            if not released:
                _THREAD_LOCK.release()


def _child_holds(lock_path: Path) -> bool:
    """True when the flock is held by a process this one started (the admitted Part 2 child or its descendant)."""
    pid = lock_holder_pid(lock_path)
    return pid is not None and _from_here(pid)


def _close(fd: int, flocked: bool) -> None:
    if flocked:
        with contextlib.suppress(OSError):
            fcntl.flock(fd, fcntl.LOCK_UN)
    with contextlib.suppress(OSError):
        os.close(fd)


def _admit(lpath: Path, min_free_mib: int, mem_check: Callable[[], int | None], poll_s: float, deadline: float,
           step_sleep: float, waits: _Waits, job_dir: Path | str | None,
           must_yield: Callable[[], bool]) -> tuple[int, bool]:
    """Take the in-process lock and the flock and wait for memory, in this waiter's class order.

    Returns (fd, flocked) with `_THREAD_LOCK` held. A LOW waiter that sees a HIGH ticket drops all it took and waits
    for its turn again (`_Yield`); a timeout is logged and raised with nothing held.
    """
    while True:
        try:
            _wait_turn(must_yield, deadline, step_sleep, waits)
            _take_thread_lock(deadline, step_sleep, waits, must_yield)
        except _Yield:
            continue
        except TimeoutError:
            waits.log(job_dir, timed_out=True)
            raise
        fd = os.open(str(lpath), os.O_CREAT | os.O_RDWR, 0o666)
        flocked = False
        try:
            flocked = _take_flock(fd, deadline, step_sleep, waits, lpath, job_dir, must_yield)
            _wait_memory(min_free_mib, mem_check, poll_s, deadline, waits, job_dir, must_yield)
            return fd, flocked
        except _Yield:
            _close(fd, flocked)
            _THREAD_LOCK.release()
        except BaseException as exc:
            _close(fd, flocked)
            _THREAD_LOCK.release()
            if isinstance(exc, TimeoutError):
                waits.log(job_dir, timed_out=True)
            raise


def _note(step: int) -> None:
    global _open, _events
    with _ACTIVITY_LOCK:
        _open, _events = max(0, _open + step), _events + 1


def activity() -> tuple[int, int]:
    """`(events, open)`: TICKET-320's view of GPU admissions in this process. Two equal readings with `open` 0 mean no
    admission waited, ran or ended between them (a warm worker's load measurement is then clean)."""
    with _ACTIVITY_LOCK:
        return _events, _open


def _enter() -> bool:
    global _inside
    with _ADMIT_LOCK:
        _inside += 1
    return True


def _exit() -> None:
    global _inside
    with _ADMIT_LOCK:
        _inside = max(0, _inside - 1)


def _from_here(pid: int, depth: int = 8) -> bool:
    """True when `pid` is this process or one it started (a Part 2 child, a warm worker), by walking parent pids."""
    me = os.getpid()
    for _ in range(depth):
        if pid == me:
            return True
        parent = _read_ppid_and_age(pid)[0]
        if not parent or parent == pid:
            return False
        pid = parent
    return False


def wait_class(lock_path: Path | str, phase: str) -> str:
    """Why a waiter waits, in the words the job record uses (TICKET-289): an outside flock holder is other GPU work;
    so is short memory while none of this process's calls runs; anything else is another take of this server."""
    pid = lock_holder_pid(lock_path)
    if pid is not None and not _from_here(pid):
        return job_gpu.OTHER_WORK
    if phase == "memory" and _active == 0 and _inside == 0:
        return job_gpu.OTHER_WORK
    return job_gpu.ANOTHER_TAKE


def holder_class(lock_path: Path | str) -> str:
    """The flock holder in words for a finding (TICKET-305): `part2 run outside staging (<worktree folder>)`, no pid and
    no path beyond the folder name. `other GPU work` when the holder is gone or unreadable."""
    pid = lock_holder_pid(lock_path)
    if pid is None:
        return job_gpu.OTHER_WORK
    cwd = _read_cwd(pid)
    ppid = _read_ppid_and_age(pid)[0]
    owner = holder_owner(cwd, _read_cmdline(pid), ppid, lock_path)
    label = {"part2": "part2 run outside staging", "part7-other": "another Part 7 server", "other": "another process"}.get(
        owner, job_gpu.OTHER_WORK)
    folder = Path(cwd).name if cwd and cwd != "/" else ""
    return f"{label} ({folder})" if folder else label


def gpu_status(lock_path: Path | str | None = None) -> dict[str, object]:
    """`{busy, holder}` for api/health (TICKET-289): `holder` is `other` while a process this server did not start
    holds the GPU lock, `part7` while a call of this server holds it or runs past admission, else None. No pid."""
    lpath = Path(lock_path) if lock_path is not None else config.gpu_lock_path()
    pid = lock_holder_pid(lpath)
    if pid is not None and not _from_here(pid):
        return {"busy": True, "holder": "other"}
    if pid is not None or _inside > 0:
        return {"busy": True, "holder": "part7"}
    return {"busy": False, "holder": None}


class _Watch:
    """While a job's admission waits past NOTE_AFTER_S, keep its record's `wait` set (job_gpu); clear it at the end.

    Runs only for a `job_dir` inside a running job. A daemon thread looks at the phase every NOTE_POLL_S and writes
    only when the reason class changes, so a long wait costs one record write per change.
    """

    def __init__(self, lock_path: Path, waits: _Waits, job_dir: Path | str | None, since: float | None = None) -> None:
        self.lock_path, self.waits, self.job_dir = lock_path, waits, job_dir
        self.since = time.time() if since is None else since
        self.shown: str | None = None
        self.done = threading.Event()
        self.thread: threading.Thread | None = None
        if job_dir is not None and job_gpu.tracked(job_dir):
            self.thread = threading.Thread(target=self._run, name="gpu-wait-note", daemon=True)
            self.thread.start()

    def _run(self) -> None:
        while not self.done.wait(NOTE_POLL_S):
            if time.monotonic() - self.waits.t0 < NOTE_AFTER_S:
                continue
            reason = wait_class(self.lock_path, self.waits.current)
            if reason != self.shown and not self.done.is_set():
                self.shown = reason
                job_gpu.waiting(self.job_dir, reason, self.since)

    def stop(self) -> None:
        if self.done.is_set():
            return
        self.done.set()
        if self.thread is not None:
            self.thread.join(5.0)
        if self.shown is not None:
            job_gpu.admitted(self.job_dir)
