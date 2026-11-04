"""The Meta Model API for the second opinion (TICKET-045, docs/specs/second-opinion.md).

Muse Spark 1.3 on `https://api.meta.ai/v1`: clips go up through the Files API, the request is a Responses call with
`input_file` items, and `/responses/input_tokens` counts the input before anything is spent; Part 1's
`keyframe_finder/meta_client.py` uses the same calls on the teacher's clip.

The key is the file `~/.config/firm/operator-keys/MODEL_API_KEY` (`PART5_META_KEY_FILE` for tests). It is read at
the call, stripped, and used for the `Authorization` header and nothing else: never printed, logged, written or put in
a reason. Live calls need the key file AND live mode (the phrasing switches, `muse_spark.live_on`).
An HTTP failure's reason (`HTTP 400 on responses`) carries after a colon the API's own error type and message when its
body has them (TICKET-099): one line of 160 characters at most, with the key, a Bearer token or Authorization header, a
URL, a masked key and any long quoted run taken out and control and bidi characters dropped, and the whole detail left
off when the line fails `guard.unsafe_problem` (a banned word, a link) or the status is 401 or 403 (`_scrubbed`).

Spend: the total cap is checked before anything is uploaded; the input is then counted, and the call is refused when
its estimate (the counted input plus the full output allowance at Part 1's list rates) passes `PART5_META_CALL_MAX_USD`
(default 0.50) or would take the ledger past `PART5_META_SPEND_CAP_USD` (default 5.00). A limit that is set but is not a
finite amount from 0 up refuses the call (a limit that cannot be read must not become another one), and so does a
ledger that exists and cannot be read (an unknown total is not a total of 0). The ledger `~/.simon/meta_usage.jsonl`
(`PART5_META_USAGE_FILE`) is opened and locked (flock) before the cap check and held until the call is recorded, so two
processes cannot both pass the cap; it gets one line per call: UTC time, model, HTTP status, token counts and USD,
never the key or text. A call whose cost is not known may still have been billed, so its line carries the pre-call
estimate with `estimated: true`: one that failed with no answer from the API (a timeout, a connection error, an
unreadable body), one the API answered with a 5xx status (a gateway may answer after the model ran) and one answered
with a body that holds no token counts. A call the API refused with a status below 500 is recorded at $0.

`call(client, body, purpose, rates=RATES, **extra)` is that sequence for any Responses body (count, budget under the
lock, send, record): the per-take opinion (purpose `second_opinion`, clips uploaded first), the history opinion
(`history_opinion`, text only, TICKET-072) and Ask this take (`ask`, muse-wonder-1.0 at its own `rates`, TICKET-081,
docs/specs/ask-this-take.md) all use it, so there is one place that spends. The ledger line names `body["model"]`.
`function_calls` and `response_id` read a tool-calling answer for the ask loop.
"""
import json
import math
import os
import re
import shutil
import socket
import subprocess
import urllib.error
import urllib.request
import unicodedata
import uuid
from pathlib import Path

from ..phrasing.local_llm import no_redirect_opener
from ..phrasing.muse_spark import append_line, open_ledger_at, path_of, read_key_from, unavailable_for, utc_now

