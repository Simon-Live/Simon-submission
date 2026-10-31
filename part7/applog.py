"""Part 7's own log: what Part 7 decided (trim, crop, fallbacks) and why a request or a job failed.

The parts' output already lands in `<job>/steps/*.log`. This log covers the glue between them, which was
silent before: one line per decision, prefixed with the job id when there is one, redacted like the step logs.
`serve` writes it to `<state>/part7.log` and to stderr; every job also gets its own `<job>/steps/part7.log`.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re
import threading
import time
from typing import Any

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


def _append_job_log(text: str, job_dir: Path | str, level: int) -> None:
    try:
        steps = job_root(job_dir) / "steps"
        steps.mkdir(parents=True, exist_ok=True)
        with (steps / "part7.log").open("a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {logging.getLevelName(level)} {text}\n")
    except OSError:
        pass


def log(msg: str, job: str | None = None, job_dir: Path | str | None = None, level: int = logging.INFO) -> None:
    """Log `msg` (redacted); with `job_dir` also append it to the job's own `steps/part7.log`.

    Any folder inside `<state>/jobs/<id>/` (say `work/trainer`) means that job's `<id>/steps/part7.log`, so one
    job has one Part 7 log.
    """
    text = keys.redact(f"job {job}: {msg}" if job else msg)
    LOGGER.log(level, text)
    if job_dir is not None:
        _append_job_log(text, job_dir, level)
    if job:
        _observe(job, msg)


# ----- anomalies (TICKET-091, docs/specs/observability.md) ----------------------------------------------
_BARE = re.compile(r"^[^\s\"=]+$")
_GPU_WAIT = re.compile(r"^gpu wait ([0-9.]+) s\b")
_FACTS: dict[str, dict[str, Any]] = {}
_FACTS_LOCK = threading.Lock()
_FACTS_MAX = 200  # jobs tracked at once; a job that never ends is forgotten oldest first


def env_float(name: str, default: float) -> float:
    """A positive float from the environment, else `default` (a bad value never breaks the app)."""
    try:
        value = float(os.environ.get(name, ""))
    except ValueError:
        return default
    return value if value > 0 else default


def slow_stage_limit(stage: str) -> float:
    """Seconds after which a stage is slow: `SIMON7_SLOW_STAGE_<STAGE>_S`, else `SIMON7_SLOW_STAGE_S`, else 300."""
    return env_float(f"SIMON7_SLOW_STAGE_{stage.upper()}_S", env_float("SIMON7_SLOW_STAGE_S", 300.0))


def _value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return f"{value:.1f}"
    text = " ".join(str(value).split())
    return text if _BARE.match(text) else '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def anomaly_text(kind: str, /, job: str | None = None, detail: str = "", **fields: Any) -> str:
    """`ANOMALY <kind> [job=<id>] key=value ... [detail=<rest of line>]`; None fields are left out."""
    parts = [f"ANOMALY {kind}"]
    if job:
        parts.append(f"job={job}")
    parts += [f"{k}={_value(v)}" for k, v in fields.items() if v is not None]
    text = " ".join(parts)
    one_line = " ".join(str(detail).split())
    return f"{text} detail={one_line}" if one_line else text


def anomaly(kind: str, /, detail: str = "", job: str | None = None, job_dir: Path | str | None = None,
            **fields: Any) -> None:
    """Log one machine-readable WARNING line `ANOMALY <kind> ...` (also to the job's log with `job_dir`)."""
    text = keys.redact(anomaly_text(kind, job, detail, **fields))
    LOGGER.warning(text)
    if job_dir is not None:
        _append_job_log(text, job_dir, logging.WARNING)


def fact(job: str, key: str, value: Any) -> None:
    """Remember `key=value` about a running job for its summary line (numbers under `gpu_wait` add up)."""
    with _FACTS_LOCK:
        facts = _FACTS.setdefault(job, {})
        facts[key] = facts.get(key, 0.0) + value if key.startswith("gpu_wait") else value
        while len(_FACTS) > _FACTS_MAX:
            del _FACTS[next(iter(_FACTS))]


def pop_facts(job: str) -> dict[str, Any]:
    """The facts of a finished job (and forget them)."""
    with _FACTS_LOCK:
        return _FACTS.pop(job, {})


def _observe(job: str, msg: str) -> None:
    """Capture what the summary needs from lines other modules already log (gpu_lock's `gpu wait <s> s`)."""
    found = _GPU_WAIT.match(msg)
    if found:
        with _FACTS_LOCK:
            stage = _FACTS.get(job, {}).get("_stage")
        fact(job, "gpu_wait", float(found.group(1)))
        if stage:
            fact(job, f"gpu_wait.{stage}", float(found.group(1)))


def cause(exc: BaseException) -> str:
    """The exception and whatever it was raised from (`from None` hides it but keeps `__context__`), shortened."""
    parts = [f"{type(exc).__name__}: {exc}"]
    inner = exc.__cause__ or exc.__context__
    if inner is not None:
        parts.append(f"caused by {type(inner).__name__}: {inner}")
    return " | ".join(p[-1500:] for p in parts)
