"""The models card of one person of a group result (docs/specs/group-results.md R2)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from part7 import jobs, models_used_person as mup
from support import Api

SAM3D = [{"name": "sam-3d-body-dinov3", "source": "hf"}, {"name": "mhr", "source": "hf"}]
PEOPLE = "cccccccccc01"


def write(path: Path, doc: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc), encoding="utf-8")


def person(d: Path, pid: str, lines: int) -> None:
    faults = [{"backend": "muse-spark"}] * lines
    write(d / "work" / "person" / pid / "analysis.json",
          {"phrasing": {"requested": "live", "backend": "muse-spark", "model": "m-" + pid, "faults": faults},
           "second_opinion": {"status": "ok", "model": "op-" + pid, "verdicts": [1] * lines, "observations": []}})


def group_job(root: Path, jid: str = "dddddddddd01") -> Path:
    d = root / jid
    write(d / "job.json", {"id": jid, "kind": "group", "status": "done", "people_job": PEOPLE,
                           "started_at": "2026-11-02T10:00:00Z", "finished_at": "2026-11-02T10:03:00Z",
                           "result": {"people": [{"id": "p1", "analysis": "x"}, {"id": "p2", "analysis": "x"},
                                                 {"id": "p3", "analysis": None}]}})
    write(d / "work" / "part2" / "pose3d.json", {"frames": [{"people": [{"id": "p1"}, {"id": "p2"}]}],
                                                 "provenance": {"backend": "gpu", "models": SAM3D}})
    write(d / "steps" / "part7.log", "x INFO job dddddddddd01: part 2 exit 0 in 70.0 s (part2.log)\n")
    write(root / PEOPLE / "work" / "tracks.json", {"provenance": {"tracker": "api-sam31"}})
    person(d, "p1", 4)
    person(d, "p2", 7)
    return d


def rows(doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {r["id"]: r for r in doc["models"]}


def test_a_group_person_gets_the_meta_models_that_ran_for_them(tmp_path: Path) -> None:
    group_job(tmp_path)
    doc = mup.collect(tmp_path, "dddddddddd01", "p1")
    assert doc is not None and doc["person"] == "p1"
    r = rows(doc)
    assert (r["sam31-you"]["status"], r["sam31-you"]["facts"]["via"]) == ("live", "meta_api")
    assert (r["sam3d-you"]["status"], r["sam3d-you"]["seconds"]) == ("live", 70.0)
    assert r["mhr-you"]["status"] == "live"
    assert (r["spark-phrasing"]["status"], r["spark-phrasing"]["facts"]["lines"]) == ("live", 4)
    assert r["spark-opinion"]["facts"]["verdicts"] == 4
    assert all(m["maker"] == "Meta" for m in doc["models"])


def test_a_persons_card_shows_nothing_of_anyone_else(tmp_path: Path) -> None:
    group_job(tmp_path)
    one, two = (mup.collect(tmp_path, "dddddddddd01", p) for p in ("p1", "p2"))
    assert one is not None and two is not None
    text = json.dumps(one)
    for other in ("p2", "m-p2", "op-p2"):
        assert other not in text
    assert {m["clip"] for m in one["models"]} == {"you"}  # no trainer rows, no account rows
    assert [m["id"] for m in one["models"]] == [m["id"] for m in two["models"]]
    assert two["models"][-1]["facts"]["verdicts"] == 7 and one["models"][-1]["facts"]["verdicts"] == 4
    assert "frames" not in json.dumps([m["facts"] for m in one["models"]])  # the clip's frames cover everyone


def test_only_analysed_people_of_done_group_jobs(tmp_path: Path) -> None:
    d = group_job(tmp_path)
    assert mup.collect(tmp_path, "dddddddddd01", "p3") is None      # no analysis: failed row
    assert mup.collect(tmp_path, "dddddddddd01", "zz") is None       # not in the group
    assert mup.collect(tmp_path, "ffffffffffff", "p1") is None
    write(d / "job.json", {"kind": "follow", "status": "done", "result": {"people": [{"id": "p1", "analysis": "x"}]}})
    assert mup.collect(tmp_path, "dddddddddd01", "p1") is None


def test_fallback_pose_is_labelled(tmp_path: Path) -> None:
    d = group_job(tmp_path)
    write(d / "work" / "part2" / "pose3d.json", {"provenance": {"backend": "cpu", "models": []}})
    r = rows(mup.collect(tmp_path, "dddddddddd01", "p1") or {})
    assert (r["sam3d-you"]["status"], r["mhr-you"]["status"]) == ("fallback", "not_run")


def test_wording_rows_carry_no_seconds_even_with_a_job_wide_part5_log(tmp_path: Path) -> None:
    # Part 5 logs every person's run as part5_analyse.log, so the last one wins in steps/part7.log: no per-person time
    d = group_job(tmp_path)
    write(d / "work" / "person" / "p1" / "analysis.json",
          {"phrasing": {"requested": "local-llm", "backend": "local-llm", "faults": [{"backend": "local-llm", "model": "muse-glimmer-1"}]},
           "second_opinion": {"status": "ok", "verdicts": []}})
    (d / "steps" / "part7.log").write_text("x INFO job dddddddddd01: part 2 exit 0 in 70.0 s (part2.log)\n"
                                           "x INFO job dddddddddd01: part 5 exit 0 in 11.0 s (part5_analyse.log)\n"
                                           "x INFO job dddddddddd01: part 5 exit 0 in 99.0 s (part5_analyse.log)\n", encoding="utf-8")
    one, two = (rows(mup.collect(tmp_path, "dddddddddd01", p) or {}) for p in ("p1", "p2"))
    for r in (one, two):
        assert r["spark-phrasing"]["seconds"] is None and r["glimmer-phrasing"]["seconds"] is None
    assert one["glimmer-phrasing"]["status"] == "live" and two["spark-phrasing"]["status"] == "live"
    assert one["sam3d-you"]["seconds"] == 70.0   # the group's one Part 2 run keeps its time


def test_unknown_and_missing_record_states(tmp_path: Path) -> None:
    d = group_job(tmp_path)
    (d / "work" / "part2" / "pose3d.json").unlink()
    (tmp_path / PEOPLE / "work" / "tracks.json").unlink()
    r = rows(mup.collect(tmp_path, "dddddddddd01", "p1") or {})
    assert (r["sam3d-you"]["status"], r["sam3d-you"]["facts"]["reason"]) == ("unknown", "no_pose_file")
    assert (r["mhr-you"]["status"], r["mhr-you"]["facts"]["reason"]) == ("unknown", "no_pose_file")
    assert (r["sam31-you"]["status"], r["sam31-you"]["facts"]["reason"]) == ("unknown", "no_tracks")
    write(d / "work" / "part2" / "pose3d.json", {"provenance": {"models": [SAM3D[0]]}})   # SAM 3D Body without the rig
    assert rows(mup.collect(tmp_path, "dddddddddd01", "p1") or {})["mhr-you"]["facts"]["reason"] == "no_rig_record"


def test_tracking_row_branches(tmp_path: Path) -> None:
    d = group_job(tmp_path)
    record = json.loads((d / "job.json").read_text())

    def tracking() -> dict[str, Any]:
        return rows(mup.collect(tmp_path, "dddddddddd01", "p1") or {})["sam31-you"]

    write(tmp_path / PEOPLE / "work" / "tracks.json", {"provenance": {"tracker": "local-sam31"}})
    assert (tracking()["status"], tracking()["facts"]["via"]) == ("live", "local_weights")
    write(tmp_path / PEOPLE / "work" / "tracks.json", {"provenance": {"tracker": "yolo", "fallback_reason": "no key"}})
    assert (tracking()["status"], tracking()["facts"]["ran"]) == ("fallback", "yolo")
    write(tmp_path / PEOPLE / "work" / "steps" / "part2_track.api.log", "x")   # the API call ran and failed
    write(tmp_path / PEOPLE / "work" / "tracks.json", {"provenance": {"tracker": "yolo"}})
    assert tracking()["facts"]["reason"] == "api_attempt_failed"
    write(d / "job.json", {**record, "people_job": "../x"})
    assert tracking()["facts"]["reason"] == "no_tracks"
    write(d / "job.json", {k: v for k, v in record.items() if k != "people_job"})
    assert tracking()["facts"]["reason"] == "no_tracks"


def test_route_404s(api: Api) -> None:
    def make(kind: str, ok: bool, people: list[dict[str, Any]]) -> str:
        def fn(ctx: jobs.JobContext) -> dict[str, Any]:
            if not ok:
                raise jobs.JobFailed("followers", "no")
            return {"result": {"people": people}}

        jid = api.app.queue.submit(kind, fn, people_job=PEOPLE)["id"]
        api.app.queue.wait(jid, 10)
        return jid

    follow = make("follow", True, [{"id": "p1", "analysis": "x"}])
    failed = make("group", False, [])
    noana = make("group", True, [{"id": "p1", "analysis": None}])
    assert api.json("GET", f"api/results/{follow}/p1/models.json")[0] == 404      # not a group job
    assert api.json("GET", f"api/results/{failed}/p1/models.json")[0] == 404      # a failed job
    assert api.json("GET", "api/results/NOTANID/p1/models.json")[0] == 404        # a bad job id
    assert api.json("GET", f"api/results/{noana}/p1/models.json")[0] == 404       # a person with no analysis


def test_route_answers_per_person_and_404s_others(api: Api) -> None:
    def fn(ctx: jobs.JobContext) -> dict[str, Any]:
        for p in ("p1", "p2"):
            person(ctx.dir, p, 3)
        write(ctx.dir / "work" / "part2" / "pose3d.json", {"provenance": {"models": SAM3D}})
        return {"result": {"people": [{"id": "p1", "analysis": "x"}, {"id": "p2", "analysis": "x"}]}}

    rec = api.app.queue.submit("group", fn, people_job=PEOPLE)
    jid = rec["id"]
    assert api.app.queue.wait(jid, 10)["status"] == "done"
    status, doc = api.json("GET", f"api/results/{jid}/p1/models.json")
    assert status == 200 and doc["person"] == "p1" and rows(doc)["sam3d-you"]["status"] == "live"
    assert api.json("GET", f"api/results/{jid}/p9/models.json")[0] == 404
    assert api.json("GET", f"api/results/{jid}/..%2Fx/models.json")[0] == 404
    assert api.json("GET", f"api/results/{jid}/p1/other.json")[0] == 404
