"""HTTP route of the teacher page (docs/specs/teacher-dashboard.md); `server.py` calls `handle` with the other routes.

`GET api/teacher/<entry>` answers the takes and cues of finished follow jobs for one catalog movement, and its class
table (docs/specs/class-table.md). The path is
not `api/catalog/...` because `catalog/` is proxied to Part 6 before `_api` runs. No answer names a job, a person
or a path (challenges.md "Privacy": a job id is the follower's private key).
"""

from __future__ import annotations

from typing import Any

from part7 import attribution, auth, challenges, identity, teacher_stats

MSG_NO_ENTRY = "This movement is not in the catalog."


def handle(h: Any, method: str, route: str) -> bool:
    """Answer `route` (below `api/`) when it belongs to the teacher page; False when it does not."""
    parts = route.split("/")
    if parts[0] != "teacher" or len(parts) not in (2, 3) or (len(parts) == 3 and parts[2] != "author"):
        return False
    if method not in ("GET", "HEAD"):
        h._error(405, "Method not allowed.")
        return True
    entry_id = parts[1]
    if (not challenges.ENTRY_ID_RE.match(entry_id) or h.app.child.get_entry(entry_id) is None
            or not auth.may_view_entry(h, entry_id)):  # an entry its owner marked "only me" (identity.md)
        h._error(404, MSG_NO_ENTRY)
        return True
    if len(parts) == 3:  # the author line alone, for the watch and follow screens (no take stats read)
        h._json(200, {"attribution": attribution.for_entry(h, entry_id)})
        return True
    owners = identity.follow_owners(h.app.state, entry_id)  # groups takes by follower inside class_table; never answered
    line = attribution.for_entry(h, entry_id)
    # each follower's scores go to the entry's signed-in owner alone (`mine`, fails closed); everyone else gets the
    # class-level facts on the same public page, never a 401 (class-table.md "Who sees what")
    mine = line.get("mine") is True
    h._json(200, {**teacher_stats.page(h.app.queue.root, entry_id, owners, with_followers=mine), "attribution": line})
    return True
