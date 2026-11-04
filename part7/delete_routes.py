"""`POST api/jobs/<id>/delete`: remove a take's clip, tracks and analysis (TICKET-159); `server.py` calls `handle` first.

A take is a finished follow, group or trainer job. Its folder holds the follower clip, the tracks and `analysis.json`, so the
folder goes; so do the raw upload it came from (when the record names it), the people job that cut the clip, and any
challenge board entry made from the take, and the saved Idempotency-Key answers that name it (idempotency.py). Who may
delete (`refusal`, TICKET-373): a take made signed in only from its owner's session; a featured take (the operator-named
hero, the Impact page's takes, whose ids every visitor sees) only by its signed-in owner; any other take by whoever
holds its id, as in challenges.md "Privacy" (the result link contains it). A queued or running job is
refused (409), because its worker still writes into the folder; so is a take whose export is being made (R3). A
raw upload or people job that another queued or running job still uses is kept and named in `kept`; so is one that
another finished job names (its models-used page reads the people job's tracks), unless the deleted take is a group
take and the other finished job is also a group take (a follow or trainer take from the same people job keeps them). A take whose spoken cue is being made is refused (409, R-d).

A trainer take (TICKET-111) holds the trainer's recording (which has sound), the job folder with the 3D meshes, and
the movement it made in the catalog. The catalog entry is a copy made by Part 6 `import` (video without sound,
keyframes, skeleton, animation) and names no Part 7 file, so by default it stays: only the files of the take go, and
the spoken-cue transcripts (`narration.json`, made from the voice) and the voice clips leave the entry, the sound
leaves its video (`narration_own.drop_audio`, named `sound`: a movement keeps its sound only with captions), and the kept follow ghost made from
the take's Part 2 files goes (`ghost.forget` after the queue forgets the take, named `ghost` in `removed`). The body `{"remove_entry": true}`
removes the movement too (`drop_movement`: its folder, labels, boards, programme, credit and access row). Only a
shipped sample is kept, and named in `kept`; a challenge that uses the movement goes with it (prod-data.md, LEG-C1).
A follower's result of that movement then shows no 3D trainer.

`POST api/entries/<id>/delete` removes a trainer movement after its take is gone (prod-data.md "Delete key"): from
its signed-in owner's session, or with the take's creator token in `{"creator_token": ...}` (an anonymous trainer).
`remove_entries` removes the movements of a deleted account (`account_entries`), `remove_made` its people jobs, group
takes and uploads (no takes row, DI-N1), `forget_account` the boards it made,
and `sweep_entries` enforces the retention of a movement (prod-data.md "Retention"): kept until its owner deletes it or
the owner's account goes (180 days idle, or deleted); a movement with no account goes 180 days after it was made, 7
when it was never published.

The raw upload of a take is named by the job record's `upload_id`; a trainer job made before that field was written
(data-integrity D1) names it only in its `_resume` spec, which `upload_of` reads too.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
import shutil
from typing import Any

import time

from part7 import take_access, takes_on, upload_owner  # who may delete a take (TICKET-373)
from part7 import applog, auth, challenges, config, entry_access, identity, my_reference, programme, reference_approval, export_routes, history_store, jobs, labels, muse_fix, muse_fix_routes, narration, narration_own, speech
from part7 import serverless_route  # serverless-compute.md AC-SC4: the take's objects at Modal go with it
from part7 import ghost  # the kept follow ghost goes with its trainer take (follow-ghost.md AC-7)

TAKE_KINDS = ("follow", "group", "trainer")
MSG_NO_JOB = "This take was not found. It may already be deleted."
MSG_BUSY = "This take is still being analysed. Delete it when it has finished."
MSG_EXPORTING = "An export is being made. Delete this take when it has finished."
MSG_SPEAKING = "A spoken cue is being made."
MSG_DRAWING = "A picture of you is being made. Delete this take when it has finished."
MSG_NOT_TAKE = "Only a take can be deleted here."
MSG_NOT_OWNER = "This take belongs to a signed-in account. Sign in to that account to delete it."
MSG_FEATURED = "This take is featured in the app and cannot be deleted here."
MSG_OWNER_UNKNOWN = "Deleting is not available right now. Try again in a moment."
MSG_NO_CLAIM = "This take is featured in the app, so it cannot be added to an account."
MSG_NO_ENTRY = "This movement was not found. It may already be deleted."
MSG_NOT_ENTRY_OWNER = "Only the person who recorded this movement can delete it."
MSG_SAMPLE = "This movement ships with Simon and cannot be deleted."
MSG_ENTRY_BUSY = "Someone is following this movement right now. Try again in a few minutes."
MSG_CSRF = "This request came from another site."
MSG_BAD_LENGTH = "The request has a Content-Length that is not a number."
REMOVED, SAMPLE, BUSY, GONE = "removed", "sample", "busy", "gone"


def upload_of(job: dict[str, Any], folder: Path | None = None) -> str | None:
    """The upload id a take came from: `upload_id` on the record, else the `_resume` spec's (an older trainer job).
    The queue's public view leaves `_resume` out, so with `folder` (the job folder) the stored `job.json` is read."""
    found = job.get("upload_id")
    if isinstance(found, str) and jobs.UPLOAD_ID_RE.match(found):
        return found
    stored = job if folder is None else history_store.read_json(folder / "job.json")
    spec = stored.get("_resume") if isinstance(stored, dict) else None
    found = spec.get("upload_id") if isinstance(spec, dict) else None
    return found if isinstance(found, str) and jobs.UPLOAD_ID_RE.match(found) else None


