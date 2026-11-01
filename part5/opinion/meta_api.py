"""The Meta Model API for the second opinion (TICKET-045, docs/specs/second-opinion.md).

Muse Spark 1.3 on `https://api.meta.ai/v1`: clips go up through the Files API, the request is a Responses call with
`input_file` items, and `/responses/input_tokens` counts the input before anything is spent; Part 1's
`keyframe_finder/meta_client.py` uses the same calls on the teacher's clip.

The key is the file `~/.config/firm/operator-keys/MODEL_API_KEY` (`PART5_META_KEY_FILE` for tests). It is read at
the call, stripped, and used for the `Authorization` header and nothing else: never printed, logged, written or put in
a reason. Live calls need the key file AND live mode (the phrasing switches, `muse_spark.live_on`).

Spend: the total cap is checked before anything is uploaded; the input is then counted, and the call is refused when
its estimate (the counted input plus the full output allowance at Part 1's list rates) passes `PART5_META_CALL_MAX_USD`
(default 0.50) or would take the ledger past `PART5_META_SPEND_CAP_USD` (default 5.00). A value of either variable that
is not a finite amount from 0 up keeps the default and logs a warning. The ledger `~/.simon/meta_usage.jsonl`
(`PART5_META_USAGE_FILE`) is opened and locked (flock) before the cap check and held until the call is recorded, so two
processes cannot both pass the cap; it gets one line per call: UTC time, model, HTTP status, token counts and USD,
never the key or text. A call that failed with no answer from the API (a timeout, a connection error, an unreadable
body) may still have been billed, so its line carries the pre-call estimate with `estimated: true`; a call the API
answered with an error status is recorded at $0.
"""
import json
import logging
import math
import os
import shutil
import socket
import subprocess
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

from ..phrasing.local_llm import no_redirect_opener
from ..phrasing.muse_spark import open_ledger_at, path_of, read_key_from, unavailable_for

API = "https://api.meta.ai/v1"
MODEL = "muse-spark-1.3"
BACKEND = "meta-model-api"
KEY_FILE, KEY_ENV = "~/.config/firm/operator-keys/MODEL_API_KEY", "PART5_META_KEY_FILE"
USAGE_FILE, USAGE_ENV = "~/.simon/meta_usage.jsonl", "PART5_META_USAGE_FILE"
CAP_ENV, CAP_USD = "PART5_META_SPEND_CAP_USD", 5.0
CALL_MAX_ENV, CALL_MAX_USD = "PART5_META_CALL_MAX_USD", 0.50
RATES = {"input": 1.25, "cached": 0.15, "output": 4.25}   # USD per million tokens, Part 1's spend.py list rates
MAX_OUTPUT_TOKENS = 3000
TIMEOUT_S = 300
LOCK_WAIT_S = TIMEOUT_S + 30   # another process's call may hold the ledger for as long as one call can take
CLIP_MAX_S, CLIP_FPS, CLIP_WIDTH = 60, 8, 480   # what is sent: the first minute, 8 frames a second, 480 px wide
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
UPLOAD_NAME = "clip.mp4"   # the name in the multipart header: a fixed one, so a path's characters never reach it
CLIP_UNREADABLE = "clip not readable"
_log = logging.getLogger(__name__)


class OpinionError(Exception):
    """The second opinion could not be had. `reason` is short and never holds a secret or a model's text."""

    def __init__(self, reason, usage=None):
        super().__init__(reason)
        self.reason, self.usage = reason, usage


def key_path():
    return path_of(KEY_ENV, KEY_FILE)


def usage_path():
    return path_of(USAGE_ENV, USAGE_FILE)


def unavailable(live=False):
    """None when a live call is allowed, else the reason. Never reads the key."""
    return unavailable_for(key_path(), live)


def read_key():
    return read_key_from(key_path(), OpinionError)


def _env_usd(name, default):
    """The USD amount in the variable `name`; `default` when it is unset, and, with a logged warning, when it is not a
    finite number from 0 up (a cap of nan, inf or -1 would stop nothing)."""
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError:
        value = math.nan
    if not math.isfinite(value) or value < 0:
        _log.warning("%s=%r is not a finite amount of USD from 0 up; using the default $%.2f", name, raw, default)
        return default
    return value


