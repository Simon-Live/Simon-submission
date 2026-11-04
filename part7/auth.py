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

from part7 import applog, config, consent_record, creator, entry_access, mail, prod_check, quota
from part7.prod_mode import is_prod
from part7 import identity as ident

COOKIE = "s7_sid"
COOKIE_MAX_AGE = ident.SESSION_ABSOLUTE_S
BODY_MAX = 4096
START_PER_IP = (10, 3600)  # requests, seconds
VERIFY_PER_IP = (30, 600)
STATUS_PER_IP = (200, 600)  # the code screen asks api/auth/mail-status every 1.5 s for up to 40 s
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
        self.status_limit = Limiter(*STATUS_PER_IP)
        self._store: ident.IdentityStore | None = None
        self.mailer.keyer = lambda address: self.store.email_key(address.strip().lower())  # the same hash the sign-in lines carry
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
                self._store.idle_remover = self._remove_idle
            return self._store

    def _remove_idle(self, user_id: str) -> bool:
        """An account idle for 180 days goes whole, as "Delete my data" (LEG-M1); False while a take of it runs."""
        from part7 import auth_routes

        return "busy" not in auth_routes.delete_account(self.app, user_id)


def _pepper(state: Path) -> bytes:
    """`SIMON7_AUTH_PEPPER` from the keys folder (outside prod also the identity folder when that is not writable); made
    on first use, 0600."""
    from part7 import keys

    # byok R7: prod keeps the pepper with the other secrets only; a copy in the state dir would ride in every backup
    folders = (config.keys_dir(),) if is_prod() else (config.keys_dir(), Path(state) / "identity")
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


def client_addr(h: Any) -> str | None:
    """The client address every limiter counts (app-surface R6), or None for a direct local request.

    The server binds 127.0.0.1, so a loopback peer is the gateway and its forwarded address is trusted: `Cf-Connecting-Ip`,
    else (outside prod only) a single `X-Forwarded-For`. In prod only `Cf-Connecting-Ip` counts (the edge sets it and
    strips the rest), so no `X-Forwarded-For` a caller writes moves a count (go-live-readiness.md "Identity headers",
    HARDENING 2.5). A loopback peer without one is a local probe. Any other peer is its own address: a forwarded header
    from it is ignored."""
    if not _peer_is_loopback(h):
        return str(h.client_address[0])
    forwarded = (h.headers.get("Cf-Connecting-Ip") or "").strip()
    xff = "" if is_prod() else (h.headers.get("X-Forwarded-For") or "").strip()
    return forwarded or (xff if xff and "," not in xff else None)


def client_key(h: Any) -> str:
    """A short hash of the client address (`client_addr`, else the peer), for throttling only (never for authorisation)."""
    return quota.visitor_key(client_addr(h) or str(h.client_address[0])) or "unknown"


def is_https(h: Any) -> bool:
    """The gateway's rule: a loopback peer and either `Cf-Connecting-Ip` or `X-Forwarded-Proto: https`."""
    if not _peer_is_loopback(h):
        return False
    return bool(h.headers.get("Cf-Connecting-Ip")) or (h.headers.get("X-Forwarded-Proto") or "").strip().lower() == "https"


def same_origin(h: Any) -> bool:
    """An `Origin` whose host and port equal `Host`, and a same-origin fetch when the browser says which (no body rule)."""
    origin, host = h.headers.get("Origin"), (h.headers.get("Host") or "").strip().lower()
    if not origin or not host or urlsplit(origin).netloc.lower() != host:
        return False
    site = h.headers.get("Sec-Fetch-Site")
    return site is None or site.strip().lower() == "same-origin"


