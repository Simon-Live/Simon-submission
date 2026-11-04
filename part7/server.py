"""The Simon Part 7 HTTP server: API, catalog proxy and static `web/` (app.md "Server").

stdlib `ThreadingHTTPServer` on 127.0.0.1. Paths are relative to the base path; a request outside it is 404.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import errno
import json
import logging
import mimetypes
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import sys
import threading
import time
from typing import Any, Callable
from urllib.parse import urlsplit
import uuid

from part7 import (
    animation_format, applog, attribution, auth, auth_routes, buildinfo, board_preview, challenge_routes, client_log, config, delete_routes, entry_check, export_data_routes, export_routes, heartbeat,
    health_probe, history_routes, history_store, idempotency, identity, jobs, judge_view, labels, media, mesh_files, mesh_stream_routes, model_import, model_only, models_used, modes, modules, muse_fix_routes, narration_routes,
    devices_routes, modal_creds_routes, my_reference, my_reference_routes, notes_routes, people, people_routes, private_mode, profile_routes, processor, proxy, quota, reference_approval_routes, refused_uploads, replay, result_media, resume, run_on, sections, selfheal, share_routes, speech_routes,
    source_routes, progress_routes, teacher_routes,
    takes_on_routes, upload_owner,
    architecture, catalog_search_routes, impact,
    group,  # one-letter.md L5: a group job's people carry `shown` at read time
    mail, mail_probe, mail_webhook,  # the SIGTERM drain waits for a mail in flight; the timed send probe
)
from part7 import own_clients  # BYOK-M6: the drain ends the own-route launchers this server started
from part7 import challenges, reference_approval, share  # their retention runs in the periodic sweep (prod-data.md)
from part7 import result_paths, take_access, take_ar, take_ar_url
from part7 import prod_check, security_headers  # prod hardening: start check, Host rule, headers (prod-hardening.md)
from part7.prod_mode import is_prod
from part7 import keys  # AC-H5c: what a killed server left in the Part 1 tree
from part7 import heat  # TICKET-274: heat on the follower's own body
from part7 import orphan_take  # TICKET-331: a follow take whose movement was deleted
from part7 import gpu_lock  # TICKET-289: api/health gpu block
from part7 import ghost, stage_split  # TICKET-264 follow the ghost, TICKET-260 stage split
from part7 import p2_warmup
from part7 import serverless_route  # serverless-compute.md: what is left at Modal goes with the sweep
from part7 import notices_routes  # TICKET-326: the footer's Licences link
from part7 import consent_record, licence_gates, modal_creds, muse_prod, policy_routes, trainer_publish  # prod hardening call sites (consent-and-age.md, licence-gates.md, byok-prod.md, trainer-publish.md)
from part7 import mirrored as mirrored_take  # TICKET-310: the person says an upload is a mirrored video
from part7.parts import p1_keyframes, p5_analyse

ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
LANG_RE = re.compile(r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})?$")
VIDEO_TYPES = {"video/mp4": "mp4", "video/webm": "webm", "video/quicktime": "mov"}
CATEGORIES = ("exercise", "dance")
NAME_MAX = 80
DRAIN_LIMIT = 300_000_000  # an oversized upload is read and dropped up to here so the browser sees the 413
DURATION_SLACK_S = 0.5  # MediaRecorder stops a little after its 60 s timer
TRIM_END_SLACK_MS = 1500  # a trim end this far past the probed length is cut at the end (the recorder clock runs long)
UNSET_TRIM = {"start_ms": 0, "end_ms": 0}  # TICKET-309: what a trim editor sends before it knows the length
JSON_BODY_MAX = 65536
CHUNK = 1 << 20

MSG_NOT_VIDEO = "This file is not a video. Pick an MP4 or WebM file."
MSG_TOO_LONG = "The video is too long (60 s at most)."
MSG_TOO_LONG_RAW = "The video is too long (90 s at most)."
MSG_TRIM_SHAPE = "The selection needs a start and an end in milliseconds."
MSG_TRIM_ORDER = "The selection must start before it ends, inside the video."
MSG_TRIM_SHORT = "The selection is too short (1 s at least)."
MSG_TRIM_LONG = "The selection is too long (60 s at most)."
MSG_HOST = "This address is not served here."
MSG_CHUNKED = "The request needs a Content-Length."
UPLOAD_BODY_MIN = JSON_BODY_MAX  # a body longer than this is an upload: the per-client guard and the prod body cap apply
MSG_NO_ENTRY = "This movement is not in the catalog."
MSG_NO_ANIMATION = "This movement has no animation to follow."
MSG_BAD_ANIMATION = "This movement's animation is not in a form the comparison accepts."
MSG_KEY_REUSED = "This Idempotency-Key was already used for a different request."
MSG_NO_UPLOAD = "The upload was not found. Pick the video again."
MSG_NO_JOB = "This job was not found."
MSG_NAME = "Give the movement a name of 80 characters at most."
MSG_CATEGORY = "Pick exercise or dance."
MSG_CATALOG_DOWN = "The catalog is not answering. Try again in a moment."
MSG_CSRF = auth_routes.MSG_CSRF
MSG_NOT_JSON = "The request must be sent as JSON."
MSG_UPLOAD_SIGN_IN = "Sign in to upload a video."
STATE_METHODS = ("POST", "PUT", "PATCH", "DELETE")


@dataclass
class App:
    """Everything a request needs; tests build one with a fake `child`."""

    state: Path
    base: str
    child: Any
    queue: jobs.JobQueue
    quota: quota.Quota
    lock: modules.Modules
    web_dir: Path = config.WEB_DIR
    phrasing: str = "live"
    backend: str = "gpu"
    build: dict[str, Any] = field(default_factory=buildinfo.unknown)
    client_rate: client_log.RateLimit = field(default_factory=client_log.RateLimit)
    idem: idempotency.Store | None = None
    part6_probe: health_probe.Part6Probe = field(default_factory=health_probe.Part6Probe)
    @property
    def idempotency(self) -> idempotency.Store:
        if self.idem is None:
            self.idem = idempotency.Store(self.state, config.RETENTION_DAYS)
        return self.idem

    @property
    def uploads(self) -> Path:
        return self.state / "uploads"

    def upload_file(self, upload_id: str) -> Path | None:
        if not jobs.UPLOAD_ID_RE.match(upload_id):
            return None
        found = sorted((self.uploads / upload_id).glob("upload.*")) if (self.uploads / upload_id).is_dir() else []
        return found[0] if found else None


def too_large_message() -> str:
    return f"The file is too large ({config.upload_max_bytes() // 1_000_000} MB at most)."


def phrasing_from_env() -> str:
    """SIMON7_PHRASING, then the licence gate: prod phrases from the template while the Muse Spark Open terms are unread (LIC-H1)."""
    return licence_gates.phrasing("template" if os.environ.get("SIMON7_PHRASING", "live") == "template" else "live")


SLOW_REQUEST_S = 2.0
DRAIN_ROUTES = frozenset({"uploads", "trainer", "follow", "people", "group", "models"})  # POSTs that start work (models: TICKET-306)
TAKE_ROUTES = DRAIN_ROUTES - {"models"}  # POSTs a take walks through
SLOW_UPLOAD_S = 20.0  # a POST api/uploads or api/models carries the visitor's file: transfer time is part of it
SLOW_MEDIA_S = 10.0  # media GETs stream; the limit applies to the time to the first byte (headers out)
MEDIA_SUFFIXES = (".mp4", ".webm", ".mov")


def make_handler(app: App) -> type[BaseHTTPRequestHandler]:
    class Handler(_Handler):
        pass

    Handler.app = app
    Handler.timeout = config.socket_timeout_s()  # APP-M3: a stalled read or write ends the connection (prod: 60 s)
    return Handler


class _Handler(BaseHTTPRequestHandler):
    _body_cache: bytes | None = None  # a JSON body read early by the Idempotency-Key check
    app: App
    _expected_busy = False  # set per request by a route whose 5xx is busy by design (speech_routes.py)
    _rid = ""  # the request id, set per request (observability.md "Failure lines and request ids")
    _reason = ""  # why this request answered 5xx
    server_version = "Simon7"
    sys_version = ""

    # ----- plumbing -------------------------------------------------------------------------
    def log_message(self, fmt: str, *args: Any) -> None:
        line = re.sub(r"(/api/shared/)[^/\s?\"]+", r"\1<token>", fmt % args)  # TICKET-233: a share token is never logged
        line = re.sub(r"\?[^\s\"]*", "", line)  # D8: no query string (a name typed into a form) reaches the log
        # An ISO UTC time first, so the 14-day age rule can read it (log_retention.py); account ids hashed (applog)
        sys.stderr.write(f"{applog.utc_stamp()} {applog.scrub(line)}\n")  # DI-R1: no movement name either

    def send_header(self, keyword: str, value: str) -> None:
        self._header_names = getattr(self, "_header_names", set()) | {keyword.lower()}
        super().send_header(keyword, value)

    def end_headers(self) -> None:
        """Every response carries the security headers (security_headers.py); a route that set one itself keeps its own."""
        sent = getattr(self, "_header_names", set())
        rest = self._rest() if hasattr(self, "path") else None  # a request line that did not parse has no path
        catalog = rest is not None and (rest == "catalog" or rest.startswith("catalog/"))
        web = config.part_dir(6) / "web" if catalog else self.app.web_dir
        framed = catalog or rest == "whitepaper.html"  # `#/whitepaper` frames this one page from the app's own origin
        for key, value in security_headers.headers(web, same_origin_frame=framed).items():
            if key.lower() not in sent:
                super().send_header(key, value)
        self._header_names = set()
        if self._rid:
            super().send_header("X-Request-Id", self._rid)  # the id its failure line carries, if it fails (observability.md)
        super().end_headers()

    def _send(self, status: int, body: bytes, ctype: str, extra: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if not any(key.lower() == "referrer-policy" for key in (extra or {})):  # a route that names it itself is not sent it twice
            self.send_header("Referrer-Policy", "no-referrer")  # a sign-in link or a job id in the URL never travels onward
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status: int, obj: Any) -> None:
        idem = getattr(self, "_idem", None)
        if idem is not None and status in idempotency.REPLAYABLE:
            try:  # remembered before the answer goes out, so a lost answer can be replayed
                kept = {k: v for k, v in obj.items() if k != "creator_token"} if isinstance(obj, dict) else obj
                self.app.idempotency.put(idem[0], idem[1], status, kept, getattr(self, "_idem_fp", None))  # R2: no token on disk
            except OSError:
                pass
        self._send(status, json.dumps(obj).encode("utf-8"), "application/json; charset=utf-8")

    def _take_refusal(self, status: int) -> bool:
        """A POST that carries a take answered 4xx: named in the log (offline-takes.md AC-OT13)."""
        return 400 <= status < 500 and self.command == "POST" and (self._rest() or "").removeprefix("api/") in TAKE_ROUTES

    def _error(self, status: int, message: str, **extra: Any) -> None:
        if status >= 500:
            self._reason = self._reason or message  # a crash's own type stays the reason over the visitor's plain text
        if status >= 500 or self._take_refusal(status):
            applog.log(f"{self.command} {applog.safe_path(urlsplit(self.path).path)} answered {status}: {message}", level=logging.WARNING)
        self._json(status, {"ok": False, "error": message, "message": message, **extra})

    def _rest(self) -> str | None:
        """The path below the base path, or None when the request is outside it."""
        path = urlsplit(self.path).path
        base = self.app.base
        if path == base.rstrip("/") and base != "/":
            return None
        return path[len(base):] if path.startswith(base) else None

    def _visitor(self) -> str | None:
        """The address every limiter counts: `auth.client_addr`, the one header-trust rule (app-surface R6)."""
        return auth.client_addr(self)

    def _body_json(self) -> dict[str, Any] | None:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if length < 0:  # reading a negative length would wait for a body that never ends
            self.close_connection = True
            self._error(400, "The request is not valid JSON.")
            return None
        if length > JSON_BODY_MAX:
            self._error(413, "The request is too large.")
            return None
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ctype != "application/json":  # app-surface R3: a text/plain form post is not taken for JSON
            self.close_connection = True  # the unread body must not be taken for the next request
            self._error(415, MSG_NOT_JSON)
            return None
        try:
            raw = self._body_cache if self._body_cache is not None else self.rfile.read(length)
            doc = json.loads(raw or b"null")
        except ValueError:
            doc = None
        if not isinstance(doc, dict):
            self._error(400, "The request is not valid JSON.")
            return None
        return doc

    # ----- dispatch -------------------------------------------------------------------------
    def do_GET(self) -> None:
        self._dispatch()

    do_HEAD = do_GET

    def do_POST(self) -> None:
        self._dispatch()

    do_PUT = do_DELETE = do_PATCH = do_OPTIONS = do_POST

    def send_response_only(self, code: int, message: str | None = None) -> None:
        self._answered = True  # a status line is out: a second response would corrupt the stream
        if self._first_byte is None:
            self._first_byte = time.monotonic()
        self._status = code
        super().send_response_only(code, message)

    def _dispatch(self) -> None:
        self._answered = False
        self._status = 0
        self._expected_busy = False  # a route sets it on an answer that is busy by design (speech_routes.py)
        self._first_byte = None
        self._rid = secrets.token_hex(6)  # our own, never the client's: a client must not choose what the log says
        self._reason = ""
        t0 = time.monotonic()
        try:
            self._timed_route()
        finally:
            end = time.monotonic()
            first = self._first_byte if self._first_byte is not None else end
            self._report_request(end - t0, first - t0)

    def _slow_limit(self, rest: str | None) -> tuple[float, bool]:
        """(limit in seconds, whether it applies to the time to first byte) for this route (observability.md)."""
        if self.command == "POST" and rest in ("api/uploads", "api/models"):
            return applog.env_float("SIMON7_SLOW_UPLOAD_S", SLOW_UPLOAD_S), False
        if self.command in ("GET", "HEAD") and rest is not None and rest.lower().endswith(MEDIA_SUFFIXES):
            return applog.env_float("SIMON7_SLOW_MEDIA_S", SLOW_MEDIA_S), True
        return applog.env_float("SIMON7_SLOW_REQUEST_S", SLOW_REQUEST_S), False

    def _report_request(self, seconds: float, first_byte_s: float | None = None) -> None:
        """`ANOMALY slow_request` past the route's limit and `ANOMALY http_5xx`; `path` is below the base path, no query."""
        full = urlsplit(self.path).path
        rest = self._rest()
        path = applog.safe_path(rest if rest is not None else full)
        fields: dict[str, Any] = {"method": self.command, "path": path, "status": self._status, "seconds": seconds}
        length = self.headers.get("Content-Length", "") if self.headers is not None else ""
        if length.isascii() and length.isdigit() and len(length) <= 20:  # past Python's digit limit int() raises, after the answer went out
            fields["bytes"] = int(length)
        limit, on_first_byte = self._slow_limit(rest)
        if (first_byte_s if on_first_byte and first_byte_s is not None else seconds) > limit:
            applog.anomaly("slow_request", **fields)
        if self._status >= 500 and self._expected_busy:  # a designed "try again shortly": one INFO line, no anomaly
            applog.log(f"{self.command} {fields['path']} answered {self._status} (busy by design)")
        elif self._status >= 500:
            applog.anomaly("http_5xx", **fields, rid=self._rid or None, route=selfheal.route_key(self.command, path),
                           reason=self._reason or f"answered {self._status} with no reason from the route")

    def _timed_route(self) -> None:
        try:
            self._route()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            # the client closed the connection mid-answer: not a server fault, so no ERROR and no traceback (TICKET-204)
            applog.log(f"client closed the connection during {self.command} {urlsplit(self.path).path}")
            self.close_connection = True
        except Exception as exc:  # a handler bug: logged with the request, the visitor gets a plain 500
            self._reason = f"crashed: {type(exc).__name__}"
            applog.log(f"{self.command} {applog.safe_path(urlsplit(self.path).path)} crashed rid={self._rid}: {applog.cause(exc)}", level=logging.ERROR)
            selfheal.note_crash(self.command, self._rest() or urlsplit(self.path).path, exc)  # names the type in the 5xx finding
            if self._answered:  # headers (and maybe part of a body) already went out: end the connection instead
                self.close_connection = True
                return
            try:
                self._error(500, "Something went wrong on the server. Try again.")
            except OSError:
                pass

    def _host_ok(self) -> bool:
        """Prod serves its own domains only; a direct local request (health.sh, smoke) may name a loopback host."""
        host = (self.headers.get("Host") or "").strip().lower()
        if not host or any(c in host for c in "/@ \\"):
            return False
        name = urlsplit(f"//{host}").hostname
        if name in prod_check.allowed_hosts():
            return True
        return name in ("127.0.0.1", "localhost", "::1") and not self.headers.get("Cf-Connecting-Ip")

    def _gate_request(self) -> bool:
        """Host rule, body cap and upload guard before any route reads a byte; True when it answered (EDGE-413, APP-H3).

        In prod every body is capped at `config.body_cap_bytes()`, below the edge's 100 MB, so the 413 is the app's. An
        upload-sized body is also counted per client (uploads an hour, bytes a day) and refused near a full disk.
        """
        if is_prod() and not self._host_ok():
            self.close_connection = True
            self._error(421, MSG_HOST)
            return True
        if self.command not in ("POST", "PUT", "PATCH"):
            return False
        if is_prod() and self.headers.get("Transfer-Encoding"):  # a chunked body has no length to cap
            self.close_connection = True
            self._error(411, MSG_CHUNKED)
            return True
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return False  # the route answers a malformed length itself
        cap = config.body_cap_bytes()
        if cap is not None and length > cap:
            self._reject_upload(413, too_large_message(), length)
            return True
        if length <= UPLOAD_BODY_MIN or quota.disk_refusal(self.app.state, length) is None:
            return False
        self._reject_upload(503, quota.UPLOAD_MESSAGE_DISK, length)
        return True

    def _route(self) -> None:
        if self._gate_request():
            return
        rest = self._rest()
        if rest is None:
            self._error(404, "Not found.")
            return
        if rest == "catalog" or rest.startswith("catalog/"):
            self._catalog()
        elif rest.startswith("api/"):
            self._api(rest[4:])
        elif self.command in ("GET", "HEAD"):
            if policy_routes.page(self, rest):  # /privacy, /terms and the other legal drafts (legal-pages.md)
                return
            if board_preview.page(self, rest):  # c/<id>: a shared board's link preview, then on to the app (board-discovery.md)
                return
            self._static(rest)
        else:
            self._error(405, "Method not allowed.")

    def _catalog(self) -> None:
        child = self.app.child
        proxy.forward(self, "127.0.0.1", child.port, self.path)

    def _api(self, route: str) -> None:
        self._idem = None
        self._idem_fp = None
        self._body_cache = None
        if self._cross_site():
            return self._reject_upload(403, MSG_CSRF, self._length_or_zero())
        if self.command == "POST" and route in DRAIN_ROUTES and self.app.queue.draining:
            return self._draining_answer(route)
        claimed = self._idempotent_begin(route)
        if claimed is False:
            return  # replayed, or the same request is still running: already answered
        try:
            self._api_routes(route)
        finally:
            if claimed:
                self.app.idempotency.end(*self._idem)
                self._idem = None

    def _cross_site(self) -> bool:
        """app-surface R3: a state-changing request that carries a session cookie must come from this origin
        (`auth.same_origin`), whatever its route; the routes' own guards still apply after this one."""
        return self.command in STATE_METHODS and auth.sid_from(self) is not None and not auth.same_origin(self)

    def _length_or_zero(self) -> int:
        try:
            return max(0, int(self.headers.get("Content-Length") or 0))
        except ValueError:
            return 0

    def _draining_answer(self, route: str) -> None:
        """A restart is draining the running jobs: no new job or upload starts (jobs.drain)."""
        self.close_connection = True  # an unread upload body must not be taken for the next request
        body = json.dumps({"ok": False, "error": jobs.DRAINING_MESSAGE, "message": jobs.DRAINING_MESSAGE}).encode()
        applog.log(f"POST {route} answered 503: draining", level=logging.WARNING)
        self._send(503, body, "application/json; charset=utf-8", {"Retry-After": str(jobs.DRAIN_RETRY_AFTER_S)})

    def _idempotent_begin(self, route: str) -> bool | None:
        """Idempotency-Key (idempotency.py). None: no key applies. True: this request owns its key.
        False: it was answered here, from the stored answer or with "busy" while the first copy still runs."""
        if self.command != "POST" or route not in idempotency.ROUTES:
            return None
        key = idempotency.valid_key(self.headers.get(idempotency.HEADER))
        if key is None:
            return None
        store = self.app.idempotency
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return None  # the route answers a malformed length itself (400)
        if length < 0:
            return None
        if route == "uploads":  # the body is a large stream: bind the key to its size and type, not to a hash of its bytes
            fp = idempotency.fingerprint(f"uploads|{length}|{self.headers.get('Content-Type') or ''}".encode())
        elif length > JSON_BODY_MAX:
            return None  # the route answers 413
        else:
            self._body_cache = self.rfile.read(length)
            fp = idempotency.identity_fingerprint(self._body_cache)
        found = store.lookup(route, key)
        if found is not None and route == "uploads":  # the stored upload may be gone (server state lost): then upload again
            upload_id = str((found[1] or {}).get("upload_id") or "")
            if self.app.upload_file(upload_id) is None:
                store.drop(route, key)
                found = None
        if found is not None:
            if route == "uploads":
                self._drain(length)
            self.close_connection = True
            legacy = idempotency.fingerprint(self._body_cache) if route != "uploads" else None
            if found[2] is not None and found[2] not in (fp, legacy):
                held = found[1].get("job") if route != "uploads" and isinstance(found[1], dict) else None
                # the job id is already the capability; the app links the take to the job it holds.
                self._error(422, MSG_KEY_REUSED, **({"job": held} if isinstance(held, str) and held else {}))
                return False
            if found[2] is not None and found[2] != fp:
                store.mark_form(route, key, "whole-body")  # saved before the identity binding: matched on the old hash
            self._send(found[0], json.dumps(found[1]).encode("utf-8"), "application/json; charset=utf-8",
                       {"Idempotent-Replayed": "true"})
            return False
        if not store.begin(route, key):
            self._drain(length if route == "uploads" else 0)
            self.close_connection = True
            self._error(503, jobs.QUEUE_FULL_MESSAGE)
            return False
        self._idem_fp = fp
        self._idem = (route, key)
        return True

    def _api_routes(self, route: str) -> None:
        method, parts = self.command, route.split("/")
        if self._take_refused(parts):  # prod-data.md "Object routes": every api/jobs/<id> and api/results/<id> route
            return
        if result_media.handle(self, method, route):  # the follower clip, with Range (coaching-moments.md)
            return
        if models_used.handle(self, method, route):  # models that ran, 2D skeleton (models-and-skeleton-data.md)
            return
        if mesh_files.handle(self, method, route):  # each person's SAM 3D Body mesh (result-redesign-additions.md R3)
            return
        if heat.handle(self, method, route):  # heat on the follower's own body (heat.md)
            return
        if mesh_stream_routes.handle(self, method, route):  # the follower's body while the job runs, owner only (mesh-stream.md)
            return
        if muse_fix_routes.handle(self, method, route):  # the corrected-pose picture and the blind referee (muse-fix-ui.md)
            return
        if take_ar_url.handle(self, method, route):  # owner-only short-lived signed link to a take file (take-ar.md)
            return
        if take_ar.handle(self, method, route):  # the rigged, animated take as GLB and USDZ for AR (take-ar.md)
            return
        if model_import.handle(self, method, route):  # imported character models (model-import.md)
            return
        if share_routes.handle(self, method, route):  # share links, api/shares and api/shared (share.md)
            return
        if progress_routes.handle(self, method, route):  # home programme and progress sheet (progress-sheet.md, TICKET-283)
            return
        if auth_routes.handle(self, method, route):  # opt-in sign-in and api/me (identity.md)
            return
        if profile_routes.handle(self, method, route):  # profile and avatars (profile.md)
            return
        if devices_routes.handle(self, method, route):  # signed-in devices (devices.md)
            return
        if modal_creds_routes.handle(self, method, route):  # TICKET-367: the user's own Modal credentials (AC-H16)
            return
        if export_data_routes.handle(self, method, route):  # download my data (export-data.md)
            return
        if my_reference_routes.handle(self, method, route):  # my reference (my-reference.md)
            return
        if reference_approval_routes.handle(self, method, route):  # a teacher approves a take as the reference (my-reference.md)
            return
        if notes_routes.handle(self, method, route):  # ask the trainer for a note (notes.md)
            return
        if source_routes.handle(self, method, route):  # source and licence credit of an entry or a take (source-credit.md)
            return
        if people_routes.handle(self, method, route):  # people choice and group mode (people.md)
            return
        if speech_routes.handle(self, method, route):  # spoken feedback lines (voice.md)
            return
        if catalog_search_routes.handle(self, method, route):  # search, filter, sort and page the catalog (catalog-search.md)
            return
        if judge_view.handle(self, method, route):  # the hero take of the judge view (judge-view.md)
            return
        if ghost.handle(self, method, route):  # the trainer's 2D ghost over the live preview (follow-ghost.md)
            return
        if impact.handle(self, method, route):  # the Impact page's persona takes (impact-page.md)
            return
        if architecture.handle(self, method, route):  # the architecture page's diagrams (impact-page.md)
            return
        if challenge_routes.handle(self, method, route):  # challenges and leaderboards (challenges.md)
            return
        if delete_routes.handle(self, method, route):  # delete this take (TICKET-159)
            return
        if teacher_routes.handle(self, method, route):  # the teacher page (teacher-dashboard.md)
            return
        if takes_on_routes.handle(self, method, route):  # takes on this movement (takes-on-movement.md)
            return
        if export_routes.handle(self, method, route):  # split-screen mp4 export (export-clip.md)
            return
        if narration_routes.handle(self, method, route):  # the trainer's spoken cues (narration.md)
            return
        if history_routes.handle(self, method, route):  # the student's history, api/me/history (history.md)
            return
        if notices_routes.handle(self, method, route):  # the third-party notices of this build (version-footer.md)
            return
        if policy_routes.handle(self, method, route):  # api/policy and api/legal/<name> (consent-and-age.md, legal-pages.md)
            return
        if method in ("GET", "HEAD"):
            if route == "health":
                return self._health()
            if route == "version":
                return self._json(200, health_probe.public_build(self.app.build) if is_prod() else self.app.build)
            if route == "config":
                return self._config()
            if route == "fixture-result" and not is_prod():  # a demo route: not served in prod
                return self._fixture()
            if route == "labels":  # an entry its owner keeps to "only me" is listed to that owner alone (identity.md)
                return self._json(200, {k: v for k, v in labels.all_labels(self.app.state).items() if auth.may_view_entry(self, k)})
            if len(parts) == 2 and parts[0] == "labels":
                found = labels.view(self.app.state, parts[1]) if auth.may_view_entry(self, parts[1]) else None
                return self._json(200, found) if found is not None else self._error(404, "No labels for this movement.")
            if len(parts) == 2 and parts[0] == "jobs":
                return self._job(parts[1])
            if len(parts) == 3 and parts[0] == "results":
                return self._result(parts[1], parts[2])
        elif method == "POST":
            if route == "client-log":
                return client_log.handle(self, self.app.client_rate)
            handler = {"uploads": self._upload, "trainer": self._trainer, "follow": self._follow}.get(route)
            if handler is not None:
                return handler()
        self._error(404, "Not found.")

    def _take_refused(self, parts: list[str]) -> bool:
        """Answer 404 (503 when the owner cannot be read) for a take of another account on any `jobs/<id>/...` or
        `results/<id>/...` route: the job record, results, meshes, skeleton, heat, models used, speech, exports (APP-C1,
        security audit B2). The delete route keeps its own rule (owner or creator token, 403)."""
        if len(parts) < 2 or parts[0] not in ("jobs", "results") or parts[2:] == ["delete"]:
            return False
        refused = take_access.refusal(self, parts[1])
        if refused and refused[0] == 404 and parts[0] == "jobs" and len(parts) == 2:
            refused = (404, MSG_NO_JOB)  # P-N1: the job record answers as for a job that does not exist
        if refused:
            self._error(*refused)
        return refused is not None

    # ----- read routes ------------------------------------------------------------------------
    def _health(self) -> None:
        app = self.app
        up, part6 = app.part6_probe.check(app.child)  # TICKET-188: a missed probe is tolerated while the last good one is fresh
        doc = {
            "ok": up,
            **({"failed": health_probe.failed_components(up)} if not up else {}),
            "part6": part6,
            "pins": app.lock.shas_short(),
            "queue": app.queue.counts(),
            "gpu": gpu_lock.gpu_status(),  # TICKET-289: an outside GPU holder shows beside an idle queue (no pids)
            "draining": app.queue.draining,
            "jobs": "run" if app.queue.owner else "standby",  # standby: a restart's new build, before the queue lock
            "gpu_jobs_today": app.quota.gpu_jobs_today(),
            "build": app.build,
            "fake": False,  # the test stand-in (tests/part7/fake_api.py) answers true; the web shows a banner for it
            "selfheal": selfheal.status(app.state),
            "mail_webhook": mail_webhook.status(),
            "mail_probe": mail_probe.status(app.state),  # off, waiting, ok or failing; the firm's watchdog reads it (mail-delivery.md)
        }
        if is_prod():  # APP-L2: a visitor gets the contract's health line; the detail stays for a direct local probe
            line = health_probe.public_doc(up, str(app.build.get("sha", "unknown")), app.queue.draining, bool(app.queue.owner))
            doc = {**doc, **line} if self._direct_local() else line
            doc.update(run_on.health_fields())  # byok-prod.md: who pays for compute and the idle TTL the store enforces
        self._json(200 if up else 503, doc)

    def _direct_local(self) -> bool:
        """A loopback peer that did not come through the gateway (no forwarded-address header): firm health.sh, the operator."""
        return (str(self.client_address[0]) in ("127.0.0.1", "::1", "::ffff:127.0.0.1")
                and not self.headers.get("Cf-Connecting-Ip") and not self.headers.get("X-Forwarded-For"))

    def _config(self) -> None:
        movement = None
        try:
            doc = json.loads(config.manifest_path().read_text(encoding="utf-8"))
            movement = {k: doc["movement"][k] for k in ("id", "name")}
        except (OSError, ValueError, KeyError, TypeError):
            pass
        self._json(
            200,
            {
                "base": self.app.base,
                "limits": {
                    "max_seconds": config.MAX_UPLOAD_SECONDS,
                    "max_clip_seconds": config.MAX_CLIP_SECONDS,
                    "min_clip_seconds": config.MIN_CLIP_SECONDS,
                    "max_bytes": config.upload_max_bytes(),
                    "recorder_bps": config.RECORDER_BPS,
                },
                "phrasing": self.app.phrasing,
                "signin_required": is_prod(),  # a take needs an account before recording: the challenge line says so
                "part5": p5_analyse.known_capabilities(),
                "movement": movement,
                "fixture_result": not is_prod() and _fixture_files()[0].is_file() and _fixture_files()[1].is_file(),
                "serverless": run_on.modal_configured(),  # TICKET-364: presence of Modal config only, never a value
                **run_on.config_fields(),  # serverless-compute.md: what the take screen says about Run on
            },
        )

    def _fixture(self) -> None:
        analysis, replay_file = _fixture_files()
        try:
            doc = {
                "analysis": json.loads(analysis.read_text(encoding="utf-8")),
                "replay": json.loads(replay_file.read_text(encoding="utf-8")),
            }
        except (OSError, ValueError):
            return self._error(404, "The example result is not available.")
        self._json(200, doc)

    def _job(self, job_id: str) -> None:
        job = self.app.queue.get(job_id) if jobs.JOB_ID_RE.match(job_id) else None
        if job is None:
            return self._error(404, MSG_NO_JOB)
        if job.get("kind") == "follow":  # the author line of a follower result (docs/specs/attribution.md)
            job = {**job, model_only.FIELD: model_only.kept(job), "attribution": attribution.for_take(self, job_id, job.get("entry_id"))}
            # narration only when there is one; owner-only routes are asked only when attribution.mine (AC-AU-12: the one viewer field)
            job["narration"] = narration_routes.has_narration(self, job.get("entry_id"))
            job["entry_gone"] = orphan_take.entry_gone(self, job.get("entry_id"))  # TICKET-331: the trainer deleted the movement
            if isinstance(job.get("reference"), dict):  # the id of the reference take and the teacher link are the owner's (ADR-0019)
                job["reference"] = my_reference.visible(job["reference"], job["attribution"].get("mine") is True)
            if job.get("status") in ("done", "failed"):  # the measured stage split (judge-take.md, TICKET-260)
                job["timing"] = stage_split.split(self.app.queue, job_id, job)
            job["mesh_stream"] = mesh_stream_routes.hint(self, job)  # null unless the caller owns this running job
        elif job.get("kind") == "group":  # each person's shown score, read now, so a result stored before it says why F
            job = group.with_shown(job, self.app.queue.job_dir(job_id))
        self._json(200, job)

    def _result(self, job_id: str, name: str) -> None:
        if not jobs.JOB_ID_RE.match(job_id) or name not in ("analysis.json", "replay.json"):
            return self._error(404, "Not found.")
        path = self.app.queue.job_dir(job_id) / "work" / "follower" / name
        if not path.is_file():
            return self._error(404, "This result is not available.")
        if name == "replay.json":
            raw, problems = replay.read_valid(path, self.app.lock, self.app.state)
            if raw is None:
                return self._error(422, "The replay file does not match its contract.", problems=problems)
            raw = replay.with_follower_unseen(raw, path.parent / "part2", (self.app.queue.get(job_id) or {}).get("person_id"))
        else:
            raw = result_paths.strip(path.read_bytes())
        if not model_only.kept(self.app.queue.get(job_id)):  # model-only-take.md: the web keys on video_kept === false
            raw = model_only.mark(raw)
        self._send(200, raw, "application/json; charset=utf-8")

    def _static(self, rest: str) -> None:
        web = self.app.web_dir.resolve()
        rel = "index.html" if rest == "" or rest.endswith("/") else rest
        target = (web / rel).resolve()
        if web not in target.parents or not target.is_file():
            return self._error(404, "Not found.")
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if target.suffix in (".js", ".mjs"):
            ctype = "text/javascript"
        body = target.read_bytes()
        if rel == "index.html":
            body = judge_view.page_with_profile(body)  # the judge URL opens in the submission profile (judge-view.md)
            p2_warmup.maybe_start(self.app, urlsplit(self.path).query)  # TICKET-260: prime the warm worker (p2-warmup.md)
        self._send(200, body, ctype + ("; charset=utf-8" if ctype.startswith("text/") else ""))

    # ----- uploads ----------------------------------------------------------------------------
    def _drain(self, length: int) -> None:
        left = min(length, DRAIN_LIMIT)
        while left > 0:
            chunk = self.rfile.read(min(CHUNK, left))
            if not chunk:
                break
            left -= len(chunk)

    def _reject_upload(self, status: int, message: str, length: int = 0) -> None:
        self._drain(length)
        self.close_connection = True
        self._error(status, message)

    def _upload(self) -> None:
        try:
            length = int(self.headers.get("Content-Length") or "")
        except ValueError:
            return self._reject_upload(411, "The upload has no length.")
        if is_prod() and auth.current_user(self) is None:  # app-surface R7: under BYOK every job needs a signed-in owner
            return self._reject_upload(401, MSG_UPLOAD_SIGN_IN, length)
        barred = consent_record.account_refusal(self, {})  # an account marked under age, from a clean browser too
        if barred is not None:
            return self._reject_upload(barred[0], barred[1], length)
        refused = consent_record.upload_refusal(self.headers)  # consent-and-age.md AC-CA4: nothing is kept before the step
        if refused is not None:
            return self._reject_upload(refused[0], refused[1], length)
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ctype not in VIDEO_TYPES:
            self._log_refusal("content_type", {"type": ctype, "announced": length, "received": 0}, "not a video type")
            return self._reject_upload(400, MSG_NOT_VIDEO, length)
        if length > config.upload_max_bytes():
            return self._reject_upload(413, too_large_message(), length)
        upload_id = uuid.uuid4().hex[:16]
        folder = self.app.uploads / upload_id
        folder.mkdir(parents=True)
        path = folder / f"upload.{VIDEO_TYPES[ctype]}"
        seen = {"upload": upload_id, "type": ctype, "announced": length, "received": 0}
        try:
            received = self._save(path, length)
            seen["received"] = received
            if received != length:
                return self._refuse_kept(folder, "short_read", seen, "the body ended before Content-Length")
            try:
                meta = media.probe(path)
            except ValueError as exc:
                return self._refuse_kept(folder, "probe_failed", seen, str(exc))
            if meta["duration_s"] > config.MAX_UPLOAD_SECONDS + DURATION_SLACK_S:
                return self._fail_upload(folder, 413, MSG_TOO_LONG_RAW)
            upload_owner.record(folder, auth.current_user(self))  # P-N1: only its uploader starts work from it
        except OSError:
            return self._fail_upload(folder, 500, "The upload could not be saved. Try again.")
        self._json(
            201,
            {"upload_id": upload_id, "duration_ms": meta["duration_ms"], "width": meta["width"], "height": meta["height"]},
        )

    def _save(self, path: Path, length: int) -> int:
        received = 0
        with path.open("wb") as out:
            while received < length:
                chunk = self.rfile.read(min(CHUNK, length - received))
                if not chunk:
                    break
                out.write(chunk)
                received += len(chunk)
        return received

    def _log_refusal(self, reason: str, seen: dict[str, Any], error: str) -> None:
        """One WARNING and one `ANOMALY upload_refused` line for a 400 MSG_NOT_VIDEO (TICKET-196)."""
        applog.log(
            f"upload refused ({reason}): content type {seen['type']!r}, announced {seen['announced']} bytes, "
            f"received {seen['received']} bytes, probe error: {error}", level=logging.WARNING,
        )
        applog.anomaly("upload_refused", detail=error, reason=reason, type=seen["type"] or None,
                       announced=seen["announced"], received=seen["received"], upload=seen.get("upload"))

    def _refuse_kept(self, folder: Path, reason: str, seen: dict[str, Any], error: str) -> None:
        self._log_refusal(reason, seen, error)
        if is_prod():  # a refused upload may be a person's video: prod keeps nothing the retention rules do not cover
            return self._fail_upload(folder, 400, MSG_NOT_VIDEO)
        refused_uploads.keep(folder, self.app.state)
        self._error(400, MSG_NOT_VIDEO)

    def _fail_upload(self, folder: Path, status: int, message: str) -> None:
        shutil.rmtree(folder, ignore_errors=True)
        self._error(status, message)

    # ----- job creation -----------------------------------------------------------------------
    def _enqueue(
        self, kind: str, fn: jobs.JobFn, entry_id: str | None = None, quota_kind: str | None = None, **record: Any,
    ) -> None:
        """Check room, count the job (as `quota_kind`, default `kind`), then queue `fn`; answers 202, 429 (sign in) or 503."""
        app, visitor = self.app, quota.counted_as(auth.current_user(self), self._visitor())
        counted = quota_kind or kind
        if not app.queue.has_room():
            return self._error(503, jobs.QUEUE_FULL_MESSAGE)
        people_job = record.get("people_job")
        paid = people_routes.claim_unit(app.queue, people_job)  # PROD-D3: the people job paid this take's GPU unit
        try:
            app.quota.reserve(counted, visitor, gpu_paid=paid)
        except quota.SignInRequired as exc:
            people_routes.unclaim_unit(app.queue, people_job, paid)
            return self._error(429, str(exc))
        except quota.ComputeStopped as exc:
            people_routes.unclaim_unit(app.queue, people_job, paid)
            return self._error(503, str(exc))
        try:
            job = app.queue.submit(kind, fn, entry_id=entry_id, **record)
        except (jobs.QueueFullError, jobs.DrainingError) as exc:
            app.quota.release(counted, visitor, gpu_paid=paid)
            people_routes.unclaim_unit(app.queue, people_job, paid)
            return self._error(503, str(exc))
        auth.attach_job(self, job)  # opt-in identity: records the owner when someone is signed in (identity.md)
        self._json(202, {"job": job["id"], **job})

    def _upload_for(self, doc: dict[str, Any]) -> Path | None:
        path = self.app.upload_file(str(doc.get("upload_id") or ""))
        if path is not None and not upload_owner.may_use(path.parent, auth.current_user(self)):
            path = None  # P-N1: another account's upload answers as a missing one
        if path is None:
            self._error(400, MSG_NO_UPLOAD)
        return path

    def _clip(self, doc: dict[str, Any], raw: Path) -> tuple[dict[str, int] | None, dict[str, Any]] | None:
        """The validated trim and the job-record fields for it; answers 400 or 413 itself and returns None."""
        try:
            duration_ms = media.probe(raw)["duration_ms"]
        except ValueError:
            self._error(400, MSG_NOT_VIDEO)
            return None
        trim = doc.get("trim")
        # TICKET-309: Continue pressed before the browser read the length is no selection: the whole clip
        if trim == UNSET_TRIM and not any(isinstance(v, bool) for v in trim.values()):
            applog.log(f"trim 0-0 ms on a {duration_ms} ms clip ({raw.suffix}) is no selection, the whole clip is used")
            trim = None
        if trim is None:
            if duration_ms > (config.MAX_CLIP_SECONDS + DURATION_SLACK_S) * 1000:
                self._error(413, MSG_TOO_LONG)
                return None
            return None, {"trim": None, "duration_ms": duration_ms}
        ints = isinstance(trim, dict) and all(
            isinstance(trim.get(k), int) and not isinstance(trim.get(k), bool) for k in ("start_ms", "end_ms")
        )
        if not ints:
            self._error(400, MSG_TRIM_SHAPE)
            return None
        start, end = trim["start_ms"], trim["end_ms"]
        if duration_ms < end <= duration_ms + TRIM_END_SLACK_MS:
            # The browser and ffprobe disagree on a MediaRecorder file's length; an end handle left at the end
            # of the clip is the end of the clip.
            applog.log(f"trim end {end} ms is past the probed {duration_ms} ms, cut at the end of the clip")
            end = duration_ms
        if not 0 <= start < end <= duration_ms:
            applog.log(f"trim rejected: {start}-{end} ms on a {duration_ms} ms clip ({raw.suffix})", level=logging.WARNING)
            self._error(400, MSG_TRIM_ORDER)
            return None
        if end - start < config.MIN_CLIP_SECONDS * 1000:
            applog.log(f"trim rejected as too short: {start}-{end} ms", level=logging.WARNING)
            self._error(400, MSG_TRIM_SHORT)
            return None
        if end - start > config.MAX_CLIP_SECONDS * 1000:
            applog.log(f"trim rejected as too long: {start}-{end} ms", level=logging.WARNING)
            self._error(400, MSG_TRIM_LONG)
            return None
        return {"start_ms": start, "end_ms": end}, {"trim": {"start_ms": start, "end_ms": end}, "duration_ms": end - start}

    def _clip_of(
        self, doc: dict[str, Any], raw: Path,
    ) -> tuple[dict[str, int] | None, dict[str, Any], people.PersonSel | None] | None:
        """Trim, job-record fields and chosen person of a trainer or follow request; answers its own errors.

        With `people_job` the people job already cut the clip, so its trim and duration are the record's.
        """
        ok, person = people_routes.selection(self, doc)
        if not ok:
            return None
        if person is None:
            clip = self._clip(doc, raw)
            return None if clip is None else (clip[0], dict(clip[1]), None)
        record = people_routes.clip_record(self, doc["people_job"])
        return record["trim"], {**record, "people_job": doc["people_job"], "person_id": person.id}, person

    def _consent(self, doc: dict[str, Any]) -> dict[str, Any] | None:
        """The consent job-record fields of a job request (consent-and-age.md), or None after answering 400 or 403."""
        refused = consent_record.refusal(doc, self)  # PM-R5: the account's kept under 13 answer too
        if refused is not None:
            self._error(*refused)
            return None
        return consent_record.job_fields(doc, auth.current_user(self))  # B2: the Meta tick is the signed-in account's

    def _muse_part1(self, consent: dict[str, Any]) -> bool:
        """docs/specs/muse-prod.md: Part 1 sends a trainer recording to Meta only with the person's tick and an open gate."""
        return consent_record.meta_allowed(consent) and muse_prod.admit("part1", auth.current_user(self), self.app.state) is None

    def _muse_follow(self, consent: dict[str, Any], entry_id: str) -> tuple[str, bool]:
        """(the phrasing of this take, whether its second opinion may send video), docs/specs/muse-prod.md AC-MP5: wording is counted
        on the gate; video needs the follower's tick and, for a trainer's own recording, the trainer's tick too."""
        user, state = auth.current_user(self), self.app.state
        if self.app.phrasing != "live" or muse_prod.admit("phrasing", user, state) is not None:
            return "template", False
        video = (consent_record.meta_allowed(consent) and muse_prod.trainer_video_allowed(self.app.state, entry_id)
                 and muse_prod.admit("opinion", user, state) is None)
        return "live", video

    def _trainer(self) -> None:
        doc = self._body_json()
        if doc is None:
            return
        consent = self._consent(doc)
        if consent is None:
            return
        user = auth.current_user(self)
        refused = trainer_publish.refusal(doc, user)  # #415: a 13 to 17 answer signs in to record a movement
        if refused is not None:
            return self._error(*refused)
        run_choice, run_owner, bad = run_on.byok_job(doc, self.app.state, user)  # byok-prod.md: prod runs on the owner's Modal
        if bad:
            return self._error(400, bad)
        name, category = str(doc.get("name") or "").strip(), str(doc.get("category") or "")
        if not 1 <= len(name) <= NAME_MAX:
            return self._error(400, MSG_NAME)
        if category not in CATEGORIES:
            return self._error(400, MSG_CATEGORY)
        entry_labels = None
        if doc.get("labels") is not None:
            try:
                entry_labels = labels.validate(doc["labels"])
            except labels.LabelsError as exc:
                return self._error(400, str(exc))
        raw = self._upload_for(doc)
        if raw is None:
            return
        clip = self._clip_of(doc, raw)
        if clip is None:
            return
        trim, record, person = clip
        record.update(consent)
        mirrored = mirrored_take.take(doc, record)  # TICKET-310: kept on the job record, Part 3 flips left and right
        record["upload_id"] = str(doc.get("upload_id"))  # D1: the take delete and Delete my data drop the raw upload too
        state = self.app.state
        floor = doc.get("floor_work") is True  # the owner's checkbox (floor-work.md)
        on_entry = labels.entry_saver(state, entry_labels, floor)
        # the signed-in person owns the new entry (identity.md); private in prod unless the upload opts in (prod-data.md)
        publish = trainer_publish.choice(doc, self.headers)  # go-live-readiness.md "GPC": Sec-GPC keeps it private
        on_entry = auth.on_entry(self, on_entry, publish=publish, deferred=True)  # R4: public after captions
        fn = processor.trainer_job(
            raw, name=name, category=category, catalog=self.app.child.catalog_dir, lock=self.app.lock,
            backend=self.app.backend, trim=trim, on_entry=on_entry, person=person, review_state=state,
            mirrored=mirrored, floor_work=floor, part1_allowed=self._muse_part1(consent),
        )
        fn = run_on.bind(fn, run_choice, state, run_owner)
        record.update(run_on.record(run_choice, run_owner))
        self._enqueue("trainer", fn, _resume=resume.trainer_spec(doc, name, category, person, publish), **record)

    def _follow(self) -> None:
        doc = self._body_json()
        if doc is None:
            return
        consent = self._consent(doc)  # consent-and-age.md: before anything of the take is read
        if consent is None:
            return
        entry_id = str(doc.get("entry_id") or "")
        raw = self._upload_for(doc)
        if raw is None:
            return
        take_labels = None
        if doc.get("labels") is not None:
            try:
                take_labels = labels.validate(doc["labels"])
            except labels.LabelsError as exc:
                return self._error(400, str(exc))
        practice = self._practice(doc)  # mode and section (practice-and-modes.md); answers 400 itself
        if practice is None:
            return
        practice = {**practice, **consent}  # kept on the job record with the take (consent-and-age.md AC-CA2)
        run_user = auth.current_user(self)  # TICKET-367: their own Modal credentials may offer serverless
        run_choice, bad = run_on.parse(doc, self.app.state, run_user)  # TICKET-364: named apart from the reference `choice` below
        if bad:
            return self._error(400, bad)
        clip = self._clip_of(doc, raw)
        if clip is None:
            return
        trim, record, person = clip
        record.update(practice)
        mirrored = mirrored_take.take(doc, record)  # TICKET-310
        record["upload_id"] = str(doc.get("upload_id"))  # so a deleted take can drop its raw upload (delete_routes.py)
        lang = doc.get("lang")  # the language the person picked (lang-picker.js); kept in job.json
        if isinstance(lang, str) and LANG_RE.match(lang):
            record["lang"] = lang
        ref = challenge_routes.follow_ref(self, doc, entry_id)  # optional challenge_id (challenges.md); answers 400 or 409
        if ref is None:
            return
        record.update(ref)
        if take_labels is not None:
            record["labels"] = take_labels  # the follower's take labels live in the job record (recorder.md)
        visible = ID_RE.match(entry_id) and auth.may_view_entry(self, entry_id)  # R3: unpublished or "only me" stays hidden
        manifest = self.app.child.get_entry(entry_id) if visible else None
        if manifest is None:
            if visible and self.app.child.health() is None:  # AC-OT14: the catalog is down, so nothing says the movement is gone
                return self._error(503, MSG_CATALOG_DOWN)
            return self._error(404, MSG_NO_ENTRY)
        self._entry_mode(record, entry_id, manifest)  # TICKET-311: the entry's kind decides the scoring profile
        expected = self._expected_clip(entry_id, manifest)
        if expected is None:
            return
        if record.get("section"):
            try:
                expected = sections.cut(expected, record["section"])
            except sections.SectionError as exc:
                return self._error(400, str(exc))
        grouped = my_reference.is_group(self.app.queue, record)  # a person of a real group video is scored against the teacher
        choice = my_reference.choose(self.app.state, auth.current_user(self), entry_id, expected, record.get("section"), grouped)  # ADR-0019
        expected = choice.expected
        record["reference"] = choice.record  # the result always says which reference was used
        skeleton = manifest.get("skeleton")
        visibility = self.app.child.get_entry_file(entry_id, str(skeleton)) if skeleton and not choice.own else None  # the teacher's visibility describes the teacher's body, not the reference's
        # Private mode for this take (private-mode.md): Part 7 keeps the feedback wording local and sends no trainer
        # video to Part 5. Part 2 still sends frames to SAM 3.1 when a Meta key exists. True/False in the request
        # wins over SIMON7_PRIVATE; absent leaves it to the env.
        private = doc["private"] if isinstance(doc.get("private"), bool) and not is_prod() else None  # never in prod (B1)
        if private:
            record["private"] = True
        take_phrasing, send_video = self._muse_follow(consent, entry_id)
        video_name = manifest.get("video_uri") if send_video and not private_mode.enabled(job_flag=private) else None
        trainer_video = self.app.child.get_entry_file(entry_id, str(video_name)) if video_name and not choice.own else None  # Part 5's second opinion compares with the teacher's video
        model_choice = model_only.requested(doc)  # "Use my 3D model instead of video" (model-only-take.md)
        if model_choice:
            record[model_only.FIELD] = False
        model_only.stamp(self, record)  # "Show only my 3D model": the owner's choice travels with the take (model-default.md AC-MD12)
        drop_source = (model_only.source_dropper(self.app.queue, self.app.uploads, str(doc.get("upload_id")), record.get("people_job"))
                       if model_choice else None)
        fn = processor.follow_job(
            raw, expected=expected, entry_id=entry_id, phrasing=take_phrasing, lock=self.app.lock,
            backend=self.app.backend, trim=trim, person=person, visibility=visibility,
            mode=record.get("mode"), lang=record.get("lang"), trainer_video=trainer_video, private=private,
            video_kept=not model_choice, drop_source=drop_source, mirrored=mirrored,
            floor_work=labels.floor_work(self.app.state, entry_id),
        )
        run_owner = run_on.owner_for(run_choice, self.app.state, run_user)
        fn = run_on.bind(fn, run_choice, self.app.state, run_owner)  # TICKET-364: the take's "Run on" choice is the job's first Part 2 route
        record.update(run_on.record(run_choice, run_owner))
        self._enqueue("follow", fn, entry_id=entry_id, _resume=resume.follow_spec(doc, person), **record)

    def _entry_mode(self, record: dict[str, Any], entry_id: str, manifest: dict[str, Any]) -> None:
        """Replace a posted mode with the entry's own (rehab tag, else category); a mismatch is logged (modes.py)."""
        if "mode" in record:
            tags = (labels.get(self.app.state, entry_id) or {}).get("tags")
            record["mode"] = modes.decide(record["mode"], modes.of_entry(manifest, tags), entry_id)

    def _practice(self, doc: dict[str, Any]) -> dict[str, Any] | None:
        """The optional `mode` and `section` of a request as job-record fields; answers 400 itself, returns None."""
        try:
            mode, section = modes.parse(doc.get("mode")), sections.parse(doc.get("section"))
        except (modes.ModeError, sections.SectionError) as exc:
            self._error(400, str(exc))
            return None
        return {**({"mode": mode} if mode else {}), **({"section": section} if section else {})}

    def _expected_clip(self, entry_id: str, manifest: dict[str, Any]) -> bytes | None:
        """The entry's animation, else its skeleton when Part 5 accepts it; answers 409 or 503 itself."""
        child = self.app.child
        name = manifest.get("animation") or manifest.get("skeleton")
        if not name:
            self._error(409, MSG_NO_ANIMATION)
            return None
        data = child.get_entry_file(entry_id, str(name))
        if data is None:
            self._error(503, MSG_CATALOG_DOWN)
            return None
        if not manifest.get("animation") and not self._skeleton_accepted(data):
            self._error(409, MSG_NO_ANIMATION)
            return None
        if not manifest.get("animation"):
            return data
        converted = animation_format.to_v1(data)  # TICKET-110: sample entries are simon.animation/1
        if converted != data and not self._skeleton_accepted(converted):  # Part 5's doctor decides before expected.json
            self._error(409, MSG_BAD_ANIMATION)
            return None
        return converted

    def _skeleton_accepted(self, data: bytes) -> bool:
        """Part 5's doctor decides whether a skeleton-only entry can be the expected clip."""
        return p5_analyse.accepts_expected(data, self.app.state / "tmp", self.app.lock)


