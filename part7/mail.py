"""Sign-in mail: stdlib SMTP, or a file outbox in local mode (docs/specs/identity.md "Mail").

`select_transport` picks `smtp` when `SIMON7_SMTP_URL` and `SIMON7_MAIL_FROM` are key files, else `file` locally,
else `off`. On staging (`STAGING_BASE_PATH` set) the file outbox is refused, so a code never sits on the deployed
app. No log line here holds an address, a code, a link or the SMTP URL.
"""

from __future__ import annotations

from datetime import datetime, timezone
from email.message import EmailMessage
from email.parser import BytesParser
from email.policy import default as default_policy
import html as htmllib
import logging
import os
from pathlib import Path
import secrets
import smtplib
import ssl
import threading
from urllib.parse import unquote, urlsplit

from part7 import applog, keys

SUBJECT = "Your Simon sign-in code"
DEFAULT_FROM = "Simon <signin@localhost>"
SMTP_TIMEOUT_S = 15


def is_local() -> bool:
    """Local mode is the same switch `cli_serve` uses for `follow_url`: no staging base path."""
    return not os.environ.get("STAGING_BASE_PATH")


def select_transport(keys_dir: Path | str | None = None) -> str:
    """`smtp`, `file` or `off`. `SIMON7_MAIL_TRANSPORT=off` forces off; `file` is never chosen on staging."""
    forced = os.environ.get("SIMON7_MAIL_TRANSPORT", "").strip().lower()
    if forced == "off":
        return "off"
    if keys.has_key("SIMON7_SMTP_URL", keys_dir) and keys.has_key("SIMON7_MAIL_FROM", keys_dir):
        return "smtp"
    return "file" if is_local() else "off"


def file_refused_on_staging(keys_dir: Path | str | None = None) -> bool:
    """True when the file outbox would have been used but staging mode refuses it."""
    return (not is_local() and os.environ.get("SIMON7_MAIL_TRANSPORT", "").strip().lower() != "off"
            and not (keys.has_key("SIMON7_SMTP_URL", keys_dir) and keys.has_key("SIMON7_MAIL_FROM", keys_dir)))


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


class Mailer:
    """The chosen transport for one app."""

    def __init__(self, state: Path, transport: str | None = None, keys_dir: Path | str | None = None) -> None:
        self.state, self.keys_dir = Path(state), keys_dir
        self.transport = transport if transport is not None else select_transport(keys_dir)

    @property
    def available(self) -> bool:
        return self.transport in ("smtp", "file")

    def send_sign_in(self, to: str, code: str, link: str) -> None:
        """Send one sign-in mail. SMTP runs in a thread so the answer time does not depend on the provider."""
        if not self.available:
            return
        sender = (keys.read_key("SIMON7_MAIL_FROM", self.keys_dir) or DEFAULT_FROM) if self.transport == "smtp" else DEFAULT_FROM
        msg = build_message(to, sender, code, link, datetime.now(timezone.utc))
        if self.transport == "file":
            try:
                _write_outbox(self.state, msg)
            except OSError as exc:
                applog.log(f"auth: outbox write failed ({type(exc).__name__})", level=logging.WARNING)
            return
        url = keys.read_key("SIMON7_SMTP_URL", self.keys_dir) or ""
        threading.Thread(target=_smtp_send, args=(url, msg), name="part7-mail", daemon=True).start()


def purge_outbox(state: Path | str, email: str) -> int:
    """Delete the outbox mails addressed to `email` (Delete my data); returns how many."""
    folder, removed = Path(state) / "outbox", 0
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
