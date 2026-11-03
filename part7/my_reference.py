"""My reference: a student's own correct take as the clip later takes are compared with (docs/specs/my-reference.md, ADR-0019).

One reference per person per movement, kept at `<state>/myref/<user>/<entry>/` as `reference.json` (a copy of the take's
Part 3 `follower.json`, which Part 5 reads as an expected clip) and `meta.json`. The copy outlives the 7-day job folder.
Part 7 only picks which clip goes to Part 5 as `expected`; it scores nothing. The range-of-motion check belongs to Part 5.

`choose` is the single decision point: the follow route and the restart rebuild both call it, and its `record` is stored
on the job so the result always says which reference was used.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import logging
from pathlib import Path
import shutil
from typing import Any

from part7 import applog, history_store, labels

REFERENCE_NAME, META_NAME, ROOT = "reference.json", "meta.json", "myref"
OWN, TEACHER = "own", "teacher"
WHY_DELETED, WHY_SECTION, WHY_UNUSABLE, WHY_GROUP = "reference_deleted", "section", "reference_unusable", "group"
VIEWER_KEYS = ("used", "date", "why", "approved")  # what anyone but the owner may read from a job record
OWNER_HIDDEN = ("approved_by",)  # a teacher's account id is kept on the job but never answered, even to the owner (ADR-0019)


@dataclass
class Choice:
    """What the follow job is given: the clip bytes and the record kept on the job."""

    expected: bytes
    record: dict[str, Any]
    own: bool = False


def folder(state: Path | str, user_id: str, entry_id: str) -> Path:
    return Path(state) / ROOT / user_id / entry_id


def meta(state: Path | str, user_id: str, entry_id: str) -> dict[str, Any] | None:
    """The reference record of one person and movement, or None. Its `state` is "ok" or "deleted"."""
    if not history_store.valid_ids(user_id, entry_id):
        return None
    found = history_store.read_json(folder(state, user_id, entry_id) / META_NAME)
    return found if isinstance(found, dict) and found.get("state") in ("ok", "deleted") else None


def public(found: dict[str, Any] | None) -> dict[str, Any] | None:
    """What the owner sees: the take it came from, its date and whether the teacher answered a note about it."""
    if found is None or found.get("state") != "ok":
        return None
    out = {"job_id": found["job_id"], "date": found["take_date"], "set": found["set_utc"], "teacher_note": bool(found.get("teacher_note"))}
    if found.get("approved_by"):  # a teacher approved this take (ADR-0019 "Teacher approval"); the date only, never who
        out["approved"] = str(found.get("approved_utc") or "")[:10]
    return out


def set_reference(state: Path | str, user_id: str, entry_id: str, job_id: str, take_date: str, data: bytes, teacher_note: bool,
                  extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """Make `job_id` the reference of `entry_id`, replacing any earlier one (also a "deleted" marker)."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    doc = {"state": "ok", "job_id": job_id, "entry_id": entry_id, "take_date": take_date, "set_utc": now, "teacher_note": teacher_note, **(extra or {})}
    with history_store.locked(state):
        write_unlocked(state, user_id, entry_id, doc, data)
    return doc


def write_unlocked(state: Path | str, user_id: str, entry_id: str, doc: dict[str, Any], data: bytes) -> None:
    """Write the copy and the record; the caller holds `history_store.locked` (the teacher approval decides and writes under one lock)."""
    where = folder(state, user_id, entry_id)
    where.mkdir(parents=True, exist_ok=True)
    (where / REFERENCE_NAME).write_bytes(data)  # the meta is written last, so a half copy never reads as a reference
    history_store.write_json(where / META_NAME, doc)


def approver_marker(teacher_id: str) -> str:
    """What a job record keeps of the approving teacher: a hash, so the record names no account and stays after that account is gone."""
    return "t-" + hashlib.sha256(b"simon7-approver:" + str(teacher_id).encode("utf-8")).hexdigest()[:16]


def remove(state: Path | str, user_id: str, entry_id: str) -> bool:
    """Remove the reference (or its "deleted" marker); True when there was one."""
    if meta(state, user_id, entry_id) is None:
        return False
    with history_store.locked(state):
        shutil.rmtree(folder(state, user_id, entry_id), ignore_errors=True)
    return True


def forget(state: Path | str, user_id: str, entry_id: str | None = None) -> int:
    """Remove all of a person's references (or one movement's); the number removed. Runs with the account and "forget"."""
    if not history_store.valid_ids(user_id, entry_id if entry_id is not None else "x"):
        return 0
    if entry_id is not None:
        return int(remove(state, user_id, entry_id))
    base = Path(state) / ROOT / user_id
    count = sum(1 for e in base.iterdir() if e.is_dir()) if base.is_dir() else 0
    with history_store.locked(state):
        shutil.rmtree(base, ignore_errors=True)
    return count


