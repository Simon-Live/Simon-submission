"""Finding leaderboards (docs/specs/board-discovery.md, TICKET-431): the lists the movement page, the result, Me and
home show, so a person can open a board without a link.

Three reads, one card shape, no write:
`GET api/movements/<id>/boards`, `GET api/boards` (home) and `GET api/me/boards` (Me). A card is
`{id, title, kind, visibility, ends_at, ended, entries, viewer_rank, top: [{name, score_label}], url}`: no email, no job
id, no pid. Who may see a board is decided by `_viewable` alone (the visibility lane replaces its one line with
`challenge_visibility.can_view`); ranking is `challenges.ranked`, untouched.

"The viewer's" entries are the ones on a take the caller owns (signed in) or on a take this browser named in `?jobs=`
that nobody owns (takes_on.device_ids), the same two ways `api/takes-on` finds "your takes".
"""

from __future__ import annotations

from typing import Any, Callable
from urllib.parse import parse_qsl, urlsplit

from part7 import auth, challenge_visibility as vis, challenges, judge_view, takes_on

TOP = 3        # names on a card
LIMIT = 50     # cards in one answer
HOME_LIMIT = 6  # cards on home


def _viewable(board: dict[str, Any], viewer: Any) -> bool:
    """True when `viewer` (the request handler) may see `board` on a list: the board is shown, its movement is one they may
    view (ADR-0019, D6), and challenge_visibility.can_view, the one check of who sees a board, says yes."""
    return (challenges.shown(board) and auth.may_view_entry(viewer, str(board.get("entry_id")))
            and vis.can_view(board, vis.viewer_of(viewer)))


def score_label(entry: dict[str, Any]) -> str:
    """The board row's score as the result headline words it ("9,249 points of 12,160"), else the plain score."""
    s = entry.get("shown")
    if isinstance(s, dict) and isinstance(s.get("figures"), str):
        cap = f" {s['caption']}" if s.get("caption") else ""
        return f"{s['figures']} points{cap}" if s.get("unit") == "points" else f"{s['figures']}{cap}"
    return str(entry.get("score"))


def _mine(h: Any, device: list[str]) -> set[str]:
    """The job ids this caller's entries came from: their account's takes, and the unowned ones this browser named."""
    user, out = auth.current_user(h), set()
    if user is not None:
        out |= {t["job_id"] for t in auth.identity(h.app).takes_of(user)}
    out |= {j for j in device if takes_on.keyed_by_id(h.app, j, user)}
    return out


def _is_mine(entry: dict[str, Any], mine: set[str], user: str | None) -> bool:
    return entry.get("job_id") in mine or (user is not None and challenges.is_of(entry, user))


def _card(doc: dict[str, Any], keep: Any, mine: set[str], user: str | None = None) -> dict[str, Any]:
    board = challenges.ranked(challenges._kept(doc, keep))  # raw entries (job ids stay here, never in the answer)
    ranks = [e["rank"] for e in board if _is_mine(e, mine, user)]
    return {
        "id": doc["id"], "title": challenges.masked(doc["title"], "Challenge"), "kind": doc["kind"], "creator": challenges.masked(doc.get("creator_name")),
        "mine": user is not None and doc.get("owner") == user, "visibility": vis.visibility_of(doc),
        "ends_at": doc.get("ends_at"), "ended": challenges.ended(doc), "entries": len(board),
        "viewer_rank": min(ranks) if ranks else None,
        "top": [{"name": challenges.masked(e["name"]), "score_label": score_label(e)} for e in board[:TOP] if not is_capped(e)],
        "url": f"#/challenge/{doc['id']}",
    }


def is_capped(entry: dict[str, Any]) -> bool:
    return bool((entry.get("shown") or {}).get("capped"))  # one-letter.md L6: a capped take never heads a list


def _order(card: dict[str, Any]) -> tuple[bool, int]:
    return (card["ended"], -card["entries"])  # open boards first, the busiest first


def boards(h: Any, *, entry_id: str | None, device: list[str], only_mine: bool = False, limit: int = LIMIT, judge: bool = False) -> list[dict[str, Any]]:
    """The cards the caller may see: open ones first, ended ones after. `only_mine`: made by the caller or holding their entry."""
    keep, mine, user = takes_on.board_keep(h.app, entry_id), _mine(h, device), auth.current_user(h)
    out = []
    for doc in challenges._docs(h.app.state):
        if entry_id is not None and doc.get("entry_id") != entry_id:
            continue
        if not _viewable(doc, h) or (judge and judge_view.is_test_challenge(doc)):  # the judge view leaves test boards out
            continue
        card = _card(doc, keep, mine, user)
        if only_mine and card["viewer_rank"] is None and not (user is not None and doc.get("owner") == user):
            continue
        out.append(card)
    out.sort(key=lambda c: (_order(c), c["id"]))
    return out[:limit]


def annotate(h: Any, doc: dict[str, Any], out: dict[str, Any], keep: Any) -> dict[str, Any]:
    """`out` (challenges.view of `doc`) with `you` on the caller's rows and `can_manage` for the board's maker. The rows
    keep the order of challenges.view, so they pair with the ranked raw entries one for one; no id leaves the server."""
    user, mine = auth.current_user(h), _mine(h, _device(h))
    raw = challenges.ranked(challenges._kept(doc, keep))
    for row, entry in zip(out["entries"], raw):
        row["you"] = _is_mine(entry, mine, user)
    return {**out, "can_manage": user is not None and doc.get("owner") == user}


def _query(h: Any) -> dict[str, str]:
    return dict(parse_qsl(urlsplit(h.path).query))


def _device(h: Any) -> list[str]:
    return takes_on.device_ids(_query(h).get("jobs"))


def handle(h: Any, method: str, route: str, may_view_movement: Callable[[Any, Any], bool]) -> bool:
    """Answer the three list routes (below `api/`); False when `route` is not one of them."""
    parts = route.split("/")
    movement = len(parts) == 3 and parts[0] == "movements" and parts[2] == "boards"
    if not (movement or parts in (["boards"], ["me", "boards"])):
        return False
    if method not in ("GET", "HEAD"):
        h._error(405, "Method not allowed.")
        return True
    query = _query(h)
    device, judge = _device(h), query.get("view") == judge_view.VIEW_JUDGE
    if movement and not may_view_movement(h, parts[1]):
        h._error(404, "This movement is not in the catalog.")  # a private movement answers as a missing one
    elif parts == ["me", "boards"]:
        h._json(200, {"boards": boards(h, entry_id=None, device=device, judge=judge, only_mine=True)})
    else:
        h._json(200, {"boards": boards(h, entry_id=parts[1] if movement else None, device=device, judge=judge,
                                       limit=LIMIT if movement else HOME_LIMIT)})
    return True
