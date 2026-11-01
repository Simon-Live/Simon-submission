"""HTTP routes of opt-in sign-in and the signed-in person's own data (docs/specs/identity.md "Routes").

`server.py` `_api` calls `handle(h, method, route)` with `route` below `api/`. Every answer carries
`Referrer-Policy: no-referrer`. A POST must pass the CSRF guard (`auth.origin_ok`) and carry at most 4 KB of JSON.
Nothing here logs an address, a token, a code or a session id.
"""

from __future__ import annotations

import importlib
import json
import logging
from typing import Any, Callable

from part7 import applog, auth, challenge_routes, identity, jobs, labels, mail
from part7.http_body import drain_before_refusal

MSG_SIGN_IN = "Sign in to see this."
MSG_CSRF = "This request came from another site."
MSG_INVALID = "This link or code is not valid or has expired. Ask for a new one."
MSG_EMAIL = "Enter a valid email address."
MSG_ORIGIN = "Sign-in mail cannot be sent for this address."
MSG_RATE = "Too many tries. Wait a little, then try again."
MSG_OFF = "Sign-in is not available."
MSG_BAD = "The request is not valid."
MSG_TOO_BIG = "The request is too large."
MSG_OTHER = "This take is kept by another account."
MSG_NO_JOB = challenge_routes.MSG_NO_JOB
MSG_NO_ENTRY = "This movement is not yours."
MSG_BUSY = "Try again when these finish."
CONFIRM = "delete"
VERSION_MAX = 40

# Delete-take seam: `remover(app, job_id) -> "removed" | "busy" | "gone"`. server.build_app sets it to
# `delete_routes.remove_for_account`; None (a bare test app) leaves the folders to the 7-day sweep.
TakeRemover = Callable[[Any, str], str]
TAKE_REMOVER: TakeRemover | None = None


def _reply(h: Any, status: int, obj: Any = None, headers: dict[str, str] | None = None) -> None:
    body = b"" if obj is None else json.dumps(obj).encode("utf-8")
    extra = {"Referrer-Policy": "no-referrer", **(headers or {})}
    h._send(status, body, "application/json; charset=utf-8", extra)


def _fail(h: Any, status: int, message: str, **more: Any) -> None:
    _reply(h, status, {"ok": False, "error": message, "message": message, **more})


def _history(name: str) -> Callable | None:
    """`part7.history_store.<name>` when that module exists (C-STORE); None before it lands."""
    try:
        module = importlib.import_module("part7.history_store")
    except ModuleNotFoundError as exc:
        if exc.name != "part7.history_store":
            raise
        return None
    return getattr(module, name, None)


def _post_body(h: Any, *, fields: bool = True) -> dict[str, Any] | None:
    """The JSON body of a guarded POST, or None after answering 403, 413 or 400. With `fields=False` only CSRF and the
    size are checked, the body is drained and ignored, and `{}` returns (sign-out)."""
    if not auth.origin_ok(h):
        _fail(h, 403, MSG_CSRF)
        return None
    try:
        length = int(h.headers.get("Content-Length") or 0)
    except ValueError:
        length = -1
    if length < 0 or length > auth.BODY_MAX:
        drain_before_refusal(h, length)  # TICKET-194: the answer arrives instead of a connection reset
        _fail(h, 413 if length > auth.BODY_MAX else 400, MSG_TOO_BIG if length > auth.BODY_MAX else MSG_BAD)
        return None
    raw = h.rfile.read(length) if length else b""
    if not fields:
        return {}
    try:
        doc = json.loads(raw or b"null")
    except ValueError:
        doc = None
    if not isinstance(doc, dict):
        _fail(h, 400, MSG_BAD)
        return None
    return doc


def _user_or_401(h: Any) -> str | None:
    user_id = auth.current_user(h)
    if user_id is None:
        _fail(h, 401, MSG_SIGN_IN)
    return user_id


def _me_doc(h: Any, user_id: str | None) -> dict[str, Any]:
    st = auth.state(h.app)
    doc: dict[str, Any] = {"available": st.available, "signed_in": False}
    user = auth.identity(h.app).user(user_id) if user_id else None
    if user is not None:
        doc.update(signed_in=True, user_id=user["user_id"], email=user["email"], retention=user["retention"])
    return doc


