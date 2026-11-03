"""The curated judge view (docs/specs/judge-view.md): what a judge sees first, and what stays out of it.

Nothing here deletes or edits data. Two things are decided:

- `is_test_id` / `is_test_challenge` / `judge_challenges`: the verify, check-7 and QA runs name the movements they make
  `verify-<UTC stamp>-<hash>`, `check-7-...` and `qa-...`; a board on such a movement is a test artefact. The judge
  view (`GET api/challenges?view=judge`) leaves those boards out. Without `view=judge` the list is unchanged, so the
  staging verify and the QA recipes still see their own boards.
- `page_with_profile`: on the judge URL (`SIMON7_DEFAULT_PROFILE=submission`) the page opens in the submission profile
  unless the visitor asks for `?profile=default`.
- `hero`: the finished take the home screen links to. An operator names it (`SIMON7_HERO_JOB`, or `hero.json` in the
  state folder); otherwise the best-scoring finished take of a non-test movement that has both people's meshes.

`GET api/judge/hero` answers `{job_id, entry_id, score, source}`, plus `shown` (part7/shown_score.py) when the take's
analysis is there; `job_id` is null when no take qualifies.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from part7 import heading, history_store, job_lookup, jobs, light, mesh_files, my_reference, quality_cap, shown_score

TEST_ID_RE = re.compile(r"^(verify|check-7|qa)-", re.IGNORECASE)
PROFILE_ENV = "SIMON7_DEFAULT_PROFILE"
PROFILE_META = b'<meta name="simon-default-profile" content="submission">'
HERO_ENV = "SIMON7_HERO_JOB"
HERO_FILE = "hero.json"
VIEW_JUDGE = "judge"


def is_test_id(entry_id: Any) -> bool:
    """True for a movement id that a verify, check-7 or QA run made."""
    return bool(TEST_ID_RE.match(str(entry_id or "")))


def is_test_challenge(doc: dict[str, Any]) -> bool:
    return is_test_id(doc.get("entry_id"))


def judge_challenges(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """`rows` (challenge summaries) without the boards on test movements."""
    return [row for row in rows if not is_test_challenge(row)]


def default_profile() -> str:
    """"submission" when this server is the judge URL (`SIMON7_DEFAULT_PROFILE=submission`), else "default"."""
    return "submission" if os.environ.get(PROFILE_ENV, "").strip().lower() == "submission" else "default"


def page_with_profile(html: bytes) -> bytes:
    """`html` (web/index.html) with the default profile written in as a meta tag, which web/flags.js reads.

    A visitor's `?profile=default` or `?profile=submission` still wins and is remembered there.
    """
    if default_profile() != "submission" or PROFILE_META in html:
        return html
    return html.replace(b"</head>", PROFILE_META + b"\n</head>", 1)


def _configured_id(state: Path) -> str | None:
    named = os.environ.get(HERO_ENV, "").strip()
    if named:
        return named
    doc = job_lookup.read_json(state / HERO_FILE)
    value = doc.get("job_id") if isinstance(doc, dict) else None
    return value.strip() if isinstance(value, str) and value.strip() else None


def _candidate(jobs_root: Path, job_id: str) -> dict[str, Any] | None:
    """`{job_id, entry_id, score}` when `job_id` is a public, finished take of a non-test movement with both meshes."""
    if not jobs.JOB_ID_RE.match(job_id):
        return None
    record = job_lookup.read_json(jobs_root / job_id / "job.json")
    if not isinstance(record, dict) or record.get("kind") != "follow" or record.get("status") != "done":
        return None
    entry_id = record.get("entry_id")
    if my_reference.uses_own(record):  # ADR-0019: never the hero
        return None
    result = record.get("result")
    score = result.get("score") if isinstance(result, dict) else None
    if is_test_id(entry_id) or history_store.is_private(record) or isinstance(score, bool) or not isinstance(score, (int, float)):
        return None
    meshes = mesh_files.index(jobs_root, job_id)
    if not meshes or not all(meshes.values()):
        return None
    if _warned(jobs_root / job_id, result):  # a capped or warned take is never what a judge sees first
        return None
    # one-letter.md: the hero line shows the result headline's score; the pick (`_best`) still sorts by `score`
    shown = shown_score.of_path(jobs_root / job_id / "work" / "follower" / "analysis.json", result.get("light"))
    return {"job_id": job_id, "entry_id": entry_id, "score": score, **({"shown": shown} if shown else {})}


def _warned(folder: Path, result: dict[str, Any]) -> bool:
    """True when the take carries a warning, a warning cap or a low match, or its analysis status is not ok."""
    if result.get("status_code") not in (None, "ok"):
        return True
    if light.level_of(result.get("light")) != "ok":
        return True  # TICKET-247: a dim or dark take is never the hero
    if quality_cap.level_of(result.get("quality")) in ("degraded", "major"):
        return True  # Part 5's quality block above ok: never the hero (a missing block is not assessed, not excluded)
    if heading.is_rough(result.get("quality")):
        return True  # TICKET-246: filmed from another angle than the trainer, a rough score, never the hero
    rel = result.get("analysis")
    path = folder / rel if isinstance(rel, str) and rel and ".." not in rel else None
    found = list(folder.glob("**/analysis.json")) if path is None or not path.is_file() else [path]
    doc = job_lookup.read_json(found[0]) if found else None
    if not isinstance(doc, dict):
        return False  # no analysis file: the job result alone decides
    score = doc.get("score") if isinstance(doc.get("score"), dict) else {}
    match = doc.get("match") if isinstance(doc.get("match"), dict) else {}
    if quality_cap.level_of(doc.get("quality")) in ("degraded", "major"):
        return True
    if heading.is_rough(doc.get("quality")):
        return True  # TICKET-246, from the analysis file
    return bool(doc.get("warnings") or score.get("capped_by") or match.get("quality") == "low"
                or (doc.get("status") or {}).get("code", "ok") != "ok")


_MEASURES: dict[str, tuple[int, float]] = {}  # job folder -> (analysis mtime, shown measure): each analysis is read once


def _measure(folder: Path, result: dict[str, Any], score: float) -> float:
    """The take's shown measure (one-letter.md L3: the credit percent shown, else the capped score), else `score`."""
    path = folder / "work" / "follower" / "analysis.json"
    try:
        stamp = path.stat().st_mtime_ns
    except OSError:
        return score
    hit = _MEASURES.get(str(folder))
    if hit and hit[0] == stamp:
        return hit[1]
    shown = shown_score.shown(job_lookup.read_json(path), result.get("light"))
    measure = float(shown["measure"]) if shown else score
    _MEASURES[str(folder)] = (stamp, measure)
    return measure


