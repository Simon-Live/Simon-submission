"""Which Meta models ran for one person of a group result (docs/specs/group-results.md R2).

`collect(jobs_root, job_id, pid)` returns `{job, person, job_seconds, models: [row, ...]}` with the same row shape as
`models_used.collect`, or None when `job_id` is not a done group job or `pid` is not one of its analysed people.
Only rows about that person's own take: SAM 3.1 tracking of the clip (from the people job's tracks provenance), SAM 3D
Body and the MHR rig (the group's one Part 2 run lists its models; no frame counts, so nothing about another person
leaks), and Muse Spark / Muse Glimmer wording and the second opinion read from the person's own `analysis.json`
(the wording rows carry no seconds: Part 5's time is not kept per person). The trainer person's rows, account rows and the other takes of the group never appear.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from part7 import group, models_used as mu

PERSON_ROWS = ("sam31-you", "sam3d-you", "mhr-you", "spark-phrasing", "glimmer-phrasing", "spark-opinion")


def _analysed(record: dict[str, Any], pid: str) -> bool:
    people = (record.get("result") or {}).get("people")
    return any(isinstance(p, dict) and p.get("id") == pid and p.get("analysis") for p in people or [])


def _body_rows(job_dir: Path) -> list[dict[str, Any]]:
    """SAM 3D Body and MHR from the provenance of the group's single Part 2 run."""
    pose = mu._json(job_dir / "work" / "part2" / "pose3d.json")
    prov = pose.get("provenance") if isinstance(pose, dict) else None
    secs = mu.step_seconds(job_dir).get("part2.log")
    if not isinstance(prov, dict):
        return [mu._row("sam3d-you", "SAM 3D Body", "you", "unknown", reason="no_pose_file"),
                mu._row("mhr-you", "MHR", "you", "unknown", reason="no_pose_file")]
    names = [str(m.get("name") or "") for m in prov.get("models") or [] if isinstance(m, dict)]
    if not any(n.startswith(mu.SAM3D) for n in names):
        ran = prov.get("lifter") or prov.get("backend") or "unknown"
        return [mu._row("sam3d-you", "SAM 3D Body", "you", "fallback", secs, ran=ran),
                mu._row("mhr-you", "MHR", "you", "not_run", reason="no_body_model")]
    mhr = (mu._row("mhr-you", "MHR", "you", "live", secs, via="local_gpu") if mu.MHR in names
           else mu._row("mhr-you", "MHR", "you", "unknown", reason="no_rig_record"))
    return [mu._row("sam3d-you", "SAM 3D Body", "you", "live", secs, via="local_gpu"), mhr]


def collect(jobs_root: Path, job_id: str, pid: str) -> dict[str, Any] | None:
    job_dir = jobs_root / job_id
    record = mu._json(job_dir / "job.json")
    if not isinstance(record, dict) or record.get("kind") != "group" or record.get("status") != "done" or not _analysed(record, pid):
        return None
    analysis = group.person_dir(job_dir, pid) / "analysis.json"
    # Part 5 logs every person's run under one name (part5_analyse.log) in the job-wide log, so a time read from it is
    # the last person's: the per-person wording rows carry no seconds.
    own = [{**r, "seconds": None} for r in (mu.phrasing_row(job_dir, analysis), mu.glimmer_row(job_dir, record, analysis))]
    rows = [mu.people_tracking_row(jobs_root, record.get("people_job")), *_body_rows(job_dir), *own,
            mu.opinion_row(job_dir, analysis)]
    rows.sort(key=lambda r: mu.ORDER.index(r["id"]))
    return {"job": job_id, "person": pid, "job_seconds": mu._job_seconds(record), "models": rows}
