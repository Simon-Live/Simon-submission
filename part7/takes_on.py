"""Takes on this movement (docs/specs/takes-on-movement.md, TICKET-327): the rows of `GET api/takes-on/<entry>`.

Three lists for one catalog movement, each built from stores that already exist and checked with the rules that
already exist: `auth.may_view_entry` for the movement (in the route), the identity store's job owner for every take,
private mode (`history_store.is_private`) and `my_reference` for the takes that stay with their owner. No new privacy
rule lives here; `stays_with_owner` only combines those, and the board POST refuses what it names (challenge_routes).

- `mine`: the caller's own takes, newest first. Signed in, the identity store's ownership rows; on any browser, the job
  ids the browser says it sent while signed out (a job id is the take's private key, as a result link is), kept only
  when nobody owns the job. An owner lookup that fails drops the take (fails closed).
- `shared`: scores other people posted to a challenge board of this movement that the caller may open (an invited
  board answers only to those on it), never the caller's own, never a take that stays with its owner. No job id.
- `followers`: True for the movement's signed-in owner, whose class table (teacher_routes) already lists the takes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from part7 import auth, challenge_visibility, challenges, consent_record, history_store, identity as ident, jobs, my_reference, shown_score, upload_owner

DEVICE_MAX = 20  # job ids one request may name
SHARED_MAX = 20  # rows of "shared"; the scan stops once it has them
BOARDS_MAX = 50  # boards of one movement read per request, newest first
POSTS_MAX = 400  # board posts examined per request, whatever is shown
MINE_MAX = 50
UNKNOWN = object()  # the owner lookup failed


def device_ids(raw: Any) -> list[str]:
    """The distinct, well-formed job ids of a `jobs=` query value, at most DEVICE_MAX; anything else is dropped."""
    out: list[str] = []
    for part in str(raw or "").split(","):
        if jobs.JOB_ID_RE.match(part) and part not in out:
            out.append(part)
    return out[:DEVICE_MAX]


def owner(app: Any, job_id: str) -> Any:
    """The identity store's owner of `job_id` (None: nobody), or UNKNOWN when the store cannot answer."""
    if not ident.db_path(app.state).is_file():
        return None
    try:
        return auth.identity(app).owner_of(job_id)
    except Exception:  # noqa: BLE001  any store fault: the caller drops the take
        return UNKNOWN


def keyed_by_id(app: Any, job_id: str, caller: str | None = None) -> bool:
    """True when naming `job_id` proves it is the caller's: nobody owns it, so its id is its key (identity.md). A group
    take has no takes row, so its record is read too: one made signed in answers only to that account (S-R1)."""
    if owner(app, job_id) is not None:
        return False
    made = upload_owner.people_owner(app.queue, job_id, ("group",))
    return made is not upload_owner.UNKNOWN and (not made or made == caller)


def stays_with_owner(state: Path | str, job_id: str, job: Any, owner_id: Any, entry_id: str) -> bool:
    """True for a take that is its owner's alone: private mode, scored against the owner's own reference, or kept as it."""
    if isinstance(job, dict) and (history_store.is_private(job) or my_reference.uses_own(job)):
        return True
    if owner_id is UNKNOWN:
        return True
    found = my_reference.meta(state, owner_id, entry_id) if isinstance(owner_id, str) else None
    return bool(found and found.get("job_id") == job_id)


def _scored(job_dir: Path) -> tuple[Any, Any]:
    """Score and grade of a finished take, read from its own analysis.json (never stored twice)."""
    analysis = history_store.read_json(job_dir / "work" / "follower" / "analysis.json")
    score = analysis.get("score") if isinstance(analysis, dict) else None
    value = score.get("value") if isinstance(score, dict) else None
    grade = score.get("grade") if isinstance(score, dict) else None
    ok = isinstance(value, (int, float)) and not isinstance(value, bool)
    return (value if ok else None), (grade if ok and isinstance(grade, str) else None)


