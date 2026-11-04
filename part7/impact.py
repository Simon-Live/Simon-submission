"""The Impact page's persona takes (docs/specs/impact-page.md): one finished take per demo scenario, or none.

The takes are named in a JSON file, an array of
`{persona, job_id, entry_id, take_url, trainer_entry_url, score, mode, clip_source: {url, licence, file},
why_this_clip, recorded_utc, staging_sha}`. Where it is read, first found wins:

1. `SIMON7_PERSONA_TAKES`, a path to such a file;
2. `<state dir>/persona-takes.json` (staging sets it without a restart);
3. `docs/impact/persona-takes.json` in the repo.

A named take is shown only when this server holds it as a finished, scored follow take of a non-test movement that
is not private, on the movement the file names. Anything else is reported as missing, never trusted.

`GET api/impact` answers `{source, personas: [{persona, take | null, missing}]}` with the four personas in order.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from part7 import config, history_store, job_lookup, jobs, judge_view

PERSONAS = ("seated", "bodies", "home-rehab", "remote-class")
ENV = "SIMON7_PERSONA_TAKES"
STATE_FILE = "persona-takes.json"
REPO_FILE = Path("docs") / "impact" / "persona-takes.json"
HTTPS_RE = re.compile(r"^https://[^\s\"'<>]+$")
TEXT_MAX = 400


def _source(state: Path, repo_root: Path) -> tuple[str, Path | None]:
    named = os.environ.get(ENV, "").strip()
    if named:
        return "env", Path(named)
    if (state / STATE_FILE).is_file():
        return "state", state / STATE_FILE
    if (repo_root / REPO_FILE).is_file():
        return "repo", repo_root / REPO_FILE
    return "none", None


def _text(value: Any) -> str | None:
    return value.strip()[:TEXT_MAX] if isinstance(value, str) and value.strip() else None


def _clip(doc: Any) -> dict[str, Any] | None:
    """The clip's licence and source page; a source that is not an https URL is dropped, not shown."""
    if not isinstance(doc, dict):
        return None
    url = doc.get("url") if isinstance(doc.get("url"), str) and HTTPS_RE.match(doc["url"]) else None
    licence = _text(doc.get("licence"))
    return {"url": url, "licence": licence} if url or licence else None


def _take(row: dict[str, Any], jobs_root: Path) -> tuple[dict[str, Any] | None, str]:
    """`(take, "")` when the named job qualifies here, else `(None, reason)`."""
    job_id = row.get("job_id")
    if not isinstance(job_id, str) or not jobs.JOB_ID_RE.match(job_id):
        return None, "not_found"
    record = job_lookup.read_json(jobs_root / job_id / "job.json")
    if not isinstance(record, dict) or record.get("kind") != "follow" or record.get("status") != "done":
        return None, "not_found"
    result = record.get("result") if isinstance(record.get("result"), dict) else {}
    score = result.get("score")
    entry_id = record.get("entry_id")
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        return None, "not_found"
    if judge_view.is_test_id(entry_id) or history_store.is_private(record):
        return None, "not_found"
    if row.get("entry_id") not in (None, entry_id):
        return None, "not_found"
    mode = _text(record.get("mode")) or _text(result.get("mode")) or _text(row.get("mode"))
    return {
        "job_id": job_id, "entry_id": entry_id, "score": score, "mode": mode,
        "clip_source": _clip(row.get("clip_source")), "why_this_clip": _text(row.get("why_this_clip")),
        "recorded_utc": _text(row.get("recorded_utc")),
    }, ""


def named_job_ids(state: Path, repo_root: Path | None = None) -> set[str]:
    """Every job id the persona file names, whether or not it qualifies today: those ids are public, so
    `delete_routes.featured` treats every one as featured (TICKET-373)."""
    _, path = _source(state, repo_root or config.REPO_ROOT)
    doc = job_lookup.read_json(path) if path else None
    rows = doc if isinstance(doc, list) else []
    return {r["job_id"] for r in rows if isinstance(r, dict) and isinstance(r.get("job_id"), str)}


def personas(state: Path, jobs_root: Path, repo_root: Path | None = None) -> dict[str, Any]:
    """The four persona cards' data; a persona without a qualifying take has `take: null` and a `missing` reason."""
    source, path = _source(state, repo_root or config.REPO_ROOT)
    doc = job_lookup.read_json(path) if path else None
    rows = [r for r in doc if isinstance(r, dict)] if isinstance(doc, list) else []
    named = {}
    for row in rows:
        if row.get("persona") in PERSONAS and row["persona"] not in named:
            named[row["persona"]] = row
    out = []
    for persona in PERSONAS:
        row = named.get(persona)
        take, reason = _take(row, jobs_root) if row else (None, "not_listed")
        out.append({"persona": persona, "take": take, "missing": reason or None})
    return {"source": source, "personas": out}


def handle(h: Any, method: str, route: str) -> bool:
    """Answer `impact`; False for any other route."""
    if route != "impact" or method not in ("GET", "HEAD"):
        return False
    h._json(200, personas(h.app.state, h.app.queue.job_dir("0" * 12).parent))
    return True
