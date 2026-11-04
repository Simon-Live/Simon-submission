"""Part 2 and captions on the operator's Modal workspace (docs/specs/serverless-compute.md).

The launcher `deploy/serverless/p2_client.py --serverless` gets the path of the secrets folder and never a token; only its
child, the process that talks to Modal, opens the token files. A person's media goes up to a Modal Volume under a random
key. The ledger `<state>/modal-keys/<key>.json` (`{job, at}`, written by the client before the upload and removed once the
object is deleted) is how a take delete or the sweep finds what a crash left at Modal.
"""

from __future__ import annotations

import contextlib
import contextvars
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from typing import Iterator

from part7 import applog, compute_mode, config, job_gpu, own_clients

CLIENT = config.REPO_ROOT / "deploy" / "serverless" / "p2_client.py"
BUSY_EXIT, STOPPED_EXIT = 79, 80  # = p2_client.BUSY_EXIT, STOPPED_EXIT (a test keeps them equal)
LEDGER_DIR = "modal-keys"
STATUS_FILE = "serverless-status.json"
OWNER = "server"  # own_clients: the launcher registers so the drain and down.sh stop it, under no person's id
STALE_S = 3 * 3600.0  # a ledger entry this old has no running call: the client waits less than this for any call
WATCH_S = 2.0
DELETE_TIMEOUT_S = 300.0
MSG_SIGN_IN = "Sign in to analyse a take. Simon needs an account for GPU work."
MSG_BUSY = "Simon's graphics cards were all busy, so this take did not run. Try it again in a few minutes."
MSG_STOPPED = "Simon cannot run GPU work right now, so this take did not run. Try again later."
MESSAGES = {BUSY_EXIT: MSG_BUSY, STOPPED_EXIT: MSG_STOPPED}

_JOB: contextvars.ContextVar[tuple[str, str, list[int]] | None] = contextvars.ContextVar("serverless_job", default=None)


def enabled() -> bool:
    return compute_mode.serverless()


def ledger(state: Path | str) -> Path:
    return Path(state) / LEDGER_DIR


@contextlib.contextmanager
def job(state: Path | str, job_id: str) -> Iterator[list[int]]:
    """Within the block, this thread's calls belong to `job_id`; yields the list a stopped call's exit code lands in."""
    stops: list[int] = []
    token = _JOB.set((str(state), str(job_id), stops))
    try:
        with own_clients.job(state, OWNER):
            yield stops
    finally:
        _JOB.reset(token)


def note_exit(code: int | None) -> None:
    found = _JOB.get()
    if found is not None and code in MESSAGES:
        found[2].append(code)


def timeout_s(base: float) -> float:
    """A call's bound: its run time, the wait for a GPU and a margin for the upload."""
    return base + config.serverless_queue_wait_s() + 120.0


def _flags(status: Path | None) -> list[str]:
    found = _JOB.get()
    out = ["--secrets-dir", str(config.keys_dir())]
    if found is not None:
        out += ["--ledger", str(ledger(found[0])), "--job", found[1]]
    if status is not None:
        out += ["--status", str(status)]
    return [*out, "--queue-wait", f"{config.serverless_queue_wait_s():.0f}"]


def command(sub: list[str], sha: str, work: Path | str) -> list[str]:
    """Part 2 `sub` on the operator's workspace. No token in this argv: a folder's path only."""
    status = Path(work) / "steps" / STATUS_FILE
    return [sys.executable, "-I", str(CLIENT), "--serverless", *own_clients.launcher_args(), *_flags(status),
            "--sha", sha, "--", *sub]


def transcribe_command(wav: Path | str, out: Path | str) -> list[str]:
    return [sys.executable, "-I", str(CLIENT), "--serverless", *own_clients.launcher_args(), *_flags(None), "--transcribe",
            "--input", str(wav), "--out", str(out)]


@contextlib.contextmanager
def watching(work: Path | str) -> Iterator[None]:
    """While a call runs, its status file drives the job record's `wait`: the job page says it waits for a GPU."""
    path, stop = Path(work) / "steps" / STATUS_FILE, threading.Event()

    def loop() -> None:
        shown = False
        while not stop.wait(WATCH_S):
            doc = _status(path)
            if doc.get("state") == "queued" and not shown:
                job_gpu.waiting(work, job_gpu.GPU_QUEUE, float(doc.get("since") or time.time()))
                shown = True
            elif doc.get("state") != "queued" and shown:
                job_gpu.admitted(work)
                shown = False
        if shown:
            job_gpu.admitted(work)

    thread = threading.Thread(target=loop, name="serverless-wait", daemon=True)
    path.unlink(missing_ok=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=WATCH_S + 1)
        path.unlink(missing_ok=True)


def _status(path: Path) -> dict:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


# ----- what is left at Modal -----------------------------------------------------------------------------------------
def _entries(state: Path | str) -> list[tuple[Path, dict]]:
    folder = ledger(state)
    if not folder.is_dir():
        return []
    return [(path, _status(path)) for path in sorted(folder.glob("*.json"))]


def mark_job(state: Path | str, job_id: str) -> int:
    """Mark what the ledger names for `job_id` as due now (a take or account delete); how many entries."""
    count = 0
    for path, doc in _entries(state):
        if doc.get("job") == job_id:
            doc["due"] = True
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(doc), encoding="utf-8")
            os.replace(tmp, path)
            count += 1
    return count


def due(state: Path | str, now: float | None = None) -> int:
    """Entries a call no longer needs: marked by a delete, or older than STALE_S."""
    moment = time.time() if now is None else now
    return sum(1 for _, doc in _entries(state)
               if doc.get("due") or moment - float(doc.get("at") or 0) > STALE_S)


def delete_due(state: Path | str, run=subprocess.run) -> bool:
    """Run the client's `--delete` when anything is due; entries stay until Modal confirmed. Modal unreachable or a
    failed delete is logged and the next sweep tries again."""
    count = due(state)
    if not count:
        return True
    argv = [sys.executable, "-I", str(CLIENT), "--serverless", "--secrets-dir", str(config.keys_dir()),
            "--ledger", str(ledger(state)), "--stale-s", f"{STALE_S:.0f}", "--delete"]
    try:
        done = run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   start_new_session=True, timeout=DELETE_TIMEOUT_S, check=False)
        code = int(done.returncode)
    except (OSError, subprocess.TimeoutExpired) as exc:
        applog.log(f"serverless: delete at Modal did not run ({type(exc).__name__}); {count} left for the next sweep",
                   level=logging.WARNING)
        return False
    if code != 0:
        applog.log(f"serverless: delete at Modal ended with exit {code}; {count} left for the next sweep",
                   level=logging.WARNING)
    return code == 0


def forget_job(state: Path | str, job_id: str) -> None:
    """A take or account delete: what is still at Modal for this job goes now, off the request's thread."""
    if not enabled() or not mark_job(state, job_id):
        return
    threading.Thread(target=delete_due, args=(state,), name="serverless-delete", daemon=True).start()