def _fixture_files() -> tuple[Path, Path]:
    base = config.REPO_ROOT / "fixtures" / "input"
    return (base / "analysis-1.2.0.json", base / "replay.json")


def build_app(
    state: Path | str,
    base_path: str,
    *,
    child: Any,
    lock: modules.Modules | None = None,
    web_dir: Path | None = None,
    phrasing: str | None = None,
    start_queue: bool = True,
) -> App:
    """Create the state folders, the queue and the quota around `child`."""
    prod_check.verify_start()  # prod: a bad configuration stops here, before any state is made
    root = Path(state)
    root.mkdir(parents=True, exist_ok=True)
    app = App(
        state=root, base=config.normalize_base_path(base_path), child=child,
        queue=jobs.JobQueue(root, start=start_queue), quota=quota.Quota(root), lock=lock or modules.load(),
        web_dir=web_dir or config.WEB_DIR, phrasing=phrasing or phrasing_from_env(),
        build=buildinfo.collect(config.REPO_ROOT),
    )
    app.uploads.mkdir(parents=True, exist_ok=True)
    selfheal.configure(root)
    _clean_uploads(app.uploads)
    refused_uploads.sweep(app.state)
    muse_prod.bind(app)
    app.queue.on_cleanup = lambda: _sweep(app)  # with each job sweep, so a long-running server also frees them
    auth_routes.TAKE_REMOVER = delete_routes.remove_for_account  # account delete removes the account's takes (identity.md)
    app.idempotency.prune(config.RETENTION_DAYS)
    app.queue.resume(lambda record: resume.rebuild(app, record))  # jobs queued at the last stop run again
    return app


