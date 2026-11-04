"""Job queue of the web app: one worker, a free GPU memory check, a timeout, cancel and cleanup.

Spec: docs/specs/run-app.md (Jobs; AC-A08, AC-A09, AC-A12), docs/specs/tracker-registry.md (Budget). ADR-0007.

    q = JobQueue(jobs_dir)                 # jobs_dir/<id>/ for each job (outside the repo tree)
    q.start()                              # marks jobs left unfinished by a restart as failed, sweeps, starts
    job = q.new_job(mode="single", kind="video", backend="gpu", tracker=None)   # its dir exists now
    q.submit(job)                          # QueueFull when 5 jobs are not yet finished
    q.public(job.id)                       # the visitor's view of one job; q.listing() for the queue
    q.cancel(job.id)                       # kills the run's process group
    q.stop()

States: queued -> waiting-gpu -> running -> done | failed | cancelled. Each job runs `part2 run` as a subprocess
in its own process group (start_new_session), with the GPU venv python when it exists. A job that uses the GPU
waits until the host's GPU lock is free and 12 GiB are free, re-checked every 15 s for 10 minutes. The worker then
lets go of the lock and starts the run, which takes it around each GPU stage itself (`part2 run` around the gpu
backend's estimate, a SAM tracker while it tracks), so the run never waits on its own parent.
The server never holds a key: the run reads key files through part2.keys, and MODEL_API_KEY and HF_TOKEN are
removed from its environment. Spend: the staging ledger ($10) and a per-job ledger in the job dir ($0.50).
"""
from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field, fields
from pathlib import Path

from part2 import gpu_guard
from part2.backends import NoPersonFound

ROOT = Path(__file__).resolve().parent.parent
STATES = ("queued", "waiting-gpu", "running", "done", "failed", "cancelled")
FINISHED = frozenset({"done", "failed", "cancelled"})
JOB_ID = re.compile(r"[0-9a-f]{12}")
STAGES = ("frames", "track", "pose", "write")
FPS = 10                                       # video and photo intake rate (run-app.md, Uploads and limits)
DOWNLOADS = ("pose3d.json", "tracks.json", "camera.json")
JOBS_ENV = "PART2_JOBS_DIR"
JOBS_DEFAULT = "~/.local/state/simon-part-2/jobs"
PYTHON_ENV = "PART2_JOB_PYTHON"
GPU_PYTHON = "~/.local/state/simon-part-2/venvs/gpu-cu128/bin/python"
STAGING_LEDGER = "~/.simon/meta_spend_staging.jsonl"
KEY_VARS = ("MODEL_API_KEY", "HF_TOKEN")       # never handed to a run; it reads the key files itself
GPU_TRACKERS = (None, "local-open")            # Automatic runs local-sam31 or local-open: GPU, the tracker locks
# The CPU backend missed the 3D bar with all three lifters (bones-prior, the default, at 0.145 m mean distance;
# fixed-bones 0.2656 m; motionbert 0.2914 m; limit 0.10 m, AC-B10), so its results are labelled "3D approximate".
# Set True once TICKET-016 records a pass.
CPU_3D_BAR_PASSED = False

MESSAGES = {
    "gpu_busy": "The GPU is busy with other work; try again later.",
    "timeout": "The job took longer than 20 minutes and was stopped.",
    "restarted": "The server restarted.",
    "no_person": "No person was found in this file.",
    "out_of_memory": "The GPU ran out of memory on this file. Try a shorter clip or the CPU backend.",
    "start": "The job could not be started on this server.",
    "failed": "The run stopped with an error. Try another file, or try again later.",
}
# Run errors that have a plain message of their own, found in the stderr text; anything else gets MESSAGES["failed"].
# "No person found" is found by the run's exit code first (NoPersonFound.exit_code, CONTRACT.md); its pattern stays
# for a run that only left the line (a part2 from before the code, a different command behind PART2_JOB_PYTHON).
ERROR_PATTERNS = (
    (re.compile(r"no person found", re.I), "no_person"),
    (re.compile(r"another GPU job is running"), "gpu_busy"),
    (re.compile(r"out of memory|OutOfMemoryError", re.I), "out_of_memory"),
)


