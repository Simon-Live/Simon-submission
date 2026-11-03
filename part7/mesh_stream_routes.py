"""Owner-only routes for the follower's body while the job runs (TICKET-284; docs/specs/mesh-stream.md "Routes").

- `GET api/jobs/<id>/mesh-stream`: `{closed, stream}`. `stream` is `mesh_stream_files.snapshot` (null until the first
  frame is flushed), so the page makes no failing request while it waits.
- `GET api/results/<id>/mesh-stream/<name>`: one of `stream.json`, `head.bin`, `chunk-NNNN.bin` of that job.

Owner-only: 401 without a session; 404 for a job the caller does not own, an unknown id or a job that is not a follow job.
Closed when the job ends: once a job is not queued or running the snapshot is null and `closed` is true, and the files answer
404 (the finished mesh is served by `mesh_files`). Bounded in rate (RATE_LIMIT answers per RATE_WINDOW_S per user and job,
then 429) and in size (the manifest and chunks are small; a file over MAX_FILE_BYTES is not served).
"""

from __future__ import annotations

from typing import Any

from part7 import history_store, jobs, mesh_stream_files
from part7.auth import Limiter
from part7.auth_routes import MSG_SIGN_IN

MODEL = "SAM 3D Body"
RUNNING = ("queued", "running")
MAX_FILE_BYTES = 4_000_000
RATE_LIMIT, RATE_WINDOW_S = 20, 2.0
MSG_GONE = "This job was not found."
MSG_RATE = "Too many requests. Try again in a moment."
_limiter = Limiter(RATE_LIMIT, RATE_WINDOW_S)


def _owner(h: Any, job_id: str) -> tuple[str | None, bool]:
    """`(user, owns)`: the signed-in user id (None when signed out) and whether that user owns `job_id`."""
    auth = history_store.optional_module("part7.auth")
    user = auth.current_user(h) if auth is not None else None
    user = user if isinstance(user, str) and history_store.USER_ID_RE.match(user) else None
    return user, user is not None and history_store.owner_of(h.app.state, job_id) == user


def hint(h: Any, job: dict[str, Any]) -> dict[str, Any] | None:
    """What the job answer carries for the owner of a running follow job, so no other viewer's page ever asks."""
    if job.get("kind") != "follow" or job.get("status") not in RUNNING or not isinstance(job.get("id"), str):
        return None
    return {"url": f"api/jobs/{job['id']}/mesh-stream", "model": MODEL} if _owner(h, job["id"])[1] else None


def handle(h: Any, method: str, route: str) -> bool:
    """Answer the two routes above; False for any other route."""
    parts = route.split("/")
    snap = len(parts) == 3 and parts[0] == "jobs" and parts[2] == "mesh-stream"
    file = len(parts) == 4 and parts[0] == "results" and parts[2] == "mesh-stream"
    if not (snap or file) or method not in ("GET", "HEAD"):
        return False
    job_id = parts[1]
    user, owns = _owner(h, job_id)
    if user is None:
        h._error(401, MSG_SIGN_IN)
        return True
    job = h.app.queue.get(job_id) if owns and jobs.JOB_ID_RE.match(job_id) else None
    if job is None or job.get("kind") != "follow":
        h._error(404, MSG_GONE)
        return True
    if not _limiter.hit(f"{user}:{job_id}"):
        h._error(429, MSG_RATE)
        return True
    running = job.get("status") in RUNNING
    root = h.app.queue.job_dir(job_id).parent
    if snap:
        h._json(200, {"closed": not running, "model": MODEL, "stage": job.get("stage"),
                      "stream": mesh_stream_files.snapshot(root, job_id) if running else None})
        return True
    path = mesh_stream_files.stream_file(root, job_id, parts[3]) if running else None
    if path is None or path.stat().st_size > MAX_FILE_BYTES:
        h._error(404, MSG_GONE)
        return True
    h._send(200, path.read_bytes(), mesh_stream_files.content_type(parts[3]), {"Cache-Control": "private, no-store"})
    return True
