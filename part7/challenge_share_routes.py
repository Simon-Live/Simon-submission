"""Routes that set who sees a board and mail the invites (docs/specs/board-visibility.md).

`POST|GET api/challenges/<id>/access` (the owner only): the visibility, the addresses to add, remove or mail again, and the
owner's list with who has joined. `GET|POST api/invites/stop/<key>`: the stop link in every invite mail, honoured by the
server (`invite_mail.stop`). Addresses are in request bodies only, never in a path, so no log line holds one.
"""

from __future__ import annotations

import html
from typing import Any

from part7 import auth, challenge_visibility as vis, challenges, entry_access, invite_mail

MSG_CHALLENGE = "This challenge was not found."
MSG_VISIBILITY = "Choose Public, or People I choose."
MSG_STOPPED = "Done. Simon will not mail you invites again."
MSG_STOP_UNKNOWN = "This stop link is not valid. Write to privacy@simon.live and we will stop the mail by hand."
MSG_PRIVATE_MOVEMENT = ("This movement is private, so only you can see this board until you publish the movement. "
                        "People you invite can open the board but cannot see the movement or take part.")
PAGE = ("<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
        "<title>Stop invites from Simon</title><main style='font:16px system-ui;max-width:32rem;margin:3rem auto;padding:0 1rem'>{body}</main>")


def board_link(h: Any, board_id: str) -> str | None:
    origin = auth.public_origin(h)
    return None if origin is None else f"{origin}{h.app.base}#/challenge/{board_id}"


def movement_open(h: Any, entry_id: str) -> bool:
    """True when someone who is not the movement's owner could see the movement (it is published and not 'only me')."""
    try:
        if not entry_access.visible(h.app.state, entry_id, None, None, getattr(getattr(h.app, "child", None), "catalog_dir", None)):
            return False
        from part7 import identity
        if identity.db_path(h.app.state).is_file():
            found = auth.identity(h.app).entry_owner(entry_id)
            return found is None or not found[1]
        return True
    except Exception:
        return False


def mail_invites(h: Any, board: dict[str, Any], emails: list[str]) -> list[dict[str, Any]]:
    """Mail each address its invite and keep each result on the board. `[{email, state, failure_id?}]`; the owner's own
    address is skipped. `state` is `sent` only when the provider accepted."""
    viewer = vis.viewer_of(h)
    mine = (viewer.email if viewer else None) or ""
    origin, link = auth.public_origin(h), board_link(h, board["id"])
    out: dict[str, dict[str, Any]] = {}
    for email in emails:
        if email == mine:
            continue
        out[email] = invite_mail.send_one(h.app, email, board["owner"], board.get("creator_name"), board.get("title"), link, origin)
    if out:
        vis.record_mail(h.app.state, board["id"], out)
    return [{"email": e, **r} for e, r in out.items()]


def access_doc(h: Any, board: dict[str, Any], mail: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """The owner's answer: the list, the board link (to copy when a mail failed), and a warning for a private movement."""
    fresh = challenges.get(h.app.state, board["id"]) or board
    private = not movement_open(h, fresh["entry_id"])
    return {**vis.owner_view(fresh), "link": board_link(h, fresh["id"]), "mail": mail or [],
            "movement_private": private, "warning": MSG_PRIVATE_MOVEMENT if private else None}


def parse_change(doc: dict[str, Any]) -> tuple[str | None, list[str], list[str], list[str]]:
    """`(visibility, add, remove, resend)` from an access request; ValueError(message) for a bad one."""
    visibility = doc.get("visibility")
    if visibility is not None and visibility not in (vis.PUBLIC, vis.INVITED):
        raise ValueError(MSG_VISIBILITY)
    lists = []
    for field in ("add", "remove", "resend"):
        good, bad = vis.clean_emails(doc.get(field))
        if bad:
            raise ValueError(vis.MSG_NO_ADDRESS)
        lists.append(good)
    return visibility, lists[0], lists[1], lists[2]


def _owned(h: Any, board_id: str) -> dict[str, Any] | None:
    """The board when the caller owns it; else answers 401, 403 or 404 and returns None."""
    board = challenges.get(h.app.state, board_id)
    if not challenges.shown(board):
        h._error(404, MSG_CHALLENGE)
        return None
    viewer = vis.viewer_of(h)
    if viewer is None:
        h._error(401, vis.MSG_SIGN_IN_TO_CHOOSE)
    elif not vis.can_view(board, viewer):
        h._error(*vis.refusal(viewer))
    elif not vis.is_owner(board, viewer):
        h._error(403, vis.MSG_OWNER_ONLY)
    else:
        return board
    return None


def _access(h: Any, method: str, board_id: str) -> None:
    from part7 import challenge_routes
    if method == "POST" and not auth.origin_ok(h):
        return h._error(403, "The request did not come from this page.")
    body = challenge_routes._body(h) if method == "POST" else {}
    if body is None:
        return
    board = _owned(h, board_id)
    if board is None:
        return
    if method != "POST":
        return h._json(200, access_doc(h, board))
    try:
        visibility, add, remove, resend = parse_change(body)
    except ValueError as exc:
        return h._error(400, str(exc))
    after = vis.set_access(h.app.state, board_id, visibility, add, remove)
    results = []
    if body.get("mail", True) is not False:
        known = set(vis.invite_emails(after))
        results = mail_invites(h, after, [e for e in dict.fromkeys(add + resend) if e in known])
    h._json(200, access_doc(h, after, results))


def _stop(h: Any, method: str, key: str) -> None:
    if method == "POST":
        h.close_connection = True  # a mail client's one-click POST has a body this route does not read
        h._send(200 if invite_mail.stop(h.app.state, key) else 404, PAGE.format(body=html.escape(
            MSG_STOPPED if invite_mail.stopped(h.app.state, key) else MSG_STOP_UNKNOWN)).encode("utf-8"), "text/html; charset=utf-8")
        return
    form = ("<h1>Stop invites from Simon?</h1><p>You will get no more challenge invites from Simon at this address.</p>"
            "<form method=post action=''><button type=submit>Stop invites</button></form>")
    h._send(200, PAGE.format(body=form).encode("utf-8"), "text/html; charset=utf-8")


def handle(h: Any, method: str, route: str) -> bool:
    """Answer the access and stop routes; False when `route` is neither."""
    parts = route.split("/")
    if len(parts) == 3 and parts[0] == "challenges" and parts[2] == "access" and method in ("GET", "HEAD", "POST"):
        _access(h, "POST" if method == "POST" else "GET", parts[1])
        return True
    if len(parts) == 3 and parts[:2] == ["invites", "stop"] and method in ("GET", "HEAD", "POST"):
        _stop(h, "POST" if method == "POST" else "GET", parts[2])
        return True
    return False