def _sweep(app: App) -> None:
    """The periodic sweep: old uploads, and history copies past their retention (history.md)."""
    _clean_uploads(app.uploads)
    _clear_part1_env(app.lock)  # at a takeover too; frees the key of a run that outlived its server (AC-H5c)
    if serverless_route.enabled():
        serverless_route.delete_due(app.state)  # what a crash or a failed delete left at Modal
    try:
        p1_keyframes.sweep(app.state)  # a clip or a key a killed Part 1 run left behind (muse-prod.md AC-MP9)
    except OSError as exc:
        applog.log(f"part 1 copy: sweep failed: {applog.cause(exc)}", level=logging.WARNING)
    try:
        refused_uploads.sweep(app.state)
    except OSError as exc:  # kept evidence must not stop the job sweep
        applog.log(f"refused uploads: sweep failed: {applog.cause(exc)}", level=logging.WARNING)
    try:
        entry_check.sweep(app.state, app.child.catalog_dir, app.queue)  # saved videos still match their recordings
    except Exception as exc:  # the content check must not stop the job sweep
        applog.log(f"entry check: sweep failed: {applog.cause(exc)}", level=logging.WARNING)
    try:
        ghost.sweep(app.state, app.child.catalog_dir, app.queue)  # the trainer's ghost outlives its job folder (follow-ghost.md)
    except Exception as exc:  # the ghost copy must not stop the job sweep
        applog.log(f"ghost: sweep failed: {applog.cause(exc)}", level=logging.WARNING)
    try:
        history_store.sweep(app.state)
    except Exception as exc:  # a history fault must not stop the job sweep
        applog.log(f"history: sweep failed: {applog.cause(exc)}", level=logging.WARNING)
    try:
        if identity.db_path(app.state).is_file():  # expired sessions and sign-in challenges, and accounts idle for 180 days
            auth.identity(app).prune(app.state)
    except Exception as exc:
        applog.log(f"auth: prune failed: {applog.cause(exc)}", level=logging.WARNING)
    try:
        delete_routes.sweep_entries(app)  # prod-data.md: movements past their retention, access rows of gone movements
    except Exception as exc:  # the movement sweep must not stop the job sweep
        applog.log(f"entries: sweep failed: {applog.cause(exc)}", level=logging.WARNING)
    _sweep_records(app)


