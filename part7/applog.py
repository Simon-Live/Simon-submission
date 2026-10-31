"""Part 7's own log: what Part 7 decided (trim, crop, fallbacks) and why a request or a job failed.

The parts' output already lands in `<job>/steps/*.log`. This log covers the glue between them, which was
silent before: one line per decision, prefixed with the job id when there is one, redacted like the step logs.
`serve` writes it to `<state>/part7.log` and to stderr; every job also gets its own `<job>/steps/part7.log`.
"""

from __future__ import annotations

import logging
from pathlib import Path

from part7 import keys

LOGGER = logging.getLogger("part7")
FORMAT = "%(asctime)s %(levelname)s %(message)s"


def setup(state: Path | str) -> Path:
    """Send the log to `<state>/part7.log` and stderr (once per process); return the file path."""
    path = Path(state) / "part7.log"
    if not any(getattr(h, "_part7", False) for h in LOGGER.handlers):
        path.parent.mkdir(parents=True, exist_ok=True)
        for handler in (logging.FileHandler(path, encoding="utf-8"), logging.StreamHandler()):
            handler.setFormatter(logging.Formatter(FORMAT))
            handler._part7 = True  # type: ignore[attr-defined]
            LOGGER.addHandler(handler)
        LOGGER.setLevel(logging.INFO)
    return path


def job_id_of(work: Path | str) -> str:
    """The job id of any folder inside `<state>/jobs/<id>/`, else the folder name."""
    p = Path(work)
    for folder in (p, *p.parents):
        if folder.parent.name == "jobs":
            return folder.name
    return p.name


def log(msg: str, job: str | None = None, job_dir: Path | str | None = None, level: int = logging.INFO) -> None:
    """Log `msg` (redacted); with `job_dir` also append it to `<job_dir>/steps/part7.log`."""
    text = keys.redact(f"job {job}: {msg}" if job else msg)
    LOGGER.log(level, text)
    if job_dir is not None:
        try:
            steps = Path(job_dir) / "steps"
            steps.mkdir(parents=True, exist_ok=True)
            with (steps / "part7.log").open("a", encoding="utf-8") as fh:
                fh.write(f"{logging.getLevelName(level)} {text}\n")
        except OSError:
            pass


def cause(exc: BaseException) -> str:
    """The exception and whatever it was raised from (`from None` hides it but keeps `__context__`), shortened."""
    parts = [f"{type(exc).__name__}: {exc}"]
    inner = exc.__cause__ or exc.__context__
    if inner is not None:
        parts.append(f"caused by {type(inner).__name__}: {inner}")
    return " | ".join(p[-1500:] for p in parts)