# ----- sign-in ---------------------------------------------------------------------------------
def _start(h: Any) -> None:
    st = auth.state(h.app)
    if not st.available:
        return _fail(h, 404, MSG_OFF)
    doc = _post_body(h)
    if doc is None:
        return
    ip = auth.client_key(h)
    if not st.start_limit.hit(ip):
        return _fail(h, 429, MSG_RATE)
    email = identity.normalise_email(doc.get("email"))
    if email is None:
        return _fail(h, 400, MSG_EMAIL)
    if auth.public_origin(h) is None:  # a forged Host would put the sign-in link on someone else's site
        return _fail(h, 403, MSG_ORIGIN)
    store = st.store
    made = store.start_challenge(email, ip)
    key = store.email_key(email)
    if made is None:  # a per-address or global limit: the same 202, no mail
        applog.log(f"auth: sign-in limited for {key}", level=logging.INFO)
    else:
        token, code = made
        st.mailer.send_sign_in(email, code, auth.public_link(h, token))
        applog.log(f"auth: sign-in started for {key}")
    _reply(h, 202, {"ok": True})


def _verify(h: Any) -> None:
    st = auth.state(h.app)
    if not st.available:
        return _fail(h, 404, MSG_OFF)
    doc = _post_body(h)
    if doc is None:
        return
    if not st.verify_limit.hit(auth.client_key(h)):
        return _fail(h, 429, MSG_RATE)
    store = st.store
    token, email, code = doc.get("token"), doc.get("email"), doc.get("code")
    if isinstance(token, str):
        user_id = store.consume_token(token)
    elif isinstance(email, str) and isinstance(code, str):
        user_id = store.consume_code(email, code)
    else:
        user_id = None
    presented = auth.sid_from(h)
    if presented:  # a sid sent with the verify is revoked whatever the outcome (no fixation)
        store.end_session(presented)
    if user_id is None:
        return _fail(h, 400, MSG_INVALID)
    sid = store.new_session(user_id)
    user = store.user(user_id) or {}
    applog.log(f"auth: signed in {user_id}")
    _reply(h, 200, {"user_id": user_id, "email": user.get("email")}, {"Set-Cookie": auth.cookie_header(h, sid)})


def _signout(h: Any) -> None:
    if _post_body(h, fields=False) is None:
        return
    sid = auth.sid_from(h)
    if sid:
        auth.identity(h.app).end_session(sid)
    _reply(h, 204, None, {"Set-Cookie": auth.cookie_header(h, None)})


# ----- the signed-in person's data -----------------------------------------------------------------
def _claim(h: Any) -> None:
    doc = _post_body(h)
    if doc is None or (user_id := _user_or_401(h)) is None:
        return
    job_id = doc.get("job_id")
    job = h.app.queue.get(job_id) if isinstance(job_id, str) and jobs.JOB_ID_RE.match(job_id) else None
    kind = _kind_of(job)
    if job is None or kind is None:
        return _fail(h, 404, MSG_NO_JOB)
    store = auth.identity(h.app)
    if not store.attach(job_id, user_id, kind, job.get("entry_id"), job.get("people_job"), "claim"):
        return _fail(h, 409, MSG_OTHER)
    result = job.get("result") if isinstance(job.get("result"), dict) else {}
    if kind == "trainer" and isinstance(result.get("entry_id"), str):
        store.attach_entry(result["entry_id"], user_id, job_id)
    claim = _history("claim")
    if claim is not None:
        claim(h.app.state, user_id, job_id)
    _reply(h, 200, {"claimed": True, "kind": kind})


def _kind_of(job: dict | None) -> str | None:
    """`follow` or `trainer`. A group take (job kind `group`) is not owned, and neither is any other kind; a follow
    cut from one person of a people job is an ordinary follow take."""
    if not job or job.get("kind") not in ("follow", "trainer"):
        return None
    return job["kind"]


def _score_of(h: Any, job_id: str) -> tuple[Any, Any]:
    """Score and grade from the job's own `analysis.json` (never stored twice)."""
    path = h.app.queue.job_dir(job_id) / "work" / "follower" / "analysis.json"
    try:
        score = json.loads(path.read_text(encoding="utf-8")).get("score")
    except (OSError, ValueError, AttributeError):
        return None, None
    if not isinstance(score, dict):
        return None, None
    value, grade = score.get("value"), score.get("grade")
    return (value if isinstance(value, (int, float)) and not isinstance(value, bool) else None,
            grade if isinstance(grade, str) else None)


def _takes(h: Any, user_id: str) -> None:
    out = []
    for take in auth.identity(h.app).takes_of(user_id):
        job = h.app.queue.get(take["job_id"])
        score, grade = _score_of(h, take["job_id"]) if job else (None, None)
        out.append({"job_id": take["job_id"], "kind": take["kind"], "entry_id": take["entry_id"],
                    "created_at": take["created_at"], "status": job["status"] if job else "expired",
                    "score": score, "grade": grade})
    _reply(h, 200, {"takes": out})


