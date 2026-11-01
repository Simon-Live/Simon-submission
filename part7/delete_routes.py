"""`POST api/jobs/<id>/delete`: remove a take's clip, tracks and analysis (TICKET-159); `server.py` calls `handle` first.

A take is a finished follow, group or trainer job. Its folder holds the follower clip, the tracks and `analysis.json`, so the
folder goes; so do the raw upload it came from (when the record names it), the people job that cut the clip, and any
challenge board entry made from the take, and the saved Idempotency-Key answers that name it (idempotency.py). There are no accounts: the job id is the visitor's private key, as in
challenges.md "Privacy", and it is the only authorisation (the result link contains it). A queued or running job is
refused (409), because its worker still writes into the folder; so is a take whose export is being made (R3). A
raw upload or people job that another queued or running job still uses is kept and named in `kept`; so is one that
another finished job names (its models-used page reads the people job's tracks), unless the deleted take is a group
take and the other finished job is also a group take (a follow or trainer take from the same people job keeps them). A take whose spoken cue is being made is refused (409, R-d).

A trainer take (TICKET-111) holds the trainer's recording (which has sound), the job folder with the 3D meshes, and
the movement it made in the catalog. The catalog entry is a copy made by Part 6 `import` (video without sound,
keyframes, skeleton, animation) and names no Part 7 file, so by default it stays: only the files of the take go, and
the spoken-cue transcripts (`narration.json`, made from the voice) leave the entry. The body `{"remove_entry": true}`
removes the movement too (its folder and labels). The entry is kept, and named in `kept`, when it is a shipped
sample or a challenge uses it. A follower's result of that movement then shows no 3D trainer.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import shutil
from typing import Any

from part7 import applog, auth, challenges, export_routes, history_store, jobs, labels, narration, speech

TAKE_KINDS = ("follow", "group", "trainer")
MSG_NO_JOB = "This take was not found. It may already be deleted."
MSG_BUSY = "This take is still being analysed. Delete it when it has finished."
MSG_EXPORTING = "An export is being made. Delete this take when it has finished."
MSG_SPEAKING = "A spoken cue is being made."
MSG_NOT_TAKE = "Only a take can be deleted here."


def _drop_upload(uploads: Path, upload_id: Any) -> bool:
    folder = uploads / upload_id if isinstance(upload_id, str) and jobs.UPLOAD_ID_RE.match(upload_id) else None
    if folder is None or folder.is_symlink() or not folder.is_dir():
        return False
    shutil.rmtree(folder, ignore_errors=True)
    return True


def _entry_folder(app: Any, job: dict[str, Any]) -> tuple[str, Path] | None:
    """`(entry id, folder)` of the catalog entry a trainer job made, or None when it has none on disk."""
    result = job.get("result")
    entry_id = job.get("entry_id") or (result.get("entry_id") if isinstance(result, dict) else None)
    if not isinstance(entry_id, str) or not labels.ENTRY_ID_RE.match(entry_id):
        return None
    folder = Path(app.child.catalog_dir) / entry_id
    return (entry_id, folder) if folder.is_dir() and not folder.is_symlink() else None


def _is_sample(folder: Path) -> bool:
    """True unless the entry's manifest reads and says it is not a shipped sample (when unsure, the entry stays)."""
    try:
        return json.loads((folder / "manifest.json").read_text(encoding="utf-8")).get("files_source") == "fixture"
    except (OSError, ValueError, AttributeError):
        return True


def _drop_entry(app: Any, entry_id: str, folder: Path) -> bool:
    """Remove the entry folder (renamed to an unlisted dot folder first, as Part 6 does) and its labels."""
    doomed = folder.parent / f".evict-{entry_id}"
    shutil.rmtree(doomed, ignore_errors=True)
    try:
        os.rename(folder, doomed)
    except OSError:
        return False
    shutil.rmtree(doomed, ignore_errors=True)
    (Path(app.state) / "labels" / f"{entry_id}.json").unlink(missing_ok=True)
    return True


def _trainer_entry(app: Any, job: dict[str, Any], remove_entry: bool, removed: list[str], kept: list[str]) -> None:
    """The catalog side of deleting a trainer take: the transcripts go; the movement goes only on request and when safe."""
    found = _entry_folder(app, job)
    if found is None:
        return
    entry_id, folder = found
    if remove_entry:
        if _is_sample(folder) or challenges.list_all(app.state, entry_id=entry_id):
            kept.append("entry")
        elif _drop_entry(app, entry_id, folder):
            removed.append("entry")
            return
        else:
            kept.append("entry")
    transcript = folder / narration.FILE_NAME
    if transcript.is_file() and not transcript.is_symlink():  # the cues were made from the trainer's voice
        transcript.unlink(missing_ok=True)
        removed.append("narration")


