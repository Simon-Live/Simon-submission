"""Non-staging Part 2 GPU work waits while a staging take waits for the GPU lock.

Spec: docs/specs/staging-yield.md. The wait runs at the start of a command and, since TICKET-056, before every later
GPU acquire of that process (the mid-run yield).

    staging_yield.gate(command)       # called by part2.cli.main; returns at once for a staging take or no waiter
    staging_yield.mark_staging_for_worker()   # a staging client tells the warm worker the request is a staging take

Part 7 writes a ticket file `<pid>-<thread>-<ns>` into `<lock>.waiters/` while a staging waiter waits; a ticket counts
while its pid is alive and started no later than the ticket (a reused pid does not count). A ticket of this process or
any ancestor is our caller's own and is ignored. This module only reads that folder (it never removes a ticket) and
never touches the lock.
"""
from __future__ import annotations

import functools
import os
import sys
import time
from pathlib import Path

PRIORITY_ENV = "SIMON7_GPU_PRIORITY"          # Part 7's own variable: `staging` marks a staging take
RELAY_ENV = "PART2_GPU_PRIORITY"              # crosses the warm-worker socket (only PART2_* does)
STAGING = ("staging", "high")
WAITERS_SUFFIX = ".waiters"
GPU_COMMANDS = frozenset({"run", "track", "serve-worker", "avatar", "autorig", "image3d", "stock"})
POLL_S = 1.0
MESSAGE = "part2: waiting for a staging take ({n} waiting)"
YIELD_TIMEOUT_ENV = "PART2_YIELD_TIMEOUT_S"   # TICKET-056: the yield budget of one process
YIELD_TIMEOUT_S = 1800.0
GRACE_ENV = "PART2_YIELD_GRACE_S"             # after the last ticket is gone: the longest wait for the take's child
GRACE_S = 30.0
STUCK_ENV = "PART2_YIELD_STUCK_S"             # a ticket's own process holding the flock this long is stuck on memory
STUCK_S = 10.0
HANDOFF_POLL_S = 0.2
START_SLACK_S = 5.0                           # clock-tick and boot-time rounding when a pid's start is compared
TIMEOUT_MESSAGE = "part2: gave up waiting for a staging take after {s:.0f} s ({n} still waiting); not yielding again"
STAND_DOWN_MESSAGE = ("part2: a staging take has held the GPU lock for {s:.0f} s while waiting for memory; "
                      "not yielding, waiting for the lock itself")
GRACE_MESSAGE = "part2: no staging process took the GPU lock within {s:.0f} s of its ticket going; continuing"
RESUME_MESSAGE = "part2: staging take cleared; resuming GPU work"
PROC_LOCKS = "/proc/locks"

_BUDGET = {"spent": 0.0, "over": False}       # one yield budget per process (R2)


def lock_path() -> Path:
    from part2 import trackers

    return Path(os.environ.get(trackers.GPU_LOCK_ENV) or trackers.GPU_LOCK_DEFAULT).expanduser()


def waiters_dir(lock: Path | str | None = None) -> Path:
    lock = Path(lock) if lock is not None else lock_path()
    return lock.parent / (lock.name + WAITERS_SUFFIX)


def is_staging(env=None) -> bool:
    env = os.environ if env is None else env
    return any(env.get(k, "").strip().lower() in STAGING for k in (PRIORITY_ENV, RELAY_ENV))


def _stat_tail(pid: int) -> list[str] | None:
    """The /proc/<pid>/stat fields after the parenthesised name (index 0 is field 3, the state)."""
    try:
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
    except (OSError, IndexError):
        return None


def _ppid(pid: int) -> int:
    """Parent pid from /proc/<pid>/stat (field 4); 0 when unreadable."""
    tail = _stat_tail(pid)
    try:
        return int(tail[1]) if tail else 0
    except (IndexError, ValueError):
        return 0


