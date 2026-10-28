"""The HTTP server of the run app (spec run-app.md "API / Interface Contract").

    python3 -m part3.server [--host 127.0.0.1] [--port 8733] [--base /]

Standard library only. The route table is fixed: the pages, the API and a table of the files of `web/`
built once at start-up. A request path is only ever looked up in that table, never joined to a
filesystem path, so `..`, encoded dots and backslashes simply miss and answer 404. All run logic is in
`part3.runapi`; this module owns sockets, limits, headers and the log line.
"""

import argparse
import base64
import hashlib
import ipaddress
import json
import os
import pathlib
import re
import socket
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BufferedReader, RawIOBase  # the standard library's io: in this module `io` is part3.io
from urllib.parse import parse_qsl

from part3 import io, runapi

MAX_BODY = 2 * 1024 * 1024  # bytes of an upload; a larger Content-Length is refused with 413
DRAIN_MAX = 8 * 1024 * 1024  # an oversize body up to this size is read and thrown away before the 413
SOCKET_TIMEOUT_S = 15.0  # a connection that sends nothing for this long is dropped
HEADER_DEADLINE_S = 20.0  # the request line and headers must be complete this long after the connection opens
BODY_TIMEOUT_S = 15.0  # the whole upload must arrive within this
LINGER_S = 3.0  # how long a refused request's small body is thrown away after the answer
MAX_CONNECTIONS = 16  # open connections; one more goes to the reserve below
RESERVED_CONNECTIONS = 1  # kept for `GET api/health` once MAX_CONNECTIONS are open; anything else there gets `busy`
RESERVE_HEAD_S = 2.0  # a reserve connection must send its request line and headers within this
RESERVE_LINGER_S = 0.2  # how long a reserve connection's refused body is thrown away
MAX_RUNS = 2  # pipeline runs at once; a third gets `busy`
RUN_TIMEOUT_S = 20.0  # a run past this answers `timeout`; its thread ends on its own and then frees its slot
MAX_QUERY_FIELDS = 20

