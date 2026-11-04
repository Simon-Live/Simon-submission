"""The age rule of every log Simon writes: a line older than KEEP_DAYS (14, the gateway's) goes (data-integrity D3, D8).

Stdlib only and free of other `part7` imports: `prod/statetool.py` loads this file by path from the release tree, so the
backup applies the same rule as the app's sweep (docs/specs/prod-data.md "Retention").

A line's time is the ISO time it starts with (`part7.log`, the job logs, `up.sh`'s `--- up.sh start <time>` lines,
the request lines of `server-<port>.log`), or an `http.server` time in brackets (`[03/Nov/2026 12:00:00]`, Part 6's
request lines). A line with no time (a traceback, a part's own output) belongs to the timed line before it. Lines before
the first timed line belong to that first timed line; a file with no timed line at all is judged by its modification
time. Trimming rewrites the file in place (same inode): the writers open their logs with O_APPEND, so after the
truncate they keep appending at the new end. A rotated copy (`part7.log.1`) left empty is removed.
"""

from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import re
import time
from typing import Iterable

KEEP_DAYS = 14
_ISO = re.compile(rb"^(?:--- up\.sh \w+ )?(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})")
_HTTP = re.compile(rb"\[(\d{2}/[A-Z][a-z]{2}/\d{4}) (\d{2}:\d{2}:\d{2})\]")
LOG_NAME = re.compile(r"^[\w.-]+\.log(?:\.\d+)?$")


def cutoff(now: float | None = None, days: int = KEEP_DAYS) -> float:
    return (time.time() if now is None else now) - days * 86400


def line_time(line: bytes) -> float | None:
    """Seconds since the epoch of a log line's own time (UTC), else None."""
    found = _ISO.match(line)
    try:
        if found:
            moment = datetime.strptime(f"{found.group(1).decode()} {found.group(2).decode()}", "%Y-%m-%d %H:%M:%S")
            return moment.replace(tzinfo=timezone.utc).timestamp()
        found = _HTTP.search(line[:200])
        if found:
            moment = datetime.strptime(f"{found.group(1).decode()} {found.group(2).decode()}", "%d/%b/%Y %H:%M:%S")
            return moment.replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        return None
    return None


def keep_lines(lines: Iterable[bytes], limit: float, untimed_at: float) -> list[bytes]:
    """The lines whose time (or the time of the timed line they belong to) is at or after `limit`."""
    out: list[bytes] = []
    leading: list[bytes] = []
    keep: bool | None = None
    for line in lines:
        at = line_time(line)
        if at is not None:
            keep = at >= limit
            if leading:
                out += leading if keep else []
                leading = []
        elif keep is None:
            leading.append(line)
            continue
        if keep:
            out.append(line)
    if leading:  # no timed line at all: the whole file is as old as its modification time
        out += leading if untimed_at >= limit else []
    return out


def trim_file(path: Path, limit: float) -> int:
    """Drop the lines of `path` older than `limit`, in place; the number of bytes removed (0 when nothing was old)."""
    try:
        with path.open("r+b") as fh:
            mtime = os.fstat(fh.fileno()).st_mtime
            data = fh.read()
            kept = b"".join(keep_lines(data.splitlines(keepends=True), limit, mtime))
            if len(kept) == len(data):
                return 0
            tail = fh.read()  # what a writer appended while the lines were read stays
            fh.seek(0)
            fh.write(kept + tail)
            fh.truncate()
    except (FileNotFoundError, IsADirectoryError, PermissionError):
        return 0
    if not kept and not tail and re.search(r"\.log\.\d+$", path.name):
        path.unlink(missing_ok=True)
    return len(data) - len(kept)


def trim_dir(folder: Path | str, limit: float) -> int:
    """`trim_file` on every log file directly in `folder` (`*.log`, `*.log.N`); the bytes removed."""
    base, gone = Path(folder), 0
    for path in sorted(base.iterdir()) if base.is_dir() else []:
        if LOG_NAME.match(path.name) and path.is_file() and not path.is_symlink():
            gone += trim_file(path, limit)
    return gone
