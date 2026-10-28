"""HTTP server: static `web/`, the catalog API and entry files, under SIMON6_BASE_PATH.

Stdlib only. `ThreadingHTTPServer` with daemon threads, so a browser's parallel requests never
block each other and the process exits at once on SIGTERM. Requests are logged to stderr. Error
bodies are JSON `{"error": "<field or reason>"}`.
"""
from __future__ import annotations

import json
import os
import signal
import sys
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from . import catalog
from .catalog import REPO_ROOT
from .motion import CATEGORIES
from .validate import clean_create_request

MAX_BODY = 4096
DRAIN_LIMIT = 1 << 20
CHUNK = 1 << 16
TYPES = {
    ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml", ".json": "application/json",
    ".webm": "video/webm", ".mp4": "video/mp4",
}
FALLBACK_TYPE = "application/octet-stream"
# Entry files are data: never a page or script on the app origin.
ENTRY_TYPES = {ext: TYPES[ext] for ext in (".svg", ".json", ".webm", ".mp4")}


def normalize_base(value):
    """'/simon/' -> '/simon'; '' and '/' -> ''."""
    value = (value or "/").strip()
    return "/" + value.strip("/") if value.strip("/") else ""


def parse_range(header, size):
    """(start, end) inclusive for one satisfiable `bytes=a-b` range, else None (send it all)."""
    if not header or not header.startswith("bytes=") or "," in header or size <= 0:
        return None
    first, _, last = header[6:].strip().partition("-")
    try:
        if first == "":
            n = int(last)
            if n <= 0:
                return None
            start, end = max(size - n, 0), size - 1
        else:
            start = int(first)
            end = min(int(last), size - 1) if last else size - 1
    except ValueError:
        return None
    return (start, end) if 0 <= start <= end < size else None


class CatalogServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, root, base_path, web_root, max_recordings):
        super().__init__(address, Handler)
        self.root = Path(root)
        self.base_path = base_path
        self.web_root = Path(web_root).resolve()
        self.max_recordings = max_recordings
        self.save_lock = threading.Lock()    # one save at a time, so the cap cannot overshoot


