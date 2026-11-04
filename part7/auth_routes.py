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
from urllib.parse import parse_qs, urlsplit

from part7 import (applog, attribution, auth, challenge_routes, creator, devices, entry_access, history_store, identity, jobs, labels, mail,
                   mail_status, mail_webhook, modal_creds, model_only, model_store, shown_score, staging_mailbox, trainer_publish)
from part7 import serverless_route
from part7.http_body import drain_before_refusal

MSG_SIGN_IN = "Sign in to see this."
MSG_EVICTED = "This movement was taken out of public view after a report. It stays visible to you."
MSG_CSRF = "This request came from another site."
MSG_INVALID = "This link or code is not valid or has expired. Ask for a new one."
MSG_EMAIL = "Enter a valid email address."
MSG_ORIGIN = "Sign-in mail cannot be sent for this address."
MSG_RATE = "Too many tries. Wait a little, then try again."
MSG_OFF = "Sign-in is not available."
MSG_BAD = "The request is not valid."
MSG_TOO_BIG = "The request is too large."
MSG_OTHER = "This take is kept by another account."
MSG_NOT_CREATOR = "Only the device that made this take can keep it. Open it on that device and keep it there."
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


def guarded_body(h: Any) -> dict[str, Any] | None:
    """`_post_body` for the other owner-only POST routes (teacher_routes shares): CSRF, size and a JSON object."""
    return _post_body(h)


def _user_or_401(h: Any) -> str | None:
    user_id = auth.current_user(h)
    if user_id is None:
        _fail(h, 401, MSG_SIGN_IN)
    return user_id


def _me_doc(h: Any, user_id: str | None) -> dict[str, Any]:
    st = auth.state(h.app)
    doc: dict[str, Any] = {"available": st.available, "signed_in": False}
    if st.mailer.transport == "outbox":
        doc["outbox"] = True  # the sign-in screen links the staging test mailbox
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
    made, why = store.start_challenge_why(email, ip)
    key = store.email_key(email)
    attempt = st.mailer.board.new_id()
    if made is None:  # a per-address or global limit: the same 202 and the same "sent", no mail
        st.mailer.board.set(attempt, mail_status.SENT)
        applog.log(f"auth: sign-in limited for {key} ({why})", level=logging.INFO)
        if why == "global":  # the security limit stays; the operator hears that real people may be getting no code
            applog.anomaly("signin_global_limited", limit=identity.GLOBAL_MAILS_PER_HOUR)
    else:
        token, code = made
        st.mailer.send_sign_in(email, code, auth.public_link(h, token), attempt)
        applog.log(f"auth: sign-in started for {key}")
    _reply(h, 202, {"ok": True, "attempt": attempt})


def _mail_status(h: Any) -> None:
    """What became of the mail of one attempt: `pending`, `sent`, `failed` or `unknown` (expired, or not an id). The id is
    random and ties to no address, and a rate-limited address reads `sent`, so this tells nothing about any account."""
    st = auth.state(h.app)
    if not st.available:
        return _fail(h, 404, MSG_OFF)
    if not st.status_limit.hit(auth.client_key(h)):
        return _fail(h, 429, MSG_RATE)
    raw = parse_qs(urlsplit(h.path).query).get("id", [""])[0]
    status = st.mailer.board.get(raw) if mail_status.ID_RE.match(raw) else mail_status.UNKNOWN
    _reply(h, 200, {"status": status}, {"Cache-Control": "no-store"})


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
    sid = store.new_session(user_id, devices.device_label(h.headers.get("User-Agent")))  # a coarse label, never the User-Agent
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
    from part7 import delete_routes  # here: delete_routes imports route modules that import this one
    if job_id in delete_routes.featured(h.app):  # TICKET-373: a featured id is public, so it proves no claim
        return _fail(h, 403, delete_routes.MSG_NO_CLAIM)
    store = auth.identity(h.app)
    # LEG-H4: a result link alone never claims; the account that holds the take may copy it from any browser
    if store.owner_of(job_id) != user_id and not creator.valid(h.app.state, job_id, doc.get("creator_token")):
        return _fail(h, 403, MSG_NOT_CREATOR)
    if not store.attach(job_id, user_id, kind, job.get("entry_id"), job.get("people_job"), "claim"):
        return _fail(h, 409, MSG_OTHER)
    result = job.get("result") if isinstance(job.get("result"), dict) else {}
    if kind == "trainer" and isinstance(result.get("entry_id"), str):
        store.attach_entry(result["entry_id"], user_id, job_id)
        entry_access.record(h.app.state, result["entry_id"], trainer_job=job_id, owner=user_id,
                            published=entry_access.published_default(None))  # fills the owner of a signed-out trainer take
    claim = _history("claim")
    copied = claim(h.app.state, user_id, job_id) if claim is not None else False
    _reply(h, 200, {"claimed": True, "kind": kind, "kept": kind != "follow" or copied is True})  # kept: "See it in Me" holds


