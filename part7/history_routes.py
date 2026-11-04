"""HTTP routes of the student's history, `api/me/history...` (docs/specs/history.md "Routes"); `server.py` calls `handle`.

Every route needs a session (`part7.auth.current_user`, lane lc-auth): 401 without one, 404 for another user's
entry or take (the store is read by the signed-in user's id only). Claims are `POST api/me/claims` (auth's).
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import parse_qs, urlsplit

from part7 import (attribution, muse_prod, history_all, history_all_routes, history_ask, history_facts, history_focus, history_patterns_job, history_plan, history_reel,
                   history_recap, history_report, history_since, history_store, labels, progress_sheet, result_media, shown_score, take_ask)
from part7.auth_routes import MSG_CSRF, MSG_SIGN_IN  # one wording for the sign-in and CSRF refusals

MSG_NOT_FOUND = "There is nothing here."
MSG_METHOD = "Method not allowed."
MSG_CONSENT_BODY = "Send video as true or false and a version."
MSG_NO_REPORT = "No comparison has been made yet."
MSG_NO_REEL = "No reel has been made yet."
CLIP_URL = "api/me/history/{entry}/takes/{job}/clip.mp4"


def _user(h: Any) -> str | None:
    auth = history_store.optional_module("part7.auth")
    user = auth.current_user(h) if auth is not None else None
    return user if isinstance(user, str) and history_store.USER_ID_RE.match(user) else None


def _same_origin(h: Any) -> bool:
    auth = history_store.optional_module("part7.auth")
    return bool(auth is not None and auth.origin_ok(h))


def _public_take(entry: str, take: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    """`row` is the take's fact-table row: the group marks the score line is drawn by (TICKET-208)."""
    return {
        "section_key": row.get("section_key"), "mode": row.get("mode"), "score_version": row.get("score_version"),
        "score_scale": row.get("score_scale"), "synthetic": bool(take.get("synthetic")), "in_group": bool(row.get("in_group")), "no_person": bool(row.get("no_person")), "uncapped": row.get("uncapped"),
        "take": take["take"], "job_id": take["job_id"], "at": take["at"], "duration_s": take["duration_s"],
        "score": take["score"], "grade": take["grade"], "shown": row.get("shown"),  # one-letter.md: the result headline's score
        "private": take["private"], "video_kept": take.get("video_kept") is not False,
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
        rows.append({"entry_id": entry, "name": labels.entry_name(h.app.child, entry, h.app.state), "takes": len(found), "synthetic": any(t.get("synthetic") for t in found),
                     "latest": {"take": last["take"], "at": last["at"], "score": last["score"], "grade": last["grade"],
                                "shown": shown_score.of_take(last)}})
    mine = [{"takes": history_all.readable(history_store.takes(state, user, e["entry_id"]))} for e in rows]
    h._json(200, {"entries": rows, "across": len(rows) >= history_all.MIN_ENTRIES,
                  "recap_offer": history_recap.offer(mine, history_recap.utc_now()), "consent": history_store.consent(state, user),
                  "retention": history_store.retention_opt_in(state, user)})


def _empty_entry(h: Any, user: str, entry: str) -> dict[str, Any]:
    """The `_entry` shape for a catalog entry the signed-in user has no takes of."""
    return {
        "entry_id": entry, "name": labels.entry_name(h.app.child, entry, h.app.state), "takes": [], "facts": history_facts.build([], entry),
        "consent": history_store.consent(h.app.state, user), "retention": history_store.retention_opt_in(h.app.state, user),
        "report": "none", "can_compare": False, "patterns": _patterns_runner(h).eligibility(user, entry),
        "attribution": attribution.for_take(h, None, entry, owner=user),  # same shape as a non-empty answer (TICKET-232)
    }


def _entry(h: Any, user: str, entry: str) -> None:
    found = history_store.takes(h.app.state, user, entry)
    if not found:
        if h.app.child.get_entry(entry) is None:  # unknown to the catalog: nothing here
            return h._error(404, MSG_NOT_FOUND)
        return h._json(200, _empty_entry(h, user, entry))  # the caller's own namespace: "no takes yet" is an answer, not an error
    runner = _runner(h)
    hostable, key, _ = runner.plan(user, entry)
    facts = history_facts.build(found, entry)
    h._json(200, {
        "entry_id": entry, "name": labels.entry_name(h.app.child, entry, h.app.state),
        "takes": [_public_take(entry, t, row) for t, row in zip(found, facts["takes"])],
        "facts": facts, "consent": history_store.consent(h.app.state, user),
        "retention": history_store.retention_opt_in(h.app.state, user),
        "report": runner.status(user, entry, key) or ("ready" if history_report.cached(h.app.state, user, entry, key) else "none"),
        "can_compare": len(hostable) >= history_report.MIN_TAKES,
        "patterns": _patterns_runner(h).eligibility(user, entry),
        "attribution": attribution.for_take(h, None, entry, owner=user),
    })


def _accepted(h: Any, state: str) -> None:
    retry = str(history_report.RETRY_AFTER_S)
    body = b'{"status": "%s", "retry_after": %s}' % (state.encode(), retry.encode())
    h._send(202, body, "application/json; charset=utf-8", {"Retry-After": retry})


def _with_line(h: Any, user: str, entry: str, report: Any) -> Any:
    """The report with its author and trainer line, read now from stored facts (never written by the model)."""
    if not isinstance(report, dict):
        return report
    return {**report, "attribution": attribution.for_take(h, None, entry, owner=user)}


def _post_report(h: Any, user: str, entry: str) -> None:
    if not history_store.takes(h.app.state, user, entry):
        return h._error(404, MSG_NOT_FOUND)
    try:
        kind, value = _runner(h).request(user, entry)
    except history_report.Refused as refusal:
        return h._error(refusal.status, refusal.message)
    if kind == "cached":
        return h._json(200, _with_line(h, user, entry, value))
    _accepted(h, value)


def _get_report(h: Any, user: str, entry: str) -> None:
    if not history_store.takes(h.app.state, user, entry):
        return h._error(404, MSG_NOT_FOUND)
    runner = _runner(h)
    _, key, _ = runner.plan(user, entry)
    hit = history_report.cached(h.app.state, user, entry, key)
    if hit is not None:
        return h._json(200, _with_line(h, user, entry, hit))
    running = runner.status(user, entry, key)
    if running:
        return _accepted(h, running)
    h._error(404, MSG_NO_REPORT)


def _patterns_runner(h: Any) -> history_patterns_job.PatternRunner:
    return history_patterns_job.runner_for(h.app.state, h.app.child.catalog_dir)


def _post_patterns(h: Any, user: str, entry: str) -> None:
    """`POST me/history/<entry>/patterns`: the pattern finder (TICKET-221); 200 with a stored result, else 202 and a worker."""
    if not history_store.takes(h.app.state, user, entry):
        return h._error(404, MSG_NOT_FOUND)
    try:
        kind, value = _patterns_runner(h).request(user, entry)
    except history_report.Refused as refusal:
        return h._error(refusal.status, refusal.message)
    if kind == "cached":
        return h._json(200, value)
    _accepted(h, value)


def _get_patterns(h: Any, user: str, entry: str) -> None:
    if not history_store.takes(h.app.state, user, entry):
        return h._error(404, MSG_NOT_FOUND)
    runner = _patterns_runner(h)
    _, _, key, _ = runner.plan(user, entry)
    hit = history_patterns_job.cached(h.app.state, user, entry, key)
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


def _link_clip(entry: str, takes: list[dict[str, Any]], link: dict[str, Any]) -> dict[str, Any]:
    kept = next((t for t in takes if t["job_id"] == link.get("job_id")), None)
    return {**link, "clip": CLIP_URL.format(entry=entry, job=link["job_id"]) if kept and kept["clip"] else None}


def _since_takes(h: Any, user: str, job: str) -> tuple[str, list[dict[str, Any]]] | None:
    """`(entry, the user's takes of it with this job in them)`, or None when the job is not the user's.

    A job whose history copy is not written yet (it is copied on another thread after the job) is added from its folder."""
    state = h.app.state
    for entry in history_store.entries(state, user):
        found = history_store.takes(state, user, entry)
        if any(t["job_id"] == job for t in found):
            return entry, found
    pending = history_store.pending_take(state, user, job)
    if pending is None:
        return None
    rows = sorted([*history_store.takes(state, user, pending["entry_id"]), pending], key=lambda t: (str(t["at"] or ""), t["job_id"]))
    for number, item in enumerate(rows, 1):
        item["take"] = number
    return pending["entry_id"], rows


def _since(h: Any, user: str, job: str) -> None:
    """`GET me/since-last-time/<job>`: the owner's comparison with their previous take; 404 for any other job."""
    got = _since_takes(h, user, job)
    if got is None:
        return h._error(404, MSG_NOT_FOUND)
    if not history_store.retention_opt_in(h.app.state, user):  # keeping takes is off: nothing is compared
        return h._json(200, {"since": None})
    entry, found = got
    doc = history_since.since_last_time(history_facts.build(found, entry), job)
    if doc is not None:
        doc = {**doc, "entry_id": entry, "facts": [{**f, "link": _link_clip(entry, found, f["link"])} for f in doc["facts"]],
               "bests": [{**f, "link": _link_clip(entry, found, f["link"])} for f in doc["bests"]]}
    h._json(200, {"since": doc})


REEL_URL = "api/me/history/{entry}/reel.mp4"


def _public_reel(entry: str, takes: list[dict[str, Any]], doc: dict[str, Any]) -> dict[str, Any]:
    """The stored reel for the page: no server path; every moment links to its take's clip."""
    moments = [{**_link_clip(entry, takes, {"job_id": next((t["job_id"] for t in takes if t["take"] == m["take"]), None)}), **m}
               for m in doc["moments"]]
    return {**{k: v for k, v in doc.items() if k != "moments"}, "moments": moments, "video_url": REEL_URL.format(entry=entry)}


def _post_reel(h: Any, user: str, entry: str) -> None:
    """`POST .../reel`: 200 a finished reel, 202 while it is made, 409 without consent, 422 with fewer than 2 clips."""
    found = history_store.takes(h.app.state, user, entry)
    if not found:
        return h._error(404, MSG_NOT_FOUND)
    try:
        kind, value = history_reel.runner_for(h.app.state).request(user, entry)
    except history_report.Refused as refusal:
        return h._error(refusal.status, refusal.message)
    if kind == "cached":
        return h._json(200, _public_reel(entry, found, value))
    _accepted(h, value)


def _get_reel(h: Any, user: str, entry: str) -> None:
    found = history_store.takes(h.app.state, user, entry)
    if not found:
        return h._error(404, MSG_NOT_FOUND)
    runner = history_reel.runner_for(h.app.state)
    _, key = runner.plan(user, entry)
    hit = history_reel.cached(h.app.state, user, entry, key)
    if hit is not None and history_store.consent(h.app.state, user)["video"]:
        return h._json(200, _public_reel(entry, found, hit))
    running = runner.status(user, entry, key)
    if running:
        return _accepted(h, running)
    failed = runner.failure(user, entry, key)
    if failed:
        return h._json(200, {"format": history_reel.FORMAT, "status": "failed", "reason": failed, "entry_id": entry})
    hit = history_reel.cached(h.app.state, user, entry, key)  # the reel may have finished between the first look and now
    if hit is not None and history_store.consent(h.app.state, user)["video"]:
        return h._json(200, _public_reel(entry, found, hit))
    h._error(404, MSG_NO_REEL)


def _reel_file(h: Any, user: str, entry: str) -> None:
    """`GET .../reel.mp4`: the finished film, only to its owner."""
    if not history_store.takes(h.app.state, user, entry):
        return h._error(404, MSG_NOT_FOUND)
    _, key = history_reel.runner_for(h.app.state).plan(user, entry)
    path = history_reel.file_for(h.app.state, user, entry, key)
    if history_reel.cached(h.app.state, user, entry, key) is None or not history_store.consent(h.app.state, user)["video"]:
        return h._error(404, MSG_NOT_FOUND)
    result_media.serve_file(h, path)


def _ask_info(h: Any, user: str) -> None:
    """`GET me/history/ask`: whether the box can be used, three questions built from the person's own takes."""
    state = h.app.state
    entries = history_ask.gather(state, user, lambda e: labels.entry_name(h.app.child, e, h.app.state))
    takes = sum(len(e["rows"]) for e in entries)
    can = takes >= history_ask.MIN_TAKES and muse_prod.status("ask_history", user, state) is None  # muse-prod.md: never a box that fails
    h._json(200, {"retention": history_store.retention_opt_in(state, user), "takes": takes, "can_ask": can,
                  "suggestions": history_ask.suggestions(entries) if can else [],
                  "max_chars": history_ask.QUESTION_MAX})


def _refused(h: Any, refusal: history_report.Refused) -> None:
    """The plain refusal of an ask route; a `Busy` one adds `Retry-After` and its wait."""
    if isinstance(refusal, history_ask.Busy):
        retry = str(history_ask.RETRY_AFTER_S)
        body = json.dumps({"ok": False, "error": refusal.message, "message": refusal.message, "code": refusal.code, "retry_after": int(retry)}).encode()
        return h._send(refusal.status, body, "application/json; charset=utf-8", {"Retry-After": retry})
    h._error(refusal.status, refusal.message, **({"code": refusal.code} if refusal.code else {}))


def _ask(h: Any, user: str) -> None:
    """`POST me/history/ask {question}`: one grounded answer over the whole history (docs/specs/history-ask.md)."""
    doc = h._body_json()
    if doc is None:
        return
    try:
        out = history_ask.run_question(h.app.state, user, doc.get("question"), lambda e: labels.entry_name(h.app.child, e, h.app.state),
                                       lambda entry, job: CLIP_URL.format(entry=entry, job=job))
    except history_report.Refused as refusal:
        return _refused(h, refusal)
    h._json(200, out)


def _take_entry(h: Any, user: str, job: str) -> dict[str, Any] | None:
    """The one-take movement of `job` when it is the caller's own take, else None (a stranger's job and a missing one look alike)."""
    got = _since_takes(h, user, job)
    mine = next((t for t in got[1] if t["job_id"] == job), None) if got else None
    if got is None or mine is None:
        return None
    return take_ask.entry_of(got[0], labels.entry_name(h.app.child, got[0], h.app.state), mine)


def _ask_take(h: Any, user: str, job: str, method: str) -> None:
    """`GET|POST me/history/ask-take/<job>`: whether the box can be used, and one cited answer about this take (docs/specs/take-ask.md)."""
    entry = _take_entry(h, user, job)
    if entry is None:
        return h._error(404, take_ask.MSG_NOT_FOUND, code="not_found")
    state = h.app.state
    if method != "POST":
        kept = history_store.retention_opt_in(state, user)
        can = (kept and not entry["takes"][0]["private"] and take_ask.available()  # a pin without `part5 ask` shows no box
               and muse_prod.status("ask_take", user, state) is None)  # muse-prod.md: nor a closed feature
        return h._json(200, {"retention": kept, "can_ask": can, "suggestions": take_ask.suggestions(entry) if can else [], "max_chars": history_ask.QUESTION_MAX})
    doc = h._body_json()
    if doc is None:
        return
    try:
        out = take_ask.run_question(state, user, job, entry, doc.get("question"))
    except history_report.Refused as refusal:
        return _refused(h, refusal)
    h._json(200, out)


def _plan(h: Any, user: str, entry: str) -> None:
    """`GET <entry>/plan[?job=<job>]`: the next-session plan from the owner's readable takes (a just-finished `job` is included)."""
    found = history_store.takes(h.app.state, user, entry)
    job = parse_qs(urlsplit(h.path).query).get("job", [""])[0]
    if job and history_store.JOB_ID_RE.match(job) and not any(t["job_id"] == job for t in found):
        got = _since_takes(h, user, job)
        found = got[1] if got and got[0] == entry else found
    if not found:
        return h._error(404, MSG_NOT_FOUND)
    plan = None
    if history_store.retention_opt_in(h.app.state, user):
        plan = history_plan.build(history_facts.build(history_report.hostable(found), entry), _words())
    h._json(200, {"plan": plan})


def _focus(h: Any, user: str, entry: str) -> None:
    """`GET <entry>/focus[?job=<job>]`: what the owner worked on last time (TICKET-223 AC-1) and, with a just-finished `job`
    of this movement, what that take says about it (AC-2). Readable takes only (never private, never rehab); nothing without
    the keeping consent. A catalog movement with no takes of the caller's is an empty answer, not an error."""
    state = h.app.state
    found = history_store.takes(state, user, entry)
    job = parse_qs(urlsplit(h.path).query).get("job", [""])[0]
    if job and history_store.JOB_ID_RE.match(job) and not any(t["job_id"] == job for t in found):
        got = _since_takes(h, user, job)
        found = got[1] if got and got[0] == entry else found
    if not found and h.app.child.get_entry(entry) is None:
        return h._error(404, MSG_NOT_FOUND)
    if not found or not history_store.retention_opt_in(state, user):
        return h._json(200, {"focus": None, "after": None})
    readable = history_all.readable(found)
    mine = next((t for t in readable if t["job_id"] == job), None) if job else None
    before = [t for t in readable if mine is None or t["take"] < mine["take"]]
    report = None
    if mine is None and before:
        _, key, _ = _runner(h).plan(user, entry)
        report = history_report.cached(state, user, entry, key)
    seen = history_focus.focus(history_facts.build(before, entry), report) if before else None
    done = history_focus.after(history_facts.build(readable[:readable.index(mine) + 1], entry), seen, job) if seen and mine else None
    h._json(200, {"focus": seen, "after": done})


def _words() -> Any:
    guard = history_store.optional_module("part7.history_guard")
    return guard.load_words() if guard is not None else None


def _consent(h: Any, user: str) -> None:
    doc = h._body_json()
    if doc is None:
        return
    try:
        out = history_store.set_consent(h.app.state, user, doc.get("video"), doc.get("version"), doc.get("meta_adults"))
    except ValueError:
        return h._error(400, MSG_CONSENT_BODY)
    h._json(200, out)


def _forget(h: Any, user: str, entry: str | None) -> None:
    removed = history_store.forget(h.app.state, user, entry)
    auth = history_store.optional_module("part7.auth")
    store = getattr(auth, "identity", None)
    if callable(store):  # TICKET-283: a progress sheet read these takes, so its links and stored copies go with them
        progress_sheet.drop_shares(store(h.app), user, entry)
    h._json(200, {"removed": removed})


def handle(h: Any, method: str, route: str) -> bool:
    """Answer `route` (below `api/`) when it is a history route; False when it is not."""
    parts = route.split("/")
    since = parts[:2] == ["me", "since-last-time"] and len(parts) == 3
    if not since and (parts[:2] != ["me", "history"] or len(parts) > 6):
        return False
    user = _user(h)
    if user is None:
        h._error(401, MSG_SIGN_IN)
        return True
    if since:
        if method not in ("GET", "HEAD"):
            h._error(405, MSG_METHOD)
        elif history_store.JOB_ID_RE.match(parts[2]):
            _since(h, user, parts[2])
        else:
            h._error(404, MSG_NOT_FOUND)
        return True
    read, rest = method in ("GET", "HEAD"), parts[2:]
    if method in ("POST", "DELETE") and not _same_origin(h):  # CSRF, as auth_routes: JSON content type and a same-origin Origin
        h._error(403, MSG_CSRF, code="forbidden_origin")
        return True
    entry = rest[0] if rest else None
    if history_all_routes.handle(h, method, rest, user):  # all, cross reports and recap (TICKET-223/224)
        return True
    if entry == "ask" and len(rest) == 1:  # a fixed word, not a movement (an entry id of "ask" is not served here)
        _ask(h, user) if method == "POST" else _ask_info(h, user) if read else h._error(405, MSG_METHOD)
    elif entry == "ask-take" and len(rest) == 2 and history_store.JOB_ID_RE.match(rest[1]):  # one take of the caller's (TICKET-269)
        _ask_take(h, user, rest[1], method) if method == "POST" or read else h._error(405, MSG_METHOD)
    elif entry == "consent" and len(rest) == 1:
        _consent(h, user) if method == "POST" else h._error(405, MSG_METHOD)
    elif entry is not None and not labels.ENTRY_ID_RE.match(entry):
        h._error(404, MSG_NOT_FOUND)
    elif not rest and read:
        _list(h, user)
    elif len(rest) <= 1 and method == "DELETE":
        _forget(h, user, entry)
    elif len(rest) == 1 and read:
        _entry(h, user, entry)
    elif rest[1:] == ["plan"] and read:
        _plan(h, user, entry)
    elif rest[1:] == ["focus"] and read:
        _focus(h, user, entry)
    elif rest[1:] == ["report"] and method == "POST":
        _post_report(h, user, entry)
    elif rest[1:] == ["report"] and read:
        _get_report(h, user, entry)
    elif rest[1:] == ["patterns"] and method == "POST":
        _post_patterns(h, user, entry)
    elif rest[1:] == ["patterns"] and read:
        _get_patterns(h, user, entry)
    elif rest[1:] == ["reel"] and method == "POST":
        _post_reel(h, user, entry)
    elif rest[1:] == ["reel"] and read:
        _get_reel(h, user, entry)
    elif rest[1:] == ["reel.mp4"] and read:
        _reel_file(h, user, entry)
    elif len(rest) == 4 and rest[1] == "takes" and rest[3] == "clip.mp4" and read:
        _clip(h, user, entry, rest[2]) if history_store.JOB_ID_RE.match(rest[2]) else h._error(404, MSG_NOT_FOUND)
    else:
        known = not rest or rest[1:2] in (["report"], ["patterns"], ["takes"], ["reel"], ["reel.mp4"], ["plan"], ["focus"])
        h._error(405 if known else 404, MSG_METHOD if known else MSG_NOT_FOUND)
    return True
