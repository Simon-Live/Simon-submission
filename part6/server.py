"""HTTP server: static `web/`, the catalog API and entry files, under SIMON6_BASE_PATH.

Stdlib only. `ThreadingHTTPServer` with daemon threads, so a browser's parallel requests never
block each other and the process exits at once on SIGTERM. Requests are logged to stderr. Error
bodies are JSON `{"error": "<field or reason>"}`. A recording is processed by a job on the worker
of `part6/jobs.py`; the entry is stored under the save lock, which also covers the visitor cap.
An import reads its files outside that lock and takes it only to write and cap; one import runs at
a time and its whole body must arrive within BODY_SECONDS (docs/specs/catalog-contract.md AC-C03,
AC-C07, AC-C09).
"""
from __future__ import annotations

import base64
import binascii
import json
import os
import signal
import sys
import threading
import time
import traceback
import unicodedata
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from . import catalog, contract, importer
from .catalog import REPO_ROOT
from .jobs import Busy, Jobs, describe
from .motion import CATEGORIES
from .validate import FILES_SOURCES, NotJson, clean_create_request, clean_name, parse_json

MAX_BODY = 4096                    # POST api/entries
MAX_IMPORT_BODY = 24 << 20         # POST api/import (AC-C07)
MAX_IMPORTS = 1                    # imports running at once
BODY_SECONDS = 60.0                # a request body must arrive within this long in total
DRAIN_LIMIT = 1 << 20
CHUNK = 1 << 16
WAIT_SECONDS = 3.0                 # how long POST api/entries waits before it answers 202
ID_TRIES = 8
FILE_NAME_MAX = 255
BUSY = "busy, try again"
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

    def __init__(self, address, root, base_path, web_root, max_recordings, processor=None,
                 follow_url=None):
        super().__init__(address, Handler)
        self.root = Path(root)
        self.base_path = base_path
        self.web_root = Path(web_root).resolve()
        self.max_recordings = max_recordings
        self.follow_url = follow_url
        self.save_lock = threading.Lock()    # one save at a time, so the cap cannot overshoot
        self.import_slots = threading.BoundedSemaphore(MAX_IMPORTS)
        self.jobs = Jobs(self.root, processor, store=self.store)

    def store(self, recording, files, files_source, description):
        """Store a processed recording as an entry, then apply the cap; the worker's callback."""
        with self.save_lock:
            manifest = importer.store_processed(
                self.root, recording, files, files_source=files_source,
                description=description, visitor=True)
            self.apply_cap(manifest["id"])
        return manifest

    def apply_cap(self, keep_id):
        """Trim the oldest visitor entries over the cap. A failed trim is logged; the new entry
        stays saved. The caller holds the save lock."""
        try:
            catalog.enforce_cap(self.root, self.max_recordings, keep_id)
        except OSError as exc:
            catalog.log(f"could not apply the cap of {self.max_recordings}: {exc}")

    def server_close(self):
        self.jobs.close()
        super().server_close()


