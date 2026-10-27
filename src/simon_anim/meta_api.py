"""Meta Model API client.

Live HTTP calls run only when META_LIVE=1. `make check-4` does not import
this module. Open-weight runtimes (Muse Glimmer, Muse Spark Open) are a
separate opt-in via META_LOCAL=1 and a local base URL. Nothing here fabricates
a successful API body.

Chat completions follow the probed shape:

    POST {base}/chat/completions
    model muse-spark-1.3 (or another chat model)
    response.choices[0].message.content
    response.usage.prompt_tokens / completion_tokens / total_tokens
    response.usage.completion_tokens_details.reasoning_tokens
    response.usage.prompt_tokens_details.cached_tokens
    response.choices[0].finish_reason in {stop, length}

Muse Spark always reasons, and reasoning tokens consume max_tokens first.
This client floors max_tokens at 1024. That floor is not always enough:
live smoke of the Part 4 critique and plan hooks needed 2048, because
reasoning burned a 1024 budget and returned empty content. Those hooks
request 2048. A truncated body is still recorded on the spend ledger.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE_URL = "https://api.meta.ai/v1"
MIN_MAX_TOKENS = 1024

# Ballpark prices used for the spend ledger. Output includes reasoning tokens.
# prompt_tokens are billed entirely at the input rate (no cached discount).
PRICES = {
    "muse-spark-1.3": {"kind": "tokens", "in_per_mtok": 1.25, "out_per_mtok": 4.25},
    "muse-spark-1.2": {"kind": "tokens", "in_per_mtok": 1.25, "out_per_mtok": 4.25},
    "muse-spark-1.1": {"kind": "tokens", "in_per_mtok": 1.25, "out_per_mtok": 4.25},
    "muse-wonder-1.0": {"kind": "tokens", "in_per_mtok": 4.0, "out_per_mtok": 20.0},
    "muse-image-1.0": {"kind": "image", "usd": 0.01},
    "muse-voice-transcribe-1.0": {"kind": "audio_hour", "usd_per_hour": 0.18},
    "sam-3.1": {"kind": "image", "usd": 2.50 / 1000.0},
}

ROOT = Path(__file__).resolve().parents[2]
LEDGER_JSON = ROOT / "docs" / "meta-api-spend.json"
LEDGER_MD = ROOT / "docs" / "meta-api-spend.md"

ALERT_STEP_USD = 5.0


class MetaLiveDisabled(RuntimeError):
    """Raised when a live call is requested while META_LIVE is not set."""


class MetaConfigError(RuntimeError):
    """Raised when a live call is allowed but the key or URL is missing."""


class MetaAPIError(RuntimeError):
    """The API responded with an error or an unusable body. Not a fake success."""


class MetaTruncated(MetaAPIError):
    """finish_reason=length and message content is null. Raise max_tokens."""


def live_calls_allowed() -> bool:
    return os.environ.get("META_LIVE", "").strip().lower() in {"1", "true", "yes", "on"}


def local_calls_allowed() -> bool:
    return os.environ.get("META_LOCAL", "").strip().lower() in {"1", "true", "yes", "on"}


def api_key() -> str | None:
    for name in ("META_API_KEY", "MODEL_API_KEY"):
        value = os.environ.get(name)
        if value and value.strip():
            return value.strip()
    return None


def _require_live_key() -> str:
    if not live_calls_allowed():
        raise MetaLiveDisabled(
            "Meta Model API calls are off. Export META_LIVE=1 to enable them. "
            "make check-4 uses classical interpolation and does not need a key."
        )
    key = api_key()
    if not key:
        raise MetaConfigError(
            "META_LIVE=1 but neither META_API_KEY nor MODEL_API_KEY is set. "
            "Create a key at https://dev.meta.ai and export it in the shell that "
            "runs the command. Do not commit the key."
        )
    return key


def estimate_token_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    price = PRICES.get(model)
    if not price or price["kind"] != "tokens":
        return 0.0
    return (prompt_tokens / 1_000_000.0) * price["in_per_mtok"] + (
        completion_tokens / 1_000_000.0
    ) * price["out_per_mtok"]


def thresholds_crossed(previous: float, current: float, step: float = ALERT_STEP_USD) -> list[float]:
    """Return $5, $10, $15, ... thresholds that `current` newly reaches."""
    if current < step or current + 1e-12 < previous:
        return []
    start = int(previous // step) + 1
    end = int(current // step)
    return [step * n for n in range(start, end + 1)]


def load_ledger() -> dict:
    if not LEDGER_JSON.is_file():
        return {"cumulative_usd": 0.0, "alerts_crossed_usd": [], "calls": []}
    return json.loads(LEDGER_JSON.read_text(encoding="utf-8"))


def _render_markdown(ledger: dict) -> str:
    cumulative = float(ledger.get("cumulative_usd", 0.0))
    alerts = ledger.get("alerts_crossed_usd") or []
    lines = [
        "# Meta Model API spend ledger",
        "",
        "Estimated spend for live calls made by this repo. Classical `make check-4`",
        "does not call the API. Open-weight local runs are logged at $0.",
        "",
        f"Cumulative estimated spend: **${cumulative:.4f}**",
        "",
    ]
    if alerts:
        pretty = ", ".join(f"${int(v)}" if float(v).is_integer() else f"${v:.2f}" for v in alerts)
        lines.append(f"Alert thresholds crossed: **{pretty}**")
    else:
        lines.append("Alert thresholds crossed: none")
    lines.extend(
        [
            "",
            "Alerts fire when cumulative estimated spend reaches $5, $10, $15, and so on.",
            "Token prices used here: Muse Spark $1.25 / $4.25 per million input / output tokens",
            "(reasoning tokens count as output, and `completion_tokens` already includes them);",
            "Muse Wonder $4 / $20 per million; Muse Image $0.01 per image; Muse Voice Transcribe",
            "$0.18 per hour; SAM 3.1 $2.50 per 1,000 images. Cached prompt tokens are not discounted.",
            "",
            "A coordinator probe outside this repo made 3 tiny Muse Spark calls (<< $0.01).",
            "Those calls are not in the table below.",
            "",
            "| When (UTC) | Model | Call | Prompt tokens | Completion tokens | Reasoning tokens | Estimated USD | Cumulative |",
            "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    if not ledger.get("calls"):
        lines.append("| — | — | no live calls | 0 | 0 | 0 | 0.0000 | 0.0000 |")
    for call in ledger["calls"]:
        lines.append(
            "| {when} | {model} | {call} | {prompt} | {completion} | {reasoning} | {usd:.4f} | {cum:.4f} |".format(
                when=call.get("when", ""),
                model=call.get("model", ""),
                call=call.get("call", ""),
                prompt=call.get("prompt_tokens", "—"),
                completion=call.get("completion_tokens", "—"),
                reasoning=call.get("reasoning_tokens", "—"),
                usd=float(call.get("estimated_usd", 0.0)),
                cum=float(call.get("cumulative_usd", 0.0)),
            )
        )
    notes = ledger.get("notes") or []
    if notes:
        lines.extend(["", "## Alerts", ""])
        lines.extend(notes)
    lines.append("")
    return "\n".join(lines)


def record_spend(
    *,
    model: str,
    call: str,
    estimated_usd: float,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    reasoning_tokens: int | None = None,
    cached_tokens: int | None = None,
    detail: str | None = None,
) -> dict:
    """Append one call and rewrite the ledger. Returns alert info."""
    ledger = load_ledger()
    previous = float(ledger.get("cumulative_usd", 0.0))
    cumulative = previous + float(estimated_usd)
    crossed = thresholds_crossed(previous, cumulative)
    when = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    entry = {
        "when": when,
        "model": model,
        "call": call,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "reasoning_tokens": reasoning_tokens,
        "cached_tokens": cached_tokens,
        "estimated_usd": round(float(estimated_usd), 6),
        "cumulative_usd": round(cumulative, 6),
    }
    if detail:
        entry["detail"] = detail
    ledger.setdefault("calls", []).append(entry)
    ledger["cumulative_usd"] = round(cumulative, 6)
    already = [float(v) for v in ledger.get("alerts_crossed_usd") or []]
    notes = list(ledger.get("notes") or [])
    for threshold in crossed:
        if threshold not in already:
            already.append(threshold)
            label = int(threshold) if float(threshold).is_integer() else threshold
            notes.append(
                f"> **SPEND ALERT:** cumulative estimated spend crossed ${label} "
                f"(now ${cumulative:.4f}) at {when} on `{model}` / `{call}`."
            )
            print(
                f"SPEND ALERT: cumulative estimated Meta spend crossed ${label} "
                f"(now ${cumulative:.4f}).",
                flush=True,
            )
    ledger["alerts_crossed_usd"] = already
    ledger["notes"] = notes
    LEDGER_JSON.parent.mkdir(parents=True, exist_ok=True)
    LEDGER_JSON.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
    LEDGER_MD.write_text(_render_markdown(ledger), encoding="utf-8")
    return {"cumulative_usd": cumulative, "crossed_usd": crossed}


def _post_json(url: str, payload: dict, key: str, timeout: float = 120.0) -> dict:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:2000]
        raise MetaAPIError(f"HTTP {exc.code} from {url}: {body}") from exc
    except urllib.error.URLError as exc:
        raise MetaAPIError(f"request to {url} failed: {exc.reason}") from exc
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise MetaAPIError(f"response from {url} was not JSON") from exc
    if not isinstance(parsed, dict):
        raise MetaAPIError(f"response from {url} was not a JSON object")
    return parsed


def parse_chat_completion(payload: dict) -> dict:
    """Read the probed OpenAI chat.completion shape. Do not invent fields."""
    try:
        choice = payload["choices"][0]
        message = choice["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise MetaAPIError("chat completion is missing choices[0].message") from exc
    content = message.get("content")
    finish = choice.get("finish_reason")
    usage = payload.get("usage") or {}
    details = usage.get("completion_tokens_details") or {}
    prompt_details = usage.get("prompt_tokens_details") or {}
    parsed = {
        "content": content,
        "finish_reason": finish,
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "total_tokens": usage.get("total_tokens"),
        "reasoning_tokens": details.get("reasoning_tokens"),
        "cached_tokens": prompt_details.get("cached_tokens"),
        "model": payload.get("model"),
    }
    if content in (None, "") and finish == "length":
        raise MetaTruncated(
            "Muse returned finish_reason=length with empty content. Reasoning tokens "
            "consume max_tokens first. The client floor is 1024; live smoke of the "
            "Spark critique and Wonder plan needed 2048 before content was returned."
        )
    return parsed


def chat_completion(
    *,
    model: str,
    messages: list[dict],
    call: str,
    max_tokens: int = 1024,
    temperature: float = 0.2,
    base_url: str | None = None,
    local: bool = False,
) -> dict:
    """POST /v1/chat/completions. Records spend. Refuses to run unless gated."""
    if any(message.get("role") == "system" for message in messages):
        raise MetaConfigError("use the developer role, not system, for Meta chat messages")
    if max_tokens < MIN_MAX_TOKENS:
        max_tokens = MIN_MAX_TOKENS
    if local:
        if not local_calls_allowed():
            raise MetaLiveDisabled(
                "Local open-weight calls are off. Set META_LOCAL=1 and a base URL. "
                "No weights are downloaded by this repo."
            )
        if not base_url:
            raise MetaConfigError("local chat call requires base_url")
        key = os.environ.get("LOCAL_MODEL_API_KEY", "local")
        url = base_url.rstrip("/") + "/chat/completions"
    else:
        key = _require_live_key()
        url = (base_url or BASE_URL).rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    body = _post_json(url, payload, key)
    try:
        parsed = parse_chat_completion(body)
    except MetaTruncated:
        usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
        details = usage.get("completion_tokens_details") or {}
        prompt_details = usage.get("prompt_tokens_details") or {}
        prompt_tokens = int(usage.get("prompt_tokens") or 0)
        completion_tokens = int(usage.get("completion_tokens") or 0)
        cost = 0.0 if local else estimate_token_cost(model, prompt_tokens, completion_tokens)
        record_spend(
            model=model,
            call=f"{call}:truncated",
            estimated_usd=cost,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            reasoning_tokens=details.get("reasoning_tokens"),
            cached_tokens=prompt_details.get("cached_tokens"),
            detail="finish_reason=length with empty content",
        )
        raise
    prompt_tokens = int(parsed["prompt_tokens"] or 0)
    completion_tokens = int(parsed["completion_tokens"] or 0)
    cost = 0.0 if local else estimate_token_cost(model, prompt_tokens, completion_tokens)
    spend = record_spend(
        model=model,
        call=call,
        estimated_usd=cost,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        reasoning_tokens=parsed["reasoning_tokens"],
        cached_tokens=parsed["cached_tokens"],
    )
    parsed["estimated_usd"] = cost
    parsed["cumulative_usd"] = spend["cumulative_usd"]
    parsed["source"] = "local" if local else "meta"
    return parsed


def generate_image(*, prompt: str, call: str) -> dict:
    """POST /v1/images/generations. Cost is recorded only when an image is returned."""
    key = _require_live_key()
    body = _post_json(
        BASE_URL + "/images/generations",
        {"model": "muse-image-1.0", "prompt": prompt, "n": 1, "response_format": "b64_json"},
        key,
        timeout=180.0,
    )
    data = body.get("data")
    if not isinstance(data, list) or not data or not isinstance(data[0], dict):
        raise MetaAPIError("image response did not include data[0]")
    image = data[0].get("b64_json") or data[0].get("url")
    if not image:
        raise MetaAPIError("image response had neither b64_json nor url")
    spend = record_spend(model="muse-image-1.0", call=call, estimated_usd=0.01, detail="1 image")
    return {
        "source": "meta",
        "model": "muse-image-1.0",
        "b64_json": data[0].get("b64_json"),
        "url": data[0].get("url"),
        "estimated_usd": 0.01,
        "cumulative_usd": spend["cumulative_usd"],
    }


def transcribe_wav(*, wav_path: Path, call: str) -> dict:
    """POST /v1/asr/transcribe with multipart audio. Duration comes from the wav header."""
    key = _require_live_key()
    path = Path(wav_path)
    audio = path.read_bytes()
    seconds = _wav_duration_seconds(audio)
    boundary = "simon-part4-boundary"
    request_json = json.dumps(
        {"model": "muse-voice-transcribe-1.0", "audioEncoding": "WAV", "mode": "PUSH_TO_TALK"}
    ).encode("utf-8")
    parts = []
    parts.append(
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="request"\r\n'
        "Content-Type: application/json\r\n\r\n".encode("utf-8")
        + request_json
        + b"\r\n"
    )
    parts.append(
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="audio"; filename="{path.name}"\r\n'
        "Content-Type: audio/wav\r\n\r\n".encode("utf-8")
        + audio
        + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    body = b"".join(parts)
    request = urllib.request.Request(
        BASE_URL + "/asr/transcribe",
        data=body,
        headers={
            "Authorization": f"Bearer {key}",
            "Accept": "application/json",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=180.0) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:2000]
        raise MetaAPIError(f"HTTP {exc.code} from transcribe: {detail}") from exc
    except urllib.error.URLError as exc:
        raise MetaAPIError(f"transcribe request failed: {exc.reason}") from exc
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise MetaAPIError("transcribe response was not JSON") from exc
    text = _transcript_text(parsed)
    if text is None:
        raise MetaAPIError("transcribe response had no transcript text")
    cost = (seconds / 3600.0) * PRICES["muse-voice-transcribe-1.0"]["usd_per_hour"]
    spend = record_spend(
        model="muse-voice-transcribe-1.0",
        call=call,
        estimated_usd=cost,
        detail=f"{seconds:.3f}s audio",
    )
    return {
        "source": "meta",
        "model": "muse-voice-transcribe-1.0",
        "text": text,
        "duration_s": seconds,
        "estimated_usd": cost,
        "cumulative_usd": spend["cumulative_usd"],
    }


def segment_image(*, image_url: str, prompt: str, call: str) -> dict:
    """POST /v1/responses for sam-3.1. Returns the raw response; masks are not invented."""
    key = _require_live_key()
    body = _post_json(
        BASE_URL + "/responses",
        {
            "model": "sam-3.1",
            "input": [
                {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": prompt},
                        {"type": "input_image", "image_url": image_url},
                    ],
                }
            ],
        },
        key,
        timeout=180.0,
    )
    spend = record_spend(model="sam-3.1", call=call, estimated_usd=PRICES["sam-3.1"]["usd"], detail="1 image")
    return {
        "source": "meta",
        "model": "sam-3.1",
        "response": body,
        "estimated_usd": PRICES["sam-3.1"]["usd"],
        "cumulative_usd": spend["cumulative_usd"],
    }


def _wav_duration_seconds(blob: bytes) -> float:
    if len(blob) < 44 or blob[0:4] != b"RIFF" or blob[8:12] != b"WAVE":
        raise MetaAPIError("audio is not a WAV file; duration (and therefore price) is unknown")
    channels = int.from_bytes(blob[22:24], "little")
    rate = int.from_bytes(blob[24:28], "little")
    bits = int.from_bytes(blob[34:36], "little")
    data_bytes = None
    offset = 12
    while offset + 8 <= len(blob):
        chunk = blob[offset : offset + 4]
        size = int.from_bytes(blob[offset + 4 : offset + 8], "little")
        if chunk == b"data":
            data_bytes = size
            break
        offset += 8 + size + (size % 2)
    if not data_bytes or channels <= 0 or rate <= 0 or bits <= 0:
        raise MetaAPIError("could not read WAV duration")
    return data_bytes / (rate * channels * (bits / 8.0))


def _transcript_text(payload: dict) -> str | None:
    """Accept a few documented transcript containers. Return None if none are present."""
    if isinstance(payload.get("text"), str):
        return payload["text"]
    transcript = payload.get("transcript")
    if isinstance(transcript, str):
        return transcript
    if isinstance(transcript, dict) and isinstance(transcript.get("text"), str):
        return transcript["text"]
    turns = payload.get("turns")
    if isinstance(turns, list):
        bits = []
        for turn in turns:
            if isinstance(turn, dict) and isinstance(turn.get("text"), str):
                bits.append(turn["text"])
            elif isinstance(turn, str):
                bits.append(turn)
        if bits:
            return " ".join(bits)
    return None