class QueueFull(RuntimeError):
    pass


class AlreadyFinished(RuntimeError):
    pass


@dataclass
class Settings:
    max_pending: int = 5                # jobs not yet finished
    min_free_gib: float = gpu_guard.MIN_FREE_GIB
    gpu_wait_s: float = 600.0
    gpu_poll_s: float = 15.0
    timeout_s: float = 1200.0
    retention_s: float = 86400.0
    sweep_every_s: float = 600.0
    kill_grace_s: float = 5.0
    poll_s: float = 0.25
    total_budget_usd: float = 10.0
    job_budget_usd: float = 0.50
    staging_ledger: str = STAGING_LEDGER


@dataclass
class Job:
    id: str
    dir: Path
    mode: str                           # single | class
    kind: str                           # video | photo | sample
    input: str = ""                     # what the run reads: a file in the job dir or a sample's frames dir
    backend: str = "gpu"
    tracker: str | None = None          # None is Automatic (the bulk order); else local-open or bytetrack
    sample: str | None = None
    state: str = "queued"
    created: float = 0.0
    started: float | None = None
    ended: float | None = None
    progress: dict = field(default_factory=lambda: {"stage": None, "done": 0, "total": 0})
    error: str | None = None
    ran: dict = field(default_factory=dict)          # backend, tracker, lifter named by the written files
    fallback: dict | None = None
    notice: str | None = None
    approximate: bool = False
    frames: int = 0
    files: list = field(default_factory=list)
    cancel_event: threading.Event = field(default_factory=threading.Event, repr=False, compare=False)

    SAVED = ("id", "mode", "kind", "input", "backend", "tracker", "sample", "state", "created", "started", "ended",
             "progress", "error", "ran", "fallback", "notice", "approximate", "frames", "files")

    def record(self) -> dict:
        return {k: getattr(self, k) for k in self.SAVED}

    @classmethod
    def from_record(cls, rec: dict, d: Path) -> "Job":
        known = {f.name for f in fields(cls)} & set(cls.SAVED)
        job = cls(dir=d, **{k: v for k, v in rec.items() if k in known})
        if job.state not in STATES or not JOB_ID.fullmatch(job.id):
            raise ValueError("not a job record")
        return job

    def public(self, position) -> dict:
        """What a visitor sees: no path, no command line, no log."""
        ran = self.ran or {}
        tracker = ran.get("tracker") if self.state == "done" else (
            None if self.mode == "single" else self.tracker or "automatic")
        return {"id": self.id, "state": self.state, "mode": self.mode, "kind": self.kind, "sample": self.sample,
                "backend": ran.get("backend") or self.backend, "tracker": tracker, "lifter": ran.get("lifter"),
                "fallback": self.fallback, "notice": self.notice, "approximate": self.approximate,
                "progress": dict(self.progress), "position": position, "error": self.error,
                "files": list(self.files), "frames": self.frames, "created": self.created,
                "started": self.started, "ended": self.ended}


# ---- progress -------------------------------------------------------------------------------------------

class Progress:
    """Turns the run's stdout into {stage, done, total}. `progress <stage> <done> <total>` lines (PART2_PROGRESS=1)
    win; until the first such line, the run's own summary lines move the stage on."""
    LINE = re.compile(r"progress (frames|track|pose|write) (\d+) (\d+)\s*$")
    FRAMES = re.compile(r"(\d+) frames -> ")

    def __init__(self, mode: str):
        self.mode, self.n, self.explicit = mode, 0, False
        self.value = {"stage": "frames", "done": 0, "total": 0}

    def feed(self, line: str) -> bool:
        line = line.strip()
        m = self.LINE.fullmatch(line)
        if m:
            self.explicit = True
            done, total = int(m.group(2)), int(m.group(3))
            self.value = {"stage": m.group(1), "done": min(done, total) if total else done, "total": total}
            return True
        if self.explicit:
            return False
        m = self.FRAMES.match(line)
        if m:
            self.n = int(m.group(1))
            self.value = {"stage": "track" if self.mode == "class" else "pose", "done": 0, "total": self.n}
        elif " tracked people -> " in line:
            self.value = {"stage": "pose", "done": 0, "total": self.n}
        elif line.startswith("camera-space 3D"):
            self.value = {"stage": "write", "done": 0, "total": 1}
        elif line.startswith("pose3d for people") or line.endswith("camera.json"):
            self.value = {"stage": "write", "done": 1, "total": 1}
        else:
            return False
        return True


