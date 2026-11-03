"""Request helpers of opt-in sign-in: pepper, per-app state, cookie, origin check, rate limits, hooks for other routes.

`current_user(h)` is the contract the rest of the app reads (C-ID): None until a valid session cookie arrives, and
None on any store error, so no anonymous flow can fail because of identity. With no cookie the store is not opened.
"""

from __future__ import annotations

from collections import deque
import logging
import os
from pathlib import Path
import secrets
import threading
import time
from typing import Any, Callable
from urllib.parse import urlsplit

from part7 import applog, config, mail, quota
from part7 import identity as ident

COOKIE = "s7_sid"
COOKIE_MAX_AGE = ident.SESSION_ABSOLUTE_S
BODY_MAX = 4096
START_PER_IP = (10, 3600)  # requests, seconds
VERIFY_PER_IP = (30, 600)
START_PER_IP_OUTBOX = (60, 3600)  # staging test mailbox only: no real mail leaves, and every tester shares the
#                                    tunnel's one address; per-address and global limits still apply
CLOCK: Callable[[], float] = time.time  # tests replace it

_INIT = threading.Lock()


class Limiter:
    """A sliding window per key, in memory: `hit` is False once `limit` calls fall inside `window` seconds."""

    def __init__(self, limit: int, window: float) -> None:
        self.limit, self.window = limit, window
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str) -> bool:
        now = CLOCK()
        with self._lock:
            if len(self._hits) > 5000:  # forget keys with nothing left in the window
                self._hits = {k: q for k, q in self._hits.items() if q and q[-1] > now - self.window}
            queue = self._hits.setdefault(key, deque())
            while queue and queue[0] <= now - self.window:
                queue.popleft()
            if len(queue) >= self.limit:
                return False
            queue.append(now)
            return True


class AuthState:
    """What one app needs for sign-in: the mailer, the IP limiters and the lazily opened store."""

    def __init__(self, app: Any) -> None:
        self.app = app
        self.mailer = mail.Mailer(app.state)
        start = START_PER_IP_OUTBOX if self.mailer.transport == "outbox" else START_PER_IP
        self.start_limit, self.verify_limit = Limiter(*start), Limiter(*VERIFY_PER_IP)
        self._store: ident.IdentityStore | None = None
        if mail.file_refused_on_staging():
            applog.log("auth: file outbox refused on staging; sign-in is off", level=logging.WARNING)
        elif mail.provider_blocked_by_origin():
            applog.log("auth: mail is configured but this app shares the gateway origin; sign-in is off (ADR-0014)", level=logging.WARNING)

    @property
    def available(self) -> bool:
        return self.mailer.available

    @property
    def store(self) -> ident.IdentityStore:
        with _INIT:
            if self._store is None:
                self._store = ident.IdentityStore(self.app.state, _pepper(self.app.state), clock=lambda: CLOCK())
            return self._store


