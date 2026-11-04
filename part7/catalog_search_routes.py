"""HTTP route `GET api/catalog/search` (docs/specs/catalog-search.md, TICKET-440); `server.py` calls `handle`.

It reads Part 6's list through the child, keeps what the caller may see (the same rules as the proxied list:
`auth.may_view_entry`, the policy switches, the test-entry rule of web/curation.js, the judge profile) and hands the
rows to `catalog_search`. Nothing is written. `no-store`: the answer depends on who asks.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from part7 import applog, auth, catalog_search as cs, challenge_visibility, challenges, entry_access, identity as ident, judge_view
from part7 import labels, prod_mode, takes_on

MSG_METHOD = "Method not allowed."
MSG_RATE = "Too many requests. Wait a little, then try again."
MSG_MINE = "Sign in to see your own movements."
MSG_DOWN = "The catalog is not answering. Try again in a moment."
HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}
PER_CLIENT = (120, 60)  # requests, seconds
_LIMIT: dict[int, auth.Limiter] = {}

# web/curation.js CURATED, HIDDEN_IDS and test rule, kept in step by tests/part7/test_catalog_search.py
CURATED = (
    "arm-wave", "hip-twist", "side-step", "shruti-floss", "part4-step-touch", "squat", "forward-lunge", "jumping-jack",
    "bodyweight-squat", "dance-expressions", "high-knees-class", "dumbbell-lateral-raise", "wall-push-up-home-programme",
    "power-jump", "body-squat-side-view", "bodyweight-squat-mm-fit-real-people",
)
HIDDEN_IDS = ("arm-salute",)
TEST_NAME = re.compile(r"^(verify|check-7)\b", re.IGNORECASE)
TEST_TAGS = ("verify", "check7", "check-7")


def _key(entry_id: str, keys: tuple[str, ...]) -> bool:
    return any(entry_id == k or entry_id.startswith(f"{k}-") for k in keys)


def is_test_entry(entry: dict[str, Any], tags: tuple[str, ...]) -> bool:
    """web/curation.js `isTestEntry`: flagged, named like a verify run, id of a verify, check-7 or QA run, or tagged so."""
    return (entry.get("hidden") is True or entry.get("test") is True
            or bool(TEST_NAME.match(str(entry.get("name") or "").strip()))
            or judge_view.is_test_id(entry.get("id")) or any(t in TEST_TAGS for t in tags))


def _reply(h: Any, status: int, doc: dict[str, Any], extra: dict[str, str] | None = None) -> None:
    h._send(status, json.dumps(doc).encode("utf-8"), "application/json; charset=utf-8", {**HEADERS, **(extra or {})})


def _refuse(h: Any, status: int, message: str, extra: dict[str, str] | None = None) -> None:
    _reply(h, status, {"ok": False, "error": message, "message": message}, extra)


def _credits(app: Any) -> dict[str, str]:
    """`{entry_id: "title creator"}` of the entries' source credits; empty when there is no identity store."""
    if not ident.db_path(app.state).is_file():
        return {}
    try:
        found = auth.identity(app).fetch("SELECT subject_id, title, creator FROM source_credits WHERE kind = 'entry'")
    except Exception as exc:  # search still works on titles and tags
        applog.log(f"catalog search: credits unreadable ({type(exc).__name__})", level=logging.WARNING)
        return {}
    return {str(r["subject_id"]): f"{r['title']} {r['creator']}" for r in found}


def _listed(entry_id: str, entry: dict[str, Any], tags: tuple[str, ...], *, owned: set[str], submission: bool,
            show_hidden: bool) -> bool:
    """True when the library lists this movement for this caller (web/curation.js `arrange`, judge-catalog.js)."""
    if (is_test_entry(entry, tags) or _key(entry_id, HIDDEN_IDS)) and not show_hidden:
        return False
    if submission:
        return entry_id in owned or (_key(entry_id, CURATED) and bool(entry.get("video_uri")))
    return True


def rows_for(h: Any, q: cs.Query, rehab_on: bool, user: str | None) -> list[cs.Row]:
    """The rows this caller may search. Raises `LookupError` when the catalog child does not answer."""
    app = h.app
    entries = app.child.list_entries()
    if entries is None:
        raise LookupError(MSG_DOWN)
    submission = judge_view.default_profile() == "submission" if q.submission is None else q.submission
    all_labels = labels.all_labels(app.state)
    credits = _credits(app)
    owned = set(entry_access.owned_by(app.state, user)) if user else set()
    viewer = challenge_visibility.viewer_of(h)  # a movement whose only board is invited reads as boardless to anyone else
    boards = {str(b.get("entry_id")) for b in challenges.list_all(app.state, keep=takes_on.board_keep(app), allow=lambda b: challenge_visibility.can_view(b, viewer))}
    takes = app.queue.follow_counts()
    minors: dict[str, bool] = {}
    show_hidden = bool(q.terms) and not submission and not prod_mode.is_prod()  # the web finds a verify run by name
    out = []
    for entry in entries:
        entry_id = entry.get("id") if isinstance(entry, dict) else None
        if not isinstance(entry_id, str) or not auth.may_view_entry(h, entry_id, minors):
            continue
        tags = tuple((all_labels.get(entry_id) or {}).get("tags") or ())
        if not _listed(entry_id, entry, tags, owned=owned, submission=submission, show_hidden=show_hidden):
            continue
        out.append(cs.row(entry, tags=tags, credit=credits.get(entry_id, ""), rehab_on=rehab_on, mine=entry_id in owned,
                          takes=takes.get(entry_id, 0), board=entry_id in boards))
    return out


def handle(h: Any, method: str, route: str) -> bool:
    """Answer `catalog/search` (below `api/`); False for any other route."""
    if route != "catalog/search":
        return False
    if method not in ("GET", "HEAD"):
        _refuse(h, 405, MSG_METHOD)
        return True
    if not _LIMIT.setdefault(id(h.app), auth.Limiter(*PER_CLIENT)).hit(auth.client_key(h)):
        _refuse(h, 429, MSG_RATE, {"Retry-After": str(PER_CLIENT[1])})
        return True
    rehab_on = prod_mode.policy("rehab")
    try:
        q = cs.parse(h.path.partition("?")[2], rehab_on)
    except cs.SearchError as exc:
        _refuse(h, 400, str(exc))
        return True
    user = auth.current_user(h)
    if q.mine and user is None:
        _refuse(h, 401, MSG_MINE)
        return True
    try:
        body = cs.run(rows_for(h, q, rehab_on, user), q)
    except LookupError as exc:
        _refuse(h, 503, str(exc))
        return True
    _reply(h, 200, {"ok": True, **body, "types_offered": [t for t in cs.TYPES if t != "rehab" or rehab_on]})
    return True
