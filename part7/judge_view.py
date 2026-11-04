"""The curated judge view (docs/specs/judge-view.md): what a judge sees first, and what stays out of it.

Nothing here deletes or edits data. Two things are decided:

- `is_test_id` / `is_test_challenge` / `judge_challenges`: the verify, check-7 and QA runs name the movements they make
  `verify-<UTC stamp>-<hash>`, `check-7-...` and `qa-...`; a board on such a movement is a test artefact. The judge
  view (`GET api/challenges?view=judge`) leaves those boards out. Without `view=judge` the list is unchanged, so the
  staging verify and the QA recipes still see their own boards.
- `page_with_profile`: on the judge URL (`SIMON7_DEFAULT_PROFILE=submission`) the page opens in the submission profile
  unless the visitor asks for `?profile=default`.
- `hero`: the finished take the home screen links to. Only a take an operator names (`SIMON7_HERO_JOB`, or `hero.json`
  in the state folder) is ever offered, and only while it qualifies. Nothing is picked on the operator's behalf: a job
  id is the key to its take (its clip, its result and its delete), so the route never hands out a take nobody chose
  to show (TICKET-373; the old best-scoring pick gave visitors a stranger's job id).

`GET api/judge/hero` answers `{job_id, entry_id, score, source}`, plus `shown` (part7/shown_score.py) when the take's
analysis is there; `job_id` is null when no take is named or the named take does not qualify.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from part7 import applog, heading, history_store, job_lookup, jobs, light, mesh_files, my_reference, quality_cap, shown_score

TEST_ID_RE = re.compile(r"^(verify|check-7|qa)-", re.IGNORECASE)
PROFILE_ENV = "SIMON7_DEFAULT_PROFILE"
PROFILE_META = b'<meta name="simon-default-profile" content="submission">'
HERO_ENV = "SIMON7_HERO_JOB"
HERO_FILE = "hero.json"
EVER_FILE = "hero-ever.json"  # every job id that was ever named hero (TICKET-374 R1), in the state dir
VIEW_JUDGE = "judge"
NO_HERO = {"job_id": None, "entry_id": None, "score": None, "source": "none"}


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


class _Everything:
    """Stands in for the ever-named list when it exists but cannot be read: every id counts as once featured (fail closed)."""

    def __contains__(self, _item: object) -> bool:
        return True

    def __iter__(self):
        return iter(())


def ever_named(state: Path) -> Any:
    """The set of every job id ever named hero (read as configured), which stays protected after the hero changes.

    A list that exists but cannot be read answers a set that contains everything: no take is then deletable by id."""
    path = Path(state) / EVER_FILE
    if not path.is_file():
        return set()
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        return {str(i) for i in doc["job_ids"]} if isinstance(doc, dict) and isinstance(doc.get("job_ids"), list) else _Everything()
    except (OSError, ValueError):
        return _Everything()


def _remember(state: Path, job_id: str) -> None:
    """Add `job_id` to the ever-named list; an unreadable list is left as it is."""
    known = ever_named(state)
    if isinstance(known, _Everything) or job_id in known:
        return
    try:
        history_store.write_json(Path(state) / EVER_FILE, {"job_ids": sorted(known | {job_id})})
    except OSError as exc:  # the hero still answers; the next read tries again
        applog.log(f"judge: could not record the hero {job_id}: {applog.cause(exc)}", level=logging.WARNING)


def configured_id(state: Path) -> str | None:
    """The operator-named hero job id (`SIMON7_HERO_JOB`, else `hero.json`), whether or not it qualifies; else None.

    Each id read here is also kept in `ever_named`, so a take once named stays protected from a visitor's delete and
    claim after the operator names another (and when `hero.json` later cannot be read)."""
    named = os.environ.get(HERO_ENV, "").strip()
    if not named:
        doc = job_lookup.read_json(Path(state) / HERO_FILE)
        value = doc.get("job_id") if isinstance(doc, dict) else None
        named = value.strip() if isinstance(value, str) and value.strip() else ""
    if named and jobs.JOB_ID_RE.match(named):
        _remember(Path(state), named)
    return named or None


def _candidate(state: Path, jobs_root: Path, job_id: str, may_view: Any = None) -> dict[str, Any] | None:
    """`{job_id, entry_id, score}` when `job_id` is a public, finished take of a non-test movement with both meshes
    that no account owns."""
    from part7 import take_access  # here: take_access imports this module

    if not jobs.JOB_ID_RE.match(job_id):
        return None
    if not take_access.may_feature(state, job_id):  # prod-data.md D4: an account's take is never the hero
        return None
    record = job_lookup.read_json(jobs_root / job_id / "job.json")
    if not isinstance(record, dict) or record.get("kind") != "follow" or record.get("status") != "done":
        return None
    entry_id = record.get("entry_id")
    if my_reference.uses_own(record):  # ADR-0019: never the hero
        return None
    if may_view is not None and not may_view(str(entry_id)):  # residual 5: a hidden movement is never the hero
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
    # one-letter.md: the hero line shows the result headline's score
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


def hero(state: Path, jobs_root: Path, may_view: Any = None) -> dict[str, Any]:
    """The take the judge view shows first: the named take when it qualifies, else none. A named take that does not
    qualify is ignored, not trusted, and no other take stands in for it. `may_view(entry_id)` (the route passes
    `auth.may_view_entry`) refuses a take whose movement the caller may not see."""
    named = configured_id(state)
    found = _candidate(state, jobs_root, named, may_view) if named else None
    if found:
        return {**found, "source": "configured"}
    return dict(NO_HERO)


def handle(h: Any, method: str, route: str) -> bool:
    """Answer `judge/hero`; False for any other route."""
    if route != "judge/hero" or method not in ("GET", "HEAD"):
        return False
    from part7 import auth  # here: the app's one rule for who sees a movement

    h._json(200, hero(h.app.state, h.app.queue.job_dir("0" * 12).parent,
                      may_view=lambda entry_id: auth.may_view_entry(h, entry_id)))
    return True
