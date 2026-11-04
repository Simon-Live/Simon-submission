"""Sign-in mail: stdlib SMTP, an HTTP mail API, or a file outbox in local mode (docs/specs/identity.md "Mail").

`select_transport` picks the staging test mailbox (`outbox`) when `SIMON7_MAIL_TRANSPORT=outbox` on the own origin,
otherwise a provider when its key files exist (`smtp`: `SIMON7_SMTP_URL`, or `SIMON7_SMTP_HOST` with
optional port, user and password; `api`: `SIMON7_MAIL_API_KEY`; each also needs `SIMON7_MAIL_FROM`), else `file`
locally, else `off`. On staging the file outbox is refused, so a code never sits on the deployed app, and a provider
is used only on the app's own origin (`STAGING_ROUTE=root`, ADR-0014): on the shared gateway origin sign-in stays
off. No log line here holds an address, a code, a link, a key or the SMTP URL.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import format_datetime, make_msgid, parseaddr
from email.parser import BytesParser
from email.policy import default as default_policy
import hashlib
import html as htmllib
import json
import logging
import os
from pathlib import Path
import re
import secrets
import smtplib
import ssl
import threading
import time
from typing import Any, Callable
from urllib import error as urlerror, request as urlrequest
from urllib.parse import quote, unquote, urlsplit

from part7 import applog, config, keys, mail_status, mail_suppress, selfheal, staging_mailbox
from part7.prod_mode import is_prod

SUBJECT = "Your Simon sign-in code"
DEFAULT_FROM = "Simon <signin@localhost>"
SMTP_TIMEOUT_S = 15
API_TIMEOUT_S = 15
RETRY_DELAY_S = 2.0  # one more try after a connection fault or a 4xx
_FLIGHT: set[threading.Thread] = set()  # mail threads in flight (drain)
_FLIGHT_LOCK = threading.Lock()
DEFAULT_API_URL = "https://api.resend.com/emails"  # Resend-compatible JSON: from, to, subject, text, html


def is_local() -> bool:
    """Local mode: not on staging. In root mode the hub leaves `STAGING_BASE_PATH` empty, so the route is asked too."""
    return config.staging_route() is None


def smtp_url(keys_dir: Path | str | None = None) -> str | None:
    """The SMTP URL: `SIMON7_SMTP_URL`, else built from `SIMON7_SMTP_HOST` (+ `_PORT`, `_USER`, `_PASSWORD`).

    Port 465 is implicit TLS (`smtps`), any other port STARTTLS (`smtp`). The result holds the password: never log it.
    """
    whole = keys.read_key("SIMON7_SMTP_URL", keys_dir)
    if whole or is_prod():  # prod reads exactly the ADR-0025 files SIMON7_SMTP_URL and SIMON7_MAIL_FROM
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
    """`smtp`, `api`, `file` or `off`. `SIMON7_MAIL_TRANSPORT=off` forces off; `file` is never chosen on staging.

    In prod only `smtp` (secrets SIMON7_SMTP_URL and SIMON7_MAIL_FROM, ADR-0025) or `off`: never the outbox, the file
    transport or the HTTP mail API, whatever the environment says (prod_check.verify_start refuses those at start).
    """
    if is_prod():
        return "smtp" if provider(keys_dir) == "smtp" else "off"
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
    return (not is_prod() and not is_local() and os.environ.get("SIMON7_MAIL_TRANSPORT", "").strip().lower() != "off"
            and provider(keys_dir) is None and select_transport(keys_dir) != "outbox")


class Outgoing(EmailMessage):
    """A message that knows what it is for, so the log line can say kind and recipient key without the address."""

    kind = "mail"
    rcpt_key = "-"


def _plain_key(address: str) -> str:
    """A short hash of the address for a log line when no keyed hash is wired in (the ops notice, a bare Mailer)."""
    return hashlib.sha256(address.strip().lower().encode("utf-8")).hexdigest()[:12]


def reply_to() -> str | None:
    """`support@<prod host>` in prod, where that mailbox is registered (docs/prod/registry-block.yaml `inbound`); else None."""
    if not is_prod():
        return None
    host = os.environ.get("SIMON7_PROD_HOSTS", "simon.live").split(",")[0].strip().removeprefix("www.")
    return f"support@{host}"


def stamp_headers(msg: EmailMessage, sender: str, when: datetime) -> None:
    """`Date`, a `Message-ID` in the sender's domain and, in prod, `Reply-To`: the headers a strict filter looks for."""
    msg["Date"] = format_datetime(when)
    msg["Message-ID"] = make_msgid(domain=parseaddr(sender)[1].rpartition("@")[2] or None)
    answer = reply_to()
    if answer:
        msg["Reply-To"] = answer


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
    msg = Outgoing()
    msg["Subject"], msg["From"], msg["To"] = SUBJECT, sender, to
    stamp_headers(msg, sender, when)
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


