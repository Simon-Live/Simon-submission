"""Processor jobs: choose a processor and run recordings through it one at a time.

The plug-in contract is documented in `part6/processor.py` (docs/specs/catalog-contract.md
AC-C09). `parse_processor` turns `module:function` into the callable. `Jobs` owns one worker
thread that runs submitted recordings in order, keeps each job's status and stores the result as a
catalog entry through a callback. Status vocabulary, exactly: `queued`, `processing:<stage>`,
`failed:<stage>: <reason>`, `done`. Jobs live in memory: the last `keep` are kept and a restart
loses them; the entry folder is the durable result.
"""
from __future__ import annotations

import importlib
import re
import sys
import threading
import time
import traceback
from collections import OrderedDict, deque

from . import catalog, formats, importer, processor

DEFAULT_PROCESSOR = processor.DEFAULT
SPEC_RE = re.compile(r"^[A-Za-z_][\w.]*:[A-Za-z_]\w*\Z")
STAGE_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}\Z")
# A failed status exactly as published in contracts/job-status.schema.json: the stage, a colon, a
# space and a reason that starts with a visible character.
FAILED_RE = re.compile(r"^failed:[a-z0-9][a-z0-9_-]{0,31}: \S.*\Z")
PROCESSING = "processing:"
FAILED = "failed:"
REASON_MAX = 200
STATUS_MAX = 300
UNSTAGED = "processing"       # the stage named when a processor fails before it reported one
NO_REASON = "the processor failed"
VALIDATE_STAGE = "validate"
STORE_STAGE = "store"


class Busy(Exception):
    """Too many recordings are waiting, or the queue is closed."""


def _first_line(text, limit=REASON_MAX):
    lines = str(text).strip().splitlines()
    return (lines[0].strip() if lines else "")[:limit].rstrip()


def parse_processor(spec):
    """The callable named by `module:function`; ValueError with a plain message when it cannot be
    used. The module is imported here, so a bad setting stops the server at start."""
    if not isinstance(spec, str) or not SPEC_RE.match(spec):
        raise ValueError(f"processor {spec!r} must look like module:function")
    module_name, _, function = spec.partition(":")
    try:
        module = importlib.import_module(module_name)
    except Exception as exc:    # a module can fail to import in any way
        reason = _first_line(exc) or type(exc).__name__
        raise ValueError(f"processor {spec}: cannot import {module_name}: {reason}") from exc
    if not hasattr(module, function):
        raise ValueError(f"processor {spec}: {module_name} has no {function}")
    run = getattr(module, function)
    if not callable(run):
        raise ValueError(f"processor {spec}: {function} is not a function")
    return run


def describe(run):
    """`module:function` of a processor callable (the class name for a callable object); the
    default spec for None, the mock."""
    if run is None:
        return DEFAULT_PROCESSOR
    module = getattr(run, "__module__", None) or type(run).__module__
    return f"{module}:{getattr(run, '__name__', None) or type(run).__name__}"


def _stage_of(status):
    """The stage in a `processing:<stage>` string, or None for anything else."""
    if isinstance(status, str) and status.startswith(PROCESSING):
        stage = status[len(PROCESSING):]
        if STAGE_RE.match(stage):
            return stage
    return None


def _failed(stage, reason):
    return f"{FAILED}{stage}: {reason or NO_REASON}"


def _returned_failure(status, stage):
    """The status for a processor's returned `failed:...` text. One that is exactly
    `failed:<stage>: <reason>` is kept (first line, at most STATUS_MAX characters); any other
    becomes `failed:<last reported stage, else processing>: <the text after "failed:">`, so a
    served status always matches the published pattern."""
    line = _first_line(status, STATUS_MAX)
    if FAILED_RE.match(line):
        return line
    return _failed(stage or UNSTAGED, _first_line(line[len(FAILED):], REASON_MAX))


class _Job:
    def __init__(self, recording):
        self.id = recording["id"]
        self.recording = dict(recording)
        self.status = "queued"
        self.stage = None          # the last stage reported
        self.entry = None
        self.finished = False

    def snapshot(self):
        return {"id": self.id, "status": self.status, "entry": self.entry}


