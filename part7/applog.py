"""Part 7's own log: what Part 7 decided (trim, crop, fallbacks) and why a request or a job failed.

The parts' output already lands in `<job>/steps/*.log`. This log covers the glue between them, which was
silent before: one line per decision, prefixed with the job id when there is one, redacted like the step logs.
`serve` writes it to `<state>/part7.log` and to stderr; every job also gets its own `<job>/steps/part7.log`.

An account id (`u-` and 24 hex) never reaches a log line: `pseudonym` puts `u#` and 12 hex of its sha256 in its place,
so lines of one account still match (the operator hashes a known id to find them) and a deleted account's id is not
in any log. Lines older than 14 days go with the periodic sweep (`sweep`, `log_retention.py`; data-integrity D3, D8).
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
import hashlib
import os
from pathlib import Path
import re
import threading
import time
from typing import Any

from part7 import keys, log_retention
from part7 import selfheal

LOGGER = logging.getLogger("part7")
FORMAT = "%(asctime)sZ %(levelname)s %(message)s"
MAX_BYTES = 5_000_000  # part7.log rolls to part7.log.1 .. .3 past this, so a restart never empties it
BACKUPS = 3
SERVER_LOG_DIR_ENV = "SIMON7_SERVER_LOG_DIR"  # prod/up.sh: where server-<port>.log and setup.log live, outside the state
_USER_ID = re.compile(r"\bu-[0-9a-f]{24}\b")


def utc_stamp() -> str:
    """Now as `YYYY-MM-DDTHH:MM:SSZ`, the time a log line starts with (the 14-day rule reads it, log_retention.py)."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def pseudonym(text: str) -> str:
    """`text` with every account id replaced by `u#<12 hex of its sha256>`."""
    return _USER_ID.sub(lambda m: "u#" + hashlib.sha256(m.group(0).encode("ascii")).hexdigest()[:12], text)


# A catalog movement id is the slug of the name its trainer chose (1 to 40 of a to z, 0 to 9 and single inner `-`),
# then `-` and 8 hex (Part 6 `catalog.new_id`, Part 7 `p6_catalog.new_id`). The name is personal; the 8 hex are random
# and still tell one movement from another in a log. A token of that exact form is always scrubbed, whatever made it.
_ENTRY_ID = re.compile(r"(?<![\w-])(?=[a-z0-9-]*[a-z])(?=[a-z0-9-]{1,40}-[0-9a-f]{8}(?![\w-]))"
                       r"[a-z0-9]+(?:-[a-z0-9]+)*-([0-9a-f]{8})(?![\w-])")
NAME_MARK = "<name>"


def no_names(text: str) -> str:
    """`text` with each movement id written as `<name>-<its 8 hex>` (data-integrity DI-R1)."""
    return _ENTRY_ID.sub(lambda m: f"{NAME_MARK}-{m.group(1)}", text)


_MAIL_ADDRESS = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
_PRIVATE_PATH = re.compile(r"((?:^|/)api/(?:shared|take-ar)/)[^/\s?\"]+")


def scrub(text: str) -> str:
    """What every log line goes through: no account id (`pseudonym`), no movement name (`no_names`), no mail address."""
    return _MAIL_ADDRESS.sub("<mail>", no_names(pseudonym(text)))


def safe_path(path: str) -> str:
    """A request path as a log may hold it: no query string, no share or take token (TICKET-233, D8)."""
    return _PRIVATE_PATH.sub(r"\1<token>", path.split("?", 1)[0])


def sweep(state: Path | str, now: float | None = None) -> int:
    """Apply the 14-day age rule to the logs in `state` (part7.log, part6.log and their copies) and in the server log
    folder up.sh names; the bytes removed. Holds each handler's lock while its own file is trimmed."""
    limit = log_retention.cutoff(now)
    folders = [Path(state)]
    extra = os.environ.get(SERVER_LOG_DIR_ENV, "").strip()
    if extra:
        folders.append(Path(extra))
    handlers = [h for h in LOGGER.handlers if getattr(h, "_part7", False)]
    for handler in handlers:
        handler.acquire()
    try:
        return sum(log_retention.trim_dir(folder, limit) for folder in folders)
    finally:
        for handler in handlers:
            handler.release()


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
    text = scrub(keys.redact(f"job {job}: {msg}" if job else msg))
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


def secs(value: float) -> str:
    """Seconds for a log line or note: one decimal at most, no trailing `.0` (`26.5`, `90`). TICKET-101."""
    return f"{round(float(value), 1):g}"


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
    text = scrub(keys.redact(anomaly_text(kind, job, detail, **fields)))
    LOGGER.warning(text)
    selfheal.observe_anomaly(kind, detail, fields)  # TICKET-204: a known kind marks its self-heal check
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
