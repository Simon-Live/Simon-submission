"""Part 7 supervises its Part 6 catalog child (docs/specs/self-healing.md "Part 6 supervisor").

A child that exited, or stopped answering for `HUNG_S`, is restarted through its own handle (never by name), with a
backoff that doubles up to `BACKOFF_MAX_S`. Each restart is a `SELFHEAL` line. The third restart without a stable
period raises one operator notice. A child that stays healthy for `STABLE_S` clears the count.
"""

from __future__ import annotations

import logging
from pathlib import Path
import threading
import time
from typing import Any, Callable

from part7 import applog, ops_notice, selfheal

INTERVAL_S = 15.0  # env SIMON7_P6_SUPERVISE_S
HUNG_S = 60.0  # a live child that has not answered for this long is restarted
BACKOFF_S = 2.0
BACKOFF_MAX_S = 60.0
STABLE_S = 300.0
NOTICE_AFTER = 3


class Part6Supervisor:
    def __init__(self, child: Any, state: Path | str, paused: Callable[[], bool] = lambda: False,
                 clock: Callable[[], float] = time.monotonic, interval: float | None = None) -> None:
        self.child, self.state, self.paused, self.clock = child, Path(state), paused, clock
        self.interval = interval if interval is not None else applog.env_float("SIMON7_P6_SUPERVISE_S", INTERVAL_S)
        self.restarts = 0
        self._last_restart = 0.0
        self._next_at = 0.0
        self._silent_since: float | None = None
        self._noticed = False
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> "Part6Supervisor":
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="part6-supervisor", daemon=True)
            self._thread.start()
        return self

    def stop(self, timeout: float = 20.0) -> None:
        """Called before the child is stopped at shutdown, so a stopping child is never restarted."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                self.tick()
            except Exception as exc:  # the supervisor outlives any one failed look at the child
                applog.log(f"part6 supervisor: tick failed: {applog.cause(exc)}", level=logging.WARNING)

    def tick(self) -> None:
        if self.paused():
            return
        now = self.clock()
        reason = self._fault(now)
        if reason is None:
            self._healthy(now)
        elif now >= self._next_at:
            self._restart(now, reason)

    def _fault(self, now: float) -> str | None:
        if not self.child.running():
            return f"exited with code {self.child.returncode()}"
        if self.child.health() is not None:
            self._silent_since = None
            return None
        self._silent_since = now if self._silent_since is None else self._silent_since
        silent = now - self._silent_since
        return f"no answer for {silent:.0f} s" if silent >= HUNG_S else None

    def _healthy(self, now: float) -> None:
        if self.restarts and self._silent_since is None and now - self._last_restart >= STABLE_S:
            selfheal.action("part6_stable", f"answering for {STABLE_S:.0f} s after {self.restarts} restart(s)")
            selfheal.record("part6_supervisor")
            self.restarts, self._next_at, self._noticed = 0, 0.0, False

    def _restart(self, now: float, reason: str) -> None:
        self.restarts += 1
        self._last_restart = now
        self._next_at = now + min(BACKOFF_MAX_S, BACKOFF_S * 2 ** (self.restarts - 1))
        self._silent_since = None
        applog.anomaly("part6_down", reason=reason, restarts=self.restarts)
        self.child.stop()
        self.child.start()
        answered = self.child.running() and self.child.health() is not None
        outcome = "answering" if answered else "still not answering"
        selfheal.action("part6_restart", f"restart {self.restarts}: {reason}; {outcome}")
        if self.restarts >= NOTICE_AFTER and not self._noticed:
            self._noticed = True
            ops_notice.send("The catalog keeps failing",
                            f"Part 6, the catalog service, has been restarted {self.restarts} times without staying up. "
                            f"Latest fault: {reason}. Latest restart: {outcome}. The app keeps retrying, at most once a "
                            f"minute. Run `prod.sh failures <id>` on the server for the last hour.", self.state)
