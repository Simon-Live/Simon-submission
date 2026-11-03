"""HTTP routes of the split-screen export (docs/specs/export-clip.md, TICKET-153); `server.py` calls `handle`.

`POST api/jobs/<job>/export` queues a render of a finished follow job (202; 200 when it is ready already),
`GET api/jobs/<job>/export` answers the status JSON, `GET api/jobs/<job>/export.mp4` serves the clip with Range
(404 until it is ready). One render runs at a time, in a daemon thread, so the request never waits for ffmpeg.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import threading
from typing import Any

from part7 import applog, export_clip, jobs, model_only, result_media
from part7.labels import ENTRY_ID_RE

NAME_MP4, NAME_STATUS = "export.mp4", "status.json"
NOT_THERE = "This result is not available."
MSG_NOT_DONE = "This result is still being analysed."
MSG_NOT_FOLLOW = "Only a follow result can be made into a clip."
MSG_NO_VIDEO = "The video of this result is no longer available."
MSG_NO_TRAINER = "The reference video of this movement is not available."
MSG_FAILED = "The clip could not be made. Try again."
MSG_BUSY = "Another clip is being made. Try again in a minute."
MSG_INTERRUPTED = "The clip was interrupted. Try again."
ACTIVE = ("queued", "rendering")

_RENDER_ONE = threading.Lock()  # one render at a time
_STATE_LOCK = threading.Lock()
_STATE: dict[str, dict[str, Any]] = {}  # job id -> status of a render started by this process


class Refused(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status, self.message = status, message


def export_dir(h: Any, job_id: str) -> Path:
    return h.app.queue.job_dir(job_id) / "export"


def _plain_file(path: Path) -> bool:
    return path.is_file() and not path.is_symlink()


def _inputs(h: Any, job_id: str) -> tuple[Path, Path, dict[str, Any] | None, export_clip.Facts]:
    """(trainer clip, follower clip, section, facts) of a finished follow job, else `Refused`."""
    job = h.app.queue.get(job_id) if jobs.JOB_ID_RE.match(job_id) else None
    if not job:
        raise Refused(404, NOT_THERE)
    if job.get("status") != "done":
        raise Refused(409, MSG_NOT_DONE)
    if job.get("kind") != "follow":
        raise Refused(409, MSG_NOT_FOLLOW)
    if model_only.view_only(job):  # the owner shows only the 3D model: no clip of them, to anyone (model-default.md AC-MD12)
        raise Refused(404, model_only.MSG_VIEW_ONLY)
    if not model_only.kept(job):
        raise Refused(409, model_only.MSG_NO_VIDEO)
    job_dir = h.app.queue.job_dir(job_id)
    follower, analysis_file = job_dir / "work" / "video.mp4", job_dir / "work" / "follower" / "analysis.json"
    if not _plain_file(follower) or not _plain_file(analysis_file):
        raise Refused(409, MSG_NO_VIDEO)
    entry = str(job.get("entry_id") or "")
    trainer = Path(h.app.child.catalog_dir) / entry / "video.mp4"
    if not ENTRY_ID_RE.match(entry) or not _plain_file(trainer):
        raise Refused(409, MSG_NO_TRAINER)
    try:
        analysis = json.loads(analysis_file.read_text(encoding="utf-8"))
        facts = export_clip.facts_from(job, analysis if isinstance(analysis, dict) else {})
    except (OSError, ValueError):
        raise Refused(409, MSG_NO_VIDEO) from None
    except export_clip.ExportError as exc:
        raise Refused(409, exc.message) from None
    section = job.get("section") if isinstance(job.get("section"), dict) else None
    return trainer, follower, section, facts


def render_active(job_id: str) -> bool:
    """True while this process is queueing or rendering an export for `job_id` (delete refuses then)."""
    with _STATE_LOCK:
        return (_STATE.get(job_id) or {}).get("state") in ACTIVE


def _write_status(directory: Path, status: dict[str, Any]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    tmp = directory / (NAME_STATUS + ".tmp")
    tmp.write_text(json.dumps(status), encoding="utf-8")
    os.replace(tmp, directory / NAME_STATUS)


def status_of(h: Any, job_id: str) -> dict[str, Any]:
    """The export status of `job_id`: this process's render, else the record on disk, else `none`."""
    with _STATE_LOCK:
        live = _STATE.get(job_id)
    if live:
        return dict(live)
    directory = export_dir(h, job_id)
    try:
        saved = json.loads((directory / NAME_STATUS).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"state": "none"}
    if not isinstance(saved, dict):
        return {"state": "none"}
    if saved.get("state") in ACTIVE:  # written by a process that is gone
        return {"state": "failed", "message": MSG_INTERRUPTED}
    if saved.get("state") == "ready" and not _plain_file(directory / NAME_MP4):
        return {"state": "none"}
    return saved


