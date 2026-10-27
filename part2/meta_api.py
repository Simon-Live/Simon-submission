"""Meta Model API client (https://api.meta.ai/v1) with a local budget guard (#4).

    file_id = upload("clip.mp4")
    for delta in respond("sam-3.1", [text("person"), video(file_id)], est_cost_usd=sam_video_cost(1800)):
        ...

MODEL_API_KEY comes from the environment or the repo's .env. Meta has no hard spend cap, so
every call that costs money goes through the guard: it refuses a call that would take the
recorded total past META_BUDGET_USD, and prints a reminder each time the total crosses a
multiple of META_BUDGET_REMIND_EVERY_USD. Spend is recorded in a JSONL ledger shared by every
session on this machine (META_SPEND_LEDGER, default ~/.simon/meta_spend.jsonl).
"""
import json
import os
import sys
import time
import urllib.request
import uuid
from pathlib import Path

BASE_URL = "https://api.meta.ai/v1"
ROOT = Path(__file__).resolve().parent.parent

# Published prices (dev.meta.ai/docs/pricing-rate-limits, checked 2026-10-27).
SAM_VIDEO_USD_PER_FRAME = 0.20 / 1000
SAM_VIDEO_MIN_FRAMES = 50
SAM_IMAGE_USD = 2.50 / 1000


class BudgetExceeded(RuntimeError):
    pass


def sam_video_cost(n_frames: int) -> float:
    return max(n_frames, SAM_VIDEO_MIN_FRAMES) * SAM_VIDEO_USD_PER_FRAME


def text(s: str) -> dict:
    return {"type": "input_text", "text": s}


def video(file_id: str) -> dict:
    return {"type": "input_video", "file_id": file_id}


def image_url(url: str) -> dict:
    return {"type": "input_image", "image_url": url}


def _env(name: str, default=None):
    if name in os.environ:
        return os.environ[name]
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            key, sep, value = line.partition("=")
            if sep and key.strip() == name:
                return value.strip()
    return default


class Budget:
    def __init__(self, limit_usd=None, remind_every_usd=None, ledger=None):
        self.limit = float(limit_usd if limit_usd is not None else _env("META_BUDGET_USD", "0") or 0)
        self.remind_every = float(remind_every_usd if remind_every_usd is not None
                                  else _env("META_BUDGET_REMIND_EVERY_USD", "0") or 0)
        self.ledger = Path(ledger or _env("META_SPEND_LEDGER", "~/.simon/meta_spend.jsonl")).expanduser()

    def spent(self) -> float:
        if not self.ledger.exists():
            return 0.0
        return sum(json.loads(line)["usd"] for line in self.ledger.read_text().splitlines() if line.strip())

    def reserve(self, usd: float, what: str) -> None:
        """Refuse a call that would cross the limit (a limit of 0 or unset refuses all paid calls)."""
        total = self.spent()
        if usd > 0 and total + usd > self.limit:
            raise BudgetExceeded(f"{what}: ${usd:.4f} would take spend to ${total + usd:.2f}, "
                                 f"over META_BUDGET_USD=${self.limit:.2f} (ledger {self.ledger})")

    def record(self, usd: float, what: str, model: str) -> float:
        self.ledger.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.ledger.with_suffix(".lock")
        with lock_path.open("a") as lock:
            try:
                import fcntl

                fcntl.flock(lock, fcntl.LOCK_EX)
            except (ImportError, OSError):
                pass  # best effort: the read+append below is still one open
            before = self.spent()
            with self.ledger.open("a") as f:
                f.write(json.dumps({"ts": time.time(), "model": model, "what": what, "usd": usd}) + "\n")
        after = before + usd
        if self.remind_every > 0 and int(after // self.remind_every) > int(before // self.remind_every):
            print(f"[meta budget] spent ${after:.2f} of ${self.limit:.2f}", file=sys.stderr)
        return after


def _request(method, path, body=None, headers=None, timeout=600):
    key = _env("MODEL_API_KEY")
    if not key:
        raise RuntimeError("MODEL_API_KEY is not set (environment or .env)")
    req = urllib.request.Request(BASE_URL + path, data=body, method=method,
                                 headers={"Authorization": f"Bearer {key}", **(headers or {})})
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:500]
        raise RuntimeError(f"Meta API {method} {path}: HTTP {e.code}: {detail}") from None
    except urllib.error.URLError as e:
        raise RuntimeError(f"Meta API {method} {path}: {e.reason}") from None


def multipart(fields: dict, file_field: str, path: Path) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    parts = []
    for name, value in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{file_field}"; filename="{path.name}"\r\n'
                 f"Content-Type: application/octet-stream\r\n\r\n".encode() + path.read_bytes() + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def upload(path) -> str:
    """Upload a file (free) and return its file_id."""
    body, ctype = multipart({"purpose": "user_data"}, "file", Path(path))
    with _request("POST", "/files", body, {"Content-Type": ctype}) as r:
        return json.loads(r.read())["id"]


def sse_text_deltas(lines):
    """Yield output_text deltas from a /responses event stream (iterable of byte lines)."""
    event = None
    for raw in lines:
        line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
        if line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data = line[5:].strip()
            if data == "[DONE]":
                return
            payload = json.loads(data)
            kind = payload.get("type", event)
            if kind == "response.output_text.delta":
                yield payload["delta"]
            elif kind in ("error", "response.failed"):
                raise RuntimeError(f"Meta API stream error: {json.dumps(payload)[:500]}")


def respond(model: str, content: list, est_cost_usd: float, metadata=None, budget: Budget | None = None,
            what: str = "", **extra):
    """Stream a /responses call, yielding output_text deltas. The estimated cost is checked
    against the budget before the call and recorded as soon as the call is accepted."""
    budget = budget or Budget()
    what = what or model
    budget.reserve(est_cost_usd, what)
    body = {"model": model, "stream": True,
            "input": [{"type": "message", "role": "user", "content": content}], **extra}
    if metadata:
        body["metadata"] = metadata
    with _request("POST", "/responses", json.dumps(body).encode(),
                  {"Content-Type": "application/json", "Accept": "text/event-stream"}) as r:
        # Record as soon as the call is accepted: a caller that stops reading
        # early has still been charged, so the ledger must not wait for EOF.
        budget.record(est_cost_usd, what, model)
        yield from sse_text_deltas(r)
