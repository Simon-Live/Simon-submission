"""The measured stage split on a follow job's answer (docs/specs/judge-take.md, TICKET-260 AC-4)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from part7 import stage_split

LINE = ("2026-11-02 01:02:03 INFO job f67053ccd35b summary: kind=follow status=ok total=102.6s upload=0.5s "
        "pose=95.8s(gpu_wait=1.2s) analyse=6.3s part1=live mode=dance")


class Queue:
    def __init__(self, root: Path, jobs: dict[str, dict[str, Any]]) -> None:
        self.root, self.jobs = root, jobs

    def get(self, job_id: str) -> dict[str, Any] | None:
        return self.jobs.get(job_id)

    def job_dir(self, job_id: str) -> Path:
        return self.root / job_id


def _log(root: Path, job_id: str, text: str) -> None:
    steps = root / job_id / "steps"
    steps.mkdir(parents=True, exist_ok=True)
    (steps / "part7.log").write_text(text, encoding="utf-8")


def test_parse_summary_reads_stages_in_order_with_gpu_wait() -> None:
    got = stage_split.parse_summary(LINE + "\n", "f67053ccd35b")
    assert got == {"status": "ok", "total_s": 102.6, "stages": [
        {"name": "upload", "seconds": 0.5}, {"name": "pose", "seconds": 95.8, "gpu_wait_s": 1.2},
        {"name": "analyse", "seconds": 6.3}]}


def test_parse_summary_ignores_other_jobs_and_takes_the_last_line() -> None:
    assert stage_split.parse_summary(LINE, "aaaaaaaaaaaa") is None
    two = LINE + "\n" + LINE.replace("total=102.6s", "total=50.0s")
    assert stage_split.parse_summary(two, "f67053ccd35b")["total_s"] == 50.0


def test_split_names_the_skipped_picker_and_the_people_seconds(tmp_path: Path) -> None:
    _log(tmp_path, "f67053ccd35b", "stage pose start: -\n" + LINE + "\n")
    _log(tmp_path, "peoplejob001", "job peoplejob001 summary: kind=people status=ok total=9.4s tracking=8.0s\n")
    q = Queue(tmp_path, {"peoplejob001": {"kind": "people", "result": {"people": [{"id": "0"}], "auto_id": "0"}}})
    got = stage_split.split(q, "f67053ccd35b", {"people_job": "peoplejob001", "person_id": "0"})
    assert got["recorded"] is True and got["picker"] == "skipped" and got["people_s"] == 9.4
    assert [s["name"] for s in got["stages"]] == ["upload", "pose", "analyse"]


def test_split_says_shown_when_the_person_was_picked_by_hand(tmp_path: Path) -> None:
    _log(tmp_path, "f67053ccd35b", LINE)
    q = Queue(tmp_path, {"peoplejob001": {"result": {"people": [{"id": "0"}, {"id": "1"}], "auto_id": None}}})
    got = stage_split.split(q, "f67053ccd35b", {"people_job": "peoplejob001", "person_id": "1"})
    assert got["picker"] == "shown" and "people_s" not in got


def test_an_old_job_without_a_summary_is_not_recorded_never_zeros(tmp_path: Path) -> None:
    q = Queue(tmp_path, {})
    assert stage_split.split(q, "f67053ccd35b", {}) == {"recorded": False}
    _log(tmp_path, "f67053ccd35b", "stage pose start: -\nstage pose end in 3.0 s: exits 2:0\n")
    assert stage_split.split(q, "f67053ccd35b", {}) == {"recorded": False}
    _log(tmp_path, "f67053ccd35b", "job f67053ccd35b summary: kind=follow status=ok total=1.0s\n")
    assert stage_split.split(q, "f67053ccd35b", {}) == {"recorded": False}  # a total with no stage is no split


# ----- through the running app: GET api/jobs/<id> (part7/server.py) -----------------------------------------------
def test_a_done_follow_job_answers_its_timing_and_a_people_job_does_not(api: Any) -> None:
    from part7 import jobs

    def fn(ctx: jobs.JobContext) -> dict[str, Any]:
        ctx.set_stage("pose")
        ctx.set_stage("analyse")
        return {"result": {"entry_id": "lateral-raise"}}

    def bare(ctx: jobs.JobContext) -> dict[str, Any]:
        return {"result": {"entry_id": "lateral-raise"}}

    rec = api.app.queue.submit("follow", fn, entry_id="lateral-raise")
    assert api.app.queue.wait(rec["id"], 10)["status"] == "done"
    status, doc = api.json("GET", f"api/jobs/{rec['id']}")
    assert status == 200 and doc["timing"]["recorded"] is True  # the queue wrote the summary line itself
    assert [st["name"] for st in doc["timing"]["stages"]] == ["pose", "analyse"]
    old = api.app.queue.submit("follow", bare, entry_id="lateral-raise")  # no stage: nothing to split
    assert api.app.queue.wait(old["id"], 10)["status"] == "done"
    assert api.json("GET", f"api/jobs/{old['id']}")[1]["timing"] == {"recorded": False}
    people = api.app.queue.submit("people", fn, _people_owner="")  # made signed out (prod-data.md P-N1)
    assert api.app.queue.wait(people["id"], 10)["status"] == "done"
    status, doc = api.json("GET", f"api/jobs/{people['id']}")
    assert status == 200 and "timing" not in doc