def delete_take(app: Any, job_id: str, remove_entry: bool = False) -> tuple[int, dict[str, Any]]:
    """`(status, body)` for deleting `job_id`; the body is `{deleted, removed}` or `{error}`.

    `remove_entry` only matters for a trainer take: it also removes the catalog movement the take made.
    """
    job = app.queue.get(job_id) if jobs.JOB_ID_RE.match(job_id) else None
    if job is None:
        return 404, {"error": MSG_NO_JOB}
    if job.get("kind") not in TAKE_KINDS:
        return 400, {"error": MSG_NOT_TAKE}
    if job.get("status") not in ("done", "failed"):
        return 409, {"error": MSG_BUSY}
    if export_routes.render_active(job_id):
        return 409, {"error": MSG_EXPORTING}
    if speech.active_in(app.queue.job_dir(job_id)):  # the synthesis thread writes into the job folder
        return 409, {"error": MSG_SPEAKING}
    removed, kept = ["job"], []
    upload_id, people_job = job.get("upload_id"), job.get("people_job")
    owner = job.get("kind") == "group"  # the group take owns its people job: a sibling's result does not keep it

    def in_use(field: str, value: str) -> bool:
        # A finished job's "models used" still reads the people job's tracks and its upload, so they stay (AC-3).
        # The group take owns its people job (and its upload) against another group take only: a finished follow or trainer take made
        # from the same people job (shared_path) still reads its tracks, so it keeps them.
        ignore = ("group", "people") if owner else ()  # the people job goes with its group take
        return app.queue.active_refs(field, value, job_id) or app.queue.finished_refs(field, value, job_id, ignore)

    if isinstance(upload_id, str) and in_use("upload_id", upload_id):
        kept.append("upload")
    elif _drop_upload(app.uploads, upload_id):
        removed.append("upload")
    # An Idempotency-Key retry (offline takes) must not be answered with the id of a take that is gone.
    app.idempotency.forget_ids([job_id, upload_id, people_job])
    if isinstance(people_job, str) and jobs.JOB_ID_RE.match(people_job):
        other = app.queue.get(people_job)
        if other is not None and other.get("kind") == "people":
            if in_use("people_job", people_job):
                kept.append("people")
            elif app.queue.forget(people_job):
                removed.append("people")
    if challenges.remove_job(app.state, job_id):
        removed.append("board")
    if job.get("kind") == "trainer":
        _trainer_entry(app, job, remove_entry, removed, kept)
    app.queue.forget(job_id)
    for hook, what in ((history_store.drop_take, "history copy"), (lambda state, job: auth.forget_job(app, job), "ownership row")):
        try:  # the take is already gone: a fault in an opt-in store must not turn an anonymous delete into a 500
            hook(app.state, job_id)  # the student's history copy and any report citing it, then the ownership row
        except Exception as exc:
            applog.log(f"delete: could not drop the {what} of {job_id}: {applog.cause(exc)}", level=logging.WARNING)
    return 200, {"deleted": True, "removed": removed, **({"kept": kept} if kept else {})}


def remove_for_account(app: Any, job_id: str) -> str:
    """`auth_routes.TAKE_REMOVER`: "removed", "busy" or "gone" for one take of a deleted account."""
    status, _ = delete_take(app, job_id)
    return "removed" if status == 200 else "busy" if status == 409 else "gone"


def handle(h: Any, method: str, route: str) -> bool:
    """Answer `jobs/<id>/delete` and return True; any other route returns False."""
    parts = route.split("/")
    if len(parts) != 3 or parts[0] != "jobs" or parts[2] != "delete":
        return False
    if method != "POST":
        h._error(405, "Method not allowed.")
        return True
    remove_entry = False
    if int(h.headers.get("Content-Length") or 0) > 0:  # a follow or group delete sends no body
        doc = h._body_json()
        if doc is None:
            return True
        remove_entry = doc.get("remove_entry") is True
    status, body = delete_take(h.app, parts[1], remove_entry)
    if "error" in body:
        h._error(status, body["error"])
    else:
        h._json(status, body)
    return True
