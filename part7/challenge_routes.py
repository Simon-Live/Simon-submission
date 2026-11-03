"""HTTP routes of challenges (docs/specs/challenges.md); `server.py` calls `handle` before its own routes.

Scores are never taken from the browser: an entry names a finished job (and a person of a group job) and this
module reads that job's `analysis.json` itself. Public answers never carry the job id or pid of an entry.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from part7 import challenges, client_log, group, history_store, jobs, judge_view, quota, shown_score, takes_on
from part7.http_body import drain_before_refusal

BODY_MAX = 8192
RATE_LIMIT = 20  # POSTs a minute from one visitor
CREW_MAX = 8
MSG_BODY_LARGE = "The request is too large."
MSG_RATE = "Too many challenge requests. Try again in a minute."
MSG_SPONSORED = "Sponsored challenges are set up by the operator."
MSG_NO_ENTRY = "This movement is not in the catalog."
MSG_JOB = "Name a finished result to add."
MSG_NO_JOB = "This result was not found. Results are kept for 7 days."
MSG_UNFINISHED = "This result is not finished yet."
MSG_UNSCORED = "This take was not scored, so it cannot join a challenge."
MSG_OWNER_ONLY = "This take is private to you, so it cannot go on a board."  # private mode or own reference (TICKET-327)
MSG_STORE = "Boards are not available right now. Try again in a minute."  # the identity store did not answer
MSG_OTHER_MOVEMENT = "This result is for a different movement than the challenge."
MSG_PERSON = "Choose which person of the group result to add."
MSG_PEOPLE = "Add 1 to 8 people, each with a name."
MSG_BAD_LENGTH = "The request is not valid."
MSG_CHALLENGE = "This challenge was not found."


def _limiter(h: Any) -> client_log.RateLimit:
    return h.app.__dict__.setdefault("challenge_rate", client_log.RateLimit(limit=RATE_LIMIT))


def _allowed(h: Any) -> bool:
    key = h._visitor() or (h.client_address[0] if h.client_address else "unknown")
    if _limiter(h).allow(key):
        return True
    h._error(429, MSG_RATE)
    return False


def _visitor_key(h: Any) -> str:
    """The hashed visitor key of quota.py (the address itself is never stored)."""
    return quota.visitor_key(h._visitor() or (h.client_address[0] if h.client_address else "unknown")) or "unknown"


def _body(h: Any) -> dict[str, Any] | None:
    """The rate-checked JSON body, or None after answering 400, 413 or 429."""
    try:
        length = int(h.headers.get("Content-Length") or 0)
    except ValueError:
        length = 0
    if length < 0:
        h.close_connection = True  # a negative length would make the read wait for a body that never ends
        h._error(400, MSG_BAD_LENGTH)
        return None
    if length > BODY_MAX:
        drain_before_refusal(h, length)  # TICKET-194: the 413 arrives instead of a connection reset
        h._error(413, MSG_BODY_LARGE)
        return None
    if not _allowed(h):
        return None
    return h._body_json()


def _fail(h: Any, exc: challenges.ChallengeError) -> None:
    h._error(exc.status, str(exc))


# ----- reading a finished result -------------------------------------------------------------------------
def _analysis_of(h: Any, job_id: Any, pid: Any) -> tuple[dict[str, Any], str | None]:
    """`(analysis, entry_id)` of a finished solo job or a person of a finished group job; ChallengeError otherwise."""
    if not isinstance(job_id, str) or not jobs.JOB_ID_RE.match(job_id):
        raise challenges.ChallengeError(MSG_JOB)
    job = h.app.queue.get(job_id)
    if job is None:
        raise challenges.ChallengeError(MSG_NO_JOB, 404)
    if job.get("status") != "done":
        raise challenges.ChallengeError(MSG_UNFINISHED, 409)
    entry = job.get("entry_id") or (job.get("result") or {}).get("entry_id")
    owner_id = takes_on.owner(h.app, job_id)
    if owner_id is takes_on.UNKNOWN:
        raise challenges.ChallengeError(MSG_STORE, 503)  # not the take's fault: nothing is decided without the store
    if takes_on.stays_with_owner(h.app.state, job_id, job, owner_id, str(entry or "")):
        raise challenges.ChallengeError(MSG_OWNER_ONLY, 409)  # a board is public: an owner-only take never goes on one
    folder = h.app.queue.job_dir(job_id)
    if job.get("kind") == "group":
        people = (job.get("result") or {}).get("people") or []
        if pid is None or not isinstance(pid, (str, int)) or isinstance(pid, bool):
            raise challenges.ChallengeError(MSG_PERSON)
        pid = str(pid)
        if not jobs.PID_RE.match(pid) or pid not in {str(p.get("id")) for p in people}:
            raise challenges.ChallengeError(MSG_PERSON)
        path, entry_id = group.person_dir(folder, pid) / "analysis.json", (job.get("result") or {}).get("entry_id")
    elif job.get("kind") == "follow":
        if pid is not None:
            raise challenges.ChallengeError(MSG_JOB)
        path, entry_id = folder / "work" / "follower" / "analysis.json", job.get("entry_id")
    else:
        raise challenges.ChallengeError(MSG_JOB)
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise challenges.ChallengeError(MSG_NO_JOB, 404) from None
    return (doc if isinstance(doc, dict) else {}), entry_id


def _score_entry(h: Any, challenge: dict[str, Any], job_id: Any, pid: Any, name: Any) -> dict[str, Any]:
    """The stored form of one entry, with the score read from the job's own analysis."""
    clean = challenges.clean_name(name)
    analysis, entry_id = _analysis_of(h, job_id, pid)
    if entry_id != challenge["entry_id"]:
        raise challenges.ChallengeError(MSG_OTHER_MOVEMENT, 409)
    score, status = analysis.get("score"), analysis.get("status")
    value = score.get("value") if isinstance(score, dict) else None
    grade = score.get("grade") if isinstance(score, dict) else None
    code = status.get("code") if isinstance(status, dict) else None
    if code != "ok" or isinstance(value, bool) or not isinstance(value, (int, float)) or not isinstance(grade, str):
        raise challenges.ChallengeError(MSG_UNSCORED, 409)
    light = history_store.light_of(h.app.queue.get(job_id) or {}) if pid is None else None   # a group person has no light reading
    return {
        "name": clean, "score": value, "grade": grade[:3], "job_id": job_id, "pid": None if pid is None else str(pid),
        "strongest_section": challenges.strongest_section(score),
        "shown": shown_score.of_analysis(analysis, light),  # one-letter.md: the board shows this; it still ranks by `score`
        "private": False, "own_reference": False,  # TICKET-327: checked at post time (refused otherwise); disk only, read after the job expires
    }


