"""The measured stage split of one follow job, read from its own `steps/part7.log` (docs/specs/judge-take.md, TICKET-260).

`jobs.summary_line` writes one `job <id> summary: kind=.. status=.. total=..s <stage>=..s[(gpu_wait=..s)] ...` line
when a job ends. `split(queue, job_id, job)` reads that line back for the result screen: the seconds of each stage
in the order they ran, the total, and whether the person picker was skipped (the people job chose its one person
itself, `auto_id`). Nothing is estimated: a job with no summary line answers `{"recorded": false}`, never zeros.
"""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any

SUMMARY_RE = re.compile(r"job (?P<id>[0-9A-Za-z_-]+) summary: (?P<rest>.*)$")
STAGE_RE = re.compile(r"^(?P<name>[a-z_][a-z0-9_]*)=(?P<s>\d+(?:\.\d+)?)s(?:\(gpu_wait=(?P<wait>\d+(?:\.\d+)?)s\))?$")
NOT_STAGES = frozenset({"total"})
NOT_RECORDED: dict[str, Any] = {"recorded": False}


def _log_text(job_dir: Path) -> str:
    try:
        return (job_dir / "steps" / "part7.log").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def parse_summary(text: str, job_id: str) -> dict[str, Any] | None:
    """`{status, total_s, stages: [{name, seconds, gpu_wait_s?}]}` from the last summary line of `job_id`, else None."""
    found = None
    for line in text.splitlines():
        m = SUMMARY_RE.search(line)
        if m and m.group("id") == job_id:
            found = m.group("rest")
    if found is None:
        return None
    status, total, stages = None, None, []
    for token in found.split():
        if token.startswith("status="):
            status = token.split("=", 1)[1]
            continue
        if token.startswith("total=") and token.endswith("s"):
            try:
                total = float(token[len("total="):-1])
            except ValueError:
                total = None
            continue
        m = STAGE_RE.match(token)
        if m and m.group("name") not in NOT_STAGES:
            row: dict[str, Any] = {"name": m.group("name"), "seconds": float(m.group("s"))}
            if m.group("wait"):
                row["gpu_wait_s"] = float(m.group("wait"))
            stages.append(row)
    if total is None:
        return None
    return {"status": status, "total_s": total, "stages": stages}


def _people(queue: Any, people_job: Any, person_id: Any) -> dict[str, Any]:
    """`picker` ("skipped" or "shown") and `people_s`, from the people job this take chose its person in."""
    if not isinstance(people_job, str):
        return {}
    pjob = queue.get(people_job) or {}
    out: dict[str, Any] = {}
    result = pjob.get("result") if isinstance(pjob.get("result"), dict) else {}
    auto = result.get("auto_id")
    if person_id is not None and result:
        out["picker"] = "skipped" if auto is not None and str(auto) == str(person_id) else "shown"
    found = parse_summary(_log_text(queue.job_dir(people_job)), people_job)
    if found is not None:
        out["people_s"] = found["total_s"]
    return out


def split(queue: Any, job_id: str, job: dict[str, Any]) -> dict[str, Any]:
    """The `timing` field of a follow job's answer: `{recorded: true, total_s, stages, picker?, people_s?}` or not recorded."""
    found = parse_summary(_log_text(queue.job_dir(job_id)), job_id)
    if found is None or not found["stages"]:
        return dict(NOT_RECORDED)
    return {"recorded": True, **found, **_people(queue, job.get("people_job"), job.get("person_id"))}
