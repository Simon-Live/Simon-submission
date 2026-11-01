"""`GET api/narration/<entry>`: the trainer's narration cues of a catalog entry (docs/specs/narration.md).

`server.py` calls `handle` before its own routes. The file is `<catalog>/<entry>/narration.json`, written by
`narration.attach` after the trainer job; an entry without one (no audio, no speech, a failed call) answers 404 and
the page shows nothing.
"""

from __future__ import annotations

import json
from typing import Any

from part7 import labels, narration

MSG_NONE = "This movement has no narration."
PRIVATE = ("estimated_usd",)  # spend stays out of the public answer


def handle(h: Any, method: str, route: str) -> bool:
    """Answer `narration/<entry>` and return True; False for any other route."""
    parts = route.split("/")
    if method not in ("GET", "HEAD") or len(parts) != 2 or parts[0] != "narration":
        return False
    entry = parts[1]
    path = h.app.child.catalog_dir / entry / narration.FILE_NAME if labels.ENTRY_ID_RE.match(entry) else None
    try:
        doc = json.loads(path.read_text(encoding="utf-8")) if path is not None and path.is_file() else None
    except (OSError, ValueError):
        doc = None
    if not isinstance(doc, dict):
        h._error(404, MSG_NONE)
    else:
        h._json(200, {k: v for k, v in doc.items() if k not in PRIVATE})
    return True
