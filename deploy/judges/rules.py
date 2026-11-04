"""The judges' relay's rules (deploy/judges/README.md): what it forwards, what each call costs, and when it stops.

Pure functions and constants, no Modal and no network, so tests/test_judges_relay.py checks them as they are. The relay
(deploy/judges/relay.py) holds Simon's Meta API key and runs Part 2 on Simon's Modal; anyone with the repo's link can
call it, so it forwards only the calls Simon makes, counts what they cost, and stops at the cap or the end of judging.
"""

from __future__ import annotations

from datetime import datetime, timezone
import os
import re

# Judging ends Nov 9, 2026, 11:59 PM ET (EST, UTC-5): the relay answers 410 after this. RELAY_ENDS (ISO 8601) moves it.
ENDS = datetime.fromisoformat(os.environ.get("RELAY_ENDS", "2026-11-10T04:59:00+00:00"))
CAP_USD = float(os.environ.get("RELAY_CAP_USD", "200"))   # every judge together; the relay refuses past it
IP_DAY_USD = float(os.environ.get("RELAY_IP_DAY_USD", "25"))   # one address in one UTC day
IP_PER_MINUTE = int(os.environ.get("RELAY_IP_PER_MINUTE", "60"))   # requests from one address in one minute
ALERT_FRACTIONS = (0.5, 0.8, 1.0)   # ntfy alerts as spending passes these parts of the cap
MAX_BODY_BYTES = 140 * 1024 * 1024   # a 95 MB take, base64-encoded for Part 2, with room for the request around it

# Meta API calls Simon makes (Part 1 meta_client.py, Part 5 opinion/meta_api.py, Part 7 history_api.py and
# narration_api.py): method and path under /v1. Anything else is refused, so the key cannot be used for other work.
ALLOWED_CALLS = (
    ("POST", re.compile(r"^files$")),
    ("DELETE", re.compile(r"^files/[A-Za-z0-9_.:-]{1,200}$")),
    ("POST", re.compile(r"^responses$")),
    ("POST", re.compile(r"^responses/input_tokens$")),
    ("POST", re.compile(r"^asr/transcribe$")),
    ("POST", re.compile(r"^images/edits$")),   # Muse Image: "You, doing it right" (part7/muse_fix_api.py)
)
MODELS = ("sam-3.1", "muse-spark-1.3", "muse-wonder-1.0", "muse-voice-transcribe-1.0", "muse-image-1.0")

# USD, the rates the parts already record (Part 1 keyframe_finder/spend.py): tokens per million, SAM 3.1 per frame.
RATES = {
    "sam-3.1": {"frame": 0.20 / 1000},
    "muse-spark-1.3": {"input_mtok": 1.25, "cached_input_mtok": 0.15, "output_mtok": 4.25},
    "muse-wonder-1.0": {"input_mtok": 4.00, "cached_input_mtok": 0.20, "output_mtok": 20.00},
    "muse-voice-transcribe-1.0": {"hour": 0.18},
}
# What a call is counted at before its answer says more: a SAM 3.1 track of a 90 s take at 30 fps (2,700 frames),
# a large Muse request, a 5 min transcript. A streamed answer keeps this figure, so it is set high.
RESERVE_USD = {"sam-3.1": 0.60, "muse-spark-1.3": 0.10, "muse-wonder-1.0": 0.40, "muse-voice-transcribe-1.0": 0.02,
               "muse-image-1.0": 0.15}   # Muse Image's price per picture is not published here: counted at this figure
FREE_PATHS = ("files", "responses/input_tokens")   # uploads, deletes and token counts are not billed

# Part 2 on Modal's L40S: $1.95 an hour (Modal pricing), counted 1.5x for start-up and the idle window after a run.
PART2_USD_PER_SECOND = 1.95 / 3600 * 1.5
PART2_RESERVE_USD = 0.75   # counted when a Part 2 run starts; settled from its measured time when it ends


# Part 2 on Modal holds its own Meta key: a Meta-API tracker there would spend it without the relay counting, so
# every Part 2 run through the relay tracks on Modal's GPU (SAM 3.1 weights in the image, no Meta call).
LOCAL_TRACKERS = ("local-sam31", "local-open", "bytetrack")
RELAY_TRACKER = "local-sam31"


def part2_argv(argv: list[str]) -> list[str]:
    """`argv` with any tracker that is not a GPU one swapped for local-sam31."""
    out = list(argv)
    for i, flag in enumerate(out[:-1]):
        if flag == "--tracker" and out[i + 1] not in LOCAL_TRACKERS:
            out[i + 1] = RELAY_TRACKER
    return out


