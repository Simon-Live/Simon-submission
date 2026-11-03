"""Keep a staging take's waiter ticket until the admitted Part 2 child holds the flock (TICKET-317).

`gpu_lock.acquire(hold_flock=False)` admits a call and drops the flock, so its Part 2 child can take it. Part 2's own
yield (a non-staging process steps back while a live staging ticket exists) must see a ticket for that whole gap, or a
low-priority process retakes the flock before the child reaches it. The ticket is therefore dropped here, not at
admission: when the flock holder is the call's process or one it started, when the grace runs out, or when the call ends.
"""

from __future__ import annotations

import contextlib
import threading
import time
from pathlib import Path
from typing import Callable

from part7 import applog

HANDOFF_GRACE_S = 20.0  # a child that has not taken the flock by then is not coming for it
HANDOFF_POLL_S = 0.05


class Handoff:
    """A daemon thread that drops `ticket` once `holder_ok()` is true or the grace passes; `stop()` drops it at once."""

    def __init__(self, ticket: Path, holder_ok: Callable[[], bool], job_dir: Path | str | None = None,
                 grace_s: float | None = None, poll_s: float | None = None) -> None:
        self.ticket, self.holder_ok, self.job_dir = ticket, holder_ok, job_dir
        self.grace_s = HANDOFF_GRACE_S if grace_s is None else grace_s
        self.poll_s = HANDOFF_POLL_S if poll_s is None else poll_s
        self.done = threading.Event()
        self.thread = threading.Thread(target=self._run, name="gpu-handoff", daemon=True)
        self.thread.start()

    def _drop(self) -> None:
        with contextlib.suppress(OSError):
            self.ticket.unlink()

    def _run(self) -> None:
        end = time.monotonic() + self.grace_s
        try:
            while not self.done.is_set():
                if self.holder_ok():
                    return
                if time.monotonic() >= end:
                    job = applog.job_id_of(self.job_dir) if self.job_dir is not None else None
                    applog.log(f"gpu handoff: no Part 2 process took the lock in {self.grace_s:g} s; "
                               "staging ticket dropped", job, self.job_dir)
                    return
                self.done.wait(self.poll_s)
        except BaseException:  # noqa: BLE001 - the ticket must go on any failure, then the error is not hidden
            self._drop()
            raise
        finally:
            self._drop()

    def stop(self) -> None:
        self.done.set()
        self.thread.join(5.0)
        self._drop()