def classify(stderr_tail: str, returncode: int | None = None) -> str:
    """The visitor's message for a failed run: by its exit code when the code says what happened, else by its stderr."""
    if returncode == NoPersonFound.exit_code:
        return MESSAGES["no_person"]
    for pattern, key in ERROR_PATTERNS:
        if pattern.search(stderr_tail):
            return MESSAGES[key]
    return MESSAGES["failed"]


# ---- the run command and its environment ---------------------------------------------------------------------

def job_python() -> str:
    """PART2_JOB_PYTHON, else the gpu-cu128 venv python when it exists, else this interpreter."""
    given = os.environ.get(PYTHON_ENV)
    if given:
        return given
    gpu = Path(GPU_PYTHON).expanduser()
    return str(gpu) if gpu.is_file() else sys.executable


def default_command(job: Job, python: str | None = None) -> list[str]:
    argv = [python or job_python(), "-m", "part2", "run", "--mode", "multi" if job.mode == "class" else "single",
            "--input", job.input, "--out", str(job.dir / "out"), "--backend", job.backend]
    if job.kind in ("video", "photo"):
        argv += ["--fps", str(FPS)]
    if job.mode == "class" and job.tracker:
        argv += ["--tracker", job.tracker]
    return argv


def run_env(settings: Settings, job_dir: Path | None = None, root: Path = ROOT) -> dict:
    """The environment of a run (and of the capability probe): no key, no PART2_TRACKER (the order decides),
    the staging spend settings, progress lines on, no bytecode written into the tree."""
    drop = set(KEY_VARS) | {"PART2_TRACKER"}
    env = {k: v for k, v in os.environ.items() if k not in drop}
    env.update({
        "PYTHONPATH": str(root), "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1", "PART2_PROGRESS": "1",
        "META_SPEND_LEDGER": str(Path(settings.staging_ledger).expanduser()),
        "META_BUDGET_USD": f"{settings.total_budget_usd:g}",
        "PART2_JOB_BUDGET_USD": f"{settings.job_budget_usd:g}",
    })
    if job_dir is not None:
        env["PART2_JOB_LEDGER"] = str(job_dir / "meta_spend_job.jsonl")
    return env


def kill_group(proc: subprocess.Popen, grace_s: float = 5.0, wait: bool = True) -> None:
    """SIGTERM to the run's own process group, then SIGKILL after grace_s. Never signals any other group:
    the group id is the run's pid because it was started with start_new_session."""
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(proc.pid, sig)
        except (ProcessLookupError, PermissionError):
            return
        if not wait:
            return
        try:
            proc.wait(timeout=grace_s)
            return
        except subprocess.TimeoutExpired:
            continue


def default_jobs_dir(port: int | None = None) -> Path:
    """PART2_JOBS_DIR, else ~/.local/state/simon-part-2/jobs/<port>: each server owns its own job dirs, so a
    restart of the dev server never touches the staging server's jobs."""
    given = os.environ.get(JOBS_ENV)
    if given:
        return Path(given).expanduser()
    base = Path(JOBS_DEFAULT).expanduser()
    return base / str(port) if port else base


# ---- the queue ----------------------------------------------------------------------------------------------

