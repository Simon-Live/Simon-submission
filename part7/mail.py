"""Sign-in mail: stdlib SMTP, an HTTP mail API, or a file outbox in local mode (docs/specs/identity.md "Mail").

`select_transport` picks the staging test mailbox (`outbox`) when `SIMON7_MAIL_TRANSPORT=outbox` on the own origin,
otherwise a provider when its key files exist (`smtp`: `SIMON7_SMTP_URL`, or `SIMON7_SMTP_HOST` with
optional port, user and password; `api`: `SIMON7_MAIL_API_KEY`; each also needs `SIMON7_MAIL_FROM`), else `file`
locally, else `off`. On staging the file outbox is refused, so a code never sits on the deployed app, and a provider
is used only on the app's own origin (`STAGING_ROUTE=root`, ADR-0014): on the shared gateway origin sign-in stays
off. No log line here holds an address, a code, a link, a key or the SMTP URL.
"""

from __future__ import annotations

from datetime import datetime, timezone
from email.message import EmailMessage
from email.parser import BytesParser
from email.policy import default as default_policy
import html as htmllib
import json
import logging
import os
from pathlib import Path
import secrets
import smtplib
import ssl
import threading
from urllib import error as urlerror, request as urlrequest
from urllib.parse import quote, unquote, urlsplit

from part7 import applog, config, keys, staging_mailbox

SUBJECT = "Your Simon sign-in code"
DEFAULT_FROM = "Simon <signin@localhost>"
SMTP_TIMEOUT_S = 15
API_TIMEOUT_S = 15
DEFAULT_API_URL = "https://api.resend.com/emails"  # Resend-compatible JSON: from, to, subject, text, html


def is_local() -> bool:
    """Local mode: not on staging. In root mode the hub leaves `STAGING_BASE_PATH` empty, so the route is asked too."""
    return config.staging_route() is None


def smtp_url(keys_dir: Path | str | None = None) -> str | None:
    """The SMTP URL: `SIMON7_SMTP_URL`, else built from `SIMON7_SMTP_HOST` (+ `_PORT`, `_USER`, `_PASSWORD`).

    Port 465 is implicit TLS (`smtps`), any other port STARTTLS (`smtp`). The result holds the password: never log it.
    """
    whole = keys.read_key("SIMON7_SMTP_URL", keys_dir)
    if whole:
        return whole
    host = keys.read_key("SIMON7_SMTP_HOST", keys_dir)
    if not host:
        return None
    port = (keys.read_key("SIMON7_SMTP_PORT", keys_dir) or "587").strip()
    user, password = keys.read_key("SIMON7_SMTP_USER", keys_dir), keys.read_key("SIMON7_SMTP_PASSWORD", keys_dir)
    login = f"{quote(user, safe='')}:{quote(password or '', safe='')}@" if user else ""
    return f"{'smtps' if port == '465' else 'smtp'}://{login}{host.strip()}:{port}"


def provider(keys_dir: Path | str | None = None) -> str | None:
    """`smtp` or `api` when its key files exist (and the sender), else None. Reads names, never logs values."""
    if not keys.has_key("SIMON7_MAIL_FROM", keys_dir):
        return None
    if smtp_url(keys_dir):
        return "smtp"
    return "api" if keys.has_key("SIMON7_MAIL_API_KEY", keys_dir) else None


def provider_blocked_by_origin(keys_dir: Path | str | None = None) -> bool:
    """True when a provider is configured but the app shares the gateway origin (ADR-0014), so sign-in stays off."""
    return provider(keys_dir) is not None and not is_local() and config.staging_route() != "root"


def select_transport(keys_dir: Path | str | None = None) -> str:
    """`smtp`, `api`, `file` or `off`. `SIMON7_MAIL_TRANSPORT=off` forces off; `file` is never chosen on staging."""
    forced = os.environ.get("SIMON7_MAIL_TRANSPORT", "").strip().lower()
    if forced == "off":
        return "off"
    if forced == "outbox" and config.staging_route() == "root":
        return "outbox"  # the staging test mailbox: only on the app's own origin, never locally or on the shared origin
    found = provider(keys_dir)
    if found and (is_local() or config.staging_route() == "root"):
        return found
    return "file" if is_local() else "off"


def file_refused_on_staging(keys_dir: Path | str | None = None) -> bool:
    """True when the file outbox would have been used but staging mode refuses it."""
    return (not is_local() and os.environ.get("SIMON7_MAIL_TRANSPORT", "").strip().lower() != "off"
            and provider(keys_dir) is None and select_transport(keys_dir) != "outbox")


def build_message(to: str, sender: str, code: str, link: str, when: datetime) -> EmailMessage:
    """Plain text plus a minimal HTML part. No tracking pixel; it says when the request was made, never from where."""
    stamp = when.strftime("%Y-%m-%d %H:%M UTC")
    text = (
        f"Someone asked to sign in to Simon with this address at {stamp}.\n\n"
        f"Your code: {code}\n\n"
        f"Or open this link on the device you asked from:\n{link}\n\n"
        "The code and the link work once and stop working after 15 minutes.\n\n"
        "If you did not ask, ignore this mail.\n"
    )
    html = (
        f"<p>Someone asked to sign in to Simon with this address at {stamp}.</p>"
        f"<p>Your code: <strong>{code}</strong></p>"
        f'<p>Or <a href="{htmllib.escape(link, quote=True)}">open this link</a> on the device you asked from.</p>'
        "<p>The code and the link work once and stop working after 15 minutes.</p>"
        "<p>If you did not ask, ignore this mail.</p>"
    )
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = SUBJECT, sender, to
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    return msg