API = os.environ.get("SIMON_META_API", "https://api.meta.ai/v1").rstrip("/")  # SIMON_META_API: the judges' relay (deploy/judges/README.md)
MODEL = "muse-spark-1.3"
BACKEND = "meta-model-api"
KEY_FILE, KEY_ENV = "~/.config/firm/operator-keys/MODEL_API_KEY", "PART5_META_KEY_FILE"
USAGE_FILE, USAGE_ENV = "~/.simon/meta_usage.jsonl", "PART5_META_USAGE_FILE"
CAP_ENV, CAP_USD = "PART5_META_SPEND_CAP_USD", 5.0
CALL_MAX_ENV, CALL_MAX_USD = "PART5_META_CALL_MAX_USD", 0.50
RATES = {"input": 1.25, "cached": 0.15, "output": 4.25}   # USD per million tokens, Part 1's spend.py list rates
MAX_OUTPUT_TOKENS = 3000   # the default allowance for a request that names none (every feature names its own: prompt.py)
TIMEOUT_S = 300
LOCK_WAIT_S = TIMEOUT_S + 30   # another process's call may hold the ledger for as long as one call can take
CLIP_MAX_S, CLIP_FPS, CLIP_WIDTH = 60, 8, 480   # what is sent: the first minute, 8 frames a second, 480 px wide
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
UPLOAD_NAME = "clip.mp4"   # the name in the multipart header: a fixed one, so a path's characters never reach it
CLIP_UNREADABLE = "clip not readable"
# TICKET-099: the API's own error type and message ride on an HTTP failure's reason. 160 characters, so "HTTP 400 on
# responses: " and the detail fit the 200 of the Ask document's `fallback_reason`; the body is read to 8 KB at most.
ERROR_DETAIL_CHARS, ERROR_BODY_BYTES = 160, 8192
NO_DETAIL_STATUSES = (401, 403)   # an authentication answer may echo the key (masked, so no replace finds it): no detail
# What the detail never keeps: a Bearer token or an Authorization header, a URL (with a scheme, `www.` or a host and a
# path), a long run with a digit in it (an id or a key) and a long quoted run (a request echoed back, which may hold
# a model's text), and any word with a run of asterisks in it (a masked key: `mk_live_********ghij`).
_UNSAFE = re.compile(r"(?i)\bbearer\s+\S+|\bauthorization\b[^\n]*|\b[a-z][a-z0-9+.-]*://\S+|\bwww\.\S+"
                     r"|\b[\w-]+(?:\.[\w-]+)+/\S*|\b(?=[\w-]*\d)[\w-]{24,}\b|\"[^\"]{40,}\"|'[^']{40,}'|\S*\*{3,}\S*")
PURPOSE = "second_opinion"   # the ledger's `purpose` of a per-take call; another feature names its own (`call`)


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
    """The USD amount in the variable `name`; `default` when it is unset or blank. A value that is set and is not a
    finite number from 0 up (`1,5`, nan, inf, -1) raises OpinionError: a limit that cannot be read must not run at
    another one (a cap of nan or inf would stop nothing). The reason names the variable and never its value."""
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError:
        value = math.nan
    if not math.isfinite(value) or value < 0:
        raise OpinionError(f"{name} is not an amount of USD from 0 up")
    return value


def price(input_tokens, output_tokens, cached_tokens=0, rates=RATES):
    """USD for one call at the list `rates` (Muse Spark's unless given); cached input at the cache rate."""
    cached = min(int(cached_tokens), int(input_tokens))
    return round(((int(input_tokens) - cached) * rates["input"] + cached * rates["cached"]
                  + int(output_tokens) * rates["output"]) / 1_000_000, 6)


def spent():
    """USD recorded in the ledger so far; 0 when there is no ledger yet. A ledger that is there and cannot be read
    (no read permission, not text) raises OpinionError("usage ledger not readable"): the total is unknown, and an
    unknown total is not a total of 0 (it fails closed). So does a line whose `usd` is not a finite amount from 0 up
    (NaN would turn the total into NaN, which no comparison against the cap can catch; a negative amount would pay
    the total down): the total cannot be trusted."""
    try:
        lines = usage_path().read_text().splitlines()
    except (FileNotFoundError, NotADirectoryError):   # nothing recorded yet; a path that cannot hold a ledger is the
        return 0.0                                     # writer's to refuse ("usage ledger not writable")
    except (OSError, ValueError):
        raise OpinionError("usage ledger not readable") from None
    total = 0.0
    for line in lines:
        try:
            amount = float(json.loads(line).get("usd") or 0)
        except OverflowError:   # an integer too large for a float is not an amount either
            raise OpinionError("usage ledger not readable") from None
        except (ValueError, AttributeError, TypeError):
            continue
        if not math.isfinite(amount) or amount < 0:
            raise OpinionError("usage ledger not readable")
        total += amount
    return total