def take_deleted(state: Path | str, job_id: str) -> int:
    """The take `job_id` was deleted: a reference made from it becomes a "deleted" marker (the copy goes), so the next
    result says it fell back to the teacher. The number of references changed."""
    base, changed = Path(state) / ROOT, 0
    if not isinstance(job_id, str) or not history_store.JOB_ID_RE.match(job_id) or not base.is_dir():
        return 0
    with history_store.locked(state):
        for path in base.glob("*/*/" + META_NAME):
            found = history_store.read_json(path)
            if isinstance(found, dict) and found.get("job_id") == job_id and found.get("state") == "ok":
                (path.parent / REFERENCE_NAME).unlink(missing_ok=True)
                history_store.write_json(path, {**found, "state": "deleted"})
                changed += 1
    return changed


def _teacher(expected: bytes, why: str | None) -> Choice:
    return Choice(expected, {"used": TEACHER, **({"why": why} if why else {})})


def is_group(queue: Any, job: dict[str, Any]) -> bool:
    """True when a take is one person of a real group video: its people job found more than one person. The upload flow
    always runs the people step, so a one-person upload also has a `people_job` and is NOT a group. A people job that
    cannot be read is treated as a group, so a person who is not the signed-in student is never offered or scored
    against the uploader's reference."""
    people_job = job.get("people_job")
    if not people_job and not job.get("person_id"):
        return False
    from part7 import people_routes  # lazy: people_routes imports the group and quota modules
    found = people_routes.people_result(queue, people_job)
    return found is None or len(found[0].get("people") or []) > 1


def uses_own(job: Any) -> bool:
    """True when a job record says its take was compared with the student's own reference."""
    ref = job.get("reference") if isinstance(job, dict) else None
    return isinstance(ref, dict) and ref.get("used") == OWN


def visible(reference: dict[str, Any], owner: bool) -> dict[str, Any]:
    """The `reference` of a job record as a caller may read it: the owner sees all; anyone else sees which kind was used,
    its date and the fallback reason, never the id of the reference take or the teacher link (the job record is readable by id)."""
    if owner:
        return {k: v for k, v in reference.items() if k not in OWNER_HIDDEN}
    return {k: reference[k] for k in VIEWER_KEYS if k in reference}


def choose(state: Path | str, user_id: str | None, entry_id: str, teacher_expected: bytes, section: Any = None,
           grouped: bool = False) -> Choice:
    """The clip a new take of `entry_id` is compared with. Always returns a record saying which.

    The record and the copy are read under the history lock, so a replace or a delete cannot split them."""
    if grouped:  # a person of a group video is not the signed-in student
        return _teacher(teacher_expected, WHY_GROUP)
    if not user_id:
        return _teacher(teacher_expected, None)
    with history_store.locked(state):
        found = meta(state, user_id, entry_id)
        if found is None:
            return _teacher(teacher_expected, None)
        if found["state"] == "deleted":
            return _teacher(teacher_expected, WHY_DELETED)
        if section:  # a section is cut from the teacher's animation; the copy of a whole take is not cut here
            return _teacher(teacher_expected, WHY_SECTION)
        try:
            data = (folder(state, user_id, entry_id) / REFERENCE_NAME).read_bytes()
        except OSError:
            applog.log("my reference: the copy is unreadable, the teacher's clip is used", level=logging.WARNING)
            return _teacher(teacher_expected, WHY_UNUSABLE)
    record = {"used": OWN, "job_id": found["job_id"], "date": found["take_date"], "teacher_note": bool(found.get("teacher_note"))}
    if found.get("approved_by"):  # the student accepted a teacher's approval: the job records who and when (ADR-0019)
        record.update({"approved_by": approver_marker(found["approved_by"]), "approved": str(found.get("approved_utc") or "")[:10]})
    return Choice(data, record, own=True)


def export_rows(ctx: Any) -> list[dict[str, Any]]:
    """The `my_references` section of "download my data": one row per movement; the movement data stays on the server."""
    base = Path(ctx.state) / ROOT / ctx.user_id
    rows = []
    for entry in sorted(p.name for p in base.iterdir() if p.is_dir()) if base.is_dir() else []:
        found = meta(ctx.state, ctx.user_id, entry) if labels.ENTRY_ID_RE.match(entry) else None
        if found is None:
            continue
        rows.append({"entry_id": entry, "movement": ctx.movement(entry), "state": found["state"], "take_date": found["take_date"],
                     "set": found["set_utc"], "teacher_note": bool(found.get("teacher_note")),
                     "note": "Simon keeps the movement data of this take until you remove the reference or delete your account."})
    return rows