class JobQueue:
    def __init__(self, jobs_dir, settings: Settings | None = None, command=None, root: Path = ROOT,
                 free_gib=None, try_lock=None, release=None, clock=time.time):
        self.dir = Path(jobs_dir).expanduser()
        self.settings = settings or Settings()
        self.command = command or default_command
        self.root = Path(root)
        self.free_gib = free_gib or gpu_guard.free_gib
        self.try_lock = try_lock or gpu_guard.try_lock
        self.release = release or gpu_guard.release
        self.clock = clock
        self._jobs: dict[str, Job] = {}
        self._order: list[str] = []
        self._current: Job | None = None
        self._proc: subprocess.Popen | None = None
        self._cv = threading.Condition()
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []

    # -- lifecycle

    def start(self) -> "JobQueue":
        self.recover()
        for target in (self._worker, self._sweeper):
            t = threading.Thread(target=target, daemon=True, name=f"jobs-{target.__name__.strip('_')}")
            t.start()
            self._threads.append(t)
        return self

    def stop(self) -> None:
        self._stop.set()
        with self._cv:
            job, proc = self._current, self._proc
            if job is not None and job.state not in FINISHED:
                self._finish(job, "failed", MESSAGES["restarted"])
                job.cancel_event.set()
            self._cv.notify_all()
        if proc is not None:
            kill_group(proc, self.settings.kill_grace_s)
        for t in self._threads:
            t.join(2)

    def recover(self) -> None:
        """At start: unfinished jobs of an earlier run of this server are failed with "The server restarted.",
        anything older than the retention is removed, and dirs without a job record (an upload cut off by a
        crash) are removed."""
        self.dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        now = self.clock()
        for d in self._job_dirs():
            job = self._load(d)
            if job is None:
                self._remove(d)
                continue
            if job.state not in FINISHED:
                job.state, job.error, job.ended = "failed", MESSAGES["restarted"], now
                self._save(job)
            if now - (job.ended or job.created) > self.settings.retention_s:
                self._remove(d)
                continue
            with self._cv:
                self._jobs[job.id] = job

    # -- jobs

    def new_job(self, **attrs) -> Job:
        """A job with a fresh id and its own dir (mode 700); not queued until submit()."""
        self.dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        while True:
            jid = secrets.token_hex(6)
            try:
                (self.dir / jid).mkdir(mode=0o700)
                break
            except FileExistsError:
                continue
        return Job(id=jid, dir=self.dir / jid, created=self.clock(), **attrs)

    def discard(self, job: Job) -> None:
        """Remove a job that was never submitted (its upload was refused)."""
        self._remove(job.dir)

    def pending(self) -> int:
        with self._cv:
            return sum(1 for j in self._jobs.values() if j.state not in FINISHED)

    def submit(self, job: Job) -> Job:
        with self._cv:
            if sum(1 for j in self._jobs.values() if j.state not in FINISHED) >= self.settings.max_pending:
                raise QueueFull()
            job.state, job.created = "queued", self.clock()
            self._jobs[job.id] = job
            self._order.append(job.id)
            self._save(job)
            self._cv.notify_all()
        return job

    def get(self, jid: str) -> Job | None:
        with self._cv:
            return self._jobs.get(jid) if JOB_ID.fullmatch(jid or "") else None

    def busy(self) -> bool:
        with self._cv:
            return self._current is not None

    def _position(self, job: Job) -> int | None:
        if job.state in FINISHED:
            return None
        if job.state != "queued" or job.id not in self._order:
            return 0
        return (1 if self._current is not None else 0) + self._order.index(job.id)   # jobs ahead of this one

    def public(self, jid: str) -> dict | None:
        with self._cv:
            job = self._jobs.get(jid) if JOB_ID.fullmatch(jid or "") else None
            return None if job is None else job.public(self._position(job))

    def listing(self) -> list[dict]:
        """The queue as visitors see it: jobs not yet finished, oldest first, each named by a short reference
        rather than its id (an id lets its holder download or cancel the job)."""
        with self._cv:
            live = sorted((j for j in self._jobs.values() if j.state not in FINISHED), key=lambda j: j.created)
            return [{"ref": j.id[:4], "state": j.state, "position": self._position(j), "mode": j.mode,
                     "created": j.created} for j in live]

    def cancel(self, jid: str) -> str:
        with self._cv:
            job = self._jobs.get(jid) if JOB_ID.fullmatch(jid or "") else None
            if job is None:
                raise KeyError(jid)
            if job.state in FINISHED:
                raise AlreadyFinished(jid)
            if job.id in self._order:
                self._order.remove(job.id)
            self._finish(job, "cancelled", None)
            job.cancel_event.set()
            proc = self._proc if self._current is job else None
        if proc is not None:
            kill_group(proc, wait=False)       # the worker waits for it and sends SIGKILL if needed
        return "cancelled"

    # -- the worker

    def _worker(self) -> None:
        while not self._stop.is_set():
            with self._cv:
                while not self._order and not self._stop.is_set():
                    self._cv.wait()
                if self._stop.is_set():
                    return
                job = self._jobs[self._order.pop(0)]
                self._current = job
            try:
                self._run(job)
            except Exception as exc:  # never a dead worker; the class name goes to the server log only
                print(f"jobs: {type(exc).__name__} while running a job", file=sys.stderr)
                with self._cv:
                    if job.state not in FINISHED:
                        self._finish(job, "failed", MESSAGES["failed"])
            finally:
                with self._cv:
                    self._current = None

    def needs_gpu(self, job: Job) -> bool:
        return job.backend == "gpu" or self.run_takes_lock(job)

    @staticmethod
    def run_takes_lock(job: Job) -> bool:
        """A class run with a SAM tracker takes the GPU lock itself while it tracks."""
        return job.mode == "class" and job.tracker in GPU_TRACKERS

    def _run(self, job: Job) -> None:
        """Wait for the GPU (lock free and 12 GiB) when the job needs it, then run it without holding the lock:
        `part2 run` takes it around each GPU stage itself (AC-B-NFR-03), so it never waits on its own parent."""
        if job.cancel_event.is_set():
            return
        if self.needs_gpu(job):
            lock = self._wait_for_gpu(job)
            if lock is None:
                return
            self.release(lock)
        with self._cv:
            if job.state in FINISHED:
                return
            self._set(job, state="running", started=self.clock())
        self._execute(job)

    def _wait_for_gpu(self, job: Job):
        """The held GPU lock once 12 GiB are free, or None (cancelled, or failed after the wait limit)."""
        with self._cv:
            if job.state in FINISHED:
                return None
            self._set(job, state="waiting-gpu")
        deadline = time.monotonic() + self.settings.gpu_wait_s
        while not job.cancel_event.is_set():
            lock = self.try_lock()
            if lock is not None:
                free = self.free_gib()
                enough = free >= self.settings.min_free_gib if free is not None else job.backend != "gpu"
                if enough:
                    return lock
                self.release(lock)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                with self._cv:
                    if job.state not in FINISHED:
                        self._finish(job, "failed", MESSAGES["gpu_busy"])
                return None
            job.cancel_event.wait(min(self.settings.gpu_poll_s, remaining))
        return None

    def _execute(self, job: Job) -> None:
        out_log, err_log = job.dir / "run.out", job.dir / "run.err"
        try:
            with err_log.open("wb") as err:
                proc = subprocess.Popen(self.command(job), cwd=job.dir, env=run_env(self.settings, job.dir, self.root),
                                        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=err,
                                        start_new_session=True)
        except OSError:
            with self._cv:
                self._finish(job, "failed", MESSAGES["start"])
            return
        with self._cv:
            self._proc = proc
        reader = threading.Thread(target=self._read, args=(job, proc, out_log), daemon=True)
        reader.start()
        outcome = self._watch(job, proc)
        reader.join(5)
        with self._cv:
            self._proc = None
            if job.state in FINISHED:          # cancelled (or failed by stop()) while it ran
                return
            if outcome == "timeout":
                self._finish(job, "failed", MESSAGES["timeout"])
            elif proc.returncode == 0:
                self._collect(job)
            else:
                self._finish(job, "failed", classify(tail(err_log), proc.returncode))

    def _watch(self, job: Job, proc: subprocess.Popen) -> str:
        deadline = time.monotonic() + self.settings.timeout_s
        while True:
            try:
                proc.wait(timeout=self.settings.poll_s)
                return "exited"
            except subprocess.TimeoutExpired:
                pass
            if job.cancel_event.is_set():
                kill_group(proc, self.settings.kill_grace_s)
                return "cancelled"
            if time.monotonic() >= deadline:
                kill_group(proc, self.settings.kill_grace_s)
                return "timeout"

    def _read(self, job: Job, proc: subprocess.Popen, out_log: Path) -> None:
        prog = Progress(job.mode)
        with out_log.open("w", encoding="utf-8", errors="replace") as log:
            for raw in proc.stdout:
                line = raw.decode("utf-8", "replace")
                log.write(line)
                if prog.feed(line):
                    with self._cv:
                        if job.state == "running":
                            self._set(job, progress=dict(prog.value))
        proc.stdout.close()

    def _collect(self, job: Job) -> None:
        """Read what ran from the written files; a run that wrote no pose3d.json failed."""
        out = job.dir / "out"
        try:
            pose3d = json.loads((out / "pose3d.json").read_text())
            frames = len(pose3d["frames"])
        except (OSError, ValueError, KeyError, TypeError):
            self._finish(job, "failed", MESSAGES["failed"])
            return
        prov = pose3d.get("provenance") if isinstance(pose3d.get("provenance"), dict) else {}
        ran = {"backend": prov.get("backend") or job.backend, "tracker": prov.get("tracker"),
               "lifter": prov.get("lifter")}
        fallback = notice = None
        if prov.get("fallback_from"):
            fallback = {"from": prov["fallback_from"], "reason": prov.get("fallback_reason")}
            notice = fallback_notice(prov)
        files = [n for n in DOWNLOADS if (out / n).is_file()]
        self._finish(job, "done", None, ran=ran, fallback=fallback, notice=notice, files=files, frames=frames,
                     approximate=ran["backend"] == "cpu" and not CPU_3D_BAR_PASSED,
                     progress={"stage": "write", "done": 1, "total": 1})

    # -- state changes (called with self._cv held)

    def _set(self, job: Job, **changes) -> None:
        for k, v in changes.items():
            setattr(job, k, v)
        self._save(job)

    def _finish(self, job: Job, state: str, error: str | None, **changes) -> None:
        self._set(job, state=state, error=error, ended=self.clock(), **changes)

    # -- storage and cleanup

    def _job_dirs(self) -> list[Path]:
        try:
            return [d for d in self.dir.iterdir() if JOB_ID.fullmatch(d.name) and d.is_dir() and not d.is_symlink()]
        except OSError:
            return []

    @staticmethod
    def _load(d: Path) -> Job | None:
        try:
            return Job.from_record(json.loads((d / "job.json").read_text()), d)
        except (OSError, ValueError, TypeError):
            return None

    @staticmethod
    def _save(job: Job) -> None:
        tmp = job.dir / "job.json.tmp"
        try:
            tmp.write_text(json.dumps(job.record()))
            os.replace(tmp, job.dir / "job.json")
        except OSError:
            pass                               # the record in memory stays authoritative

    def _remove(self, d: Path) -> None:
        """Delete one job dir: only a direct child of the jobs dir named like a job id, never a symlink."""
        if d.parent != self.dir or not JOB_ID.fullmatch(d.name) or d.is_symlink():
            return
        shutil.rmtree(d, ignore_errors=True)

    def sweep(self) -> None:
        """Remove jobs that ended more than the retention ago, and stray dirs older than it."""
        now, keep_s = self.clock(), self.settings.retention_s
        with self._cv:
            old = [j for j in self._jobs.values() if j.state in FINISHED and now - (j.ended or j.created) > keep_s]
            for j in old:
                del self._jobs[j.id]
            known = set(self._jobs)
        for j in old:
            self._remove(j.dir)
        for d in self._job_dirs():
            if d.name in known:
                continue
            try:
                age = now - d.stat().st_mtime
            except OSError:
                continue
            if age > keep_s:
                self._remove(d)

    def _sweeper(self) -> None:
        while not self._stop.wait(self.settings.sweep_every_s):
            try:
                self.sweep()
            except Exception as exc:  # the sweeper must outlive one bad dir
                print(f"jobs: {type(exc).__name__} while sweeping", file=sys.stderr)


def fallback_notice(prov: dict) -> str | None:
    """The plain line for a job that ran a later tracker: part2.provenance.fallback_note, the wording the CLI prints
    (a spend cap, no key, no parity pass, not installed, a refused Meta credential). A reason it does not know still
    names the tracker that ran."""
    from part2 import provenance

    try:
        return provenance.fallback_note(prov)
    except KeyError:
        return f"tracked with {prov.get('tracker')}"


def tail(path: Path, size: int = 8192) -> str:
    try:
        with path.open("rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - size))
            return f.read().decode("utf-8", "replace")
    except OSError:
        return ""