# ----- routes ------------------------------------------------------------------------------------------
def _wanted(doc: dict[str, Any], default_name: Any = None) -> list[tuple[Any, Any, Any]]:
    """`(job_id, pid, name)` of the one result or the crew a request names; ChallengeError for a bad crew."""
    if "people" in doc:
        people = doc["people"]
        ok = isinstance(people, list) and 1 <= len(people) <= CREW_MAX and all(isinstance(p, dict) for p in people)
        if not ok:
            raise challenges.ChallengeError(MSG_PEOPLE)
        return [(doc.get("job_id"), p.get("pid"), p.get("name")) for p in people]
    return [(doc.get("job_id"), doc.get("pid"), doc.get("name", default_name))]


def _create(h: Any) -> None:
    """Make a challenge, optionally with its first entry or crew; any failure creates nothing."""
    doc = _body(h)
    if doc is None:
        return
    if doc.get("sponsor") is not None or doc.get("kind") == "sponsored" or "ends_at" in doc:
        return h._error(400, MSG_SPONSORED)
    entry_id = doc.get("entry_id")
    try:
        if not isinstance(entry_id, str) or not challenges.ENTRY_ID_RE.match(entry_id):
            raise challenges.ChallengeError(challenges.MSG_ENTRY)
        if h.app.child.get_entry(entry_id) is None:
            raise challenges.ChallengeError(MSG_NO_ENTRY, 404)
        first = []
        if "job_id" in doc or "people" in doc:
            wanted = _wanted(doc, doc.get("creator_name"))
            first = [_score_entry(h, {"entry_id": entry_id}, job, pid, name) for job, pid, name in wanted]
        made = challenges.create(
            h.app.state, entry_id=entry_id, title=doc.get("title"), creator_name=doc.get("creator_name"),
            kind=doc.get("kind"), entries=first, visitor=_visitor_key(h),
        )
    except challenges.ChallengeError as exc:
        return _fail(h, exc)
    h._json(201, {**challenges.view(made, keep=takes_on.board_keep(h.app, entry_id)), "added": [challenges.public_entry(e) for e in made["entries"]]})


