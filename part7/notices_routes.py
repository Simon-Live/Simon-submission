"""GET api/notices: the third-party notices of the running build as plain text (version-footer.md AC-F6, TICKET-326).

The footer's Licences link opens this, so the notices always match the commit that is live, not upstream main.
"""

from __future__ import annotations

from typing import Any

from part7 import config

NOTICES = config.REPO_ROOT / "THIRD_PARTY_NOTICES.md"
MSG_NO_NOTICES = "The licence notices are not in this build."


def handle(h: Any, method: str, route: str) -> bool:
    """Answer `route` (below `api/`) when it is `notices`; False when it is not."""
    if route != "notices":
        return False
    if method not in ("GET", "HEAD"):
        h._error(405, "Method not allowed.")
        return True
    try:
        body = NOTICES.read_bytes()
    except OSError:
        h._error(404, MSG_NO_NOTICES)
        return True
    h._send(200, body, "text/plain; charset=utf-8")
    return True
