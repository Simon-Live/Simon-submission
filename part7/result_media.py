"""The follower's clip of a finished job, with HTTP Range (coaching-moments.md "Follower video").

`handle(h, method, route)` answers `results/<job>/video.mp4` (follow job) and `results/<job>/<pid>/video.mp4`
(group job) and returns True; any other route returns False. The clip is the one Part 5 scored, so its clock is the
analysis `at_s` clock. Only finished jobs serve it; everything else is 404.
"""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from part7 import group, jobs

NAME = "video.mp4"
CHUNK = 256 * 1024
RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")
MSG_GONE = "This video is not available."
UNSATISFIABLE = "unsatisfiable"


def clip_path(h: Any, job_id: str, pid: str | None) -> Path | None:
    """The clip file of a finished follow job (or of person `pid` of a finished group job), else None."""
    if not jobs.JOB_ID_RE.match(job_id):
        return None
    job = h.app.queue.get(job_id)
    if not job or job.get("status") != "done":
        return None
    job_dir = h.app.queue.job_dir(job_id)
    if pid is None:
        ok = job.get("kind") == "follow"
    else:
        ok = job.get("kind") == "group" and bool(jobs.PID_RE.match(pid)) and group.person_dir(job_dir, pid).is_dir()
    path = job_dir / "work" / NAME
    return path if ok and path.is_file() and not path.is_symlink() else None


def byte_range(header: str | None, size: int) -> tuple[int, int] | str | None:
    """`(start, end)` inclusive for a single-range header; None when absent or malformed (serve it whole);
    UNSATISFIABLE when it starts past the end."""
    m = RANGE_RE.match(header.strip()) if header else None
    if not m or (m.group(1) == "" and m.group(2) == ""):
        return None
    if m.group(1) == "":  # the last N bytes
        n = int(m.group(2))
        return (max(0, size - n), size - 1) if n else UNSATISFIABLE
    start = int(m.group(1))
    end = min(int(m.group(2)), size - 1) if m.group(2) else size - 1
    if start >= size or end < start:
        return UNSATISFIABLE
    return (start, end)


def _serve(h: Any, path: Path) -> None:
    size = path.stat().st_size
    rng = byte_range(h.headers.get("Range"), size)
    if rng == UNSATISFIABLE:
        h.send_response(416)
        h.send_header("Content-Range", f"bytes */{size}")
        h.send_header("Content-Length", "0")
        h.end_headers()
        return
    start, end = rng if isinstance(rng, tuple) else (0, size - 1)
    h.send_response(206 if rng else 200)
    h.send_header("Content-Type", "video/mp4")
    h.send_header("Accept-Ranges", "bytes")
    h.send_header("Content-Length", str(end - start + 1))
    h.send_header("Cache-Control", "private, max-age=3600")
    if rng:
        h.send_header("Content-Range", f"bytes {start}-{end}/{size}")
    h.end_headers()
    if h.command == "HEAD":
        return
    left = end - start + 1
    with path.open("rb") as f:
        f.seek(start)
        while left > 0:
            block = f.read(min(CHUNK, left))
            if not block:
                break
            h.wfile.write(block)
            left -= len(block)


def handle(h: Any, method: str, route: str) -> bool:
    """Answer a follower-clip route (below `api/`); False when `route` is not one."""
    parts = route.split("/")
    if method not in ("GET", "HEAD") or parts[0] != "results" or parts[-1] != NAME or len(parts) not in (3, 4):
        return False
    path = clip_path(h, parts[1], parts[2] if len(parts) == 4 else None)
    if path is None:
        h._error(404, MSG_GONE)
    else:
        _serve(h, path)
    return True