def _drop_upload(uploads: Path, upload_id: Any) -> bool:
    folder = uploads / upload_id if isinstance(upload_id, str) and jobs.UPLOAD_ID_RE.match(upload_id) else None
    if folder is None or folder.is_symlink() or not folder.is_dir():
        return False
    shutil.rmtree(folder, ignore_errors=True)
    return True


def _job_entry_id(job: dict[str, Any]) -> str | None:
    """The catalog entry id a trainer job made, or None."""
    result = job.get("result")
    entry_id = job.get("entry_id") or (result.get("entry_id") if isinstance(result, dict) else None)
    return entry_id if isinstance(entry_id, str) and labels.ENTRY_ID_RE.match(entry_id) else None


def _entry_folder(app: Any, job: dict[str, Any]) -> tuple[str, Path] | None:
    """`(entry id, folder)` of the catalog entry a trainer job made, or None when it has none on disk."""
    entry_id = _job_entry_id(job)
    if entry_id is None:
        return None
    folder = Path(app.child.catalog_dir) / entry_id
    return (entry_id, folder) if folder.is_dir() and not folder.is_symlink() else None


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
    (Path(app.state) / "labels" / "review" / f"{entry_id}.json").unlink(missing_ok=True)
    labels.set_floor_work(app.state, entry_id, False)
    return True


def _forget_entry(app: Any, entry_id: str) -> None:
    """What Part 7 keeps about a movement besides its folder: boards (sponsored too), programme, credit, notes, rows."""
    challenges.remove_entry(app.state, entry_id)
    programme.remove(app.state, entry_id)
    entry_access.drop(app.state, entry_id)
    if identity.db_path(app.state).is_file():
        auth.identity(app).drop_entry(entry_id)


def drop_movement(app: Any, entry_id: str) -> str:
    """Delete the movement `entry_id` and every public copy of it: "removed", "sample" (kept), "busy" (a follow of it
    is queued or running) or "gone" (no such folder; what Part 7 kept about it still goes)."""
    if not labels.ENTRY_ID_RE.match(entry_id):
        return GONE
    folder = Path(app.child.catalog_dir) / entry_id
    if folder.is_dir() and not folder.is_symlink():
        if entry_access.shipped_sample(app.child.catalog_dir, entry_id):  # an unreadable manifest is no sample
            return SAMPLE
        if app.queue.active_refs("entry_id", entry_id) or not _drop_entry(app, entry_id, folder):
            return BUSY
        _forget_entry(app, entry_id)
        return REMOVED
    _forget_entry(app, entry_id)
    return GONE