STATIC_TYPES = {
    ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8", ".json": "application/json", ".png": "image/png",
    ".svg": "image/svg+xml",
}
PAGES = {"": "app.html", "agreement": "index.html"}  # path below the base -> file of web/
GET = ("GET", "HEAD")
CSP = ("default-src 'self'; script-src {scripts}; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
       "connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
_INLINE_SCRIPT = re.compile(r"<script\b(?![^>]*\bsrc\s*=)[^>]*>(.*?)</script\s*>", re.S | re.I)
_LENGTH = re.compile(r"[0-9]{1,15}")
_ADDRESS = re.compile(r"[0-9A-Fa-f:.]{2,45}")
_UNPRINTABLE = re.compile(r"[^\x20-\x7e]")


def normalise_base(base):
    """The base path with exactly one leading and one trailing slash (`/` stays `/`)."""
    inner = base.strip("/")
    return f"/{inner}/" if inner else "/"


def build_table(web_dir):
    """{url path below the base: file} for every file under `web_dir` with an allowed extension."""
    root, table = pathlib.Path(web_dir), {}
    for folder, _, names in os.walk(root):
        for name in names:
            path = pathlib.Path(folder, name)
            if path.suffix.lower() in STATIC_TYPES and not name.startswith(".") and not path.is_symlink():
                table[path.relative_to(root).as_posix()] = path
    return table


def log(line):
    """One line on stderr with a UTC time stamp."""
    print(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {line}", file=sys.stderr, flush=True)


def csp_for(path):
    """The Content-Security-Policy of an HTML file: 'self' plus the SHA-256 of each inline script."""
    text = path.read_text(encoding="utf-8", errors="replace")
    hashes = [f"'sha256-{base64.b64encode(hashlib.sha256(block.encode()).digest()).decode()}'"
              for block in _INLINE_SCRIPT.findall(text)]
    return CSP.format(scripts=" ".join(["'self'", *hashes]))


class AppServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 64

    def __init__(self, address, base="/", web_dir=None):
        self.base = normalise_base(base)
        self.table = build_table(web_dir or io.REPO / "web")
        self.csp = {name: csp_for(path) for name, path in self.table.items() if path.suffix.lower() == ".html"}
        self.slots = threading.BoundedSemaphore(MAX_RUNS)
        self.connections = threading.BoundedSemaphore(MAX_CONNECTIONS)
        self.reserve = threading.BoundedSemaphore(RESERVED_CONNECTIONS)
        self.reserved = set()  # the sockets that were admitted through the reserve
        runapi.samples()  # fail now, not on the first request, when a fixture is missing
        super().__init__(address, Handler)

    def process_request(self, request, client_address):
        """Admit a connection: a general slot, else the reserve (which only answers health), else `busy`."""
        if self.connections.acquire(blocking=False):
            gate = self.connections
        elif self.reserve.acquire(blocking=False):
            gate = self.reserve
            self.reserved.add(request)
        else:
            return self._turn_away(request, client_address)
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.reserved.discard(request)
            gate.release()
            raise

    def process_request_thread(self, request, client_address):
        gate = self.reserve if request in self.reserved else self.connections
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.reserved.discard(request)
            gate.release()

    def finish_request(self, request, client_address):
        (ReserveHandler if request in self.reserved else Handler)(request, client_address, self)

    def _turn_away(self, request, client_address):
        """Over the connection cap: a quick `busy` answer, written without reading the request."""
        status, body = runapi.error("busy")
        data = json.dumps(body).encode()
        head = (f"HTTP/1.0 {status} Service Unavailable\r\nContent-Type: application/json\r\n"
                f"Content-Length: {len(data)}\r\nCache-Control: no-store\r\nX-Content-Type-Options: nosniff\r\n"
                "Referrer-Policy: no-referrer\r\nConnection: close\r\n\r\n")
        try:
            request.settimeout(0.2)
            request.sendall(head.encode() + data)
            request.shutdown(socket.SHUT_WR)
            request.recv(65536)  # let a request already on the wire arrive, so the close is not a reset
        except OSError:
            pass
        self.shutdown_request(request)
        log(f"- - {status} 0ms {client_address[0]} connection cap")


class _HeadReader(RawIOBase):
    """The raw reader of a connection. While `deadline` (a time.monotonic() value) is set, no read waits past it,
    so the request line and headers must be complete by then however slowly they trickle in."""

    def __init__(self, sock):
        super().__init__()
        self._sock, self.deadline = sock, None

    def readable(self):
        return True

    def readinto(self, buffer):
        if self.deadline is not None:
            left = self.deadline - time.monotonic()
            if left <= 0:
                raise TimeoutError("the request head took too long")
            self._sock.settimeout(min(left, SOCKET_TIMEOUT_S))
        return self._sock.recv_into(buffer)


class Handler(BaseHTTPRequestHandler):
    server_version = "part3"
    protocol_version = "HTTP/1.0"  # one request per connection: an unread body can never be mistaken for a request
    disable_nagle_algorithm = True  # the header block and the body go out as two writes
    reserved = False  # True in ReserveHandler: only GET api/health is answered

    def setup(self):
        self.timeout = SOCKET_TIMEOUT_S  # a client that sends nothing cannot hold a thread
        super().setup()
        self.rfile.close()  # the standard reader has no total deadline; this one stops a trickle of header bytes
        self._head = _HeadReader(self.connection)
        self._head.deadline = time.monotonic() + (RESERVE_HEAD_S if self.reserved else HEADER_DEADLINE_S)
        self.rfile = BufferedReader(self._head)

    def parse_request(self):
        try:
            return super().parse_request()
        finally:
            self._head.deadline = None  # the head is in; the body has its own deadline (`_chunks`)
            self.connection.settimeout(self.timeout)  # writes get the normal timeout again

    def version_string(self):
        return self.server_version

    # -- entry points -------------------------------------------------------------------------

    def _dispatch(self):
        self._started, self._note = time.perf_counter(), ""
        path, _, query = self.path.partition("?")
        base = self.server.base
        if self.reserved and not (self.command in GET and path == base + "api/health"):
            return self._refuse("busy", RESERVE_LINGER_S)
        if not path.startswith(base):
            if base != "/" and path == base.rstrip("/") and self.command in GET:
                return self._send(308, b"", "text/plain", "no-cache", [("Location", base)])
            return self._error("not_found")
        methods, action = self._endpoint(path[len(base):])
        if action is None:
            return self._error("not_found")
        if self.command not in methods:
            return self._error("method", [("Allow", ", ".join(methods))])
        return action(query)

    do_GET = do_HEAD = do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = _dispatch

    def _endpoint(self, rel):
        """(methods, action) for a path below the base; (None, None) when there is no such path."""
        if rel == "api/health":
            return GET, lambda query: self._json(200, {"ok": True, "samples": len(runapi.samples())})
        if rel == "api/samples":
            return GET, lambda query: self._json(200, {"samples": runapi.samples()})
        if rel == "api/run":
            return ("POST",), self._run
        name = PAGES.get(rel, rel)
        if name in self.server.table:
            return GET, lambda query: self._static(name)
        return None, None

    # -- answers ------------------------------------------------------------------------------

    def _send(self, status, body, ctype, cache, extra=()):
        headers = [("Content-Type", ctype), ("Content-Length", str(len(body))), ("Cache-Control", cache),
                   ("X-Content-Type-Options", "nosniff"), ("Referrer-Policy", "no-referrer"), *extra]
        try:
            self.send_response(status)
            for name, value in headers:
                self.send_header(name, value)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)
        except OSError:  # the client hung up; there is nobody to answer
            self.close_connection = True
        self._log(status)

    def _json(self, status, body, extra=()):
        try:
            data = json.dumps(body, allow_nan=False).encode()
        except ValueError:  # a NaN or infinity that a metric should have turned into null
            traceback.print_exc(file=sys.stderr)
            status, body = runapi.error("internal")
            data = json.dumps(body).encode()
        self._send(status, data, "application/json", "no-store", extra)

    def _error(self, code, extra=()):
        status, body = runapi.error(code)
        self._json(status, body, extra)

    def send_error(self, code, message=None, explain=None):  # the base class answers malformed requests in HTML
        self._started, self._note = time.perf_counter(), ""
        self.close_connection = True
        self._json(code, runapi.error("bad_request")[1])

    def _static(self, name):
        path = self.server.table[name]
        try:
            data = path.read_bytes()
        except OSError:
            return self._error("not_found")
        csp = self.server.csp.get(name)
        self._send(200, data, STATIC_TYPES[path.suffix.lower()], "no-cache",
                   [("Content-Security-Policy", csp)] if csp else [])

    # -- POST api/run -------------------------------------------------------------------------

    def _run(self, query):
        if self.headers.get("Sec-Fetch-Site", "").lower() == "cross-site":
            return self._refuse("cross_site")
        length, problem = self._length()
        if problem:
            return self._error(problem)
        if length > MAX_BODY:
            return self._too_large(length)
        try:
            fields = dict(reversed(parse_qsl(query, keep_blank_values=True, max_num_fields=MAX_QUERY_FIELDS)))
        except ValueError:
            return self._refuse("bad_request")
        slots, handed = self.server.slots, False
        if not slots.acquire(blocking=False):  # the slot is taken before the body is read
            return self._refuse("busy")
        try:
            body = b"".join(self._chunks(length, BODY_TIMEOUT_S))
            if len(body) != length:
                return self._error("bad_request")
            if body:
                self._note = f"upload={length}B sha256={hashlib.sha256(body).hexdigest()[:16]}"
            handed = True
            status, payload = self._execute(fields.get("sample"), fields.get("flip", "auto"), fields.get("name"), body)
        finally:
            if not handed:
                slots.release()
        self._json(status, payload)

    def _length(self):
        """(Content-Length, None), or (None, error code): 411 when missing (or chunked), 400 when not digits."""
        raw = self.headers.get("Content-Length")
        if raw is None or self.headers.get("Transfer-Encoding"):
            return None, "length_required"
        if not _LENGTH.fullmatch(raw):
            return None, "bad_request"
        return int(raw), None

    def _too_large(self, length):
        """413: a body up to DRAIN_MAX is read and thrown away first, a larger one is not read at all."""
        self.close_connection = True
        if length <= DRAIN_MAX:
            self._discard(length, BODY_TIMEOUT_S)
        self._error("too_large", [("Connection", "close")])

    def _refuse(self, code, linger_s=None):
        """Answer `code`, then throw away a small unread body so the client sees the answer, not a reset."""
        self.close_connection = True
        self._error(code, [("Connection", "close")])
        raw = self.headers.get("Content-Length", "")
        self._discard(min(int(raw), DRAIN_MAX) if _LENGTH.fullmatch(raw) else 0, LINGER_S if linger_s is None else linger_s)

    def _chunks(self, length, seconds):
        """The next pieces of the request body, up to `length` bytes, until it ends or `seconds` pass."""
        deadline = time.monotonic() + seconds
        try:
            while length > 0 and (left := deadline - time.monotonic()) > 0:
                self.connection.settimeout(left)
                try:
                    chunk = self.rfile.read1(min(length, 65536))
                except OSError:
                    return
                if not chunk:
                    return
                length -= len(chunk)
                yield chunk
        finally:
            self.connection.settimeout(SOCKET_TIMEOUT_S)  # writes get the normal timeout again

    def _discard(self, length, seconds):
        for _ in self._chunks(length, seconds):
            pass

    def _execute(self, sample, flip, name, body):
        """`runapi.handle` in a worker thread, RUN_TIMEOUT_S at most. The caller's run slot goes with the
        thread and comes back only when it ends, so a flood of slow runs gets `busy`, not more work."""
        slots, box = self.server.slots, []

        def work():
            try:
                box.append(runapi.handle(sample, flip, name, body))
            except Exception:  # noqa: BLE001 - logged here, answered as `internal` without it
                traceback.print_exc(file=sys.stderr)
                box.append(runapi.error("internal"))
            finally:
                slots.release()

        worker = threading.Thread(target=work, daemon=True)
        try:
            worker.start()
        except BaseException:
            slots.release()
            raise
        worker.join(RUN_TIMEOUT_S)
        return box[0] if box and not worker.is_alive() else runapi.error("timeout")

    # -- log ----------------------------------------------------------------------------------

    def log_request(self, code="-", size="-"):  # `_log` writes the one line per request
        pass

    def _client(self):
        peer = self.client_address[0]
        try:
            loopback = ipaddress.ip_address(peer).is_loopback
        except ValueError:
            loopback = False
        headers = getattr(self, "headers", None)
        forwarded = ((headers.get("X-Forwarded-For") if headers else None) or "").split(",")[0].strip()
        return forwarded if loopback and _ADDRESS.fullmatch(forwarded) else peer

    def _log(self, status):
        path = _UNPRINTABLE.sub("?", getattr(self, "path", "-").partition("?")[0])[:200]
        ms = (time.perf_counter() - getattr(self, "_started", time.perf_counter())) * 1000.0
        note = f" {self._note}" if getattr(self, "_note", "") else ""
        log(f"{self.command} {path} {status} {ms:.0f}ms {self._client()}{note}")


class ReserveHandler(Handler):
    """The handler of the connection kept back for `GET api/health` once every general slot is taken. It answers
    health and `busy` to anything else, and gives a slow client only RESERVE_HEAD_S, so visitors cannot hold it."""

    reserved = True


def _parser():
    parser = argparse.ArgumentParser(prog="python3 -m part3.server", description="Serve the Part 3 run app.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8733)
    parser.add_argument("--base", default="/", help="path prefix the app answers under (default /)")
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    try:
        app = AppServer((args.host, args.port), args.base)
    except OSError as problem:
        print(f"part3.server: cannot listen on {args.host}:{args.port} ({problem.strerror})", file=sys.stderr)
        return 1
    print(f"part3.server: http://{args.host}:{app.server_address[1]}{app.base} ({len(app.table)} static files)",
          file=sys.stderr, flush=True)
    try:
        app.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        app.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
