"""The one Muse Spark 1.3 call for the history report (docs/specs/history-meta.md, TICKET-181 AC-2 to AC-6).

`ask(packed)` uploads the packed clips to the Meta Files API (`expires_after` 3600), counts the text with
`/responses/input_tokens` (blind to video, so clips are priced by their seconds), refuses a call that is dear or past the total cap, appends the ledger line under flock
BEFORE the call, makes one Responses call and deletes every uploaded file on every path. The key comes from
`keys.read_key`; it is used for the Authorization header and nothing else. Every failure is a `HistoryError` with a
short reason that holds no key, no model text and no user id; an HTTP failure adds Meta's own error message, cut to
`ERROR_CHARS` with keys, bearer tokens, data URLs and long base64 runs masked (TICKET-330). Nothing here imports another Part.
"""

from __future__ import annotations

import fcntl
import json
import math
import os
from pathlib import Path
import re
import socket
import time
from typing import Any, Callable
import urllib.error
import urllib.request
import uuid

from part7 import config, history_prompt, keys
from part7.history_prompt import MAX_VIDEOS, VIDEO_TOKENS_PER_S

API = os.environ.get("SIMON_META_API", "https://api.meta.ai/v1").rstrip("/")  # SIMON_META_API: the judges' relay (deploy/judges/README.md)
MODEL = "muse-spark-1.3"          # never the -contributor model: student video is not for training
KEY_NAME = "MODEL_API_KEY"
RATES = {"input": 1.25, "cached": 0.15, "output": 4.25}   # USD per million tokens
MAX_OUTPUT_TOKENS = 4000
TIMEOUT_S = 300.0
# Both limits are off unless their env var holds a positive number (off by default during testing).
CALL_MAX_ENV = "SIMON7_HISTORY_CALL_MAX_USD"
CAP_ENV = "SIMON7_HISTORY_CAP_USD"
EXPIRES_AFTER_S = 3600
CACHE_KEY, CACHE_RETENTION = "simon-history", "in_memory"
# Both accepted by the API (demos/rubric/HISTORY/spike.json). The guard parses JSON from the text either way.
STRICT_SCHEMA = True
STORE_FALSE_ACCEPTED = True


class HistoryError(RuntimeError):
    """The report could not be had. `reason` is short; the server turns it into a fact-table fallback."""

    def __init__(self, reason: str, usage: dict[str, Any] | None = None):
        super().__init__(reason)
        self.reason, self.usage = reason, usage


def price(input_tokens: int, output_tokens: int, cached_tokens: int = 0) -> float:
    cached = min(int(cached_tokens), int(input_tokens))
    return round(((int(input_tokens) - cached) * RATES["input"] + cached * RATES["cached"]
                  + int(output_tokens) * RATES["output"]) / 1_000_000, 6)


def _env_usd(name: str) -> float | None:
    try:
        value = float(os.environ.get(name, ""))
    except ValueError:
        return None
    return value if value > 0 else None


def ledger_path(state: Path | str | None = None) -> Path:
    return config.state_root(state) / "history" / "spend.jsonl"


def spent_usd(ledger: Path) -> float:
    """USD on the ledger: a reserved call counts at its estimate until a `settle` line gives its real cost."""
    reserved: dict[str, float] = {}
    total = 0.0
    try:
        lines = ledger.read_text(encoding="utf-8").splitlines()
    except OSError:
        return 0.0
    for line in lines:
        try:
            row = json.loads(line)
            usd, call = float(row.get("usd") or 0.0), str(row.get("call"))
        except (ValueError, AttributeError, TypeError):
            continue
        if row.get("kind") == "settle":
            total += usd - reserved.pop(call, 0.0)
        else:
            reserved[call] = usd
            total += usd
    return total


def read_ledger(ledger: Path) -> list[dict[str, Any]]:
    """Every readable ledger line; a line from before TICKET-206 has no `feature` and reads as "compare"."""
    try:
        lines = ledger.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    rows = []
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append({**row, "feature": row.get("feature") or DEFAULT_FEATURE})
    return rows


def spent_by_feature(ledger: Path) -> dict[str, float]:
    """USD per feature, counted as `spent_usd` counts (a reserve stands at its estimate until its settle)."""
    reserved: dict[str, tuple[str, float]] = {}
    totals: dict[str, float] = {}
    for row in read_ledger(ledger):
        usd, call, feature = float(row.get("usd") or 0.0), str(row.get("call")), row["feature"]
        if row.get("kind") == "settle":
            held = reserved.pop(call, (feature, 0.0))[1]
            totals[feature] = totals.get(feature, 0.0) + usd - held
        elif row.get("kind") == "reserve":
            reserved[call] = (feature, usd)
            totals[feature] = totals.get(feature, 0.0) + usd
    return {k: round(v, 6) for k, v in totals.items()}


