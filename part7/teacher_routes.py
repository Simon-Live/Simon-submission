"""HTTP route of the teacher page (docs/specs/teacher-dashboard.md); `server.py` calls `handle` with the other routes.

`GET api/teacher/<entry>` answers the takes and cues of finished follow jobs for one catalog movement, and its class
table (docs/specs/class-table.md). The path is
not `api/catalog/...` because `catalog/` is proxied to Part 6 before `_api` runs. No answer names a job, a person
or a path (challenges.md "Privacy": a job id is the follower's private key).

Shared with the teacher (operator ruling 2026-11-03, private-default D3, prod-data.md "Teacher page"): the per-take
rows go to the movement's signed-in owner alone, and only for takes their owners shared; everyone else gets the count
of shared takes. `GET api/teacher/<entry>/shares` lists the caller's own takes of the movement with that choice, and
`POST api/teacher/<entry>/shares {job_id, shared}` sets it for one of them (the take's owner only). Sharing is 403
`MSG_MINOR` for an account marked 13 to 17 or a take with that answer (privacy PM-R1); unsharing is never refused.
"""

from __future__ import annotations

from typing import Any

from part7 import attribution, auth, auth_routes, challenges, history_store, identity, my_reference, teacher_stats, trainer_publish

MSG_NO_ENTRY = "This movement is not in the catalog."
MSG_NO_TAKE = "This take is not available."
MSG_MINOR = "Sharing takes is off for anyone under 18."
SUBS = ("author", "shares")


def _shareable(job: Any, entry_id: str) -> bool:
    """A finished solo follow take of this movement that the teacher page could show (not private, not own reference)."""
    return (isinstance(job, dict) and job.get("kind") == "follow" and job.get("status") == "done"
            and job.get("entry_id") == entry_id and not history_store.is_private(job) and not my_reference.uses_own(job))


def _own_takes(h: Any, user_id: str, entry_id: str) -> list[dict[str, Any]]:
    """The caller's shareable takes of `entry_id`, newest first, each with its share choice."""
    out = []
    for take in auth.identity(h.app).takes_of(user_id):
        job = h.app.queue.get(take["job_id"]) if take["kind"] == "follow" and take["entry_id"] == entry_id else None
        if _shareable(job, entry_id):
            out.append({"job_id": take["job_id"], "at": job.get("finished_at") or job.get("created_at") or "",
                        "shared": teacher_stats.shared_with_teacher(h.app.queue.job_dir(take["job_id"]))})
    return sorted(out, key=lambda r: (str(r["at"]), r["job_id"]), reverse=True)


def _shares(h: Any, method: str, entry_id: str) -> None:
    if method == "POST":
        doc = auth_routes.guarded_body(h)
        if doc is None:
            return
    user_id = auth.current_user(h)
    if user_id is None:
        return h._error(401, auth_routes.MSG_SIGN_IN)
    if method != "POST":
        return h._json(200, {"takes": _own_takes(h, user_id, entry_id)})
    job_id, shared = doc.get("job_id"), doc.get("shared")
    if not isinstance(job_id, str) or not isinstance(shared, bool):
        return h._error(400, auth_routes.MSG_BAD)
    try:
        owner = auth.identity(h.app).owner_of(job_id)
    except Exception:  # noqa: BLE001  the store did not answer: nothing changes (fails closed)
        return h._error(503, MSG_NO_TAKE)
    if owner != user_id or not _shareable(h.app.queue.get(job_id), entry_id):  # the same 404 for missing and not yours
        return h._error(404, MSG_NO_TAKE)
    if shared and trainer_publish.minor_refused(h, user_id, h.app.queue.get(job_id)):  # PM-R1
        return h._error(403, MSG_MINOR)
    teacher_stats.set_shared(h.app.queue.job_dir(job_id), shared)
    h._json(200, {"job_id": job_id, "shared": shared})


def handle(h: Any, method: str, route: str) -> bool:
    """Answer `route` (below `api/`) when it belongs to the teacher page; False when it does not."""
    parts = route.split("/")
    if parts[0] != "teacher" or len(parts) not in (2, 3) or (len(parts) == 3 and parts[2] not in SUBS):
        return False
    shares = len(parts) == 3 and parts[2] == "shares"
    if method not in ("GET", "HEAD") and not (shares and method == "POST"):
        h._error(405, "Method not allowed.")
        return True
    entry_id = parts[1]
    if (not challenges.ENTRY_ID_RE.match(entry_id) or h.app.child.get_entry(entry_id) is None
            or not auth.may_view_entry(h, entry_id)):  # an entry its owner marked "only me" (identity.md)
        h._error(404, MSG_NO_ENTRY)
        return True
    if shares:
        _shares(h, method, entry_id)
        return True
    if len(parts) == 3:  # the author line alone, for the watch and follow screens (no take stats read)
        h._json(200, {"attribution": attribution.for_entry(h, entry_id)})
        return True
    owners = identity.follow_owners(h.app.state, entry_id)  # groups takes by follower inside class_table; never answered
    line = attribution.for_entry(h, entry_id)
    # the shared takes' rows go to the entry's signed-in owner alone (`mine`, fails closed); everyone else gets the count
    # of shared takes on the same public page, never a 401 (D3, class-table.md "Who sees what")
    mine = line.get("mine") is True
    h._json(200, {**teacher_stats.page(h.app.queue.root, entry_id, owners, with_followers=mine), "attribution": line})
    return True