def _row(h: Any, job_id: str, at: Any, kept: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """One take of mine: the job while its folder is kept, else its history copy, else an expired row."""
    job = h.app.queue.get(job_id)
    if job is not None:
        status, folder = job.get("status"), h.app.queue.job_dir(job_id)
        score, grade = _scored(folder) if status == "done" else (None, None)
        where = "result" if status == "done" else "job" if status in ("queued", "running") else "none"
        return {"job_id": job_id, "at": job.get("finished_at") or job.get("created_at") or at, "status": status, "score": score, "grade": grade,
                "shown": shown_score.of_job(folder, job) if status == "done" else None, "private": history_store.is_private(job), "open": where}
    copy = kept.get(job_id)
    if copy is not None:
        return {"job_id": job_id, "at": copy.get("at") or at, "status": "kept", "score": copy.get("score"), "grade": copy.get("grade"),
                "shown": shown_score.of_take(copy), "private": bool(copy.get("private")), "open": "history"}
    return {"job_id": job_id, "at": at, "status": "expired", "score": None, "grade": None, "shown": None, "private": False, "open": "none"}


def _unowned_take(h: Any, entry_id: str, job_id: str) -> bool:
    """True for a follow take of this movement that nobody owns (a signed-out take this browser sent)."""
    job = h.app.queue.get(job_id)
    if job is None or job.get("kind") != "follow" or job.get("entry_id") != entry_id:
        return False
    return owner(h.app, job_id) is None  # owned by anyone, or unknown, is never listed from a browser's word


def mine(h: Any, entry_id: str, user: str | None, device: list[str]) -> list[dict[str, Any]]:
    """The caller's takes of `entry_id`, newest first."""
    rows: dict[str, dict[str, Any]] = {}
    kept: dict[str, dict[str, Any]] = {}
    if user is not None:
        kept = {t["job_id"]: t for t in history_store.takes(h.app.state, user, entry_id)}
        for take in auth.identity(h.app).takes_of(user):
            if take["kind"] == "follow" and take["entry_id"] == entry_id:
                rows[take["job_id"]] = _row(h, take["job_id"], take["created_at"], kept)
    for job_id in device:
        if job_id not in rows and _unowned_take(h, entry_id, job_id):
            rows[job_id] = _row(h, job_id, None, kept)
    ordered = sorted(rows.values(), key=lambda r: (str(r["at"] or ""), r["job_id"]), reverse=True)
    return ordered[:MINE_MAX]


def is_minor_post(app: Any, job: Any, account: Any) -> bool:
    """True when a post is by someone marked 13 to 17: the take's own answer, or its account's mark (privacy PM-B2, PM-R4).
    The mark can come after the post, so it is read on every view; a store that cannot answer reads as a minor (fails closed)."""
    if consent_record.is_minor(job if isinstance(job, dict) else None):
        return True
    if not isinstance(account, str) or account is UNKNOWN:
        return account is UNKNOWN
    try:
        return auth.identity(app).is_minor(account)
    except Exception:  # noqa: BLE001  an unknown answer is not an adult's
        return True


def board_keep(app: Any, entry_id: str | None = None) -> Any:
    """The `keep` of a public board view (challenges.view, summary, list_all): a post shows unless it stays with its owner.

    Recorded flags first (a post since TICKET-327), then the same rule as the board POST while anything is left to check:
    the job record, and the owner's own reference, which can be set after the post. One lookup per job per request."""
    seen: dict[str, bool] = {}

    def keep(item: dict[str, Any]) -> bool:
        job_id = item.get("job_id")
        if item.get("private") or item.get("own_reference"):
            return False
        if not isinstance(job_id, str):
            return True
        if job_id not in seen:
            job = history_store.read_json(Path(app.state) / "jobs" / job_id / "job.json")
            movement = entry_id or (job.get("entry_id") or (job.get("result") or {}).get("entry_id") if isinstance(job, dict) else None) or ""
            owner_id = owner(app, job_id)
            seen[job_id] = not stays_with_owner(app.state, job_id, job, owner_id, str(movement)) and not is_minor_post(app, job, owner_id or item.get("owner"))
        return seen[job_id]
    return keep


def _listable(h: Any, item: dict[str, Any], entry_id: str, user: str | None, device: list[str]) -> bool:
    """A board post others may see here: not the caller's, and not a take that stays with its owner."""
    job_id = item.get("job_id")
    if not isinstance(job_id, str) or job_id in device or item.get("private") or item.get("own_reference"):
        return False
    job = history_store.read_json(Path(h.app.state) / "jobs" / job_id / "job.json")
    if "private" not in item and not isinstance(job, dict):
        return False  # posted before the board recorded it and the job folder is gone: nothing left to check, so not shown
    owner_id = owner(h.app, job_id)
    if user is not None and owner_id == user:
        return False
    return not stays_with_owner(h.app.state, job_id, job, owner_id, entry_id)


def shared(h: Any, entry_id: str, user: str | None, device: list[str]) -> list[dict[str, Any]]:
    """Scores other people posted to a board of `entry_id`, newest first; the board link, never a job id."""
    out: list[dict[str, Any]] = []
    examined = 0
    viewer = challenge_visibility.viewer_of(h)
    for summary in challenges.list_all(h.app.state, entry_id=entry_id, allow=lambda b: challenge_visibility.can_view(b, viewer))[:BOARDS_MAX]:
        doc = challenges.get(h.app.state, summary["id"]) or {}
        for item in reversed(doc.get("entries", [])):  # newest post first
            examined += 1
            if examined > POSTS_MAX:
                return sorted(out, key=lambda r: str(r["at"] or ""), reverse=True)
            if not _listable(h, item, entry_id, user, device):
                continue
            public = challenges.public_entry(item)
            out.append({"name": public.get("name"), "score": public.get("score"), "grade": public.get("grade"),
                        "shown": public.get("shown"), "at": public.get("created_at"), "board": doc["id"], "title": doc.get("title")})
            if len(out) >= SHARED_MAX:
                break
        if len(out) >= SHARED_MAX:
            break
    return sorted(out, key=lambda r: str(r["at"] or ""), reverse=True)
