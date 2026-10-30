"""Trainer labels (tags and notes) kept by Part 7 in `<state>/labels/<entry_id>.json` (recorder.md "Labels").

Part 6 has no tags field, so the labels live beside it and the catalog screen merges them.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from typing import Any

TAG_RE = re.compile(r"^[a-z0-9-]{1,24}$")
ENTRY_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
MAX_TAGS = 8
NOTES_MAX = 280

MSG_LABELS = "Labels must be tags and notes."
MSG_TAGS = "Use up to 8 tags, each 1 to 24 characters: lower case letters, digits and hyphens."
MSG_NOTES = "Notes can be 280 characters at most."


class LabelsError(ValueError):
    """The labels are not acceptable; the message is plain words for the person."""


def validate(raw: Any) -> dict[str, Any]:
    """Return `{tags, notes}` cleaned (duplicate tags dropped, notes trimmed) or raise `LabelsError`."""
    if not isinstance(raw, dict):
        raise LabelsError(MSG_LABELS)
    tags_in, notes = raw.get("tags", []), raw.get("notes", "")
    if not isinstance(tags_in, list) or not all(isinstance(t, str) and TAG_RE.match(t) for t in tags_in):
        raise LabelsError(MSG_TAGS)
    tags = list(dict.fromkeys(tags_in))
    if len(tags) > MAX_TAGS:
        raise LabelsError(MSG_TAGS)
    if notes is None:
        notes = ""
    if not isinstance(notes, str) or len(notes.strip()) > NOTES_MAX:
        raise LabelsError(MSG_NOTES)
    return {"tags": tags, "notes": notes.strip()}


def _dir(state: Path) -> Path:
    return Path(state) / "labels"


def save(state: Path, entry_id: str, labels: dict[str, Any]) -> None:
    """Write the (already validated) labels for `entry_id` atomically."""
    if not ENTRY_ID_RE.match(entry_id):
        raise LabelsError("This movement id is not valid.")
    folder = _dir(state)
    folder.mkdir(parents=True, exist_ok=True)
    doc = {**labels, "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    tmp = folder / f".{entry_id}.tmp"
    tmp.write_text(json.dumps(doc), encoding="utf-8")
    os.replace(tmp, folder / f"{entry_id}.json")


def get(state: Path, entry_id: str) -> dict[str, Any] | None:
    """One entry's `{tags, notes}`, or None when it has none (or the file is unreadable)."""
    if not ENTRY_ID_RE.match(entry_id):
        return None
    try:
        doc = json.loads((_dir(state) / f"{entry_id}.json").read_text(encoding="utf-8"))
        return {"tags": list(doc["tags"]), "notes": str(doc["notes"])}
    except (OSError, ValueError, KeyError, TypeError):
        return None


def all_labels(state: Path) -> dict[str, dict[str, Any]]:
    """`{entry_id: {tags, notes}}` for every labelled entry."""
    out: dict[str, dict[str, Any]] = {}
    folder = _dir(state)
    if not folder.is_dir():
        return out
    for path in sorted(folder.glob("*.json")):
        found = get(state, path.stem)
        if found is not None:
            out[path.stem] = found
    return out
