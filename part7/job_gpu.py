"""What a running job shows about the GPU on its record (TICKET-289, docs/specs/app.md "GPU wait on the job").

The job queue registers each job's folder while the job runs (`track`), with the queue's update path as the sink.
GPU code that knows only a folder inside the job (`gpu_lock.acquire(job_dir=...)`, `p2_pose`) reports through the
functions below; a folder no running job owns (a check, a test, a lane script) reports nothing.

Fields written on the job record, never a pid or a path:

- `wait`: `{"since": <UTC ISO time>, "reason": "another take" | "other GPU work" | "gpu queue"}` while the job waits in GPU
  admission, else null. A take that goes on waiting for the warm worker of its stage (TICKET-320, `warm_wait`) keeps
  the start of its first wait, and says `another take` while it waits for that worker outside admission.
- `worker`: `"warm"` once the 3D step leased the warm Part 2 worker, `"cold"` when it ran the slower per-call path
  although a warm worker exists; `worker_reason` names why for cold: `busy`, `restarting` or `failed`.
"""

from __future__ import annotations

from pathlib import Path
import threading
import time
from typing import Any, Callable

ANOTHER_TAKE = "another take"
OTHER_WORK = "other GPU work"
GPU_QUEUE = "gpu queue"  # serverless: Modal has not started the call yet (serverless-compute.md AC-SC7)
WARM = "warm"
COLD = "cold"
COLD_BUSY = "busy"  # another take holds the warm worker
COLD_RESTARTING = "restarting"  # the worker is starting, down, unhealthy or restarting for a new pin
COLD_FAILED = "failed"  # the worker dropped the call; it repeats per-call

_LOCK = threading.Lock()
_SINKS: dict[Path, Callable[..., None]] = {}


def track(job_dir: Path | str, update: Callable[..., None]) -> None:
    """Route reports for any folder inside `job_dir` to `update(**fields)` until `untrack`."""
    with _LOCK:
        _SINKS[Path(job_dir).resolve()] = update


def untrack(job_dir: Path | str) -> None:
    with _LOCK:
        _SINKS.pop(Path(job_dir).resolve(), None)


def _sink(folder: Path | str | None) -> Callable[..., None] | None:
    if folder is None:
        return None
    p = Path(folder).resolve()
    with _LOCK:
        for candidate in (p, *p.parents):
            if candidate in _SINKS:
                return _SINKS[candidate]
    return None


def tracked(folder: Path | str | None) -> bool:
    """True when `folder` is inside a running job's folder."""
    return _sink(folder) is not None


def _send(folder: Path | str | None, **fields: Any) -> None:
    sink = _sink(folder)
    if sink is not None:
        sink(**fields)


def iso(epoch: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch))


def waiting(folder: Path | str | None, reason: str, since: float) -> None:
    """The job waits in GPU admission since `since` (epoch seconds) for `reason` (ANOTHER_TAKE or OTHER_WORK)."""
    _send(folder, wait={"since": iso(since), "reason": reason})


def admitted(folder: Path | str | None) -> None:
    """The admission wait is over (admitted or given up): the wait is cleared."""
    _send(folder, wait=None)


def worker(folder: Path | str | None, path: str, reason: str | None = None) -> None:
    """The 3D step runs on the warm worker (`WARM`) or the per-call path (`COLD`, with `reason`)."""
    _send(folder, worker=path, worker_reason=reason if path == COLD else None)