def _started_at(pid: int) -> float | None:
    """Epoch seconds at which `pid` started (boot time plus start ticks), or None when unreadable."""
    tail = _stat_tail(pid)
    try:
        ticks = int(tail[19])
        btime = next(int(ln.split()[1]) for ln in Path("/proc/stat").read_text().splitlines() if ln.startswith("btime "))
        return btime + ticks / os.sysconf("SC_CLK_TCK")
    except (TypeError, IndexError, ValueError, StopIteration, OSError):
        return None


def _alive(pid: int, ticket_ns: int | None = None) -> bool:
    """The pid exists and, when the ticket carries its time, was not started after the ticket (pid reuse, R3)."""
    if not Path(f"/proc/{pid}").exists():
        return False
    started = _started_at(pid) if ticket_ns else None
    return started is None or started <= ticket_ns / 1e9 + START_SLACK_S


def ancestors(pid: int | None = None) -> set[int]:
    """This process, its parent and every ancestor up to pid 1. A ticket of one of them is our own caller's: Part 7's
    server, its subprocesses and the warm workers are all children of one server, so we never wait on them."""
    pid = os.getpid() if pid is None else pid
    seen: set[int] = set()
    while pid > 0 and pid not in seen:
        seen.add(pid)
        pid = _ppid(pid)
    return seen


def _live_tickets(lock, own: set[int]) -> set[int]:
    """Pids of the live tickets beside the lock that are not ours or an ancestor's; empty when the folder is absent."""
    try:
        names = [p.name for p in waiters_dir(lock).iterdir()]
    except OSError:
        return set()
    live = set()
    for name in names:
        parts = name.split("-")
        if not parts[0].isdigit() or int(parts[0]) in own:
            continue
        ns = int(parts[2]) if len(parts) == 3 and parts[2].isdigit() else None
        if _alive(int(parts[0]), ns):
            live.add(int(parts[0]))
    return live


def staging_waiting(lock: Path | str | None = None) -> int:
    """How many processes have a live ticket beside the lock that is not ours or an ancestor's; 0 when absent."""
    return len(_live_tickets(lock, ancestors()))


def wait_for_staging(lock: Path | str | None = None, poll_s: float = POLL_S, sleep=time.sleep, log=None,
                     env=None) -> int:
    """Block while a live staging ticket exists, unless this process is a staging take. Logs one line on the first
    wait. Returns the number of polls that waited (0 when it did not wait). The command-start wait."""
    if is_staging(env):
        return 0
    log = log or (lambda line: print(line, file=sys.stderr, flush=True))
    polls = 0
    while True:
        n = staging_waiting(lock)
        if n == 0:
            return polls
        if polls == 0:
            log(MESSAGE.format(n=n))
        polls += 1
        sleep(poll_s)


# ---- the mid-run yield (TICKET-056) ---------------------------------------------------------------------------

def _env_float(name: str, default: float, env=None) -> float:
    env = os.environ if env is None else env
    try:
        return max(0.0, float(env.get(name, default)))
    except ValueError:
        return default


def yield_timeout_s(env=None) -> float:
    return _env_float(YIELD_TIMEOUT_ENV, YIELD_TIMEOUT_S, env)


def grace_s(env=None) -> float:
    return _env_float(GRACE_ENV, GRACE_S, env)


def reset_budget() -> None:
    """Forget the spent yield budget (tests; a long-lived worker never calls it)."""
    _BUDGET.update(spent=0.0, over=False)


def flock_holders(lock: Path | str) -> set[int]:
    """Pids that hold a flock on `lock`, from /proc/locks (read only; device and inode both match). Empty when it
    cannot be read."""
    try:
        st = os.stat(lock)
        text = Path(PROC_LOCKS).read_text()
    except OSError:
        return set()
    want = (os.major(st.st_dev), os.minor(st.st_dev), st.st_ino)
    holders = set()
    for line in text.splitlines():
        f = line.split()
        if len(f) < 6 or f[1] != "FLOCK" or not f[4].isdigit():
            continue
        try:
            major, minor, inode = f[5].split(":")
            if (int(major, 16), int(minor, 16), int(inode)) == want:
                holders.add(int(f[4]))
        except ValueError:
            continue
    return holders


