"""The link preview of a board (docs/specs/board-discovery.md AC-P1 to AC-P5, TICKET-431): `GET <base>c/<id>`.

A shared board link used to be `<app>#/challenge/<id>`; a fragment never reaches a server, so a chat app showed the generic
Simon card. `c/<id>` is a small server-rendered page: Open Graph tags for the crawler, and a meta refresh that sends a person
on to `#/challenge/<id>` in the app, where the board's own access check still applies.

Only a public board on a movement the caller may view gets its title, count and top score in the tags. A private (invited),
missing, sponsored-off or unviewable board gets the same generic Simon page, so the preview never says a board exists.
The image is the site's og-image at an absolute URL (a crawler cannot use a relative one).
"""

from __future__ import annotations

import html
import re
from typing import Any

from part7 import auth, board_discovery, challenge_visibility as vis, challenges, takes_on

ID_RE = re.compile(r"c/([A-Za-z0-9_-]{11})/?")
GENERIC_TITLE = "Simon"
GENERIC_TEXT = "Find your way to move. Record a movement once and Simon checks yours against it."
IMAGE = "icons/og-image.png"


def _facts(h: Any, board: dict[str, Any] | None) -> tuple[str, str]:
    """`(title, description)`: the board's own only for a public board the caller may see; else the generic words."""
    if board is None or not challenges.shown(board) or not vis.can_view(board, None) or not auth.may_view_entry(h, str(board["entry_id"])):
        return GENERIC_TITLE, GENERIC_TEXT
    rows = challenges.ranked(challenges._kept(board, takes_on.board_keep(h.app, board["entry_id"])))
    top = next((e for e in rows if not board_discovery.is_capped(e)), None)
    count = f"{len(rows)} {'person is' if len(rows) == 1 else 'people are'} on this leaderboard."
    lead = f" Top score {board_discovery.score_label(top)}." if top else ""
    return str(challenges.masked(board["title"], "Challenge")), f"{count}{lead} Can you beat it?"


def render(h: Any, board_id: str) -> bytes:
    board = challenges.get(h.app.state, board_id)
    title, text = _facts(h, board)
    base = h.app.base if h.app.base.endswith("/") else h.app.base + "/"
    origin = auth.public_origin(h)
    e = html.escape
    tags = [f'<meta property="og:title" content="{e(title)}">', f'<meta property="og:description" content="{e(text)}">',
            '<meta property="og:type" content="website">', '<meta name="twitter:card" content="summary_large_image">']
    if origin:  # without a trusted origin there is no honest absolute URL, so no image and no og:url
        tags += [f'<meta property="og:url" content="{e(origin + base + "c/" + board_id)}">',
                 f'<meta property="og:image" content="{e(origin + base + IMAGE)}">',
                 '<meta property="og:image:width" content="1200">', '<meta property="og:image:height" content="630">']
    target = f"{base}#/challenge/{board_id}"
    page = ('<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            f"<title>{e(title)}</title>{''.join(tags)}"
            f'<meta http-equiv="refresh" content="0;url={e(target)}"></head>'
            f'<body><p><a href="{e(target)}">Open the leaderboard in Simon</a></p></body></html>')
    return page.encode("utf-8")


def page(h: Any, rest: str) -> bool:
    """Answer `c/<id>` (below the base path); False for any other path."""
    found = ID_RE.fullmatch(rest)
    if not found:
        return False
    h._send(200, render(h, found.group(1)), "text/html; charset=utf-8")
    return True