def _kind_of(job: dict | None) -> str | None:
    """`follow` or `trainer`. A group take (job kind `group`) is not owned, and neither is any other kind; a follow
    cut from one person of a people job is an ordinary follow take."""
    if not job or job.get("kind") not in ("follow", "trainer"):
        return None
    return job["kind"]


def _score_of(h: Any, job_id: str, light: Any = None) -> tuple[Any, Any, Any]:
    """Score, grade and the shown score (one-letter.md) from the job's own `analysis.json` (never stored twice)."""
    path = h.app.queue.job_dir(job_id) / "work" / "follower" / "analysis.json"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        score = doc.get("score")
    except (OSError, ValueError, AttributeError):
        return None, None, None
    if not isinstance(score, dict):
        return None, None, None
    value, grade = score.get("value"), score.get("grade")
    return (value if isinstance(value, (int, float)) and not isinstance(value, bool) else None,
            grade if isinstance(grade, str) else None, shown_score.of_analysis(doc, light))


def _takes(h: Any, user_id: str) -> None:
    out = []
    for take in auth.identity(h.app).takes_of(user_id):
        job = h.app.queue.get(take["job_id"])
        score, grade, shown = _score_of(h, take["job_id"], history_store.light_of(job)) if job else (None, None, None)
        made = (job or {}).get("entry_id") or ((job or {}).get("result") or {}).get("entry_id")  # a trainer take is attached at submit, before its movement exists
        has_copy = _history("has_copy")  # a follow take is kept when its history copy exists; a row alone is the 7-day job
        kept = take["kind"] != "follow" or (has_copy is not None and has_copy(h.app.state, user_id, take["entry_id"] or made, take["job_id"]) is True)
        out.append({"job_id": take["job_id"], "kind": take["kind"], "entry_id": take["entry_id"] or made, "kept": kept,
                    "created_at": take["created_at"], "status": job["status"] if job else "expired",
                    "score": score, "grade": grade, "shown": shown, "video_kept": model_only.kept(job),
                    "attribution": attribution.for_take(h, take["job_id"], take["entry_id"], owner=user_id)})
    _reply(h, 200, {"takes": out})


def _shown(h: Any, entry_id: str) -> bool | None:
    """Whether the movement's row publishes it; None when it has no row and is no shipped sample, so nobody sees it,
    its owner included (W-N1, review residual 1). A shipped sample without a row is shown to everyone."""
    row = entry_access.get(h.app.state, entry_id)
    if row is not None:
        return row.get("published") is not False
    return True if entry_access.shipped_sample(h.app.child.catalog_dir, entry_id) else None