class Jobs:
    """Run recordings through `run` on one worker thread, in the order they were submitted.

    `run` is the processor callable; None means the mock `part6.processor.process`, looked up
    when a job starts. `store(recording, files, files_source, description)` writes the entry and
    returns its manifest; the default stores it without a lock or a cap. At most `max_waiting`
    jobs wait behind the running one, and the last `keep` jobs are remembered.
    """

    def __init__(self, root, run=None, max_waiting=8, keep=50, store=None):
        self.root = root
        self.max_waiting = max_waiting
        self.keep = keep
        self._run = run
        self._store = store or self._store_entry
        self._cond = threading.Condition()
        self._jobs = OrderedDict()
        self._waiting = deque()
        self._closed = False
        self._thread = threading.Thread(target=self._work, name="part6-jobs", daemon=True)
        self._thread.start()

    # Public

    def submit(self, recording):
        """Queue a recording; the job dict `{id, status, entry}`. Raises Busy when the queue is
        full. The job id is the recording's id, which must not be in use."""
        with self._cond:
            if self._closed:
                raise Busy("the processor queue is closed")
            if len(self._waiting) >= self.max_waiting:
                raise Busy(f"{self.max_waiting} recordings are already waiting")
            if recording["id"] in self._jobs:
                raise ValueError(f"job {recording['id']} already exists")
            job = _Job(recording)
            self._jobs[job.id] = job
            self._waiting.append(job)
            self._trim()
            self._cond.notify_all()
            return job.snapshot()

    def has(self, job_id):
        with self._cond:
            return job_id in self._jobs

    def get(self, job_id):
        """The job dict, or None when the id is unknown or older than the last `keep` jobs."""
        with self._cond:
            job = self._jobs.get(job_id)
            return job.snapshot() if job else None

    def wait(self, job_id, seconds):
        """The job dict once the job is done or failed, or as it stands after `seconds`."""
        deadline = time.monotonic() + seconds
        with self._cond:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            while not job.finished:
                left = deadline - time.monotonic()
                if left <= 0:
                    break
                self._cond.wait(left)
            return job.snapshot()

    def close(self, timeout=1.0):
        """Stop taking jobs, fail the waiting ones and let the running one end. Python cannot stop
        a thread, so a processor that never returns is left behind (it is a daemon thread)."""
        with self._cond:
            self._closed = True
            while self._waiting:
                job = self._waiting.popleft()
                self._finish(job, _failed("shutdown", "the server stopped"))
            self._cond.notify_all()
        self._thread.join(timeout)

    # Worker

    def _work(self):
        while True:
            with self._cond:
                while not self._waiting and not self._closed:
                    self._cond.wait()
                if self._closed:
                    return
                job = self._waiting.popleft()
            try:
                self._execute(job)
            except Exception:    # a bug here must not stop the queue
                traceback.print_exc(file=sys.stderr)
                with self._cond:
                    self._finish(job, _failed(job.stage or UNSTAGED, "internal error"))

    def _execute(self, job):
        run = self._run or processor.process
        try:
            result = run(dict(job.recording), lambda status: self._report(job, status))
        except Exception as exc:
            traceback.print_exc(file=sys.stderr)
            reason = _first_line(exc) or type(exc).__name__
            with self._cond:
                self._finish(job, _failed(job.stage or UNSTAGED, reason))
            return
        self._settle(job, result)

    def _report(self, job, status):
        stage = _stage_of(status)
        if stage is None:
            catalog.log(f"job {job.id}: ignored status {repr(status)[:80]}")
            return
        with self._cond:
            if not job.finished:
                job.status, job.stage = PROCESSING + stage, stage
                self._cond.notify_all()

    def _settle(self, job, result):
        if not isinstance(result, dict):
            kind = type(result).__name__
            return self._end(job, _failed(job.stage or UNSTAGED, f"the processor returned {kind}"))
        status = result.get("status")
        if isinstance(status, str) and status.startswith(FAILED):
            return self._end(job, _returned_failure(status, job.stage))
        files = {kind: result[kind] for kind in formats.KINDS if result.get(kind) is not None}
        source, description = self._origin()
        try:
            manifest = self._store(job.recording, files, source, description)
        except importer.ImportProblem as exc:
            return self._end(job, _failed(VALIDATE_STAGE, _first_line(exc)))
        except Exception as exc:    # the detail may hold a server path: log it, do not serve it
            traceback.print_exc(file=sys.stderr)
            exists = isinstance(exc, FileExistsError)
            return self._end(job, _failed(
                STORE_STAGE, "the entry already exists" if exists else "could not save the entry"))
        self._end(job, "done", manifest)

    def _origin(self):
        """(files_source, description) of the entry this worker's processor makes."""
        day = f"{catalog.utc_now():%Y-%m-%d}"
        run = self._run
        if run is None or run is processor.process:
            return "mock", processor.MOCK_DESCRIPTION.format(day=day)
        return "processor", f"Recorded {day}. Processed by {describe(run)}."

    def _store_entry(self, recording, files, files_source, description):
        return importer.store_processed(self.root, recording, files, files_source=files_source,
                                        description=description, visitor=True)

    def _end(self, job, status, entry=None):
        with self._cond:
            self._finish(job, status, entry)

    def _finish(self, job, status, entry=None):
        """Mark a job over. The caller holds the lock."""
        job.status, job.entry, job.finished = status, entry, True
        self._trim()
        self._cond.notify_all()

    def _trim(self):
        """Forget the oldest finished jobs beyond `keep`. The caller holds the lock."""
        while len(self._jobs) > self.keep:
            oldest = next((key for key, job in self._jobs.items() if job.finished), None)
            if oldest is None:
                return
            del self._jobs[oldest]
