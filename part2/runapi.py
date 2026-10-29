"""Request logic of the run API: uploads, limits, content sniffing, job creation, capabilities, error mapping.

Spec: docs/specs/run-app.md (Uploads and limits, route table; AC-A04 to AC-A07, AC-A10). The HTTP layer is
part2/server.py; the queue is part2/jobs.py. Standard library only, plus Pillow (a project dependency) to open
photos and ffprobe (a subprocess with a timeout and no shell) to read videos.

    caps = Capabilities()                          # what can run here, probed in the job interpreter
    doc = capabilities_doc(caps.raw(), samples(root), Limits())
    created = create_job(queue, doc, samples(root), Limits(), headers, rfile)   # {"id", "state"} or ApiError

Nothing here trusts a file name or a Content-Type: a photo is what Pillow opens as JPEG or PNG, a video is what
ffprobe reads as mp4, mov or webm with a video stream. Errors are ApiError(status, code) with a plain sentence;
no message holds a path, a class name or a trace.
"""
from __future__ import annotations

import json
import mmap
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from email.message import Message
from email.parser import HeaderParser
from pathlib import Path

from part2 import jobs

ROOT = Path(__file__).resolve().parent.parent
TEST_CAP_HEADER = "X-Part2-Test-Max-Body"   # lowers the body cap for one request (verify tests); never raises it
VIDEO_FORMATS = {"mov,mp4,m4a,3gp,3g2,mj2": ".mp4", "matroska,webm": ".webm"}
JPEG_MAGIC, PNG_MAGIC = b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n"
FIELDS = ("mode", "backend", "tracker", "sample")
FIELD_MAX = 200
MAX_PARTS = 16
BY_ORDER = ("api-sam31", "local-sam31")      # a visitor never names a paid or key-gated tracker
NAMED_TRACKERS = ("local-open", "bytetrack")
TRACKER_NAMES = ("api-sam31", "bytetrack", "local-open", "local-sam31")
# Titles name the clip, not the mode, so no radio's name contains another's ("One person", "Class").
SAMPLES = {"single": ("Stretch sample", "single"), "class": ("Yoga sample", "class")}

MESSAGES = {
    "too_large": "The file is too large. Videos can be up to 200 MB and photos up to 20 MB.",
    "unsupported": "This file is not a video or photo the app can read.",
    "too_long": "Videos can be at most 60 seconds long.",
    "no_frames": "No frames could be read from this video.",
    "photo_too_big": "Photos can be at most 8000 pixels on the longest side.",
    "queue_full": "The queue is full. Try again in a few minutes.",
    "length_required": "The upload needs a Content-Length header.",
    "bad_length": "The Content-Length header must be a whole number of bytes.",
    "bad_form": "The upload could not be read. Send it as a form with a file or a sample.",
    "short_body": "The upload ended early. Try again.",
    "bad_mode": "Choose a mode: single for one person, or class.",
    "no_input": "Choose a file or a sample to run.",
    "both_inputs": "Send a file or a sample, not both.",
    "unknown_sample": "That sample does not exist.",
    "unknown_backend": "Unknown backend. Choose gpu or cpu.",
    "backend_unavailable": "The {name} backend is not available here.",
    "no_backend": "No backend is available here right now.",
    "unknown_tracker": "Unknown tracker. Choose Automatic, local-open or bytetrack.",
    "tracker_by_order": "The {name} tracker is chosen by the app, not by name. Choose Automatic.",
    "tracker_unavailable": "The {name} tracker is not available here.",
    "no_ffprobe": "Videos cannot be read on this server right now.",
}
BACKEND_LABELS = {"gpu": "GPU (SAM 3D Body)", "cpu": "CPU (RTMPose and a lifter)"}
BACKEND_REASONS = {"gpu": "no GPU backend is set up on this server",
                   "cpu": "the CPU backend is not installed on this server"}
TRACKER_LABELS = {"automatic": "Automatic", "local-open": "local-open (SAM 2.1)", "bytetrack": "bytetrack"}
TRACKER_REASONS = {"no_key": "no key on this server", "budget": "spend cap reached",
                   "missing": "not installed on this server", "other": "cannot run on this server"}
UNCHECKED = "the server could not check it"


