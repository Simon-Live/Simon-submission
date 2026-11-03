"""Judge-URL warm-up of Part 2's warm worker (TICKET-260, docs/specs/p2-warmup.md).

The first `part2 run` after a worker starts pays one-off costs the loaded model does not remove. When the judge page
loads (`SIMON7_DEFAULT_PROFILE=submission`, or `?profile=submission`) and nothing else needs the GPU, one 1-frame run
through the worker pays them before the judge's first take. It never starts while a take is queued or running, while
the GPU lock is held, or while the worker is busy or starting, and it runs once per worker life (the worker's pid).
The result is one log line, `p2_warmup seconds=<s> exit=<n>`.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any
from urllib.parse import parse_qs

from part7 import applog, config, gpu_lock, judge_view, p2_worker
from part7.parts import p2_pose

_LOCK = threading.Lock()
_warmed: set[int] = set()  # worker pids already primed (or tried) in this process
_running = False
ADMIT_TIMEOUT_S = 5.0  # the GPU turn is not waited for: a busy host skips the warm-up


def wanted(query: str) -> bool:
    """True when the page asked for the judge profile: `?profile=submission`, or the server default without a `profile`."""
    asked = (parse_qs(query).get("profile") or [""])[0].strip().lower()
    return asked == "submission" or (asked == "" and judge_view.default_profile() == "submission")


def skip_reason(app: Any) -> str | None:
    """Why no warm-up should start now, or None when one may."""
    if app.backend != "gpu" or not p2_pose.warm_worker_enabled():
        return "no warm worker"
    if p2_worker.state() != "idle":
        return f"worker {p2_worker.state()}"
    counts = app.queue.counts()
    if counts["running"] or counts["waiting"]:
        return "a take is queued or running"
    try:
        holder = gpu_lock.lock_holder_pid(config.gpu_lock_path())
    except OSError:
        holder = None
    if holder is not None:
        return f"GPU lock held by pid {holder}"
    return None


def maybe_start(app: Any, query: str = "") -> str:
    """Start the warm-up in the background when the page is the judge page and it may; returns what was decided."""
    global _running
    if not wanted(query):
        return "not the judge page"
    why = skip_reason(app)
    life = p2_worker.worker_life()
    if why is None and life is None:
        why = "no worker process"
    with _LOCK:
        if why is None and (_running or life in _warmed):
            why = "already warmed or running"
        if why is not None:
            return why
        _running = True
        _warmed.add(life)
    threading.Thread(target=_run, args=(app,), name="p2-warmup", daemon=True).start()
    return "started"


def _busy(app: Any) -> bool:
    counts = app.queue.counts()
    return bool(counts["running"] or counts["waiting"])


def _run(app: Any) -> None:
    global _running
    t0 = time.monotonic()
    code: int | str = "skipped"
    try:
        with gpu_lock.acquire(min_free_mib=0, concurrent=True, hold_flock=False, timeout_s=ADMIT_TIMEOUT_S):
            if _busy(app):
                return  # a take arrived while the turn was taken: it gets the worker
            with p2_worker.lease() as sock:
                if sock is not None:
                    step, why = p2_pose.warmup_step(app.state, app.lock, sock)
                    code = step["exit"] if step is not None else why
    except TimeoutError:
        code = "gpu busy"
    except Exception as exc:  # a warm-up never breaks the page
        code = f"error {applog.cause(exc)}"
    finally:
        with _LOCK:
            _running = False
        applog.log(f"p2_warmup seconds={time.monotonic() - t0:.1f} exit={code}",
                   level=logging.INFO if code == 0 else logging.WARNING)


def reset() -> None:
    """Forget what was warmed (tests)."""
    global _running
    with _LOCK:
        _warmed.clear()
        _running = False
