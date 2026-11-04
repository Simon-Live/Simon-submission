"""The app's operator notices (docs/specs/observability.md "Operator notices").

Every notice leaves through `send`, in prod only, by the app's own mail sender to `SIMON7_OPS_NOTICE_TO` or else
`hello@<first prod host>`, which forwards to the operator. `clean` is applied to subject and body on every path, so
a notice can hold no account id, mail address, movement name, token, key value or IP address. `note_failure` turns a
failure rate into at most one notice per `COOLDOWN_S`. The cooldown is kept in the state folder, so a restart does not
send a second one.
"""

from __future__ import annotations

from collections import Counter, deque
import json
import logging
import os
from pathlib import Path
import re
import threading
import time

from part7 import applog, keys, mail

BODY_MAX = 1500
SUBJECT_MAX = 120
WINDOW_S = 600.0
THRESHOLD = 10  # env SIMON7_FAILURE_NOTICE_N: failures within WINDOW_S that raise a notice
COOLDOWN_S = 3600.0
STATE_FILE = "ops-notice-state.json"
_LABELLED = re.compile(r"(?i)\b(token|secret|password|passwd|api[_-]?key|authorization|cookie|bearer)\b(\s*[=:]\s*|\s+)(?:bearer\s+)?\S+")
_URL_CREDS = re.compile(r"\b([a-z][a-z0-9+.-]*://)[^/\s]*@")
_TOKEN_PATH = re.compile(r"((?:^|/)(?:api/shared|api/take-ar|signin)/)[^/\s?#\"]+")
_QUERY = re.compile(r"\?[^\s\"]*")
_LONG = re.compile(r"\b[A-Za-z0-9_-]{32,}\b")
_IP4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")

_LOCK = threading.Lock()
_HITS: deque[tuple[float, str]] = deque()


def clean(text: str, limit: int = BODY_MAX) -> str:
    """`text` as it may leave the server. Applied to every subject and body."""
    out = _URL_CREDS.sub(r"\1", keys.redact(str(text)))  # credentials in a URL go before the address mask reads them
    out = applog.scrub(out)
    out = _LABELLED.sub(lambda m: f"{m.group(1)}=<redacted>", out)
    out = _TOKEN_PATH.sub(r"\1<token>", out)
    out = _IP4.sub("<ip>", _LONG.sub("<token>", _QUERY.sub("", out)))
    return out[:limit]


def recipient() -> str:
    chosen = os.environ.get("SIMON7_OPS_NOTICE_TO", "").strip()
    if chosen:
        return chosen
    host = os.environ.get("SIMON7_PROD_HOSTS", "simon.live").split(",")[0].strip()
    return f"hello@{host.removeprefix('www.')}"


def send(subject: str, body: str, state: Path | str) -> bool:
    """Send one notice now and wait for the provider; True when it was accepted. Logged either way, without the address."""
    title = clean(subject, SUBJECT_MAX)
    if not mail.is_prod():
        applog.log(f"NOTICE not sent outside prod: {title}")
        return False
    sender = mail.Mailer(Path(state))
    sent = sender.send_notice_now(recipient(), f"[simon.live] {title}", clean(body))
    applog.log(f"NOTICE {'sent' if sent else 'NOT sent'}: {title}", level=logging.INFO if sent else logging.ERROR)
    return sent


def _claim(state: Path | str, now: float) -> bool:
    """True once per COOLDOWN_S across builds that share the state folder."""
    path = Path(state) / STATE_FILE
    try:
        last = float(json.loads(path.read_text(encoding="utf-8")).get("last", 0))
    except (OSError, ValueError, AttributeError, TypeError):
        last = 0.0
    if now - last < COOLDOWN_S:
        return False
    try:
        path.write_text(json.dumps({"last": now}), encoding="utf-8")
    except OSError:
        pass  # a notice matters more than its cooldown record
    return True


def _threshold() -> int:
    return int(applog.env_float("SIMON7_FAILURE_NOTICE_N", THRESHOLD))


def note_failure(label: str, state: Path | str | None, now: float | None = None) -> bool:
    """Count one failure. True when this one crossed the threshold and its notice was started."""
    if state is None:
        return False
    now = time.time() if now is None else now
    with _LOCK:
        _HITS.append((now, label))
        while _HITS and now - _HITS[0][0] >= WINDOW_S:
            _HITS.popleft()
        if len(_HITS) < _threshold() or not _claim(state, now):
            return False
        top = Counter(name for _, name in _HITS).most_common(5)
        total = len(_HITS)
    lines = "; ".join(f"{name}: {count}" for name, count in top)
    body = (f"{total} failures in the last {WINDOW_S / 60:.0f} minutes. Most frequent: {lines}. "
            f"Run `prod.sh failures <id>` on the server for the last hour. "
            f"The next notice comes after {COOLDOWN_S / 60:.0f} minutes at the earliest.")
    threading.Thread(target=send, args=("Failure rate is high", body, state), name="ops-notice", daemon=True).start()
    return True


def reset() -> None:
    """Forget the counted failures (tests, and `selfheal.configure`)."""
    with _LOCK:
        _HITS.clear()


def cli_notice(state: Path | str) -> int:
    """`part7 ops-notice`: send PROD_NOTICE_SUBJECT and PROD_NOTICE_BODY. Exit 0 accepted, 1 not."""
    subject, body = os.environ.get("PROD_NOTICE_SUBJECT", ""), os.environ.get("PROD_NOTICE_BODY", "")
    if not subject:
        print("ops-notice: PROD_NOTICE_SUBJECT is empty")
        return 2
    sent = send(subject, body, state)
    try:  # another process's notice: appended directly, so the serving process keeps its own log handler and rotation
        with (Path(state) / "part7.log").open("a", encoding="utf-8") as fh:
            fh.write(f"{applog.utc_stamp()} {'INFO' if sent else 'ERROR'} NOTICE {'sent' if sent else 'NOT sent'}: {clean(subject, SUBJECT_MAX)}\n")
    except OSError:
        pass  # the firm records the exit code as well
    return 0 if sent else 1
