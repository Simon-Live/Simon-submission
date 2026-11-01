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

from part7 import applog, config, history_store, job_lookup, keys

QUEUE_FULL_MESSAGE = "The app is busy. Try again in a few minutes."
FALLBACK_REASON = "the step failed unexpectedly"
_URL_RE = re.compile(r"\b[a-z][a-z0-9+.-]*://\S+", re.I)
_PATH_RE = re.compile(r"(?:[A-Za-z]:)?[~.\w-]*(?:/[^\s'\"):;,]*)+")
_HOST_RE = re.compile(r"\b(?:[a-z0-9-]+\.)+(?:com|org|net|io|dev|ai|app|local|internal|cloud)\b", re.I)
_TOKEN_RE = re.compile(r"\b[A-Za-z0-9_-]{32,}\b")
JOB_ID_RE = re.compile(r"^[0-9a-f]{12}$")
UPLOAD_ID_RE = re.compile(r"^[0-9a-f]{16}$")
PID_RE = re.compile(r"^[0-9A-Za-z_-]{1,40}$")  # a person of a group job; shared by result_media and challenge_routes


class QueueFullError(Exception):
    """More jobs wait than the queue limit allows (HTTP 503)."""


class DrainingError(Exception):
    """The server is restarting and takes no new job (HTTP 503 with Retry-After)."""


DRAINING_MESSAGE = "Restarting shortly, try again in a minute."
DRAIN_RETRY_AFTER_S = 60
DRAIN_CUT_REASON = "the app restarted before this take finished; record it again"


class JobFailed(Exception):
    """A job step failed in `stage` for a plain `reason` shown to the visitor."""

    def __init__(self, stage: str, reason: str, cause: str = "failed") -> None:
        super().__init__(reason)
        self.stage = stage
        self.reason = reason
        self.cause = cause  # the class of the failure for `ANOMALY job_failed` (failcause.py)


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


SLOW_JOB_S = 900.0  # a job longer than this logs `ANOMALY slow_job` (env SIMON7_SLOW_JOB_S)
SUMMARY_FIELDS = (("mode", "mode"), ("section", "section"), ("challenge_id", "challenge"))