def _trainer_entry(app: Any, job: dict[str, Any], remove_entry: bool, removed: list[str], kept: list[str]) -> None:
    """The catalog side of deleting a trainer take: the transcripts go; the movement goes on request (not a sample)."""
    found = _entry_folder(app, job)
    if found is None:
        return
    entry_id, folder = found
    if remove_entry:
        if drop_movement(app, entry_id) == REMOVED:  # drop_movement keeps a shipped sample (SAMPLE)
            removed.append("entry")
            return
        kept.append("entry")
    transcript = folder / narration.FILE_NAME
    if transcript.is_file() and not transcript.is_symlink():  # the cues were made from the trainer's voice
        transcript.unlink(missing_ok=True)
        shutil.rmtree(folder / narration.CLIPS_DIR, ignore_errors=True)  # the cut audio is the same voice
        removed.append("narration")
        if narration_own.drop_audio(folder, job.get("id")):  # the voice goes from the video too: no sound without captions
            removed.append("sound")


def delete_take(app: Any, job_id: str, remove_entry: bool = False) -> tuple[int, dict[str, Any]]:
    """`(status, body)` for deleting `job_id`; the body is `{deleted, removed}` or `{error}`.

    `remove_entry` only matters for a trainer take: it also removes the catalog movement the take made.
    """
    job = app.queue.get(job_id) if jobs.JOB_ID_RE.match(job_id) else None
    if job is None:
        # The 7-day sweep forgets the job, not its board entry: the score must still go (challenges.md "Integrity").
        gone = jobs.JOB_ID_RE.match(job_id) and challenges.remove_job(app.state, job_id)
        return (200, {"deleted": True, "removed": ["board"]}) if gone else (404, {"error": MSG_NO_JOB})
    if job.get("kind") not in TAKE_KINDS:
        return 400, {"error": MSG_NOT_TAKE}
    if job.get("status") not in ("done", "failed"):
        return 409, {"error": MSG_BUSY}
    if export_routes.render_active(job_id):
        return 409, {"error": MSG_EXPORTING}
    if speech.active_in(app.queue.job_dir(job_id)):  # the synthesis thread writes into the job folder
        return 409, {"error": MSG_SPEAKING}
    if muse_fix_routes.active(job_id):  # the worker writes into work/muse-fix of this job (TICKET-280)
        return 409, {"error": MSG_DRAWING}
    removed, kept = ["job"], []
    upload_id, people_job = upload_of(job, app.queue.job_dir(job_id)), job.get("people_job")
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
    if muse_fix.delete(app.queue.job_dir(job_id)):  # the corrected-pose picture and referee records go with the take
        removed.append("muse-fix")
    if challenges.remove_job(app.state, job_id):
        removed.append("board")
    if job.get("kind") == "trainer":
        _trainer_entry(app, job, remove_entry, removed, kept)
    app.queue.forget(job_id)
    # TICKET-374 R-a: the kept ghost goes only after the queue has forgotten the take, so a
    # concurrent ghost GET or sweep cannot re-save a copy from a take that is being deleted.
    ghost_entry = _job_entry_id(job) if job.get("kind") == "trainer" else None
    if ghost_entry is not None:
        try:
            if ghost.forget(app.state, ghost_entry, job_id):  # made from the take's own Part 2 files, so it leaves with them
                removed.append("ghost")
        except Exception as exc:
            applog.log(f"delete: could not drop the kept ghost of {job_id}: {applog.cause(exc)}", level=logging.WARNING)
    serverless_route.forget_job(app.state, job_id)
    if isinstance(people_job, str) and "people" in removed:
        serverless_route.forget_job(app.state, people_job)
    for hook, what in ((history_store.drop_take, "history copy"), (my_reference.take_deleted, "own reference"), (reference_approval.take_deleted, "reference approval"),(lambda state, job: auth.forget_job(app, job), "ownership row")):
        try:  # the take is already gone: a fault in an opt-in store must not turn an anonymous delete into a 500
            hook(app.state, job_id)  # the student's history copy and any report citing it, then the ownership row
        except Exception as exc:
            applog.log(f"delete: could not drop the {what} of {job_id}: {applog.cause(exc)}", level=logging.WARNING)
    return 200, {"deleted": True, "removed": removed, **({"kept": kept} if kept else {})}


