"""Addresses the provider says it cannot or must not mail again (docs/specs/mail-delivery.md "Bounces and complaints").

`mail_webhook` adds an address when Resend reports a bounce or a complaint; `mail.Mailer.send_notice` (account
notices and board invites) then sends nothing to it. Sign-in mail is not blocked: a person whose address bounced once
must still be able to ask for a code. The file `<state>/mail-suppressed.json` (0600) holds SHA-256 digests of the
lowercased address, never the address; Delete my data does not need to touch it because it holds no address.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import threading
import time

FILE = "mail-suppressed.json"
CAP = 5000
_LOCK = threading.Lock()


def digest(email: str) -> str:
    return hashlib.sha256(email.strip().lower().encode("utf-8")).hexdigest()


def _load(state: Path | str) -> dict[str, dict]:
    try:
        doc = json.loads((Path(state) / FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def is_suppressed(state: Path | str, email: str) -> bool:
    with _LOCK:
        return digest(email) in _load(state)


def add(state: Path | str, email: str, reason: str, now: float | None = None) -> bool:
    """Record `email` as suppressed; False when it already was (the webhook then raises no second anomaly)."""
    key = digest(email)
    with _LOCK:
        rows = _load(state)
        if key in rows:
            return False
        rows[key] = {"at": time.time() if now is None else now, "reason": reason}
        while len(rows) > CAP:
            del rows[next(iter(rows))]
        path = Path(state) / FILE
        tmp = path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            json.dump(rows, out)
        os.replace(tmp, path)
    return True


def count(state: Path | str) -> int:
    with _LOCK:
        return len(_load(state))
