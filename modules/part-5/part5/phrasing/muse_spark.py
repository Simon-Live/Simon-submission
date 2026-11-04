"""The `muse-spark` backend: Muse Spark served by Baseten (ADR-0005).

One POST per fault to Baseten's OpenAI-compatible chat completions endpoint, model exactly
`meta-models/muse-spark-open-1026`. An analysis in a language other than English makes one more POST, `complete`, for its
cues (TICKET-080), through the same key, rate limit and ledger. It is a reasoning model, so `max_tokens` stays well above 512:
a short budget is spent on reasoning and comes back as empty content (the one live smoke on
2026-10-29 spent 833 of 850 completion tokens on reasoning; the timed lines of the 2026-10-30
review spent 1200 to 3200 at the default reasoning effort; `reasoning_effort: low` brings it to
about 900 in 3 s).

The key is the file `~/.config/firm/operator-keys/BASETEN_API_KEY` (`PART5_BASETEN_KEY_FILE` for
tests). It is read at the call, stripped, and used for the `Authorization` header and nothing else:
never printed, logged, written, put in a reason, or stored beyond the request. Live calls need the
key file AND live mode (`--live`, `SIMON5_LIVE=1` or `META_LIVE=1`; #20, ADR-0008). A process makes
at most 30 calls a minute (`PART5_MUSE_PER_MINUTE`), counted under a lock because calls run on a thread pool. Every call, whether it succeeds or not, appends one usage line
(token counts, model, UTC time, HTTP status; never the key or the text) to
`~/.simon/baseten_usage.jsonl` (`PART5_BASETEN_USAGE_FILE` for tests).

The key file and ledger helpers (`path_of`, `unavailable_for`, `read_key_from`, `open_ledger_at`, `append_line`,
`utc_now`) are shared with the Meta Model API client of the second opinion (`opinion.meta_api`), which keeps its own
key and ledger files: each caller names the file and the error to raise.
"""
import json
import os
import threading
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

try:
    import fcntl
except ImportError:   # not a POSIX host: no cross-process lock, the in-process checks still hold
    fcntl = None

from .lang import EN
from .local_llm import BackendError, chat_request, content, raw_request, send, urllib_client

NAME = "muse-spark"
URL = "https://inference.baseten.co/v1/chat/completions"
MODEL = "meta-models/muse-spark-open-1026"
MAX_TOKENS = 2048
BATCH_MAX_TOKENS = 6000   # TICKET-080: one call carries every cue of an analysis (about 30 texts); most of it is reasoning
# Review 2026-10-30: at the default effort a call took 6 to 12 s and often passed the 10 s timeout.
OPTIONS = {"reasoning_effort": "low"}
KEY_FILE = "~/.config/firm/operator-keys/BASETEN_API_KEY"
USAGE_FILE = "~/.simon/baseten_usage.jsonl"
KEY_ENV, USAGE_ENV, LIVE_ENV = "PART5_BASETEN_KEY_FILE", "PART5_BASETEN_USAGE_FILE", "META_LIVE"
LIVE_ENVS = (LIVE_ENV, "SIMON5_LIVE")  # either switches live mode on (ADR-0008)
PER_MINUTE_ENV, PER_MINUTE = "PART5_MUSE_PER_MINUTE", 30
_calls = deque()  # monotonic times of this process's recent model calls, for the rate limit
_slot_lock = threading.Lock()  # phrasing runs calls on a thread pool: the limit is claimed under it
_ledger_lock = threading.Lock()  # and each ledger line is appended under it
LOCK_POLL_S = 0.05  # how often a process waiting for a locked ledger looks again


def path_of(env, default):
    """The file named by the variable `env`, else the built-in `default`, with `~` expanded."""
    return Path(os.environ.get(env) or default).expanduser()


def key_path():
    return path_of(KEY_ENV, KEY_FILE)


def usage_path():
    return path_of(USAGE_ENV, USAGE_FILE)


def model():
    return MODEL


def live_on(live=False):
    """True when live mode is on: the `--live` flag, `SIMON5_LIVE=1` or `META_LIVE=1`."""
    return bool(live) or any(os.environ.get(name) == "1" for name in LIVE_ENVS)


def unavailable_for(key_file, live=False):
    """None when a live call using the key in `key_file` is allowed, else the reason. Never reads the key."""
    if not key_file.is_file():
        return "no key"
    if not live_on(live):
        return f"live calls are off (use --live, SIMON5_LIVE=1 or {LIVE_ENV}=1)"
    return None


def unavailable(live=False):
    """None when live calls are allowed, else the reason they are not. Never reads the key."""
    return unavailable_for(key_path(), live)


