"""Idempotency-Key for the four routes that create something: uploads, follow, trainer and group.

The app saves a camera take on the device and retries it. A response can be lost after the server accepted the
request; without a key the retry would create a second upload or job and use a second daily analysis. The browser
sends the take's id as `Idempotency-Key`; a repeat of the same key on the same route answers the original 201 or 202
body: no new upload, no new job, no quota charge. Records live under `<state>/idempotency/` for the retention days.
Requests with no key, a key that is not a UUID, or on any other route behave as before.
"""

from __future__ import annotations

import hashlib
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


def fingerprint(payload: bytes) -> str:
    """The hash a key is bound to: a replay under the same key must carry the same request body."""
    return hashlib.sha256(payload).hexdigest()


# The fields that say WHICH take a request is; name, category, labels and notes are edits and stay out of the binding.
IDENTITY_FIELDS = ("upload_id", "entry_id", "people_job", "person_id", "trim", "trainer_id", "follower_ids",
                   "mode", "section", "challenge_id")
ID_RE = re.compile(r"^(?:[0-9a-f]{12}|[0-9a-f]{16})$")  # job ids (12 hex), upload ids: nothing else is indexed


def identity_fingerprint(payload: bytes) -> str:
    """Hash of the identifying fields of a JSON request body (a body that is not a JSON object: the whole body).

    After a lost answer the person may edit the take's details; the retry must replay the original job, not fail.
    """
    try:
        doc = json.loads(payload.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return fingerprint(payload)
    if not isinstance(doc, dict):
        return fingerprint(payload)
    ident = {k: doc.get(k) for k in IDENTITY_FIELDS if k in doc}
    return fingerprint(json.dumps(ident, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if ID_RE.match(value) else []
    if isinstance(value, dict):
        return [s for v in value.values() for s in _strings(v)]
    if isinstance(value, list):
        return [s for v in value for s in _strings(v)]
    return []


# A record holds the answer, the time it was made and the hash of the request's identifying fields (JSON routes) or
# of its size and type (uploads); edits to name, category or labels do not change it. `lookup` treats a record older
# than the retention as absent and removes it; `put` prunes the folder at most once an hour, so a server that
# stays up never keeps stale keys. `forget_ids` uses an id to record index, built by one scan on first use and
# kept current by `put` and `drop`, so a delete costs a lookup, not a scan of every record.
class Store:
    """Key to response on disk, with the set of requests still being served."""

    PRUNE_EVERY_S = 3600.0

    def __init__(self, state: Path | str, retention_days: float = 7.0) -> None:
        self.dir = Path(state) / "idempotency"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.retention_days = retention_days
        self._lock = threading.Lock()
        self._active: set[tuple[str, str]] = set()
        self._index: dict[str, set[Path]] | None = None
        self._by_path: dict[Path, set[str]] = {}  # reverse map: the index entries each record holds
        self._pruned_at = time.time()

    def _path(self, route: str, key: str) -> Path:
        return self.dir / f"{route}-{key}.json"

    def _read(self, path: Path) -> dict[str, Any] | None:
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
            int(doc["status"])
            doc["body"]
        except (OSError, ValueError, KeyError, TypeError):
            return None
        return doc if isinstance(doc, dict) else None

    def lookup(self, route: str, key: str) -> tuple[int, Any, str | None] | None:
        """`(status, body, fingerprint)` of a live record; an expired one is removed and reads as absent."""
        path = self._path(route, key)
        doc = self._read(path)
        if doc is None:
            return None
        created = doc.get("created")
        if isinstance(created, (int, float)) and created < time.time() - self.retention_days * 86400:
            self.drop(route, key)
            return None
        fp = doc.get("fingerprint")
        return int(doc["status"]), doc["body"], fp if isinstance(fp, str) else None

    def get(self, route: str, key: str) -> tuple[int, Any] | None:
        found = self.lookup(route, key)
        return (found[0], found[1]) if found else None

    def put(self, route: str, key: str, status: int, body: Any, fp: str | None = None) -> None:
        path = self._path(route, key)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"status": status, "body": body, "created": time.time(), "fingerprint": fp}), encoding="utf-8")
        os.replace(tmp, path)
        with self._lock:
            if self._index is not None:
                self._add(path, body)
            due = time.time() - self._pruned_at > self.PRUNE_EVERY_S
            if due:
                self._pruned_at = time.time()
        if due:
            self.prune(self.retention_days)

    def drop(self, route: str, key: str) -> None:
        path = self._path(route, key)
        path.unlink(missing_ok=True)
        self._unindex(path)

    def _add(self, path: Path, body: Any) -> None:
        assert self._index is not None
        for text in _strings(body):
            self._index.setdefault(text, set()).add(path)
            self._by_path.setdefault(path, set()).add(text)

    def _built_index(self) -> dict[str, set[Path]]:
        if self._index is None:
            self._index = {}
            for child in self.dir.glob("*.json"):
                doc = self._read(child)
                if doc is not None:
                    self._add(child, doc.get("body"))
        return self._index

    def forget_ids(self, ids: list[str]) -> int:
        """Drop every record whose answer names one of `ids` (a deleted take's job, upload or people job).

        A retry with that key would otherwise be answered with an id that no longer exists; with the record gone it
        is a fresh request. Returns how many records went.
        """
        wanted = [i for i in ids if isinstance(i, str) and i]
        if not wanted:
            return 0
        with self._lock:
            index = self._built_index()
            paths = {p for i in wanted for p in index.pop(i, ())}
            for p in paths:
                self._by_path.pop(p, None)
        gone = 0
        for path in paths:
            if path.exists():
                path.unlink(missing_ok=True)
                gone += 1
        return gone

    def mark_form(self, route: str, key: str, form: str) -> None:
        """Note on a stored record which fingerprint form matched a replay (`whole-body`: saved before the identity binding)."""
        path = self._path(route, key)
        doc = self._read(path)
        if doc is None or doc.get("fingerprint_form") == form:
            return
        doc["fingerprint_form"] = form
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(doc), encoding="utf-8")
        os.replace(tmp, path)

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

    def _unindex(self, path: Path) -> None:
        with self._lock:
            for text in self._by_path.pop(path, ()):
                paths = (self._index or {}).get(text)
                if paths is not None:
                    paths.discard(path)

    def prune(self, retention_days: float) -> int:
        """Delete records older than the retention; returns how many went."""
        cutoff = time.time() - retention_days * 86400
        gone = 0
        for child in self.dir.iterdir():
            try:
                if child.stat().st_mtime < cutoff:
                    shutil.rmtree(child, ignore_errors=True) if child.is_dir() else child.unlink()
                    gone += 1
                    self._unindex(child)
            except OSError:
                continue
        return gone
