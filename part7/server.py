"""The Simon Part 7 HTTP server: API, catalog proxy and static `web/` (app.md "Server").

stdlib `ThreadingHTTPServer` on 127.0.0.1. Paths are relative to the base path; a request outside it is 404.
"""

from __future__ import annotations

from dataclasses import dataclass
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

from part7 import applog, config, jobs, labels, media, people, people_routes, pins, processor, proxy, quota, replay
from part7.parts import p5_analyse

ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
UPLOAD_ID_RE = re.compile(r"^[0-9a-f]{16}$")
VIDEO_TYPES = {"video/mp4": "mp4", "video/webm": "webm", "video/quicktime": "mov"}
CATEGORIES = ("exercise", "dance")
NAME_MAX = 80
DRAIN_LIMIT = 300_000_000  # an oversized upload is read and dropped up to here so the browser sees the 413
DURATION_SLACK_S = 0.5  # MediaRecorder stops a little after its 60 s timer
TRIM_END_SLACK_MS = 1500  # a trim end this far past the probed length is cut at the end (the recorder clock runs long)
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
    lock: pins.Lock
    web_dir: Path = config.WEB_DIR
    phrasing: str = "live"
    backend: str = "gpu"

    @property
    def uploads(self) -> Path:
        return self.state / "uploads"

    def upload_file(self, upload_id: str) -> Path | None:
        if not UPLOAD_ID_RE.match(upload_id):
            return None
        found = sorted((self.uploads / upload_id).glob("upload.*")) if (self.uploads / upload_id).is_dir() else []
        return found[0] if found else None


def phrasing_from_env() -> str:
    return "template" if os.environ.get("SIMON7_PHRASING", "live") == "template" else "live"


def make_handler(app: App) -> type[BaseHTTPRequestHandler]:
    class Handler(_Handler):
        pass

    Handler.app = app
    return Handler


class _Handler(BaseHTTPRequestHandler):
    app: App
    server_version = "Simon7"
    sys_version = ""

    # ----- plumbing -------------------------------------------------------------------------
    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write(f"{self.log_date_time_string()} {fmt % args}\n")

    def _send(self, status: int, body: bytes, ctype: str, extra: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status: int, obj: Any) -> None:
        self._send(status, json.dumps(obj).encode("utf-8"), "application/json; charset=utf-8")

    def _error(self, status: int, message: str, **extra: Any) -> None:
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
        length = int(self.headers.get("Content-Length") or 0)
        if length > JSON_BODY_MAX:
            self._error(413, "The request is too large.")
            return None
        try:
            doc = json.loads(self.rfile.read(length) or b"null")
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

    def _dispatch(self) -> None:
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
        method, parts = self.command, route.split("/")
        if people_routes.handle(self, method, route):  # people choice and group mode (people.md)
            return
        if method in ("GET", "HEAD"):
            if route == "health":
                return self._health()
            if route == "config":
                return self._config()
            if route == "fixture-result":
                return self._fixture()
            if route == "labels":
                return self._json(200, labels.all_labels(self.app.state))
            if len(parts) == 2 and parts[0] == "labels":
                found = labels.get(self.app.state, parts[1])
                return self._json(200, found) if found is not None else self._error(404, "No labels for this movement.")
            if len(parts) == 2 and parts[0] == "jobs":
                return self._job(parts[1])
            if len(parts) == 3 and parts[0] == "results":
                return self._result(parts[1], parts[2])
        elif method == "POST":
            handler = {"uploads": self._upload, "trainer": self._trainer, "follow": self._follow}.get(route)
            if handler is not None:
                return handler()
        self._error(404, "Not found.")

    # ----- read routes ------------------------------------------------------------------------
    def _health(self) -> None:
        app = self.app
        part6 = app.child.health()
        doc = {
            "ok": part6 is not None,
            "part6": {"ok": part6 is not None, "entries": len(app.child.list_entries()) if part6 else 0},
            "pins": app.lock.pins_short(),
            "queue": app.queue.counts(),
            "gpu_jobs_today": app.quota.gpu_jobs_today(),
        }
        self._json(200 if part6 is not None else 503, doc)

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
        self._send(200, target.read_bytes(), ctype + ("; charset=utf-8" if ctype.startswith("text/") else ""))

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
            return self._reject_upload(400, MSG_NOT_VIDEO, length)
        if length > config.MAX_UPLOAD_BYTES:
            return self._reject_upload(413, MSG_TOO_LARGE, length)
        upload_id = uuid.uuid4().hex[:16]
        folder = self.app.uploads / upload_id
        folder.mkdir(parents=True)
        path = folder / f"upload.{VIDEO_TYPES[ctype]}"
        try:
            received = self._save(path, length)
            if received != length:
                return self._fail_upload(folder, 400, MSG_NOT_VIDEO)
            try:
                meta = media.probe(path)
            except ValueError:
                return self._fail_upload(folder, 400, MSG_NOT_VIDEO)
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
        except jobs.QueueFullError:
            app.quota.release(counted, visitor)
            return self._error(503, jobs.QUEUE_FULL_MESSAGE)
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
        state = self.app.state
        on_entry = (lambda entry_id: labels.save(state, entry_id, entry_labels)) if entry_labels is not None else None
        fn = processor.trainer_job(
            raw, name=name, category=category, catalog=self.app.child.catalog_dir, lock=self.app.lock,
            backend=self.app.backend, trim=trim, on_entry=on_entry, person=person,
        )
        self._enqueue("trainer", fn, **record)

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
        clip = self._clip_of(doc, raw)
        if clip is None:
            return
        trim, record, person = clip
        if take_labels is not None:
            record["labels"] = take_labels  # the follower's take labels live in the job record (recorder.md)
        manifest = self.app.child.get_entry(entry_id) if ID_RE.match(entry_id) else None
        if manifest is None:
            return self._error(404, MSG_NO_ENTRY)
        expected = self._expected_clip(entry_id, manifest)
        if expected is None:
            return
        skeleton = manifest.get("skeleton")
        visibility = self.app.child.get_entry_file(entry_id, str(skeleton)) if skeleton else None
        fn = processor.follow_job(
            raw, expected=expected, entry_id=entry_id, phrasing=self.app.phrasing, lock=self.app.lock,
            backend=self.app.backend, trim=trim, person=person, visibility=visibility,
        )
        self._enqueue("follow", fn, entry_id=entry_id, **record)

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
        return data

    def _skeleton_accepted(self, data: bytes) -> bool:
        """Part 5's doctor decides whether a skeleton-only entry can be the expected clip."""
        scratch = self.app.state / "tmp" / uuid.uuid4().hex[:12]
        scratch.mkdir(parents=True)
        try:
            (scratch / "expected.json").write_bytes(data)
            step = p5_analyse.doctor(scratch / "expected.json", scratch, consumer="part5", lock=self.app.lock)
            return step["exit"] == 0
        finally:
            shutil.rmtree(scratch, ignore_errors=True)


