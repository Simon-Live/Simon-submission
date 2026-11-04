"""Who can see and join a board (docs/specs/board-visibility.md). `can_view` is the sole access check.

A board is `public` (anyone, with or without the link, listed on its movement) or `invited` ("People I choose": the owner
and the signed-in accounts whose verified address is on the board's invite list). A stored board without `visibility`
is public, which is the migration: no existing board changes who can see it.

Addresses: `identity.normalise_email` is the one rule (trim, NFKC, lower case, IDNA domain). It does no provider
aliasing, so `ann+x@example.com` and `ann@example.com` are two addresses, exactly as they are two accounts at sign-in;
the invite matches the address the person signs in with and nothing else. No answer carries an address except to the
board's owner (`owner_view`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from part7 import challenges, identity

PUBLIC, INVITED = "public", "invited"
MSG_SIGN_IN = "This board is for people the owner invited. Sign in with the email address the invite was sent to."
MSG_WRONG_ACCOUNT = ("This board is for people the owner invited. You are signed in with a different address. "
                     "Sign out, then sign in with the address the invite was sent to.")
MSG_OWNER_ONLY = "Only the person who made this board can change who sees it."
MSG_SIGN_IN_TO_CHOOSE = "Sign in to choose who sees a board."
MSG_NO_ADDRESS = "That does not look like an email address."


@dataclass(frozen=True)
class Viewer:
    """Who asks: the signed-in account and its verified address. `None` as a viewer means signed out."""
    user_id: str
    email: str | None


def visibility_of(board: dict[str, Any]) -> str:
    return INVITED if board.get("visibility") == INVITED and board.get("kind") != "sponsored" else PUBLIC


def invite_emails(board: dict[str, Any]) -> list[str]:
    return [str(i.get("email")) for i in board.get("invites") or [] if isinstance(i, dict) and i.get("email")]


def is_owner(board: dict[str, Any], viewer: Viewer | None) -> bool:
    return viewer is not None and bool(board.get("owner")) and viewer.user_id == board.get("owner")


def is_invited(board: dict[str, Any], viewer: Viewer | None) -> bool:
    email = identity.normalise_email(viewer.email) if viewer is not None else None
    return email is not None and email in invite_emails(board)


def can_view(board: dict[str, Any], viewer: Viewer | None) -> bool:
    """True for a public board, and for an invited board when the viewer is its owner or is signed in with an invited
    address. Signed out, a wrong account and a removed person all get False."""
    if visibility_of(board) == PUBLIC:
        return True
    return is_owner(board, viewer) or is_invited(board, viewer)


def viewer_of(h: Any) -> Viewer | None:
    """The request's viewer (cached on the handler), or None when signed out. A store fault reads as signed out."""
    if hasattr(h, "_board_viewer"):
        return h._board_viewer
    from part7 import auth
    found: Viewer | None = None
    user_id = auth.current_user(h)
    if user_id:
        try:
            user = auth.identity(h.app).user(user_id) or {}
        except Exception:
            user = {}
        found = Viewer(user_id, user.get("email"))
    h._board_viewer = found
    return found


def refusal(viewer: Viewer | None) -> tuple[int, str]:
    """The answer for a viewer `can_view` refused: 401 signed out, else 403. The words name neither the invited people
    nor whether this viewer's address is on the list."""
    return (403, MSG_WRONG_ACCOUNT) if viewer is not None else (401, MSG_SIGN_IN)


def role(board: dict[str, Any], viewer: Viewer | None) -> str | None:
    """`owner`, `guest` (an invited person) or None, for the page to show the right controls."""
    return "owner" if is_owner(board, viewer) else "guest" if is_invited(board, viewer) else None


def mark_joined(state: Any, board: dict[str, Any], viewer: Viewer | None) -> None:
    """The first time an invited person opens the board signed in, stamp `joined_at` on their invite."""
    email = identity.normalise_email(viewer.email) if viewer is not None else None
    if email is None or is_owner(board, viewer):
        return
    row = next((i for i in board.get("invites") or [] if i.get("email") == email), None)
    if row is None or row.get("joined_at"):
        return

    def stamp(doc: dict[str, Any]) -> None:
        for i in doc.get("invites") or []:
            if i.get("email") == email and not i.get("joined_at"):
                i["joined_at"] = challenges.stamp(datetime.now(timezone.utc))

    challenges.update(state, board["id"], stamp)


def clean_emails(raw: Any) -> tuple[list[str], list[str]]:
    """`(good, bad)` from a list of typed addresses: normalised, de-duplicated in order; `bad` keeps what was typed."""
    good: list[str] = []
    bad: list[str] = []
    for item in raw if isinstance(raw, list) else []:
        email = identity.normalise_email(item)
        if email is None:
            bad.append(str(item)[:80])
        elif email not in good:
            good.append(email)
    return good, bad


def set_access(state: Any, board_id: str, visibility: str | None, add: list[str], remove: list[str]) -> dict[str, Any]:
    """Apply an owner's change in one write: the visibility, addresses to add and addresses to remove. Switching to
    Public keeps the list, so switching back needs no retyping."""
    def change(doc: dict[str, Any]) -> None:
        if visibility is not None:
            doc["visibility"] = visibility
        rows = [i for i in doc.get("invites") or [] if i.get("email") not in remove]
        have = {i["email"] for i in rows}
        now = challenges.stamp(datetime.now(timezone.utc))
        rows += [{"email": e, "added_at": now, "joined_at": None, "mail": None} for e in add if e not in have]
        doc["invites"] = rows
    return challenges.update(state, board_id, change)[0]


def record_mail(state: Any, board_id: str, results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Keep the last mail state of each invite (`sent`, `failed` or `not_mailed`, and a failure id) for the owner's list."""
    def change(doc: dict[str, Any]) -> None:
        for i in doc.get("invites") or []:
            r = results.get(i.get("email"))
            if r:
                i["mail"], i["failure_id"] = r["state"], r.get("failure_id")
    challenges.update(state, board_id, change)
    return challenges.get(state, board_id) or {}


def owner_view(board: dict[str, Any]) -> dict[str, Any]:
    """The only answer that carries addresses: the owner's own list and who has joined."""
    rows = [{"email": i["email"], "joined": bool(i.get("joined_at")), "mail": i.get("mail"), "failure_id": i.get("failure_id")}
            for i in board.get("invites") or []]
    return {"visibility": visibility_of(board), "invites": rows}


def forget_address(state: Any, email: str) -> int:
    """Delete-my-data of an invited person: take `email` off every invite list; returns how many lists changed."""
    changed = 0
    target = identity.normalise_email(email)
    for doc in list(challenges.docs(state)):
        if target and target in invite_emails(doc):
            challenges.update(state, doc["id"], lambda d: d.__setitem__("invites", [i for i in d.get("invites") or [] if i.get("email") != target]))
            changed += 1
    return changed
