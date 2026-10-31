"""check-7 yields to live staging jobs (TICKET-089, check-7.md "Yielding to staging").

A queued or running job on the staging app is a live user; a check must not hold the shared GPU lock
against it. A job counts as live when its `job.json` says `queued` or `running` and the file was written
within `LIVE_WINDOW_S` (every stage change rewrites it, so an old file is a job that died with its server).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import time
from typing import Callable

from part7 import config

LIVE_WINDOW_S = 30 * 60
POLL_S = 15.0
DEFAULT_YIELD_MAX_S = 1800.0
ENV_IGNORE = "SIMON7_CHECK_IGNORE_STAGING"
ENV_YIELD_MAX = "SIMON7_CHECK_YIELD_MAX_S"


class Deferred(Exception):
    """Staging has live jobs and the check gave way (exit 2). The message is the reason."""


def reason(n: int) -> str:
    return f"staging has {n} live job(s)"


def live_jobs(state: Path | None = None, now: Callable[[], float] = time.time) -> int:
    """Count queued or running staging jobs updated within the last `LIVE_WINDOW_S`."""
    jobs = (Path(state) if state is not None else config.staging_dir()) / "jobs"
    if not jobs.is_dir():
        return 0
    live = 0
    for record in jobs.glob("*/job.json"):
        try:
            if now() - record.stat().st_mtime > LIVE_WINDOW_S:
                continue
            status = json.loads(record.read_text(encoding="utf-8")).get("status")
        except (OSError, ValueError, AttributeError):
            continue
        if status in ("queued", "running"):
            live += 1
    return live


def yield_max_s() -> float:
    try:
        return float(os.environ.get(ENV_YIELD_MAX, DEFAULT_YIELD_MAX_S))
    except ValueError:
        return DEFAULT_YIELD_MAX_S


class Gate:
    """`at_start()` defers at once; `before_stage()` waits for staging to go quiet, then defers."""

    def __init__(
        self,
        state: Path | None = None,
        max_wait_s: float | None = None,
        poll_s: float = POLL_S,
        count: Callable[[], int] | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        log: Callable[[str], None] = lambda msg: None,
    ) -> None:
        self.max_wait_s = yield_max_s() if max_wait_s is None else max_wait_s
        self.poll_s = poll_s
        self.count = count or (lambda: live_jobs(state))
        self.clock, self.sleep, self.log = clock, sleep, log
        self.ignore = os.environ.get(ENV_IGNORE) == "1"

    def at_start(self) -> None:
        n = 0 if self.ignore else self.count()
        if n:
            raise Deferred(reason(n))

    def before_stage(self, label: str = "") -> None:
        if self.ignore:
            return
        n = self.count()
        if not n:
            return
        deadline = self.clock() + self.max_wait_s
        self.log(f"check-7: yielding to staging before {label or 'the next stage'}: {reason(n)}")
        while n:
            if self.clock() >= deadline:
                raise Deferred(reason(n))
            self.sleep(self.poll_s)
            n = self.count()