class ApiError(Exception):
    def __init__(self, status: int, code: str, **fmt):
        self.status, self.code = status, code
        self.message = MESSAGES[code].format(**fmt)
        super().__init__(self.message)


@dataclass(frozen=True)
class Limits:
    video_bytes: int = 200_000_000
    photo_bytes: int = 20_000_000
    form_slack: int = 64 * 1024              # multipart headers and the small fields around the file
    video_s: float = 60.0
    photo_px: int = 8000
    fps: int = jobs.FPS
    max_frames: int = 600

    @property
    def body_bytes(self) -> int:
        return self.video_bytes + self.form_slack

    def public(self, queue: int) -> dict:
        return {"video_mb": self.video_bytes / 1e6, "video_s": self.video_s, "photo_mb": self.photo_bytes / 1e6,
                "photo_px": self.photo_px, "fps": self.fps, "max_frames": self.max_frames, "queue": queue}


# ---- the request body ------------------------------------------------------------------------------------

def body_cap(headers, limits: Limits) -> int:
    raw = (headers.get(TEST_CAP_HEADER) or "").strip()
    return min(limits.body_bytes, int(raw)) if re.fullmatch(r"[0-9]{1,15}", raw) else limits.body_bytes


def body_length(headers, cap: int) -> int:
    """The declared body length; 411 without one (or chunked), 400 unless digits, 413 over the cap (nothing read)."""
    if headers.get("Transfer-Encoding"):
        raise ApiError(411, "length_required")
    values = headers.get_all("Content-Length") if hasattr(headers, "get_all") else [headers.get("Content-Length")]
    values = [v for v in (values or []) if v is not None]
    if not values:
        raise ApiError(411, "length_required")
    raw = {v.strip() for v in values}
    if len(raw) != 1 or not re.fullmatch(r"[0-9]{1,15}", next(iter(raw))):
        raise ApiError(400, "bad_length")
    n = int(next(iter(raw)))
    if n > cap:
        raise ApiError(413, "too_large")
    return n


def form_boundary(content_type: str) -> str:
    msg = Message()
    msg["content-type"] = content_type or ""
    boundary = msg.get_param("boundary") if msg.get_content_type() == "multipart/form-data" else None
    if not isinstance(boundary, str) or not re.fullmatch(r"[0-9A-Za-z'()+_,./:=? -]{1,70}", boundary):
        raise ApiError(400, "bad_form")
    return boundary


def receive(rfile, length: int, dest: Path, chunk: int = 1 << 20) -> None:
    """Copy exactly `length` body bytes to dest; 400 when the client stops early or stalls past the socket timeout."""
    left = length
    with dest.open("wb") as f:
        while left:
            try:
                block = rfile.read(min(chunk, left))
            except OSError:
                block = b""
            if not block:
                raise ApiError(400, "short_body")
            f.write(block)
            left -= len(block)


@dataclass
class Form:
    fields: dict
    file: tuple | None                       # (start, end) of the file's bytes in the body, or None


def _part_headers(raw: bytes) -> tuple[str | None, str | None]:
    msg = HeaderParser().parsestr(raw.decode("utf-8", "replace") + "\r\n\r\n")
    if msg.get_content_disposition() != "form-data":
        raise ApiError(400, "bad_form")
    name = msg.get_param("name", header="content-disposition")
    filename = msg.get_param("filename", header="content-disposition")
    return (name if isinstance(name, str) else None), (filename if isinstance(filename, str) else None)


def parse_multipart(path: Path, boundary: str) -> Form:
    """Read a multipart/form-data body from disk without loading it: the small text fields and the span of the
    `file` part. Unknown fields are ignored; a repeated field is an error."""
    delim = b"--" + boundary.encode("ascii")
    fields, span = {}, None
    with path.open("rb") as f:
        try:
            mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
        except ValueError:                   # an empty body
            raise ApiError(400, "bad_form") from None
        with mm:
            pos = mm.find(delim)
            if pos < 0:
                raise ApiError(400, "bad_form")
            for _ in range(MAX_PARTS + 1):
                pos += len(delim)
                if mm[pos:pos + 2] == b"--":
                    return Form(fields, span)
                if mm[pos:pos + 2] != b"\r\n":
                    raise ApiError(400, "bad_form")
                head_end = mm.find(b"\r\n\r\n", pos + 2, pos + 2 + 8192)
                if head_end < 0:
                    raise ApiError(400, "bad_form")
                name, filename = _part_headers(mm[pos + 2:head_end])
                start = head_end + 4
                end = mm.find(b"\r\n" + delim, start)
                if end < 0:
                    raise ApiError(400, "bad_form")
                if name in fields or (name == "file" and span is not None):
                    raise ApiError(400, "bad_form")
                if name == "file":
                    span = (start, end) if end > start or filename else None
                elif name in FIELDS:
                    if end - start > FIELD_MAX:
                        raise ApiError(400, "bad_form")
                    fields[name] = mm[start:end].decode("utf-8", "replace").strip()
                pos = end + 2
    raise ApiError(400, "bad_form")


