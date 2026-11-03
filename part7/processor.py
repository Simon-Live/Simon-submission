"""Job functions for the queue: the trainer job (Parts 1 to 4, then Part 6 `import`) and the follow job.

Both normalize the upload to H.264 MP4 (`media.py`) in their first stage, run `chain.py` with the stage
callback of the job, and turn a failed chain result into `JobFailed` with a plain reason.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from part7 import chain, entry_check, light, media, model_only, modules, narration, people, quality_cap, selfheal
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


def floor_scored(result: dict[str, Any], floor_work: bool) -> bool:
    """True when the entry is floor work and Part 3 got `--floor-work` for this take (floor-work.md).

    Part 3's `--view part5` file has no `frame` block, so the fact is what Part 7 sent: the chain reports
    `floor_work: true` only when the pinned Part 3 offered the flag and it was on the argv.
    """
    return floor_work is True and result.get("floor_work") is True


def _raise_if_failed(result: dict[str, Any]) -> None:
    if result.get("ok"):
        return
    stage = str(result.get("stage") or "upload")
    error = str(result.get("error") or "")
    prefix = f"failed:{stage}: "
    raise JobFailed(stage, error[len(prefix):] if error.startswith(prefix) else error,
                    str(result.get("cause") or "failed"))


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
    review_state: Path | str | None = None,
    mirrored: bool = False,
    floor_work: bool = False,
) -> JobFn:
    """Return the job function for a trainer upload; it ends with a Part 6 entry and Part 6 doctor.

    `on_entry` runs once the entry exists (the server saves the labels there). `person` (people.md) makes it
    about one person of a people job and reuses that job's trimmed clip (already cut: `trim` then only reports).
    `review_state` (the app's state folder) turns on the saved-entry content check (entry_check.py, TICKET-204).
    `mirrored` (TICKET-310): the person said the upload is a mirrored video; Part 3 flips left and right.
    `floor_work` (the owner marked the movement as done on the floor) goes to Part 3 as `--floor-work` where offered.
    """

    def run(ctx: JobContext) -> dict[str, Any]:
        video = _clip(ctx, raw, person, trim)
        result = chain.trainer(
            video, ctx.work / "trainer", report=ctx.set_stage, lock=lock, backend=backend, state=state,
            catalog=catalog, name=name, category=category, person=person, mirrored=mirrored, floor_work=floor_work,
        )
        if result.get("note"):
            ctx.add_note(str(result["note"]))
        _raise_if_failed(result)
        entry_id = str(result["entry_id"])
        if on_entry is not None:
            on_entry(entry_id)
        narration.attach(  # the trainer's spoken cues; never fails the job (narration.md)
            raw, catalog / entry_id, files=result.get("files"), video=video, trim=trim, job_dir=ctx.work,
        )
        if review_state is not None and entry_check.check_entry(review_state, catalog, entry_id, video, ctx.id):
            selfheal.record("entry_content")
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
        **({"quality": doc["quality"]} if isinstance(doc, dict) and isinstance(doc.get("quality"), dict) else {}),
        **({"uncapped": score["uncapped"]} if isinstance(score, dict) and isinstance(score.get("uncapped"), dict) else {}),
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
    mode: str | None = None,
    lang: str | None = None,
    trainer_video: bytes | None = None,
    private: bool | None = None,
    video_kept: bool = True,
    drop_source: Callable[[str], None] | None = None,
    mirrored: bool = False,
    floor_work: bool = False,
) -> JobFn:
    """Return the job function for a follower upload against the entry's `expected` clip bytes.

    `visibility` is the trainer's `skeleton.json`; Part 5 uses it to refuse takes whose body is not visible.

    With a `trim`, `at_s` in the analysis is on the trimmed clip's clock and the result carries `trim`.
    `mode` (modes.py) goes to Part 5 as `--profile` when the pin offers it. The caller has already cut `expected`
    to a section when the request had one (sections.py).
    `person` (people.md) makes the analysis that of one person of a people job, on that job's trimmed clip.
    `lang` (the follower's pick), `trainer_video` (the entry's video bytes, for Part 5's second opinion) and
    `private` (private-mode.md) go to Part 5 only where the pin offers the matching flag (p5_analyse.py).
    With `video_kept=False` (model-only-take.md) the take is analysed as always, then the source video and every
    derived video or image leave the job folder; `drop_source(job id)` removes the raw upload and people media.
    `mirrored` (TICKET-310): the person said the upload is a mirrored video; Part 3 flips left and right.
    `floor_work` (the entry is marked floor work) goes to Part 3 as `--floor-work` where offered (floor-work.md).
    """

    def run(ctx: JobContext) -> dict[str, Any]:
        try:
            return _follow(ctx)
        finally:
            if not video_kept:  # after the analysis and the 3D files are written; a failed take keeps no video either
                model_only.purge_job(ctx.dir)
                if drop_source is not None:
                    drop_source(ctx.id)

    def _follow(ctx: JobContext) -> dict[str, Any]:
        video = _clip(ctx, raw, person, trim)
        expected_path = ctx.work / "expected.json"
        expected_path.write_bytes(expected)
        visibility_path = None
        if visibility is not None:
            visibility_path = ctx.work / "expected_skeleton.json"
            visibility_path.write_bytes(visibility)
        expected_video = None
        if trainer_video is not None:
            expected_video = ctx.work / "expected_video.mp4"
            expected_video.write_bytes(trainer_video)
        result = chain.follower(
            video, expected_path, ctx.work / "follower", report=ctx.set_stage, lock=lock, backend=backend,
            state=state, phrasing=phrasing, person=person, expected_visibility=visibility_path,
            mode=mode, lang=lang, expected_video=expected_video, private=private, mirrored=mirrored,
            floor_work=floor_work,
        )
        if result.get("note"):
            ctx.add_note(str(result["note"]))
        _raise_if_failed(result)
        files = result["files"]
        summary = quality_cap.apply(_score_summary(Path(files["analysis"])))  # Part 5 reports quality.score_cap; Part 7 applies it
        summary = light.apply(summary, light.measure(video))  # TICKET-247: Part 7 reads the light itself
        return {
            "result": {
                **summary,
                "trim": trim,
                "analysis": f"api/results/{ctx.id}/analysis.json",
                "replay": f"api/results/{ctx.id}/replay.json" if "replay" in files else None,
                **({} if video_kept else {model_only.FIELD: False}),
                **({"floor_work": True} if floor_scored(result, floor_work) else {}),
            },
        }

    return run
