"""A heartbeat line every minute, and the anomalies a watcher needs from it (TICKET-091, observability.md).

`Heartbeat(queue, state)` runs one daemon thread started by `serve`: it logs `heartbeat queued=N running=N
oldest_running_s=.. load1=.. gpu_free_mib=.. disk_free_gb=..` (`na` for a reading it cannot take; `p2_worker` is `off`, `starting`, `idle`, `busy` or `down`, TICKET-099) and adds
`ANOMALY queue_backlog` (more than `BACKLOG_QUEUED` jobs waiting for over `BACKLOG_S`), `ANOMALY heartbeat_stale`
(a job running longer than `STALE_RUNNING_S`) and `ANOMALY disk_low`. It reads counters and never touches a request.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
import shutil
import threading
import time
from typing import Any, Callable

from part7 import applog, gpu_lock, p2_worker

INTERVAL_S = 60.0  # env SIMON7_HEARTBEAT_S
BACKLOG_QUEUED = 2  # env SIMON7_BACKLOG_QUEUED: more waiting jobs than this ...
BACKLOG_S = 120.0  # env SIMON7_BACKLOG_S: ... for longer than this is a backlog
STALE_RUNNING_S = 1800.0  # env SIMON7_STALE_RUNNING_S
DISK_LOW_GB = 2.0  # env SIMON7_DISK_LOW_GB


def _num(value: float | int | None, digits: int = 1) -> str:
    return "na" if value is None else f"{value:.{digits}f}"


def _tracker_note() -> str:
    """` p2_tracker=<state>` while the warm SAM 3.1 tracker pool runs (TICKET-117), else nothing."""
    state = p2_worker.track_state()
    return "" if state == "off" else f" p2_tracker={state}"


class Heartbeat:
    """Logs the server's vital signs every `interval` seconds until `stop()`; `tick()` is one beat."""

    def __init__(self, queue: Any, state: Path | str, *, interval: float | None = None,
                 clock: Callable[[], float] = time.monotonic,
                 gpu_free: Callable[[], int | None] = gpu_lock.free_gpu_memory_mib) -> None:
        self.queue, self.state, self.clock, self.gpu_free = queue, Path(state), clock, gpu_free
        self.interval = interval if interval is not None else applog.env_float("SIMON7_HEARTBEAT_S", INTERVAL_S)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._backlog_since: float | None = None

    def start(self) -> "Heartbeat":
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="part7-heartbeat", daemon=True)
            self._thread.start()
        return self

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                self.tick()
            except Exception as exc:  # a failing reading must never stop the beat
                applog.log(f"heartbeat failed: {applog.cause(exc)}", level=logging.ERROR)

    def _readings(self) -> dict[str, Any]:
        snap = self.queue.snapshot()
        try:
            load1: float | None = os.getloadavg()[0]
        except OSError:
            load1 = None
        try:
            disk: float | None = shutil.disk_usage(self.state).free / 1e9
        except OSError:
            disk = None
        try:
            gpu = self.gpu_free()
        except Exception:
            gpu = None
        return {**snap, "load1": load1, "gpu_free_mib": gpu, "disk_free_gb": disk}

    def tick(self) -> dict[str, Any]:
        """Log one heartbeat and its anomalies; return the readings."""
        r = self._readings()
        applog.log(f"heartbeat queued={r['queued']} running={r['running']} oldest_running_s={_num(r['oldest_running_s'])} "
                   f"load1={_num(r['load1'], 2)} gpu_free_mib={_num(r['gpu_free_mib'], 0)} "
                   f"disk_free_gb={_num(r['disk_free_gb'])} p2_worker={p2_worker.state()}{_tracker_note()}")
        now = self.clock()
        limit = applog.env_float("SIMON7_BACKLOG_QUEUED", BACKLOG_QUEUED)
        if r["queued"] > limit:
            self._backlog_since = self._backlog_since if self._backlog_since is not None else now
            waited = now - self._backlog_since
            if waited > applog.env_float("SIMON7_BACKLOG_S", BACKLOG_S):
                applog.anomaly("queue_backlog", queued=r["queued"], running=r["running"], seconds=waited,
                               gpu_free_mib=r["gpu_free_mib"], oldest_running_s=r["oldest_running_s"])
        else:
            self._backlog_since = None
        oldest = r["oldest_running_s"]
        if oldest is not None and oldest > applog.env_float("SIMON7_STALE_RUNNING_S", STALE_RUNNING_S):
            applog.anomaly("heartbeat_stale", "a job has been running far longer than any stage should take",
                           running=r["running"], oldest_running_s=oldest, load1=r["load1"], gpu_free_mib=r["gpu_free_mib"])
        if r["disk_free_gb"] is not None and r["disk_free_gb"] < applog.env_float("SIMON7_DISK_LOW_GB", DISK_LOW_GB):
            applog.anomaly("disk_low", disk_free_gb=r["disk_free_gb"])
        return r