def featured(app: Any) -> set[str]:
    """Job ids every visitor is shown (take_access.featured, which holds every id ever named hero): holding one proves
    nothing, and neither does a claim made with one (`auth_routes._claim` refuses them)."""
    return take_access.featured(app)


def made_by(app: Any, job_id: str, user_id: str | None) -> bool:
    """True when `user_id` made `job_id` signed in (ownership `via` "submit"); a claim, no user or a store fault is False."""
    if not user_id:
        return False
    try:
        return any(t["job_id"] == job_id and t["via"] == "submit" for t in auth.identity(app).takes_of(user_id))
    except Exception as exc:  # noqa: BLE001  an unreadable store never hands over a featured take
        applog.log(f"delete: could not read how {job_id} is owned: {applog.cause(exc)}", level=logging.WARNING)
        return False


def _session_user(h: Any) -> Any:
    """The signed-in user id, None when nobody is, or `takes_on.UNKNOWN` when the session store cannot answer (unlike
    `auth.current_user`, which reads a fault as anonymous)."""
    sid = auth.sid_from(h)
    if sid is None or not identity.db_path(h.app.state).is_file():
        return None
    try:
        return auth.identity(h.app).session_user(sid)
    except Exception as exc:  # noqa: BLE001
        applog.log(f"delete: session lookup failed ({type(exc).__name__})", level=logging.WARNING)
        return takes_on.UNKNOWN


def refusal(h: Any, job_id: str) -> tuple[int, str] | None:
    """`(status, message)` when this caller may not delete `job_id`, else None (TICKET-373).

    A featured take: only the person who made it signed in (a claim never counts). A take made signed in or claimed:
    only its owner's session. Any other take keeps the job id as its key (identity.md: delete by job id works signed
    out), unless the store cannot say who owns it: then nobody, for now (503, fails closed). An id the 7-day sweep forgot
    keeps its account's rule (a score it left on a board is the account's); an unowned unknown id is left to `delete_take` (404)."""
    if not jobs.JOB_ID_RE.match(job_id):
        return None
    known = h.app.queue.get(job_id) is not None
    owner = takes_on.owner(h.app, job_id)
    if owner is takes_on.UNKNOWN:
        return 503, MSG_OWNER_UNKNOWN
    if owner is None and not known:
        return None  # a take the sweep forgot, owned by nobody: its id is its key (delete_take answers 404 or takes its board score off)
    if owner is None:  # a group take has no takes row: its record names who made it (go-live P-N1)
        made = upload_owner.people_owner(h.app.queue, job_id)
        if made is upload_owner.UNKNOWN:
            return 403, MSG_NOT_OWNER
        owner = made or None
    user = _session_user(h) if owner is not None else None
    if user is takes_on.UNKNOWN:
        return 503, MSG_OWNER_UNKNOWN  # a failed session lookup is not a stranger's session (TICKET-374 R8)
    if job_id in featured(h.app):
        return None if user == owner and made_by(h.app, job_id, user) else (403, MSG_FEATURED)
    return (403, MSG_NOT_OWNER) if owner is not None and user != owner else None


def remove_for_account(app: Any, job_id: str) -> str:
    """`auth_routes.TAKE_REMOVER`: "removed", "busy" or "gone" for one take of a deleted account.

    A featured take the account only claimed stays ("gone": not counted as removed); the account's ownership row goes
    with the account."""
    if job_id in featured(app) and not made_by(app, job_id, auth.job_owner(app, job_id)):
        return "gone"
    status, _ = delete_take(app, job_id)
    return "removed" if status == 200 else "busy" if status == 409 else "gone"