def origin_ok(h: Any) -> bool:
    """CSRF guard for a POST: JSON content type and `same_origin`."""
    ctype = (h.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    return ctype == "application/json" and same_origin(h)


def public_origin(h: Any) -> str | None:
    """The origin a sign-in link may carry, or None when this request cannot be trusted to name one.

    `SIMON7_PUBLIC_ORIGIN` (a pinned `https://host`) wins. Without it: in local mode a loopback `Host`; on staging a
    `Host` that came through the gateway hop (a loopback peer with `Cf-Connecting-Ip` or `X-Forwarded-Proto`), which
    routes on the hostname itself. Any other `Host` (a forged one on a direct connection) is refused."""
    pinned = (prod_check.origin() or "") if is_prod() else os.environ.get("SIMON7_PUBLIC_ORIGIN", "").strip().rstrip("/")
    if is_prod() and not pinned:
        return None  # prod never builds a link from a request's Host
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
    if is_prod() or is_https(h):  # hosting audit R-H13: prod is https only, whatever headers the hop sent
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
    """After a queue accepts a job: hand the submitting device the creator token of a follow or trainer take (in the
    202 answer only, never in the job record), give a pending trainer movement its job id, and record the owner when
    someone is signed in (first owner wins). `job` is the queue's view copy, and the idempotency store keeps the answer
    without the token (server `_json`), so the token reaches no file and a replayed answer carries none."""
    job_id, kind = job.get("id"), job.get("kind")
    link = getattr(h, "_entry_link", None)
    if link is not None and isinstance(job_id, str):  # on_entry ran earlier in this same trainer request
        h._entry_link = None
        link.job(job_id)
    if isinstance(job_id, str) and kind in ident.KINDS:
        try:
            job["creator_token"] = creator.token_for(h.app.state, job_id)
        except (OSError, ValueError) as exc:
            applog.log(f"auth: no creator token for a take ({type(exc).__name__})", level=logging.WARNING)
    user_id = current_user(h)
    if user_id is not None and consent_record.is_minor(job):  # go-live R6: the account's 13 to 17 answer is kept
        try:
            identity(h.app).mark_minor(user_id)
        except Exception as exc:
            applog.log(f"auth: could not keep the age answer of an account ({type(exc).__name__})", level=logging.WARNING)
    if user_id is None or kind not in ident.KINDS or not isinstance(job_id, str):  # a group take (kind "group") is not owned
        return
    try:
        identity(h.app).attach(job_id, user_id, kind, job.get("entry_id"), job.get("people_job"), "submit")
    except Exception as exc:
        applog.log(f"auth: could not record the owner of a take ({type(exc).__name__})", level=logging.WARNING)


def on_entry(h: Any, inner: Callable | None, publish: Any = None, deferred: bool = False) -> Callable | None:
    """Compose the trainer's `on_entry` callback: the signed-in user owns the catalog entry Part 6 names, and the
    entry's access row (entry_access.py) is written with the take's job id. `publish` is the uploader's explicit
    opt-in for this upload (`True` only); without it a prod movement stays private (`policy("trainer_public")`), and
    `entry_access.GPC_PRIVATE` (Global Privacy Control, `trainer_publish.choice`) keeps it private everywhere.
    With `deferred` the row stays unpublished until the job calls the callback's `ready()` (entry_access.Link)."""
    user_id = current_user(h)
    minor = bool(user_id) and _account_minor(h.app, user_id)  # go-live R6: an account that answered 13 to 17 never publishes
    link = entry_access.Link(h.app.state, user_id or "", entry_access.published_default(publish) and not minor, deferred)
    h._entry_link = link  # attach_job gives it the job id once the queue made the job
    return owned_entry(h.app, user_id, inner, link=link)


def _account_minor(app: Any, user_id: str) -> bool:
    """The identity row's 13 to 17 mark (kept after the 7-day job sweep); True when the store cannot say."""
    try:
        return identity(app).is_minor(user_id)
    except Exception as exc:  # noqa: BLE001  fails closed: an unknown answer is not an adult's
        applog.log(f"auth: could not read the age mark of an account ({type(exc).__name__})", level=logging.WARNING)
        return True


def job_owner(app: Any, job_id: str) -> str | None:
    """The user `attach_job` recorded for `job_id` at submit, or None (signed out, no identity file, a store fault)."""
    if not ident.db_path(app.state).is_file():
        return None
    try:
        return identity(app).owner_of(job_id)
    except Exception as exc:  # an unknown owner leaves the entry unowned, as for a signed-out take
        applog.log(f"auth: could not read the owner of a take ({type(exc).__name__})", job_id, level=logging.WARNING)
        return None


def owned_entry(app: Any, user_id: str | None, inner: Callable | None, *, job_id: str = "",
                link: entry_access.Link | None = None, publish: Any = None, deferred: bool = False) -> Callable:
    """`inner` wrapped so `user_id` owns the entry it is called with and the entry's access row is written; the
    wrapper's `ready()` is the link's (entry_access.Link.ready).

    `on_entry` uses it at submit (with its `link`) and `resume.py` for a trainer job rebuilt after a restart
    (TICKET-287; `job_id` names the rebuilt job and `publish` the opt-in its submit carried, kept in `_resume`)."""
    if link is None:
        minor = bool(user_id) and _account_minor(app, user_id)  # go-live R6, as on_entry
        link = entry_access.Link(app.state, user_id or "", entry_access.published_default(publish) and not minor, deferred)
        if job_id:
            link.job(job_id)
    store = identity(app) if user_id is not None else None

    def wrapped(entry_id: str) -> Any:
        result = inner(entry_id) if inner is not None else None
        try:
            link.saved(entry_id)
        except OSError as exc:  # the movement is saved; a missing row only loses the anonymous delete key
            applog.log(f"auth: could not record the access row of an entry ({type(exc).__name__})", level=logging.WARNING)
        if store is not None:
            try:
                store.attach_entry(entry_id, user_id, "")
            except Exception as exc:
                applog.log(f"auth: could not record the owner of an entry ({type(exc).__name__})", level=logging.WARNING)
        return result

    wrapped.ready = link.ready  # type: ignore[attr-defined]  processor.trainer_job calls it once the video is fit to show
    wrapped.reserve = link.reserve  # type: ignore[attr-defined]  chain.trainer: the held-back row before Part 6 saves (W-N1)
    return wrapped


def may_view_entry(h: Any, entry_id: str, minors: dict[str, bool] | None = None) -> bool:
    """False for an unpublished trainer movement (entry_access.py) unless the caller owns it or holds its creator
    token, for an entry its owner marked "only me" when the caller is not that owner, and when a store errs. `minors`
    is the request's cache of the owners' account marks (`entry_access.visible`, review R5)."""
    try:
        if not entry_access.visible(h.app.state, entry_id, current_user(h), h.headers.get(entry_access.HEADER),
                                    getattr(getattr(h.app, "child", None), "catalog_dir", None), minors):
            return False
    except Exception as exc:  # fails closed, as "only me" does
        applog.log(f"auth: could not check whether an entry is published ({type(exc).__name__})", level=logging.WARNING)
        return False
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
