"""Reverse proxy of `<base>catalog/**` to the Part 6 child server (`part7/proxy.py`).

Only GET and HEAD pass (APP-H2): every other method answers 405 here and never reaches Part 6, so its create and
import routes are not public. Headers except hop-by-hop, status, `Range` and 206 pass through; the body streams in
chunks so a trainer video is never held in memory.

A movement the caller may not see (`auth.may_view_entry`: unpublished, or "only me" and not theirs) is 404 on
`api/entries/<id>`, its files and `api/jobs/<id>`, and is left out of the `api/entries` list (the list, a small
JSON document, is read whole for that).

Two guards for what Part 6 might do with a path (go-live-readiness.md "Redirects" and "File paths"; HARDENING 2.9,
3.7): a path whose segments, decoded up to three times, hold `..`, `.`, an empty inner segment (`//`, an absolute
path), a backslash or a NUL is 404 here and never reaches Part 6; an answer whose `Location` is not a relative path
on this origin (`unsafe_location`) is 404 with nothing relayed, and a `Refresh` header is never relayed.
"""

from __future__ import annotations

import http.client
from http.server import BaseHTTPRequestHandler
import json
from typing import Any, Callable
from urllib.parse import unquote, urlsplit

HOP_BY_HOP = frozenset(
    {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailers",
     "transfer-encoding", "upgrade", "proxy-connection"}
)
CHUNK = 65536
UPSTREAM_TIMEOUT_S = 60.0
LIST_MAX = 8 << 20  # the entries list read whole to filter it
METHODS = ("GET", "HEAD")
DECODE_ROUNDS = 3  # %2e, %252e and %25252e are each one round
NOT_RELAYED = frozenset({"refresh"})  # a timed redirect the Location check would not see
LIST = "list"
Visible = Callable[[str], bool]


def _answer(handler: BaseHTTPRequestHandler, status: int, message: str, head_only: bool,
            extra: dict[str, str] | None = None) -> None:
    body = json.dumps({"ok": False, "error": message}).encode()
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    for key, value in (extra or {}).items():
        handler.send_header(key, value)
    handler.end_headers()
    if not head_only:
        handler.wfile.write(body)


def _unavailable(handler: BaseHTTPRequestHandler, head_only: bool) -> None:
    _answer(handler, 503, "The catalog is not answering. Try again in a moment.", head_only)


def scope(target: str, base: str) -> tuple[str, str | None] | None:
    """What a catalog path names: `("list", None)` for `api/entries`, `("entry", id)` for an entry, its files or its
    Part 6 job, None for anything else (the catalog page's own static files)."""
    path = urlsplit(target).path
    prefix = base.rstrip("/") + "/catalog/"
    if not path.startswith(prefix):
        return None
    segments = [unquote(s) for s in path[len(prefix):].split("/")]
    if segments[:1] != ["api"] or len(segments) < 2 or segments[1] not in ("entries", "jobs"):
        return None
    if segments[1] == "entries" and segments[2:] in ([], [""]):
        return (LIST, None)
    return ("entry", segments[2]) if len(segments) > 2 and segments[2] else None


def unsafe_path(target: str) -> bool:
    """True when the path of `target`, as sent or decoded up to `DECODE_ROUNDS` times, could leave a file root:
    a `..` or `.` segment, an empty segment before the last (`//`, an absolute path), a backslash, a NUL, or an
    escape that is not UTF-8."""
    text = urlsplit(target).path
    for _ in range(DECODE_ROUNDS + 1):
        segments = text.split("/")
        if any(s in ("..", ".") for s in segments) or "" in segments[1:-1] or "\\" in text or "\x00" in text:
            return True
        try:
            decoded = unquote(text, errors="strict")
        except UnicodeDecodeError:  # an overlong or broken escape (`%c0%ae`): a decoder may read it as a dot
            return True
        if decoded == text:
            return False
        text = decoded
    return True  # still encoded after every round: not a path a page asks for


def unsafe_location(value: str) -> bool:
    """True unless `value` is a relative reference on this origin: no scheme, no host, no `//` start, no backslash
    and no control character (a browser reads `/\\host` and `///host` as another host)."""
    text = value.strip()
    if not text or "\\" in text or any(ord(c) < 0x20 or ord(c) == 0x7F for c in text):
        return True
    parts = urlsplit(text)
    return bool(parts.scheme or parts.netloc or text.startswith("//"))


