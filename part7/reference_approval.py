"""A teacher approves a student's take as the student's reference (docs/specs/my-reference.md "Teacher approval", ADR-0019).

The teacher may approve only a take the student already sent them through ask-the-trainer (an open note request on an
entry the teacher owns). Nothing here widens who can see a take. The student decides:

- no reference yet and no earlier "no": the approval is accepted at once and sits in the student's own
  `myref/<student>/<entry>/meta.json` as `approved_by` and `approved_utc` (the student can remove it at any time);
- a reference exists, or the student once declined or removed an approval: the approval waits as a suggestion in
  `<state>/myref_suggest/<student>/<entry>/` (`suggestion.json` and a copy of the skeleton). It changes no scoring until
  the student accepts it, and it expires after `SUGGESTION_DAYS`.

`declined.json` in the same folder lists the takes the student said no to, so a removal wins over a second approval of
the same take. Owner-only: no answer to a third person carries these files. Part 7 only picks the clip; scoring is Part 5's.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import shutil
import time
from typing import Any, Callable

from part7 import history_store, labels, my_reference

ROOT, SUGGESTION, COPY, DECLINED = "myref_suggest", "suggestion.json", "reference.json", "declined.json"
TOMBSTONES = ".forgot"  # <student>.<entry|all>: when their data was last forgotten (a late approval is refused)
SUGGESTION_DAYS, DECLINED_KEPT = 30, 20
ACCEPTED, SUGGESTED = "accepted", "suggested"
_FMT = "%Y-%m-%dT%H:%M:%SZ"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def folder(state: Path | str, student: str, entry_id: str) -> Path:
    return Path(state) / ROOT / student / entry_id


def suggestion(state: Path | str, student: str, entry_id: str) -> dict[str, Any] | None:
    """The waiting suggestion for one student and movement, or None. An expired one is removed on the way."""
    if not history_store.valid_ids(student, entry_id):
        return None
    found = history_store.read_json(folder(state, student, entry_id) / SUGGESTION)
    if not isinstance(found, dict) or not isinstance(found.get("job_id"), str) or not found.get("approved_by"):
        return None
    try:
        made = datetime.strptime(str(found.get("approved_utc")), _FMT).replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    if _now() - made > timedelta(days=SUGGESTION_DAYS):
        drop_suggestion(state, student, entry_id)
        return None
    return found


def public_suggestion(found: dict[str, Any] | None) -> dict[str, Any] | None:
    """What the student reads: the approval date and the take's date; never the teacher's id."""
    if found is None:
        return None
    return {"job_id": found["job_id"], "date": found.get("take_date", ""), "approved": str(found["approved_utc"])[:10]}


def was_declined(state: Path | str, student: str, entry_id: str, job_id: str | None = None) -> bool:
    """True when the student once declined or removed an approval of this movement (of this take, when `job_id` is given)."""
    found = history_store.read_json(folder(state, student, entry_id) / DECLINED) if history_store.valid_ids(student, entry_id) else None
    if not isinstance(found, list):
        return False
    return bool(found) if job_id is None else job_id in found


def note_declined(state: Path | str, student: str, entry_id: str, job_id: str) -> None:
    where = folder(state, student, entry_id)
    with history_store.locked(state):
        found = history_store.read_json(where / DECLINED)
        kept = [j for j in (found if isinstance(found, list) else []) if j != job_id] + [job_id]
        history_store.write_json(where / DECLINED, kept[-DECLINED_KEPT:])


def drop_suggestion(state: Path | str, student: str, entry_id: str) -> bool:
    where = folder(state, student, entry_id)
    with history_store.locked(state):
        had = (where / SUGGESTION).is_file()
        (where / SUGGESTION).unlink(missing_ok=True)
        (where / COPY).unlink(missing_ok=True)
    return had


def _tombstone(state: Path | str, student: str, entry_id: str | None) -> Path:
    return Path(state) / ROOT / TOMBSTONES / f"{student}.{entry_id or 'all'}"


def _forgotten_since(state: Path | str, student: str, entry_id: str, since: float) -> bool:
    """True when the student's data (or this movement) was forgotten at or after `since`."""
    for path in (_tombstone(state, student, None), _tombstone(state, student, entry_id)):
        found = history_store.read_json(path)
        if isinstance(found, dict) and isinstance(found.get("at"), (int, float)) and found["at"] >= since:
            return True
    return False


def approve(state: Path | str, student: str, entry_id: str, job_id: str, take_date: str, data: bytes, teacher: str,
            teacher_note: bool = False, since: float = 0.0, still_allowed: Callable[[], bool] | None = None) -> str | None:
    """Record the teacher's approval; "accepted" (it became the reference), "suggested" (it waits for the student) or None
    (refused: `still_allowed` said no, or the student's data was forgotten after `since`, the time the caller began its checks).

    The decision and the write happen under one lock, so a reference the student sets meanwhile is seen, not overwritten,
    and a withdrawn request, a deleted take or a deleted account never ends with a copy left behind."""
    stamp = _now().strftime(_FMT)
    where = folder(state, student, entry_id)
    with history_store.locked(state):
        if (still_allowed is not None and not still_allowed()) or _forgotten_since(state, student, entry_id, since):
            return None
        current = my_reference.meta(state, student, entry_id)
        if current and current["state"] == "ok" and current["job_id"] == job_id and current.get("approved_by") == teacher:
            return ACCEPTED  # the same approval again changes nothing
        if (current and current["state"] == "ok") or was_declined(state, student, entry_id):
            where.mkdir(parents=True, exist_ok=True)
            (where / COPY).write_bytes(data)  # the record is written last, so a half copy never reads as a suggestion
            history_store.write_json(where / SUGGESTION, {"job_id": job_id, "take_date": take_date, "approved_by": teacher,
                                                         "approved_utc": stamp, "teacher_note": teacher_note})
            return SUGGESTED
        doc = {"state": "ok", "job_id": job_id, "entry_id": entry_id, "take_date": take_date, "set_utc": stamp,
               "teacher_note": teacher_note, "approved_by": teacher, "approved_utc": stamp}
        my_reference.write_unlocked(state, student, entry_id, doc, data)
        return ACCEPTED


