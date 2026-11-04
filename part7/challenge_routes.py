"""HTTP routes of challenges (docs/specs/challenges.md); `server.py` calls `handle` before its own routes.

Scores are never taken from the browser: an entry names a finished job (and a person of a group job) and this
module reads that job's `analysis.json` itself. Public answers never carry the job id or pid of an entry.

Private movements and takes (private-default D6, prod-data.md "Boards"): a board is made, listed, read and added to
only on a movement the caller may view (`auth.may_view_entry`), and a missing movement and a private one get the same
404. A take goes on a board only from its owner's session; another account's take answers as a missing one (404).

Boards show names, so nothing of someone under 18 reaches one (privacy PM-B2, PM-R4): an account marked 13 to 17 (or
owning a take or movement that is) cannot make a board (403, so no `creator_name` of theirs is stored), and a take goes
on no board when its own answer or its owner's account mark says 13 to 17 (`trainer_publish.minor_refused`).
"""

from __future__ import annotations

import json
from pathlib import Path
import threading
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from part7 import (auth, board_copycheck, board_discovery, challenge_share_routes, challenge_visibility as vis, challenges, client_log, group,
                   history_store, jobs, judge_view, ops_notice, prod_mode, quota, shown_score, takes_on, trainer_publish, upload_owner)
from part7.http_body import drain_before_refusal

BODY_MAX = 8192
RATE_LIMIT = 20  # POSTs a minute from one visitor
CREW_MAX = 8
REPORT_NOTICE_EVERY = 5  # the first report of a board and every fifth after it email the operator
MSG_BODY_LARGE = "The request is too large."
MSG_RATE = "Too many challenge requests. Try again in a minute."
MSG_ENDS_AT = "A board ends when its maker closes it. You cannot set an end date here."
MSG_MAKER_ONLY = "Only the person who made this board can do that."
MSG_SPONSORED = "Sponsored challenges are set up by the operator."
MSG_NO_ENTRY = "This movement is not in the catalog."
MSG_JOB = "Name a finished result to add."
MSG_NO_JOB = "This result was not found. Results are kept for 7 days."
MSG_UNFINISHED = "This result is not finished yet."
MSG_SECTION = "A practice section is not the whole movement, so it cannot join a challenge. Follow the whole movement."
MSG_UNSCORED = "This take was not scored, so it cannot join a challenge."
MSG_OWNER_ONLY = "This take is private to you, so it cannot go on a board."  # private mode or own reference (TICKET-327)
MSG_STORE = "Boards are not available right now. Try again in a minute."  # the identity store did not answer
MSG_OTHER_MOVEMENT = "This result is for a different movement than the challenge."
MSG_PERSON = "Choose which person of the group result to add."
MSG_PEOPLE = "Add 1 to 8 people, each with a name."
MSG_BAD_LENGTH = "The request is not valid."
MSG_CHALLENGE = "This challenge was not found."
MSG_OWN_COMPUTE = "This take was scored on your own compute, so it stays off ranked boards."  # #415 byok_ranked
MSG_MINOR = "Boards show names, so a take from someone under 18 stays off them."  # LEG-H1 under-18 defaults
MSG_MINOR_BOARD = "Boards show names, so someone under 18 cannot make one."  # PM-B2
MSG_MOVEMENT_PRIVATE = "This challenge is not open yet. Its movement is private, so ask the person who sent you the link to publish it."
MSG_PROD_SIGN_IN = "Sign in to start a challenge."
MSG_PROD_RESULT = "Start a challenge from a result you scored."
MSG_GUEST_PRIVATE ="The owner has not made this movement open to others yet, so scores cannot be added."


def _gate(h: Any, board: dict[str, Any] | None) -> str | None:
    """`open` when the caller may see the board and its movement; `restricted` when the caller may see the board but not
    its private movement (the board's owner, or a person invited to an invited board); otherwise the answer is sent (401
    signed out and 403 wrong account on an invited board, 404 for the rest) and None returns. `vis.can_view` is the only
    check of who sees a board."""
    if board is None or not challenges.shown(board):
        h._error(404, MSG_CHALLENGE)
        return None
    viewer = vis.viewer_of(h)
    if not vis.can_view(board, viewer):
        status, message = vis.refusal(viewer)
        h._error(status, message, needs_sign_in=viewer is None)
        return None
    if auth.may_view_entry(h, board["entry_id"]):
        return "open"
    if vis.is_owner(board, viewer) or (vis.visibility_of(board) == vis.INVITED and vis.is_invited(board, viewer)):
        return "restricted"  # the link must not die for the owner or the invited when the movement goes private
    h._error(404, MSG_MOVEMENT_PRIVATE, code="movement_private")  # D6 still holds: the board id is the link, the movement id is not shown
    return None


