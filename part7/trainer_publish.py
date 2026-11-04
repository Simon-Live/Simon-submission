"""Who sees a new trainer movement (docs/specs/trainer-publish.md; #415 `trainer_public`, LEG-C1, LEG-H1).

One path for the publish choice (integration, 2026-11-03): this module reads the request, `entry_access` keeps the
answer (prod-data.md). `opt_in(doc)` is True only for an explicit `public: true` from an answer that is not 13 to 17;
the server passes it to `auth.on_entry(..., publish=...)`, and `entry_access.published_default` makes the movement
public when nothing is asked (`entry_access.open_by_default`, outside prod only) or the upload opted in. In prod the
`trainer_public` switch only pre-ticks the web's box; the server publishes on the upload's own answers. Otherwise the movement is private:
its signed-in owner sees it, or the device that holds the take's creator token (creator.py).

A 13 to 17 answer can never opt in, and in prod it signs in to record a movement (`refusal`). Later, the
owner's switch (`POST api/me/entries/<id> {"published": true}`) asks `publish_refused`: never for a movement made with a
13 to 17 answer, nor for an account that answered 13 to 17 on any movement or take it owns (private-default D1); the
account's row keeps that answer after the job records are swept (identity `age_band`, go-live R6).

Nobody under 18 in the video (privacy PM-B3, prod policy "minors never publish"): a public movement shows everyone in
its video, so `opt_in` also needs the uploader's statement `nobody_under_18: true` (a boolean) next to `public: true`;
without it the movement stays private. The access row records the statement (`entry_access` `nobody_under_18`), and a
later publish by the owner needs it on the row or in that request (`statement_missing`).

`minor_refused` is the one account check of the share, board, note and teacher routes (privacy PM-B1, PM-B2, PM-R1):
a 13 to 17 answer on the account, on a take or movement it owns, or on the job in hand; True when the store cannot say.
"""

from __future__ import annotations

import logging
from typing import Any, Mapping

from part7 import applog, auth, consent_record, entry_access, gpc

MSG_MINOR = "Sign in to record a movement. It stays private to you."
MSG_MINOR_PUBLISH = "Movements recorded by someone under 18 stay private."
MSG_STATEMENT = "Tick that nobody in the video is under 18 to show this movement to everyone."
STATEMENT = "nobody_under_18"


def _minor(doc: Mapping[str, Any]) -> bool:
    return consent_record.is_minor({"consent": consent_record.job_fields(doc).get("consent")})


def stated(doc: Mapping[str, Any] | None) -> bool:
    """True when the request carries the statement `nobody_under_18: true` (a boolean, PM-B3)."""
    return isinstance(doc, Mapping) and doc.get(STATEMENT) is True


def opt_in(doc: Mapping[str, Any]) -> bool:
    """True when the request asks to show the movement to everyone (`public: true`, a boolean), states that nobody in
    the video is under 18 (`nobody_under_18: true`, PM-B3) and the person is not 13 to 17."""
    return doc.get("public") is True and stated(doc) and not _minor(doc)


def statement_missing(state: Any, entry_id: str, doc: Mapping[str, Any] | None) -> bool:
    """True when the owner's publish of `entry_id` lacks the PM-B3 statement: not on its access row, not in `doc`.
    Never with the `trainer_public` switch on (outside prod every movement is public and nothing is asked)."""
    if entry_access.open_by_default():
        return False
    return not (stated(doc) or (entry_access.get(state, entry_id) or {}).get(STATEMENT) is True)


def minor_refused(h: Any, user_id: str | None, job: Mapping[str, Any] | None = None) -> bool:
    """True when nothing may be shared or shown to strangers for this caller (PM-B1, PM-B2, PM-R1, PM-R4): `job` carries
    a 13 to 17 answer, or the signed-in account is a minor (`owner_minor`). Fails closed when the store cannot say."""
    if consent_record.is_minor(job):
        return True
    if not user_id:
        return False
    try:
        return owner_minor(h.app, auth.identity(h.app), user_id)
    except Exception as exc:  # noqa: BLE001  fails closed: an unknown answer is not an adult's
        applog.log(f"trainer publish: could not read the age mark of an account ({type(exc).__name__})", level=logging.WARNING)
        return True


def choice(doc: Mapping[str, Any], headers: Any = None) -> bool | str:
    """The publish choice of a request: True for `opt_in`, `entry_access.GPC_PRIVATE` when the request carries Global
    Privacy Control without opting in (private whatever the default says), else False (the switch
    decides). go-live-readiness.md "GPC"."""
    if opt_in(doc):
        return True
    return entry_access.GPC_PRIVATE if headers is not None and gpc.signal(headers) else False


def refusal(doc: Mapping[str, Any], user_id: str | None) -> tuple[int, str] | None:
    """(status, message) when a trainer request cannot start for this caller; None when it may. In prod, a 13 to 17 answer signed out is refused: a minor's movement is kept by an account, never by a device key."""
    if user_id or entry_access.open_by_default() or not _minor(doc):
        return None
    return 401, MSG_MINOR


def account_minor(queue: Any, store: Any, user_id: str) -> bool:
    """True when the account's row keeps a 13 to 17 answer (identity `age_band`, go-live R6), or any take `user_id`
    owns, while its job record is kept, carries one."""
    if store.is_minor(user_id):
        return True
    for take in store.takes_of(user_id):
        if consent_record.is_minor(queue.get(take["job_id"])):
            return True
    return False


def owner_minor(app: Any, store: Any, user_id: str) -> bool:
    """The account rule of `publish_refused`, read once per request (go-live R3): a 13 to 17 answer on the account's row,
    a take or a movement it owns."""
    return account_minor(app.queue, store, user_id) or entry_access.owner_is_minor(app.state, user_id)


def publish_refused(app: Any, store: Any, entry_id: str, user_id: str, minor: bool | None = None) -> bool:
    """True when `user_id` may not make `entry_id` public (entry_access.publish_refused, or a 13 to 17 answer of
    theirs). `minor` is `owner_minor` when the caller already read it for this request."""
    minor = owner_minor(app, store, user_id) if minor is None else minor
    return minor or entry_access.publish_refused(app.state, entry_id, user_id, owner_minor=False)
