"""Idempotency-Key for the four routes that create something: uploads, follow, trainer and group.

The app saves a camera take on the device and retries it. A response can be lost after the server accepted the
request; without a key the retry would create a second upload or job and use a second daily analysis. The browser
sends the take's id as `Idempotency-Key`; a repeat of the same key on the same route answers the original 201 or 202
body: no new upload, no new job, no quota charge. Records live under `<state>/idempotency/` for the retention days.
Requests with no key, a key that is not a UUID, or on any other route behave as before.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import threading
import time
from typing import Any

ROUTES = frozenset({"uploads", "follow", "trainer", "group"})
KEY_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
HEADER = "Idempotency-Key"
REPLAYABLE = (201, 202)  # only an accepted request is remembered; a refusal is worth retrying


def valid_key(value: str | None) -> str | None:
    """The key in canonical lower case, or None when it is missing or not a UUID."""
    key = (value or "").strip().lower()
    return key if KEY_RE.match(key) else None


class Store:
    """Key to response on disk, with the set of requests still being served."""

    def __init__(self, state: Path | str) -> None:
        self.dir = Path(state) / "idempotency"
        self.dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._active: set[tuple[str, str]] = set()

    def _path(self, route: str, key: str) -> Path:
        return self.dir / f"{route}-{key}.json"

    def get(self, route: str, key: str) -> tuple[int, Any] | None:
        try:
            doc = json.loads(self._path(route, key).read_text(encoding="utf-8"))
            return int(doc["status"]), doc["body"]
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def put(self, route: str, key: str, status: int, body: Any) -> None:
        path = self._path(route, key)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"status": status, "body": body, "created": time.time()}), encoding="utf-8")
        os.replace(tmp, path)

    def drop(self, route: str, key: str) -> None:
        self._path(route, key).unlink(missing_ok=True)

    def begin(self, route: str, key: str) -> bool:
        """Claim the key for this request; False when another request with it is still running."""
        with self._lock:
            if (route, key) in self._active:
                return False
            self._active.add((route, key))
            return True

    def end(self, route: str, key: str) -> None:
        with self._lock:
            self._active.discard((route, key))

    def prune(self, retention_days: float) -> int:
        """Delete records older than the retention; returns how many went."""
        cutoff = time.time() - retention_days * 86400
        gone = 0
        for child in self.dir.iterdir():
            try:
                if child.stat().st_mtime < cutoff:
                    shutil.rmtree(child, ignore_errors=True) if child.is_dir() else child.unlink()
                    gone += 1
            except OSError:
                continue
        return gone
