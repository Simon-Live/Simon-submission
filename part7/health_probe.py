"""Part 6 probe for `api/health` that survives a slow child (TICKET-188).

A single 2 s probe that misses under host load must not turn `api/health` into a 503, because the staging
watchdog restarts the app on 503. The last good probe is kept; a miss younger than `SIMON7_HEALTH_PART6_STALE_S`
(default 120) answers ok with `stale_s`. Only a child unreachable for longer than that is reported down.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable

from part7 import applog, config, selfheal

WARN_EVERY_S = 30.0


class Part6Probe:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._good_at: float | None = None
        self._entries = 0
        self._warned_at: float | None = None

    def check(self, child: Any) -> tuple[bool, dict[str, Any]]:
        """Probe `child`; return (ok, the `part6` field of the health document)."""
        if child.health() is not None:
            entries = len(child.list_entries())
            with self._lock:
                self._good_at, self._entries = self._clock(), entries
            selfheal.record("health_stale_cache")
            return True, {"ok": True, "entries": entries}
        now = self._clock()
        with self._lock:
            good_at, entries = self._good_at, self._entries
            age = None if good_at is None else now - good_at
            if age is None or age > config.health_part6_stale_s():
                return False, {"ok": False, "entries": 0}
            warn = self._warned_at is None or now - self._warned_at >= WARN_EVERY_S
            if warn:
                self._warned_at = now
        if warn:
            applog.log(f"health: Part 6 probe missed; answering from the last good probe {age:.0f}s old", level=logging.WARNING)
        selfheal.record("health_stale_cache", f"Part 6 probe missed; answered from the last good probe {age:.0f}s old")
        return True, {"ok": True, "entries": entries, "stale_s": round(age)}