def call_ceiling():
    """The per-call ceiling in USD (`PART5_META_CALL_MAX_USD`); OpinionError when it is set and is not an amount."""
    return _env_usd(CALL_MAX_ENV, CALL_MAX_USD)


def check_settings():
    """Raise OpinionError when either limit variable is set to something that is not an amount (see `_env_usd`), so a
    call is refused before anything is uploaded."""
    _env_usd(CAP_ENV, CAP_USD)
    _env_usd(CALL_MAX_ENV, CALL_MAX_USD)


def check_cap(estimate=0.0):
    """Raise OpinionError("spend cap reached") when a call estimated at `estimate` USD would take the ledger past the
    cap, or when the ledger is already at it (so `check_cap()` before an upload stops a call that cannot be made)."""
    total, cap = spent(), _env_usd(CAP_ENV, CAP_USD)
    if total >= cap or total + estimate > cap:
        raise OpinionError("spend cap reached")


def check_budget(estimate):
    """Raise OpinionError when a call estimated at `estimate` USD passes the per-call ceiling or the cap."""
    ceiling = call_ceiling()
    if estimate > ceiling:
        raise OpinionError(f"estimated ${estimate:.2f} over the per-call limit of ${ceiling:.2f}")
    check_cap(estimate)


def open_ledger():
    """The ledger opened for appending and locked BEFORE the call, so a spend that cannot be recorded is not made and
    another process cannot pass the cap meanwhile; the lock is held until the returned file is closed."""
    return open_ledger_at(usage_path(), OpinionError, LOCK_WAIT_S)


def estimated_usage(input_tokens, estimate, allowance=MAX_OUTPUT_TOKENS):
    """The usage to record when the spend is unknown and may have happened: the pre-call `estimate` for the counted
    input and the full output `allowance` of the request, marked `estimated`."""
    return {"input_tokens": input_tokens, "output_tokens": allowance, "cached_tokens": 0, "usd": estimate,
            "estimated": True}


def failed_usage(status, input_tokens, estimate, allowance=MAX_OUTPUT_TOKENS):
    """The usage to record for a failed call: $0 when the API refused it with a `status` below 500 (a 4xx, such as 429:
    the model did not run), else the pre-call `estimate`. No status means no answer reached us, and a 5xx may come from
    a gateway after the model ran, so in both the spend is unknown and may have happened."""
    if status is not None and status < 500:
        return read_usage({})
    return estimated_usage(input_tokens, estimate, allowance)


def answered_usage(payload, input_tokens, estimate, allowance=MAX_OUTPUT_TOKENS, rates=RATES):
    """The usage to record for a call the API answered with `payload`: the body's own token counts priced at `rates`,
    or, when it holds no input and output counts, the pre-call `estimate` (an answer that does not say what it cost
    may have cost it)."""
    usage = payload.get("usage") if isinstance(payload, dict) else None
    if isinstance(usage, dict) and all(_count(usage.get(k)) is not None for k in ("input_tokens", "output_tokens")):
        return read_usage(payload, rates)
    return estimated_usage(input_tokens, estimate, allowance)


def ledger_line(status, usage, purpose=PURPOSE, model=MODEL, **extra):
    """One ledger line: no key, no text. `purpose` names the feature that made the call and `model` the model it
    asked; `extra` adds fields such as `prompt_version` (short identifiers, never text)."""
    return {"time": utc_now(), "model": model, "purpose": purpose, "http_status": status, **extra, **usage}


def write_ledger(ledger, status, usage, purpose=PURPOSE, model=MODEL, **extra):
    """Append one ledger line to the open `ledger`; OpinionError when it cannot be written."""
    append_line(ledger, ledger_line(status, usage, purpose, model, **extra), OpinionError)


def preflight():
    """Refuse a call before anything is uploaded or sent: a limit variable that is not an amount (`check_settings`),
    and a total that has already reached the cap (`check_cap`). OpinionError with the reason."""
    check_settings()
    check_cap()


