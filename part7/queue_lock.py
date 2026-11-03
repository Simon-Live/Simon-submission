"""The job queue's lock: one server runs the jobs of a state folder (TICKET-240, staging.md "Restart with no gap").

`QueueLock(state, after_pid)` holds `flock` on `<state>/jobs.lock`. `try_take()` never blocks: it fails while another
process holds the lock, and while the process `after_pid` names still runs (pid plus its start time, so a reused pid
does not count). A restart names the old server there, so an old build that predates the lock is waited for as well.
The kernel drops the lock when the holder exits, crash included.
"""

from __future__ import annotations

import fcntl
import os
from pathlib import Path

LOCK_NAME = "jobs.lock"


def start_time(pid: int) -> str | None:
    """Field 22 of `/proc/<pid>/stat` (when the process started), or None when there is no such process."""
    try:
        text = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return None
    fields = text[text.rfind(")") + 2:].split()
    return fields[19] if len(fields) > 19 else None


class QueueLock:
    """`flock` on `<state>/jobs.lock`, taken without blocking once `after_pid` has exited."""

    def __init__(self, state: Path | str, after_pid: int | None = None) -> None:
        self.path = Path(state) / LOCK_NAME
        self._fd: int | None = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        started = start_time(after_pid) if after_pid else None
        self._after = (after_pid, started) if after_pid and started else None
        self.held = False

    def waits_for_pid(self) -> bool:
        """True while the process named by `after_pid` still runs."""
        return self._after is not None and start_time(self._after[0]) == self._after[1]

    def try_take(self) -> bool:
        """Take the lock now if nobody holds it and `after_pid` has exited; True when this object holds it."""
        if self.held:
            return True
        if self._fd is None or self.waits_for_pid():
            return False
        try:
            fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return False
        self._after, self.held = None, True
        return True

    def release(self) -> None:
        """Close the file: the lock is free for the next server. Idempotent."""
        if self._fd is not None:
            os.close(self._fd)
        self._fd, self.held = None, False