def price(input_tokens, output_tokens, cached_tokens=0):
    """USD for one call at the list rates; cached input at the cache rate."""
    cached = min(int(cached_tokens), int(input_tokens))
    return round(((int(input_tokens) - cached) * RATES["input"] + cached * RATES["cached"]
                  + int(output_tokens) * RATES["output"]) / 1_000_000, 6)


def spent():
    """USD recorded in the ledger so far; 0 when there is none."""
    try:
        lines = usage_path().read_text().splitlines()
    except OSError:
        return 0.0
    total = 0.0
    for line in lines:
        try:
            total += float(json.loads(line).get("usd") or 0)
        except (ValueError, AttributeError, TypeError):
            continue
    return total


def check_cap(estimate=0.0):
    """Raise OpinionError("spend cap reached") when a call estimated at `estimate` USD would take the ledger past the
    cap, or when the ledger is already at it (so `check_cap()` before an upload stops a call that cannot be made)."""
    total, cap = spent(), _env_usd(CAP_ENV, CAP_USD)
    if total >= cap or total + estimate > cap:
        raise OpinionError("spend cap reached")


def check_budget(estimate):
    """Raise OpinionError when a call estimated at `estimate` USD passes the per-call ceiling or the cap."""
    ceiling = _env_usd(CALL_MAX_ENV, CALL_MAX_USD)
    if estimate > ceiling:
        raise OpinionError(f"estimated ${estimate:.2f} over the per-call limit of ${ceiling:.2f}")
    check_cap(estimate)


def open_ledger():
    """The ledger opened for appending and locked BEFORE the call, so a spend that cannot be recorded is not made and
    another process cannot pass the cap meanwhile; the lock is held until the returned file is closed."""
    return open_ledger_at(usage_path(), OpinionError, LOCK_WAIT_S)


def failed_usage(status, input_tokens, estimate):
    """The usage to record for a failed call: nothing when the API answered with an error `status` (it refused the
    call), else the pre-call `estimate` for the counted input and the full output allowance (no answer reached us, so
    the spend is unknown and may have happened)."""
    if status is not None:
        return read_usage({})
    return {"input_tokens": input_tokens, "output_tokens": MAX_OUTPUT_TOKENS, "cached_tokens": 0, "usd": estimate,
            "estimated": True}


def ledger_line(status, usage):
    """One ledger line: no key, no text."""
    return {"time": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "model": MODEL, "purpose":
            "second_opinion", "http_status": status, **usage}


def write_ledger(ledger, status, usage):
    """Append one ledger line to the open `ledger`; OpinionError when it cannot be written."""
    try:
        ledger.write(json.dumps(ledger_line(status, usage), sort_keys=True) + "\n")
        ledger.flush()
    except OSError:
        raise OpinionError("usage ledger not writable") from None


def read_usage(payload):
    """`{input_tokens, output_tokens, cached_tokens, usd}` from a Responses body."""
    usage = payload.get("usage") if isinstance(payload, dict) else None
    usage = usage if isinstance(usage, dict) else {}

    def count(value):
        return value if isinstance(value, int) and not isinstance(value, bool) else 0

    details = usage.get("input_tokens_details") if isinstance(usage.get("input_tokens_details"), dict) else {}
    tokens = {"input_tokens": count(usage.get("input_tokens")), "output_tokens": count(usage.get("output_tokens")),
              "cached_tokens": count(details.get("cached_tokens"))}
    return {**tokens, "usd": price(tokens["input_tokens"], tokens["output_tokens"], tokens["cached_tokens"])}


def output_text(payload):
    """The answer text of a Responses body: every `output_text` of every message, else `output_text`."""
    chunks = []
    for item in payload.get("output") or []:
        if isinstance(item, dict) and item.get("type", "message") == "message":
            for part in item.get("content") or []:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    chunks.append(part["text"])
    text = "\n".join(chunks) or payload.get("output_text") or ""
    return text if isinstance(text, str) else ""


def clip_seconds(path):
    """A video's duration from ffprobe, or None when it cannot be read."""
    if shutil.which("ffprobe") is None:
        return None
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                              str(path)], capture_output=True, text=True, timeout=60, check=True).stdout
        return float(out.strip())
    except (subprocess.SubprocessError, OSError, ValueError):
        return None


