"""Meta Model API calls. The key is loaded from .env and never printed."""

import json
import uuid
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from keyframe_finder.sam_parse import BoxParser
from keyframe_finder.spend import estimate, record, require_budget

ROOT = Path(__file__).resolve().parents[1]
API = "https://api.meta.ai/v1"
SPARK = "muse-spark-1.3"
SAM = "sam-3.1"


def api_key():
    env_path = ROOT / ".env"
    if not env_path.exists():
        raise RuntimeError("MODEL_API_KEY is missing. Add it to .env.")
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, value = stripped.split("=", 1)
        if name.strip() == "MODEL_API_KEY":
            key = value.strip().strip('"').strip("'")
            if not key:
                raise RuntimeError("MODEL_API_KEY is empty in .env.")
            return key
    raise RuntimeError("MODEL_API_KEY is missing from .env.")


def _request(method, path, body=None, headers=None, timeout=120):
    req_headers = {"Authorization": f"Bearer {api_key()}"}
    if headers:
        req_headers.update(headers)
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        req_headers["Content-Type"] = "application/json"
    request = Request(API + path, data=data, headers=req_headers, method=method)
    try:
        return urlopen(request, timeout=timeout)
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:2000]
        raise RuntimeError(f"Meta API {exc.code} on {path}: {detail}") from None


def _multipart(path):
    boundary = "----simon" + uuid.uuid4().hex
    file_bytes = Path(path).read_bytes()
    filename = Path(path).name
    chunks = [
        f"--{boundary}\r\n".encode(),
        b'Content-Disposition: form-data; name="purpose"\r\n\r\n',
        b"user_data\r\n",
        f"--{boundary}\r\n".encode(),
        (
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            "Content-Type: video/mp4\r\n\r\n"
        ).encode(),
        file_bytes,
        f"\r\n--{boundary}--\r\n".encode(),
    ]
    return boundary, b"".join(chunks)


def upload_video(path):
    boundary, payload = _multipart(path)
    request = Request(
        API + "/files",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key()}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=300) as response:
            file_obj = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:2000]
        raise RuntimeError(f"Meta API {exc.code} on /files: {detail}") from None
    if "id" not in file_obj:
        raise RuntimeError("File upload did not return an id.")
    return file_obj["id"]


def delete_file(file_id):
    try:
        with _request("DELETE", f"/files/{file_id}", timeout=60):
            return
    except RuntimeError:
        return


def _iter_sse(response):
    buffer = b""
    while True:
        chunk = response.read(65536)
        if not chunk:
            break
        buffer += chunk
        while b"\n" in buffer:
            line, buffer = buffer.split(b"\n", 1)
            yield line.rstrip(b"\r").decode("utf-8", errors="replace")
    if buffer.strip():
        yield buffer.decode("utf-8", errors="replace")


def _stream(body, timeout):
    request = Request(
        API + "/responses",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key()}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        },
        method="POST",
    )
    try:
        response = urlopen(request, timeout=timeout)
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:2000]
        raise RuntimeError(f"Meta API {exc.code} on /responses: {detail}") from None
    return response


def track_people(file_id, frame_count):
    """Stream SAM 3.1 person tracks. Returns observations and the billed frame count."""
    billed = max(50, int(frame_count))
    cost = estimate(SAM, frame=billed)
    require_budget(cost, f"SAM 3.1 on {billed} frames (${cost:.2f})")
    body = {
        "model": SAM,
        "stream": True,
        "metadata": {"include_confidence": "true", "mask_encoding": "one_bit"},
        "input": [
            {
                "type": "message",
                "role": "user",
                "content": [
                    {"type": "input_text", "text": "person"},
                    {"type": "input_video", "file_id": file_id},
                ],
            }
        ],
    }
    parser = BoxParser()
    usage = {}
    announced = 0
    with _stream(body, timeout=1800) as response:
        for line in _iter_sse(response):
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if not data or data == "[DONE]":
                continue
            event = json.loads(data)
            kind = event.get("type", "")
            if kind == "response.output_text.delta":
                parser.feed(event.get("delta") or "")
                if parser.frames >= announced + 200:
                    announced = parser.frames
                    print(f"  SAM frames {parser.frames}", flush=True)
            elif kind == "response.completed":
                usage = (event.get("response") or {}).get("usage") or event.get("usage") or {}
            elif kind in {"error", "response.failed"} or event.get("error"):
                raise RuntimeError(f"SAM 3.1 failed: {event.get('error') or event}")
    billed_frames = int(usage.get("video_frames_processed") or billed)
    actual = estimate(SAM, frame=billed_frames)
    warnings = record(actual, f"SAM 3.1 person track, {billed_frames} frames", model=SAM)
    return parser.tracks, warnings


def count_spark_tokens(file_id, prompt):
    body = {
        "model": SPARK,
        "input": [
            {
                "type": "message",
                "role": "user",
                "content": [
                    {"type": "input_text", "text": prompt},
                    {"type": "input_file", "file_id": file_id},
                ],
            }
        ],
    }
    with _request("POST", "/responses/input_tokens", body, timeout=300) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if "input_tokens" in payload:
        return int(payload["input_tokens"])
    usage = payload.get("usage") or payload
    return int(usage.get("input_tokens") or usage.get("total_tokens") or 0)


def name_sections(file_id, duration_s):
    prompt = (
        "This is a movement video. List each exercise or dance phrase in time order. "
        "Return only JSON with this shape: "
        '{"sections":[{"movement":"squat","start_s":0,"end_s":10,'
        '"phase_names":["start","bottom","top"]}]}. '
        "phase_names must be 3 or 5 snake_case poses in time order inside one repetition. "
        f"Times are seconds from the start. The clip is {duration_s:.1f} seconds long. "
        "Cover the whole clip. Do not name individual people."
    )
    input_tokens = count_spark_tokens(file_id, prompt)
    output_tokens = 2000
    cost = estimate(
        SPARK,
        input_mtok=input_tokens / 1_000_000,
        cached_input_mtok=0,
        output_mtok=output_tokens / 1_000_000,
    )
    require_budget(
        cost,
        f"Muse Spark on this clip (~{input_tokens} input tokens, ${cost:.2f})",
    )
    body = {
        "model": SPARK,
        "max_output_tokens": output_tokens,
        "reasoning": {"effort": "low"},
        "input": [
            {
                "type": "message",
                "role": "user",
                "content": [
                    {"type": "input_text", "text": prompt},
                    {"type": "input_file", "file_id": file_id},
                ],
            }
        ],
    }
    with _request("POST", "/responses", body, timeout=600) as response:
        payload = json.loads(response.read().decode("utf-8"))
    usage = payload.get("usage") or {}
    details = usage.get("input_tokens_details") or {}
    cached = int(details.get("cached_tokens") or 0)
    used_in = int(usage.get("input_tokens") or input_tokens)
    used_out = int(usage.get("output_tokens") or 0)
    actual = estimate(
        SPARK,
        input_mtok=max(0, used_in - cached) / 1_000_000,
        cached_input_mtok=cached / 1_000_000,
        output_mtok=used_out / 1_000_000,
    )
    warnings = record(actual or 0, "Muse Spark phase names", model=SPARK)
    text = _output_text(payload)
    return text, warnings


def _output_text(payload):
    chunks = []
    for item in payload.get("output") or []:
        if isinstance(item, str):
            chunks.append(item)
            continue
        for content in item.get("content") or []:
            if isinstance(content, str):
                chunks.append(content)
            elif isinstance(content, dict):
                chunks.append(content.get("text") or "")
    if chunks:
        return "\n".join(chunks)
    return payload.get("output_text") or ""