def _fixture_files() -> tuple[Path, Path]:
    base = config.REPO_ROOT / "fixtures" / "input"
    return (base / "analysis-1.2.0.json", base / "replay.json")


def build_app(
    state: Path | str,
    base_path: str,
    *,
    child: Any,
    lock: pins.Lock | None = None,
    web_dir: Path | None = None,
    phrasing: str | None = None,
    start_queue: bool = True,
) -> App:
    """Create the state folders, the queue and the quota around `child`."""
    root = Path(state)
    root.mkdir(parents=True, exist_ok=True)
    app = App(
        state=root, base=config.normalize_base_path(base_path), child=child,
        queue=jobs.JobQueue(root, start=start_queue), quota=quota.Quota(root), lock=lock or pins.load(),
        web_dir=web_dir or config.WEB_DIR, phrasing=phrasing or phrasing_from_env(),
    )
    app.uploads.mkdir(parents=True, exist_ok=True)
    _clean_uploads(app.uploads)
    return app


def _clean_uploads(uploads: Path) -> None:
    cutoff = time.time() - config.RETENTION_DAYS * 86400
    for child in uploads.iterdir():
        if child.is_dir() and child.stat().st_mtime < cutoff:
            shutil.rmtree(child, ignore_errors=True)


def make_server(app: App, host: str = config.DEV_HOST, port: int = 0) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), make_handler(app))
    server.daemon_threads = True
    return server


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
    if follow_url is None and not os.environ.get("STAGING_BASE_PATH"):
        follow_url = f"http://{host}:{port}{base}#/follow/{{id}}"
    child = p6_catalog.Child(
        catalog_dir=Path(state) / "catalog", base_path=base, follow_url=follow_url, state=Path(state)
    )
    child.start()
    if child.health() is None:
        print("serve: Part 6 did not start; see part6.log in the state folder", file=sys.stderr)
        child.stop()
        return 1
    app = build_app(state, base, child=child)
    applog.setup(state)
    p2_pose.start_workers(app.queue.workers, state, app.lock)  # warm Part 2 workers when the pin has them
    server = make_server(app, host, port)
    signal.signal(signal.SIGTERM, lambda *_: threading.Thread(target=server.shutdown, daemon=True).start())
    print(f"serving http://{host}:{server.server_address[1]}{base} (state {Path(state)})", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        app.queue.close()
        p2_worker.stop_pool()
        child.stop()
    return 0
