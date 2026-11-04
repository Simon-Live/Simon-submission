"""Who may open a take by its job id (docs/specs/prod-data.md "Object routes", APP-C1, TICKET-373).

A take made signed in belongs to its account: its clip, its split-screen export and its delete answer only to the
owner's session (`refusal`). So do a people job and a group take made signed in, whose owner is the people
record's `_people_owner` (upload_owner.people_owner, go-live P-N1). An anonymous take keeps the job id as its key, as a result link does (identity.md). When
the owner cannot be read the route refuses (503, fails closed).

Featured takes (private-default D4): the operator-named hero and the Impact page's takes have public ids, so holding
one proves nothing (`featured`, used by the claim refusal). Being featured never opens a take: a signed-in take answers
only to its owner whatever the operator's files name, and `may_feature` is True only for a take no account owns (the
operator's own, made signed out; prod records nothing signed out, byok-prod.md). No take owner can opt in to being
featured today, so no owned take is ever named.
"""

from __future__ import annotations

from pathlib import Path
import sqlite3
from typing import Any

from part7 import auth, identity, impact, jobs, judge_view, takes_on, upload_owner

MSG_NOT_YOURS = "This take is not available."
MSG_OWNER_UNKNOWN = "This take cannot be opened right now. Try again in a moment."


def featured(app: Any) -> set[str]:
    """Job ids every visitor is shown: every id the operator ever named hero (`judge_view.ever_named`) and every take the Impact page's persona file names, each
    whether or not it qualifies today. Their ids are public, so holding one proves nothing, and neither does a claim
    made with one (`auth_routes._claim` refuses them)."""
    state = Path(app.state)
    ids = {judge_view.configured_id(state)} | impact.named_job_ids(state)  # TICKET-373 B1: every id the persona file names
    ids.discard(None)
    ever = judge_view.ever_named(state)  # every id ever named hero stays protected after the operator names another
    return ids | ever if isinstance(ever, set) else ever


def may_feature(state: Path | str, job_id: Any) -> bool:
    """True when the operator may name `job_id` as the hero or on the Impact page: no account owns it. A store that
    cannot answer counts as owned (fails closed)."""
    if not isinstance(job_id, str) or not jobs.JOB_ID_RE.match(job_id):
        return False
    path = identity.db_path(Path(state))
    if not path.is_file():
        return True
    try:  # not identity.owner_of_job: it answers None (nobody) when the store errs
        db = sqlite3.connect(str(path), timeout=10)
        try:
            return db.execute("SELECT 1 FROM takes WHERE job_id = ?", (job_id,)).fetchone() is None
        finally:
            db.close()
    except sqlite3.Error:
        return False


def refusal(h: Any, job_id: str) -> tuple[int, str] | None:
    """`(status, message)` when this caller may not read `job_id`, else None. 404 for another account's take, so the
    answer is the same as for a take that does not exist; a featured id is no exception (D4)."""
    if not jobs.JOB_ID_RE.match(job_id):
        return None
    owner = takes_on.owner(h.app, job_id)
    if owner is takes_on.UNKNOWN:
        return 503, MSG_OWNER_UNKNOWN
    if owner is None:  # P-N1: a people job, and a group take through it, has no takes row; its record names the owner
        owner = upload_owner.people_owner(h.app.queue, job_id)
        if owner is upload_owner.UNKNOWN:
            return 404, MSG_NOT_YOURS  # a people record without its owner is nobody's to read (fails closed)
        owner = owner or None  # "" is a people job made signed out: its id is its key
    if owner is None or auth.current_user(h) == owner:
        return None
    return 404, MSG_NOT_YOURS