def _sweep_records(app: App) -> None:
    """The small stores' retention (prod-data.md "Retention"): idle boards (D10), expired share links (D12), day files
    of the quota (D11), reference tombstones (D6) and log lines past 14 days (D3). One fault never stops the others."""
    steps: list[tuple[str, Callable[[], Any]]] = [
        ("boards", lambda: challenges.sweep(app.state)),
        ("quota", lambda: quota.prune(app.quota.dir)),
        ("reference tombstones", lambda: reference_approval.sweep_tombstones(app.state)),
        ("logs", lambda: applog.sweep(app.state)),
    ]
    if identity.db_path(app.state).is_file():
        steps.append(("share links", lambda: share.sweep(auth.identity(app))))
        steps.append(("identity checkpoint", lambda: auth.identity(app).checkpoint_due
                      and auth.identity(app).checkpoint(identity.CHECKPOINT_RETRY_MS)))  # R2: until a delete's WAL is gone
    for what, step in steps:
        try:
            step()
        except Exception as exc:  # noqa: BLE001  a retention fault is logged and the next sweep tries again
            applog.log(f"{what}: sweep failed: {applog.cause(exc)}", level=logging.WARNING)


def _clean_uploads(uploads: Path) -> None:
    cutoff = time.time() - config.RETENTION_DAYS * 86400
    for child in uploads.iterdir():
        if child.is_dir() and child.stat().st_mtime < cutoff:
            shutil.rmtree(child, ignore_errors=True)


