"""The one set of caps for what the converter jail reports (TICKET-341 review B-b). Stdlib only.

`supervisor.py` applies them to the jail's outcome before it writes `convert.json`; `part7/model_import.py` loads this
file by path and applies them again before the record reaches character.json. Anything not of the expected type goes.
"""

from __future__ import annotations

MAX_ITEMS = 50  # steps (and the first 10 of them for attempts)
MAX_KEYS = 12
MAX_KEY = 40
MAX_TEXT = 200
MAX_LIST = 20
MAX_NUMBER = 1e12
MAX_ATTEMPTS = 10


def scalar(value: object) -> object:
    """None, a bool, a finite number under MAX_NUMBER, a string cut at MAX_TEXT, or a short list of short strings."""
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value if abs(value) < MAX_NUMBER else None
    if isinstance(value, str):
        return value[:MAX_TEXT]
    if isinstance(value, list):
        return [v[:MAX_TEXT] for v in value[:MAX_LIST] if isinstance(v, str)]
    return None


def items(raw: object, limit: int = MAX_ITEMS) -> list[dict]:
    """At most `limit` dicts of at most MAX_KEYS short keys with `scalar` values; anything else is dropped."""
    if not isinstance(raw, list):
        return []
    return [{str(k)[:MAX_KEY]: scalar(v) for k, v in list(item.items())[:MAX_KEYS]}
            for item in raw[:limit] if isinstance(item, dict)]


def one_of(value: object, allowed: tuple) -> object:
    return value if value in allowed else None
