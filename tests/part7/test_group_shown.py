"""A group job's people carry `shown` at read time (docs/specs/one-letter.md L5), so a stored group result written before
the block existed still says why every grade is F.

Staging a1c2f6886: 44's dance group jobs dbf5d47d974d and 6be0bf0fb8fc finished at 17:32Z and 18:03Z, before the
`shown` block was written into new group results, so their stored people have id, label, status_code, score, grade,
faults, analysis, replay and quality and no `shown`; every person's own analysis.json is capped by low_match.
"""

from __future__ import annotations

import json
from typing import Any

from part7 import challenges, group, jobs
from support import Api

ENTRY = "dance-real-people"
LOW_MATCH = {"capped_by": ["low_match"], "uncapped": {"value": 72, "grade": "C"}}
CREDIT = {"version": "simon.credit.v1", "percent": 61.0, "grade": "D", "points": 9000, "max_points": 14754, "tolerance": "normal"}


def _person(pid: str, value: int, capped: bool = True) -> dict[str, Any]:
    score = {"value": value, "grade": "F", "credit": CREDIT, **(LOW_MATCH if capped else {})}
    return {"status": {"code": "ok"}, "score": score, "warnings": [{"code": "low_match", "text": "Low match."}] if capped else []}


def _old_group_job(api: Api, people: dict[str, dict[str, Any]]) -> str:
    """A finished group job stored the way the two staging jobs were: people without `shown`."""
    def fn(ctx: jobs.JobContext) -> dict[str, Any]:
        rows = []
        for pid, doc in people.items():
            folder = group.person_dir(ctx.dir, pid)
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "analysis.json").write_text(json.dumps(doc), encoding="utf-8")
            rows.append({"id": pid, "label": "", "status_code": "ok", "score": doc["score"]["value"], "grade": "F", "faults": 0,
                         "analysis": f"api/results/{ctx.id}/{pid}/analysis.json", "replay": None})
        return {"result": {"entry_id": ENTRY, "trainer_id": 9, "people": rows}}

    rec = api.app.queue.submit("group", fn, entry_id=ENTRY, _people_owner="")  # made signed out (prod-data.md P-N1)
    assert api.app.queue.wait(rec["id"], 10)["status"] == "done"
    stored = api.app.queue.get(rec["id"])["result"]["people"]
    assert all("shown" not in p for p in stored)   # the fixture is shaped like the staging jobs
    return rec["id"]


def test_every_person_of_an_old_group_job_carries_shown_at_read_time(api: Api) -> None:
    job = _old_group_job(api, {"1": _person("1", 59), "4": _person("4", 59), "0": _person("0", 53), "2": _person("2", 0)})
    status, doc = api.json("GET", f"api/jobs/{job}")   # signed out, as the QA check read it
    assert status == 200
    people = doc["result"]["people"]
    assert [p["id"] for p in people] == ["1", "4", "0", "2"]   # the stored order is kept
    for p in people:
        assert p["shown"]["capped"] is False and p["shown"]["warning"] == ["low_match"], p   # nothing capped (team, 2 Nov)
        assert p["shown"]["unit"] == "points" and p["shown"]["letter"] in "SABCDEF"   # nothing capped: the credit, not the capped score
    assert people[0]["shown"]["figures"] == "9,000"   # the person's credit points, not the capped 59


def test_an_uncapped_person_reads_its_credit_and_a_person_without_an_analysis_has_none(api: Api) -> None:
    job = _old_group_job(api, {"1": _person("1", 59), "2": _person("2", 40, capped=False)})
    (group.person_dir(api.app.queue.job_dir(job), "1") / "analysis.json").unlink()
    people = api.json("GET", f"api/jobs/{job}")[1]["result"]["people"]
    assert people[0].get("shown") is None   # no analysis to read: nothing invented
    assert (people[1]["shown"]["letter"], people[1]["shown"]["figures"]) == ("D", "9,000")


def test_the_stored_job_record_is_not_rewritten(api: Api) -> None:
    job = _old_group_job(api, {"1": _person("1", 59)})
    api.json("GET", f"api/jobs/{job}")
    assert "shown" not in api.app.queue.get(job)["result"]["people"][0]   # read time only


def test_a_capped_group_is_never_featured() -> None:
    capped = {"letter": "F", "figures": "59", "caption": "score out of 100", "unit": "score", "capped": True, "warning": ["low_match"], "measure": 59}
    crew = [{"name": f"P{i}", "score": 59, "grade": "F", "created_at": f"2026-11-02T10:00:0{i}Z", "shown": capped} for i in range(3)]
    doc = {"id": "x", "entries": crew}
    assert challenges.summary(doc)["leader"] is None   # no headline for a board where every take was capped
    assert len(challenges.view(doc)["entries"]) == 3   # still listed, by their capped scores