def accept(state: Path | str, student: str, entry_id: str) -> dict[str, Any] | None:
    """The student accepts the waiting suggestion: it replaces their reference. The new reference record, or None."""
    found = suggestion(state, student, entry_id)
    if found is None:
        return None
    try:
        data = (folder(state, student, entry_id) / COPY).read_bytes()
    except OSError:
        drop_suggestion(state, student, entry_id)
        return None
    made = my_reference.set_reference(state, student, entry_id, found["job_id"], found.get("take_date", ""), data,
                                      bool(found.get("teacher_note")), {"approved_by": found["approved_by"], "approved_utc": found["approved_utc"]})
    drop_suggestion(state, student, entry_id)
    return made


def decline(state: Path | str, student: str, entry_id: str) -> bool:
    """The student declines the waiting suggestion; the same take is not suggested again."""
    found = suggestion(state, student, entry_id)
    if found is None:
        return False
    note_declined(state, student, entry_id, found["job_id"])
    drop_suggestion(state, student, entry_id)
    return True


def take_deleted(state: Path | str, job_id: str) -> int:
    """The take `job_id` was deleted: a waiting suggestion made from it goes. The number removed."""
    base, count = Path(state) / ROOT, 0
    if not isinstance(job_id, str) or not history_store.JOB_ID_RE.match(job_id) or not base.is_dir():
        return 0
    for path in base.glob("*/*/" + SUGGESTION):
        found = history_store.read_json(path)
        if isinstance(found, dict) and found.get("job_id") == job_id:
            count += int(drop_suggestion(state, path.parent.parent.name, path.parent.name))
    return count


def forget(state: Path | str, user_id: str, entry_id: str | None = None) -> int:
    """The account (or one movement) is forgotten. As a student: every suggestion and "no" of theirs goes. As a teacher
    (whole account only): their waiting suggestions go and the approval is taken off references they approved, which stay
    the student's own. The number of records changed."""
    if not history_store.valid_ids(user_id, entry_id if entry_id is not None else "x"):
        return 0
    base = Path(state) / ROOT
    changed = 0
    with history_store.locked(state):
        history_store.write_json(_tombstone(state, user_id, entry_id), {"at": time.time()})  # an approval that began earlier is refused
        mine = base / user_id
        if entry_id is not None:
            changed += int((mine / entry_id).is_dir())
            shutil.rmtree(mine / entry_id, ignore_errors=True)
            return changed
        changed += sum(1 for p in mine.iterdir() if p.is_dir()) if mine.is_dir() else 0
        shutil.rmtree(mine, ignore_errors=True)
        for path in base.glob("*/*/" + SUGGESTION) if base.is_dir() else []:
            found = history_store.read_json(path)
            if isinstance(found, dict) and found.get("approved_by") == user_id:
                path.unlink(missing_ok=True)
                (path.parent / COPY).unlink(missing_ok=True)
                changed += 1
        for path in (Path(state) / my_reference.ROOT).glob("*/*/" + my_reference.META_NAME):
            found = history_store.read_json(path)
            if isinstance(found, dict) and found.get("approved_by") == user_id:
                history_store.write_json(path, {k: v for k, v in found.items() if k not in ("approved_by", "approved_utc")})
                changed += 1
    return changed


def _rows(state: Path | str) -> list[tuple[str, str, str, dict[str, Any]]]:
    """Every approval on disk as (student, entry, state, record): accepted ones and waiting suggestions."""
    out = []
    for path in sorted((Path(state) / my_reference.ROOT).glob("*/*/" + my_reference.META_NAME)):
        found = my_reference.meta(state, path.parent.parent.name, path.parent.name)
        if found and found["state"] == "ok" and found.get("approved_by"):
            out.append((path.parent.parent.name, path.parent.name, ACCEPTED, found))
    for path in sorted((Path(state) / ROOT).glob("*/*/" + SUGGESTION)):
        found = suggestion(state, path.parent.parent.name, path.parent.name)
        if found:
            out.append((path.parent.parent.name, path.parent.name, SUGGESTED, found))
    return out


def export_rows(ctx: Any) -> list[dict[str, Any]]:
    """The `reference_approvals` section of "download my data", for both people. A student's row says which take their
    teacher approved and when; a teacher's row says which approval they made. Neither names the other person, and no movement data."""
    out = []
    for student, entry, state, found in _rows(ctx.state):
        role = "student" if student == ctx.user_id else "teacher" if found.get("approved_by") == ctx.user_id else None
        if role is None or not labels.ENTRY_ID_RE.match(entry):
            continue
        out.append({"role": role, "movement": ctx.movement(entry), "state": state, "take_date": found.get("take_date"),
                    "approved": found.get("approved_utc"),
                    "note": "Simon keeps the movement data of this take until the reference is removed or the student's account is deleted."
                    if role == "student" else "You approved a take that a student sent you. Simon keeps no movement data of it for you."})
    return out