def _limiter(h: Any) -> client_log.RateLimit:
    return h.app.__dict__.setdefault("challenge_rate", client_log.RateLimit(limit=RATE_LIMIT))


def _allowed(h: Any) -> bool:
    key = quota.client_of(h._visitor() or (h.client_address[0] if h.client_address else "unknown"))  # R12: an IPv6 /64
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
def _owned_by_caller(h: Any, job_id: str) -> str | None:
    """The owner of `job_id` (None: nobody, whose job id is its key, identity.md). ChallengeError 404, as for a missing
    result, when an account owns it and the caller is not that account; 503 when the store cannot say."""
    owner_id = takes_on.owner(h.app, job_id)
    if owner_id is takes_on.UNKNOWN:
        raise challenges.ChallengeError(MSG_STORE, 503)  # not the take's fault: nothing is decided without the store
    if owner_id is not None and auth.current_user(h) != owner_id:  # D6: another account's take is not there for them
        raise challenges.ChallengeError(MSG_NO_JOB, 404)
    if owner_id is None:  # a group take has no takes row: its record names who made it, read the way take_access.py reads it
        made = upload_owner.people_owner(h.app.queue, job_id, ("group",))
        if made is upload_owner.UNKNOWN or (made and auth.current_user(h) != made):  # "" is made signed out: its id is its key
            raise challenges.ChallengeError(MSG_NO_JOB, 404)
    return owner_id


def _viewable(h: Any, entry_id: Any) -> bool:
    """True when the movement exists in the catalog and this caller may view it (a private one answers as missing)."""
    return (isinstance(entry_id, str) and h.app.child.get_entry(entry_id) is not None
            and auth.may_view_entry(h, entry_id))