LISTEN_BACKLOG = 128  # go-live-readiness.md "Races": the stdlib's 5 reset connections of a burst of 20


class _Server(ThreadingHTTPServer):
    request_queue_size = LISTEN_BACKLOG


def make_server(app: App, host: str = config.DEV_HOST, port: int = 0) -> ThreadingHTTPServer:
    server = _Server((host, port), make_handler(app))
    server.daemon_threads = True
    return server


def _drain_then_stop(queue: jobs.JobQueue, server: ThreadingHTTPServer) -> None:
    """SIGTERM: refuse new jobs, let the running ones finish (up to SIMON7_DRAIN_MAX_S), then stop serving."""
    try:
        applog.log(f"SIGTERM: draining, at most {config.drain_max_s():.0f} s")
        deadline = time.monotonic() + config.drain_max_s()  # one max for the take jobs and the model jobs
        model_import.begin_drain()  # TICKET-306: no model job starts here any more
        cut = queue.drain(config.drain_max_s())
        own_clients.stop_all(queue.root.parent, parent=os.getpid())  # BYOK-M6: a cut take's own-route Modal client ends here
        cut += model_import.drain(deadline)
        cut += mail.drain(max(5.0, deadline - time.monotonic()))  # a sign-in mail in flight, retry included, is not cut in half
        if not cut:
            selfheal.record("restart_drain")  # drained clean; a cut-off job marks it through ANOMALY drain_cut_off
    finally:
        server.shutdown()