def yield_to_staging(lock: Path | str | None = None, *, sleep=time.sleep, clock=time.monotonic, log=None, env=None,
                     poll_s: float = POLL_S, handoff_poll_s: float = HANDOFF_POLL_S) -> int:
    """The mid-run yield point: called while this process holds nothing, just before it takes the GPU lock again.

    No staging take, or a live ticket none of ours: returns 0 at once. With a ticket it waits until none is left,
    then waits for the take to use the lock: a process that takes the flock after the ticket went (the Part 2 child
    Part 7 starts on admission) and releases it, at most PART2_YIELD_GRACE_S. A holder that was already holding when
    the ticket went is the admission itself and does not count until it lets go and takes the lock again.
    Stands down, to the lock's own wait, when a ticket's own process holds the flock with its ticket still live for
    PART2_YIELD_STUCK_S: Part 7 takes the flock and then waits for free memory, and this process, models loaded, may be
    what it waits for. A third party holding the flock does not stop the yield. One budget per process
    (PART2_YIELD_TIMEOUT_S): after it runs out the process never yields again. Returns the polls that waited."""
    if is_staging(env) or _BUDGET["over"]:
        return 0
    log = log or (lambda line: print(line, file=sys.stderr, flush=True))
    lock = Path(lock) if lock is not None else lock_path()
    own = ancestors()
    budget = max(0.0, yield_timeout_s(env) - _BUDGET["spent"])
    grace, stuck_s = grace_s(env), _env_float(STUCK_ENV, STUCK_S, env)
    start = clock()
    polls, held_since, pre, handoff_at, took = 0, {}, None, None, False
    try:
        while True:
            live = _live_tickets(lock, own)
            holders = flock_holders(lock) - own
            if live:
                pre, handoff_at, took = None, None, False
                now = clock()
                held_since = {p: held_since.get(p, now) for p in holders & live}
                if any(now - t >= stuck_s for t in held_since.values()):
                    log(STAND_DOWN_MESSAGE.format(s=stuck_s))
                    return polls
                if now - start >= budget:
                    _BUDGET["over"] = True
                    log(TIMEOUT_MESSAGE.format(s=yield_timeout_s(env), n=len(live)))
                    return polls
                if polls == 0:
                    log(MESSAGE.format(n=len(live)))
                polls += 1
                sleep(poll_s)
                continue
            if polls == 0:
                return 0
            if pre is None:
                pre, handoff_at = set(holders), clock()
            pre &= holders  # a holder that let go and takes the lock again is a taker
            taking = holders - pre
            took = took or bool(taking)
            if took and not taking:
                break
            if clock() - handoff_at >= grace:
                log(GRACE_MESSAGE.format(s=grace))
                break
            sleep(handoff_poll_s)
        log(RESUME_MESSAGE)
        return polls
    finally:
        _BUDGET["spent"] += clock() - start


def _yielding(original):
    @functools.wraps(original)
    def gpu_lock(*args, **kwargs):
        yield_to_staging()  # nothing is held here: the flock of the clip before is released, the next not yet taken
        return original(*args, **kwargs)

    gpu_lock.staging_yield = True
    gpu_lock.staging_original = original
    return gpu_lock


def install() -> bool:
    """Make every later `part2.trackers.gpu_lock()` (so `gpu_guard.gpu_lock()` and `output_steps.gpu_locked`, which
    look it up at call time) a yield point. The stamped files stay untouched. Idempotent; True when it installed."""
    from part2 import trackers

    if getattr(trackers.gpu_lock, "staging_yield", False):
        return False
    trackers.gpu_lock = _yielding(trackers.gpu_lock)
    return True


def gate(command: str) -> None:
    """The one call of part2.cli.main for a command that can take the GPU lock."""
    if command in GPU_COMMANDS:
        wait_for_staging()
        install()


def mark_staging_for_worker() -> None:
    """A staging client forwarding to the warm worker sets PART2_GPU_PRIORITY so the worker, whose own environment
    lacks SIMON7_GPU_PRIORITY, does not make the staging take wait on its own ticket."""
    if is_staging():
        os.environ[RELAY_ENV] = "staging"
