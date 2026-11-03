"""Saved-entry content check: a movement's catalog video must match the clip that was recorded (TICKET-204).

After a trainer job saves its entry, and in the retention sweep for recent trainer jobs, the entry's video is probed
against the job's trimmed upload (`jobs/<id>/work/video.mp4`). It is a mismatch when the durations differ by more than
`TOLERANCE_S`, when the entry video cannot be read, or when the file is under `MIN_BYTES_PER_S` for its length.
A mismatch logs a WARNING and `ANOMALY entry_video_mismatch`, and marks the entry `needs_review` in Part 7's own
labels store (`labels.mark_review`; Part 6's files are never edited). A later match clears the mark. Never raises.
Spec: docs/specs/self-healing.md.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from part7 import applog, labels, media, selfheal

TOLERANCE_S = 0.5  # the entry clip may differ from the trimmed upload by this much (re-encode rounding)
MIN_BYTES_PER_S = 1000  # a real take is never smaller than this per second; a blank or truncated file is
SWEEP_LIMIT = 50  # newest trainer jobs checked per sweep, so a long history costs a bounded number of probes
VIDEO_NAME = "video.mp4"


def entry_video(catalog: Path | str, entry_id: str) -> Path | None:
    """The entry's video file named by its manifest (`video_uri`), else `video.mp4`; None when it has none."""
    folder = Path(catalog) / entry_id
    name = VIDEO_NAME
    try:
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        uri = manifest.get("video_uri") if isinstance(manifest, dict) else None
        if isinstance(uri, str) and uri and "/" not in uri and not uri.startswith("."):
            name = uri
        elif isinstance(manifest, dict) and "video_uri" in manifest and not uri:
            return None
    except (OSError, ValueError):
        pass
    path = folder / name
    return path if path.is_file() else None


def compare(entry: Path, upload: Path) -> dict[str, Any] | None:
    """None when the entry video matches `upload`; else `{entry_s, upload_s, why}`. None too when `upload` is unreadable."""
    try:
        upload_s = media.probe(upload)["duration_ms"] / 1000.0
    except (ValueError, KeyError, OSError):
        return None  # nothing to compare against
    try:
        entry_s = media.probe(entry)["duration_ms"] / 1000.0
    except (ValueError, KeyError, OSError):
        return {"entry_s": None, "upload_s": upload_s, "why": "the entry video cannot be read"}
    if abs(entry_s - upload_s) > TOLERANCE_S:
        return {"entry_s": entry_s, "upload_s": upload_s, "why": "the length differs from the recording"}
    try:
        size = entry.stat().st_size
    except OSError:
        return {"entry_s": entry_s, "upload_s": upload_s, "why": "the entry video cannot be read"}
    if size < MIN_BYTES_PER_S * entry_s:
        return {"entry_s": entry_s, "upload_s": upload_s, "why": "the file is too small for its length"}
    return None


def check_entry(state: Path | str, catalog: Path | str, entry_id: str, upload: Path | str, job: str | None = None) -> bool:
    """Check one saved entry; True when it matches (or cannot be compared). A mismatch is logged and flagged."""
    try:
        video = entry_video(catalog, entry_id)
        if video is None:
            return True  # an entry without a video has nothing to mismatch
        found = compare(video, Path(upload))
        if found is None:
            if labels.clear_review(Path(state), entry_id):
                applog.log(f"entry check: {entry_id} matches its recording again; review mark cleared", job)
            return True
        fresh = labels.mark_review(Path(state), entry_id, found["why"])
        if fresh:
            applog.log(f"entry check: the video of {entry_id} may not match what was recorded ({found['why']})",
                       job, level=logging.WARNING)
            applog.anomaly("entry_video_mismatch", found["why"], job=job, entry=entry_id,
                           entry_s=found["entry_s"], upload_s=found["upload_s"])
        return False
    except Exception as exc:  # the check never fails the job or the sweep
        applog.log(f"entry check failed for {entry_id}: {applog.cause(exc)}", job, level=logging.WARNING)
        return True


def sweep(state: Path | str, catalog: Path | str, queue: Any) -> int:
    """Check the entries of the newest done trainer jobs; return how many mismatch. Marks the self-heal record."""
    bad = 0
    seen: set[str] = set()
    for job_id, entry_id in queue.recent_trainer_entries(SWEEP_LIMIT):
        if entry_id in seen:
            continue
        seen.add(entry_id)
        upload = Path(queue.job_dir(job_id)) / "work" / VIDEO_NAME
        if upload.is_file() and not check_entry(state, catalog, entry_id, upload, job_id):
            bad += 1
    if bad == 0:
        selfheal.record("entry_content")
    return bad