@dataclass
class Outcome:
    """One try at the provider: accepted or not, whether a second try may help, and the provider's own id."""

    ok: bool
    transient: bool = False
    reason: str = ""
    provider_id: str | None = None


_ID_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{15,}")


def _reply_id(reply: object) -> str | None:
    """The provider's id out of its answer to DATA (bytes or text): the first long word, else the trimmed text. An
    address in it is masked by the log filter; nothing here is a key."""
    text = reply.decode("utf-8", "replace") if isinstance(reply, (bytes, bytearray)) else str(reply or "")
    found = _ID_WORD.search(text)
    return (found.group(0) if found else " ".join(text.split())[:60]) or None


def _smtp_transient(exc: BaseException) -> bool:
    """A connection fault or a 4xx answer may pass on a second try; a TLS fault, a login refusal or a 5xx will not."""
    if isinstance(exc, ssl.SSLError):
        return False
    if isinstance(exc, smtplib.SMTPServerDisconnected):
        return True
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        codes = [v[0] for v in exc.recipients.values()]
        return bool(codes) and all(400 <= c < 500 for c in codes)
    code = getattr(exc, "smtp_code", None)
    if isinstance(code, int):
        return 400 <= code < 500
    return isinstance(exc, OSError) and not isinstance(exc, smtplib.SMTPException)


def _smtp_once(url: str, msg: EmailMessage) -> Outcome:
    """One try over implicit TLS (`smtps`) or STARTTLS (`smtp`, which fails rather than continue in the clear)."""
    parts = urlsplit(url)
    host = parts.hostname or ""
    if parts.scheme not in ("smtp", "smtps") or not host:
        applog.log("auth: mail not sent (SMTP settings are not valid)", level=logging.WARNING)
        return Outcome(False, reason="smtp settings not valid")
    context = ssl.create_default_context()
    reply: list[object] = []
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
            _keep_data_reply(client, reply)
            client.send_message(msg)
    except (OSError, smtplib.SMTPException) as exc:  # the type only: the message can hold the address
        code = getattr(exc, "smtp_code", None)
        why = type(exc).__name__ + (f" {code}" if isinstance(code, int) else "")
        applog.log(f"auth: mail not sent ({why})", level=logging.WARNING)
        return Outcome(False, _smtp_transient(exc), why)
    return Outcome(True, provider_id=_reply_id(reply[0]) if reply else None)


def _keep_data_reply(client: Any, reply: list[object]) -> None:
    """The server's answer to DATA names the message; `send_message` drops it, so note it as it passes."""
    plain = getattr(client, "data", None)
    if plain is None:
        return

    def data(body: Any) -> Any:
        out = plain(body)
        reply.append(out[1])
        return out

    client.data = data