class Handler(BaseHTTPRequestHandler):
    server_version = "Simon6"
    protocol_version = "HTTP/1.1"
    timeout = 30
    _headers_sent = False
    _body_done = False

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
        self._body_done = False
        if method not in ("GET", "HEAD"):
            self.close_connection = True    # a body we do not read must not become a request
        try:
            self._dispatch(method)
            if method not in ("GET", "HEAD") and not self._body_done:
                self._discard_body()
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True

    def _dispatch(self, method):
        try:
            self._route(method)
        except (BrokenPipeError, ConnectionResetError):
            raise
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
        known = {("health",): ("GET", "HEAD"), ("contract",): ("GET", "HEAD"),
                 ("entries",): ("GET", "HEAD", "POST"), ("import",): ("POST",)}
        allowed = known.get(tuple(segments)) or (
            ("GET", "HEAD") if (segments[:1] == ["entries"] and len(segments) in (2, 3))
            or (segments[:1] == ["jobs"] and len(segments) == 2) else None)
        if allowed is None:
            return self._error(404, "not found")
        if method not in allowed:
            return self._error(405, "method not allowed")
        if segments == ["health"]:
            return self._json(200, {"ok": True, "entries": len(catalog.list_entries(root)),
                                    "contract_version": contract.CONTRACT_VERSION})
        if segments == ["contract"]:
            return self._json(200, contract.document(self.server.follow_url))
        if segments == ["import"]:
            return self._import()
        if segments[0] == "jobs":
            return self._job(segments[1])
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
        source = (query.get("source") or [""])[0] or None
        if source is not None and source not in FILES_SOURCES:
            return self._error(400, "source")
        q = (query.get("q") or [""])[0]
        self._json(200, {"entries": catalog.list_entries(self.server.root, q, category, source)})

    def _create(self):
        body = self._read_body(MAX_BODY)
        if body is None:
            return
        obj = self._json_object(body)
        if obj is None:
            return
        fields, bad = clean_create_request(obj)
        if bad:
            return self._error(400, bad)
        srv = self.server
        entry_id = self._free_id(fields["name"])
        recording = dict(fields, id=entry_id, video_path=None)
        try:
            job = srv.jobs.submit(recording)
        except Busy:
            return self._error(503, BUSY)
        job = srv.jobs.wait(entry_id, WAIT_SECONDS) or job
        if job["status"] == "done":
            return self._json(201, job["entry"])
        self._json(202, {"id": entry_id, "status": job["status"], "job": f"api/jobs/{entry_id}"})

    def _free_id(self, name):
        """A new entry id that names no folder and no remembered job."""
        srv = self.server
        for _ in range(ID_TRIES):
            entry_id = catalog.new_id(name)
            if not (srv.root / entry_id).exists() and not srv.jobs.has(entry_id):
                return entry_id
        raise RuntimeError("could not allocate an entry id")

    def _job(self, job_id):
        job = self.server.jobs.get(job_id) if catalog.is_valid_id(job_id) else None
        if job is None:
            return self._error(404, "not found")
        self._json(200, job)

    def _json_object(self, body):
        """The body parsed as a JSON object, or None after a 400 was sent. Strict JSON, and a body
        nested too deep to parse is a 400, not an error of ours."""
        try:
            obj = parse_json(body)
        except NotJson:
            obj = None
        if not isinstance(obj, dict):
            self._error(400, "body")
            return None
        return obj

    def _import(self):
        """POST api/import: at most MAX_IMPORTS at once, the slot taken before the body is read."""
        slots = self.server.import_slots
        if not slots.acquire(blocking=False):
            return self._refuse(503, BUSY)
        try:
            self._import_body()
        finally:
            slots.release()

    def _import_body(self):
        if self.headers.get_content_type() != "application/json":
            return self._refuse(400, "body")
        body = self._read_body(MAX_IMPORT_BODY)
        if body is None:
            return
        obj = self._json_object(body)
        del body    # a 24 MiB import is held a few times over; let go of each copy when done
        if obj is None:
            return
        name, category = clean_name(obj.get("name")), obj.get("category")
        if name is None:
            return self._error(400, "name")
        if category not in CATEGORIES:
            return self._error(400, "category")
        items, bad = decode_files(obj.get("files"))
        del obj
        if bad:
            return self._error(400, bad)
        srv = self.server
        try:
            prepared = importer.prepare_import(name, category, items)    # slow, no lock
            del items
            with srv.save_lock:                                          # only the write and the cap
                manifest = importer.commit_import(srv.root, prepared, visitor=True)
                srv.apply_cap(manifest["id"])
        except importer.ImportProblem as exc:
            return self._error(400, str(exc))
        self._json(201, manifest)

    def _length(self):
        """The Content-Length as a non-negative int, else -1."""
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            return -1
        return length if length >= 0 else -1

    def _refuse(self, status, reason):
        """Answer without reading the body, then drop what is left of it (see _discard_body)."""
        self.close_connection = True
        self._error(status, reason)
        self._discard_body()

    def _discard_body(self):
        """Drop at most DRAIN_LIMIT bytes of an unread request body before the connection closes,
        so a client still sending sees the answer instead of a reset."""
        self._body_done = True
        left = min(self._length(), DRAIN_LIMIT)
        try:
            while left > 0:
                chunk = self.rfile.read(min(CHUNK, left))
                if not chunk:
                    break
                left -= len(chunk)
        except OSError:
            pass    # the client stopped sending; the connection closes anyway

    def _read_body(self, limit):
        """The request body bytes, read in chunks, or None after an error response was sent: 400
        `body` for a bad or short body, 413 for one over `limit`, 408 `body too slow` when it has
        not all arrived BODY_SECONDS after the first byte was asked for."""
        length = self._length()
        if length < 0:
            self.close_connection = True
            self._error(400, "body")
            return None
        if length > limit:
            self._refuse(413, "body too large")
            return None
        self._body_done = True
        try:
            body, failure = self._receive(length), (400, "body")
        except TimeoutError:
            body, failure = None, (408, "body too slow")
        self.connection.settimeout(self.timeout)
        if body is None:
            self.close_connection = True
            self._error(*failure)
        return body

    def _receive(self, length):
        """`length` bytes of the body, or None when the client stops short. Each read waits at
        most what is left of BODY_SECONDS, so a sender that trickles bytes cannot hold the
        request open; TimeoutError when the time is up."""
        deadline = time.monotonic() + BODY_SECONDS
        parts, left = [], length
        while left > 0:
            patience = min(deadline - time.monotonic(), self.timeout)
            if patience <= 0:
                raise TimeoutError("the body did not arrive in time")
            self.connection.settimeout(patience)
            chunk = self.rfile.read1(min(CHUNK, left))    # one read, never a wait for a full chunk
            if not chunk:
                return None
            parts.append(chunk)
            left -= len(chunk)
        return b"".join(parts)

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
        body = json.dumps(obj, allow_nan=False).encode("utf-8")    # never NaN or Infinity
        self._start(status, len(body),
                    {"Content-Type": "application/json", "Cache-Control": "no-store"})
        if self.command != "HEAD":
            self.wfile.write(body)

    def _error(self, status, reason):
        self._json(status, {"error": reason})

    def _redirect(self, location):
        self._start(301, 0, {"Location": location, "Cache-Control": "no-store"})