def feature_cap(feature: str, kind: str) -> float | None:
    """The cap of one feature from `SIMON7_HISTORY_<FEATURE>_CAP_USD` (total) or `..._CALL_MAX_USD` (per call), or None.

    Off unless the variable is set to a positive number (operator ruling: spend caps are off by default). The
    global caps above are unchanged and still bound every feature."""
    name = "".join(c if c.isalnum() else "_" for c in feature).upper()
    suffix = {"total": "CAP_USD", "call": "CALL_MAX_USD"}[kind]
    try:
        value = float(os.environ.get(f"SIMON7_HISTORY_{name}_{suffix}", ""))
    except ValueError:
        return None
    return value if value > 0 else None


def _append(ledger: Path, row: dict[str, Any], limit: float | None = None, reserve: bool = False) -> None:
    """Append one line under an exclusive lock; with `limit`, refuse when the total would pass it.

    A reserve line (`reserve`) also stops at its feature's own cap when `feature_cap` has one, with or without a
    global cap (spend caps are off by default; a feature cap set on its own still binds)."""
    try:
        ledger.parent.mkdir(parents=True, exist_ok=True)
        with ledger.with_name(ledger.name + ".lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                if limit is not None and spent_usd(ledger) + float(row["usd"]) > limit:
                    raise HistoryError("spend cap reached")
                own = feature_cap(row["feature"], "total") if reserve else None
                if own is not None and spent_by_feature(ledger).get(row["feature"], 0.0) + float(row["usd"]) > own:
                    raise HistoryError(f"spend cap reached for {row['feature']}")
                with ledger.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(row, sort_keys=True) + "\n")
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)
    except OSError:
        raise HistoryError("spend ledger not writable") from None


DEFAULT_FEATURE = "compare"  # the one feature before TICKET-206; a ledger line without `feature` is read as this


def _line(call: str, kind: str, usd: float, feature: str, prompt_version: str | None, **fields: Any) -> dict[str, Any]:
    """A ledger line: time, call id, model, feature, prompt version and numbers only. No user id, no text, no file name."""
    return {"call": call, "kind": kind, "model": MODEL, "usd": round(usd, 6), "feature": feature, "prompt_version": prompt_version,
            "when": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **fields}


def read_usage(payload: Any) -> dict[str, int]:
    usage = payload.get("usage") if isinstance(payload, dict) and isinstance(payload.get("usage"), dict) else {}

    def count(value: Any) -> int:
        return value if isinstance(value, int) and not isinstance(value, bool) else 0

    details = usage.get("input_tokens_details") if isinstance(usage.get("input_tokens_details"), dict) else {}
    return {"input_tokens": count(usage.get("input_tokens")), "output_tokens": count(usage.get("output_tokens")),
            "cached_tokens": count(details.get("cached_tokens"))}


def output_text(payload: Any) -> str:
    chunks = []
    for item in (payload.get("output") if isinstance(payload, dict) else None) or []:
        if isinstance(item, dict) and item.get("type", "message") == "message":
            chunks += [p["text"] for p in item.get("content") or [] if isinstance(p, dict) and isinstance(p.get("text"), str)]
    text = "\n".join(chunks) or (payload.get("output_text") if isinstance(payload, dict) else "") or ""
    return text if isinstance(text, str) else ""


def build_body(packed: dict[str, Any], file_ids: dict[int, str]) -> dict[str, Any]:
    """The Responses body. `file_ids` maps the index of each video item in `packed['content']` to its file id."""
    content: list[dict[str, Any]] = []
    for i, item in enumerate(packed["content"]):
        if item["type"] == "video":
            content += [{"type": "input_text", "text": f"{item['label']} video:"},
                        {"type": "input_file", "file_id": file_ids[i]}]
        else:
            content.append({"type": "input_text", "text": item["text"]})
    body: dict[str, Any] = {"model": MODEL, "max_output_tokens": MAX_OUTPUT_TOKENS, "reasoning": {"effort": "low"},
                            "input": [{"type": "message", "role": "user", "content": content}],
                            "prompt_cache_key": packed.get("cache_key") or CACHE_KEY,  # TICKET-219: one key per user and movement (history_longpack)
                            "prompt_cache_retention": CACHE_RETENTION}
    if STRICT_SCHEMA:
        body["text"] = {"format": {"type": "json_schema", "name": packed.get("schema_name") or history_prompt.SCHEMA_NAME,
                                   "schema": packed["schema"], "strict": True}}
    if STORE_FALSE_ACCEPTED:
        body["store"] = False
    return body


