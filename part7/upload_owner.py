"""Who may use a raw upload, and which uploads and people jobs an account made (docs/specs/prod-data.md "Uploads and
people jobs", go-live findings P-N1 and DI-N1).

`POST api/uploads` writes `uploads/<id>/owner.json` = `{"user": <user id or "">}` beside the video. A take, a people
job or a group submit names an upload by its id; `may_use` lets only the account that uploaded it signed in use it,
so an upload id read anywhere never makes another person's movement. An upload made signed out keeps its id as its
key, as an anonymous take does (identity.md). An upload without the file is refused (fails closed).

A people job and a group take keep their owner in `_people_owner` (people_routes.py). `jobs_of` and `uploads_of` name what an
account made outside its takes, so Delete my data removes them and the export ZIP holds them.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from part7 import job_lookup, jobs

FILE = "owner.json"
USER_FIELD = "user"
PEOPLE_OWNER = "_people_owner"  # jobs.JobQueue keeps "_" fields in job.json and leaves them out of every view
UNKNOWN = object()  # a people record whose owner cannot be read


def record(folder: Path, user_id: str | None) -> None:
    """Bind the upload in `folder` to `user_id` (None or "": made signed out); a 0600 file, written atomically."""
    tmp = folder / f".{FILE}.tmp"
    tmp.write_text(json.dumps({USER_FIELD: user_id or ""}), encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, folder / FILE)


def owner(folder: Path) -> str | None:
    """The user id the upload is bound to, "" for one made signed out, None when the file is missing or unreadable."""
    try:
        doc = json.loads((folder / FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    found = doc.get(USER_FIELD) if isinstance(doc, dict) else None
    return found if isinstance(found, str) else None


def may_use(folder: Path, user_id: str | None) -> bool:
    """True when the caller (`user_id`, None signed out) may start work from the upload in `folder`."""
    found = owner(folder)
    return found is not None and (found == "" or found == user_id)


def people_owner(queue: Any, job_id: str, kinds: tuple[str, ...] = ("people", "group")) -> Any:
    """The owner a people job (or a group take, through its people job) was made by: a user id, "" signed out, None for
    any other job, UNKNOWN for a people record without a readable owner. A group record written before it kept the
    field takes its people job's owner; when that job is gone or is not a people job it is UNKNOWN (S-R1)."""
    doc = job_lookup.read_json(queue.job_dir(job_id) / "job.json")
    kind = doc.get("kind") if isinstance(doc, dict) else None
    if kind not in kinds:
        return None
    found = doc.get(PEOPLE_OWNER)
    if isinstance(found, str):
        return found
    source = doc.get("people_job") if kind == "group" else None
    if not isinstance(source, str) or not jobs.JOB_ID_RE.match(source):
        return UNKNOWN
    via = people_owner(queue, source, ("people",))  # one step, never to another group record
    return via if isinstance(via, str) else UNKNOWN  # fails closed


def jobs_of(state: Path | str, user_id: str) -> dict[str, str]:
    """`{job_id: kind}` of the people jobs and group takes `user_id` made signed in, whose folders are still kept.
    They have no takes row, so Delete my data and the export find them here."""
    folder = Path(state) / "jobs"
    if not user_id or not folder.is_dir():
        return {}
    out = {}
    for child in sorted(folder.iterdir()):
        if not jobs.JOB_ID_RE.match(child.name) or child.is_symlink():
            continue
        doc = job_lookup.read_json(child / "job.json")
        if isinstance(doc, dict) and doc.get("kind") in ("people", "group") and doc.get(PEOPLE_OWNER) == user_id:
            out[child.name] = str(doc["kind"])
    return out


def uploads_of(uploads: Path, user_id: str) -> list[str]:
    """The upload ids bound to `user_id`, still held."""
    if not user_id or not uploads.is_dir():
        return []
    return [c.name for c in sorted(uploads.iterdir())
            if jobs.UPLOAD_ID_RE.match(c.name) and not c.is_symlink() and c.is_dir() and owner(c) == user_id]
