"""Helpers of the progress-sheet tests (docs/specs/progress-sheet.md, TICKET-283): real Part 5 files, tracked takes on given days."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
from typing import Any

from part7 import history_store, identity

ROOT = Path(__file__).resolve().parents[2]
ENTRY = "body-squat-19b06562"
JOB_TEMPLATE = ROOT / "tests" / "part7" / "fixtures" / "history" / "cc7cd5469055" / "job.json"
REAL_ANALYSIS = ROOT / "tests" / "part7" / "fixtures" / "analysis" / "real-part5-1.9.0-es-live.analysis.json"
REAL_REPLAY = ROOT / "fixtures" / "input" / "replay.json"
DAYS = ("2026-10-27", "2026-10-28", "2026-10-28", "2026-10-30", "2026-11-01")  # five sessions on four days


def job_id(n: int) -> str:
    return f"{n:012x}"


def seed(state: Path, db: identity.IdentityStore, user: str, job: str, day: str, *, mode: str | None = "rehab",
         replay: bool = True, entry: str = ENTRY) -> bool:
    """A finished follow job of `user` with the real analysis (and replay) on `day`, then its history copy."""
    folder = state / "jobs" / job
    (folder / "work" / "follower").mkdir(parents=True, exist_ok=True)
    record: dict[str, Any] = {**json.loads(JOB_TEMPLATE.read_text()), "id": job, "entry_id": entry,
                              "created_at": f"{day}T09:00:00Z", "finished_at": f"{day}T09:05:00Z"}
    record.pop("mode", None)
    if mode:
        record["mode"] = mode
    (folder / "job.json").write_text(json.dumps(record))
    shutil.copyfile(REAL_ANALYSIS, folder / "work" / "follower" / "analysis.json")
    if replay:
        shutil.copyfile(REAL_REPLAY, folder / "work" / "follower" / "replay.json")
    assert db.attach(job, user, "follow", entry, None, "claim")
    return history_store.record_take(state, record, folder)


def seed_five(state: Path, db: identity.IdentityStore, user: str) -> list[str]:
    jobs = [job_id(0xA00 + i) for i in range(len(DAYS))]
    for job, day in zip(jobs, DAYS):
        assert seed(state, db, user, job, day)
    return jobs
