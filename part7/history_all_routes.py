"""Routes of "across my movements" and the monthly recap, below `api/me/history/` (docs/specs/history-all.md, TICKET-224).

    GET  all                  the movements a cross report reads and the table of measures across them (422 with fewer than 2 movements)
    POST all/prefs            {left_out: [movement ids]} leave movements out; voids the cross reports
    POST all/report           the optional text-only model call (200 cached, 202 running, 409, 422, 429); GET reads it (200, 202, 404)
    GET  recap[?month=YYYY-MM] the month's recap (UTC); POST recap/report makes its model part

`history_routes.handle` calls `handle` after its own sign-in and same-origin checks, so every route here is the signed-in
owner's only and reads only that person's own folder.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlsplit

from part7 import history_all, history_cross, history_recap, history_report, history_store, labels

MSG_NOT_FOUND = "There is nothing here."
MSG_METHOD = "Method not allowed."
MSG_PREFS = "Send left_out as a list of movement ids."
MSG_MONTH = "Send the month as YYYY-MM."
MSG_FEW = history_cross.MSG_FEW_MOVEMENTS
DISCLOSURE = ("Sent to Meta's model: the measurements and cues of the takes of the movements listed here. "
              "No video is sent. Take a movement out of the list to leave it out.")


def _runner(h: Any) -> history_cross.Runner:
    return history_cross.runner_for(h.app.state, h.app.child)


def _name_of(h: Any):
    return lambda entry: labels.entry_name(h.app.child, entry, h.app.state)


def _state_word(runner: history_cross.Runner, user: str, kind: str, key: str, month: str | None, state: Any) -> str:
    return runner.status(user, kind, key) or ("ready" if history_cross.cached(state, user, kind, key, month) else "none")


def _all(h: Any, user: str) -> None:
    state = h.app.state
    entries = history_all.gather(state, user, _name_of(h))
    if len(entries) < history_all.MIN_ENTRIES:
        return h._error(422, MSG_FEW)
    read = history_all.included(entries)
    runner = _runner(h)
    _, key = runner.plan(user, "all", None)
    why = history_all.blocker(read)
    h._json(200, {
        "format": "simon.history.all.table.v1", "entries": [history_all.public_entry(e) for e in entries],
        "table": history_all.cross_table(read), "can_read": why is None, "blocked": why,
        "report": _state_word(runner, user, "all", key, None, state), "disclosure": DISCLOSURE,
    })


def _prefs(h: Any, user: str) -> None:
    doc = h._body_json()
    if doc is None:
        return
    mine = set(history_store.entries(h.app.state, user))
    try:
        listed = doc.get("left_out") if isinstance(doc, dict) else None
        history_all.set_left_out(h.app.state, user, [e for e in listed if e in mine] if isinstance(listed, list) else listed)
    except ValueError:
        return h._error(400, MSG_PREFS)
    _all(h, user)


def _accepted(h: Any, state: str) -> None:
    retry = str(history_report.RETRY_AFTER_S)
    h._send(202, b'{"status": "%s", "retry_after": %s}' % (state.encode(), retry.encode()), "application/json; charset=utf-8", {"Retry-After": retry})


def _post_report(h: Any, user: str, kind: str, month: str | None) -> None:
    try:
        verdict, value = _runner(h).request(user, kind, month)
    except history_report.Refused as refusal:
        return h._error(refusal.status, refusal.message)
    if verdict == "cached":
        return h._json(200, value)
    _accepted(h, value)


def _get_report(h: Any, user: str, kind: str, month: str | None) -> None:
    runner = _runner(h)
    _, key = runner.plan(user, kind, month)
    hit = history_cross.cached(h.app.state, user, kind, key, month)
    if hit is not None:
        return h._json(200, hit)
    running = runner.status(user, kind, key)
    if running:
        return _accepted(h, running)
    h._error(404, "No comparison has been made yet.")


def _month(h: Any, entries: list[dict[str, Any]]) -> str | None:
    asked = parse_qs(urlsplit(h.path).query).get("month")
    if not asked:
        return history_recap.default_month(entries, history_recap.utc_now())
    return asked[0] if history_recap.valid_month(asked[0]) else None


def _recap(h: Any, user: str) -> None:
    state = h.app.state
    entries = history_all.gather(state, user, _name_of(h))
    month = _month(h, entries)
    if month is None:
        return h._error(400, MSG_MONTH)
    recap = history_recap.build(entries, month)
    runner = _runner(h)
    _, key = runner.plan(user, "recap", month)
    model = history_cross.cached(state, user, "recap", key, month)
    hidden = recap["takes"] < history_cross.MIN_RECAP_TAKES
    word = "hidden" if hidden else (runner.status(user, "recap", key) or ("ready" if model else "none"))
    if model and model.get("next_focus"):
        recap = {**recap, "next_focus": {**model["next_focus"], "source": "model"}}
    h._json(200, {"recap": recap, "model": model, "model_state": word, "disclosure": DISCLOSURE,
                  "offer": history_recap.offer(entries, history_recap.utc_now())})


def _month_for_report(h: Any, user: str) -> str | None:
    entries = history_all.gather(h.app.state, user, _name_of(h))
    return _month(h, entries)


def handle(h: Any, method: str, rest: list[str], user: str) -> bool:
    """Answer `rest` (the route below `me/history/`) when it is an all or recap route; False when it is not."""
    if not rest or rest[0] not in ("all", "recap") or len(rest) > 2:
        return False
    read = method in ("GET", "HEAD")
    area, tail = rest[0], rest[1:]
    if area == "all" and not tail and read:
        _all(h, user)
    elif area == "all" and tail == ["prefs"] and method == "POST":
        _prefs(h, user)
    elif area == "all" and tail == ["report"] and method == "POST":
        _post_report(h, user, "all", None)
    elif area == "all" and tail == ["report"] and read:
        _get_report(h, user, "all", None)
    elif area == "recap" and not tail and read:
        _recap(h, user)
    elif area == "recap" and tail == ["report"] and (method == "POST" or read):
        month = _month_for_report(h, user)
        if month is None:
            h._error(400, MSG_MONTH)
        elif method == "POST":
            _post_report(h, user, "recap", month)
        else:
            _get_report(h, user, "recap", month)
    else:
        known = not tail or tail in (["prefs"], ["report"])
        h._error(405 if known else 404, MSG_METHOD if known else MSG_NOT_FOUND)
    return True