def _pepper(state: Path) -> bytes:
    """`SIMON7_AUTH_PEPPER` from the keys folder (or the identity folder when that is not writable); made on first use, 0600."""
    from part7 import keys

    folders = (config.keys_dir(), Path(state) / "identity")
    for folder in folders:
        found = keys.read_key("SIMON7_AUTH_PEPPER", folder)
        if found:
            return bytes.fromhex(found) if _is_hex(found) else found.encode("utf-8")
    value = secrets.token_hex(32)
    for folder in folders:
        try:
            folder.mkdir(parents=True, exist_ok=True)
            fd = os.open(folder / "SIMON7_AUTH_PEPPER", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as out:
                out.write(value + "\n")
            keys.read_key("SIMON7_AUTH_PEPPER", folder)  # registers it for redaction
            return bytes.fromhex(value)
        except OSError:
            continue
    return bytes.fromhex(value)  # nowhere to keep it: open challenges die with the process


def _is_hex(text: str) -> bool:
    try:
        bytes.fromhex(text)
        return True
    except ValueError:
        return False


def state(app: Any) -> AuthState:
    """The app's sign-in state, created on first use."""
    found = getattr(app, "_auth_state", None)
    if found is None:
        with _INIT:
            found = getattr(app, "_auth_state", None)
            if found is None:
                found = AuthState(app)
                app._auth_state = found
    return found


def identity(app: Any) -> ident.IdentityStore:
    return state(app).store


# ----- request pieces --------------------------------------------------------------------------------
def _peer_is_loopback(h: Any) -> bool:
    return str(h.client_address[0]) in ("127.0.0.1", "::1", "::ffff:127.0.0.1")


def client_key(h: Any) -> str:
    """A short hash of the client address, for throttling only (never for authorisation).

    The server binds 127.0.0.1, so a loopback peer is the gateway and its forwarded address is trusted.
    """
    addr = str(h.client_address[0])
    if _peer_is_loopback(h):
        forwarded = (h.headers.get("Cf-Connecting-Ip") or "").strip()
        xff = (h.headers.get("X-Forwarded-For") or "").strip()
        if forwarded:
            addr = forwarded
        elif xff and "," not in xff:
            addr = xff
    return quota.visitor_key(addr) or "unknown"


def is_https(h: Any) -> bool:
    """The gateway's rule: a loopback peer and either `Cf-Connecting-Ip` or `X-Forwarded-Proto: https`."""
    if not _peer_is_loopback(h):
        return False
    return bool(h.headers.get("Cf-Connecting-Ip")) or (h.headers.get("X-Forwarded-Proto") or "").strip().lower() == "https"


def origin_ok(h: Any) -> bool:
    """CSRF guard for a POST: JSON content type, an `Origin` whose host and port equal `Host`, same-origin fetch."""
    ctype = (h.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    if ctype != "application/json":
        return False
    origin, host = h.headers.get("Origin"), (h.headers.get("Host") or "").strip().lower()
    if not origin or not host or urlsplit(origin).netloc.lower() != host:
        return False
    site = h.headers.get("Sec-Fetch-Site")
    return site is None or site.strip().lower() == "same-origin"


def public_origin(h: Any) -> str | None:
    """The origin a sign-in link may carry, or None when this request cannot be trusted to name one.

    `SIMON7_PUBLIC_ORIGIN` (a pinned `https://host`) wins. Without it: in local mode a loopback `Host`; on staging a
    `Host` that came through the gateway hop (a loopback peer with `Cf-Connecting-Ip` or `X-Forwarded-Proto`), which
    routes on the hostname itself. Any other `Host` (a forged one on a direct connection) is refused."""
    pinned = os.environ.get("SIMON7_PUBLIC_ORIGIN", "").strip().rstrip("/")
    if pinned:
        parts = urlsplit(pinned)
        return pinned if parts.scheme in ("http", "https") and parts.netloc and not parts.path else None
    host = (h.headers.get("Host") or "").strip()
    if not host or "/" in host or "@" in host:
        return None
    scheme = "https" if is_https(h) else "http"
    if mail.is_local():
        name = urlsplit(f"//{host}").hostname
        return f"{scheme}://{host}" if name in ("127.0.0.1", "localhost", "::1") else None
    gateway = _peer_is_loopback(h) and bool(h.headers.get("Cf-Connecting-Ip") or h.headers.get("X-Forwarded-Proto"))
    return f"{scheme}://{host}" if gateway else None


def public_link(h: Any, token: str) -> str | None:
    """The sign-in link: the trusted origin, the base path, the token in the fragment; None when no origin is trusted."""
    origin = public_origin(h)
    return None if origin is None else f"{origin}{h.app.base}#/signin/{token}"


def sid_from(h: Any) -> str | None:
    """The session id from `Cookie`. Read piece by piece, not with SimpleCookie: one stray separator (a gateway
    that removed its own cookie and left "; s7_sid=...") makes SimpleCookie drop every cookie, which signs the
    person out silently (staging, 2026-11-01)."""
    for piece in (h.headers.get("Cookie") or "").split(";"):
        name, _, value = piece.strip().partition("=")
        if name == COOKIE and value.strip():
            return value.strip()
    return None


def cookie_header(h: Any, sid: str | None) -> str:
    """`Set-Cookie` value: set (`sid`) or cleared (None). Path is the base path, never `/` on the shared origin."""
    path = h.app.base
    parts = [f"{COOKIE}={sid or ''}", f"Path={path}", "HttpOnly", "SameSite=Lax", f"Max-Age={COOKIE_MAX_AGE if sid else 0}"]
    if is_https(h):
        parts.append("Secure")
    return "; ".join(parts)


# ----- contract B (hooks for other routes) ----------------------------------------------------------------
def current_user(h: Any) -> str | None:
    """The signed-in user id, or None. Never raises: identity must not break an anonymous flow."""
    sid = sid_from(h)
    if sid is None or not ident.db_path(h.app.state).is_file():  # no identity file: nobody can be signed in
        return None
    try:
        return identity(h.app).session_user(sid)
    except Exception as exc:  # a store fault answers as anonymous, and is logged once per request
        applog.log(f"auth: session lookup failed ({type(exc).__name__})", level=logging.WARNING)
        return None


def attach_job(h: Any, job: dict) -> None:
    """After a queue accepts a job: record its owner when someone is signed in (first owner wins)."""
    user_id = current_user(h)
    kind = job.get("kind")
    if user_id is None or kind not in ident.KINDS or not isinstance(job.get("id"), str):  # a group take (kind "group") is not owned
        return
    try:
        identity(h.app).attach(job["id"], user_id, kind, job.get("entry_id"), job.get("people_job"), "submit")
    except Exception as exc:
        applog.log(f"auth: could not record the owner of a take ({type(exc).__name__})", level=logging.WARNING)


def on_entry(h: Any, inner: Callable | None) -> Callable | None:
    """Compose the trainer's `on_entry` callback so the signed-in user owns the catalog entry Part 6 names."""
    return owned_entry(h.app, current_user(h), inner)


def job_owner(app: Any, job_id: str) -> str | None:
    """The user `attach_job` recorded for `job_id` at submit, or None (signed out, no identity file, a store fault)."""
    if not ident.db_path(app.state).is_file():
        return None
    try:
        return identity(app).owner_of(job_id)
    except Exception as exc:  # an unknown owner leaves the entry unowned, as for a signed-out take
        applog.log(f"auth: could not read the owner of a take ({type(exc).__name__})", job_id, level=logging.WARNING)
        return None


def owned_entry(app: Any, user_id: str | None, inner: Callable | None) -> Callable | None:
    """`inner` wrapped so `user_id` owns the entry it is called with; `inner` itself when there is no user.

    `on_entry` uses it at submit and `resume.py` for a trainer job rebuilt after a restart (TICKET-287)."""
    if user_id is None:
        return inner
    store = identity(app)

    def wrapped(entry_id: str) -> Any:
        result = inner(entry_id) if inner is not None else None
        try:
            store.attach_entry(entry_id, user_id, "")
        except Exception as exc:
            applog.log(f"auth: could not record the owner of an entry ({type(exc).__name__})", level=logging.WARNING)
        return result

    return wrapped


def may_view_entry(h: Any, entry_id: str) -> bool:
    """False for an entry its owner marked "only me" when the caller is not that owner, and when the store errs."""
    if not ident.db_path(h.app.state).is_file():
        return True
    try:
        found = identity(h.app).entry_owner(entry_id)
    except Exception as exc:  # "only me" fails closed: when the store cannot answer, the page stays hidden
        applog.log(f"auth: could not check who may view an entry ({type(exc).__name__})", level=logging.WARNING)
        return False
    if found is None or not found[1]:
        return True
    return current_user(h) == found[0]


def forget_job(app: Any, job_id: str) -> None:
    """Delete hook: drop the ownership row of a deleted take."""
    if ident.db_path(app.state).is_file():
        identity(app).forget_job(job_id)
