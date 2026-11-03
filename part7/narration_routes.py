"""`GET api/narration/<entry>`: the trainer's narration cues of a catalog entry (docs/specs/narration.md).

`server.py` calls `handle` before its own routes. The file is `<catalog>/<entry>/narration.json`, written by
`narration.attach` after the trainer job; an entry without one (no audio, no speech, a failed call) answers 404 and
the page shows nothing.
"""

from __future__ import annotations

import json
import re
from typing import Any

from part7 import labels, narration

MSG_NONE = "This movement has no narration."
CLIP_RE = re.compile(r"^cue-[0-9]{1,3}\.wav$")
PRIVATE = ("estimated_usd",)  # spend stays out of the public answer


def has_narration(h: Any, entry: Any) -> bool:
    """True when `entry` has a narration file, so the result page asks for it only then (no 404 in the console)."""
    if not isinstance(entry, str) or not labels.ENTRY_ID_RE.match(entry):
        return False
    return (h.app.child.catalog_dir / entry / narration.FILE_NAME).is_file()


def handle(h: Any, method: str, route: str) -> bool:
    """Answer `narration/<entry>` and return True; False for any other route."""
    parts = route.split("/")
    if method not in ("GET", "HEAD") or len(parts) not in (2, 3) or parts[0] != "narration":
        return False
    if len(parts) == 3:
        return _clip(h, parts[1], parts[2])
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


def _clip(h: Any, entry: str, name: str) -> bool:
    """`narration/<entry>/cue-<n>.wav`: the trainer's own words for one cue (TICKET-270); 404 when there is no such clip."""
    path = h.app.child.catalog_dir / entry / narration.CLIPS_DIR / name if labels.ENTRY_ID_RE.match(entry) and CLIP_RE.match(name) else None
    if path is None or path.is_symlink() or not path.is_file():
        h._error(404, MSG_NONE)
    else:
        h._send(200, path.read_bytes(), "audio/wav", {})
    return True