def account_entries(app: Any, user_id: str) -> list[str]:
    """Every movement `user_id` owns: the identity store's rows and the access rows that outlive a deleted take."""
    ids = list(entry_access.owned_by(app.state, user_id))
    if identity.db_path(app.state).is_file():
        ids += [e["entry_id"] for e in auth.identity(app).entries_of(user_id)]
    return list(dict.fromkeys(ids))


def remove_entries(app: Any, entry_ids: list[str]) -> dict[str, list[str]]:
    """`{removed, kept, busy}` movement ids after deleting each of `entry_ids` (an account's, APP-H4, LEG-C2)."""
    out: dict[str, list[str]] = {"removed": [], "kept": [], "busy": []}
    for entry_id in entry_ids:
        outcome = drop_movement(app, entry_id)
        out["busy" if outcome == BUSY else "kept" if outcome == SAMPLE else "removed"].append(entry_id)
    return out


def account_jobs(app: Any, user_id: str) -> tuple[dict[str, str], list[str]]:
    """The people jobs and group takes `user_id` made (no takes row, upload_owner.jobs_of) and those still queued or
    running, which keep Delete my data from starting (DI-N1)."""
    made = upload_owner.jobs_of(app.state, user_id)
    return made, [j for j in made if (app.queue.get(j) or {}).get("status") in ("queued", "running")]


def remove_made(app: Any, user_id: str, made: dict[str, str]) -> None:
    """Delete my data, after the takes: the account's group takes (with their people job and upload), its other
    people jobs (clip, pictures of each person, tracks, record) and every upload still bound to it (DI-N1)."""
    for job_id in [j for j, kind in made.items() if kind == "group"]:
        delete_take(app, job_id)
    for job_id in [j for j, kind in made.items() if kind == "people"]:
        app.queue.forget(job_id)
        serverless_route.forget_job(app.state, job_id)
    held = upload_owner.uploads_of(app.uploads, user_id)
    for upload_id in held:
        _drop_upload(app.uploads, upload_id)
    app.idempotency.forget_ids([*made, *held])


def forget_account(app: Any, user_id: str, job_ids: Any = ()) -> int:
    """What Delete my data removes besides takes and movements: the account's scores on every board and the boards it
    made (deleted when empty, else kept under a neutral name, data-integrity D7). `job_ids` are its takes, for rows stamped
    with neither `owner` nor `poster`. Returns how many boards went or changed."""
    done = challenges.remove_account(app.state, user_id, job_ids)
    return done["removed"] + done["anonymised"]


def _account_gone(app: Any, owner: str) -> bool:
    """True when the identity store says `owner` has no account any more; False when it cannot say (the movement stays)."""
    if not identity.db_path(app.state).is_file():
        return False
    try:
        return auth.identity(app).user(owner) is None
    except Exception as exc:  # noqa: BLE001  an unreadable store never deletes a movement
        applog.log(f"entries: could not read the owner of a movement: {applog.cause(exc)}", level=logging.WARNING)
        return False


def expired(app: Any, row: dict[str, Any], now: float) -> bool:
    """The retention rule of one trainer movement (prod-data.md "Retention", data-integrity D3). Owned: kept while the
    account exists (the account itself goes after 180 days idle, with its movements). Not owned: 7 days unpublished,
    180 days published, from `created_at`."""
    owner = row.get("owner")
    if owner:
        return _account_gone(app, str(owner))
    age = now - float(row.get("created_at") or now)
    days = config.RETENTION_DAYS if row.get("published") is False else identity.ACCOUNT_IDLE_S // 86400
    return age > days * 86400


def _saving(row: dict[str, Any], now: float) -> bool:
    """True while a row is younger than Part 6's import timeout: the save it was reserved for may still be running."""
    made = row.get("created_at")
    return isinstance(made, (int, float)) and now - made < config.TIMEOUTS["6"]


