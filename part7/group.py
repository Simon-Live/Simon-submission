"""The group job: one recording of a trainer and a class, each person against the trainer (TICKET-059).

Part 2 runs once for everyone chosen, the trainer goes through the trainer chain (and into the catalog when
asked), then every follower goes through the follower chain against the trainer's animation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from part7 import chain, failcause, labels as entry_store, modules, shown_score
from part7.jobs import JobContext, JobFailed, JobFn
from part7.parts import p2_pose
from part7.people import PersonSel, pose_for, reused_clip
from part7.processor import _raise_if_failed, _score_summary


def person_dir(job_dir: Path, pid: str) -> Path:
    """Where person `pid`'s analysis.json and replay.json live in group job `job_dir`."""
    return job_dir / "work" / "person" / pid


def with_shown(job: dict[str, Any], job_dir: Path) -> dict[str, Any]:
    """A finished group job with each person's `shown` (part7/shown_score.py) read now from their own analysis.json, so a
    result stored before the block existed (staging jobs dbf5d47d974d, 6be0bf0fb8fc) still says why a grade is F
    (one-letter.md L5). The stored order and record are left as they are; a person without an analysis gets none."""
    result = job.get("result")
    if job.get("status") != "done" or not isinstance(result, dict) or not isinstance(result.get("people"), list):
        return job
    people = [{**p, "shown": shown_score.of_path(person_dir(Path(job_dir), str(p["id"])) / "analysis.json")}
              if isinstance(p, dict) and isinstance(p.get("id"), (str, int)) and not isinstance(p.get("id"), bool) else p
              for p in result["people"]]
    return {**job, "result": {**result, "people": people}}


def order(people: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Highest shown measure first (one-letter.md L3: the credit percent shown, else the capped score); takes without a
    score (refused or failed) last, each side in the given order."""
    return sorted(people, key=lambda p: (shown_score.rank_of(p) is None, -(shown_score.rank_of(p) or 0)))


def _follower_row(job_id: str, pid: str, label: str, res: dict[str, Any]) -> dict[str, Any]:
    """One row of the group result from a follower chain result."""
    if not res.get("ok"):
        reason = str(res.get("error") or "the analysis failed").split(": ", 2)[-1]
        return {"id": pid, "label": label, "status_code": "error", "score": None, "grade": None, "faults": 0,
                "analysis": None, "replay": None, "reason": reason}
    summary = _score_summary(Path(res["files"]["analysis"]))
    base = f"api/results/{job_id}/{pid}"
    return {
        "id": pid, "label": label, "status_code": summary.get("status_code") or res.get("status"),
        "score": summary.get("score"), "grade": summary.get("grade"), "faults": summary.get("faults", 0),
        "shown": shown_score.of_path(res["files"]["analysis"]),  # one-letter.md: the row shows this; `order` still sorts by score
        "analysis": f"{base}/analysis.json", "replay": f"{base}/replay.json" if "replay" in res["files"] else None,
        **({"quality": summary["quality"]} if "quality" in summary else {}),
    }


def group_job(
    *,
    people_work: Path,
    trainer_id: str,
    follower_ids: list[str],
    name: str,
    category: str,
    catalog: Path,
    labels: dict[str, str] | None = None,
    entry_labels: dict[str, Any] | None = None,
    labels_state: Path | None = None,
    save_entry: bool = True,
    lock: modules.Modules | None = None,
    state: Path | str | None = None,
    backend: str = "gpu",
    phrasing: str = "live",
    mode: str | None = None,
    floor_work: bool = False,
) -> JobFn:
    """Return the job function of `POST api/group` on the people job whose work folder is `people_work`."""

    def run(ctx: JobContext) -> dict[str, Any]:
        lk = lock or modules.load()
        sel = PersonSel(id=trainer_id, people_work=people_work)
        video = reused_clip(ctx, sel)
        ctx.set_stage("track")  # the people job already tracked everyone; its tracks are reused
        if not (people_work / "tracks.json").is_file():
            raise JobFailed("track", "the chosen clip is no longer available, choose the people again")
        pose3d = _pose_once(ctx, sel, [trainer_id, *follower_ids], video, backend, lk, state)
        sel = PersonSel(id=trainer_id, people_work=people_work, pose3d=pose3d)

        def to_stage(stage: str) -> None:
            ctx.set_stage("catalog" if stage == "catalog" else "trainer")

        trained = chain.trainer(
            video, ctx.work / "trainer", report=to_stage, lock=lk, backend=backend, state=state,
            catalog=catalog if save_entry else None, name=name, category=category, person=sel,
            floor_work=floor_work,
        )
        if trained.get("note"):
            ctx.add_note(str(trained["note"]))
        _raise_if_failed(trained)
        entry_id = trained.get("entry_id")
        save_new = entry_store.entry_saver(labels_state, entry_labels or None, floor_work) if labels_state is not None else None
        if entry_id and save_new is not None:
            save_new(str(entry_id))  # recorder.md "Labels" and floor-work.md: part7/labels.py
        rows = _followers(ctx, trained["files"]["animation"], trained["files"]["skeleton"], video, people_work, pose3d,
                          follower_ids, labels or {}, lk, backend, state, phrasing, mode, floor_work)
        result = {"entry_id": entry_id, "trainer_id": trainer_id, "people": order(rows)}
        return {"entry_id": entry_id, "result": result}

    return run


def _pose_once(
    ctx: JobContext, sel: PersonSel, ids: list[str], video: Path, backend: str, lk: modules.Modules,
    state: Path | str | None,
) -> Path:
    """Part 2 for everyone chosen at once, then its doctor; JobFailed with a plain reason."""
    ctx.set_stage("pose")
    try:
        step, pose3d, note = pose_for(sel, ids, video, ctx.work, backend, lk, state)
    except TimeoutError:
        raise JobFailed("pose", "the GPU is busy, try again later") from None
    except RuntimeError:
        raise JobFailed("pose", "the 3D step is not available") from None
    if note:
        ctx.add_note(note)
    if step["exit"] != 0 or not pose3d.is_file():
        cause, text = failcause.classify("3D", step)
        raise JobFailed("pose", text, cause)
    if p2_pose.doctor(pose3d, ctx.work, lock=lk, state=state)["exit"] != 0:
        raise JobFailed("pose", "pose3d.json was rejected by part 2")
    return pose3d


def _followers(
    ctx: JobContext, animation: str, skeleton: str, video: Path, people_work: Path, pose3d: Path,
    follower_ids: list[str], labels: dict[str, str], lk: modules.Modules, backend: str, state: Path | str | None,
    phrasing: str, mode: str | None = None, floor_work: bool = False,
) -> list[dict[str, Any]]:
    """Run the follower chain for each id against the trainer's animation; a failure is a row, not the job."""
    rows: list[dict[str, Any]] = []
    total = len(follower_ids)
    for k, pid in enumerate(follower_ids, start=1):
        ctx.set_stage("followers")
        ctx._queue.update(ctx.id, progress=f"{k} of {total}")
        folder = person_dir(ctx.dir, pid)
        res = chain.follower(
            video, animation, folder, lock=lk, backend=backend, state=state, phrasing=phrasing,
            person=PersonSel(id=pid, people_work=people_work, pose3d=pose3d), expected_visibility=skeleton,
            mode=mode, floor_work=floor_work,
        )
        if res.get("note"):
            ctx.add_note(f"person {pid}: {res['note']}")
        rows.append(_follower_row(ctx.id, pid, labels.get(pid) or f"Person {pid}", res))
    return rows
