"""SEEDED histories for the across-my-movements, recap and plan tests (labelled seeded: not a real student's takes).

`put_take` writes one kept take straight into the history store layout, with an analysis.json built from the arguments,
so a test controls every fault, cue, time and mode. Squats and a dance routine share a left knee cue, as the research
example says ("the left-knee cue came up in squats and in the dance routine").
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from part7 import history_store

SQUAT, DANCE, REHAB = "squat-aaaaaaaa", "dance-bbbbbbbb", "rehab-cccccccc"
KNEE = {"measure": "knee_valgus", "side": "left", "joint": "left_knee", "body_part": "knee", "cue": "Push the left knee out"}
CHEST = {"measure": "trunk_lean_forward", "side": "center", "joint": "spine", "body_part": "torso", "cue": "Keep your chest up"}
_n = {"count": 0}


def fault(kind: dict[str, Any], at_s: float, size: float = 20.0) -> dict[str, Any]:
    return {**kind, "at_s": at_s, "follower_t_s": [at_s, at_s + 0.5], "magnitude_deg": size, "text_timed": "x"}


def put_take(state: Path, user: str, entry: str, at: str, score: int, faults: list[dict[str, Any]], *, mode: str = "fitness",
             private: bool = False, section_key: str = "full", duration: float = 10.0, job: str | None = None) -> str:
    _n["count"] += 1
    job_id = job or f"{_n['count']:012x}"
    folder = history_store.take_dir(state, user, entry, job_id)
    analysis = {"status": {"code": "ok"}, "faults": faults, "score": {"value": score, "grade": "B", "version": "score.v1", "params_sha256": "ab" * 32,
                                            "timeline": [{"t_s": [0.0, duration], "compared": True, "misses": []}]}}
    history_store.write_json(folder / history_store.ANALYSIS_NAME, analysis)
    history_store.write_json(folder / history_store.META_NAME, {
        "job_id": job_id, "entry_id": entry, "at": at, "duration_s": duration, "duration_source": "test", "score": score, "grade": "B",
        "private": private, "section_key": section_key, "mode": mode, "score_version": "score.v1:abababab", "clip": False, "kept_ts": 1e12})
    return job_id


def seed(state: Path, user: str) -> dict[str, list[str]]:
    """Squats (3 takes, Oct then Nov), a dance routine (2 takes), one rehab take and one private squat take."""
    jobs: dict[str, list[str]] = {SQUAT: [], DANCE: [], REHAB: []}
    jobs[SQUAT] += [
        put_take(state, user, SQUAT, "2026-10-05T10:00:00Z", 60, [fault(KNEE, 2.0), fault(CHEST, 5.0)]),
        put_take(state, user, SQUAT, "2026-10-20T10:00:00Z", 75, [fault(KNEE, 2.1, 16.0)]),  # both later takes sit below the first (TICKET-214 steadier status)
        put_take(state, user, SQUAT, "2026-11-01T10:00:00Z", 80, [fault(KNEE, 2.1, 14.0)]),
    ]
    jobs[DANCE] += [
        put_take(state, user, DANCE, "2026-10-10T10:00:00Z", 50, [fault(KNEE, 3.0)], mode="dance"),
        put_take(state, user, DANCE, "2026-10-25T10:00:00Z", 70, [fault(KNEE, 3.1)], mode="dance"),
    ]
    jobs[REHAB] += [put_take(state, user, REHAB, "2026-10-12T10:00:00Z", 90, [fault(KNEE, 1.0)], mode="rehab")]
    put_take(state, user, SQUAT, "2026-10-26T10:00:00Z", 10, [fault(CHEST, 4.0)], private=True)
    return jobs