def sweep_entries(app: Any, now: float | None = None) -> int:
    """The retention of trainer movements (`expired`): an access row whose folder is gone goes; a movement past its
    rule goes whole (`drop_movement`; a shipped sample stays). Returns how many movements went."""
    now = time.time() if now is None else now
    gone = 0
    for row in entry_access.rows(app.state):
        entry_id = str(row.get("entry_id") or "")
        if not (Path(app.child.catalog_dir) / entry_id).is_dir():
            if _saving(row, now):
                continue  # residual 3: a row reserved before the Part 6 save (W-N1); its folder is still being written
            entry_access.drop(app.state, entry_id)
            continue
        if expired(app, row, now):
            gone += drop_movement(app, entry_id) == REMOVED
    # PM-R10: a folder saved after its reserved row was undone goes past the save window; no other folder without a row
    for entry_id in entry_access.orphans(app.state, app.child.catalog_dir, now, config.TIMEOUTS["6"]):
        result = drop_movement(app, entry_id)
        gone += result == REMOVED
        if result != BUSY:
            entry_access.forget_undone(app.state, entry_id)
    return gone


def entry_refusal(h: Any, entry_id: str, token: Any) -> tuple[int, str] | None:
    """`(status, message)` when this caller may not delete the movement, else None: its signed-in owner, or the holder
    of the creator token of the trainer take that made it. 404 when nothing of the movement is known."""
    row = entry_access.get(h.app.state, entry_id)
    user = auth.current_user(h)
    owner = auth.identity(h.app).entry_owner(entry_id) if user and identity.db_path(h.app.state).is_file() else None
    if user and ((row and row.get("owner") == user) or (owner and owner[0] == user)):
        return None
    if row is not None and entry_access.holds_key(h.app.state, row, token):
        return None
    if row is None and owner is None and not (Path(h.app.child.catalog_dir) / entry_id).is_dir():
        return 404, MSG_NO_ENTRY
    return 403, MSG_NOT_ENTRY_OWNER


def _optional_body(h: Any) -> dict[str, Any] | None:
    """The JSON body, `{}` for none, or None after answering 400: a malformed Content-Length is the client's error,
    never a crash (app-surface R2)."""
    try:
        length = int(h.headers.get("Content-Length") or 0)
    except ValueError:
        length = -1
    if length < 0:
        h.close_connection = True  # the body's end is unknown: it must not be read as the next request
        h._error(400, MSG_BAD_LENGTH)
        return None
    return h._body_json() if length > 0 else {}


def _entry_delete(h: Any, entry_id: str) -> None:
    if not auth.origin_ok(h):  # a session acts here, so the sign-in routes' CSRF guard applies
        return h._error(403, MSG_CSRF)
    doc = _optional_body(h)
    if doc is None:
        return
    if not labels.ENTRY_ID_RE.match(entry_id):
        return h._error(404, MSG_NO_ENTRY)
    refused = entry_refusal(h, entry_id, doc.get("creator_token"))
    if refused:
        return h._error(*refused)
    outcome = drop_movement(h.app, entry_id)
    if outcome == SAMPLE:
        return h._error(403, MSG_SAMPLE)
    if outcome == BUSY:
        return h._error(409, MSG_ENTRY_BUSY)
    h._json(200, {"deleted": True, "entry_id": entry_id, "removed": outcome == REMOVED})


def handle(h: Any, method: str, route: str) -> bool:
    """Answer `jobs/<id>/delete` and `entries/<id>/delete` and return True; any other route returns False."""
    parts = route.split("/")
    if len(parts) != 3 or parts[0] not in ("jobs", "entries") or parts[2] != "delete":
        return False
    if method != "POST":
        h._error(405, "Method not allowed.")
        return True
    if parts[0] == "entries":
        _entry_delete(h, parts[1])
        return True
    if not auth.origin_ok(h):  # security audit R5: a session deletes here, so the CSRF guard applies as for entries
        h._error(403, MSG_CSRF)
        return True
    doc = _optional_body(h)  # a follow or group delete sends no body
    if doc is None:
        return True
    remove_entry = doc.get("remove_entry") is True
    refused = refusal(h, parts[1])
    if refused:
        h._error(*refused)
        return True
    status, body = delete_take(h.app, parts[1], remove_entry)
    if "error" in body:
        h._error(status, body["error"])
    else:
        h._json(status, body)
    return True