def _set(job_id: str, directory: Path, **status: Any) -> None:
    with _STATE_LOCK:
        _STATE[job_id] = status
    _write_status(directory, status)


def _run(job_id: str, directory: Path, trainer: Path, follower: Path, section: dict[str, Any] | None,
         facts: export_clip.Facts) -> None:
    with _RENDER_ONE:
        _set(job_id, directory, state="rendering")
        try:
            seconds = export_clip.render(trainer, follower, directory / NAME_MP4, facts, section)
            size = (directory / NAME_MP4).stat().st_size
            _set(job_id, directory, state="ready", url=f"api/jobs/{job_id}/{NAME_MP4}", bytes=size,
                 duration_s=round(seconds, 2), burned=facts.as_dict())
        except export_clip.ExportError as exc:
            applog.log(f"export failed: {exc.message}", job=job_id, level=logging.WARNING)
            _set(job_id, directory, state="failed", message=MSG_FAILED)
        except Exception as exc:  # a render thread must never die silently
            applog.log(f"export crashed: {exc!r}", job=job_id, level=logging.ERROR)
            _set(job_id, directory, state="failed", message=MSG_FAILED)


def _post(h: Any, job_id: str) -> None:
    try:
        trainer, follower, section, facts = _inputs(h, job_id)
    except Refused as exc:
        return h._error(exc.status, exc.message)
    current = status_of(h, job_id)
    if current["state"] == "ready":
        return h._json(200, {"ok": True, "job": job_id, **current})
    directory = export_dir(h, job_id)
    with _STATE_LOCK:
        if (_STATE.get(job_id) or {}).get("state") in ACTIVE:
            return h._json(202, {"ok": True, "job": job_id, **_STATE[job_id]})
        if any(v.get("state") == "queued" for v in _STATE.values()):  # one render waits at most (export-clip.md)
            return h._error(429, MSG_BUSY)
        _STATE[job_id] = {"state": "queued"}
    _write_status(directory, {"state": "queued"})
    threading.Thread(target=_run, args=(job_id, directory, trainer, follower, section, facts), daemon=True,
                     name=f"export-{job_id}").start()
    h._json(202, {"ok": True, "job": job_id, "state": "queued"})


def _clip(h: Any, job_id: str) -> None:
    path = export_dir(h, job_id) / NAME_MP4
    if status_of(h, job_id).get("state") != "ready" or not _plain_file(path):
        return h._error(404, "This clip is not ready.")
    result_media.serve_file(h, path)


def handle(h: Any, method: str, route: str) -> bool:
    """Answer an export route (below `api/`); False when `route` is not one."""
    parts = route.split("/")
    if len(parts) != 3 or parts[0] != "jobs" or parts[2] not in ("export", NAME_MP4):
        return False
    job_id, what = parts[1], parts[2]
    if not jobs.JOB_ID_RE.match(job_id) or not h.app.queue.get(job_id):
        h._error(404, NOT_THERE)
    elif what == NAME_MP4 and method in ("GET", "HEAD"):
        _clip(h, job_id)
    elif what == "export" and method == "POST":
        _post(h, job_id)
    elif what == "export" and method in ("GET", "HEAD"):
        h._json(200, {"ok": True, "job": job_id, **status_of(h, job_id)})
    else:
        h._error(405, "Method not allowed.")
    return True
