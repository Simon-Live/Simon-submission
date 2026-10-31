"""Circuit breaker for Part 1's network calls (TICKET-089, processor.md "Fallbacks").

Part 1 failed on every staging run of 2026-10-31 (timeouts at 90 s, cut streams), each wasting its budget and a
Meta call. Three consecutive transient failures within 30 minutes open the circuit for 20 minutes: Part 1 is skipped
and Part 3 picks the key frames. After the window one probe call runs (half-open): success closes the circuit,
failure re-opens it for twice the window, up to 2 hours. State is `<state>/part1_health.json`, read and written
under a file lock with an atomic replace. `SIMON7_PART1_BREAKER=off` disables it.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
from pathlib import Path
import time
from typing import Any, Callable, Iterator

from part7 import config

FAILURES_TO_OPEN = 3
FAILURE_WINDOW_S = 30 * 60
BASE_OPEN_S = 20 * 60
MAX_OPEN_S = 2 * 60 * 60
PROBE_STALE_S = 10 * 60  # a probe that never reported back no longer blocks the next one
ENV = "SIMON7_PART1_BREAKER"

_now: Callable[[], float] = time.time  # tests replace it


def enabled() -> bool:
    return os.environ.get(ENV, "").strip().lower() != "off"


def _path(state: Path | str | None) -> Path:
    return (Path(state) if state is not None else config.state_root()) / "part1_health.json"


@contextlib.contextmanager
def _locked(state: Path | str | None) -> Iterator[dict[str, Any]]:
    path = _path(state)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path) + ".lock", os.O_CREAT | os.O_RDWR, 0o666)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(doc, dict):
                doc = {}
        except (OSError, ValueError):
            doc = {}
        yield doc
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(doc, sort_keys=True), encoding="utf-8")
        tmp.replace(path)
    finally:
        os.close(fd)


def until_text(ts: float) -> str:
    return time.strftime("%H:%MZ", time.gmtime(ts))


def pause_note(ts: float) -> str:
    return f"key frames from Part 3, Part 1 paused after repeated network failures (until {until_text(ts)})"


def allow(state: Path | str | None = None) -> tuple[bool, float]:
    """`(True, 0)` to call Part 1 (closed, or this caller is the half-open probe); else `(False, open_until)`."""
    now = _now()
    with _locked(state) as doc:
        until = float(doc.get("open_until", 0.0))
        if until <= 0:
            return (True, 0.0)
        if now < until:
            return (False, until)
        probe = float(doc.get("probe_at", 0.0))
        if probe and now - probe < PROBE_STALE_S:
            return (False, now + PROBE_STALE_S - (now - probe))  # another call is probing
        doc["probe_at"] = now
        return (True, 0.0)


def record(outcome: str, state: Path | str | None = None) -> float:
    """Record `ok`, `transient` or `other`; return the new `open_until` (0 when the circuit is closed)."""
    now = _now()
    with _locked(state) as doc:
        probing = float(doc.get("open_until", 0.0)) > 0
        if outcome != "transient":
            doc.clear()  # a reply (good or bad) is not a network failure: the streak ends, the circuit closes
            return 0.0
        if probing:
            window = min(float(doc.get("window_s", BASE_OPEN_S)) * 2, MAX_OPEN_S)
            doc.update(window_s=window, open_until=now + window, probe_at=0.0, failures=[])
            return float(doc["open_until"])
        failures = [t for t in doc.get("failures", []) if now - float(t) <= FAILURE_WINDOW_S] + [now]
        doc["failures"] = failures
        if len(failures) >= FAILURES_TO_OPEN:
            doc.update(window_s=BASE_OPEN_S, open_until=now + BASE_OPEN_S, probe_at=0.0, failures=[])
            return float(doc["open_until"])
        return 0.0
