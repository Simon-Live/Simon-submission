"""The Simon Part 7 HTTP server: API, catalog proxy and static `web/` (app.md "Server").

stdlib `ThreadingHTTPServer` on 127.0.0.1. Paths are relative to the base path; a request outside it is 404.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import mimetypes
import os
from pathlib import Path
import re
import shutil
import signal
import sys
import threading
import time
from typing import Any
from urllib.parse import urlsplit
import uuid

from part7 import (
    animation_format, applog, attribution, auth, auth_routes, buildinfo, challenge_routes, client_log, config, delete_routes, entry_check, export_data_routes, export_routes, heartbeat,
    health_probe, history_routes, history_store, idempotency, identity, jobs, judge_view, labels, media, mesh_files, mesh_stream_routes, model_import, model_only, models_used, modes, modules, muse_fix_routes, narration_routes,
    devices_routes, my_reference, my_reference_routes, notes_routes, people, people_routes, private_mode, profile_routes, processor, proxy, quota, reference_approval_routes, refused_uploads, replay, result_media, resume, sections, selfheal, share_routes, speech_routes,
    source_routes, progress_routes, teacher_routes,
    takes_on_routes,
    architecture, impact,
    group,  # one-letter.md L5: a group job's people carry `shown` at read time
)
from part7 import take_ar, take_ar_url
from part7 import heat  # TICKET-274: heat on the follower's own body
from part7 import orphan_take  # TICKET-331: a follow take whose movement was deleted
from part7 import gpu_lock  # TICKET-289: api/health gpu block
from part7 import ghost, stage_split  # TICKET-264 follow the ghost, TICKET-260 stage split
from part7 import p2_warmup
from part7 import notices_routes  # TICKET-326: the footer's Licences link
from part7 import mirrored as mirrored_take  # TICKET-310: the person says an upload is a mirrored video
from part7.parts import p5_analyse

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
MSG_TOO_LARGE = "The file is too large (95 MB at most)."
MSG_NO_ENTRY = "This movement is not in the catalog."
MSG_NO_ANIMATION = "This movement has no animation to follow."
MSG_BAD_ANIMATION = "This movement's animation is not in a form the comparison accepts."
MSG_KEY_REUSED = "This Idempotency-Key was already used for a different request."
MSG_NO_UPLOAD = "The upload was not found. Pick the video again."
MSG_NAME = "Give the movement a name of 80 characters at most."
MSG_CATEGORY = "Pick exercise or dance."
MSG_CATALOG_DOWN = "The catalog is not answering. Try again in a moment."


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


def phrasing_from_env() -> str:
    return "template" if os.environ.get("SIMON7_PHRASING", "live") == "template" else "live"


SLOW_REQUEST_S = 2.0
DRAIN_ROUTES = frozenset({"uploads", "trainer", "follow", "people", "group", "models"})  # POSTs that start work (models: TICKET-306)
SLOW_UPLOAD_S = 20.0  # a POST api/uploads or api/models carries the visitor's file: transfer time is part of it
SLOW_MEDIA_S = 10.0  # media GETs stream; the limit applies to the time to the first byte (headers out)
MEDIA_SUFFIXES = (".mp4", ".webm", ".mov")


def make_handler(app: App) -> type[BaseHTTPRequestHandler]:
    class Handler(_Handler):
        pass

    Handler.app = app
    return Handler


class _Handler(BaseHTTPRequestHandler):
    _body_cache: bytes | None = None  # a JSON body read early by the Idempotency-Key check
    app: App
    _expected_busy = False  # set per request by a route whose 5xx is busy by design (speech_routes.py)
    server_version = "Simon7"
    sys_version = ""

    # ----- plumbing -------------------------------------------------------------------------
    def log_message(self, fmt: str, *args: Any) -> None:
        line = re.sub(r"(/api/shared/)[^/\s?\"]+", r"\1<token>", fmt % args)  # TICKET-233: a share token is never logged
        sys.stderr.write(f"{self.log_date_time_string()} {line}\n")

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
                self.app.idempotency.put(idem[0], idem[1], status, obj, getattr(self, "_idem_fp", None))
            except OSError:
                pass
        self._send(status, json.dumps(obj).encode("utf-8"), "application/json; charset=utf-8")

    def _error(self, status: int, message: str, **extra: Any) -> None:
        if status >= 500:
            applog.log(f"{self.command} {urlsplit(self.path).path} answered {status}: {message}", level=logging.WARNING)
        self._json(status, {"ok": False, "error": message, "message": message, **extra})

    def _rest(self) -> str | None:
        """The path below the base path, or None when the request is outside it."""
        path = urlsplit(self.path).path
        base = self.app.base
        if path == base.rstrip("/") and base != "/":
            return None
        return path[len(base):] if path.startswith(base) else None

    def _visitor(self) -> str | None:
        return self.headers.get("Cf-Connecting-Ip") or None

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
        fields: dict[str, Any] = {"method": self.command, "path": rest if rest is not None else full,
                                  "status": self._status, "seconds": seconds}
        length = self.headers.get("Content-Length", "") if self.headers is not None else ""
        if length.isdigit():
            fields["bytes"] = int(length)
        limit, on_first_byte = self._slow_limit(rest)
        if (first_byte_s if on_first_byte and first_byte_s is not None else seconds) > limit:
            applog.anomaly("slow_request", **fields)
        if self._status >= 500 and self._expected_busy:  # a designed "try again shortly": one INFO line, no anomaly
            applog.log(f"{self.command} {fields['path']} answered {self._status} (busy by design)")
        elif self._status >= 500:
            applog.anomaly("http_5xx", **fields)

    def _timed_route(self) -> None:
        try:
            self._route()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            # the client closed the connection mid-answer: not a server fault, so no ERROR and no traceback (TICKET-204)
            applog.log(f"client closed the connection during {self.command} {urlsplit(self.path).path}")
            self.close_connection = True
        except Exception as exc:  # a handler bug: logged with the request, the visitor gets a plain 500
            applog.log(f"{self.command} {urlsplit(self.path).path} crashed: {applog.cause(exc)}", level=logging.ERROR)
            selfheal.note_crash(self.command, self._rest() or urlsplit(self.path).path, exc)  # names the type in the 5xx finding
            if self._answered:  # headers (and maybe part of a body) already went out: end the connection instead
                self.close_connection = True
                return
            try:
                self._error(500, "Something went wrong on the server. Try again.")
            except OSError:
                pass

    def _route(self) -> None:
        rest = self._rest()
        if rest is None:
            self._error(404, "Not found.")
            return
        if rest == "catalog" or rest.startswith("catalog/"):
            self._catalog()
        elif rest.startswith("api/"):
            self._api(rest[4:])
        elif self.command in ("GET", "HEAD"):
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
        if method in ("GET", "HEAD"):
            if route == "health":
                return self._health()
            if route == "version":
                return self._json(200, self.app.build)
            if route == "config":
                return self._config()
            if route == "fixture-result":
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

    # ----- read routes ------------------------------------------------------------------------
    def _health(self) -> None:
        app = self.app
        up, part6 = app.part6_probe.check(app.child)  # TICKET-188: a missed probe is tolerated while the last good one is fresh
        doc = {
            "ok": up,
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
        }
        self._json(200 if up else 503, doc)

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
                    "max_bytes": config.MAX_UPLOAD_BYTES,
                    "recorder_bps": config.RECORDER_BPS,
                },
                "phrasing": self.app.phrasing,
                "part5": p5_analyse.known_capabilities(),
                "movement": movement,
                "fixture_result": _fixture_files()[0].is_file() and _fixture_files()[1].is_file(),
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
            return self._error(404, "This job was not found.")
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
        else:
            raw = path.read_bytes()
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
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        try:
            length = int(self.headers.get("Content-Length") or "")
        except ValueError:
            return self._reject_upload(411, "The upload has no length.")
        if ctype not in VIDEO_TYPES:
            self._log_refusal("content_type", {"type": ctype, "announced": length, "received": 0}, "not a video type")
            return self._reject_upload(400, MSG_NOT_VIDEO, length)
        if length > config.MAX_UPLOAD_BYTES:
            return self._reject_upload(413, MSG_TOO_LARGE, length)
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
        refused_uploads.keep(folder, self.app.state)
        self._error(400, MSG_NOT_VIDEO)

    def _fail_upload(self, folder: Path, status: int, message: str) -> None:
        shutil.rmtree(folder, ignore_errors=True)
        self._error(status, message)

    # ----- job creation -----------------------------------------------------------------------
    def _enqueue(
        self, kind: str, fn: jobs.JobFn, entry_id: str | None = None, quota_kind: str | None = None, **record: Any,
    ) -> None:
        """Check room and quota (of `quota_kind`, default `kind`), then queue `fn`; answers 202, 429 or 503."""
        app, visitor = self.app, self._visitor()
        counted = quota_kind or kind
        if not app.queue.has_room():
            return self._error(503, jobs.QUEUE_FULL_MESSAGE)
        try:
            app.quota.reserve(counted, visitor)
        except quota.VisitorQuotaError as exc:
            return self._error(429, str(exc))
        except quota.DailyCapError as exc:
            return self._error(503, str(exc))
        try:
            job = app.queue.submit(kind, fn, entry_id=entry_id, **record)
        except (jobs.QueueFullError, jobs.DrainingError) as exc:
            app.quota.release(counted, visitor)
            return self._error(503, str(exc))
        auth.attach_job(self, job)  # opt-in identity: records the owner when someone is signed in (identity.md)
        self._json(202, {"job": job["id"], **job})

    def _upload_for(self, doc: dict[str, Any]) -> Path | None:
        path = self.app.upload_file(str(doc.get("upload_id") or ""))
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

    def _trainer(self) -> None:
        doc = self._body_json()
        if doc is None:
            return
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
        mirrored = mirrored_take.take(doc, record)  # TICKET-310: kept on the job record, Part 3 flips left and right
        state = self.app.state
        floor = doc.get("floor_work") is True  # the owner's checkbox (floor-work.md)
        on_entry = labels.entry_saver(state, entry_labels, floor)
        on_entry = auth.on_entry(self, on_entry)  # the signed-in person owns the new entry (identity.md)
        fn = processor.trainer_job(
            raw, name=name, category=category, catalog=self.app.child.catalog_dir, lock=self.app.lock,
            backend=self.app.backend, trim=trim, on_entry=on_entry, person=person, review_state=state,
            mirrored=mirrored, floor_work=floor,
        )
        self._enqueue("trainer", fn, _resume=resume.trainer_spec(doc, name, category, person), **record)

    def _follow(self) -> None:
        doc = self._body_json()
        if doc is None:
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
        manifest = self.app.child.get_entry(entry_id) if ID_RE.match(entry_id) else None
        if manifest is None:
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
        private = doc["private"] if isinstance(doc.get("private"), bool) else None
        if private:
            record["private"] = True
        video_name = (manifest.get("video_uri")
                      if self.app.phrasing == "live" and not private_mode.enabled(job_flag=private) else None)
        trainer_video = self.app.child.get_entry_file(entry_id, str(video_name)) if video_name and not choice.own else None  # Part 5's second opinion compares with the teacher's video
        model_choice = model_only.requested(doc)  # "Use my 3D model instead of video" (model-only-take.md)
        if model_choice:
            record[model_only.FIELD] = False
        drop_source = (model_only.source_dropper(self.app.queue, self.app.uploads, str(doc.get("upload_id")), record.get("people_job"))
                       if model_choice else None)
        fn = processor.follow_job(
            raw, expected=expected, entry_id=entry_id, phrasing=self.app.phrasing, lock=self.app.lock,
            backend=self.app.backend, trim=trim, person=person, visibility=visibility,
            mode=record.get("mode"), lang=record.get("lang"), trainer_video=trainer_video, private=private,
            video_kept=not model_choice, drop_source=drop_source, mirrored=mirrored,
            floor_work=labels.floor_work(self.app.state, entry_id),
        )
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
    app.queue.on_cleanup = lambda: _sweep(app)  # with each job sweep, so a long-running server also frees them
    auth_routes.TAKE_REMOVER = delete_routes.remove_for_account  # account delete removes the account's takes (identity.md)
    app.idempotency.prune(config.RETENTION_DAYS)
    app.queue.resume(lambda record: resume.rebuild(app, record))  # jobs queued at the last stop run again
    return app


def _sweep(app: App) -> None:
    """The periodic sweep: old uploads, and history copies past their retention (history.md)."""
    _clean_uploads(app.uploads)
    try:
        refused_uploads.sweep(app.state)
    except OSError as exc:  # kept evidence must not stop the job sweep
        applog.log(f"refused uploads: sweep failed: {applog.cause(exc)}", level=logging.WARNING)
    try:
        entry_check.sweep(app.state, app.child.catalog_dir, app.queue)  # saved videos still match their recordings
    except Exception as exc:  # the content check must not stop the job sweep
        applog.log(f"entry check: sweep failed: {applog.cause(exc)}", level=logging.WARNING)
    try:
        history_store.sweep(app.state)
    except Exception as exc:  # a history fault must not stop the job sweep
        applog.log(f"history: sweep failed: {applog.cause(exc)}", level=logging.WARNING)
    try:
        if identity.db_path(app.state).is_file():  # expired sessions and sign-in challenges, and accounts idle for 180 days
            auth.identity(app).prune(app.state)
    except Exception as exc:
        applog.log(f"auth: prune failed: {applog.cause(exc)}", level=logging.WARNING)


def _clean_uploads(uploads: Path) -> None:
    cutoff = time.time() - config.RETENTION_DAYS * 86400
    for child in uploads.iterdir():
        if child.is_dir() and child.stat().st_mtime < cutoff:
            shutil.rmtree(child, ignore_errors=True)


def make_server(app: App, host: str = config.DEV_HOST, port: int = 0) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), make_handler(app))
    server.daemon_threads = True
    return server


def _drain_then_stop(queue: jobs.JobQueue, server: ThreadingHTTPServer) -> None:
    """SIGTERM: refuse new jobs, let the running ones finish (up to SIMON7_DRAIN_MAX_S), then stop serving."""
    try:
        applog.log(f"SIGTERM: draining, at most {config.drain_max_s():.0f} s")
        deadline = time.monotonic() + config.drain_max_s()  # one max for the take jobs and the model jobs
        model_import.begin_drain()  # TICKET-306: no model job starts here any more
        cut = queue.drain(config.drain_max_s())
        cut += model_import.drain(deadline)
        if not cut:
            selfheal.record("restart_drain")  # drained clean; a cut-off job marks it through ANOMALY drain_cut_off
    finally:
        server.shutdown()


def cli_serve(
    host: str, port: int, base_path: str, state: Path | str, follow_url: str | None = None
) -> int:
    """`part7 serve`: start the Part 6 child, then serve until SIGINT or SIGTERM."""
    from part7 import p2_worker
    from part7.parts import p2_pose, p6_catalog

    if host not in ("127.0.0.1", "localhost", "::1"):
        print("serve: the app listens on 127.0.0.1 only", file=sys.stderr)
        return 2
    base = config.normalize_base_path(base_path)
    log_path = applog.setup(state)  # first: the queue logs jobs a restart interrupted while it loads
    applog.log(f"serve start: pid {os.getpid()} on {host}:{port}{base}, state {Path(state)}, log {log_path}")
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
    applog.log(f"serve ready: build {app.build.get('short')}, pins {app.lock.shas_short()}")
    p5_analyse.warm(app.lock)  # the Part 5 probes run off the request path; api/config reads the cached answer
    # The one warm Part 2 worker for `run`, when enabled and the pin has it. A standby (the new build of a restart,
    # TICKET-240) starts it once it takes the queue lock: its sockets live in the shared state folder.
    applog.log(p2_pose.warm_workers_note(state))  # GPU guard: resident workers on staging only
    app.queue.when_owner(lambda: p2_pose.start_workers(state, app.lock))
    server = make_server(app, host, port)
    beat = heartbeat.Heartbeat(app.queue, state).start()  # one line a minute; stops with the server
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
        app.queue.close()
        p2_worker.stop_pool()
        p2_worker.stop_track_pool()  # the warm SAM 3.1 tracker, when it ran (TICKET-117)
        child.stop()
    return 0
