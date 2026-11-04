"""The invite mail of a board (docs/specs/board-visibility.md): who may be mailed, what the mail says, and the honest result.

A signed-in board owner types addresses; each gets one plain mail naming the owner's display name and the board title
(both cleaned of links and markup), one link to the board and a stop link. Nothing else the sender typed reaches the mail.
"Sent" means the provider accepted the message (`Mailer.send_message_now`); accepted is not delivered, and Simon reads no
bounce (see the spec). A person who used the stop link is never mailed again: the server keeps only a keyed hash of the
address (`<state>/invite-stop.json`), checked on every send.

No usage cap lives here (operator 2026-11-04, "no limits anywhere ever"): nothing counts, throttles or refuses a send.
The domain's reputation therefore rests on the sign-in rule, the opt-out and Resend's own limits. What this module does
instead is make abuse visible: one log line per mail with a keyed hash of the sending account (an address is never
logged), and an `invite_mail_failed` anomaly with a failure id when the provider did not accept.
"""

from __future__ import annotations

from datetime import datetime, timezone
from email.message import EmailMessage
import hashlib
import hmac
import html as htmllib
import json
import logging
import os
from pathlib import Path
import re
import secrets
import tempfile
import threading
from typing import Any

from part7 import applog, legal_pages, mail, mail_suppress

_LOCK = threading.Lock()
STOP_FILE = "invite-stop.json"
SUBJECT = "{who} invited you to a challenge on Simon"
FALLBACK_WHO = "Someone"
FALLBACK_TITLE = "a challenge"
_URLISH = re.compile(r"(?i)(https?:|ftp:|www\.|\S+@\S+|\b[a-z0-9-]+\.(?:[a-z]{2,})(?:/\S*)?\b|//)")
_MARKUP = re.compile(r"[<>\"`\\{}\[\]|]")


def clean_label(text: Any, fallback: str, maximum: int) -> str:
    """A name or title for the mail: no links, addresses, markup, control characters or line breaks; else `fallback`."""
    if not isinstance(text, str):
        return fallback
    kept = _MARKUP.sub(" ", _URLISH.sub(" ", text))
    kept = "".join(c if c.isprintable() else " " for c in kept)
    kept = " ".join(kept.split())[:maximum].strip()
    return kept or fallback


def key_of(pepper: bytes, value: str, purpose: str) -> str:
    """A keyed hash for logs and the stop list: 32 hex characters, never reversible to the address."""
    return hmac.new(pepper, f"{purpose}:{value}".encode("utf-8"), hashlib.sha256).hexdigest()[:32]


def stop_key(pepper: bytes, email: str) -> str:
    return key_of(pepper, email, "invite-stop")


def _path(state: Path | str) -> Path:
    return Path(state) / STOP_FILE


def _load(state: Path | str) -> dict[str, str]:
    try:
        doc = json.loads(_path(state).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in doc.items() if isinstance(k, str) and isinstance(v, str)} if isinstance(doc, dict) else {}


def stopped(state: Path | str, key: str) -> bool:
    return bool(_load(state).get(key))


def _save(state: Path | str, rows: dict[str, str]) -> None:
    Path(state).mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=state, prefix=".invite-stop.", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        out.write(json.dumps(rows))
    os.replace(name, _path(state))


def issue(state: Path | str, key: str) -> None:
    """Remember that a stop link with `key` went out, so the stop route accepts only keys it handed out."""
    with _LOCK:
        rows = _load(state)
        if key not in rows:
            rows[key] = ""
            _save(state, rows)


def stop(state: Path | str, key: str) -> bool:
    """Record that the person behind `key` wants no more invite mail. False for a key never issued."""
    with _LOCK:
        rows = _load(state)
        if not re.fullmatch(r"[0-9a-f]{32}", key or "") or key not in rows:
            return False
        rows[key] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        _save(state, rows)
    return True