def _usable_name(name):
    """A dropped file's name is refused only when it is empty, longer than FILE_NAME_MAX or holds
    a control character (category Cc), the rule of AC-C07. The Import screen strips control
    characters from the label it sends, so a browser never meets this rule; another client can.
    A space or any other non-control character is a name."""
    return (isinstance(name, str) and 1 <= len(name) <= FILE_NAME_MAX
            and not any(unicodedata.category(c) == "Cc" for c in name))


def decode_files(files):
    """([{"name", "data"}], None) for the `files` list of an import body, else (None, reason).
    `text` is UTF-8 encoded, `base64` is decoded strictly. Sizes and kinds are the importer's.
    A message built from a name shows the importer's `file_label` of it."""
    if not isinstance(files, list):
        return None, "files"
    if len(files) > importer.MAX_FILES:
        return None, "too many files"
    items = []
    for item in files:
        name = item.get("name") if isinstance(item, dict) else None
        if not _usable_name(name):
            return None, "files"
        text, packed = item.get("text"), item.get("base64")
        if isinstance(text, str) and packed is None:
            try:
                data = text.encode("utf-8")
            except UnicodeEncodeError:
                return None, f"{importer.file_label(name)}: is not valid JSON"
        elif isinstance(packed, str) and text is None:
            try:
                data = base64.b64decode(packed.encode("ascii"), validate=True)
            except (UnicodeEncodeError, binascii.Error):
                return None, f"{importer.file_label(name)}: not valid base64"
        else:
            return None, "files"
        items.append({"name": name, "data": data})
    return items, None


def make_server(root, host="127.0.0.1", port=0, base_path=None, web_root=None,
                max_recordings=catalog.DEFAULT_MAX_RECORDINGS, processor=None, follow_url=None):
    """`processor` is a callable (see `part6/processor.py`) or None for the mock; `follow_url`
    is the optional Part 7 hand-off URL template, which must be http or https."""
    catalog.guard_root(root)
    if max_recordings < 0:
        raise ValueError(f"max_recordings must be 0 or more, got {max_recordings}")
    if follow_url:
        contract.check_follow_url(follow_url)
    base = normalize_base(os.environ.get("SIMON6_BASE_PATH") if base_path is None else base_path)
    return CatalogServer((host, port), root, base, web_root or REPO_ROOT / "web", max_recordings,
                         processor, follow_url or None)


def serve(root, host="127.0.0.1", port=8726, max_recordings=catalog.DEFAULT_MAX_RECORDINGS,
          processor=None, follow_url=None):
    """Seed a missing or empty catalog with the shipped fixture entries (AC-C13a), then serve
    until SIGTERM or Ctrl-C."""
    catalog.seed(root)
    server = make_server(root, host, port, max_recordings=max_recordings, processor=processor,
                         follow_url=follow_url)

    def stop(signum, _frame):
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    address = f"http://{server.server_address[0]}:{server.server_address[1]}{server.base_path}/"
    catalog.log(f"serving {address} catalog={root} max-recordings={max_recordings} "
                f"processor={describe(processor)}")
    try:
        server.serve_forever(poll_interval=0.1)
    finally:
        server.server_close()
    return 0