# When run.sh starts (its health check says start=1), Part 2's GPU container is kept warm for an hour, so the judge's
# first take skips the model load (about 50 s). A ping every 4 minutes keeps it inside Part 2's 5-minute idle window.
WARM_MINUTES = int(os.environ.get("RELAY_WARM_MINUTES", "60"))
# Warm-ups start with judging, Nov 5, 2026, 12:00 AM ET (EST, UTC-5); before that a start does not warm Part 2.
WARM_FROM = datetime.fromisoformat(os.environ.get("RELAY_WARM_FROM", "2026-11-05T05:00:00+00:00"))
WARM_PING_S = 240
WARM_USD_PER_MINUTE = 1.95 / 60   # the L40S, counted against the cap like any GPU time


def warm_extension(now_s: float, warm_until_s: float) -> float:
    """Seconds of extra warm time a start adds: up to WARM_MINUTES from now, nothing already covered; none before
    WARM_FROM."""
    if now_s < WARM_FROM.timestamp():
        return 0.0
    return max(0.0, now_s + WARM_MINUTES * 60 - max(now_s, warm_until_s))


def is_open(now: datetime | None = None) -> bool:
    """True until the end of judging."""
    return (now or datetime.now(timezone.utc)) < ENDS


def allowed(method: str, path: str, model: str | None) -> str | None:
    """None when the relay forwards this call, else why it does not. `path` is under /v1, without a leading slash."""
    method = method.upper()
    if not any(m == method and rx.match(path) for m, rx in ALLOWED_CALLS):
        return f"{method} /v1/{path} is not a call Simon makes"
    if path in ("responses", "responses/input_tokens", "asr/transcribe", "images/edits"):
        if model not in MODELS:
            return f"model {model!r} is not one Simon uses"
        if path == "asr/transcribe" and model != "muse-voice-transcribe-1.0":
            return "asr/transcribe takes only muse-voice-transcribe-1.0"
        if (path == "images/edits") != (model == "muse-image-1.0"):
            return "muse-image-1.0 goes only to images/edits"
    return None


def reserve(path: str, model: str | None) -> float:
    """USD counted when a call is forwarded, before its answer is known."""
    if path.startswith(FREE_PATHS) or path.startswith("files/"):
        return 0.0
    return RESERVE_USD.get(model or "", 0.0)


def cost_from_usage(model: str, usage: dict | None) -> float | None:
    """USD for a finished call from the `usage` block of its answer, or None when the answer does not say."""
    if not isinstance(usage, dict):
        return None
    rate = RATES.get(model)
    if not rate:
        return None
    if "frame" in rate:
        frames = usage.get("frames") or usage.get("billed_frames") or usage.get("video_frames")
        return float(frames) * rate["frame"] if isinstance(frames, (int, float)) else None
    if "hour" in rate:
        seconds = usage.get("seconds") or usage.get("duration_s") or usage.get("audio_seconds")
        return float(seconds) / 3600 * rate["hour"] if isinstance(seconds, (int, float)) else None
    inp, out = usage.get("input_tokens"), usage.get("output_tokens")
    if not isinstance(inp, (int, float)) or not isinstance(out, (int, float)):
        return None
    details = usage.get("input_tokens_details") or {}
    cached = details.get("cached_tokens", 0) if isinstance(details, dict) else 0
    cached = cached if isinstance(cached, (int, float)) else 0
    return ((inp - cached) * rate["input_mtok"] + cached * rate["cached_input_mtok"] + out * rate["output_mtok"]) / 1e6


def part2_cost(seconds: float) -> float:
    """USD for a Part 2 run that took `seconds` on Modal."""
    return max(0.0, seconds) * PART2_USD_PER_SECOND


def refusal(spent: float, ip_spent_today: float, ip_requests_this_minute: int, cost: float, now: datetime | None = None) -> tuple[int, str] | None:
    """(HTTP status, reason) when the relay must refuse a call counted at `cost`, else None."""
    if not is_open(now):
        return (410, f"judging has ended ({ENDS.isoformat()}); the relay is closed")
    if spent + cost > CAP_USD:
        return (402, f"the judges' budget of ${CAP_USD:.0f} is spent; the relay is closed")
    if ip_spent_today + cost > IP_DAY_USD:
        return (429, f"this address has used ${IP_DAY_USD:.0f} today; try again tomorrow (UTC)")
    if ip_requests_this_minute >= IP_PER_MINUTE:
        return (429, "too many requests from this address; wait a minute")
    return None


def alerts_due(before: float, after: float, sent: list[float]) -> list[float]:
    """The alert fractions spending passed going from `before` to `after` USD, not already in `sent`."""
    return [f for f in ALERT_FRACTIONS if before < f * CAP_USD <= after and f not in sent]