def _add(h: Any, challenge_id: str) -> None:
    doc = _body(h)
    if doc is None:
        return
    challenge = challenges.get(h.app.state, challenge_id)
    if challenge is None:
        return h._error(404, MSG_CHALLENGE)
    try:
        if challenges.ended(challenge):
            raise challenges.ChallengeError(challenges.MSG_ENDED, 409)
        entries = [_score_entry(h, challenge, job, pid, name) for job, pid, name in _wanted(doc)]
        stored = challenges.add_entries(h.app.state, challenge_id, entries)
    except challenges.ChallengeError as exc:
        return _fail(h, exc)
    h._json(201, {**challenges.view(stored, keep=takes_on.board_keep(h.app, stored["entry_id"])), "added": [challenges.public_entry(e) for e in entries]})


def follow_ref(h: Any, doc: dict[str, Any], entry_id: str) -> dict[str, Any] | None:
    """The optional `challenge_id` of a follow request as a job-record field, `{}` when absent.

    The challenge must exist and be for the same movement as the take; else this answers 400 and returns None.
    An open one puts its id on the job record, so the result can offer "Add my score" on any device. One that ended
    between the start and the upload does not refuse the take: the record carries `challenge_ended` instead, and the
    result screen says so.
    """
    raw = doc.get("challenge_id")
    if raw is None:
        return {}
    found = challenges.get(h.app.state, raw) if isinstance(raw, str) else None
    if found is None:
        h._error(400, MSG_CHALLENGE)
    elif found["entry_id"] != entry_id:
        h._error(400, MSG_OTHER_MOVEMENT)
    elif challenges.ended(found):
        return {"challenge_ended": True}
    else:
        return {"challenge_id": found["id"]}
    return None


def _list(h: Any, query: dict[str, str]) -> None:
    kind, entry_id = query.get("kind"), query.get("entry_id")
    if kind is not None and kind not in challenges.KINDS:
        return h._error(400, "Unknown kind of challenge.")
    if entry_id is not None and not challenges.ENTRY_ID_RE.match(entry_id):
        return h._error(400, challenges.MSG_ENTRY)
    rows = challenges.list_all(h.app.state, entry_id=entry_id, kind=kind, keep=takes_on.board_keep(h.app))  # ADR-0019: owner-only posts leave the count and the lead
    if query.get("view") == judge_view.VIEW_JUDGE:  # the judge view leaves test boards out; no view keeps them (judge-view.md)
        rows = judge_view.judge_challenges(rows)
    h._json(200, {"challenges": rows})


def _one(h: Any, challenge_id: str) -> None:
    doc = challenges.get(h.app.state, challenge_id)
    if doc is None:
        return h._error(404, MSG_CHALLENGE)
    h._json(200, challenges.view(doc, keep=takes_on.board_keep(h.app, doc["entry_id"])))


def handle(h: Any, method: str, route: str) -> bool:
    """Answer `route` (below `api/`) when it belongs to challenges; False when it does not."""
    parts = route.split("/")
    if parts[0] != "challenges" or len(parts) > 3 or (len(parts) == 3 and parts[2] != "entries"):
        return False
    read = method in ("GET", "HEAD")
    if len(parts) == 1 and method == "POST":
        _create(h)
    elif len(parts) == 1 and read:
        _list(h, dict(parse_qsl(urlsplit(h.path).query)))
    elif len(parts) == 2 and read:
        _one(h, parts[1])
    elif len(parts) == 3 and method == "POST":
        _add(h, parts[1])
    else:
        h._error(405, "Method not allowed.")
    return True
