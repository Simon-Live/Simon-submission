"""A model-only take: "Use my 3D model instead of video" (docs/specs/model-only-take.md).

The take is analysed as always. Once `analysis.json` exists, `purge_job` removes the source video and every video or
image derived from the frames from the job folder, and `source_dropper` removes the raw upload and the people job's
media when no other job still uses them. The job record then says `video_kept: false`; absent means true.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import shutil
from typing import Any, Callable

from part7 import applog, jobs

FIELD = "video_kept"
# Video containers and image files. Tracks, poses, meshes, replay and analysis are JSON or binary and stay.
MEDIA_SUFFIXES = frozenset({".mp4", ".webm", ".mov", ".mkv", ".avi", ".m4v", ".gif",
                            ".jpg", ".jpeg", ".png", ".webp", ".bmp", ".heic"})
MSG_NO_VIDEO = "This take was kept as a 3D model only, so it has no video."


def kept(record: Any) -> bool:
    """False only for a record that says `video_kept: false`; a record without the field keeps its video."""
    return not (isinstance(record, dict) and record.get(FIELD) is False)


def requested(doc: Any) -> bool:
    """True when a request body asks for a model-only take (`model_only: true`)."""
    return isinstance(doc, dict) and doc.get("model_only") is True


def mark(raw: bytes) -> bytes:
    """A served result file with the top-level `video_kept: false` added; a file that is not a JSON object stays as is."""
    try:
        doc = json.loads(raw)
    except ValueError:
        return raw
    if not isinstance(doc, dict):
        return raw
    return json.dumps({**doc, FIELD: False}, ensure_ascii=False).encode("utf-8")


def purge_job(job_dir: Path) -> list[str]:
    """Delete every video and image under `job_dir`; return their paths relative to it.

    Walks without following links, so a link out of the folder is removed as a name and its target is untouched.
    """
    removed: list[str] = []
    for base, _dirs, names in os.walk(job_dir, followlinks=False):
        for name in names:
            path = Path(base) / name
            if path.suffix.lower() not in MEDIA_SUFFIXES:
                continue
            try:
                path.unlink()
            except OSError as exc:
                applog.log(f"model-only: could not remove {path.name}: {applog.cause(exc)}", level=logging.WARNING)
                continue
            removed.append(str(path.relative_to(job_dir)))
    return sorted(removed)


def _drop_upload(uploads: Path, upload_id: Any) -> bool:
    folder = uploads / upload_id if isinstance(upload_id, str) and jobs.UPLOAD_ID_RE.match(upload_id) else None
    if folder is None or folder.is_symlink() or not folder.is_dir():
        return False
    shutil.rmtree(folder, ignore_errors=True)
    return True


def source_dropper(queue: Any, uploads: Path, upload_id: str, people_job: str | None) -> Callable[[str], None]:
    """A function of the job id that removes the raw upload and the people job's media unless another job uses them.

    Same rule as delete_routes: a queued or running job, or a finished one, that names the upload or the people job
    keeps it. The people job's tracks stay (a finished job's "models used" page reads them); only its media go.
    """

    def in_use(field: str, value: str, job_id: str, ignore: tuple[str, ...] = ()) -> bool:
        return queue.active_refs(field, value, job_id) or queue.finished_refs(field, value, job_id, ignore)

    def drop(job_id: str) -> None:
        people_free = bool(people_job and jobs.JOB_ID_RE.match(people_job)
                           and not in_use("people_job", people_job, job_id))
        # The people job names the same upload; it goes (media only) with this take, so it does not keep the upload.
        if upload_id and not in_use("upload_id", upload_id, job_id, ("people",) if people_free else ()):
            _drop_upload(uploads, upload_id)
        if people_free:
            purge_job(queue.job_dir(str(people_job)))

    return drop
