"""A timed send probe: one real mail to a sink address, so a whole-mail outage is seen before a visitor meets it.

The operator sets `SIMON7_MAIL_PROBE_TO` (an address of theirs, or a provider test address) in the prod environment;
there is no default and none is invented. Without it the probe is off and `status` says so. With it, every
`SIMON7_MAIL_PROBE_EVERY_S` seconds (default 3600) the app sends one plain mail through its own sender and writes
`<state>/mail-probe.json` (`state`: `ok`, `failing` after `FAIL_LIMIT` misses in a row, or `waiting` before the first try).
A miss logs `ANOMALY mail_probe_failed`, which opens the `mail_send` self-heal check; a success closes it.

The alert must not depend on the mail path it watches, so it is not a mail: the answer is in the direct-local
`api/health` (`mail_probe`), in the file, and in `python -m part7 mail-probe --state DIR` (exit 0 ok, 1 failing, 3 off),
which the firm's watchdog can read (docs/specs/mail-delivery.md "Probe"). The probe counts what the provider accepts;
whether the sink's inbox received it is the operator's to look at.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import threading
import time
from typing import Any

from part7 import applog, mail

ENV_TO, ENV_EVERY = "SIMON7_MAIL_PROBE_TO", "SIMON7_MAIL_PROBE_EVERY_S"
DEFAULT_EVERY_S = 3600.0
FIRST_DELAY_S = 120.0  # after a start: the app is up and the first mail path is warm
FAIL_LIMIT = 2
FILE = "mail-probe.json"
SUBJECT = "[simon.live] mail probe"
BODY = "This is the timed mail probe of simon.live. It carries no data and needs no answer."


def target() -> str | None:
    """The sink address from the environment, or None (probe off). Only a plain `local@domain.tld` counts."""
    raw = os.environ.get(ENV_TO, "").strip()
    local, _, domain = raw.partition("@")
    ok = bool(local) and "." in domain and not any(c.isspace() or c in "<>,;\"" for c in raw) and raw.count("@") == 1
    return raw if ok else None


def every_s() -> float:
    return max(60.0, applog.env_float(ENV_EVERY, DEFAULT_EVERY_S))


def _read(state: Path | str) -> dict[str, Any]:
    try:
        doc = json.loads((Path(state) / FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def status(state: Path | str) -> dict[str, Any]:
    """`{state, why, last_try, last_ok, failures, every_s}`; `state` is `off`, `waiting`, `ok` or `failing`. Never an address."""
    if target() is None:
        return {"state": "off", "why": f"{ENV_TO} is not set; no probe runs"}
    doc = _read(state)
    failures = int(doc.get("failures", 0) or 0)
    now = "failing" if failures >= FAIL_LIMIT else "ok" if doc.get("last_ok") and failures == 0 else "waiting" if not doc else "ok"
    return {"state": now, "last_try": doc.get("last_try"), "last_ok": doc.get("last_ok"), "failures": failures, "every_s": every_s()}


def _write(state: Path | str, doc: dict[str, Any]) -> None:
    path = Path(state) / FILE
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        json.dump(doc, out)
    os.replace(tmp, path)


def run_once(state: Path | str, sender: Any = None, now: float | None = None) -> str:
    """Send one probe; returns the new status state. `off` when no sink is set."""
    sink = target()
    if sink is None:
        return "off"
    stamp = time.time() if now is None else now
    accepted = (sender or mail.Mailer(Path(state))).send_notice_now(sink, SUBJECT, BODY, kind="probe")
    doc = _read(state)
    if accepted:
        doc = {"last_try": stamp, "last_ok": stamp, "failures": 0}
    else:
        doc = {"last_try": stamp, "last_ok": doc.get("last_ok"), "failures": int(doc.get("failures", 0) or 0) + 1}
    try:
        _write(state, doc)
    except OSError as exc:
        applog.log(f"mail probe: state not written ({type(exc).__name__})", level=logging.WARNING)
    if not accepted:
        applog.anomaly("mail_probe_failed", failures=doc["failures"], last_ok=doc.get("last_ok"))
        applog.log(f"mail probe: the provider did not take the probe mail ({doc['failures']} in a row)", level=logging.ERROR)
    return status(state)["state"]


class Prober:
    """The timer: one daemon thread started by `serve` in prod. Off, and saying why, when there is no sink."""

    def __init__(self, state: Path | str, sender: Any = None) -> None:
        self.state, self.sender = Path(state), sender
        self._stop = threading.Event()

    def start(self) -> "Prober":
        if target() is None:
            applog.log(f"mail probe: off ({ENV_TO} is not set)")
            return self
        if not mail.is_prod() and self.sender is None:
            applog.log("mail probe: off (not prod)")
            return self
        applog.log(f"mail probe: on, every {every_s():.0f} s")
        threading.Thread(target=self._loop, name="mail-probe", daemon=True).start()
        return self

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        delay = FIRST_DELAY_S
        while not self._stop.wait(delay):
            try:
                run_once(self.state, self.sender)
            except Exception as exc:  # the probe never takes the app down
                applog.log(f"mail probe: crashed ({type(exc).__name__})", level=logging.ERROR)
            delay = every_s()


def cli(state: Path | str) -> int:
    """`part7 mail-probe`: print the status line; exit 0 ok or waiting, 1 failing, 3 off."""
    doc = status(state)
    print(json.dumps(doc))
    return {"failing": 1, "off": 3}.get(doc["state"], 0)