def _api_once(url: str, api_key: str, msg: EmailMessage) -> Outcome:
    """POST the message as Resend-style JSON with a Bearer key. Logs the outcome type only (no address, key or body)."""
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        applog.log("auth: mail not sent (mail API settings are not valid)", level=logging.WARNING)
        return Outcome(False, reason="mail api settings not valid")
    text, html = msg.get_body(("plain",)), msg.get_body(("html",))
    doc = {"from": str(msg["From"]), "to": [str(msg["To"])], "subject": str(msg["Subject"]),
           "text": text.get_content() if text else "", "html": html.get_content() if html else ""}
    if msg["Reply-To"]:
        doc["reply_to"] = str(msg["Reply-To"])
    req = urlrequest.Request(url, data=json.dumps(doc).encode("utf-8"), method="POST", headers={
        "Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "User-Agent": "simon-part-7"})
    try:
        with urlrequest.urlopen(req, timeout=API_TIMEOUT_S) as resp:
            ok = 200 <= resp.status < 300
            body = resp.read() if hasattr(resp, "read") else b""
    except urlerror.HTTPError as exc:
        applog.log(f"auth: mail not sent (mail API answered HTTP {exc.code})", level=logging.WARNING)
        return Outcome(False, exc.code in (408, 429) or exc.code >= 500, f"mail api http {exc.code}")
    except (OSError, ValueError) as exc:
        applog.log(f"auth: mail not sent ({type(exc).__name__})", level=logging.WARNING)
        return Outcome(False, isinstance(exc, OSError), type(exc).__name__)
    if not ok:
        applog.log("auth: mail not sent (mail API refused it)", level=logging.WARNING)
        return Outcome(False, reason="mail api refused")
    try:
        given = json.loads(body or b"{}").get("id")
    except (ValueError, AttributeError):
        given = None
    return Outcome(True, provider_id=given if isinstance(given, str) else None)


def _with_retry(once: Any, args: tuple, msg: Any) -> bool:
    """Try once more after RETRY_DELAY_S when the first failure may be passing (a connection fault, a 4xx). The line on
    success says the provider took the mail, which is not delivery: that is what the Resend webhook adds."""
    out = once(*args)
    if not out.ok and out.transient:
        time.sleep(RETRY_DELAY_S)
        out = once(*args)
    if not out.ok:
        _failed(out.reason)
        return False
    kind, key = getattr(msg, "kind", "mail"), getattr(msg, "rcpt_key", "-")
    applog.log(f"auth: mail handed to provider kind={kind} to={key} id={out.provider_id or '-'}")
    selfheal.record("mail_send")
    return True


def _smtp_send(url: str, msg: EmailMessage) -> bool:
    return _with_retry(_smtp_once, (url, msg), msg)


def _api_send(url: str, api_key: str, msg: EmailMessage) -> bool:
    return _with_retry(_api_once, (url, api_key, msg), msg)


def _failed(reason: str) -> None:
    """A mail that did not leave is a fault a person must hear about: nobody can sign in (observability.md)."""
    applog.anomaly("mail_failed", reason=reason)


class Mailer:
    """The chosen transport for one app."""

    def __init__(self, state: Path, transport: str | None = None, keys_dir: Path | str | None = None) -> None:
        self.state, self.keys_dir = Path(state), keys_dir
        self.transport = transport if transport is not None else select_transport(keys_dir)
        self.board = mail_status.AttemptBoard()  # what became of each sign-in mail (api/auth/mail-status)
        self.keyer: Callable[[str], str] = _plain_key  # auth.AuthState swaps in the store's keyed hash

    @property
    def available(self) -> bool:
        return self.transport in ("smtp", "api", "file", "outbox")

    def send_sign_in(self, to: str, code: str, link: str, attempt: str | None = None) -> None:
        """Send one sign-in mail. SMTP runs in a thread so the answer time does not depend on the provider; with an
        `attempt` id the board says `pending`, then `sent` or `failed` once the provider (or the retry) has answered."""
        if not self.available:
            return
        msg = self._tag(build_message(to, self._sender(), code, link, datetime.now(timezone.utc)), "sign_in", to)
        if self.transport == "outbox":
            self._keep_in_mailbox(to, "sign_in", msg, attempt, code=code, link=link)
            return
        self._deliver(msg, attempt)

    def send_notice(self, to: str, subject: str, text: str, kind: str = "notice") -> None:
        """Send one plain-text account notice (byok R3: a Modal token saved or replaced; `kind="invite"` for a board
        invite). An address the provider bounced or complained about gets no notice (mail_suppress). The staging test
        mailbox keeps it like a sign-in mail."""
        if not self.available or mail_suppress.is_suppressed(self.state, to):
            return
        msg = self._tag(self._notice_message(to, subject, text), kind, to)
        if self.transport == "outbox":
            self._keep_in_mailbox(to, kind, msg, None, subject=subject, body=text)
            return
        self._deliver(msg)

    def send_notice_now(self, to: str, subject: str, text: str, kind: str = "ops_notice") -> bool:
        """The same notice, sent before returning; True when the provider accepted it. For an operator notice, whose
        caller may be a short-lived process (ops_notice.py). Only a real provider counts as delivery."""
        if self.transport not in ("smtp", "api"):
            return False
        target, args = self._provider(self._tag(self._notice_message(to, subject, text), kind, to))
        return bool(target(*args))

    def send_message_now(self, msg: Outgoing, kind: str = "invite") -> bool:
        """Send a prepared message before returning, through the same transports, tagging and retry as every other mail;
        True only when the transport accepted it: a provider (SMTP or the HTTP API) said yes, or the local file outbox
        holds it. `off` sends nothing and answers False. An address the provider bounced or complained about gets nothing
        (mail_suppress), also False. Accepted is not delivered: the Resend webhook adds the bounce later."""
        to = str(msg["To"])
        if not self.available or mail_suppress.is_suppressed(self.state, to):
            return False
        self._tag(msg, kind, to)
        if self.transport == "file":
            try:
                _write_outbox(self.state, msg)
                return True
            except OSError as exc:
                applog.log(f"auth: outbox write failed ({type(exc).__name__})", level=logging.WARNING)
                return False
        if self.transport == "outbox":  # the staging test mailbox is this server's fake mail
            text = msg.get_body(("plain",))
            return self._keep_in_mailbox(to, kind, msg, None, subject=str(msg["Subject"]), body=text.get_content() if text else "")
        target, args = self._provider(msg)
        return bool(target(*args))

    def sender(self) -> str:
        return self._sender()

    def _tag(self, msg: Outgoing, kind: str, to: str) -> Outgoing:
        msg.kind, msg.rcpt_key = kind, self.keyer(to)
        return msg

    def _notice_message(self, to: str, subject: str, text: str) -> Outgoing:
        msg = Outgoing()
        msg["Subject"], msg["From"], msg["To"] = subject, self._sender(), to
        stamp_headers(msg, self._sender(), datetime.now(timezone.utc))
        msg.set_content(text)
        msg.add_alternative("".join(f"<p>{htmllib.escape(par)}</p>" for par in text.split("\n\n") if par), subtype="html")
        return msg

    def _provider(self, msg: EmailMessage) -> tuple[Any, tuple]:
        if self.transport == "api":
            api_url = keys.read_key("SIMON7_MAIL_API_URL", self.keys_dir) or DEFAULT_API_URL
            return _api_send, (api_url, keys.read_key("SIMON7_MAIL_API_KEY", self.keys_dir) or "", msg)
        return _smtp_send, (smtp_url(self.keys_dir) or "", msg)

    def _sender(self) -> str:
        return (keys.read_key("SIMON7_MAIL_FROM", self.keys_dir) or DEFAULT_FROM) if self.transport in ("smtp", "api") else DEFAULT_FROM

    def _keep_in_mailbox(self, to: str, kind: str, msg: Outgoing, attempt: str | None, **fields: str) -> bool:
        ok = True
        try:
            staging_mailbox.add(self.state, to, fields.pop("code", ""), fields.pop("link", ""), kind=kind, **fields)
            applog.log(f"auth: mail kept in the staging mailbox kind={kind} to={msg.rcpt_key}")
        except OSError as exc:
            ok = False
            applog.log(f"auth: mailbox write failed ({type(exc).__name__})", level=logging.WARNING)
        if attempt:
            self.board.set(attempt, mail_status.SENT if ok else mail_status.FAILED)
        return ok

    def _deliver(self, msg: Outgoing, attempt: str | None = None) -> None:
        """The file outbox in local mode; the provider on a thread, so the answer time does not depend on it."""
        if self.transport == "file":
            ok = True
            try:
                _write_outbox(self.state, msg)
            except OSError as exc:
                ok = False
                applog.log(f"auth: outbox write failed ({type(exc).__name__})", level=logging.WARNING)
            if attempt:
                self.board.set(attempt, mail_status.SENT if ok else mail_status.FAILED)
            return
        target, args = self._provider(msg)
        if attempt:
            self.board.set(attempt, mail_status.PENDING)
        self._spawn(target, args, attempt)

    def _spawn(self, target: Any, args: tuple, attempt: str | None) -> None:
        def run() -> None:
            ok = False
            try:
                ok = bool(target(*args))
            except Exception as exc:  # a crash is a mail that did not leave: say so, never leave the screen waiting
                applog.log(f"auth: mail thread failed ({type(exc).__name__})", level=logging.ERROR)
                _failed(type(exc).__name__)
            finally:
                if attempt:
                    self.board.set(attempt, mail_status.SENT if ok else mail_status.FAILED)
                with _FLIGHT_LOCK:
                    _FLIGHT.discard(me[0])

        me: list[Any] = []
        thread = threading.Thread(target=run, args=(), name="part7-mail", daemon=True)
        me.append(thread)
        with _FLIGHT_LOCK:
            _FLIGHT.add(thread)
        thread.start()


def drain(timeout_s: float) -> int:
    """SIGTERM: wait up to `timeout_s` for the mail threads in flight (their retry included); how many are still running.
    The same rule as the job drain: a restart does not cut a sign-in mail in half."""
    deadline = time.monotonic() + timeout_s
    with _FLIGHT_LOCK:
        running = list(_FLIGHT)
    for thread in running:
        thread.join(max(0.0, deadline - time.monotonic()))
    with _FLIGHT_LOCK:
        left = sum(1 for t in running if t.is_alive())
    if left:
        applog.anomaly("drain_cut_off", "mail still sending at the drain max", kind="mail", count=left)
    return left


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