ERROR_CHARS = 160   # most characters of Meta's error message kept in a failure reason (TICKET-330)
_ERROR_BYTES = 4096
_MASKS = (re.compile(r"data:[\w.+/-]+;base64,[A-Za-z0-9+/=_-]*"), re.compile(r"(?i)\bbearer\s+\S+"),
          re.compile(r"(?i)\b(?:sk|pk|mk|rk|key|tok|token)[-_][A-Za-z0-9_-]{6,}"), re.compile(r"[A-Za-z0-9+/=_-]{32,}"))


def mask_error(text: str, key: str | None = None) -> str:
    """`text` with key values, bearer tokens, data URLs and long base64 runs masked, whitespace collapsed, cut short."""
    out = text.replace(key, "<redacted>") if key else text
    out = keys.redact(out)
    for pattern in _MASKS:
        out = pattern.sub("<masked>", out)
    out = re.sub(r"\s+", " ", out).strip()
    return out if len(out) <= ERROR_CHARS else out[:ERROR_CHARS - 3].rstrip() + "..."


def _error_message(exc: urllib.error.HTTPError, key: str | None) -> str:
    """Meta's `error.message` (or the raw body when it is not that JSON), masked and cut; "" when there is none."""
    try:
        raw = exc.read(_ERROR_BYTES) or b""
    except Exception:  # a body that cannot be read leaves the status alone
        return ""
    text = raw.decode("utf-8", errors="replace")
    try:
        doc = json.loads(text)
    except ValueError:
        doc = None
    error = doc.get("error") if isinstance(doc, dict) else None
    message = error.get("message") if isinstance(error, dict) else error if isinstance(error, str) else None
    if message is None and isinstance(doc, dict) and isinstance(doc.get("message"), str):
        message = doc["message"]
    return mask_error(str(message) if message is not None else text, key)


def _failure(exc: Exception, step: str, key: str | None = None) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        message = _error_message(exc, key)
        return f"HTTP {exc.code} on {step}" + (f": {message}" if message else "")
    reason = getattr(exc, "reason", None)
    if isinstance(exc, (TimeoutError, socket.timeout)) or isinstance(reason, (TimeoutError, socket.timeout)):
        return f"timeout on {step}"
    if isinstance(exc, ValueError):
        return f"unreadable response on {step}"
    return f"request failed on {step} ({type(exc).__name__})"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


class HttpClient:
    """The production transport: upload, delete, count, respond. No redirect is followed."""

    def __init__(self, key: str, timeout_s: float = TIMEOUT_S):
        self._key, self._timeout_s = key, timeout_s
        self._opener = urllib.request.build_opener(_NoRedirect)

    def _call(self, method: str, path: str, data: bytes | None, content_type: str | None, step: str) -> Any:
        headers = {"Authorization": f"Bearer {self._key}", "User-Agent": "part7-history"}
        if content_type:
            headers["Content-Type"] = content_type
        request = urllib.request.Request(API + path, data=data, headers=headers, method=method)
        try:
            with self._opener.open(request, timeout=self._timeout_s) as response:
                body = response.read()
                return json.loads(body) if body.strip() else {}
        except Exception as exc:  # any failure becomes a short reason: never a traceback, a key or a payload
            raise HistoryError(_failure(exc, step, self._key)) from None

    def _json(self, path: str, body: dict[str, Any], step: str) -> Any:
        return self._call("POST", path, json.dumps(body).encode(), "application/json", step)

    def upload(self, path: str) -> str:
        boundary = "----part7history" + uuid.uuid4().hex
        fields = {"purpose": "user_data", "expires_after[anchor]": "created_at",
                  "expires_after[seconds]": str(EXPIRES_AFTER_S)}
        parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
                 for k, v in fields.items()]
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="clip.mp4"\r\n'
                     "Content-Type: video/mp4\r\n\r\n".encode())
        try:
            parts.append(Path(path).read_bytes())
        except OSError:
            raise HistoryError("a clip could not be read") from None
        parts.append(f"\r\n--{boundary}--\r\n".encode())
        answer = self._call("POST", "/files", b"".join(parts), f"multipart/form-data; boundary={boundary}", "upload")
        if not isinstance(answer, dict) or not isinstance(answer.get("id"), str):
            raise HistoryError("upload returned no file id")
        return answer["id"]

    def delete(self, file_id: str) -> None:
        self._call("DELETE", f"/files/{file_id}", None, None, "delete")

    def count(self, body: dict[str, Any]) -> int:
        answer = self._json("/responses/input_tokens", {k: body[k] for k in ("model", "input")}, "count")
        tokens = answer.get("input_tokens") if isinstance(answer, dict) else None
        if not isinstance(tokens, int) or isinstance(tokens, bool):
            raise HistoryError("token count unreadable")
        return tokens

    def respond(self, body: dict[str, Any]) -> Any:
        return self._json("/responses", body, "responses")


