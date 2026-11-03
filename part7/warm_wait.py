"""A take's bounded wait for a warm Part 2 worker another take holds (TICKET-320, docs/specs/parts-harness.md "GPU").

When a warm worker for the take's stage exists (the people tracker for `track`, the pose worker for `run`) and the
take cannot get the GPU or that worker in time, it waits for the worker rather than a cold call, for at most
`SIMON7_WARM_WAIT_MAX_S` (default 300 s) counted from the start of its GPU wait. While it waits, the job record says
`another take` (TICKET-289) from the time the wait began, and one log line names the outcome:
`warm wait: got warm after <s> s` or `warm wait: gave up after <s> s, cold (<why>)`.
"""

from __future__ import annotations

from pathlib import Path
import time
from typing import Any, Callable, TypeVar

from part7 import applog, job_gpu

MAX_ENV = "SIMON7_WARM_WAIT_MAX_S"
MAX_DEFAULT_S = 300.0
POLL_S = 1.0  # how long one look at the worker waits before the bound and the worker are read again
T = TypeVar("T")


def max_s() -> float:
    """The longest a take waits for a warm worker, from the start of its GPU wait (`MAX_ENV`, default 300 s).
    A value that is not a positive number (0, negative, not a number) keeps the default: the wait cannot be turned
    off by accident, and a shorter one is any small positive value."""
    return applog.env_float(MAX_ENV, MAX_DEFAULT_S)


class WarmWait:
    """One take's wait: started when its GPU wait starts, shown on the record once it outlasts the usual wait."""

    def __init__(self, work: Path | str | None) -> None:
        self.work = work
        self.t0 = time.monotonic()
        self.since = time.time()  # epoch seconds, for the record's `wait.since` and `gpu_lock.acquire(wait_since=)`
        self.shown = False
        self.ended = False

    def waited(self) -> float:
        return time.monotonic() - self.t0

    def left(self) -> float:
        return max_s() - self.waited()

    def show(self) -> None:
        """The take goes on waiting for the warm worker: its record says another take, since its wait began."""
        self.shown = True
        job_gpu.waiting(self.work, job_gpu.ANOTHER_TAKE, self.since)

    def got(self) -> None:
        """The take leased the warm worker after the warm wait: logged once, the record's wait cleared."""
        self._end(f"got warm after {self.waited():.1f} s")

    def gave_up(self, why: str) -> None:
        """The bound passed (or the worker went away): logged once with `why`; the take runs a cold call."""
        self._end(f"gave up after {self.waited():.1f} s, cold ({why})")

    def end(self) -> None:
        """Clear the record's wait without a line (an error ended the wait); nothing when it never showed or ended."""
        if self.shown and not self.ended:
            job_gpu.admitted(self.work)
            self.ended = True

    def _end(self, outcome: str) -> None:
        if not self.shown or self.ended:
            return
        job_gpu.admitted(self.work)
        self.ended = True
        job = applog.job_id_of(self.work) if self.work is not None else None
        applog.log(f"warm wait: {outcome}", job, self.work)


def admission_kw(warm: WarmWait, base: dict[str, Any] | None) -> dict[str, Any]:
    """`base` admission arguments with what is left of `warm`'s bound and its wait start (one `wait.since`)."""
    return {**(base or {}), "timeout_s": max(0.0, warm.left()), "wait_since": warm.since}


def wait_for(warm: WarmWait, base: dict[str, Any] | None, holds: Callable[[], bool], ready: Callable[[float], bool],
             attempt: Callable[[dict[str, Any]], T | None]) -> T | None:
    """Wait for a warm worker another take holds, until `warm`'s bound or until `holds()` (the pool has a worker running
    or starting) is false. Each time `ready(s)` says nobody leases it, `attempt(admission_kw)` admits and leases once;
    its result ends the wait. The record says another take throughout, shown again after an admission's own watcher
    cleared it. A `ready` that returns early (a stopped pool) is slept out, so the loop never spins. None at the end."""
    try:
        warm.show()
        while warm.left() > 0 and holds():
            look, began = min(POLL_S, warm.left()), time.monotonic()
            if not ready(look):
                time.sleep(max(0.0, look - (time.monotonic() - began)))
                continue
            got = attempt(admission_kw(warm, base))
            if got is not None:
                return got
            warm.show()
    except TimeoutError:
        pass
    except BaseException:
        warm.end()
        raise
    return None
