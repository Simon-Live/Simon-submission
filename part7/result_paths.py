"""A served result file without the server's own paths (`/srv/firm-prod/...`): analysis.json names the files it was made from.

The file on disk keeps them, for the server's own readers. Spec: docs/specs/observability.md "Result files".
"""

from __future__ import annotations

import json
from typing import Any


def _is_server_path(value: Any) -> bool:
    return isinstance(value, str) and value.startswith("/") and "/" in value[1:] and "\n" not in value


def _without_paths(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _without_paths(v) for k, v in value.items() if not _is_server_path(v)}
    if isinstance(value, list):
        return [_without_paths(v) for v in value if not _is_server_path(v)]
    return value


def strip(raw: bytes) -> bytes:
    """`raw` with every value that is an absolute path left out; a file that is not JSON stays as it is."""
    try:
        doc = json.loads(raw)
    except ValueError:
        return raw
    return json.dumps(_without_paths(doc), ensure_ascii=False).encode("utf-8")