def _best(jobs_root: Path) -> dict[str, Any] | None:
    scored: list[tuple[float, str]] = []
    try:
        folders = [p for p in jobs_root.iterdir() if p.is_dir()]
    except OSError:
        return None
    for folder in folders:
        record = job_lookup.read_json(folder / "job.json")
        result = record.get("result") if isinstance(record, dict) else None
        score = result.get("score") if isinstance(result, dict) else None
        if isinstance(score, (int, float)) and not isinstance(score, bool):
            scored.append((_measure(folder, result, float(score)), folder.name))
    for _, job_id in sorted(scored, reverse=True):  # best shown measure first; the first one that qualifies wins
        found = _candidate(jobs_root, job_id)
        if found:
            return found
    return None


def hero(state: Path, jobs_root: Path) -> dict[str, Any]:
    """The take the judge view shows first. A named take that does not qualify is ignored, not trusted."""
    named = _configured_id(state)
    found = _candidate(jobs_root, named) if named else None
    if found:
        return {**found, "source": "configured"}
    found = _best(jobs_root)
    if found:
        return {**found, "source": "best"}
    return {"job_id": None, "entry_id": None, "score": None, "source": "none"}


def handle(h: Any, method: str, route: str) -> bool:
    """Answer `judge/hero`; False for any other route."""
    if route != "judge/hero" or method not in ("GET", "HEAD"):
        return False
    h._json(200, hero(h.app.state, h.app.queue.job_dir("0" * 12).parent))
    return True