def read_key_from(key_file, error):
    """The key in `key_file`, stripped; raises `error("key file unreadable")` or `error("key file is empty")`."""
    try:
        key = key_file.read_text().strip()
    except (OSError, ValueError):
        raise error("key file unreadable") from None
    if not key:
        raise error("key file is empty")
    return key


def _lock(ledger, wait_s):
    """Take an exclusive lock on the open `ledger`, waiting up to `wait_s` seconds; False when it stayed taken."""
    if fcntl is None:
        return True
    deadline = time.monotonic() + wait_s
    while True:
        try:
            fcntl.flock(ledger.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except BlockingIOError:
            if time.monotonic() >= deadline:
                return False
            time.sleep(LOCK_POLL_S)


def open_ledger_at(path, error, lock_wait_s=None):
    """`path` opened for appending BEFORE the call (created 0600, its directory made), so a spend that cannot be
    recorded is not made; `error("usage ledger not writable")` when it cannot be opened.

    With `lock_wait_s` the file is also locked exclusively until it is closed, so one process's check of the ledger's
    total and the call it allows cannot be interleaved with another's; `error("usage ledger busy")` after waiting
    that many seconds.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        ledger = os.fdopen(os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600), "a")
    except OSError:
        raise error("usage ledger not writable") from None
    if lock_wait_s is None:
        return ledger
    try:
        locked = _lock(ledger, lock_wait_s)
    except OSError:
        ledger.close()
        raise error("usage ledger not writable") from None
    if not locked:
        ledger.close()
        raise error("usage ledger busy")
    return ledger


def utc_now():
    """The time of a ledger line: UTC, to the second, `2026-11-01T05:40:00Z`."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def append_line(ledger, line, error):
    """Write `line` (a dict) to the open `ledger` as one JSON line and flush it; `error("usage ledger not writable")`
    when it cannot be written. The one place either client writes a ledger line."""
    try:
        ledger.write(json.dumps(line, sort_keys=True) + "\n")
        ledger.flush()
    except OSError:
        raise error("usage ledger not writable") from None


def _per_minute():
    try:
        return int(os.environ.get(PER_MINUTE_ENV, PER_MINUTE))
    except ValueError:
        return PER_MINUTE


def _take_slot(now):
    """Claim one of this process's calls for the minute ending `now`; BackendError when none is left."""
    with _slot_lock:
        while _calls and now - _calls[0] >= 60:
            _calls.popleft()
        if len(_calls) >= _per_minute():
            raise BackendError("rate limited")
        _calls.append(now)


def _read_key():
    return read_key_from(key_path(), BackendError)


def _open_ledger():
    return open_ledger_at(usage_path(), BackendError)


def _count(usage, *path):
    for step in path:
        usage = usage.get(step) if isinstance(usage, dict) else None
    return usage if isinstance(usage, int) and not isinstance(usage, bool) else None


def _usage_line(outcome):
    usage = (outcome.body or {}).get("usage")
    reasoning = _count(usage, "completion_tokens_details", "reasoning_tokens")
    return {"time": utc_now(), "model": MODEL,
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


def _post(build, client):
    """The reply to the request `build(headers)` makes: the key is read, a rate-limit slot taken and the ledger opened
    before the call, one ledger line written after it whether it succeeded or not; raises BackendError on any failure."""
    key = _read_key()
    _take_slot(time.monotonic())
    request = build({"Authorization": f"Bearer {key}"})
    with _open_ledger() as ledger:
        outcome = send(client or urllib_client, request)
        with _ledger_lock:
            append_line(ledger, _usage_line(outcome), BackendError)
    if outcome.error:
        raise outcome.error
    return content(outcome.body)


def line(fault, *, timeout_s, client, shape=0, language=EN):
    """One reply for one fault from Muse Spark (a JSON pair for a language other than English); raises
    BackendError on any failure."""
    return _post(lambda headers: chat_request(URL, MODEL, fault, headers=headers, max_tokens=MAX_TOKENS,
                                              timeout_s=timeout_s, options=OPTIONS, shape=shape, language=language),
                 client)


def complete(chat, *, timeout_s, client):
    """One reply to the chat messages `chat` from Muse Spark (the cues of TICKET-080: a batch of texts, so the allowance
    is BATCH_MAX_TOKENS); the same key, rate limit and ledger as `line`; raises BackendError on any failure."""
    return _post(lambda headers: raw_request(URL, MODEL, chat, headers=headers, max_tokens=BATCH_MAX_TOKENS,
                                             timeout_s=timeout_s, options=OPTIONS), client)