def _clear_part1_env(lock: modules.Modules, state: Path | str | None = None) -> None:
    """AC-H5c: the serving tree's `.env`, and in prod (where the key sits in `part1/<pin>`, not in the read-only release) every
    copy's. A tree that cannot be cleared never stops the server."""
    # AC-H5c: each call has its own try, so a read-only release tree (EROFS, nothing to clear) never skips the prod sweep
    calls = [lambda: keys.drop_part1_env(lock.path("1"))]
    if state is not None:
        calls.append(lambda: p1_keyframes.sweep(state))
    for call in calls:
        try:
            call()
        except OSError as exc:
            if exc.errno != errno.EROFS:
                applog.log(f"serve: Part 1 .env not cleared: {type(exc).__name__}", level=logging.WARNING)


def cli_serve(
    host: str, port: int, base_path: str, state: Path | str, follow_url: str | None = None
) -> int:
    """`part7 serve`: start the Part 6 child, then serve until SIGINT or SIGTERM."""
    from part7 import nodump

    if is_prod():  # go-live-readiness.md "No dump": before any key or token is read (BYOK audit R1); staging and dev
        nodump.forbid()  # keep their /proc scans of the app (review R1)
    from part7 import p2_worker
    from part7 import part6_supervisor
    from part7.parts import p2_pose, p6_catalog

    if host not in ("127.0.0.1", "localhost", "::1"):
        print("serve: the app listens on 127.0.0.1 only", file=sys.stderr)
        return 2
    try:
        prod_check.verify_start()  # APP-C2: before the Part 6 child, the log and the state folder
    except RuntimeError as exc:  # ProdModeError: names the settings, never a value
        print(f"serve: {exc}", file=sys.stderr)
        return 2
    base = config.normalize_base_path(base_path)
    log_path = applog.setup(state)  # first: the queue logs jobs a restart interrupted while it loads
    applog.log(f"serve start: pid {os.getpid()} on {host}:{port}{base}, state {Path(state)}, log {log_path}")
    _clear_part1_env(modules.load(), state)
    if follow_url is None and config.staging_route() is None:
        follow_url = f"http://{host}:{port}{base}#/follow/{{id}}"
    child = p6_catalog.Child(
        catalog_dir=Path(state) / "catalog", base_path=base, follow_url=follow_url, state=Path(state)
    )
    child.start()
    if child.health() is None:
        applog.log("serve: Part 6 did not start; see part6.log in the state folder", level=logging.ERROR)
        child.stop()
        return 1
    app = build_app(state, base, child=child)
    modal_creds.start_sweeper(app.state)  # byok-prod.md BYOK-H2: expired credentials go at start-up, then every 15 minutes
    applog.log(f"serve ready: build {app.build.get('short')}, pins {app.lock.shas_short()}")
    p5_analyse.warm(app.lock)  # the Part 5 probes run off the request path; api/config reads the cached answer
    # The one warm Part 2 worker for `run`, when enabled and the pin has it. A standby (the new build of a restart,
    # TICKET-240) starts it once it takes the queue lock: its sockets live in the shared state folder.
    applog.log(p2_pose.warm_workers_note(state))  # GPU guard: resident workers on staging only
    app.queue.when_owner(lambda: p2_pose.start_workers(state, app.lock))
    server = make_server(app, host, port)
    beat = heartbeat.Heartbeat(app.queue, state).start()  # one line a minute; stops with the server
    supervisor = part6_supervisor.Part6Supervisor(child, state, paused=lambda: app.queue.draining).start()
    applog.log("mail webhook: " + json.dumps(mail_webhook.status()))  # on, or off and why: the secret file is the operator's
    prober = mail_probe.Prober(state).start()  # off, and logged as off, unless the operator set SIMON7_MAIL_PROBE_TO
    signal.signal(signal.SIGTERM, lambda *_: threading.Thread(
        target=_drain_then_stop, args=(app.queue, server), daemon=True).start())
    print(f"serving http://{host}:{server.server_address[1]}{base} (state {Path(state)})", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        beat.stop()
        prober.stop()
        supervisor.stop()
        app.queue.close()
        p2_worker.stop_pool()
        p2_worker.stop_track_pool()  # the warm SAM 3.1 tracker, when it ran (TICKET-117)
        child.stop()
    return 0
