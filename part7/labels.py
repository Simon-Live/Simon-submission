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


def view(state: Path | str, entry_id: str) -> dict[str, Any] | None:
    """One entry as `all_labels` lists it: `{tags, notes}` plus `floor_work` and `needs_review` when set; None when it has none."""
    found = get(Path(state), entry_id)
    marks = {**({"floor_work": True} if floor_work(state, entry_id) else {}),  # a flag of its own, kept when labels are edited
             **({"needs_review": True} if needs_review(Path(state), entry_id) else {})}  # flagged even with no tags or notes
    if found is None and not marks:
        return None
    return {**(found or {"tags": [], "notes": ""}), **marks}


def all_labels(state: Path) -> dict[str, dict[str, Any]]:
    """`{entry_id: view}` for every entry with labels, a floor-work mark or a review flag."""
    ids: set[str] = set()
    for folder in (_dir(state), _floor_dir(state), _review_dir(state)):
        if folder.is_dir():
            ids.update(p.stem for p in folder.glob("*.json") if ENTRY_ID_RE.match(p.stem))
    out: dict[str, dict[str, Any]] = {}
    for entry_id in sorted(ids):
        found = view(state, entry_id)
        if found is not None:
            out[entry_id] = found
    return out


def entry_saver(state: Path | str, entry_labels: dict[str, Any] | None, floor: bool) -> Any:
    """The `on_entry` hook of a new trainer entry: saves its labels and its floor-work mark; None when it has neither."""
    if entry_labels is None and not floor:
        return None

    def save_new(entry_id: str) -> None:
        if entry_labels is not None:
            save(Path(state), entry_id, entry_labels)
        if floor:
            set_floor_work(state, entry_id, True)

    return save_new


def _floor_dir(state: Path | str) -> Path:
    return _dir(Path(state)) / "floor"


def set_floor_work(state: Path | str, entry_id: str, on: bool) -> None:
    """Mark or unmark `entry_id` as floor work (floor-work.md); Part 6 has no field for it, so it lives in Part 7's store."""
    if not ENTRY_ID_RE.match(entry_id):
        raise LabelsError("This movement id is not valid.")
    target = _floor_dir(state) / f"{entry_id}.json"
    if not on:
        target.unlink(missing_ok=True)
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.parent / f".{entry_id}.tmp"
    tmp.write_text(json.dumps({"floor_work": True}), encoding="utf-8")
    os.replace(tmp, target)


def floor_work(state: Path | str | None, entry_id: str | None) -> bool:
    """True when the owner marked the entry as done on the floor."""
    if state is None or not isinstance(entry_id, str) or not ENTRY_ID_RE.match(entry_id):
        return False
    return (_floor_dir(state) / f"{entry_id}.json").is_file()


def _review_dir(state: Path) -> Path:
    return _dir(state) / "review"


def mark_review(state: Path, entry_id: str, reason: str) -> bool:
    """Flag `entry_id` as `needs_review` in Part 7's own store (TICKET-204); True when it was not flagged before.

    The flag is one file beside the labels, so Part 6's catalog files are never touched and a labels edit keeps it.
    """
    if not ENTRY_ID_RE.match(entry_id):
        return False
    folder = _review_dir(state)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{entry_id}.json"
    fresh = not target.is_file()
    doc = {"needs_review": True, "reason": reason[:200], "flagged_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    tmp = folder / f".{entry_id}.tmp"
    tmp.write_text(json.dumps(doc), encoding="utf-8")
    os.replace(tmp, target)
    return fresh


def clear_review(state: Path, entry_id: str) -> bool:
    """Remove the flag; True when there was one."""
    if not ENTRY_ID_RE.match(entry_id):
        return False
    target = _review_dir(state) / f"{entry_id}.json"
    had = target.is_file()
    target.unlink(missing_ok=True)
    return had


def needs_review(state: Path, entry_id: str) -> bool:
    return bool(ENTRY_ID_RE.match(entry_id)) and (_review_dir(state) / f"{entry_id}.json").is_file()


SEEDED_NAMES = "seeded-names.json"  # <state>/seeded-names.json: {"synthetic": true, "names": {entry_id: name}}, written only by tools/seed_history.py


def seeded_name(state: Path | str | None, entry_id: str) -> str | None:
    """The display name the demo seed recorded for a seeded movement that is not in the catalog, or None."""
    if state is None:
        return None
    try:
        doc = json.loads((Path(state) / SEEDED_NAMES).read_text(encoding="utf-8"))
        name = doc["names"][entry_id]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return name.strip() if isinstance(name, str) and name.strip() else None


def entry_name(child: Any, entry_id: str, state: Path | str | None = None) -> str:
    """The name of an entry as the pages title it (one lookup for every page).

    The catalog name with its first letter in capitals, as the catalog screen shows it (web/curation.js displayName); else the
    name the demo seed recorded for a seeded entry (`state`); else the id."""
    try:
        manifest = child.get_entry(entry_id)
    except Exception:
        manifest = None
    name = manifest.get("name") if isinstance(manifest, dict) else None
    if isinstance(name, str) and name.strip():
        name = name.strip()
        return name[0].upper() + name[1:]
    return seeded_name(state, entry_id) or entry_id
