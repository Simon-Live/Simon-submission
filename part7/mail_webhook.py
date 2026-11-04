"""The Resend webhook: bounces and complaints reach the app (docs/specs/mail-delivery.md "Bounces and complaints").

Route `POST api/auth/mail-webhook`. Resend signs each call as Svix does (Resend docs, "Verify Webhooks Requests",
https://resend.com/docs/webhooks/verify-webhooks-requests; introduction: https://resend.com/docs/dashboard/webhooks/introduction):
headers `svix-id`, `svix-timestamp` and `svix-signature` (space separated `v1,<base64>` entries); the signed text is
`<svix-id>.<svix-timestamp>.<raw body>`; the key is the base64 text after the `whsec_` prefix of the signing secret;
the MAC is HMAC-SHA256; a timestamp more than five minutes off is refused (replay). The signing secret is the file
`SIMON7_RESEND_WEBHOOK_SECRET` in the keys folder, put there by the operator. Without it the route answers 404 and
`status` says it is off. Event shapes: https://resend.com/docs/webhooks/emails/bounced (`type`, `data.to`, `data.email_id`,
`data.bounce.type`). A hard bounce, a complaint and Resend's own suppression add the recipient to `mail_suppress`
(no more notices or invites to it), log `ANOMALY mail_bounced`, `mail_complaint` or `mail_suppressed` with the keyed
address hash and Resend's email id, and never an address. A soft bounce is logged and nothing else.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import logging
import time
from typing import Any, Callable

from part7 import applog, keys, mail_suppress

SECRET_NAME = "SIMON7_RESEND_WEBHOOK_SECRET"
TOLERANCE_S = 300
BODY_MAX = 65536
PATH = "api/auth/mail-webhook"
EVENTS = {"email.bounced": "mail_bounced", "email.complained": "mail_complaint", "email.suppressed": "mail_suppressed"}


def secret_key(keys_dir: Any = None) -> bytes | None:
    """The HMAC key out of the signing secret file (`whsec_` + base64), or None when absent or not base64."""
    raw = keys.read_key(SECRET_NAME, keys_dir)
    if not raw:
        return None
    try:
        return base64.b64decode(raw.removeprefix("whsec_"), validate=True)
    except (binascii.Error, ValueError):
        return None


def status(keys_dir: Any = None) -> dict[str, Any]:
    """`{state: on|off, why}` for the health detail and the log; never the secret."""
    if not keys.has_key(SECRET_NAME, keys_dir):
        return {"state": "off", "why": f"{SECRET_NAME} is not in the keys folder; the webhook route answers 404"}
    if secret_key(keys_dir) is None:
        return {"state": "off", "why": f"{SECRET_NAME} is not a whsec_ base64 signing secret; the webhook route answers 404"}
    return {"state": "on", "route": PATH}


def sign(key: bytes, msg_id: str, stamp: str, body: bytes) -> str:
    """The `v1,<base64>` entry Resend would send for this body."""
    mac = hmac.new(key, f"{msg_id}.{stamp}.".encode("utf-8") + body, hashlib.sha256).digest()
    return "v1," + base64.b64encode(mac).decode("ascii")


def verify(key: bytes, msg_id: str, stamp: str, signatures: str, body: bytes, now: float | None = None) -> bool:
    try:
        age = abs((time.time() if now is None else now) - int(stamp))
    except (ValueError, OverflowError):  # not a number, or too long a one to subtract
        return False
    if not msg_id or age > TOLERANCE_S:
        return False
    expected = sign(key, msg_id, stamp, body).encode("utf-8")
    return any(hmac.compare_digest(expected, given.encode("utf-8", "replace")) for given in signatures.split())  # bytes: a str with non-ASCII raises


def _recipients(data: dict[str, Any]) -> list[str]:
    to = data.get("to")
    return [a for a in (to if isinstance(to, list) else [to]) if isinstance(a, str) and "@" in a]


def _hard(event: str, data: dict[str, Any]) -> bool:
    """A complaint, a Resend suppression and a permanent bounce stop mail to the address; a soft bounce does not."""
    if event != "email.bounced":
        return True
    bounce = data.get("bounce")
    kind = bounce.get("type") if isinstance(bounce, dict) else None
    return kind != "Transient"


def record(event: str, data: dict[str, Any], state: Any, keyer: Callable[[str], str]) -> int:
    """Act on one verified event; how many recipients were newly suppressed."""
    added = 0
    for address in _recipients(data):
        key = keyer(address.strip().lower())
        hard = _hard(event, data)
        fresh = mail_suppress.add(state, address, EVENTS[event]) if hard else False
        added += fresh
        if fresh or not hard:
            bounce = data.get("bounce") if isinstance(data.get("bounce"), dict) else {}
            applog.anomaly(EVENTS[event], to=key, email_id=data.get("email_id"), bounce=bounce.get("type"), sub=bounce.get("subType"),
                           blocked="yes" if hard else "no")
    return added


def handle(h: Any, state: Any, keyer: Callable[[str], str], reply: Callable[..., None], keys_dir: Any = None) -> None:
    """Answer one webhook POST. `reply(h, status, obj)` is auth_routes._reply."""
    key = secret_key(keys_dir)
    if key is None:
        return reply(h, 404, {"ok": False, "message": "The mail webhook is not enabled."})
    try:
        length = int(h.headers.get("Content-Length") or 0)
    except ValueError:
        length = -1
    if not 0 < length <= BODY_MAX:
        return reply(h, 413 if length > BODY_MAX else 400, {"ok": False, "message": "The request is not valid."})
    body = h.rfile.read(length)
    if not verify(key, h.headers.get("svix-id", ""), h.headers.get("svix-timestamp", ""), h.headers.get("svix-signature", ""), body):
        applog.log("mail webhook: signature refused", level=logging.WARNING)
        return reply(h, 400, {"ok": False, "message": "The signature is not valid."})
    try:
        doc = json.loads(body)
    except ValueError:
        doc = None
    kind, data = (doc.get("type"), doc.get("data")) if isinstance(doc, dict) else (None, None)
    if kind in EVENTS and isinstance(data, dict):
        record(kind, data, state, keyer)
    reply(h, 200, {"ok": True})  # other events are acknowledged and ignored, so Resend does not retry them
