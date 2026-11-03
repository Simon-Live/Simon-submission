"""Seed a synthetic class on one movement for the teacher page's class table (TICKET-273, docs/specs/class-table.md).

    SIMON7_STAGING=1 uv run python tools/seed_class.py --state <state dir> [--entry <entry id>]

Writes six finished follow jobs from three seeded followers into `<state>/jobs`, the folders `teacher_stats` reads. Each
job record and each analysis carries `synthetic: true`, so the page says "Seeded demo data" over the table; the record's
`seed_follower` ("1" to "3") groups the takes, and no account is made. The analyses are the seed_history template with
only faults, score and timeline replaced (`seed_history.SEED_EDIT`). Refuses without `SIMON7_STAGING=1`. Run it again and
the same job ids are rewritten with fresh times (job folders are kept 7 days from their last write).
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from part7 import history_store  # noqa: E402
import seed_history as sh  # noqa: E402

# (follower, days ago, score, faults): follower 1 returns twice, follower 2 once, follower 3 has one take. The knee
# fault reaches all three followers, so it is the class's top cue; the lean reaches one.
PLAN: tuple[tuple[str, float, int, list[tuple[tuple[str, str], float]]], ...] = (
    ("1", 6.0, 58, [(sh.KNEE, 18.0), (sh.LEAN, 14.0)]),
    ("2", 5.0, 61, [(sh.KNEE, 16.0)]),
    ("1", 3.0, 69, [(sh.KNEE, 10.0)]),
    ("3", 2.0, 72, [(sh.KNEE, 9.0)]),
    ("2", 1.0, 70, [(sh.KNEE, 8.0)]),
    ("1", 0.2, 81, []),
)


def job_id_for(entry: str, n: int) -> str:
    return hashlib.sha256(f"seed-class|{entry}|{n}".encode()).hexdigest()[:12]


def _stamp(at: datetime) -> str:
    return at.strftime("%Y-%m-%dT%H:%M:%SZ")


def seed(state: Path, entry: str = sh.SQUAT, now: datetime | None = None) -> list[str]:
    """Write the seeded jobs; returns their ids. Refuses (`sh.SeedError`) unless this is staging."""
    sh.guard(emails=())
    now = now or datetime.now(timezone.utc)
    template = json.loads(sh.TEMPLATE.read_text(encoding="utf-8"))
    written = []
    for n, (follower, days, score, faults) in enumerate(PLAN, 1):
        job, at = job_id_for(entry, n), now - timedelta(days=days)
        folder = Path(state) / "jobs" / job
        (folder / "work" / "follower").mkdir(parents=True, exist_ok=True)
        spec: dict[str, Any] = {"score": score, "faults": faults}
        history_store.write_json(folder / "work" / "follower" / "analysis.json", sh.analysis_for(template, spec))
        history_store.write_json(folder / "job.json", {
            "id": job, "kind": "follow", "status": "done", "stage": None, "stages": [], "note": None, "entry_id": entry,
            "result": None, "reason": None, "error": None, "created_at": _stamp(at), "started_at": _stamp(at),
            "finished_at": _stamp(at), "synthetic": True, "seed_follower": follower})
        written.append(job)
    return written


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--state", required=True, type=Path)
    ap.add_argument("--entry", default=sh.SQUAT)
    args = ap.parse_args(argv)
    try:
        jobs = seed(args.state, args.entry)
    except sh.SeedError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(f"seeded {len(jobs)} synthetic follow takes from 3 seeded followers on {args.entry}")
    print(f"Open #/teacher/{args.entry}. The class table is labelled seeded.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