def summary_line(job_id: str, job: dict[str, Any], status: str, total: float, spent: dict[str, float],
                 facts: dict[str, Any]) -> str:
    """`job <id> summary: kind=.. status=ok|failed total=..s <stage>=..s[(gpu_wait=..s)] part1=.. mode=.. ...`."""
    parts = [f"kind={job.get('kind')}", f"status={status}", f"total={total:.1f}s"]
    for name, seconds in spent.items():
        if name:
            waited = facts.get(f"gpu_wait.{name}")
            parts.append(f"{name}={seconds:.1f}s" + (f"(gpu_wait={waited:.1f}s)" if waited else ""))
    if facts.get("part1"):
        parts.append(f"part1={facts['part1']}")
    for key, label in SUMMARY_FIELDS:
        if job.get(key):
            sec = job[key]
            if isinstance(sec, dict) and "index" in sec:  # a section reads as `index/count`
                value = f"{sec['index']}/{sec.get('count')}"
            else:
                value = sec if isinstance(sec, str) else json.dumps(sec, separators=(",", ":"))
            parts.append(f"{label}={value}")
    return f"job {job_id} summary: " + " ".join(parts)


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
        self._clock = time.monotonic  # tests replace it
        self._marks: dict[str, tuple[str, float]] = {}  # job -> (stage, when it began), for the summary line
        self._durations: dict[str, dict[str, float]] = {}  # job -> seconds spent per stage
        self._started: dict[str, float] = {}  # running job -> when it began
        self._closed = False
        self._draining = False
        self._resumable: list[str] = []  # queued jobs from before a restart that carry a `_resume` spec
        self.on_cleanup: Callable[[], None] | None = None  # the server sweeps old uploads with each job sweep
        self._stop_sweeper = threading.Event()
        self.cleanup()  # the startup sweep; later sweeps run in their own thread, never on the job-start path
        self._load()
        job_lookup.register(self.root, self.trainer_for)
        self.workers = max(1, workers if workers is not None else config.gpu_workers())
        self._threads = [
            threading.Thread(target=self._loop, name=f"part7-jobs-{n}", daemon=True) for n in range(self.workers)
        ]
        self._sweeper = threading.Thread(target=self._sweep_loop, name="part7-jobs-sweep", daemon=True)
        if start:
            for thread in self._threads:
                thread.start()
            self._sweeper.start()

    def job_dir(self, job_id: str) -> Path:
        return self.root / job_id

    def cleanup(self, now: float | None = None) -> int:
        """Remove job folders not touched for 7 days (and their entries in memory); return how many."""
        cutoff = (now if now is not None else time.time()) - config.RETENTION_DAYS * 86400
        removed = 0
        for child in self.root.iterdir():
            record = child / "job.json"
            if child.is_dir() and JOB_ID_RE.match(child.name) and record.is_file():
                if record.stat().st_mtime < cutoff:
                    with self._cond:
                        job = self._jobs.get(child.name)
                        if job is not None and job["status"] in ("queued", "running"):
                            continue
                        self._jobs.pop(child.name, None)  # finished_refs must not count a job whose folder is gone
                        self._marks.pop(child.name, None)
                        self._durations.pop(child.name, None)
                    shutil.rmtree(child, ignore_errors=True)
                    removed += 1
        if self.on_cleanup is not None:
            self.on_cleanup()
        return removed

    def trainer_for(self, entry_id: str) -> str | None:
        """The id of the newest done trainer job that made catalog entry `entry_id`, from the records in memory."""
        with self._cond:
            found = [
                (str(j.get("finished_at") or ""), jid) for jid, j in self._jobs.items()
                if j.get("kind") == "trainer" and j.get("status") == "done"
                and (j.get("entry_id") or (j.get("result") or {}).get("entry_id")) == entry_id
            ]
        return max(found)[1] if found else None

    def _sweep_loop(self) -> None:
        """Retention sweep every `config.cleanup_every_s()` seconds, off the workers and the request threads."""
        while not self._stop_sweeper.wait(config.cleanup_every_s()):
            try:
                self.cleanup()
            except Exception as exc:  # a failed sweep must not end the thread; the next one retries
                applog.log(f"retention sweep failed: {applog.cause(exc)}", level=logging.WARNING)

    def _load(self) -> None:
        for record in sorted(self.root.glob("*/job.json")):
            try:
                job = json.loads(record.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(job, dict) or not isinstance(job.get("id"), str):
                continue
            if job.get("status") == "queued" and isinstance(job.get("_resume"), dict):
                applog.log("was queued when the server stopped; stays queued and runs after the restart",
                           job["id"], record.parent)
                self._resumable.append(job["id"])
            elif job.get("status") in ("queued", "running"):
                applog.log(f"was {job.get('status')} at {job.get('stage') or 'upload'} when the server stopped; "
                           "marked failed", job["id"], record.parent, logging.WARNING)
                self._mark_failed(job, job.get("stage") or "upload", "the server restarted")
                self._write(job)
            self._jobs[job["id"]] = job

    def resume(self, rebuild: Callable[[dict[str, Any]], "JobFn | None"]) -> int:
        """Queue the jobs that were waiting at the last stop; `rebuild(record)` makes each one's function.

        A job `rebuild` cannot rebuild (None, or an exception) is marked failed. Returns how many were queued.
        """
        queued = 0
        with self._cond:
            ids, self._resumable = self._resumable, []
            for job_id in ids:
                job = self._jobs[job_id]
                try:
                    fn = rebuild(dict(job))
                except Exception as exc:  # a record that no longer rebuilds must not stop the others
                    applog.log(f"could not resume: {applog.cause(exc)}", job_id, self.job_dir(job_id), logging.WARNING)
                    fn = None
                if fn is None:
                    self._mark_failed(job, job.get("stage") or "upload", "the server restarted")
                    self._write(job)
                    continue
                self._waiting.append((job_id, fn))
                queued += 1
                applog.log("resumed: queued again after the restart", job_id, self.job_dir(job_id))
            self._cond.notify_all()
        return queued

    @property
    def draining(self) -> bool:
        return self._draining

    def drain(self, max_s: float, *, poll_s: float = 5.0) -> int:
        """Stop starting and accepting jobs, wait up to `max_s` for the running ones; return how many were cut off.

        Queued jobs stay queued on disk (they resume after the restart). A job still running at the end is
        marked failed with a plain reason and `ANOMALY drain_cut_off`.
        """
        deadline = time.monotonic() + max_s
        with self._cond:
            self._draining = True
            self._cond.notify_all()
            last = -1
            while self._running:
                if len(self._running) != last:
                    last = len(self._running)
                    applog.log(f"drain: waiting for {last} running job(s), {len(self._waiting)} queued stay queued")
                left = deadline - time.monotonic()
                if left <= 0:
                    break
                self._cond.wait(min(left, poll_s))
            cut = sorted(self._running)
            for job_id in cut:
                self._mark_failed(self._jobs[job_id], self._jobs[job_id].get("stage") or "upload", DRAIN_CUT_REASON)
                self._write(self._jobs[job_id])
        for job_id in cut:
            applog.anomaly("drain_cut_off", f"job still running after {max_s:.0f} s", job=job_id,
                           job_dir=self.job_dir(job_id), kind=self._jobs[job_id].get("kind"))
        applog.log(f"drain: done, {len(cut)} job(s) cut off")
        return len(cut)

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
            if self._draining:
                raise DrainingError(DRAINING_MESSAGE)
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
            if stage and job_id in self._started:
                self._enter_stage(job_id, stage)
            self._write(job)
            self._cond.notify_all()

    def _enter_stage(self, job_id: str, stage: str) -> None:
        """Close the time of the stage the job was in and start `stage` (caller holds the lock)."""
        now = self._clock()
        mark = self._marks.get(job_id)
        if mark is not None and mark[0] != stage:
            spent = self._durations.setdefault(job_id, {})
            spent[mark[0]] = spent.get(mark[0], 0.0) + now - mark[1]
        if mark is None or mark[0] != stage:
            self._marks[job_id] = (stage, now)
        applog.fact(job_id, "_stage", stage)

    def snapshot(self) -> dict[str, Any]:
        """`queued`, `running` and `oldest_running_s` (None when nothing runs), for the heartbeat."""
        with self._cond:
            now = self._clock()
            ages = [now - self._started[j] for j in self._running if j in self._started]
            return {"queued": len(self._waiting), "running": len(self._running),
                    "oldest_running_s": max(ages) if ages else None}

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

    def forget(self, job_id: str) -> bool:
        """Drop a finished (`done` or `failed`) job and its folder; False when it is unknown or still queued or running."""
        with self._cond:
            job = self._jobs.get(job_id)
            if job is None or job["status"] not in ("done", "failed"):
                return False
            del self._jobs[job_id]
            self._marks.pop(job_id, None)
            self._durations.pop(job_id, None)
            self._started.pop(job_id, None)
        shutil.rmtree(self.job_dir(job_id), ignore_errors=True)
        return True

    def active_refs(self, field: str, value: str, exclude: str = "") -> bool:
        """True when a queued or running job other than `exclude` has `field == value` (an upload or people job in use)."""
        with self._cond:
            return any(j.get(field) == value and j.get("status") in ("queued", "running")
                       for jid, j in self._jobs.items() if jid != exclude)

    def finished_refs(self, field: str, value: str, exclude: str = "", ignore_kinds: tuple[str, ...] = ()) -> bool:
        """True when a finished job other than `exclude` has `field == value` (its result still reads that source).

        Jobs of a kind in `ignore_kinds` do not count.
        """
        with self._cond:
            return any(j.get(field) == value and j.get("status") == "done" and j.get("kind") not in ignore_kinds
                       for jid, j in self._jobs.items() if jid != exclude)

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
        self._stop_sweeper.set()
        job_lookup.release(self.root, self.trainer_for)
        for thread in self._threads:
            if thread.is_alive():
                thread.join(timeout=timeout)

    def _loop(self) -> None:
        while True:
            with self._cond:
                while (not self._waiting or self._draining) and not self._closed:
                    self._cond.wait()
                if self._closed:
                    return
                job_id, fn = self._waiting.popleft()
                self._running.add(job_id)
                self._started[job_id] = self._clock()
                self._jobs[job_id].update(status="running", started_at=_now())
                self._write(self._jobs[job_id])
                self._cond.notify_all()
            self._run_one(job_id, fn)
            with self._cond:
                self._running.discard(job_id)
                self._started.pop(job_id, None)
                self._marks.pop(job_id, None)
                self._durations.pop(job_id, None)
                self._cond.notify_all()

    def _start_line(self, job_id: str) -> str:
        with self._cond:
            job = dict(self._jobs[job_id])
        keys_ = ("kind", "people_job", "person_id", "trainer_id", "follower_ids", "entry_id", "trim", "duration_ms")
        return "start: " + " ".join(f"{k}={json.dumps(job[k])}" for k in keys_ if job.get(k) is not None)

    def _finish(self, job_id: str, ctx: JobContext, t0: float, status: str, stage: str | None = None,
                reason: str = "", cause: str = "failed") -> None:
        """At a job's end: the `slow_job` and `job_failed` anomalies and the one `summary` line."""
        total = self._clock() - t0
        with self._cond:
            if job_id in self._marks:
                self._enter_stage(job_id, "")  # closes the stage the job ended in
            spent = dict(self._durations.get(job_id, {}))
            job = dict(self._jobs[job_id])
        facts = applog.pop_facts(job_id)
        if status == "failed":
            applog.anomaly("job_failed", reason, job=job_id, job_dir=ctx.dir, stage=stage, cause=cause,
                           kind=job.get("kind"), seconds=total)
        limit = applog.env_float("SIMON7_SLOW_JOB_S", SLOW_JOB_S)
        if total > limit:
            applog.anomaly("slow_job", job=job_id, job_dir=ctx.dir, kind=job.get("kind"), seconds=total, limit=limit)
        applog.log(summary_line(job_id, job, status, total, spent, facts), job_dir=ctx.dir)

    def _run_one(self, job_id: str, fn: JobFn) -> None:
        ctx = JobContext(self, job_id)
        t0 = self._clock()
        applog.log(self._start_line(job_id), job_id, ctx.dir)
        try:
            outcome = fn(ctx)
            outcome = outcome if isinstance(outcome, dict) else {}
            fields: dict[str, Any] = {"status": "done", "finished_at": _now()}
            for key in ("result", "entry_id"):
                if outcome.get(key) is not None:
                    fields[key] = outcome[key]
            with self._cond:
                note = self._jobs[job_id].get("note")
            # logged before the record says done, so whoever waits for `done` finds the line already written
            applog.log(f"done in {self._clock() - t0:.1f} s" + (f"; note: {note}" if note else ""), job_id, ctx.dir)
            self._finish(job_id, ctx, t0, "ok")
            self.update(job_id, **fields)
            self._record_history(job_id)
        except JobFailed as exc:
            applog.log(f"failed at {exc.stage} after {self._clock() - t0:.1f} s: {applog.cause(exc)}", job_id,
                       ctx.dir, logging.WARNING)
            self._finish(job_id, ctx, t0, "failed", exc.stage, sanitize_reason(exc.reason), exc.cause)
            self._fail(job_id, exc.stage, sanitize_reason(exc.reason))
        except Exception as exc:  # the traceback stays in the job log only
            (ctx.dir / "steps").mkdir(exist_ok=True)
            (ctx.dir / "steps" / "error.log").write_text(keys.redact(traceback.format_exc()), encoding="utf-8")
            with self._cond:
                stage = self._jobs[job_id].get("stage") or "upload"
            applog.log(f"crashed at {stage}: {applog.cause(exc)} (traceback in steps/error.log)", job_id, ctx.dir, logging.ERROR)
            self._finish(job_id, ctx, t0, "failed", stage, FALLBACK_REASON, "crash")
            self._fail(job_id, stage, FALLBACK_REASON)

    def _record_history(self, job_id: str) -> None:
        """A finished take of a signed-in student who opted in gets a history copy (history.md).

        The copy transcodes the clip, so it runs on its own daemon thread: the job worker is free for the next job at once."""
        job, folder = self.get(job_id), self.job_dir(job_id)

        def copy() -> None:
            try:
                history_store.record_take(self.root.parent, job, folder)
            except Exception as exc:  # never fails the job, which is already done
                applog.log(f"history: could not record the take: {applog.cause(exc)}", job_id, folder, logging.WARNING)

        threading.Thread(target=copy, name=f"history-copy-{job_id}", daemon=True).start()

    def _fail(self, job_id: str, stage: str, reason: str) -> None:
        with self._cond:
            job = self._jobs[job_id]
            self._mark_failed(job, stage, reason)
            self._write(job)
            self._cond.notify_all()