def prepare(path, out_dir):
    """The clip as sent: the first CLIP_MAX_S seconds at CLIP_FPS and CLIP_WIDTH px, no sound, no metadata tags.
    Without ffmpeg the original is sent when it is at most MAX_UPLOAD_BYTES."""
    path, out = Path(path), Path(out_dir) / f"{uuid.uuid4().hex}.mp4"
    if shutil.which("ffmpeg") is not None:
        # -map_metadata -1: the recording's tags (place, time, device) are not sent
        command = ["ffmpeg", "-v", "error", "-y", "-i", str(path), "-t", str(CLIP_MAX_S), "-an", "-map_metadata", "-1",
                   "-vf", f"fps={CLIP_FPS},scale={CLIP_WIDTH}:-2", "-c:v", "libx264", "-preset", "veryfast", "-crf",
                   "30", "-pix_fmt", "yuv420p", str(out)]
        try:
            subprocess.run(command, capture_output=True, timeout=300, check=True)
            return out
        except (subprocess.SubprocessError, OSError):
            raise OpinionError("clip could not be prepared") from None
    try:
        size = path.stat().st_size
    except OSError:
        raise OpinionError(CLIP_UNREADABLE) from None
    if size > MAX_UPLOAD_BYTES:
        raise OpinionError("clip too large to send")
    return path


def _failure(exc, step):
    if isinstance(exc, urllib.error.HTTPError):
        return f"HTTP {exc.code} on {step}"
    reason = getattr(exc, "reason", None)
    if isinstance(exc, (TimeoutError, socket.timeout)) or isinstance(reason, (TimeoutError, socket.timeout)):
        return f"timeout on {step}"
    if isinstance(exc, ValueError):
        return f"unreadable response on {step}"
    return f"request failed on {step} ({type(exc).__name__})"


class HttpClient:
    """The production client: four calls, no redirect followed, every failure an OpinionError with a plain reason."""

    def __init__(self, key, timeout_s=TIMEOUT_S):
        self._key, self._timeout_s, self._opener = key, timeout_s, no_redirect_opener()
        self.last_status = None

    def _call(self, method, path, data=None, content_type=None, step=None):
        headers = {"Authorization": f"Bearer {self._key}", "User-Agent": "part5-second-opinion"}
        if content_type:
            headers["Content-Type"] = content_type
        request = urllib.request.Request(API + path, data=data, headers=headers, method=method)
        try:
            with self._opener.open(request, timeout=self._timeout_s) as response:
                self.last_status = response.status
                body = response.read()
                return json.loads(body) if body.strip() else {}
        except Exception as exc:  # any failure becomes a reason, never a traceback or the server's text
            self.last_status = getattr(exc, "code", None)
            raise OpinionError(_failure(exc, step or path)) from None

    def _json(self, path, body, step):
        return self._call("POST", path, json.dumps(body).encode(), "application/json", step)

    def upload(self, path):
        boundary = "----part5" + uuid.uuid4().hex
        try:
            video = Path(path).read_bytes()
        except OSError:
            raise OpinionError(CLIP_UNREADABLE) from None
        data = b"".join([
            f"--{boundary}\r\n".encode(), b'Content-Disposition: form-data; name="purpose"\r\n\r\nuser_data\r\n',
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="file"; filename="{UPLOAD_NAME}"\r\n'
            "Content-Type: video/mp4\r\n\r\n".encode(),
            video, f"\r\n--{boundary}--\r\n".encode()])
        answer = self._call("POST", "/files", data, f"multipart/form-data; boundary={boundary}", "upload")
        if not isinstance(answer, dict) or not isinstance(answer.get("id"), str):
            raise OpinionError("upload returned no file id")
        return answer["id"]

    def delete(self, file_id):
        try:
            self._call("DELETE", f"/files/{file_id}", step="delete")
        except OpinionError:
            pass   # a file left behind is the API's to expire; the analysis does not depend on it

    def count(self, body):
        answer = self._json("/responses/input_tokens", {k: body[k] for k in ("model", "input")}, "count")
        usage = answer.get("usage") if isinstance(answer.get("usage"), dict) else answer
        tokens = answer.get("input_tokens", usage.get("input_tokens"))
        if not isinstance(tokens, int) or isinstance(tokens, bool):
            raise OpinionError("token count unreadable")
        return tokens

    def respond(self, body):
        return self._json("/responses", body, "responses")