def call(client, body, purpose=PURPOSE, rates=RATES, **extra):
    """Count `body`, check the budget under the locked ledger, send it and record the call: `(payload, usage)`.

    The ledger is opened and locked after the count and held until the call is recorded, so the budget check and the
    call cannot be interleaved with another process's. A call whose cost is not known (no answer from the API, a 5xx,
    an answer with no token counts) is recorded at its pre-call estimate (`failed_usage`, `answered_usage`); the line
    carries `purpose` and `extra`. OpinionError for any failure, after the line is written when the call was made.

    The output allowance is the request's own `max_output_tokens` (MAX_OUTPUT_TOKENS when it names none), so the
    estimate, the ceiling check and an estimated ledger line move with the allowance a feature asks for. The call is
    priced at `rates` (Muse Spark's unless a feature names its model's) and its line names `body["model"]`."""
    counted = client.count(body)
    allowance = body.get("max_output_tokens") or MAX_OUTPUT_TOKENS
    estimate = price(counted, allowance, rates=rates)
    model = body.get("model") or MODEL
    with open_ledger() as ledger:
        check_budget(estimate)
        try:
            payload = client.respond(body)
        except OpinionError:
            status = getattr(client, "last_status", None)
            write_ledger(ledger, status, failed_usage(status, counted, estimate, allowance), purpose, model, **extra)
            raise
        usage = answered_usage(payload, counted, estimate, allowance, rates)
        write_ledger(ledger, getattr(client, "last_status", 200), usage, purpose, model, **extra)
    return payload, usage


def _count(value):
    """`value` when it is a token count (a whole number from 0 up, not a bool), else None."""
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def read_usage(payload, rates=RATES):
    """`{input_tokens, output_tokens, cached_tokens, usd}` from a Responses body at `rates`; a count it does not hold
    reads 0."""
    usage = payload.get("usage") if isinstance(payload, dict) else None
    usage = usage if isinstance(usage, dict) else {}
    details = usage.get("input_tokens_details") if isinstance(usage.get("input_tokens_details"), dict) else {}
    tokens = {"input_tokens": _count(usage.get("input_tokens")) or 0,
              "output_tokens": _count(usage.get("output_tokens")) or 0,
              "cached_tokens": _count(details.get("cached_tokens")) or 0}
    return {**tokens, "usd": price(tokens["input_tokens"], tokens["output_tokens"], tokens["cached_tokens"], rates)}


def _objects(value):
    """`value` when it is a list of JSON objects, else OpinionError("unreadable answer")."""
    if not isinstance(value, list) or not all(isinstance(entry, dict) for entry in value):
        raise OpinionError("unreadable answer")
    return value


def _output_items(payload):
    """The `output` items of a Responses body, [] when it has none. A body that is not a JSON object, or whose `output`
    is not a list of objects, is an OpinionError("unreadable answer"): R5 of the 1.14.0 review, where `{"output": 5}`
    raised a TypeError out of the ask loop after its ledger line was written, and N1 of its recheck (`[5]`)."""
    if not isinstance(payload, dict):
        raise OpinionError("unreadable answer")
    items = payload.get("output")
    return [] if items is None else _objects(items)


def _message_parts(item):
    """The `content` parts of a message item. A `content` that is not a list of objects (missing, null, `5`, `[5]`) is
    an OpinionError("unreadable answer"): N1 of the 1.14.0 recheck, where `{"type": "message", "content": 5}` raised a
    TypeError out of the ask loop, the second opinion and the history opinion alike."""
    return _objects(item.get("content"))


def output_text(payload):
    """The answer text of a Responses body: every `output_text` of every message, else `output_text`. A body that is
    not a JSON object (an array, a string), whose `output` is not a list of objects, or that has a message whose
    `content` is not a list of objects, is an OpinionError("unreadable answer")."""
    chunks = []
    for item in _output_items(payload):
        if item.get("type", "message") == "message":
            for part in _message_parts(item):
                if isinstance(part.get("text"), str):
                    chunks.append(part["text"])
    text = "\n".join(chunks) or payload.get("output_text") or ""
    return text if isinstance(text, str) else ""


