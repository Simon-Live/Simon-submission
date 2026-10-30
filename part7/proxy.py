"""Reverse proxy of `<base>catalog/**` to the Part 6 child server (`part7/proxy.py`).

Method, headers except hop-by-hop, body, status, `Range` and 206 pass through; the body streams in
chunks so a trainer video is never held in memory.
"""

from __future__ import annotations

import http.client
from http.server import BaseHTTPRequestHandler
import json

HOP_BY_HOP = frozenset(
    {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailers",
     "transfer-encoding", "upgrade", "proxy-connection"}
)
CHUNK = 65536
UPSTREAM_TIMEOUT_S = 60.0
MAX_BODY = 24 << 20  # Part 6's own import limit (MAX_IMPORT_BODY)


def _unavailable(handler: BaseHTTPRequestHandler, head_only: bool) -> None:
    body = json.dumps({"ok": False, "error": "The catalog is not answering. Try again in a moment."}).encode()
    handler.send_response(503)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    if not head_only:
        handler.wfile.write(body)


def forward(handler: BaseHTTPRequestHandler, host: str, port: int, target: str) -> int:
    """Send the request in `handler` to `host:port` at `target` and relay the answer; return the status."""
    method = handler.command
    length = int(handler.headers.get("Content-Length") or 0)
    if length > MAX_BODY:
        handler.send_error(413)
        return 413
    body = handler.rfile.read(length) if length else None
    headers = {k: v for k, v in handler.headers.items() if k.lower() not in HOP_BY_HOP | {"host"}}
    headers["Host"] = f"{host}:{port}"
    headers["Connection"] = "close"
    conn = http.client.HTTPConnection(host, port, timeout=UPSTREAM_TIMEOUT_S)
    try:
        conn.request(method, target, body=body, headers=headers)
        resp = conn.getresponse()
    except (OSError, http.client.HTTPException):
        conn.close()
        _unavailable(handler, method == "HEAD")
        return 503
    try:
        handler.send_response(resp.status)
        for key, value in resp.getheaders():
            if key.lower() not in HOP_BY_HOP | {"server", "date"}:
                handler.send_header(key, value)
        handler.send_header("Connection", "close")
        handler.end_headers()
        if method != "HEAD" and resp.status not in (204, 304):
            while True:
                chunk = resp.read(CHUNK)
                if not chunk:
                    break
                handler.wfile.write(chunk)
    except (BrokenPipeError, ConnectionResetError, http.client.HTTPException, OSError):
        pass  # the browser left mid-video, or the child stopped mid-body
    finally:
        conn.close()
    handler.close_connection = True
    return resp.status