def _entries(h: Any, user_id: str) -> None:
    out = []
    store = auth.identity(h.app)
    minor = trainer_publish.owner_minor(h.app, store, user_id)  # once per request, not per movement (go-live R3)
    for entry in store.entries_of(user_id):
        eid = entry["entry_id"]
        shown = _shown(h, eid)
        out.append({"entry_id": eid, "name": labels.entry_name(h.app.child, eid, h.app.state),
                    "created_at": entry["created_at"], "only_me": entry["only_me"],
                    "published": shown is True, "hidden": shown is None,
                    # the Watch switch shows only when the server would accept a publish (private-default D1, D5)
                    "may_publish": not trainer_publish.publish_refused(h.app, store, eid, user_id, minor),
                    "floor_work": labels.floor_work(h.app.state, eid),
                    "attribution": attribution.for_entry(h, eid)})
    _reply(h, 200, {"entries": out})


def _entry_switch(h: Any, entry_id: str) -> None:
    doc = _post_body(h)
    if doc is None or (user_id := _user_or_401(h)) is None:
        return
    value, floor, publish = doc.get("only_me"), doc.get("floor_work"), doc.get("published")
    given = (value, floor, publish)
    if not any(isinstance(v, bool) for v in given) or any(v is not None and not isinstance(v, bool) for v in given):
        return _fail(h, 400, MSG_BAD)
    store = auth.identity(h.app)
    if isinstance(floor, bool) and not labels.ENTRY_ID_RE.match(entry_id):  # the floor-work store holds no such id
        return _fail(h, 404, MSG_NO_ENTRY)
    if (found := store.entry_owner(entry_id)) is None or found[0] != user_id:
        return _fail(h, 404, MSG_NO_ENTRY)
    if publish is True and (entry_access.get(h.app.state, entry_id) or {}).get("evicted"):  # go-live-readiness.md "Evict"
        return _fail(h, 403, MSG_EVICTED)
    if publish is True and trainer_publish.publish_refused(h.app, store, entry_id, user_id):  # D1: never a minor's
        return _fail(h, 403, trainer_publish.MSG_MINOR_PUBLISH)
    if publish is True and trainer_publish.statement_missing(h.app.state, entry_id, doc):  # PM-B3: nobody under 18
        return _fail(h, 403, trainer_publish.MSG_STATEMENT)
    stated = trainer_publish.stated(doc)
    if isinstance(value, bool):
        store.set_only_me(entry_id, user_id, value)
    if isinstance(floor, bool):
        labels.set_floor_work(h.app.state, entry_id, floor)  # floor-work.md: Part 7's own store, read by every Part 3 call
    if isinstance(publish, bool):  # the owner's explicit publish choice (prod-data.md); a row is made if none exists
        if not entry_access.set_published(h.app.state, entry_id, publish, nobody_under_18=stated):
            entry_access.record(h.app.state, entry_id, owner=user_id, published=publish, nobody_under_18=stated)
    _reply(h, 200, {"entry_id": entry_id, "only_me": found[1] if value is None else value,
                    **({"floor_work": floor} if isinstance(floor, bool) else {}),
                    **({"published": publish} if isinstance(publish, bool) else {})})


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
        from part7 import progress_sheet  # TICKET-283: a progress sheet holds copies of those takes' measures, so it goes too
        progress_sheet.drop_shares(store, user_id)
    _reply(h, 200, {"retention": (store.user(user_id) or {}).get("retention")})


