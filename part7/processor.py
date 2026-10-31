"""Job functions for the queue: the trainer job (Parts 1 to 4, then Part 6 `import`) and the follow job.

Both normalize the upload to H.264 MP4 (`media.py`) in their first stage, run `chain.py` with the stage
callback of the job, and turn a failed chain result into `JobFailed` with a plain reason.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from part7 import chain, media, people, modules
from part7.jobs import JobContext, JobFailed, JobFn

REASON_UNREADABLE = "the video could not be read"


def _clip(ctx: JobContext, raw: Path, person: people.PersonSel | None, trim: dict[str, int] | None) -> Path:
    """The people job's trimmed clip when `person` names one, else `raw` normalized and cut to `trim`.

    Both branches end in `people.prepare_clip` (the people job ran it before), so trainer and follow jobs see
    the same normalize, trim and frame rate (people.md "One clip path").
    """
    if person is not None and person.people_work is not None:
        return people.reused_clip(ctx, person)
    video = people.prepare_clip(ctx, raw, trim, name="video.mp4")
    if trim is not None:
        try:
            ctx.set_fields(trimmed_duration_ms=media.probe(video)["duration_ms"])
        except ValueError:
            raise JobFailed("upload", REASON_UNREADABLE) from None
    return video


def _raise_if_failed(result: dict[str, Any]) -> None:
    if result.get("ok"):
        return
    stage = str(result.get("stage") or "upload")
    error = str(result.get("error") or "")
    prefix = f"failed:{stage}: "
    raise JobFailed(stage, error[len(prefix):] if error.startswith(prefix) else error)


def trainer_job(
    raw: Path,
    *,
    name: str,
    category: str,
    catalog: Path,
    lock: modules.Modules | None = None,
    state: Path | str | None = None,
    backend: str = "gpu",
    trim: dict[str, int] | None = None,
    on_entry: Callable[[str], None] | None = None,
    person: people.PersonSel | None = None,
) -> JobFn:
    """Return the job function for a trainer upload; it ends with a Part 6 entry and Part 6 doctor.

    `on_entry` runs once the entry exists (the server saves the labels there). `person` (people.md) makes it
    about one person of a people job and reuses that job's trimmed clip (already cut: `trim` then only reports).
    """

    def run(ctx: JobContext) -> dict[str, Any]:
        video = _clip(ctx, raw, person, trim)
        result = chain.trainer(
            video, ctx.work / "trainer", report=ctx.set_stage, lock=lock, backend=backend, state=state,
            catalog=catalog, name=name, category=category, person=person,
        )
        if result.get("note"):
            ctx.add_note(str(result["note"]))
        _raise_if_failed(result)
        entry_id = str(result["entry_id"])
        if on_entry is not None:
            on_entry(entry_id)
        return {"entry_id": entry_id, "result": {"entry_id": entry_id, "parts": result["parts"], "trim": trim}}

    return run


def _score_summary(analysis: Path) -> dict[str, Any]:
    """The few fields of Part 5's file the job screen shows; the file itself is served unchanged."""
    try:
        doc = json.loads(analysis.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    score = doc.get("score") if isinstance(doc, dict) else None
    status = doc.get("status") if isinstance(doc, dict) else None
    # A take is always scored: the pinned Part 5's refusal (null score) reads as 0 and F (app.md "Always analysed").
    no_score = isinstance(doc, dict) and not isinstance(score, dict)
    return {
        "score": score.get("value") if isinstance(score, dict) else (0 if no_score else None),
        "grade": score.get("grade") if isinstance(score, dict) else ("F" if no_score else None),
        "faults": len(doc.get("faults") or []) if isinstance(doc, dict) else 0,
        "status_code": status.get("code") if isinstance(status, dict) else None,
    }


def follow_job(
    raw: Path,
    *,
    expected: bytes,
    entry_id: str,
    phrasing: str = "template",
    lock: modules.Modules | None = None,
    state: Path | str | None = None,
    backend: str = "gpu",
    trim: dict[str, int] | None = None,
    person: people.PersonSel | None = None,
    visibility: bytes | None = None,
) -> JobFn:
    """Return the job function for a follower upload against the entry's `expected` clip bytes.

    `visibility` is the trainer's `skeleton.json`; Part 5 uses it to refuse takes whose body is not visible.

    With a `trim`, `at_s` in the analysis is on the trimmed clip's clock and the result carries `trim`.
    `person` (people.md) makes the analysis that of one person of a people job, on that job's trimmed clip.
    """

    def run(ctx: JobContext) -> dict[str, Any]:
        video = _clip(ctx, raw, person, trim)
        expected_path = ctx.work / "expected.json"
        expected_path.write_bytes(expected)
        visibility_path = None
        if visibility is not None:
            visibility_path = ctx.work / "expected_skeleton.json"
            visibility_path.write_bytes(visibility)
        result = chain.follower(
            video, expected_path, ctx.work / "follower", report=ctx.set_stage, lock=lock, backend=backend,
            state=state, phrasing=phrasing, person=person, expected_visibility=visibility_path,
        )
        if result.get("note"):
            ctx.add_note(str(result["note"]))
        _raise_if_failed(result)
        files = result["files"]
        summary = _score_summary(Path(files["analysis"]))
        return {
            "result": {
                **summary,
                "trim": trim,
                "analysis": f"api/results/{ctx.id}/analysis.json",
                "replay": f"api/results/{ctx.id}/replay.json" if "replay" in files else None,
            }
        }

    return run
