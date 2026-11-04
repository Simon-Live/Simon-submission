"""Global Privacy Control (docs/specs/go-live-readiness.md "GPC"; HARDENING 8.9).

Simon sells nothing and shares nothing for advertising, so the signal has no sale to stop. It is honoured as a no to
the optional sharing and the optional analytics the app does: a request that carries `Sec-GPC: 1`

- makes a new trainer movement private unless that same request ticks "Show this movement to everyone"
  (`trainer_publish.choice`, `entry_access.published_default`), whatever the `trainer_public` switch says;
- has its usage events to `api/client-log` (an event that is not the error report `client_error`) answered and
  not written to the log (`client_log.handle`).

The browser side (`web/api.js` `gpcOn`) reads `navigator.globalPrivacyControl` and sends no usage event at all.
"""

from __future__ import annotations

from typing import Any, Mapping

HEADER = "Sec-GPC"


def signal(headers: Mapping[str, Any] | Any) -> bool:
    """True when the request carries `Sec-GPC: 1` (the only value the GPC specification defines)."""
    try:
        value = headers.get(HEADER)
    except AttributeError:
        return False
    return isinstance(value, str) and value.strip() == "1"
