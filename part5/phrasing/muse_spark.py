"""The `muse-spark` backend: Muse Spark served by Baseten (ADR-0005).

One POST per fault to Baseten's OpenAI-compatible chat completions endpoint, model exactly
`meta-models/muse-spark-open-1026`. It is a reasoning model, so `max_tokens` stays well above 512:
a short budget is spent on reasoning and comes back as empty content (the one live smoke on
2026-10-29 spent 833 of 850 completion tokens on reasoning; the timed lines of the 2026-10-30
review spent 1200 to 3200 at the default reasoning effort; `reasoning_effort: low` brings it to
about 900 in 3 s).

The key is the file `~/.config/firm/operator-keys/BASETEN_API_KEY` (`PART5_BASETEN_KEY_FILE` for
tests). It is read at the call, stripped, and used for the `Authorization` header and nothing else:
never printed, logged, written, put in a reason, or stored beyond the request. Live calls need the
key file AND live mode (`--live`, `SIMON5_LIVE=1` or `META_LIVE=1`; #20, ADR-0008). A process makes
at most 30 calls a minute (`PART5_MUSE_PER_MINUTE`). Every call, whether it succeeds or not, appends one usage line
(token counts, model, UTC time, HTTP status; never the key or the text) to
`~/.simon/baseten_usage.jsonl` (`PART5_BASETEN_USAGE_FILE` for tests).
"""
import json
import os
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

from .local_llm import BackendError, chat_request, content, send, urllib_client

NAME = "muse-spark"
URL = "https://inference.baseten.co/v1/chat/completions"
MODEL = "meta-models/muse-spark-open-1026"
MAX_TOKENS = 2048
# Review 2026-10-30: at the default effort a call took 6 to 12 s and often passed the 10 s timeout.
OPTIONS = {"reasoning_effort": "low"}
KEY_FILE = "~/.config/firm/operator-keys/BASETEN_API_KEY"
USAGE_FILE = "~/.simon/baseten_usage.jsonl"
KEY_ENV, USAGE_ENV, LIVE_ENV = "PART5_BASETEN_KEY_FILE", "PART5_BASETEN_USAGE_FILE", "META_LIVE"
LIVE_ENVS = (LIVE_ENV, "SIMON5_LIVE")  # either switches live mode on (ADR-0008)
PER_MINUTE_ENV, PER_MINUTE = "PART5_MUSE_PER_MINUTE", 30
_calls = deque()  # monotonic times of this process's recent model calls, for the rate limit


def key_path():
    return Path(os.environ.get(KEY_ENV) or KEY_FILE).expanduser()


def usage_path():
    return Path(os.environ.get(USAGE_ENV) or USAGE_FILE).expanduser()


def model():
    return MODEL


def live_on(live=False):
    """True when live mode is on: the `--live` flag, `SIMON5_LIVE=1` or `META_LIVE=1`."""
    return bool(live) or any(os.environ.get(name) == "1" for name in LIVE_ENVS)


def unavailable(live=False):
    """None when live calls are allowed, else the reason they are not. Never reads the key."""
    if not key_path().is_file():
        return "no key"
    if not live_on(live):
        return f"live calls are off (use --live, SIMON5_LIVE=1 or {LIVE_ENV}=1)"
    return None


def _per_minute():
    try:
        return int(os.environ.get(PER_MINUTE_ENV, PER_MINUTE))
    except ValueError:
        return PER_MINUTE


def _take_slot(now):
    """Claim one of this process's calls for the minute ending `now`; BackendError when none is left."""
    while _calls and now - _calls[0] >= 60:
        _calls.popleft()
    if len(_calls) >= _per_minute():
        raise BackendError("rate limited")
    _calls.append(now)


def _read_key():
    try:
        key = key_path().read_text().strip()
    except (OSError, ValueError):
        raise BackendError("key file unreadable") from None
    if not key:
        raise BackendError("key file is empty")
    return key


def _open_ledger():
    """The ledger opened for appending BEFORE the call, so a spend that cannot be recorded is not made."""
    path = usage_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        return os.fdopen(os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600), "a")
    except OSError:
        raise BackendError("usage ledger not writable") from None


def _count(usage, *path):
    for step in path:
        usage = usage.get(step) if isinstance(usage, dict) else None
    return usage if isinstance(usage, int) and not isinstance(usage, bool) else None


def _usage_line(outcome):
    usage = (outcome.body or {}).get("usage")
    reasoning = _count(usage, "completion_tokens_details", "reasoning_tokens")
    return {"time": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "model": MODEL,
            "http_status": outcome.status,
            "prompt_tokens": _count(usage, "prompt_tokens"),
            "completion_tokens": _count(usage, "completion_tokens"),
            "reasoning_tokens": reasoning if reasoning is not None else _count(usage, "reasoning_tokens")}


def last_usage():
    """The newest ledger line as a dict, or None when there is none."""
    try:
        lines = usage_path().read_text().splitlines()
    except OSError:
        return None
    return json.loads(lines[-1]) if lines else None


def line(fault, *, timeout_s, client):
    """One line for one fault from Muse Spark; raises BackendError on any failure."""
    key = _read_key()
    _take_slot(time.monotonic())
    request = chat_request(URL, MODEL, fault, headers={"Authorization": f"Bearer {key}"},
                           max_tokens=MAX_TOKENS, timeout_s=timeout_s, options=OPTIONS)
    with _open_ledger() as ledger:
        outcome = send(client or urllib_client, request)
        try:
            ledger.write(json.dumps(_usage_line(outcome), sort_keys=True) + "\n")
        except OSError:
            raise BackendError("usage ledger not writable") from None
    if outcome.error:
        raise outcome.error
    return content(outcome.body)