def forget(state: Path | str, key: str) -> None:
    """Delete my data: an issued key never used goes; a stop stays, so the opt-out keeps being honoured."""
    with _LOCK:
        rows = _load(state)
        if key in rows and not rows[key]:
            del rows[key]
            _save(state, rows)


def stop_url(origin: str, base: str, key: str) -> str:
    return f"{origin}{base}api/invites/stop/{key}"


def build_message(to: str, sender: str, who: str, title: str, link: str, stop_link: str) -> EmailMessage:
    """FORM: announcement email. The reader is half-reading: the ask comes first, then why they got it, then the opt-out."""
    who, title = clean_label(who, FALLBACK_WHO, 24), clean_label(title, FALLBACK_TITLE, 60)
    postal = legal_pages.postal_address()  # the one postal address on the legal pages (docs/legal/dmca.md)
    if postal is None:
        raise LookupError("no postal address")  # the caller records a failed invite; a mail never goes without it
    text = (
        f"{who} invited you to the challenge \"{title}\" on Simon.\n\n"
        f"Open it here:\n{link}\n\n"
        "You will be asked to sign in with this email address. Simon mails you a one-time code, so you need no password.\n\n"
        f"You got this mail because {who} typed your address. If you do not want invites from Simon, stop them here:\n"
        f"{stop_link}\n\n"
        f"{legal_pages.COMPANY_NAME}, {postal}\n"
    )
    esc = htmllib.escape
    html = (
        f"<p>{esc(who)} invited you to the challenge &quot;{esc(title)}&quot; on Simon.</p>"
        f'<p><a href="{esc(link, quote=True)}">Open the challenge</a></p>'
        "<p>You will be asked to sign in with this email address. Simon mails you a one-time code, so you need no password.</p>"
        f"<p>You got this mail because {esc(who)} typed your address. "
        f'<a href="{esc(stop_link, quote=True)}">Stop invites from Simon</a>.</p>'
        f"<p>{esc(legal_pages.COMPANY_NAME)}, {esc(postal)}</p>"
    )
    msg = mail.Outgoing()
    msg["Subject"], msg["From"], msg["To"] = SUBJECT.format(who=who), sender, to
    mail.stamp_headers(msg, sender, datetime.now(timezone.utc))  # Date, Message-ID, and Reply-To in prod
    msg["List-Unsubscribe"] = f"<{stop_link}>"
    msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    return msg


def send_one(app: Any, to: str, owner_id: str, who: str, title: str, link: str | None, origin: str | None) -> dict[str, Any]:
    """Mail one invite. `{state: "sent"}` only when the provider accepted; `{state: "stopped"}` for a person who opted
    out (the owner is told only "not mailed", so an opt-out is not confirmed); `{state: "failed", failure_id}` otherwise."""
    from part7 import auth
    store, mailer = auth.identity(app), auth.state(app).mailer
    acct = key_of(store.pepper, owner_id, "invite-acct")[:12]
    key = stop_key(store.pepper, to)
    if stopped(app.state, key) or mail_suppress.is_suppressed(app.state, to):  # a stop link, or a bounce or complaint at Resend
        applog.log(f"invite: not mailed (stop list or bounce) acct={acct}", level=logging.INFO)
        return {"state": "not_mailed"}
    ok = False
    if mailer.available and link and origin:  # no trusted origin: no link can be built, so nothing is sent
        issue(app.state, key)
        try:
            msg = build_message(to, mailer.sender(), who, title, link, stop_url(origin, app.base, key))
            ok = mailer.send_message_now(msg, kind="invite")
        except Exception as exc:  # the type only: a message can hold the address
            applog.log(f"invite: send raised {type(exc).__name__}", level=logging.WARNING)
    if ok:
        applog.log(f"invite: provider accepted acct={acct} transport={mailer.transport}", level=logging.INFO)  # the volume metric
        return {"state": "sent"}
    failure_id = "inv_" + secrets.token_hex(4)
    applog.anomaly("invite_mail_failed", failure_id=failure_id, acct=acct, transport=mailer.transport)
    return {"state": "failed", "failure_id": failure_id}
