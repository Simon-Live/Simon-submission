"""Rebuild the function of a trainer or follow job that was still queued when the server stopped (processor.md "Restart").

`trainer_spec` and `follow_spec` run at submit time and return the small JSON dict kept in the job record as
`_resume` (None for a job about one person of a people job: those need the people job's work folder and fail
with "the server restarted" as before). `rebuild` runs at start and returns the job function, or None when the
upload, the entry or the animation is gone.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from part7 import animation_format, applog, labels, private_mode, processor, sections

SPEC_VERSION = 1


def trainer_spec(doc: dict[str, Any], name: str, category: str, person: Any) -> dict[str, Any] | None:
    if person is not None:
        return None
    return {"v": SPEC_VERSION, "upload_id": str(doc.get("upload_id") or ""), "name": name, "category": category,
            "labels": doc.get("labels")}


def follow_spec(doc: dict[str, Any], person: Any) -> dict[str, Any] | None:
    if person is not None:
        return None
    return {"v": SPEC_VERSION, "upload_id": str(doc.get("upload_id") or "")}


def rebuild(app: Any, record: dict[str, Any]) -> Any:
    """The job function for `record` (a queued job from before the restart), or None when it cannot run."""
    spec = record.get("_resume")
    if not isinstance(spec, dict) or spec.get("v") != SPEC_VERSION:
        return None
    raw = app.upload_file(str(spec.get("upload_id") or ""))
    if raw is None:
        applog.log("resume: its upload is gone", record["id"], level=logging.WARNING)
        return None
    if record.get("kind") == "trainer":
        return _trainer(app, record, spec, raw)
    if record.get("kind") == "follow":
        return _follow(app, record, raw)
    return None


def _trainer(app: Any, record: dict[str, Any], spec: dict[str, Any], raw: Path) -> Any:
    entry_labels = labels.validate(spec["labels"]) if spec.get("labels") is not None else None
    state = app.state
    on_entry = (lambda entry_id: labels.save(state, entry_id, entry_labels)) if entry_labels is not None else None
    return processor.trainer_job(
        raw, name=spec["name"], category=spec["category"], catalog=app.child.catalog_dir, lock=app.lock,
        backend=app.backend, trim=record.get("trim"), on_entry=on_entry,
    )


def _follow(app: Any, record: dict[str, Any], raw: Path) -> Any:
    entry_id = str(record.get("entry_id") or "")
    manifest = app.child.get_entry(entry_id)
    if manifest is None:
        return None
    name = manifest.get("animation") or manifest.get("skeleton")
    expected = app.child.get_entry_file(entry_id, str(name)) if name else None
    if expected is None:
        return None
    if manifest.get("animation"):
        expected = animation_format.to_v1(expected)
    if record.get("section"):
        expected = sections.cut(expected, record["section"])
    skeleton = manifest.get("skeleton")
    visibility = app.child.get_entry_file(entry_id, str(skeleton)) if skeleton else None
    private = True if record.get("private") else None
    video_name = (manifest.get("video_uri")
                  if app.phrasing == "live" and not private_mode.enabled(job_flag=private) else None)
    trainer_video = app.child.get_entry_file(entry_id, str(video_name)) if video_name else None
    return processor.follow_job(
        raw, expected=expected, entry_id=entry_id, phrasing=app.phrasing, lock=app.lock, backend=app.backend,
        trim=record.get("trim"), visibility=visibility, mode=record.get("mode"), lang=record.get("lang"),
        trainer_video=trainer_video, private=private,
    )
