"""What a movement's creator sees of the people who followed it (docs/specs/teacher-dashboard.md).

`collect(jobs_root, entry_id)` reads the finished solo follow jobs of one catalog movement straight from the job
folders: the score and grade from each take's own `analysis.json` (never from the job record), and the cues the
score gave. It carries no job id (not even a hash of one), no name and no path, so a public answer cannot hand out a result.
Each folder is parsed once per change of its files (a cache keyed by file mtimes), so a request costs one `stat` per job folder.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
import threading
from typing import Any

from part7 import applog, jobs

TAKES_MAX = 200  # the newest takes kept; the oldest are dropped, never the newest
TOP_CUES_PER_TAKE = 3
CUE_MAX = 120
CUES_MAX = 10  # rows of `cue_counts`


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _cue_text(value: Any) -> str | None:
    text = value.strip() if isinstance(value, str) else ""
    return text[:CUE_MAX] if text else None


def take_cues(score: dict[str, Any]) -> list[str]:
    """The distinct cues of one take, most repeated first, ties in the order the take showed them."""
    counts: dict[str, int] = {}
    windows = score.get("timeline")
    for window in windows if isinstance(windows, list) else []:
        if not isinstance(window, dict):
            continue
        found = [m.get("cue") for m in window.get("misses") or [] if isinstance(m, dict)]
        tempo = window.get("tempo")
        found.append(tempo.get("cue") if isinstance(tempo, dict) else None)
        for raw in found:
            text = _cue_text(raw)
            if text:
                counts[text] = counts.get(text, 0) + 1
    return sorted(counts, key=lambda text: -counts[text])  # sorted() is stable: ties keep first-seen order


def _take_of(job: dict[str, Any], analysis: dict[str, Any]) -> dict[str, Any] | None:
    """One take from a finished job and its analysis; None when the take has no usable score."""
    status, score = analysis.get("status"), analysis.get("score")
    if not isinstance(status, dict) or status.get("code") != "ok" or not isinstance(score, dict):
        return None
    value, grade = score.get("value"), score.get("grade")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isinstance(grade, str):
        return None
    at, cues = job.get("finished_at") or job.get("created_at"), take_cues(score)
    return {"at": at if isinstance(at, str) else "", "score": value, "grade": grade[:3], "top_cues": cues[:TOP_CUES_PER_TAKE], "_cues": cues}


def _skip(folder: Path, why: str) -> None:
    applog.log(f"teacher: skipped {folder.name}: {why}", level=logging.WARNING)


def _parse_folder(folder: Path) -> tuple[str, dict[str, Any] | None] | None:
    """`(entry_id, take or None)` of a finished solo follow job folder; None when it is not one (or is unreadable)."""
    try:
        job = _read_json(folder / "job.json")
    except (OSError, ValueError):
        _skip(folder, "job.json is not readable JSON")
        return None
    if not isinstance(job, dict):
        _skip(folder, "job.json is not an object")
        return None
    entry = job.get("entry_id")
    if job.get("kind") != "follow" or job.get("status") != "done" or not isinstance(entry, str):
        return None
    if job.get("private") is True:  # a private take (private-mode.md) never reaches a public page
        return None
    try:
        analysis = _read_json(folder / "work" / "follower" / "analysis.json")
    except (OSError, ValueError):
        _skip(folder, "analysis.json is missing or not readable JSON")
        return None
    return entry, (_take_of(job, analysis) if isinstance(analysis, dict) else None)


def _mtime(path: Path) -> int:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return -1


_CACHE: dict[str, dict[str, tuple[tuple[int, int], Any]]] = {}  # jobs root -> folder name -> (file stamps, parsed)
_CACHE_LOCK = threading.Lock()


def _finished_takes(jobs_root: Path, entry_id: str) -> list[dict[str, Any]]:
    """The takes of `entry_id`, each parsed again only when its `job.json` or `analysis.json` changed."""
    key = str(jobs_root)
    with _CACHE_LOCK:
        old = _CACHE.get(key, {})
    fresh: dict[str, tuple[tuple[int, int], Any]] = {}
    takes: list[dict[str, Any]] = []
    for record in sorted(Path(jobs_root).glob("*/job.json")):
        folder = record.parent
        if not jobs.JOB_ID_RE.match(folder.name):
            continue
        stamp = (_mtime(record), _mtime(folder / "work" / "follower" / "analysis.json"))
        cached = old.get(folder.name)
        parsed = cached[1] if cached and cached[0] == stamp else _parse_folder(folder)
        fresh[folder.name] = (stamp, parsed)
        if parsed and parsed[0] == entry_id and parsed[1] is not None:
            takes.append({**parsed[1], "_folder": folder.name})
    with _CACHE_LOCK:
        _CACHE[key] = fresh  # folders that are gone drop out here
    return takes


def collect(jobs_root: Path | str, entry_id: str) -> dict[str, Any]:
    """`{entry, takes, cue_counts}` for `entry_id`.

    Takes run oldest first and carry `n`, their 1-based position in that list: a label for the row that is derived from
    nothing about the job (a hash of a 48-bit job id can be searched back to the id, which is the follower's key).
    `cue_counts` are by the number of takes showing the cue.
    """
    found = sorted(_finished_takes(Path(jobs_root), entry_id), key=lambda t: (t["at"], t["_folder"]))[-TAKES_MAX:]
    counts: dict[str, int] = {}
    takes = []
    for n, take in enumerate(found, start=1):
        for text in take["_cues"]:
            counts[text] = counts.get(text, 0) + 1
        takes.append({"n": n, "at": take["at"], "score": take["score"], "grade": take["grade"], "top_cues": take["top_cues"]})
    ranked = sorted(counts, key=lambda text: (-counts[text], text))[:CUES_MAX]
    return {"entry": entry_id, "takes": takes, "cue_counts": [{"text": text, "count": counts[text]} for text in ranked]}
