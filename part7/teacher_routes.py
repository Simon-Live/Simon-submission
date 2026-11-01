"""HTTP route of the teacher page (docs/specs/teacher-dashboard.md); `server.py` calls `handle` with the other routes.

`GET api/teacher/<entry>` answers the takes and cues of finished follow jobs for one catalog movement. The path is
not `api/catalog/...` because `catalog/` is proxied to Part 6 before `_api` runs. No answer names a job, a person
or a path (challenges.md "Privacy": a job id is the follower's private key).
"""

from __future__ import annotations

from typing import Any

from part7 import auth, challenges, teacher_stats

MSG_NO_ENTRY = "This movement is not in the catalog."


def handle(h: Any, method: str, route: str) -> bool:
    """Answer `route` (below `api/`) when it belongs to the teacher page; False when it does not."""
    parts = route.split("/")
    if parts[0] != "teacher" or len(parts) != 2:
        return False
    if method not in ("GET", "HEAD"):
        h._error(405, "Method not allowed.")
        return True
    entry_id = parts[1]
    if (not challenges.ENTRY_ID_RE.match(entry_id) or h.app.child.get_entry(entry_id) is None
            or not auth.may_view_entry(h, entry_id)):  # an entry its owner marked "only me" (identity.md)
        h._error(404, MSG_NO_ENTRY)
        return True
    h._json(200, teacher_stats.collect(h.app.queue.root, entry_id))
    return True
