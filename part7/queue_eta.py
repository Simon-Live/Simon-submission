"""A rough wait estimate for queued and running jobs (app.md "Wait estimate", TICKET-288).

The samples are the run times (`finished_at - started_at`) of recent `done` jobs of each kind, read from their
`job.json` records on disk. `EtaCache.refresh` reads them once at start and again when a job ends; a request only reads
the cached numbers. With fewer than `MIN_SAMPLES` recent samples of a kind that is needed, there is no estimate:
the answer is None, never a made-up number.
"""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import re
import statistics
import threading
import time
from typing import Callable, Iterable

LAST_N = 10  # the newest done jobs of a kind that count
WINDOW_S = 7 * 86400  # samples older than this are ignored
MIN_SAMPLES = 3  # fewer recent samples of a kind: no estimate
MIN_LEFT_S = 30.0  # a running job past its median still has this much left, never zero or less
_JOB_DIR_RE = re.compile(r"^[0-9a-f]{12}$")

Sample = tuple[float, float]  # (finished at, epoch seconds; run seconds)
Median = Callable[[str], "tuple[float, int] | None"]


def epoch(stamp: object) -> float | None:
    """Epoch seconds of a `2026-11-02T10:00:00Z` stamp, else None."""
    if not isinstance(stamp, str) or not stamp:
        return None
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def sample_of(job: object) -> tuple[str, Sample] | None:
    """`(kind, (finished, seconds))` of a done job record with both times, else None."""
    if not isinstance(job, dict) or job.get("status") != "done" or not isinstance(job.get("kind"), str):
        return None
    started, finished = epoch(job.get("started_at")), epoch(job.get("finished_at"))
    if started is None or finished is None or finished <= started:
        return None
    return job["kind"], (finished, finished - started)


def read_samples(root: Path, last_n: int = LAST_N) -> dict[str, list[Sample]]:
    """The newest `last_n` samples of each kind under `root/<id>/job.json`, newest first."""
    found: dict[str, list[Sample]] = {}
    try:
        children = list(root.iterdir())
    except OSError:
        return found
    for child in children:
        if not _JOB_DIR_RE.match(child.name):
            continue
        try:
            job = json.loads((child / "job.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        got = sample_of(job)
        if got is not None:
            found.setdefault(got[0], []).append(got[1])
    return {kind: sorted(rows, reverse=True)[:last_n] for kind, rows in found.items()}


def median_of(samples: Iterable[Sample], now: float, window_s: float = WINDOW_S,
              min_samples: int = MIN_SAMPLES) -> tuple[float, int] | None:
    """`(median seconds, count)` of the samples that finished within `window_s` of `now`; None below `min_samples`."""
    recent = [seconds for finished, seconds in samples if now - finished <= window_s]
    if len(recent) < min_samples:
        return None
    return statistics.median(recent), len(recent)


def left_of(median_s: float, elapsed_s: float) -> float:
    """Seconds a running job has left: its median minus what it has run, at least `MIN_LEFT_S`."""
    return max(MIN_LEFT_S, median_s - max(0.0, elapsed_s))


def for_running(kind: str, elapsed_s: float, median: Median) -> tuple[float, dict] | None:
    """`(eta_s, eta_basis)` of a running job, or None without enough samples of its kind."""
    got = median(kind)
    if got is None:
        return None
    m, n = got
    return round(left_of(m, elapsed_s)), {"kind": kind, "samples": n, "median_s": round(m), "elapsed_s": round(elapsed_s),
                                          "late": elapsed_s >= m}


def for_queued(kind: str, ahead: list[str], running: list[tuple[str, float]], workers: int,
               median: Median) -> tuple[float, dict] | None:
    """`(eta_s, eta_basis)` of a queued job: the work before it shared by the workers, plus its own median run.

    `ahead` are the kinds queued before it, `running` the `(kind, elapsed)` of the running jobs. Any kind with too few
    samples makes the whole estimate None.
    """
    own = median(kind)
    if own is None:
        return None
    work = 0.0
    for other in ahead:
        got = median(other)
        if got is None:
            return None
        work += got[0]
    for other, elapsed in running:
        got = median(other)
        if got is None:
            return None
        work += left_of(got[0], elapsed)
    workers = max(1, workers)
    return round(work / workers + own[0]), {"kind": kind, "samples": own[1], "median_s": round(own[0]),
                                           "ahead": len(ahead), "running": len(running), "workers": workers,
                                           "late": False}


class EtaCache:
    """The cached samples per kind; `refresh` reads the disk, `median` never does."""

    def __init__(self, root: Path, clock: Callable[[], float] = time.time) -> None:
        self.root = Path(root)
        self.clock = clock
        self._samples: dict[str, list[Sample]] = {}
        self._lock = threading.Lock()

    def refresh(self) -> None:
        found = read_samples(self.root)
        with self._lock:
            self._samples = found

    def median(self, kind: str) -> tuple[float, int] | None:
        with self._lock:
            rows = self._samples.get(kind, [])
        return median_of(rows, self.clock())
