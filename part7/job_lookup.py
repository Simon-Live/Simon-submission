"""Reads that the result routes repeat on every request: parsed job files cached by mtime, and the trainer job of an entry.

`read_json(path)` returns the parsed file, re-reading only when its mtime or size changed (a result page asks for
`models.json`, `mesh.json` and `skeleton2d.json` together, and each used to parse the same large files again). The
parsed value is shared: callers must not change it.

The `JobQueue` of a jobs folder registers `trainer_for` here. It answers from the queue's records in memory (kind
`trainer`, status `done`, newest `finished_at`), so finding a trainer job no longer reads every job folder. A folder
without a registered queue (tests, tools) is scanned on disk as before.
"""

from __future__ import annotations

from collections import OrderedDict
import json
from pathlib import Path
import threading
from typing import Any, Callable

CACHE_MAX = 128
_lock = threading.Lock()
_cache: OrderedDict[str, tuple[tuple[int, int], Any]] = OrderedDict()
_lookups: dict[str, Callable[[str], str | None]] = {}


def read_json(path: Path) -> Any:
    """The parsed JSON file, or None when it is missing or not JSON."""
    key = str(path)
    try:
        st = path.stat()
        sig = (st.st_mtime_ns, st.st_size)
        with _lock:
            hit = _cache.get(key)
            if hit is not None and hit[0] == sig:
                _cache.move_to_end(key)
                return hit[1]
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    with _lock:
        _cache[key] = (sig, value)
        while len(_cache) > CACHE_MAX:
            _cache.popitem(last=False)
    return value


def register(jobs_root: Path, trainer_for: Callable[[str], str | None]) -> None:
    with _lock:
        _lookups[str(jobs_root)] = trainer_for


def release(jobs_root: Path, trainer_for: Callable[[str], str | None]) -> None:
    with _lock:
        if _lookups.get(str(jobs_root)) == trainer_for:
            del _lookups[str(jobs_root)]


def registered(jobs_root: Path) -> Callable[[str], str | None] | None:
    with _lock:
        return _lookups.get(str(jobs_root))