def extract(body: Path, span: tuple, dest: Path, chunk: int = 1 << 20) -> int:
    start, end = span
    with body.open("rb") as src, dest.open("wb") as out:
        src.seek(start)
        left = end - start
        while left:
            block = src.read(min(chunk, left))
            if not block:
                break
            out.write(block)
            left -= len(block)
    return end - start


# ---- sniffing ----------------------------------------------------------------------------------------------

def is_photo(path: Path) -> bool:
    with path.open("rb") as f:
        head = f.read(8)
    return head.startswith(JPEG_MAGIC) or head.startswith(PNG_MAGIC)


def intake_photo(src: Path, frames_dir: Path, limits: Limits) -> Path:
    """Open the photo with Pillow (JPEG or PNG only), turn it upright from its EXIF orientation and save it as
    the one frame of the job, without its metadata."""
    from PIL import Image, ImageOps

    frames_dir.mkdir(parents=True, exist_ok=True)
    dest = frames_dir / "000000.jpg"
    try:
        with Image.open(src) as im:
            if im.format not in ("JPEG", "PNG"):
                raise ApiError(415, "unsupported")
            if max(im.size) > limits.photo_px:
                raise ApiError(422, "photo_too_big")
            im.load()
            upright = ImageOps.exif_transpose(im).convert("RGB")
        upright.save(dest, "JPEG", quality=95)
    except Image.DecompressionBombError:
        raise ApiError(422, "photo_too_big") from None
    except (OSError, SyntaxError, ValueError):
        raise ApiError(415, "unsupported") from None
    return dest