def _write_outbox(state: Path, msg: EmailMessage) -> None:
    folder = Path(state) / "outbox"
    folder.mkdir(parents=True, exist_ok=True)
    os.chmod(folder, 0o700)
    name = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')}-{secrets.token_hex(4)}.eml"
    fd = os.open(folder / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as out:
        out.write(bytes(msg))
    applog.log("auth: mail written to outbox")


def _smtp_send(url: str, msg: EmailMessage) -> bool:
    parts = urlsplit(url)
    host = parts.hostname or ""
    if parts.scheme not in ("smtp", "smtps") or not host:
        applog.log("auth: mail not sent (SMTP settings are not valid)", level=logging.WARNING)
        return False
    context = ssl.create_default_context()
    try:
        if parts.scheme == "smtps":
            client: smtplib.SMTP = smtplib.SMTP_SSL(host, parts.port or 465, timeout=SMTP_TIMEOUT_S, context=context)
        else:
            client = smtplib.SMTP(host, parts.port or 587, timeout=SMTP_TIMEOUT_S)
        with client:
            if parts.scheme == "smtp":
                client.starttls(context=context)
            if parts.username:
                client.login(unquote(parts.username), unquote(parts.password or ""))
            client.send_message(msg)
    except (OSError, smtplib.SMTPException) as exc:  # the type only: the message can hold the address
        applog.log(f"auth: mail not sent ({type(exc).__name__})", level=logging.WARNING)
        return False
    applog.log("auth: mail sent")
    return True


def _api_send(url: str, api_key: str, msg: EmailMessage) -> bool:
    """POST the message as Resend-style JSON with a Bearer key. Logs the outcome type only (no address, key or body)."""
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        applog.log("auth: mail not sent (mail API settings are not valid)", level=logging.WARNING)
        return False
    text, html = msg.get_body(("plain",)), msg.get_body(("html",))
    doc = {"from": str(msg["From"]), "to": [str(msg["To"])], "subject": str(msg["Subject"]),
           "text": text.get_content() if text else "", "html": html.get_content() if html else ""}
    req = urlrequest.Request(url, data=json.dumps(doc).encode("utf-8"), method="POST", headers={
        "Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "User-Agent": "simon-part-7"})
    try:
        with urlrequest.urlopen(req, timeout=API_TIMEOUT_S) as resp:
            ok = 200 <= resp.status < 300
    except urlerror.HTTPError as exc:
        applog.log(f"auth: mail not sent (mail API answered HTTP {exc.code})", level=logging.WARNING)
        return False
    except (OSError, ValueError) as exc:
        applog.log(f"auth: mail not sent ({type(exc).__name__})", level=logging.WARNING)
        return False
    applog.log("auth: mail sent" if ok else "auth: mail not sent (mail API refused it)", level=logging.INFO if ok else logging.WARNING)
    return ok


class Mailer:
    """The chosen transport for one app."""

    def __init__(self, state: Path, transport: str | None = None, keys_dir: Path | str | None = None) -> None:
        self.state, self.keys_dir = Path(state), keys_dir
        self.transport = transport if transport is not None else select_transport(keys_dir)

    @property
    def available(self) -> bool:
        return self.transport in ("smtp", "api", "file", "outbox")

    def send_sign_in(self, to: str, code: str, link: str) -> None:
        """Send one sign-in mail. SMTP runs in a thread so the answer time does not depend on the provider."""
        if not self.available:
            return
        sender = (keys.read_key("SIMON7_MAIL_FROM", self.keys_dir) or DEFAULT_FROM) if self.transport in ("smtp", "api") else DEFAULT_FROM
        msg = build_message(to, sender, code, link, datetime.now(timezone.utc))
        if self.transport == "outbox":
            try:
                staging_mailbox.add(self.state, to, code, link)
                applog.log("auth: mail kept in the staging mailbox")
            except OSError as exc:
                applog.log(f"auth: mailbox write failed ({type(exc).__name__})", level=logging.WARNING)
            return
        if self.transport == "file":
            try:
                _write_outbox(self.state, msg)
            except OSError as exc:
                applog.log(f"auth: outbox write failed ({type(exc).__name__})", level=logging.WARNING)
            return
        if self.transport == "api":
            api_url = keys.read_key("SIMON7_MAIL_API_URL", self.keys_dir) or DEFAULT_API_URL
            args: tuple = (api_url, keys.read_key("SIMON7_MAIL_API_KEY", self.keys_dir) or "", msg)
            target = _api_send
        else:
            args, target = (smtp_url(self.keys_dir) or "", msg), _smtp_send
        threading.Thread(target=target, args=args, name="part7-mail", daemon=True).start()


def purge_outbox(state: Path | str, email: str) -> int:
    """Delete the outbox mails addressed to `email` (Delete my data); returns how many."""
    folder, removed = Path(state) / "outbox", staging_mailbox.purge(state, email)
    if not folder.is_dir():
        return 0
    for item in folder.glob("*.eml"):
        try:
            to = str(BytesParser(policy=default_policy).parsebytes(item.read_bytes(), headersonly=True)["To"] or "")
            if to.strip().lower() == email:
                item.unlink()
                removed += 1
        except OSError:
            continue
    return removed
