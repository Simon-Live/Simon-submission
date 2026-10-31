"""Job queue (SIMON7_GPU_WORKERS worker threads, default 2) with job records on disk under `<state>/jobs/<id>/` (app.md "Jobs")."""

from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import re
import shutil
import threading
import time
import traceback
import uuid
from typing import Any, Callable

from part7 import applog, config, keys

QUEUE_FULL_MESSAGE = "The app is busy. Try again in a few minutes."
FALLBACK_REASON = "the step failed unexpectedly"
_URL_RE = re.compile(r"\b[a-z][a-z0-9+.-]*://\S+", re.I)
_PATH_RE = re.compile(r"(?:[A-Za-z]:)?[~.\w-]*(?:/[^\s'\"):;,]*)+")
_HOST_RE = re.compile(r"\b(?:[a-z0-9-]+\.)+(?:com|org|net|io|dev|ai|app|local|internal|cloud)\b", re.I)
_TOKEN_RE = re.compile(r"\b[A-Za-z0-9_-]{32,}\b")
JOB_ID_RE = re.compile(r"^[0-9a-f]{12}$")


class QueueFullError(Exception):
    """More jobs wait than the queue limit allows (HTTP 503)."""


class JobFailed(Exception):
    """A job step failed in `stage` for a plain `reason` shown to the visitor."""

    def __init__(self, stage: str, reason: str) -> None:
        super().__init__(reason)
        self.stage = stage
        self.reason = reason


def sanitize_reason(reason: str) -> str:
    """Return `reason` without paths, host names, long tokens or key values; never empty."""
    text = keys.redact(str(reason or ""))
    text = _URL_RE.sub("", text)
    text = _PATH_RE.sub("", text)
    text = _HOST_RE.sub("", text)
    text = _TOKEN_RE.sub("", text)
    text = re.sub(r"\s+", " ", text).strip(" :;,.-")
    return text[:200] or FALLBACK_REASON


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class JobContext:
    """What a running job function may do: set the stage and note, and name its log files."""

    def __init__(self, queue: "JobQueue", job_id: str) -> None:
        self._queue = queue
        self.id = job_id
        self.dir = queue.job_dir(job_id)
        self.work = self.dir / "work"
        self.work.mkdir(parents=True, exist_ok=True)

    def set_stage(self, stage: str) -> None:
        self._queue.update(self.id, stage=stage)

    def add_note(self, note: str) -> None:
        self._queue.add_note(self.id, note)

    def set_fields(self, **fields: Any) -> None:
        self._queue.update(self.id, **fields)


JobFn = Callable[[JobContext], "dict[str, Any] | None"]