def function_calls(payload):
    """The tool calls of a Responses body, in order: `[{name, arguments, call_id}]` from its `function_call` output
    items (`arguments` the JSON text as sent, `""` when it is not text). An item with no name or call id is skipped: it
    cannot be answered. A body that is not an object, or whose `output` is not a list of objects, is an
    OpinionError("unreadable answer")."""
    calls = []
    for item in _output_items(payload):
        if item.get("type") == "function_call":
            name, call_id, arguments = item.get("name"), item.get("call_id"), item.get("arguments")
            if isinstance(name, str) and isinstance(call_id, str) and call_id:
                calls.append({"name": name, "arguments": arguments if isinstance(arguments, str) else "",
                              "call_id": call_id})
    return calls


def response_id(payload):
    """The `id` of a Responses body, which a follow-up names as `previous_response_id`; OpinionError("answer has no
    response id") when it has none."""
    found = payload.get("id") if isinstance(payload, dict) else None
    if not (isinstance(found, str) and found):
        raise OpinionError("answer has no response id")
    return found


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


def _scrubbed(text, key):
    """`text` as one line, the key and anything `_UNSAFE` matches replaced by `[removed]`, control and bidi characters
    taken out, cut to ERROR_DETAIL_CHARS; "" when the line fails `guard.unsafe_problem`, the check every shown text is
    held to (a banned word, a link, a control character), so the detail is dropped whole, not trimmed. A heuristic
    (R4 of the 1.14.1 review): the API's words are a third party's, so the reason holds them as a hint, not a promise."""
    from .guard import unsafe_problem   # lazy: guard imports prompt, which imports this module
    if key:
        text = text.replace(key, "[removed]")
    line = " ".join(_UNSAFE.sub("[removed]", text).split())
    line = "".join(c for c in line if unicodedata.category(c) not in ("Cc", "Cf"))
    line = line if len(line) <= ERROR_DETAIL_CHARS else line[:ERROR_DETAIL_CHARS - 3] + "..."
    return "" if unsafe_problem(line) else line


def _api_detail(exc, key):
    """`": <type>: <message>"` from the JSON error body of an HTTPError, scrubbed (`_scrubbed`); "" for any other
    failure, a body that is not JSON or one with no error text, and for a 401 or 403 whatever the body says (an
    authentication answer is where a key is echoed back, masked or not: R4). The key, headers and URLs never reach it."""
    if not isinstance(exc, urllib.error.HTTPError) or exc.code in NO_DETAIL_STATUSES:
        return ""
    try:
        body = json.loads(exc.read(ERROR_BODY_BYTES))
    except Exception:  # a closed or unreadable body, not JSON: the status line alone
        return ""
    error = body.get("error", body) if isinstance(body, dict) else None
    error = {"message": error} if isinstance(error, str) else error
    if not isinstance(error, dict):
        return ""
    kind = error.get("type") if isinstance(error.get("type"), str) else error.get("code")
    parts = [part for part in (kind, error.get("message")) if isinstance(part, str) and part.strip()]
    text = _scrubbed(": ".join(parts), key)
    return f": {text}" if text else ""


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
            raise OpinionError(_failure(exc, step or path) + _api_detail(exc, self._key)) from None

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
        if not isinstance(answer, dict):   # an array or a string body: not a count, and `.get` would raise
            raise OpinionError("unreadable answer")
        usage = answer.get("usage") if isinstance(answer.get("usage"), dict) else answer
        tokens = answer.get("input_tokens", usage.get("input_tokens"))
        if not isinstance(tokens, int) or isinstance(tokens, bool):
            raise OpinionError("token count unreadable")
        return tokens

    def respond(self, body):
        return self._json("/responses", body, "responses")
