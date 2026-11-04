"""`POST api/client-log`: the browser's own events in Part 7's log (app.md "Client log", TICKET-064).

Body `{"level": "info"|"warn"|"error", "event": "<1..64 chars>", "detail": {...}, "page": "<string>"}`.
Answers 200 `{"ok": true}` when written, 400 for a bad body, 413 when the body or `detail` is over 4 KB, 429 past 60 events a
minute from one client. The line is `client <level> <event> page=<page> <detail json>`, redacted by `applog`.
With Global Privacy Control (`Sec-GPC: 1`, part7/gpc.py) only the error report `client_error` is written; a usage
event is answered the same 200 and kept nowhere (go-live-readiness.md "GPC").
"""

from __future__ import annotations

from collections import deque
import json
import logging
import re
import secrets
import threading
import time
from typing import Any

from part7 import applog, gpc, quota, selfheal
from part7.http_body import drain_before_refusal

DETAIL_MAX = 4096  # bytes of `detail` as compact JSON
BODY_MAX = DETAIL_MAX + 1024  # the envelope around it
EVENT_MAX = 64
ERROR_EVENT = "client_error"  # web/errors.js sends it; the server logs it as `ANOMALY client_error` (observability.md)
PAGE_MAX = 200
RATE_LIMIT = 60
RATE_WINDOW_S = 60.0
RATE_MAX_KEYS = 10_000  # clients tracked at once; past it the least recently seen client is forgotten
LEVELS = {"info": logging.INFO, "warn": logging.WARNING, "error": logging.ERROR}
# C0 and C1 controls plus U+2028 and U+2029: `str.splitlines` and many log viewers break a line on U+0085,
# U+2028 and U+2029, so they could forge a second log line like a newline. A lone surrogate (JSON allows
# `\ud800`) cannot be written as UTF-8. In `event` these are refused, in `page` they become spaces.
_CONTROL = re.compile("[\x00-\x1f\x7f-\x9f\u2028\u2029\ud800-\udfff]")
# What json.dumps(ensure_ascii=False) leaves raw inside a string and the log line must not carry raw.
_JSON_ESCAPE = re.compile("[\x7f-\x9f\u2028\u2029\ud800-\udfff]")
# TICKET-174: a route with arguments (`#/result/<job>`, `#/signin/<token>`) keeps its name only, so an old cached
# client cannot put a job id or a sign-in token in the log. In `detail` (JSON text) a quote ends the argument.
_ROUTE_ARGS = re.compile(r'(#/[A-Za-z0-9_-]+)/[^\s"\\]+')
_SERVER_RID = re.compile(r"[0-9a-f]{12}")
MSG_BAD = "The log event needs level info, warn or error, an event name of 64 characters at most, a detail object and a page."
MSG_LARGE = "The log event is too large (4 KB at most)."
MSG_RATE = "Too many log events. Try again in a minute."


class RateLimit:
    """At most `limit` events per `window_s` seconds per client key (sliding window, thread safe)."""

    def __init__(self, limit: int = RATE_LIMIT, window_s: float = RATE_WINDOW_S, max_keys: int = RATE_MAX_KEYS) -> None:
        self.limit, self.window_s, self.max_keys = limit, window_s, max_keys
        self._seen: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, now: float | None = None) -> bool:
        """Count one event for `key`; False when that would pass the limit (the event is not counted)."""
        now = time.monotonic() if now is None else now
        with self._lock:
            for other in [k for k, q in self._seen.items() if q and q[-1] <= now - self.window_s]:
                del self._seen[other]  # idle clients are forgotten
            times = self._seen.pop(key, None) or deque()
            self._seen[key] = times  # most recently seen last
            while len(self._seen) > self.max_keys:
                del self._seen[next(iter(self._seen))]  # the least recently seen client
            while times and times[0] <= now - self.window_s:
                times.popleft()
            if len(times) >= self.limit:
                return False
            times.append(now)
            return True