def _check_caps_before_upload(ledger: Path, packed: dict[str, Any]) -> None:
    """Refuse an over-cap call before any file leaves the machine, from the packer's own token estimate.

    The exact reserve still happens after the counter has seen the body; this only stops a clearly over-cap call early."""
    tokens = packed.get("est_input_tokens")
    if not isinstance(tokens, (int, float)) or tokens <= 0:
        return
    estimate = price(int(tokens), MAX_OUTPUT_TOKENS)
    ceiling, cap = _env_usd(CALL_MAX_ENV), _env_usd(CAP_ENV)
    if ceiling is not None and estimate > ceiling:
        raise HistoryError(f"estimated ${estimate:.2f} is over the per-call limit of ${ceiling:.2f}")
    if cap is not None and spent_usd(ledger) + estimate > cap:
        raise HistoryError("spend cap reached")


def _check_consent(packed: dict[str, Any]) -> None:
    videos = sum(item["type"] == "video" for item in packed["content"])
    if videos and packed.get("video_consent") is not True:
        raise HistoryError("no video consent")
    if videos > MAX_VIDEOS:
        raise HistoryError(f"more than {MAX_VIDEOS} videos in one request")


def ask(packed: dict[str, Any], *, transport: Any = None, state: Path | str | None = None,
        keys_dir: Path | str | None = None,
        clock: Callable[[], float] = time.monotonic) -> tuple[str, dict[str, Any]]:
    """One call for `packed` (from `history_prompt.pack`); returns `(text, usage)` or raises `HistoryError`.

    `usage` is `{input_tokens, cached_tokens, output_tokens, usd, clips_sent}`.
    """
    _check_consent(packed)
    if transport is None:
        key = keys.read_key(KEY_NAME, keys_dir=keys_dir)
        if not key:
            raise HistoryError("no Meta Model API key")
        transport = HttpClient(key)
    ledger = ledger_path(state)
    _check_caps_before_upload(ledger, packed)
    uploaded: list[str] = []
    try:
        file_ids = {}
        for i, item in enumerate(packed["content"]):
            if item["type"] == "video":
                file_ids[i] = transport.upload(item["path"])
                uploaded.append(file_ids[i])
        body = build_body(packed, file_ids)
        counted = transport.count(body)
        # The counter does not see video (spike.json): clips are priced here by their seconds.
        reserved_tokens = counted + math.ceil(float(packed.get("video_seconds") or 0) * VIDEO_TOKENS_PER_S)
        estimate = price(reserved_tokens, MAX_OUTPUT_TOKENS)
        ceiling = _env_usd(CALL_MAX_ENV)
        if ceiling is not None and estimate > ceiling:
            raise HistoryError(f"estimated ${estimate:.2f} is over the per-call limit of ${ceiling:.2f}")
        own_call = feature_cap(str(packed.get("feature") or DEFAULT_FEATURE), "call")
        if own_call is not None and estimate > own_call:
            raise HistoryError(f"estimated ${estimate:.2f} is over the per-call limit of ${own_call:.2f} for this feature")
        call = uuid.uuid4().hex
        clips = int(packed.get("clips_sent") or 0)
        feature, version = str(packed.get("feature") or DEFAULT_FEATURE), packed.get("prompt_version")
        _append(ledger, _line(call, "reserve", estimate, feature, version, input_tokens=reserved_tokens, clips_sent=clips),
                _env_usd(CAP_ENV), reserve=True)  # off unless set (operator, 2026-11-01: all spend caps off by default)
        started = clock()
        payload = transport.respond(body)
        usage = read_usage(payload)
        usage.update(usd=price(usage["input_tokens"], usage["output_tokens"], usage["cached_tokens"]), clips_sent=clips)
        _append(ledger, _line(call, "settle", usage["usd"], feature, version, seconds=round(clock() - started, 1),
                              **{k: usage[k] for k in ("input_tokens", "cached_tokens", "output_tokens")},
                              clips_sent=clips))
        text = output_text(payload)
        if not text.strip():
            raise HistoryError("the model answered with no text", usage)
        if isinstance(payload, dict) and payload.get("status") == "incomplete":
            raise HistoryError("the model stopped before it finished", usage)
        return text, usage
    finally:
        for file_id in uploaded:
            try:
                transport.delete(file_id)
            except HistoryError:
                pass   # a file left behind expires on its own after EXPIRES_AFTER_S