def _entries(h: Any, user_id: str) -> None:
    out = []
    for entry in auth.identity(h.app).entries_of(user_id):
        out.append({"entry_id": entry["entry_id"], "name": labels.entry_name(h.app.child, entry["entry_id"]),
                    "created_at": entry["created_at"], "only_me": entry["only_me"]})
    _reply(h, 200, {"entries": out})


def _entry_switch(h: Any, entry_id: str) -> None:
    doc = _post_body(h)
    if doc is None or (user_id := _user_or_401(h)) is None:
        return
    value = doc.get("only_me")
    if not isinstance(value, bool):
        return _fail(h, 400, MSG_BAD)
    if not auth.identity(h.app).set_only_me(entry_id, user_id, value):
        return _fail(h, 404, MSG_NO_ENTRY)
    _reply(h, 200, {"entry_id": entry_id, "only_me": value})


def _consent(h: Any) -> None:
    doc = _post_body(h)
    if doc is None or (user_id := _user_or_401(h)) is None:
        return
    retention, version = doc.get("retention"), doc.get("version")
    if not isinstance(retention, bool) or not isinstance(version, str) or not 0 < len(version) <= VERSION_MAX:
        return _fail(h, 400, MSG_BAD)
    store = auth.identity(h.app)
    store.set_consent(user_id, version, retention)
    if retention is False:  # withdrawing retention removes every history copy and report now (history.md)
        withdraw = _history("withdraw_retention")
        if withdraw is not None:
            withdraw(h.app.state, user_id)
    _reply(h, 200, {"retention": (store.user(user_id) or {}).get("retention")})


def _delete(h: Any) -> None:
    doc = _post_body(h)
    if doc is None or (user_id := _user_or_401(h)) is None:
        return
    if doc.get("confirm") != CONFIRM:
        return _fail(h, 400, MSG_BAD)
    store, app = auth.identity(h.app), h.app
    owned = store.takes_of(user_id)
    busy = [t["job_id"] for t in owned if (app.queue.get(t["job_id"]) or {}).get("status") in ("queued", "running")]
    removed = 0
    if not busy:
        for take in owned:
            outcome = TAKE_REMOVER(app, take["job_id"]) if TAKE_REMOVER is not None else "gone"
            if outcome == "busy":
                busy.append(take["job_id"])
            elif outcome == "removed":
                removed += 1
    if busy:
        return _fail(h, 409, MSG_BUSY, busy=busy)
    unlinked = len(store.entries_of(user_id))
    email = (store.user(user_id) or {}).get("email")
    forget = _history("forget")
    if forget is not None:
        forget(app.state, user_id)
    store.delete_user(user_id)
    if email:
        mail.purge_outbox(app.state, email)
    applog.log(f"auth: account deleted {user_id}")
    _reply(h, 200, {"deleted": True, "takes_removed": removed, "entries_unlinked": unlinked},
           {"Set-Cookie": auth.cookie_header(h, None)})


# ----- dispatch -------------------------------------------------------------------------------------
def handle(h: Any, method: str, route: str) -> bool:
    """Answer `auth/*` and `me/*` routes (below `api/`); False when `route` is not one of them."""
    parts = route.split("/")
    if parts[0] not in ("auth", "me") or len(parts) < 2:
        return False
    get = method in ("GET", "HEAD")
    if parts[0] == "me" and not auth.state(h.app).available:  # sign-in off: the person's data routes do not exist
        _fail(h, 404, MSG_OFF)
        return True
    if route == "auth/me" and get:
        _reply(h, 200, _me_doc(h, auth.current_user(h)))
    elif route == "auth/start" and method == "POST":
        _start(h)
    elif route == "auth/verify" and method == "POST":
        _verify(h)
    elif route == "auth/signout" and method == "POST":
        _signout(h)
    elif route == "me/claims" and method == "POST":
        _claim(h)
    elif route in ("me/takes", "me/entries") and get:
        user_id = _user_or_401(h)
        if user_id is not None:
            (_takes if route == "me/takes" else _entries)(h, user_id)
    elif len(parts) == 3 and parts[:2] == ["me", "entries"] and method == "POST":
        _entry_switch(h, parts[2])
    elif route == "me/consent" and method == "POST":
        _consent(h)
    elif route == "me/delete" and method == "POST":
        _delete(h)
    else:
        return False
    return True
