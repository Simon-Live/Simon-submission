"""Who made what: the author line of an entry, a take, a result or a report (docs/specs/attribution.md).

Nothing is copied into entries, takes or reports. The name is read at request time from the owner's profile
(`part7.profile.public_identity`), so a rename or "Delete my profile details" shows on the next request. A subject
is a dict: `kind` ("entry" or "take"), `user_id`, `author_state` ("owned" or "unattributed") and, for a take, the
`trainer` subject (the entry's owner facts, or None). An unattributed subject shows no name. Never an email.
"""

from __future__ import annotations

import logging
from typing import Any

from part7 import applog, auth
from part7 import identity as ident

try:  # lane as-profile-server builds part7/profile.py; until it is merged everyone is unnamed
    from part7 import profile as _profile
except ImportError:  # pragma: no cover - the absent module is exercised by a monkeypatch in the tests
    _profile = None

UNNAMED = {"name": None, "avatar": None, "credit_as_trainer": False}


def _identity(db: Any, user_id: str) -> dict[str, Any]:
    """The public identity of `user_id`; unnamed when the profile module is missing or errs (fail closed)."""
    if _profile is None or not user_id:
        return dict(UNNAMED)
    try:
        found = _profile.public_identity(db, user_id)
    except Exception as exc:  # a profile fault must not break an entry, a result or a report
        applog.log(f"attribution: profile lookup failed ({type(exc).__name__})", level=logging.WARNING)
        return dict(UNNAMED)
    name = found.get("name")
    return {"name": name if isinstance(name, str) and name.strip() else None, "avatar": found.get("avatar"),
            "credit_as_trainer": bool(found.get("credit_as_trainer"))}


def _person(db: Any, subject: dict[str, Any] | None, trainer: bool) -> dict[str, Any] | None:
    """`{"name", "avatar"}` of an owned subject, or None when unattributed. A trainer is named only when they opted in."""
    if not subject or subject.get("author_state") != "owned" or not subject.get("user_id"):
        return None
    who = _identity(db, subject["user_id"])
    named = who["name"] if (not trainer or who["credit_as_trainer"]) else None
    return {"name": named, "avatar": who["avatar"] if named else None}


def author_line(db: Any, entry_or_take: dict[str, Any]) -> dict[str, Any]:
    """`{"author": {name, avatar} | None, "trainer_credit": {name, avatar} | None}` for one subject.

    An entry's author is its trainer, named only with `credit_as_trainer`. A take's author is its follower, named
    only with the profile's public name; its trainer credit appears only when the entry is owned, not "only me"
    and the trainer opted in with a public name. Unattributed: `author` is None (shown with no name).
    """
    subject = entry_or_take or {}
    is_entry = subject.get("kind") == "entry"
    author = _person(db, subject, trainer=is_entry)
    credit = None
    trainer = subject.get("trainer")
    if not is_entry and trainer and not trainer.get("only_me"):
        person = _person(db, trainer, trainer=True)
        credit = person if person and person["name"] else None
    return {"author": author, "trainer_credit": credit}


def payload(db: Any, subject: dict[str, Any], viewer: str | None) -> dict[str, Any]:
    """The `attribution` field: `kind`, `author`, `trainer_credit` and `mine` (the viewer is the author)."""
    line = author_line(db, subject)
    mine = bool(viewer and subject.get("author_state") == "owned" and subject.get("user_id") == viewer)
    return {"kind": subject.get("kind", "take"), **line, "mine": mine}


def _store(app: Any) -> ident.IdentityStore | None:
    if not ident.db_path(app.state).is_file():
        return None
    try:
        return auth.identity(app)
    except Exception as exc:
        applog.log(f"attribution: identity store unavailable ({type(exc).__name__})", level=logging.WARNING)
        return None


def entry_subject(store: Any, entry_id: str) -> dict[str, Any]:
    """The subject of a catalog entry; an entry with no row (made signed out) is unattributed."""
    row = store.entry_author(entry_id) if store is not None else None
    if row is None:
        return {"kind": "entry", "user_id": "", "author_state": "unattributed"}
    return {"kind": "entry", "user_id": row["user_id"], "author_state": row["author_state"], "only_me": row["only_me"]}


def take_subject(store: Any, job_id: str | None, entry_id: str | None, owner: str | None = None) -> dict[str, Any]:
    """The subject of a follower take: its owner (None for an anonymous follower) and the entry's trainer facts."""
    who = owner if owner is not None else (store.owner_of(job_id) if store is not None and job_id else None)
    trainer = entry_subject(store, entry_id) if store is not None and entry_id else None
    return {"kind": "take", "user_id": who or "", "author_state": "owned" if who else "unattributed", "trainer": trainer}


def for_entry(h: Any, entry_id: str) -> dict[str, Any]:
    """`attribution` of an entry for the request `h`; fails closed to an unattributed, nameless payload."""
    return _safe(h, lambda store: entry_subject(store, entry_id), "entry")


def for_take(h: Any, job_id: str | None, entry_id: str | None, owner: str | None = None) -> dict[str, Any]:
    """`attribution` of a follower take, result or report for the request `h`."""
    return _safe(h, lambda store: take_subject(store, job_id, entry_id, owner), "take")


def _safe(h: Any, build: Any, kind: str) -> dict[str, Any]:
    store = _store(h.app)
    try:
        return payload(store, build(store), auth.current_user(h))
    except Exception as exc:
        applog.log(f"attribution: could not build the author line ({type(exc).__name__})", level=logging.WARNING)
        return {"kind": kind, "author": None, "trainer_credit": None, "mine": False}
