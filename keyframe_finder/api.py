"""Meta Model API client. The key is read from .env and never printed."""

import json
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://api.meta.ai/v1"


def api_key():
    text = (ROOT / ".env").read_text(encoding="utf-8")
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name.strip() == "MODEL_API_KEY":
            key = value.strip().strip('"').strip("'")
            if not key:
                break
            return key
    raise RuntimeError("MODEL_API_KEY is missing from .env")


def _headers(content_type=None, accept=None):
    headers = {"Authorization": f"Bearer {api_key()}"}
    if content_type:
        headers["Content-Type"] = content_type
    if accept:
        headers["Accept"] = accept
    return headers


def _error(exc):
    detail = exc.read().decode("utf-8", "replace")[:2000]
    return RuntimeError(f"Meta API {exc.code}: {detail}")


def post_json(path, payload, timeout=600):
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        BASE + path,
        data=body,
        headers=_headers("application/json"),
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise _error(exc) from None


def upload_video(path):
    path = Path(path)
    boundary = "----SimonKeyframeBoundary"
    filename = path.name.replace('"', "")
    head = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="purpose"\r\n\r\n'
        f"user_data\r\n"
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: video/mp4\r\n\r\n"
    ).encode("utf-8")
    tail = f"\r\n--{boundary}--\r\n".encode("utf-8")
    body = head + path.read_bytes() + tail
    request = urllib.request.Request(
        BASE + "/files",
        data=body,
        headers=_headers(f"multipart/form-data; boundary={boundary}"),
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=600) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise _error(exc) from None
    if "id" not in payload:
        raise RuntimeError("file upload did not return an id")
    return payload["id"]


def open_stream(payload, timeout=1800):
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        BASE + "/responses",
        data=body,
        headers=_headers("application/json", "text/event-stream"),
        method="POST",
    )
    try:
        return urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.HTTPError as exc:
        raise _error(exc) from None


def iter_sse(response):
    for raw in response:
        line = raw.decode("utf-8", "replace").strip()
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if not data or data == "[DONE]":
            continue
        yield json.loads(data)
