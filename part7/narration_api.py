"""Muse Voice Transcribe 1.0 client for trainer narration (docs/specs/narration.md).

One multipart POST to the Meta Model API `asr/transcribe` in ENDPOINTING mode, which returns the transcript and
`turns` with `startMs` and `endMs` (PUSH_TO_TALK returns the text with no turns). The key comes from `keys.read_key`,
the price from the audio length, and every call is appended to a spend ledger before the cap is checked again.
Nothing is invented: an error, an unreadable body or a body without turns raises `NarrationError`.
"""

from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
import time
from typing import Any, Callable
import urllib.error
import urllib.request
import wave

from part7 import config, keys

URL = os.environ.get("SIMON_META_API", "https://api.meta.ai/v1").rstrip("/") + "/asr/transcribe"  # SIMON_META_API: the judges' relay (deploy/judges/README.md)
MODEL = "muse-voice-transcribe-1.0"
USD_PER_HOUR = 0.18  # Meta's list price for the model, ledger estimate
BOUNDARY = "simon-part7-narration"
TIMEOUT_S = 180.0
KEY_NAME = "MODEL_API_KEY"


class NarrationError(RuntimeError):
    """The transcript could not be had (no key, cap reached, HTTP error, unusable body); never a job failure."""


def wav_seconds(path: Path | str) -> float:
    """Length of a PCM WAV file in seconds (the price is by the second of audio)."""
    try:
        with wave.open(str(path), "rb") as w:
            return w.getnframes() / float(w.getframerate())
    except (wave.Error, EOFError, OSError, ZeroDivisionError) as exc:
        raise NarrationError(f"audio is not a readable WAV file: {exc}") from None


def cost_usd(seconds: float) -> float:
    return seconds / 3600.0 * USD_PER_HOUR


def ledger_path(state: Path | str | None = None) -> Path:
    return config.state_root(state) / "narration" / "spend.jsonl"


def spent_usd(ledger: Path) -> float:
    """Sum of the estimated_usd of every line in the ledger (a damaged line counts as 0)."""
    total = 0.0
    try:
        lines = ledger.read_text(encoding="utf-8").splitlines()
    except OSError:
        return 0.0
    for line in lines:
        try:
            total += float(json.loads(line).get("estimated_usd") or 0.0)
        except (ValueError, AttributeError, TypeError):
            continue
    return total


def cap_usd() -> float | None:
    """The spend cap in USD; off (None) unless SIMON7_NARRATION_CAP_USD is a positive number."""
    try:
        value = float(os.environ.get("SIMON7_NARRATION_CAP_USD", ""))
    except ValueError:
        return None
    return value if value > 0 else None


def reserve(ledger: Path, entry: dict[str, Any], cap: float | None) -> None:
    """Check the cap and append `entry` as one step under a file lock, so two jobs cannot both pass the check.
    The line is written before the request is sent: a call that is billed and then times out or answers 5xx counts."""
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with ledger.with_name(ledger.name + ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            if cap is not None and spent_usd(ledger) + float(entry["estimated_usd"]) > cap:
                raise NarrationError(f"the narration spend cap of ${cap:.2f} would be passed")
            with ledger.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, sort_keys=True) + "\n")
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _body(audio: bytes, name: str) -> bytes:
    request = json.dumps({"model": MODEL, "audioEncoding": "WAV", "mode": "ENDPOINTING"}).encode("utf-8")
    head = (f"--{BOUNDARY}\r\nContent-Disposition: form-data; name=\"request\"\r\n"
            "Content-Type: application/json\r\n\r\n").encode("utf-8")
    mid = (f"\r\n--{BOUNDARY}\r\nContent-Disposition: form-data; name=\"audio\"; filename=\"{name}\"\r\n"
           "Content-Type: audio/wav\r\n\r\n").encode("utf-8")
    return head + request + mid + audio + f"\r\n--{BOUNDARY}--\r\n".encode("utf-8")


def parse_turns(payload: Any) -> list[dict[str, Any]]:
    """`[{start_s, end_s, text}]` from the response, in time order; turns with no text or no times are dropped."""
    raw = payload.get("turns") if isinstance(payload, dict) else None
    if not isinstance(raw, list):
        raise NarrationError("the transcript had no turns list")
    turns: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        text, start, end = item.get("transcript"), item.get("startMs"), item.get("endMs")
        nums = all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (start, end))
        if not isinstance(text, str) or not text.strip() or not nums or end <= start or start < 0:
            continue
        turns.append({"start_s": round(start / 1000.0, 3), "end_s": round(end / 1000.0, 3), "text": text.strip()})
    return sorted(turns, key=lambda t: t["start_s"])


def transcribe(
    wav_path: Path | str,
    *,
    ledger: Path | str | None = None,
    cap: float | None = None,
    call: str = "narration",
    keys_dir: Path | str | None = None,
    opener: Callable[..., Any] = urllib.request.urlopen,
    timeout: float = TIMEOUT_S,
) -> dict[str, Any]:
    """Transcribe `wav_path`; returns `{text, turns, duration_s, estimated_usd}`. Raises `NarrationError`."""
    key = keys.read_key(KEY_NAME, keys_dir=keys_dir)
    if not key:
        raise NarrationError("no Meta Model API key")
    seconds = wav_seconds(wav_path)
    price = cost_usd(seconds)
    book = Path(ledger) if ledger is not None else ledger_path()
    limit = cap if cap is not None else cap_usd()
    audio = Path(wav_path).read_bytes()
    reserve(book, {"when": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "model": MODEL, "call": call,
                   "audio_s": round(seconds, 3), "estimated_usd": round(price, 6)}, limit)
    req = urllib.request.Request(
        URL, data=_body(audio, Path(wav_path).name), method="POST",
        headers={"Authorization": f"Bearer {key}", "Accept": "application/json",
                 "Content-Type": f"multipart/form-data; boundary={BOUNDARY}"},
    )
    try:
        with opener(req, timeout=max(1.0, timeout)) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raise NarrationError(f"transcribe answered HTTP {exc.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise NarrationError(f"transcribe request failed: {type(exc).__name__}") from None
    try:
        payload = json.loads(raw)
    except ValueError:
        raise NarrationError("transcribe answer was not JSON") from None
    turns = parse_turns(payload)
    text = payload.get("transcript") if isinstance(payload.get("transcript"), str) else " ".join(t["text"] for t in turns)
    return {"text": text, "turns": turns, "duration_s": round(seconds, 3), "estimated_usd": round(price, 6)}
