"""GET api/policy and the legal pages (docs/specs/consent-and-age.md, docs/specs/legal-pages.md).

`api/policy` tells the web app which prod switches are on (part7/prod_mode.py, #415), whether the consent and age step
is required, and the consent version it must show. It carries no secret and nothing about the visitor.
`page` answers `/privacy`, `/terms` and the other drafts of `docs/legal/` as HTML; `api/legal/<name>` is the same page.
"""

from __future__ import annotations

from typing import Any

from part7 import consent_record, legal_pages, licence_gates, muse_prod, person_check, prod_mode

SWITCHES = tuple(prod_mode.PROD_DEFAULTS)
MSG_NO_PAGE = "This page is not in this build."


def policy_doc() -> dict[str, Any]:
    return {
        "prod": prod_mode.is_prod(),
        "switches": {name: muse_prod.open_now() if name == muse_prod.SWITCH else prod_mode.policy(name) for name in SWITCHES},
        "phrasing_live": licence_gates.phrasing_live_allowed(),
        "person_check": person_check.available(),  # false: a picture is never checked, so the web asks who it shows up front
        "consent": {"required": consent_record.required(), "version": consent_record.VERSION,
                    "items": list(consent_record.ITEMS), "meta_item": consent_record.META_ITEM if muse_prod.open_now() else None, "header": consent_record.UPLOAD_HEADER},
        "age": {"minimum": consent_record.min_age(), "adult": consent_record.ADULT_AGE},
        "pages": list(legal_pages.PAGES),
    }


def _page(h: Any, method: str, name: str) -> None:
    if method not in ("GET", "HEAD"):
        h._error(405, "Method not allowed.")
        return
    body = legal_pages.render(name)
    if body is None:
        h._error(404, MSG_NO_PAGE)
        return
    h._send(200, body, "text/html; charset=utf-8")


def handle(h: Any, method: str, route: str) -> bool:
    """Answer `route` (below `api/`) when it is `policy` or `legal/<name>`; False when it is not."""
    parts = route.split("/")
    if route == "policy":
        if method not in ("GET", "HEAD"):
            h._error(405, "Method not allowed.")
        else:
            h._json(200, policy_doc())
        return True
    if len(parts) == 2 and parts[0] == "legal":
        _page(h, method, parts[1])
        return True
    return False


def page(h: Any, rest: str) -> bool:
    """Answer a top-level page path (`privacy`, `terms`, ...; below the base path, no `api/`); False for any other path."""
    name = rest.rstrip("/")
    if name not in legal_pages.PAGES:
        return False
    _page(h, h.command, name)
    return True
