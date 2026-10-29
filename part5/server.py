"""`python -m part5 serve`: the web page and the analysis API on the standard library only.

Everything lives under the base path (`/` by default, `/simon-part-5/` on staging). Requests for
`<base>api/...` go to `part5.api.handle`; every other address under the base is looked up in a
table of the files under `web/` made at start, so no request value becomes a file path.
"""
import gzip
import hashlib
import mimetypes
import signal
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from . import api

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
SOCKET_TIMEOUT_S = 30
GZIP_OVER_BYTES = 4096  # only the larger files are worth compressing (the vendored three.js is 1.3 MB)
NOT_FOUND = "Nothing is served at this address."
CONTENT_TYPES = {".js": "text/javascript; charset=utf-8", ".mjs": "text/javascript; charset=utf-8",
                 ".css": "text/css; charset=utf-8", ".html": "text/html; charset=utf-8",
                 ".svg": "image/svg+xml", ".json": "application/json; charset=utf-8",
                 ".md": "text/plain; charset=utf-8", ".txt": "text/plain; charset=utf-8"}


def static_table(web_dir=WEB_DIR):
    """`{"app.js": Path, "vendor/x.js": Path, ...}`: the files under `web/`, by relative address."""
    web_dir = Path(web_dir)
    return {p.relative_to(web_dir).as_posix(): p for p in sorted(web_dir.rglob("*"))
            if p.is_file() and not any(part.startswith(".") or part == "__pycache__"
                                       for part in p.relative_to(web_dir).parts)}


def content_type(path):
    if path.name == "LICENSE":  # the vendored library's licence has no suffix
        return CONTENT_TYPES[".txt"]
    return CONTENT_TYPES.get(path.suffix) or mimetypes.guess_type(path.name)[0] or "application/octet-stream"


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "part5"
    timeout = SOCKET_TIMEOUT_S

    def do_GET(self):
        self._dispatch("GET")

    def do_HEAD(self):
        self._dispatch("HEAD")

    def do_POST(self):
        self._dispatch("POST")

    def _dispatch(self, method):
        split = urlsplit(self.path)
        base = self.server.base_path
        rel = split.path[len(base):] if split.path.startswith(base) else None
        if rel is not None and rel.startswith("api/"):
            return self._api(method)
        if method == "POST":  # nothing outside the API takes a body, so none is read
            if rel is None:
                return self._refuse(*api.error_response(404, "path", NOT_FOUND))
            return self._refuse(*api.error_response(405, "method", "This address answers GET only.", {"Allow": "GET"}))
        if rel is None and base != "/" and split.path == base.rstrip("/"):
            return self._redirect(base + (f"?{split.query}" if split.query else ""))
        if rel is None:
            return self._send(*api.error_response(404, "path", NOT_FOUND), head=method == "HEAD")
        self._static(method, unquote(rel) or "index.html")

    def _api(self, method):
        body = b""
        if method == "POST":
            body = self._read_body()
            if body is None:
                return
        client = api.client_key(self.client_address[0], self.headers.get("X-Forwarded-For"))
        status, headers, payload = api.handle("GET" if method == "HEAD" else method, self.path, body,
                                              base_path=self.server.base_path, client=client)
        self._send(status, headers, payload, head=method == "HEAD")

    def _read_body(self):
        """The POST body, or None after answering 400, 411 or 413 (the body is then not read)."""
        raw = self.headers.get("Content-Length")
        if raw is None:
            self._refuse(*api.error_response(411, "body", "The request needs a Content-Length."))
            return None
        if not (raw.isascii() and raw.isdigit()):  # "²" is a digit to str.isdigit() and not to int()
            self._refuse(*api.error_response(400, "body", "The Content-Length must be a whole number of bytes."))
            return None
        if int(raw) > api.MAX_BODY_BYTES:
            self._refuse(*api.error_response(413, "upload", api.too_large_message("upload")))
            return None
        return self.rfile.read(int(raw))

    def _static(self, method, rel):
        path = self.server.static.get(rel)
        if path is None:
            return self._send(*api.error_response(404, "path", NOT_FOUND), head=method == "HEAD")
        data = path.read_bytes()
        etag = '"' + hashlib.sha256(data).hexdigest()[:20] + '"'
        headers = {"Content-Type": content_type(path), "Cache-Control": "no-cache", "ETag": etag,
                   "Vary": "Accept-Encoding", "X-Content-Type-Options": "nosniff"}
        if self.headers.get("If-None-Match") == etag:  # the browser already holds this exact file
            return self._send(304, headers, b"")
        if len(data) > GZIP_OVER_BYTES and "gzip" in self.headers.get("Accept-Encoding", ""):
            if etag not in self.server.gzipped:
                self.server.gzipped[etag] = gzip.compress(data, compresslevel=6, mtime=0)
            data, headers["Content-Encoding"] = self.server.gzipped[etag], "gzip"
        self._send(200, headers, data, head=method == "HEAD")

    def _redirect(self, location):
        self._send(301, {"Location": location, "Content-Type": "text/plain; charset=utf-8"}, b"Moved.\n")

    def _refuse(self, status, headers, payload):
        """Answer without reading the request body, then close so the unread bytes are dropped."""
        self.close_connection = True
        self._send(status, {**headers, "Connection": "close"}, payload)

    def _send(self, status, headers, payload, head=False):
        self.send_response(status)
        for name, value in headers.items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        if not head:
            self.wfile.write(payload)

    def log_message(self, fmt, *args):
        sys.stderr.write("%s %s\n" % (self.log_date_time_string(), fmt % args))


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, base_path, static):
        super().__init__(address, Handler)
        self.base_path, self.static = base_path, static
        self.gzipped = {}  # etag -> compressed bytes of the larger static files


def make_server(host="127.0.0.1", port=8725, base_path="/", web_dir=WEB_DIR):
    """A bound server (port 0 picks a free one). Builds the sample and file tables first."""
    base = api.normalise_base_path(base_path)
    api.table()
    return Server((host, port), base, static_table(web_dir))


def serve(host="127.0.0.1", port=8725, base_path="/"):
    """Serve until interrupted. Returns the process exit code."""
    try:
        server = make_server(host, port, base_path)
    except (OSError, ValueError, FileNotFoundError) as e:
        print(f"part5 serve: cannot start ({getattr(e, 'strerror', None) or e})", file=sys.stderr)
        return 1
    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    bound = server.server_address
    print(f"part5 serve: http://{bound[0]}:{bound[1]}{server.base_path}", flush=True)
    try:
        server.serve_forever()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        server.server_close()
    return 0
