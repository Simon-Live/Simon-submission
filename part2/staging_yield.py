"""Non-staging Part 2 GPU work waits while a staging take waits for the GPU lock.

Spec: docs/specs/staging-yield.md. The wait runs once, at the start of a command, before its first GPU acquire.

    staging_yield.gate(command)       # called by part2.cli.main; returns at once for a staging take or no waiter
    staging_yield.mark_staging_for_worker()   # a staging client tells the warm worker the request is a staging take

Part 7 writes a ticket file `<pid>-<thread>-<ns>` into `<lock>.waiters/` while a staging waiter waits; a ticket counts
while its pid is alive. A ticket of this process or any ancestor is our caller's own and is ignored. This module only reads that folder (it never removes a ticket) and never touches the lock.
"""
from __future__ import annotations

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


def lock_path() -> Path:
    from part2 import trackers

    return Path(os.environ.get(trackers.GPU_LOCK_ENV) or trackers.GPU_LOCK_DEFAULT).expanduser()


def waiters_dir(lock: Path | str | None = None) -> Path:
    lock = Path(lock) if lock is not None else lock_path()
    return lock.parent / (lock.name + WAITERS_SUFFIX)


def is_staging(env=None) -> bool:
    env = os.environ if env is None else env
    return any(env.get(k, "").strip().lower() in STAGING for k in (PRIORITY_ENV, RELAY_ENV))


def _alive(pid: int) -> bool:
    return Path(f"/proc/{pid}").exists()


def _ppid(pid: int) -> int:
    """Parent pid from /proc/<pid>/stat (field 4, after the parenthesised name); 0 when unreadable."""
    try:
        tail = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        return int(tail[1])
    except (OSError, IndexError, ValueError):
        return 0


def ancestors(pid: int | None = None) -> set[int]:
    """This process, its parent and every ancestor up to pid 1. A ticket of one of them is our own caller's: Part 7's
    server, its subprocesses and the warm workers are all children of one server, so we never wait on them."""
    pid = os.getpid() if pid is None else pid
    seen: set[int] = set()
    while pid > 0 and pid not in seen:
        seen.add(pid)
        pid = _ppid(pid)
    return seen


def staging_waiting(lock: Path | str | None = None) -> int:
    """How many tickets beside the lock belong to a live pid that is not us or one of our ancestors; 0 when the
    folder is absent."""
    try:
        names = [p.name for p in waiters_dir(lock).iterdir()]
    except OSError:
        return 0
    own = ancestors()
    pids = (n.split("-", 1)[0] for n in names)
    return sum(1 for p in pids if p.isdigit() and int(p) not in own and _alive(int(p)))


def wait_for_staging(lock: Path | str | None = None, poll_s: float = POLL_S, sleep=time.sleep, log=None,
                     env=None) -> int:
    """Block while a live staging ticket exists, unless this process is a staging take. Logs one line on the first
    wait. Returns the number of polls that waited (0 when it did not wait)."""
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


def gate(command: str) -> None:
    """The one call of part2.cli.main for a command that can take the GPU lock."""
    if command in GPU_COMMANDS:
        wait_for_staging()


def mark_staging_for_worker() -> None:
    """A staging client forwarding to the warm worker sets PART2_GPU_PRIORITY so the worker, whose own environment
    lacks SIMON7_GPU_PRIORITY, does not make the staging take wait on its own ticket."""
    if is_staging():
        os.environ[RELAY_ENV] = "staging"