class Handler(BaseHTTPRequestHandler):
    server_version = "Simon6"
    protocol_version = "HTTP/1.1"
    timeout = 30
    _headers_sent = False

    def do_GET(self):
        self._handle("GET")

    def do_HEAD(self):
        self._handle("HEAD")

    def do_POST(self):
        self._handle("POST")

    def do_PUT(self):
        self._handle("PUT")

    do_DELETE = do_PATCH = do_OPTIONS = do_PUT

    def _handle(self, method):
        self._headers_sent = False
        if method not in ("GET", "HEAD"):
            self.close_connection = True    # a body we do not read must not become a request
        try:
            self._route(method)
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True
        except Exception:
            traceback.print_exc(file=sys.stderr)
            if self._headers_sent:
                self.close_connection = True    # a second response would corrupt this one
            else:
                self._error(500, "internal error")

    # Routing

    def _route(self, method):
        parts = urlsplit(self.path)
        rest = self._strip_base(parts.path)
        if rest is None:
            return self._error(404, "not found")
        if rest == "":
            return self._redirect(self.server.base_path + "/")
        segments = [unquote(s) for s in rest.split("/")[1:]]
        if segments[0] == "api":
            return self._api(method, segments[1:], parse_qs(parts.query, keep_blank_values=True))
        if method not in ("GET", "HEAD"):
            return self._error(405, "method not allowed")
        self._static(segments)

    def _strip_base(self, path):
        base = self.server.base_path
        if not base:
            return path if path.startswith("/") else None
        if path == base:
            return ""
        return path[len(base):] if path.startswith(base + "/") else None

    def _api(self, method, segments, query):
        root = self.server.root
        known = {("health",): ("GET", "HEAD"), ("entries",): ("GET", "HEAD", "POST")}
        allowed = known.get(tuple(segments)) or (
            ("GET", "HEAD") if segments[:1] == ["entries"] and len(segments) in (2, 3) else None)
        if allowed is None:
            return self._error(404, "not found")
        if method not in allowed:
            return self._error(405, "method not allowed")
        if segments == ["health"]:
            return self._json(200, {"ok": True, "entries": len(catalog.list_entries(root))})
        if segments == ["entries"]:
            return self._create() if method == "POST" else self._list(query)
        if len(segments) == 2:
            manifest = catalog.read_manifest(root, segments[1])
            return self._json(200, manifest) if manifest else self._error(404, "not found")
        path = catalog.entry_file(root, segments[1], segments[2])
        return self._file(path, ENTRY_TYPES) if path else self._error(404, "not found")

    # API handlers

    def _list(self, query):
        category = (query.get("category") or [""])[0] or None
        if category is not None and category not in CATEGORIES:
            return self._error(400, "category")
        q = (query.get("q") or [""])[0]
        self._json(200, {"entries": catalog.list_entries(self.server.root, q, category)})

    def _create(self):
        body = self._read_body()
        if body is None:
            return
        try:
            obj = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return self._error(400, "body")
        if not isinstance(obj, dict):
            return self._error(400, "body")
        fields, bad = clean_create_request(obj)
        if bad:
            return self._error(400, bad)
        self._json(201, self._save(fields))

    def _save(self, fields):
        """Write the new entry, then trim the oldest visitor recordings over the cap. A failed
        trim is logged; the new entry stays saved."""
        srv = self.server
        with srv.save_lock:
            manifest = catalog.create_mock_entry(srv.root, **fields)
            try:
                catalog.enforce_cap(srv.root, srv.max_recordings, manifest["id"])
            except OSError as exc:
                catalog.log(f"could not apply the cap of {srv.max_recordings}: {exc}")
        return manifest

    def _read_body(self):
        """The request body bytes, or None after an error response was sent."""
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            length = -1
        if length < 0:
            self.close_connection = True
            self._error(400, "body")
            return None
        if length > MAX_BODY:
            self.rfile.read(min(length, DRAIN_LIMIT))
            self.close_connection = True
            self._error(413, "body too large")
            return None
        return self.rfile.read(length)

    # Static and file responses

    def _static(self, segments):
        web = self.server.web_root
        if segments == [""]:
            segments = ["index.html"]
        if any(s in ("", ".", "..") or s.startswith(".") or "\\" in s or "\0" in s
               for s in segments):
            return self._error(404, "not found")
        target = (web.joinpath(*segments)).resolve()
        if not target.is_relative_to(web) or not target.is_file():
            return self._error(404, "not found")
        self._file(target, TYPES, cache="no-cache")

    def _file(self, path, types, cache="no-store"):
        size = path.stat().st_size
        span = parse_range(self.headers.get("Range"), size)
        start, end = span if span else (0, size - 1)
        length = end - start + 1 if size else 0
        headers = {"Content-Type": types.get(path.suffix.lower(), FALLBACK_TYPE),
                   "Accept-Ranges": "bytes", "Cache-Control": cache}
        if span:
            headers["Content-Range"] = f"bytes {start}-{end}/{size}"
        self._start(206 if span else 200, length, headers)
        if self.command != "HEAD" and length:
            with path.open("rb") as handle:
                handle.seek(start)
                left = length
                while left > 0:
                    chunk = handle.read(min(CHUNK, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)

    # Response helpers

    def _start(self, status, length, headers):
        self.send_response(status)
        for key, value in headers.items():
            self.send_header(key, value)
        self.send_header("X-Content-Type-Options", "nosniff")
        if self.close_connection:
            self.send_header("Connection", "close")
        self.send_header("Content-Length", str(length))
        self.end_headers()
        self._headers_sent = True

    def _json(self, status, obj):
        body = json.dumps(obj).encode("utf-8")
        self._start(status, len(body),
                    {"Content-Type": "application/json", "Cache-Control": "no-store"})
        if self.command != "HEAD":
            self.wfile.write(body)

    def _error(self, status, reason):
        self._json(status, {"error": reason})

    def _redirect(self, location):
        self._start(301, 0, {"Location": location, "Cache-Control": "no-store"})


def make_server(root, host="127.0.0.1", port=0, base_path=None, web_root=None,
                max_recordings=catalog.DEFAULT_MAX_RECORDINGS):
    catalog.guard_root(root)
    if max_recordings < 0:
        raise ValueError(f"max_recordings must be 0 or more, got {max_recordings}")
    base = normalize_base(os.environ.get("SIMON6_BASE_PATH") if base_path is None else base_path)
    return CatalogServer((host, port), root, base, web_root or REPO_ROOT / "web", max_recordings)


def serve(root, host="127.0.0.1", port=8726, max_recordings=catalog.DEFAULT_MAX_RECORDINGS):
    """Seed the catalog when it has no entry, then serve until SIGTERM or Ctrl-C."""
    catalog.seed(root)
    server = make_server(root, host, port, max_recordings=max_recordings)

    def stop(signum, _frame):
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    address = f"http://{server.server_address[0]}:{server.server_address[1]}{server.base_path}/"
    catalog.log(f"serving {address} catalog={root} max-recordings={max_recordings}")
    try:
        server.serve_forever(poll_interval=0.1)
    finally:
        server.server_close()
    return 0