def _default_visible(handler: Any) -> Visible | None:
    app = getattr(handler, "app", None)
    if app is None:
        return None
    from part7 import auth  # the app's one rule for who sees a movement

    minors: dict[str, bool] = {}  # this request's account marks, one identity read per owner (review R5)
    return lambda entry_id: auth.may_view_entry(handler, entry_id, minors)


def forward(handler: BaseHTTPRequestHandler, host: str, port: int, target: str, visible: Visible | None = None) -> int:
    """Send the GET or HEAD in `handler` to `host:port` at `target` and relay the answer; return the status.

    `visible(entry_id)` (default: `auth.may_view_entry` of the handler's app) hides movements the caller may not see."""
    method = handler.command
    head_only = method == "HEAD"
    if method not in METHODS:
        handler.close_connection = True  # the unread body must not be taken for the next request
        _answer(handler, 405, "Method not allowed.", False, {"Allow": ", ".join(METHODS), "Connection": "close"})
        return 405
    if unsafe_path(target):  # go-live-readiness.md "File paths": Part 6 never sees a path that could leave its root
        _answer(handler, 404, "not found", head_only)
        return 404
    visible = visible or _default_visible(handler)
    base = getattr(getattr(handler, "app", None), "base", "/")
    found = scope(target, base) if visible is not None else None
    if found is not None and found[0] != LIST and not visible(str(found[1])):
        _answer(handler, 404, "not found", head_only)
        return 404
    headers = {k: v for k, v in handler.headers.items() if k.lower() not in HOP_BY_HOP | {"host"}}
    headers["Host"] = f"{host}:{port}"
    headers["Connection"] = "close"
    listing = found is not None and found[0] == LIST
    if listing:
        headers.pop("Range", None)
        headers["Accept-Encoding"] = "identity"
    conn = http.client.HTTPConnection(host, port, timeout=UPSTREAM_TIMEOUT_S)
    try:
        conn.request("GET" if listing else method, target, headers=headers)  # a HEAD of the list is filtered too
        resp = conn.getresponse()
    except (OSError, http.client.HTTPException):
        conn.close()
        _unavailable(handler, head_only)
        return 503
    try:
        if listing and resp.status == 200 and visible is not None:
            return _relay_list(handler, resp, visible, head_only)
        _relay(handler, resp, head_only)
    finally:
        conn.close()
    handler.close_connection = True
    return resp.status


def _relay(handler: BaseHTTPRequestHandler, resp: http.client.HTTPResponse, head_only: bool) -> None:
    if any(k.lower() == "location" and unsafe_location(v) for k, v in resp.getheaders()):
        _answer(handler, 404, "not found", head_only)  # go-live-readiness.md "Redirects": never off this origin
        return
    try:
        handler.send_response(resp.status)
        for key, value in resp.getheaders():
            if key.lower() not in HOP_BY_HOP | NOT_RELAYED | {"server", "date"}:
                handler.send_header(key, value)
        handler.send_header("Connection", "close")
        handler.end_headers()
        if not head_only and resp.status not in (204, 304):
            while True:
                chunk = resp.read(CHUNK)
                if not chunk:
                    break
                handler.wfile.write(chunk)
    except (BrokenPipeError, ConnectionResetError, http.client.HTTPException, OSError):
        pass  # the browser left mid-video, or the child stopped mid-body


def filter_list(raw: bytes, visible: Visible) -> bytes | None:
    """The Part 6 list document without the entries `visible` refuses; None when it is not a list document."""
    try:
        doc = json.loads(raw)
    except ValueError:
        return None
    entries = doc.get("entries") if isinstance(doc, dict) else None
    if not isinstance(entries, list):
        return None
    doc["entries"] = [e for e in entries if isinstance(e, dict) and isinstance(e.get("id"), str) and visible(e["id"])]
    return json.dumps(doc).encode("utf-8")


def _relay_list(handler: BaseHTTPRequestHandler, resp: http.client.HTTPResponse, visible: Visible, head_only: bool) -> int:
    handler.close_connection = True
    try:
        raw = resp.read(LIST_MAX + 1)
    except (http.client.HTTPException, OSError):
        _unavailable(handler, head_only)
        return 503
    body = filter_list(raw, visible) if len(raw) <= LIST_MAX else None
    if body is None:  # an answer that cannot be filtered is not relayed (fails closed)
        _unavailable(handler, head_only)
        return 503
    try:
        handler.send_response(200)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(body)))
        handler.send_header("Cache-Control", "no-store")
        handler.send_header("Connection", "close")
        handler.end_headers()
        if not head_only:
            handler.wfile.write(body)
    except (BrokenPipeError, ConnectionResetError, OSError):
        pass
    return 200
