"""What became of one sign-in mail, for the code screen to ask (docs/specs/mail-delivery.md "Sign-in status").

`POST api/auth/start` answers 202 at once with an attempt id: 16 random hex characters tied to no address. The mail
goes out on a thread; the thread writes `sent` (the provider took it) or `failed` (it did not, after the one retry).
`GET api/auth/mail-status?id=` reads it. An address that is rate limited gets the same `sent` as any other, so the
answer never tells whether an address has an account or has asked too often. Entries live five minutes, the newest
`CAP` stay; nothing here holds an address, a code or a link.
"""

from __future__ import annotations

import re
import secrets
import threading
import time

PENDING, SENT, FAILED, UNKNOWN = "pending", "sent", "failed", "unknown"
TTL_S = 300.0
CAP = 2000
ID_RE = re.compile(r"^[0-9a-f]{16}$")


class AttemptBoard:
    """A small in-memory map from attempt id to status."""

    def __init__(self, clock=time.monotonic) -> None:  # type: ignore[no-untyped-def]
        self._rows: dict[str, tuple[float, str]] = {}
        self._lock = threading.Lock()
        self._clock = clock

    @staticmethod
    def new_id() -> str:
        return secrets.token_hex(8)

    def set(self, attempt: str, status: str) -> None:
        now = self._clock()
        with self._lock:
            self._rows.pop(attempt, None)  # a re-set moves it to the newest end
            self._rows[attempt] = (now, status)
            for old in [k for k, (at, _) in self._rows.items() if now - at > TTL_S]:
                del self._rows[old]
            while len(self._rows) > CAP:
                del self._rows[next(iter(self._rows))]

    def get(self, attempt: str) -> str:
        with self._lock:
            row = self._rows.get(attempt)
        if row is None or self._clock() - row[0] > TTL_S:
            return UNKNOWN
        return row[1]