def _number(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def probe_video(path: Path, limits: Limits, timeout_s: float = 60.0) -> str:
    """The extension for a video ffprobe reads as mp4, mov or webm with frames; 415, or 422 when too long."""
    exe = shutil.which("ffprobe")
    if exe is None:
        raise ApiError(503, "no_ffprobe")
    cmd = [exe, "-v", "error", "-count_packets", "-print_format", "json", "-show_entries",
           "format=format_name,duration:stream=codec_type,duration,nb_read_packets", str(path)]
    try:
        done = subprocess.run(cmd, capture_output=True, timeout=timeout_s, check=False)
        doc = json.loads(done.stdout or b"{}") if done.returncode == 0 else {}
    except (OSError, subprocess.TimeoutExpired, ValueError):
        doc = {}
    fmt = (doc.get("format") or {}).get("format_name")
    video = [s for s in doc.get("streams") or [] if isinstance(s, dict) and s.get("codec_type") == "video"]
    if fmt not in VIDEO_FORMATS or not video:
        raise ApiError(415, "unsupported")
    duration = _number(doc["format"].get("duration")) or max(_number(s.get("duration")) for s in video)
    if not _number(video[0].get("nb_read_packets")) or duration <= 0:
        raise ApiError(422, "no_frames")
    if duration > limits.video_s:
        raise ApiError(422, "too_long")
    return VIDEO_FORMATS[fmt]


# ---- samples and capabilities ---------------------------------------------------------------------------------

def samples(root: Path = ROOT) -> dict:
    """Sample inputs with stored frames: {id: {id, title, mode, frames, dir}} (dir never leaves the server)."""
    out = {}
    for sid, (title, mode) in SAMPLES.items():
        d = Path(root) / "fixtures" / "input" / sid / "frames"
        try:
            n = len(json.loads((d / "frames.json").read_text())["frames"])
        except (OSError, ValueError, KeyError, TypeError):
            continue
        out[sid] = {"id": sid, "title": title, "mode": mode, "frames": n, "dir": d}
    return out


PROBE = r"""
import json
from part2 import backends, trackers

def code(why):
    if why in ("no_key", "budget"):
        return why
    return "missing" if str(why).startswith("missing") else "other"

out = {"backends": {}, "trackers": {}, "automatic": {"ok": False}}
for name in ("gpu", "cpu"):
    try:
        ok = bool(backends.get(name).available()[0])
    except Exception:
        ok = False
    out["backends"][name] = {"ok": ok}
for name in ("local-open", "bytetrack"):
    try:
        ok, why = trackers.get(name).available()
        out["trackers"][name] = {"ok": bool(ok), "why": "" if ok else code(why)}
    except Exception:
        out["trackers"][name] = {"ok": False, "why": "other"}
try:
    t, skipped = trackers.resolve("bulk")
    out["automatic"] = {"ok": True, "runs": t.name}
except Exception:
    pass
print(json.dumps(out))
"""


class Capabilities:
    """The probe's answer, cached: the first call waits for it, a stale answer is served while it refreshes."""

    def __init__(self, probe=None, python: str | None = None, settings: jobs.Settings | None = None,
                 root: Path = ROOT, ttl_s: float = 300.0, timeout_s: float = 180.0):
        self._probe = probe or self._run
        self.python, self.settings, self.root = python, settings or jobs.Settings(), Path(root)
        self.ttl_s, self.timeout_s = ttl_s, timeout_s
        self._value, self._at, self._refreshing = None, 0.0, False
        self._lock = threading.Lock()

    def _run(self) -> dict:
        done = subprocess.run([self.python or jobs.job_python(), "-c", PROBE], cwd=self.root,
                              env=jobs.run_env(self.settings, root=self.root), capture_output=True, text=True,
                              timeout=self.timeout_s, check=False)
        lines = done.stdout.strip().splitlines()
        return json.loads(lines[-1]) if done.returncode == 0 and lines else {}

    def _safe(self) -> dict:
        try:
            value = self._probe()
            return value if isinstance(value, dict) else {}
        except Exception:  # an unreadable probe means nothing is known to be available
            return {}

    def _refresh(self) -> None:
        value = self._safe()
        with self._lock:
            self._value, self._at, self._refreshing = value, time.monotonic(), False

    def raw(self) -> dict:
        with self._lock:
            value, fresh = self._value, time.monotonic() - self._at < self.ttl_s
            if value is not None and not fresh and not self._refreshing:
                self._refreshing = True
                threading.Thread(target=self._refresh, daemon=True).start()
        if value is not None:
            return value
        with self._lock:
            if self._value is None:
                self._value, self._at = self._safe(), time.monotonic()
            return self._value

    def warm(self) -> None:
        threading.Thread(target=self.raw, daemon=True).start()


def capabilities_doc(raw: dict, sample_table: dict, limits: Limits, queue: int = 5) -> dict:
    """The api/capabilities answer, built only from booleans and codes the probe returned (never its text)."""
    def entry(kind: dict | None, key: str) -> dict:
        got = (kind or {}).get(key) if isinstance(kind, dict) else None
        return got if isinstance(got, dict) else {}

    checked = bool(raw)
    backends = []
    for name in ("gpu", "cpu"):
        ok = entry(raw.get("backends"), name).get("ok") is True
        b = {"name": name, "label": BACKEND_LABELS[name], "available": ok,
             "reason": "" if ok else (BACKEND_REASONS[name] if checked else UNCHECKED)}
        if name == "cpu":
            b["approximate"] = not jobs.CPU_3D_BAR_PASSED
        backends.append(b)
    auto = raw.get("automatic") if isinstance(raw.get("automatic"), dict) else {}
    runs = auto.get("runs") if auto.get("runs") in TRACKER_NAMES else None
    trackers = [{"name": "automatic", "label": TRACKER_LABELS["automatic"], "available": bool(auto.get("ok") and runs),
                 "reason": "" if auto.get("ok") and runs else (TRACKER_REASONS["other"] if checked else UNCHECKED),
                 "runs": runs}]
    for name in NAMED_TRACKERS:
        e = entry(raw.get("trackers"), name)
        ok = e.get("ok") is True
        trackers.append({"name": name, "label": TRACKER_LABELS[name], "available": ok,
                         "reason": "" if ok else (TRACKER_REASONS.get(e.get("why"), TRACKER_REASONS["other"])
                                                  if checked else UNCHECKED)})
    return {"backends": backends, "trackers": trackers,
            "samples": [{k: s[k] for k in ("id", "title", "mode", "frames")} for s in sample_table.values()],
            "limits": limits.public(queue)}


# ---- creating a job --------------------------------------------------------------------------------------------

def choose(fields: dict, caps: dict, sample_table: dict) -> dict:
    """Mode, backend, tracker and sample from the form, checked against what can run here."""
    mode = fields.get("mode", "").lower()
    if mode not in ("single", "class"):
        raise ApiError(400, "bad_mode")
    tracker = fields.get("tracker", "").lower()
    if tracker in BY_ORDER:
        raise ApiError(400, "tracker_by_order", name=tracker)
    if tracker not in ("", "automatic", *NAMED_TRACKERS):
        raise ApiError(400, "unknown_tracker")
    backend = fields.get("backend", "").lower()
    ready = [b["name"] for b in caps["backends"] if b["available"]]
    if not backend:
        if not ready:
            raise ApiError(503, "no_backend")
        backend = ready[0]
    elif backend not in BACKEND_LABELS:
        raise ApiError(400, "unknown_backend")
    elif backend not in ready:
        raise ApiError(400, "backend_unavailable", name=backend)
    chosen = None
    if mode == "class":
        key = tracker or "automatic"
        t = next(t for t in caps["trackers"] if t["name"] == key)
        if not t["available"]:
            raise ApiError(400, "tracker_unavailable", name=t["label"].split(" ")[0])
        chosen = None if key == "automatic" else key
    sample = fields.get("sample", "")
    if sample and sample not in sample_table:
        raise ApiError(400, "unknown_sample")
    return {"mode": mode, "backend": backend, "tracker": chosen, "sample": sample or None}


def attach_input(job, body: Path, form: Form, choice: dict, sample_table: dict, limits: Limits) -> None:
    """Point the job at its input: a sample's frames in place, the upright photo, or the sniffed video."""
    if choice["sample"] and form.file:
        raise ApiError(400, "both_inputs")
    if choice["sample"]:
        job.kind, job.sample, job.input = "sample", choice["sample"], str(sample_table[choice["sample"]]["dir"])
        return
    if not form.file:
        raise ApiError(400, "no_input")
    upload = job.dir / "upload.bin"
    size = extract(body, form.file, upload)
    body.unlink()
    if size == 0:
        raise ApiError(415, "unsupported")
    if is_photo(upload):
        if size > limits.photo_bytes:
            raise ApiError(413, "too_large")
        intake_photo(upload, job.dir / "photo", limits)
        upload.unlink()
        job.kind, job.input = "photo", str(job.dir / "photo")
        return
    if size > limits.video_bytes:
        raise ApiError(413, "too_large")
    ext = probe_video(upload, limits)
    dest = job.dir / ("input" + ext)
    upload.rename(dest)
    job.kind, job.input = "video", str(dest)


def create_job(queue: jobs.JobQueue, caps: dict, sample_table: dict, limits: Limits, headers, rfile) -> dict:
    """POST api/jobs: 202 {id, state} on success, else ApiError. Size, queue and form checks run before a byte
    of the body is read; a refused upload leaves nothing on disk."""
    length = body_length(headers, body_cap(headers, limits))
    if queue.pending() >= queue.settings.max_pending:
        raise ApiError(429, "queue_full")
    boundary = form_boundary(headers.get("Content-Type", ""))
    job = queue.new_job(mode="single", kind="sample")
    try:
        body = job.dir / "upload.part"
        receive(rfile, length, body)
        form = parse_multipart(body, boundary)
        choice = choose(form.fields, caps, sample_table)
        job.mode, job.backend, job.tracker = choice["mode"], choice["backend"], choice["tracker"]
        attach_input(job, body, form, choice, sample_table, limits)
        body.unlink(missing_ok=True)
        queue.submit(job)
    except jobs.QueueFull:
        queue.discard(job)
        raise ApiError(429, "queue_full") from None
    except BaseException:
        queue.discard(job)
        raise
    return {"id": job.id, "state": job.state}