def parse(raw: bytes) -> tuple[int, dict[str, Any] | str]:
    """`(200, event)` for a valid body, else `(400 or 413, message)`."""
    if len(raw) > BODY_MAX:
        return (413, MSG_LARGE)
    try:
        doc = json.loads(raw or b"null")
    except ValueError:
        return (400, MSG_BAD)
    if not isinstance(doc, dict):
        return (400, MSG_BAD)
    level, event, detail, page = doc.get("level"), doc.get("event"), doc.get("detail", {}), doc.get("page")
    if level not in LEVELS or not isinstance(event, str) or not 1 <= len(event) <= EVENT_MAX or _CONTROL.search(event):
        return (400, MSG_BAD)
    if not isinstance(detail, dict) or not isinstance(page, str):
        return (400, MSG_BAD)
    text = json.dumps(detail, separators=(",", ":"), ensure_ascii=False, sort_keys=True)
    if len(text.encode("utf-8", "surrogatepass")) > DETAIL_MAX:
        return (413, MSG_LARGE)
    text = _ROUTE_ARGS.sub(r"\1", text)
    text = _JSON_ESCAPE.sub(lambda m: f"\\u{ord(m.group()):04x}", text)  # the same JSON, on one line, writable
    return (200, {"level": level, "event": event, "detail": text, "page": _ROUTE_ARGS.sub(r"\1", _CONTROL.sub(" ", page))[:PAGE_MAX]})


def error_fields(event: dict[str, Any]) -> dict[str, Any]:
    """The `ANOMALY client_error` fields of a `client_error` event: page, source and the cut detail fields."""
    try:
        detail = json.loads(event["detail"])
    except ValueError:
        detail = {}
    detail = detail if isinstance(detail, dict) else {}
    out: dict[str, Any] = {"page": event["page"] or "-"}
    for key in ("source", "status", "path", "file", "line", "col", "count"):
        if isinstance(detail.get(key), (str, int)) and not isinstance(detail.get(key), bool):
            out[key] = detail[key]
    if isinstance(out.get("path"), str):
        out["path"] = applog.safe_path(out["path"])
        out["route"] = selfheal.route_key("GET", out["path"])
    if isinstance(detail.get("rid"), str) and _SERVER_RID.fullmatch(detail["rid"]):
        out["server_rid"] = detail["rid"]  # the X-Request-Id of the answer the browser complains about
    return {**out, "detail": str(detail.get("message", ""))[:300]}


def line(event: dict[str, Any]) -> str:
    """The log line of a parsed event (one line: control characters are already gone)."""
    return f"client {event['level']} {event['event']} page={event['page'] or '-'} {event['detail']}"


def handle(h: Any, limiter: RateLimit) -> None:
    """Answer `POST api/client-log` on handler `h` (server.py `_Handler`)."""
    try:
        length = int(h.headers.get("Content-Length") or 0)
    except ValueError:
        return h._error(400, MSG_BAD)
    if length > BODY_MAX:
        drain_before_refusal(h, length)  # TICKET-194: the 413 arrives instead of a connection reset
        return h._error(413, MSG_LARGE)
    status, parsed = parse(h.rfile.read(length) if length > 0 else b"")
    if status != 200 or not isinstance(parsed, dict):
        return h._error(status, str(parsed))
    key = quota.client_of(h._visitor() or (h.client_address[0] if h.client_address else "unknown"))  # R12: an IPv6 /64
    if not limiter.allow(key):
        return h._error(429, MSG_RATE)
    if parsed["event"] == ERROR_EVENT:
        applog.anomaly("client_error", **error_fields(parsed), rid=secrets.token_hex(6))
    elif gpc.signal(h.headers):
        pass  # GPC: a usage event is optional analytics, so it is not kept (go-live-readiness.md "GPC")
    else:
        rid = f" rid={secrets.token_hex(6)}" if parsed["level"] == "error" else ""
        applog.log(line(parsed) + rid, level=LEVELS[parsed["level"]])
    body = b'{"ok": true}'  # 200 with a body: Chromium logs a 204 fetch as net::ERR_ABORTED in the console
    h.send_response(200)
    h.send_header("Cache-Control", "no-store")
    h.send_header("Content-Type", "application/json")
    h.send_header("Content-Length", str(len(body)))
    h.end_headers()
    h.wfile.write(body)
