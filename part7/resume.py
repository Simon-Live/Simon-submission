"""Rebuild the function of a trainer or follow job that was still queued when the server stopped (processor.md "Restart").

`trainer_spec` and `follow_spec` run at submit time and return the small JSON dict kept in the job record as
`_resume`. A job about one person of a people job keeps a v2 spec that adds `people_job` and `person_id`; `rebuild`
finds that person again in the people job's work folder, which stays on disk (TICKET-287). `rebuild` runs at start
and returns the job function, or None when the upload, the entry, the animation, the people job's folder or the
person is gone. A v1 spec (no person) rebuilds as before; a server that knows only v1 fails a v2 job as it did.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from part7 import animation_format, applog, auth, labels, mirrored, model_only, my_reference, people, people_routes, private_mode, processor, run_on, sections

SPEC_VERSION = 1
PERSON_SPEC_VERSION = 2  # a spec about one person of a people job (TICKET-287)


def trainer_spec(doc: dict[str, Any], name: str, category: str, person: Any) -> dict[str, Any] | None:
    return {"v": SPEC_VERSION, "upload_id": str(doc.get("upload_id") or ""), "name": name, "category": category,
            "labels": doc.get("labels"), **({"floor_work": True} if doc.get("floor_work") is True else {}),
            **_person_spec(doc, person)}


def follow_spec(doc: dict[str, Any], person: Any) -> dict[str, Any] | None:
    return {"v": SPEC_VERSION, "upload_id": str(doc.get("upload_id") or ""), **_person_spec(doc, person)}


def _person_spec(doc: dict[str, Any], person: Any) -> dict[str, Any]:
    """The v2 fields of a job about one person (the chosen id, which may be the people job's `auto_id`); {} without."""
    if person is None:
        return {}
    return {"v": PERSON_SPEC_VERSION, "people_job": str(doc.get("people_job") or ""), "person_id": str(person.id)}


def _person(app: Any, record: dict[str, Any], spec: dict[str, Any]) -> people.PersonSel | None:
    """The person of a v2 spec, found again in the people job's work folder; None (with the reason logged) when gone."""
    found = people_routes.people_result(app.queue, spec.get("people_job"))
    if found is None:
        applog.log(f"resume: its people job {spec.get('people_job')} or that job's work folder is gone", record["id"],
                   level=logging.WARNING)
        return None
    result, work = found
    pid = str(spec.get("person_id") or "")
    if pid not in {str(p.get("id")) for p in result.get("people") or [] if isinstance(p, dict)}:
        applog.log(f"resume: person {pid} is no longer in people job {spec.get('people_job')}", record["id"],
                   level=logging.WARNING)
        return None
    return people.PersonSel(id=pid, people_work=work)


def rebuild(app: Any, record: dict[str, Any]) -> Any:
    """The job function for `record` (a queued job from before the restart), or None when it cannot run."""
    spec = record.get("_resume")
    if not isinstance(spec, dict) or spec.get("v") not in (SPEC_VERSION, PERSON_SPEC_VERSION):
        return None
    raw = app.upload_file(str(spec.get("upload_id") or ""))
    if raw is None:
        applog.log("resume: its upload is gone", record["id"], level=logging.WARNING)
        return None
    person = _person(app, record, spec) if spec.get("v") == PERSON_SPEC_VERSION else None
    if spec.get("v") == PERSON_SPEC_VERSION and person is None:
        return None
    if record.get("kind") == "trainer":
        return _trainer(app, record, spec, raw, person)
    if record.get("kind") == "follow":
        fn = _follow(app, record, raw, person)
        if fn is None:
            return None
        return run_on.bind(fn, run_on.resumed(record.get(run_on.FIELD), record["id"]))  # TICKET-364: checked again
    return None


def _trainer(app: Any, record: dict[str, Any], spec: dict[str, Any], raw: Path, person: people.PersonSel | None) -> Any:
    entry_labels = labels.validate(spec["labels"]) if spec.get("labels") is not None else None
    state = app.state
    floor = spec.get("floor_work") is True
    on_entry = labels.entry_saver(state, entry_labels, floor)
    on_entry = auth.owned_entry(app, auth.job_owner(app, record["id"]), on_entry)  # the submitter owns it (identity.md)
    return processor.trainer_job(
        raw, name=spec["name"], category=spec["category"], catalog=app.child.catalog_dir, lock=app.lock,
        backend=app.backend, trim=record.get("trim"), on_entry=on_entry, person=person,
        review_state=state, mirrored=mirrored.of_record(record), floor_work=floor,
    )


def _reference(app: Any, record: dict[str, Any], teacher: bytes) -> tuple[bytes | None, bool]:
    """The clip a rebuilt job uses. The record already says which reference the result will name, so a job that
    named the student's own reference runs only with that same one; if it is gone the job cannot run (ADR-0019)."""
    named = record.get("reference")
    if not my_reference.uses_own(record):
        return teacher, False
    choice = my_reference.choose(app.state, auth.job_owner(app, record["id"]), str(record.get("entry_id") or ""), teacher)
    if not choice.own or choice.record.get("job_id") != named.get("job_id"):
        applog.log("resume: its own reference is gone", record["id"], level=logging.WARNING)
        return None, False
    return choice.expected, True


def _follow(app: Any, record: dict[str, Any], raw: Path, person: people.PersonSel | None) -> Any:
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
    expected, kept_own = _reference(app, record, expected)
    if expected is None:
        return None
    skeleton = manifest.get("skeleton")
    visibility = app.child.get_entry_file(entry_id, str(skeleton)) if skeleton and not kept_own else None  # the teacher's visibility describes the teacher's body
    private = True if record.get("private") else None
    video_name = (manifest.get("video_uri")
                  if app.phrasing == "live" and not private_mode.enabled(job_flag=private) else None)
    trainer_video = app.child.get_entry_file(entry_id, str(video_name)) if video_name and not kept_own else None
    video_kept = model_only.kept(record)
    drop_source = (None if video_kept else
                   model_only.source_dropper(app.queue, app.uploads, str(record.get("upload_id") or ""), record.get("people_job")))
    return processor.follow_job(
        raw, expected=expected, entry_id=entry_id, phrasing=app.phrasing, lock=app.lock, backend=app.backend,
        trim=record.get("trim"), person=person, visibility=visibility, mode=record.get("mode"), lang=record.get("lang"),
        trainer_video=trainer_video, private=private, video_kept=video_kept, drop_source=drop_source,
        mirrored=mirrored.of_record(record), floor_work=labels.floor_work(app.state, entry_id),
    )