class JobQueue:
    """Runs queued jobs on `workers` threads; the GPU lock decides how many Part 2 calls overlap."""

    def __init__(
        self, state: Path | str, *, limit: int = config.QUEUE_LIMIT, start: bool = True, workers: int | None = None
    ) -> None:
        self.root = Path(state) / "jobs"
        self.root.mkdir(parents=True, exist_ok=True)
        self.limit = limit
        self._cond = threading.Condition()
        self._jobs: dict[str, dict[str, Any]] = {}
        self._waiting: deque[tuple[str, JobFn]] = deque()
        self._running: set[str] = set()
        self._closed = False
        self.cleanup()
        self._load()
        self.workers = max(1, workers if workers is not None else config.gpu_workers())
        self._threads = [
            threading.Thread(target=self._loop, name=f"part7-jobs-{n}", daemon=True) for n in range(self.workers)
        ]
        if start:
            for thread in self._threads:
                thread.start()

    def job_dir(self, job_id: str) -> Path:
        return self.root / job_id

    def cleanup(self, now: float | None = None) -> int:
        """Remove job folders not touched for 7 days; return how many."""
        cutoff = (now if now is not None else time.time()) - config.RETENTION_DAYS * 86400
        removed = 0
        for child in self.root.iterdir():
            record = child / "job.json"
            if child.is_dir() and JOB_ID_RE.match(child.name) and record.is_file():
                if record.stat().st_mtime < cutoff:
                    shutil.rmtree(child, ignore_errors=True)
                    removed += 1
        return removed

    def _load(self) -> None:
        for record in sorted(self.root.glob("*/job.json")):
            try:
                job = json.loads(record.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(job, dict) or not isinstance(job.get("id"), str):
                continue
            if job.get("status") in ("queued", "running"):
                self._mark_failed(job, job.get("stage") or "upload", "the server restarted")
                self._write(job)
            self._jobs[job["id"]] = job

    def _write(self, job: dict[str, Any]) -> None:
        directory = self.job_dir(job["id"])
        directory.mkdir(parents=True, exist_ok=True)
        tmp = directory / "job.json.tmp"
        tmp.write_text(json.dumps(job, indent=2), encoding="utf-8")
        tmp.replace(directory / "job.json")

    @staticmethod
    def _mark_failed(job: dict[str, Any], stage: str, reason: str) -> None:
        job.update(status="failed", stage=stage, reason=reason, error=f"failed:{stage}: {reason}")
        job["finished_at"] = _now()

    def has_room(self) -> bool:
        with self._cond:
            return self._active() < self.limit

    def _active(self) -> int:
        return len(self._waiting) + len(self._running)

    def submit(self, kind: str, fn: JobFn, *, entry_id: str | None = None, **extra: Any) -> dict[str, Any]:
        """Queue `fn`; raises `QueueFullError` at the limit. `extra` fields are kept in the record."""
        with self._cond:
            if self._closed or self._active() >= self.limit:
                raise QueueFullError(QUEUE_FULL_MESSAGE)
            job_id = uuid.uuid4().hex[:12]
            job: dict[str, Any] = {
                "id": job_id, "kind": kind, "status": "queued", "stage": None, "stages": [],
                "note": None, "entry_id": entry_id, "result": None, "reason": None, "error": None,
                "created_at": _now(), "started_at": None, "finished_at": None, **extra,
            }
            self._jobs[job_id] = job
            self._waiting.append((job_id, fn))
            self._write(job)
            self._cond.notify_all()
            return self._view(job)

    def update(self, job_id: str, **fields: Any) -> None:
        with self._cond:
            job = self._jobs[job_id]
            job.update(fields)
            stage = fields.get("stage")
            if stage and stage not in job["stages"]:
                job["stages"].append(stage)
            self._write(job)
            self._cond.notify_all()

    def add_note(self, job_id: str, note: str) -> None:
        with self._cond:
            job = self._jobs[job_id]
            job["note"] = f"{job['note']}; {note}" if job.get("note") else note
            self._write(job)

    def _view(self, job: dict[str, Any]) -> dict[str, Any]:
        view = {k: v for k, v in job.items() if not k.startswith("_")}
        position = None
        if job["status"] == "queued":
            ids = [jid for jid, _ in self._waiting]
            position = ids.index(job["id"]) + 1 if job["id"] in ids else None
        view["queue_position"] = position
        return view

    def get(self, job_id: str) -> dict[str, Any] | None:
        """Return the public record of `job_id`, or None."""
        with self._cond:
            job = self._jobs.get(job_id)
            return self._view(job) if job is not None else None

    def counts(self) -> dict[str, int]:
        with self._cond:
            return {"running": len(self._running), "waiting": len(self._waiting)}

    def wait(self, job_id: str, timeout: float = 30.0) -> dict[str, Any] | None:
        """Block until the job is `done` or `failed`, or `timeout` seconds pass."""
        deadline = time.monotonic() + timeout
        with self._cond:
            while True:
                job = self._jobs.get(job_id)
                if job is None or job["status"] in ("done", "failed"):
                    return self._view(job) if job else None
                left = deadline - time.monotonic()
                if left <= 0:
                    return self._view(job)
                self._cond.wait(left)

    def close(self, timeout: float = 2.0) -> None:
        with self._cond:
            self._closed = True
            self._cond.notify_all()
        for thread in self._threads:
            if thread.is_alive():
                thread.join(timeout=timeout)

    def _loop(self) -> None:
        while True:
            with self._cond:
                while not self._waiting and not self._closed:
                    self._cond.wait()
                if self._closed:
                    return
                job_id, fn = self._waiting.popleft()
                self._running.add(job_id)
                self.cleanup()
                self._jobs[job_id].update(status="running", started_at=_now())
                self._write(self._jobs[job_id])
                self._cond.notify_all()
            self._run_one(job_id, fn)
            with self._cond:
                self._running.discard(job_id)
                self._cond.notify_all()

    def _run_one(self, job_id: str, fn: JobFn) -> None:
        ctx = JobContext(self, job_id)
        try:
            outcome = fn(ctx)
            outcome = outcome if isinstance(outcome, dict) else {}
            fields: dict[str, Any] = {"status": "done", "finished_at": _now()}
            for key in ("result", "entry_id"):
                if outcome.get(key) is not None:
                    fields[key] = outcome[key]
            self.update(job_id, **fields)
        except JobFailed as exc:
            applog.log(f"failed at {exc.stage}: {applog.cause(exc)}", job_id, ctx.dir, logging.WARNING)
            self._fail(job_id, exc.stage, sanitize_reason(exc.reason))
        except Exception as exc:  # the traceback stays in the job log only
            (ctx.dir / "steps").mkdir(exist_ok=True)
            (ctx.dir / "steps" / "error.log").write_text(keys.redact(traceback.format_exc()), encoding="utf-8")
            with self._cond:
                stage = self._jobs[job_id].get("stage") or "upload"
            applog.log(f"crashed at {stage}: {applog.cause(exc)} (traceback in steps/error.log)", job_id, ctx.dir, logging.ERROR)
            self._fail(job_id, stage, FALLBACK_REASON)

    def _fail(self, job_id: str, stage: str, reason: str) -> None:
        with self._cond:
            job = self._jobs[job_id]
            self._mark_failed(job, stage, reason)
            self._write(job)
            self._cond.notify_all()
