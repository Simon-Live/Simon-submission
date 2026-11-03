"""A follow take whose movement (catalog entry) the trainer deleted (TICKET-331, docs/specs/orphaned-take-result.md).

The job answer carries `entry_gone: true` for such a take, so the result page makes no catalog request and no
entry-dependent request (no 404 in the console). The check reads the catalog folder, as `narration_routes.has_narration`
does; a missing or malformed entry id is never called gone.
"""

from __future__ import annotations

from typing import Any

from part7 import labels


def entry_gone(h: Any, entry_id: Any) -> bool:
    """True when `entry_id` names a well-formed entry whose folder is no longer in the catalog."""
    if not isinstance(entry_id, str) or not labels.ENTRY_ID_RE.match(entry_id):
        return False
    return not (h.app.child.catalog_dir / entry_id).is_dir()