def _analysis_of(h: Any, job_id: Any, pid: Any) -> tuple[dict[str, Any], str | None]:
    """`(analysis, entry_id)` of a finished solo job or a person of a finished group job; ChallengeError otherwise."""
    if not isinstance(job_id, str) or not jobs.JOB_ID_RE.match(job_id):
        raise challenges.ChallengeError(MSG_JOB)
    job = h.app.queue.get(job_id)
    if job is None:
        raise challenges.ChallengeError(MSG_NO_JOB, 404)
    owner_id = _owned_by_caller(h, job_id)
    if job.get("status") != "done":
        raise challenges.ChallengeError(MSG_UNFINISHED, 409)
    if job.get("compute_owner") is True and not challenges.ranks_owner_compute():
        raise challenges.ChallengeError(MSG_OWN_COMPUTE, 409)
    if trainer_publish.minor_refused(h, owner_id or auth.current_user(h), job):  # PM-R4: the account mark too
        raise challenges.ChallengeError(MSG_MINOR, 409)
    if job.get("section"):
        raise challenges.ChallengeError(MSG_SECTION, 409)  # S8: a practice section is not the whole movement, so it never ranks with full takes
    entry = job.get("entry_id") or (job.get("result") or {}).get("entry_id")
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
    job = h.app.queue.get(job_id) or {}
    # A crew's take makes a movement of its own; it joins a board when its recorded source movement (set by the server from
    # the challenge the group started from, `group_source`) is the board's. Nothing else passes.
    source = job.get("source_entry_id") if job.get("kind") == "group" else None
    if entry_id != challenge["entry_id"] and source != challenge["entry_id"]:
        raise challenges.ChallengeError(MSG_OTHER_MOVEMENT, 409)
    score, status = analysis.get("score"), analysis.get("status")
    value = score.get("value") if isinstance(score, dict) else None
    grade = score.get("grade") if isinstance(score, dict) else None
    code = status.get("code") if isinstance(status, dict) else None
    if code != "ok" or isinstance(value, bool) or not isinstance(value, (int, float)) or not isinstance(grade, str):
        raise challenges.ChallengeError(MSG_UNSCORED, 409)
    board_copycheck.guard(h, challenge, job_id)  # TICKET-441: the trainer's own clip scores for its owner and stays off the board
    holder = takes_on.owner(h.app, job_id) if pid is None else None
    holder = holder if isinstance(holder, str) else (auth.current_user(h) if pid is None else None)   # S8: one row per account (a crew's people share the poster's account, so they carry none)
    poster = auth.current_user(h) if pid is not None else None  # a crew's rows carry no owner (S8) but go with the account that posted them
    light = history_store.light_of(job) if pid is None else None   # a group person has no light reading
    return {
        "name": clean, "score": value, "grade": grade[:3], "job_id": job_id, "pid": None if pid is None else str(pid),
        "strongest_section": challenges.strongest_section(score),
        "shown": shown_score.for_board(analysis, light),  # score-consistency.md S7: the one number the board ranks and shows
        **({"owner": holder} if isinstance(holder, str) else {}), **({"poster": poster} if isinstance(poster, str) else {}),  # disk only: Delete my data and the under-18 mark find the post by it
        "private": False, "own_reference": False,  # TICKET-327: checked at post time (refused otherwise); disk only, read after the job expires
        "compute_owner": job.get("compute_owner") is True,  # #415: kept so the board can leave it out if byok_ranked turns off
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


def _friend_title(h: Any, entry_id: str) -> str:
    """The title of a friend board in prod: "Beat my <movement>", from the catalog, never from the request."""
    name = (h.app.child.get_entry(entry_id) or {}).get("name")
    name = name if isinstance(name, str) and name.strip() and not challenges.has_at(name) else "movement"
    return " ".join(f"Beat my {name}".split())[:challenges.TITLE_MAX]


def _create(h: Any) -> None:
    """Make a challenge, optionally with its first entry or crew; any failure creates nothing."""
    doc = _body(h)
    if doc is None:
        return
    if "ends_at" in doc and doc.get("sponsor") is None and doc.get("kind") != "sponsored":
        return h._error(400, MSG_ENDS_AT)  # TICKET-431: the maker closes a board; nobody sets a date from the web
    if doc.get("sponsor") is not None or doc.get("kind") == "sponsored" or "ends_at" in doc:
        return h._error(400, MSG_SPONSORED)
    entry_id = doc.get("entry_id")
    try:
        if not isinstance(entry_id, str) or not challenges.ENTRY_ID_RE.match(entry_id):
            raise challenges.ChallengeError(challenges.MSG_ENTRY)
        if not _viewable(h, entry_id):  # D6: a private id answers as a missing one
            raise challenges.ChallengeError(MSG_NO_ENTRY, 404)
        if trainer_publish.minor_refused(h, auth.current_user(h)):  # PM-B2: no board and no name from a minor
            raise challenges.ChallengeError(MSG_MINOR_BOARD, 403)
        if prod_mode.is_prod():  # audit row 2: no board from a signed-out request, none without a scored result, no free title
            if not auth.current_user(h):
                raise challenges.ChallengeError(MSG_PROD_SIGN_IN, 401)
            if "job_id" not in doc and "people" not in doc:
                raise challenges.ChallengeError(MSG_PROD_RESULT)
            if doc.get("kind") == "friend":
                doc["title"] = _friend_title(h, entry_id)
        first = []
        if "job_id" in doc or "people" in doc:
            wanted = _wanted(doc, doc.get("creator_name"))
            first = [_score_entry(h, {"entry_id": entry_id}, job, pid, name) for job, pid, name in wanted]
        visibility = doc.get("visibility", vis.PUBLIC)
        if visibility not in (vis.PUBLIC, vis.INVITED):
            raise challenges.ChallengeError(challenge_share_routes.MSG_VISIBILITY)
        typed, bad = vis.clean_emails(doc.get("invites"))
        if bad:
            raise challenges.ChallengeError(vis.MSG_NO_ADDRESS)
        if (visibility == vis.INVITED or typed) and not auth.current_user(h):
            raise challenges.ChallengeError(vis.MSG_SIGN_IN_TO_CHOOSE, 401)
        now = challenges.stamp(challenges._now())
        made = challenges.create(
            h.app.state, entry_id=entry_id, title=doc.get("title"), creator_name=doc.get("creator_name"),
            kind=doc.get("kind"), entries=first, visitor=_visitor_key(h), owner=auth.current_user(h),
            visibility=visibility, invites=[{"email": e, "added_at": now, "joined_at": None, "mail": None} for e in typed],
        )
    except challenges.ChallengeError as exc:
        return _fail(h, exc)
    sent = challenge_share_routes.mail_invites(h, made, typed) if typed else []
    access = challenge_share_routes.access_doc(h, made, sent) if made.get("owner") else None
    h._json(201, {**challenges.view(made, keep=takes_on.board_keep(h.app, entry_id)),
                  "added": [challenges.public_entry(e) for e in made["entries"]], "access": access,
                  "movement_private": not challenge_share_routes.movement_open(h, entry_id)})  # the page warns and offers to publish


def _add(h: Any, challenge_id: str) -> None:
    doc = _body(h)
    if doc is None:
        return
    challenge = challenges.get(h.app.state, challenge_id)
    mode = _gate(h, challenge)
    if mode is None:
        return
    if mode == "restricted":
        return h._error(403, MSG_GUEST_PRIVATE)
    try:
        if challenges.ended(challenge):
            raise challenges.ChallengeError(challenges.MSG_ENDED, 409)
        entries = [_score_entry(h, challenge, job, pid, name) for job, pid, name in _wanted(doc)]
        stored = challenges.add_entries(h.app.state, challenge_id, entries)
    except challenges.ChallengeError as exc:
        return _fail(h, exc)
    h._json(201, {**challenges.view(stored, keep=takes_on.board_keep(h.app, stored["entry_id"])), "added": [challenges.public_entry(e) for e in entries]})


def _background(fn: Any, *args: Any) -> None:
    threading.Thread(target=fn, args=args, daemon=True).start()


def _notify(state: Path, challenge_id: str, reason: str, count: int) -> None:
    """Raise the operator notice for a report, off the request thread. It names the board, the reason code and the count, never text a visitor typed."""
    body = (f"Board {challenge_id} was reported for: {reason}. Reports on it: {count}. Look with: python -m part7 challenge show {challenge_id}; "
            f"remove one name with challenge remove-entry {challenge_id} --name NAME, or the board with challenge remove-board {challenge_id}.")
    _background(ops_notice.send, "A challenge was reported", body, state)


def _report(h: Any, challenge_id: str) -> None:
    """`POST api/challenges/<id>/report {reason}`: anyone who can see the board may report it once per reason; the first report
    and every fifth after it raise a notice (the rest are counted on the board for `challenge show`)."""
    doc = _body(h)
    if doc is None:
        return
    if _gate(h, challenges.get(h.app.state, challenge_id)) is None:  # who sees a board may report it, also when its movement went private
        return
    try:
        count, first = challenges.report(h.app.state, challenge_id, doc.get("reason"), _visitor_key(h))
    except challenges.ChallengeError as exc:
        return _fail(h, exc)
    if first or count % REPORT_NOTICE_EVERY == 0:
        _notify(h.app.state, challenge_id, str(doc["reason"]), count)
    h._json(200, {"reported": True})


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
    if not challenges.shown(found) or not auth.may_view_entry(h, found["entry_id"]) or not vis.can_view(found, vis.viewer_of(h)):
        h._error(400, MSG_CHALLENGE)
    elif found["entry_id"] != entry_id:
        h._error(400, MSG_OTHER_MOVEMENT)
    elif challenges.ended(found):
        return {"challenge_ended": True}
    else:
        return {"challenge_id": found["id"]}
    return None


def group_source(h: Any, doc: dict[str, Any]) -> dict[str, Any] | None:
    """The source a group take records when it starts from a challenge, `{}` when it does not (operator, release 10: a board
    accepts a crew's take of the same routine). The movement comes from the challenge on the server; a `source_entry_id` in the
    request is never read. A bad or unviewable challenge answers 400 and returns None; one that ended in the meantime does
    not refuse the take (`challenge_ended`, as for a follow)."""
    raw = doc.get("challenge_id")
    if raw is None:
        return {}
    found = challenges.get(h.app.state, raw) if isinstance(raw, str) else None
    if not challenges.shown(found) or not auth.may_view_entry(h, found["entry_id"]) or not vis.can_view(found, vis.viewer_of(h)):
        h._error(400, MSG_CHALLENGE)
        return None
    if challenges.ended(found):
        return {"challenge_ended": True}
    return {"challenge_id": found["id"], "source_entry_id": found["entry_id"]}


def _list(h: Any, query: dict[str, str]) -> None:
    kind, entry_id = query.get("kind"), query.get("entry_id")
    if kind is not None and kind not in challenges.KINDS:
        return h._error(400, "Unknown kind of challenge.")
    if entry_id is not None and not challenges.ENTRY_ID_RE.match(entry_id):
        return h._error(400, challenges.MSG_ENTRY)
    viewer = vis.viewer_of(h)
    rows = challenges.list_all(h.app.state, entry_id=entry_id, kind=kind, keep=takes_on.board_keep(h.app), allow=lambda b: vis.can_view(b, viewer))  # ADR-0019: owner-only posts leave the count and the lead
    seen: dict[str, bool] = {}
    rows = [r for r in rows if seen.setdefault(str(r.get("entry_id")), auth.may_view_entry(h, str(r.get("entry_id"))))]  # D6
    if query.get("view") == judge_view.VIEW_JUDGE:  # the judge view leaves test boards out; no view keeps them (judge-view.md)
        rows = judge_view.judge_challenges(rows)
    h._json(200, {"challenges": rows})


def _one(h: Any, challenge_id: str) -> None:
    doc = challenges.get(h.app.state, challenge_id)
    mode = _gate(h, doc)  # D6: a private movement's board answers as missing, except to its owner and the invited
    if mode is None:
        return
    viewer = vis.viewer_of(h)
    vis.mark_joined(h.app.state, doc, viewer)
    keep = takes_on.board_keep(h.app, doc["entry_id"])
    out = {**challenges.view(doc, keep=keep),
           "you": vis.role(doc, viewer), "movement_private": mode == "restricted",
           "warning": challenge_share_routes.MSG_PRIVATE_MOVEMENT if mode == "restricted" and vis.is_owner(doc, viewer) else None}
    h._json(200, board_discovery.annotate(h, doc, out, keep))  # TICKET-431: "you" on the caller's rows, `can_manage` for the maker


def _manage(h: Any, challenge_id: str, action: str) -> None:
    """`remove-my-score` (anyone on the board), `close` and `delete` (its maker; a signed-out board has no maker here)."""
    body = _body(h)
    if body is None:
        return
    doc = challenges.get(h.app.state, challenge_id)
    user = auth.current_user(h)
    jobs_named: tuple[str, ...] = ()
    if action == "remove-my-score":
        asked = body.get("jobs") if isinstance(body.get("jobs"), list) else []
        jobs_named = tuple(j for j in takes_on.device_ids(",".join(str(a) for a in asked)) if takes_on.keyed_by_id(h.app, j, user))
    holds_a_row = action == "remove-my-score" and doc is not None and challenges.holds_row(doc, user, jobs_named)
    if not holds_a_row and _gate(h, doc) is None:  # the same gate as reading it; a person's own score can always leave, also off the invite list
        return
    try:
        if action == "remove-my-score":
            gone = challenges.remove_scores(h.app.state, challenge_id, owner=user, job_ids=jobs_named)
            return h._json(200, {"removed": gone})
        if user is None or doc.get("owner") != user:
            raise challenges.ChallengeError(MSG_MAKER_ONLY, 403)
        if action == "close":
            challenges.close(h.app.state, challenge_id)
            return h._json(200, {"closed": True})
        challenges.delete(h.app.state, challenge_id)
        h._json(200, {"deleted": True})
    except challenges.ChallengeError as exc:
        _fail(h, exc)


def handle(h: Any, method: str, route: str) -> bool:
    """Answer `route` (below `api/`) when it belongs to challenges; False when it does not."""
    if board_discovery.handle(h, method, route, _viewable):  # the board lists of the movement page, home and Me
        return True
    if challenge_share_routes.handle(h, method, route):  # who sees a board, invite mail, the stop link
        return True
    parts = route.split("/")
    if parts[0] == "challenges" and len(parts) == 3 and parts[2] in ("remove-my-score", "close", "delete"):
        if method == "POST":
            _manage(h, parts[1], parts[2])
        else:
            h._error(405, "Method not allowed.")
        return True
    if parts[0] != "challenges" or len(parts) > 3 or (len(parts) == 3 and parts[2] not in ("entries", "report")):
        return False
    read = method in ("GET", "HEAD")
    if len(parts) == 1 and method == "POST":
        _create(h)
    elif len(parts) == 1 and read:
        _list(h, dict(parse_qsl(urlsplit(h.path).query)))
    elif len(parts) == 2 and read:
        _one(h, parts[1])
    elif len(parts) == 3 and method == "POST":
        (_report if parts[2] == "report" else _add)(h, parts[1])
    else:
        h._error(405, "Method not allowed.")
    return True
