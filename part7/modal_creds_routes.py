"""`api/me/modal`: a signed-in user's own Modal credentials (TICKET-367, parts-harness.md AC-H16, docs/specs/byok-prod.md).

GET answers `{"set", "token_id_hint", "expired", "check", "idle_ttl_s", "key_unavailable"}`, HEAD the same with no body (R7), PUT
stores `{token_id, token_secret}`, DELETE removes them, POST `me/modal/check` starts "Check my credentials" in the
background (modal_check.py) and answers 202 at once. 401 signed out; PUT, DELETE and POST pass the same CSRF guard as
`api/me/consent`. PUT and the check are rate limited per user, and the check also per token, keyed on a hash of its ID
whatever account saved it (R3, BYOK-M3, byok audit R3): 429 with a fixed message. Every save mails the account
(`mail.Mailer.send_notice`), saying whether a token was added or replaced and the last 4 characters of its ID. No
value is ever logged or answered: a bad shape gets one fixed message, the log line names the user id only.

While BYOK is paused (`compute_mode.byok_paused`, serverless-compute.md AC-SC11) PUT and the check answer 409 with the
paused message and store nothing; GET says `paused: true`; DELETE still removes what an earlier save left.
"""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any

from part7 import applog, auth, byok_crypto, byok_route, compute_mode, modal_check, modal_creds
from part7.auth_routes import _fail, _post_body, _reply, _user_or_401

NO_STORE = {"Cache-Control": "no-store"}
MSG_SAVED = ("Saved. Use Check my credentials to test them. Unused for 24 hours, they are deleted and you add a new "
             "token.")
MSG_NONE = "No token is set. Save one first."
MSG_CHECKING = "Checking. This takes up to 30 seconds."
MSG_SLOW_DOWN = "Too many tries. Wait a few minutes, then try again."
MSG_NO_KEY = modal_creds.MSG_KEY_DOWN_SAVE  # go-live BYOK N4: the server's key, as the card and the check say
PUT_LIMIT = (10, 3600.0)  # saves per user per hour
CHECK_LIMITS = ((1, 30.0), (10, 3600.0))  # one check per 30 s, ten per hour
NOTICE_SUBJECT = {False: "A Modal token was added to your Simon account",
                  True: "The Modal token on your Simon account was replaced"}
NOTICE_TEXT = ("{what} at {stamp}. Its ID ends in {last4}. Serverless takes now run on the Modal workspace of that "
               "token.\n\n"
               "If you did this, there is nothing more to do.\n\n"
               "If you did not, someone else can use your account. Sign in, remove the token on the Me page, end the "
               "sessions you do not know, and revoke the token in your Modal settings.\n")
_PUT = auth.Limiter(*PUT_LIMIT)
_CHECKS = tuple(auth.Limiter(*limit) for limit in CHECK_LIMITS)


def _view(h: Any, user_id: str) -> dict[str, Any]:
    """`key_unavailable` (lifecycle R2): a token is saved and the server's key cannot open it now; it is kept."""
    return {**modal_creds.hint(h.app.state, user_id), "check": modal_check.result(h.app.state, user_id),
            "idle_ttl_s": modal_creds.IDLE_TTL_S,
            "key_unavailable": modal_creds.key_unavailable(h.app.state, user_id), "paused": compute_mode.byok_paused()}


def _get(h: Any) -> None:
    """GET and HEAD: `h._send` writes no body for HEAD (R7), with the GET length."""
    if (user_id := _user_or_401(h)) is not None:
        _reply(h, 200, _view(h, user_id), NO_STORE)


def _put(h: Any) -> None:
    doc = _post_body(h)
    if doc is None or (user_id := _user_or_401(h)) is None:
        return
    if compute_mode.byok_paused():
        return _fail(h, 409, byok_route.MSG_PAUSED, paused=True)
    if not _PUT.hit(user_id):
        return _fail(h, 429, MSG_SLOW_DOWN)
    replaced = modal_creds.is_set(h.app.state, user_id)
    try:
        saved = modal_creds.save(h.app.state, user_id, doc.get("token_id"), doc.get("token_secret"))  # type: ignore[arg-type]
    except (OSError, byok_crypto.ByokKeyError) as exc:  # the type only: never a path or a value
        applog.log(f"auth: modal credentials not saved for {user_id} ({type(exc).__name__})", level=logging.WARNING)
        return _fail(h, 503, MSG_NO_KEY)
    if not saved:
        return _fail(h, 400, modal_creds.MSG_SHAPE)
    applog.log(f"auth: modal credentials saved for {user_id}", level=logging.INFO)
    _notify(h, user_id, replaced)
    _reply(h, 200, {**_view(h, user_id), "message": MSG_SAVED}, NO_STORE)


def _notify(h: Any, user_id: str, replaced: bool) -> None:
    """byok audit R3: a token saved with a stolen session is reported to the account owner by mail."""
    try:
        email = (auth.identity(h.app).user(user_id) or {}).get("email")
        last4 = str(modal_creds.hint(h.app.state, user_id).get("token_id_hint") or "")[-4:]
    except Exception as exc:  # the save stands; the type only, never an address
        applog.log(f"auth: modal token notice not sent for {user_id} ({type(exc).__name__})", level=logging.WARNING)
        return
    if not email:
        return
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    subject = NOTICE_SUBJECT[replaced]
    auth.state(h.app).mailer.send_notice(email, subject, NOTICE_TEXT.format(what=subject, stamp=stamp, last4=last4))


def _delete(h: Any) -> None:
    if _post_body(h, fields=False) is None or (user_id := _user_or_401(h)) is None:
        return
    removed = modal_creds.remove(h.app.state, user_id)
    applog.log(f"auth: modal credentials removed for {user_id} ({removed})", level=logging.INFO)
    _reply(h, 200, {"set": False, "token_id_hint": None, "expired": False, "check": None,
                    "idle_ttl_s": modal_creds.IDLE_TTL_S, "key_unavailable": False, "removed": removed,
                    "paused": compute_mode.byok_paused()}, NO_STORE)


def _check(h: Any) -> None:
    if _post_body(h, fields=False) is None or (user_id := _user_or_401(h)) is None:
        return
    if compute_mode.byok_paused():
        return _fail(h, 409, byok_route.MSG_PAUSED, paused=True)
    if not modal_creds.is_set(h.app.state, user_id):
        if modal_creds.key_unavailable(h.app.state, user_id):  # R2: the server's fault, said so, never "no token"
            return _fail(h, 503, modal_creds.MSG_KEY_DOWN)
        return _fail(h, 409, MSG_NONE)
    token = modal_creds.token_key(h.app.state, user_id)  # byok audit R3: many accounts cannot test one token faster
    keys = [user_id] + ([f"token:{token}"] if token else [])
    if not all(limit.hit(key) for key in keys for limit in _CHECKS):
        return _fail(h, 429, MSG_SLOW_DOWN)
    started = modal_check.start(h.app.state, user_id)  # never on this thread: the answer does not wait for Modal
    _reply(h, 202, {"checking": True, "started": started, "message": MSG_CHECKING}, NO_STORE)


def handle(h: Any, method: str, route: str) -> bool:
    """Answer `me/modal` and `me/modal/check`; False for any other route. Mounted after auth_routes, which answers 404
    when sign-in is off."""
    if route == "me/modal/check" and method == "POST":
        _check(h)
        return True
    if route != "me/modal":
        return False
    if method in ("GET", "HEAD"):
        _get(h)
    elif method == "PUT":
        _put(h)
    elif method == "DELETE":
        _delete(h)
    else:
        return False
    return True