def delete_account(app: Any, user_id: str) -> dict[str, Any]:
    """Delete everything of `user_id` (identity.md "Delete my data", prod-data.md): takes, the movements they recorded
    with every public copy, history, models, references, outbox mail, then the account. `{busy}` and nothing deleted
    while one of their takes or a follow of their movement still runs; else `{takes_removed, entries_removed,
    entries_unlinked}` (unlinked: a shipped sample the account was named on, which stays)."""
    from part7 import delete_routes  # the movements they recorded and every public copy (APP-H4, LEG-C2)
    store = auth.identity(app)
    owned = store.takes_of(user_id)
    movements = delete_routes.account_entries(app, user_id)  # before a trainer take's delete drops its entry row
    busy = [t["job_id"] for t in owned if (app.queue.get(t["job_id"]) or {}).get("status") in ("queued", "running")]
    made, made_busy = delete_routes.account_jobs(app, user_id)  # people jobs and group takes have no takes row (DI-N1)
    busy += made_busy
    removed = 0
    if not busy:
        for take in owned:
            outcome = TAKE_REMOVER(app, take["job_id"]) if TAKE_REMOVER is not None else "gone"
            if outcome == "busy":
                busy.append(take["job_id"])
            elif outcome == "removed":
                removed += 1
    entries: dict[str, list[str]] = {"removed": [], "kept": [], "busy": []}
    if not busy:
        entries = delete_routes.remove_entries(app, movements)
        busy += entries["busy"]
    if busy:
        return {"busy": busy}
    board_jobs = [t["job_id"] for t in owned] + list(made)  # read while the records exist: a board row from before `owner` and `poster` is found by its take
    delete_routes.remove_made(app, user_id, made)
    email = (store.user(user_id) or {}).get("email")
    forget = _history("forget")
    if forget is not None:
        forget(app.state, user_id)
    modal_creds.remove(app.state, user_id)  # TICKET-367: their own Modal credentials file
    for model_id in model_store.delete_all(app.state, f"u:{user_id}"):  # the models they imported or generated, files and spool entries
        serverless_route.forget_job(app.state, model_id)  # AC-SC4: and what is still at Modal for them
    delete_routes.forget_account(app, user_id, board_jobs)  # the boards they made, also on another person's movement (D7)
    store.delete_user(user_id)
    from part7 import my_reference, reference_approval  # again, only these two: an approval under way when the account went leaves no copy (ADR-0019)
    reference_approval.forget(app.state, user_id)
    my_reference.forget(app.state, user_id)
    if email:
        mail.purge_outbox(app.state, email)
        from part7 import challenge_visibility, invite_mail  # their address off every invite list; an unused stop key goes, a stop stays
        challenge_visibility.forget_address(app.state, email)
        invite_mail.forget(app.state, invite_mail.stop_key(store.pepper, email))
    return {"takes_removed": removed, "entries_removed": len(entries["removed"]), "entries_unlinked": len(entries["kept"])}


def _delete(h: Any) -> None:
    doc = _post_body(h)
    if doc is None or (user_id := _user_or_401(h)) is None:
        return
    if doc.get("confirm") != CONFIRM:
        return _fail(h, 400, MSG_BAD)
    outcome = delete_account(h.app, user_id)
    if "busy" in outcome:
        return _fail(h, 409, MSG_BUSY, busy=outcome["busy"])
    applog.log(f"auth: account deleted {user_id}")
    _reply(h, 200, {"deleted": True, **outcome}, {"Set-Cookie": auth.cookie_header(h, None)})


def _outbox(h: Any) -> None:
    """The staging test mailbox: the messages sent to exactly the address in `?email=`, newest first (identity.md)."""
    st = auth.state(h.app)
    if st.mailer.transport != "outbox":
        return _fail(h, 404, MSG_OFF)
    if not st.verify_limit.hit(auth.client_key(h)):
        return _fail(h, 429, MSG_RATE)
    raw = parse_qs(urlsplit(h.path).query).get("email", [""])[0]
    email = identity.normalise_email(raw)
    if email is None:
        return _fail(h, 400, MSG_EMAIL)
    _reply(h, 200, {"messages": staging_mailbox.messages_for(h.app.state, email), "minutes": staging_mailbox.TTL_S // 60},
           {"Cache-Control": "no-store"})


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
    if route == "auth/mail-webhook" and method == "POST":  # Resend's bounce and complaint events (signed; mail-delivery.md)
        mail_webhook.handle(h, h.app.state, auth.state(h.app).mailer.keyer, _reply)
    elif route == "auth/me" and get:
        _reply(h, 200, _me_doc(h, auth.current_user(h)))
    elif route == "auth/outbox" and get:
        _outbox(h)
    elif route == "auth/mail-status" and get:
        _mail_status(h)
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
