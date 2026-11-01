"""HTTP routes of the student's history, `api/me/history...` (docs/specs/history.md "Routes"); `server.py` calls `handle`.

Every route needs a session (`part7.auth.current_user`, lane lc-auth): 401 without one, 404 for another user's
entry or take (the store is read by the signed-in user's id only). Claims are `POST api/me/claims` (auth's).
"""

from __future__ import annotations

from typing import Any


from part7 import history_facts, history_report, history_store, labels, result_media
from part7.auth_routes import MSG_CSRF, MSG_SIGN_IN  # one wording for the sign-in and CSRF refusals

MSG_NOT_FOUND = "There is nothing here."
MSG_METHOD = "Method not allowed."
MSG_CONSENT_BODY = "Send video as true or false and a version."
MSG_NO_REPORT = "No comparison has been made yet."
CLIP_URL = "api/me/history/{entry}/takes/{job}/clip.mp4"


def _user(h: Any) -> str | None:
    auth = history_store.optional_module("part7.auth")
    user = auth.current_user(h) if auth is not None else None
    return user if isinstance(user, str) and history_store.USER_ID_RE.match(user) else None


def _same_origin(h: Any) -> bool:
    auth = history_store.optional_module("part7.auth")
    return bool(auth is not None and auth.origin_ok(h))


def _public_take(entry: str, take: dict[str, Any]) -> dict[str, Any]:
    return {
        "take": take["take"], "job_id": take["job_id"], "at": take["at"], "duration_s": take["duration_s"],
        "score": take["score"], "grade": take["grade"], "private": take["private"],
        "clip": CLIP_URL.format(entry=entry, job=take["job_id"]) if take["clip"] else None,
    }


def _runner(h: Any) -> history_report.Runner:
    return history_report.runner_for(h.app.state, h.app.child.catalog_dir)


def _list(h: Any, user: str) -> None:
    state, rows = h.app.state, []
    for entry in history_store.entries(state, user):
        found = history_store.takes(state, user, entry)
        if not found:
            continue
        last = found[-1]
        rows.append({"entry_id": entry, "name": labels.entry_name(h.app.child, entry), "takes": len(found),
                     "latest": {"take": last["take"], "at": last["at"], "score": last["score"], "grade": last["grade"]}})
    h._json(200, {"entries": rows, "consent": history_store.consent(state, user),
                  "retention": history_store.retention_opt_in(state, user)})


def _entry(h: Any, user: str, entry: str) -> None:
    found = history_store.takes(h.app.state, user, entry)
    if not found:
        return h._error(404, MSG_NOT_FOUND)
    runner = _runner(h)
    hostable, key, _ = runner.plan(user, entry)
    h._json(200, {
        "entry_id": entry, "name": labels.entry_name(h.app.child, entry), "takes": [_public_take(entry, t) for t in found],
        "facts": history_facts.build(found, entry), "consent": history_store.consent(h.app.state, user),
        "retention": history_store.retention_opt_in(h.app.state, user),
        "report": runner.status(user, entry, key) or ("ready" if history_report.cached(h.app.state, user, entry, key) else "none"),
        "can_compare": len(hostable) >= history_report.MIN_TAKES,
    })


def _accepted(h: Any, state: str) -> None:
    retry = str(history_report.RETRY_AFTER_S)
    body = b'{"status": "%s", "retry_after": %s}' % (state.encode(), retry.encode())
    h._send(202, body, "application/json; charset=utf-8", {"Retry-After": retry})


def _post_report(h: Any, user: str, entry: str) -> None:
    if not history_store.takes(h.app.state, user, entry):
        return h._error(404, MSG_NOT_FOUND)
    try:
        kind, value = _runner(h).request(user, entry)
    except history_report.Refused as refusal:
        return h._error(refusal.status, refusal.message)
    if kind == "cached":
        return h._json(200, value)
    _accepted(h, value)


def _get_report(h: Any, user: str, entry: str) -> None:
    if not history_store.takes(h.app.state, user, entry):
        return h._error(404, MSG_NOT_FOUND)
    runner = _runner(h)
    _, key, _ = runner.plan(user, entry)
    hit = history_report.cached(h.app.state, user, entry, key)
    if hit is not None:
        return h._json(200, hit)
    running = runner.status(user, entry, key)
    if running:
        return _accepted(h, running)
    h._error(404, MSG_NO_REPORT)


def _clip(h: Any, user: str, entry: str, job: str) -> None:
    take = next((t for t in history_store.takes(h.app.state, user, entry) if t["job_id"] == job), None)
    if take is None or take["clip"] is None:
        return h._error(404, MSG_NOT_FOUND)
    result_media.serve_file(h, take["clip"])


def _consent(h: Any, user: str) -> None:
    doc = h._body_json()
    if doc is None:
        return
    try:
        out = history_store.set_consent(h.app.state, user, doc.get("video"), doc.get("version"))
    except ValueError:
        return h._error(400, MSG_CONSENT_BODY)
    h._json(200, out)


def _forget(h: Any, user: str, entry: str | None) -> None:
    h._json(200, {"removed": history_store.forget(h.app.state, user, entry)})


def handle(h: Any, method: str, route: str) -> bool:
    """Answer `route` (below `api/`) when it is a history route; False when it is not."""
    parts = route.split("/")
    if parts[:2] != ["me", "history"] or len(parts) > 6:
        return False
    user = _user(h)
    if user is None:
        h._error(401, MSG_SIGN_IN)
        return True
    read, rest = method in ("GET", "HEAD"), parts[2:]
    if method in ("POST", "DELETE") and not _same_origin(h):  # CSRF, as auth_routes: JSON content type and a same-origin Origin
        h._error(403, MSG_CSRF)
        return True
    entry = rest[0] if rest else None
    if entry == "consent" and len(rest) == 1:
        _consent(h, user) if method == "POST" else h._error(405, MSG_METHOD)
    elif entry is not None and not labels.ENTRY_ID_RE.match(entry):
        h._error(404, MSG_NOT_FOUND)
    elif not rest and read:
        _list(h, user)
    elif len(rest) <= 1 and method == "DELETE":
        _forget(h, user, entry)
    elif len(rest) == 1 and read:
        _entry(h, user, entry)
    elif rest[1:] == ["report"] and method == "POST":
        _post_report(h, user, entry)
    elif rest[1:] == ["report"] and read:
        _get_report(h, user, entry)
    elif len(rest) == 4 and rest[1] == "takes" and rest[3] == "clip.mp4" and read:
        _clip(h, user, entry, rest[2]) if history_store.JOB_ID_RE.match(rest[2]) else h._error(404, MSG_NOT_FOUND)
    else:
        known = not rest or rest[1:2] in (["report"], ["takes"])
        h._error(405 if known else 404, MSG_METHOD if known else MSG_NOT_FOUND)
    return True
