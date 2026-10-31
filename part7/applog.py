"""Part 7's own log: what Part 7 decided (trim, crop, fallbacks) and why a request or a job failed.

The parts' output already lands in `<job>/steps/*.log`. This log covers the glue between them, which was
silent before: one line per decision, prefixed with the job id when there is one, redacted like the step logs.
`serve` writes it to `<state>/part7.log` and to stderr; every job also gets its own `<job>/steps/part7.log`.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import time

from part7 import keys

LOGGER = logging.getLogger("part7")
FORMAT = "%(asctime)sZ %(levelname)s %(message)s"
MAX_BYTES = 5_000_000  # part7.log rolls to part7.log.1 .. .3 past this, so a restart never empties it
BACKUPS = 3


def _formatter() -> logging.Formatter:
    fmt = logging.Formatter(FORMAT, datefmt="%Y-%m-%dT%H:%M:%S")
    fmt.converter = time.gmtime  # UTC, like the job records
    return fmt


def setup(state: Path | str) -> Path:
    """Send the log to `<state>/part7.log` (appended, rotated) and stderr, once per process; return the path.

    `serve` calls it first, before the queue loads old jobs, so every line of the process lands in the file.
    """
    path = Path(state) / "part7.log"
    if not any(getattr(h, "_part7", False) for h in LOGGER.handlers):
        path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(path, maxBytes=MAX_BYTES, backupCount=BACKUPS, encoding="utf-8")
        for handler in (file_handler, logging.StreamHandler()):
            handler.setFormatter(_formatter())
            handler._part7 = True  # type: ignore[attr-defined]
            LOGGER.addHandler(handler)
        LOGGER.setLevel(logging.INFO)
    return path


def job_id_of(work: Path | str) -> str:
    """The job id of any folder inside `<state>/jobs/<id>/`, else the folder name."""
    return job_root(work).name


def job_root(folder: Path | str) -> Path:
    """`<state>/jobs/<id>` for any folder inside it, else `folder` itself."""
    p = Path(folder)
    for candidate in (p, *p.parents):
        if candidate.parent.name == "jobs":
            return candidate
    return p


def log(msg: str, job: str | None = None, job_dir: Path | str | None = None, level: int = logging.INFO) -> None:
    """Log `msg` (redacted); with `job_dir` also append it to the job's own `steps/part7.log`.

    Any folder inside `<state>/jobs/<id>/` (say `work/trainer`) means that job's `<id>/steps/part7.log`, so one
    job has one Part 7 log.
    """
    text = keys.redact(f"job {job}: {msg}" if job else msg)
    LOGGER.log(level, text)
    if job_dir is not None:
        try:
            steps = job_root(job_dir) / "steps"
            steps.mkdir(parents=True, exist_ok=True)
            with (steps / "part7.log").open("a", encoding="utf-8") as fh:
                fh.write(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {logging.getLevelName(level)} {text}\n")
        except OSError:
            pass


def cause(exc: BaseException) -> str:
    """The exception and whatever it was raised from (`from None` hides it but keeps `__context__`), shortened."""
    parts = [f"{type(exc).__name__}: {exc}"]
    inner = exc.__cause__ or exc.__context__
    if inner is not None:
        parts.append(f"caused by {type(inner).__name__}: {inner}")
    return " | ".join(p[-1500:] for p in parts)
