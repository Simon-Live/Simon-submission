"""Meta models of a job and the 2D skeleton (docs/specs/models-and-skeleton-data.md R1, R2; AC-D1, AC-D2)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from part7 import jobs, models_used, skeleton2d
from support import Api

SAM3D = [{"name": "sam-3d-body-dinov3", "source": "hf"}, {"name": "mhr", "source": "hf"}]
ENTRY = "lateral-raise-0f13199f"


def write(path: Path, doc: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(doc if isinstance(doc, str) else json.dumps(doc), encoding="utf-8")


def job(root: Path, jid: str, kind: str = "follow", status: str = "done", **extra: Any) -> Path:
    d = root / jid
    write(d / "job.json", {"id": jid, "kind": kind, "status": status, "entry_id": ENTRY,
                           "started_at": "2026-10-31T04:42:57Z", "finished_at": "2026-10-31T04:45:44Z", **extra})
    return d


def trainer(root: Path, part1_log: str, spark: str | None = "spark", keyframes_part: int = 1,
            part7_log: str = "") -> Path:
    d = job(root, "aaaaaaaaaaa1", kind="trainer", result={"entry_id": ENTRY, "parts": {"keyframes": keyframes_part}})
    if part1_log:
        write(d / "work" / "trainer" / "steps" / "part1.log", part1_log)
    if spark:
        write(d / "work" / "trainer" / "keyframes.json",
              {"spark_names": spark, "people": [{"repetitions": [{}, {}, {}]}]})
    if part7_log:
        write(d / "steps" / "part7.log", part7_log)
    return d


def follower(d: Path, tracker: str | None = None, models: list[dict[str, Any]] = SAM3D,
             phrasing: dict[str, Any] | None = None, **prov: Any) -> None:
    work = d / "work" / "follower"
    write(work / "part2" / "pose3d.json",
          {"frames": [{"frame": 0, "t_ms": 0, "people": []}],
           "provenance": {"backend": "gpu", "tracker": tracker, "models": models, **prov}})
    write(work / "analysis.json", {"phrasing": phrasing or {"requested": "template", "backend": "template", "faults": []}})


def rows(doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {r["id"]: r for r in doc["models"]}


LIVE_PART1 = "p7-x.mp4: 10.3s at 25.0 fps, SAM about $0.03\n  SAM frames 200\n  spark sections 1: lateral_raise\n"


SHORT_PART1 = ("p7-x.mp4: 12.0s at 25.0 fps, analysis 15.0 fps, 180 frames, SAM about $0.04\n  transcoding\n  uploading\n"
               "  spark sections 1: high_knees\n  wrote out/p7-x/keyframes.json (1 people, 5 repetitions, names from spark)\n")


def test_short_clip_without_a_sam_frames_line_is_live_from_part1s_own_record(tmp_path: Path) -> None:
    # 180 analysis frames: Part 1 logs "SAM frames N" every 200, so the log has none; the cost line and the tracked
    # person in keyframes.json are Part 1's record that the SAM 3.1 call ran.
    trainer(tmp_path, SHORT_PART1, part7_log="2026 INFO job aaaaaaaaaaa1: part 1 exit 0 in 61.1 s (part1.log)\n")
    d = job(tmp_path, "bbbbbbbbbbb1")
    follower(d)
    r = rows(models_used.collect(tmp_path, "bbbbbbbbbbb1"))
    assert (r["sam31-trainer"]["status"], r["sam31-trainer"]["seconds"], r["sam31-trainer"]["facts"]["frames"]) == \
        ("live", 61.1, 180)
    assert r["spark-sections"]["status"] == "live"


def test_short_clip_with_no_tracked_person_stays_unknown(tmp_path: Path) -> None:
    d = trainer(tmp_path, SHORT_PART1)
    write(d / "work" / "trainer" / "keyframes.json", {"spark_names": "spark", "people": []})
    follower(job(tmp_path, "bbbbbbbbbbb1"))
    assert rows(models_used.collect(tmp_path, "bbbbbbbbbbb1"))["sam31-trainer"]["status"] == "unknown"


def test_no_cost_line_and_no_frames_line_stays_unknown(tmp_path: Path) -> None:
    trainer(tmp_path, "p7-x.mp4: quality check\n  spark sections 1: high_knees\n")
    follower(job(tmp_path, "bbbbbbbbbbb1"))
    assert rows(models_used.collect(tmp_path, "bbbbbbbbbbb1"))["sam31-trainer"]["status"] == "unknown"


def test_live_run_names_every_model_with_times(tmp_path: Path) -> None:
    trainer(tmp_path, LIVE_PART1, part7_log="2026 INFO job aaaaaaaaaaa1: part 1 exit 0 in 41.2 s (part1.log)\n")
    d = job(tmp_path, "bbbbbbbbbbb1")
    phr = {"requested": "live", "backend": "muse-spark", "model": "meta-models/muse-spark-open-1026",
           "faults": [{"backend": "muse-spark"}, {"backend": "muse-spark"}]}
    follower(d, phrasing=phr)
    write(d / "steps" / "part7.log", "x INFO job bbbbbbbbbbb1: part 2 exit 0 in 85.5 s (part2.log)\n"
                                     "x INFO job bbbbbbbbbbb1: part 5 exit 0 in 9.0 s (part5_analyse.log)\n")
    doc = models_used.collect(tmp_path, "bbbbbbbbbbb1")
    assert doc is not None and doc["job_seconds"] == 167.0
    r = rows(doc)
    assert [m["id"] for m in doc["models"]] == ["sam31-trainer", "spark-sections", "sam31-you", "sam3d-you",
                                                 "spark-phrasing"]
    assert (r["sam31-trainer"]["status"], r["sam31-trainer"]["seconds"], r["sam31-trainer"]["facts"]["frames"]) == \
        ("live", 41.2, 200)
    assert (r["spark-sections"]["status"], r["spark-sections"]["facts"]["repetitions"]) == ("live", 3)
    assert (r["sam31-you"]["status"], r["sam31-you"]["facts"]["reason"]) == ("not_run", "one_person")
    assert (r["sam3d-you"]["status"], r["sam3d-you"]["seconds"]) == ("live", 85.5)
    ph = r["spark-phrasing"]
    assert (ph["status"], ph["seconds"], ph["facts"]["lines_live"], ph["facts"]["lines"]) == ("live", 9.0, 2, 2)
    assert all(m["maker"] == "Meta" for m in doc["models"])


def test_cached_part1_is_cached_not_live(tmp_path: Path) -> None:
    trainer(tmp_path, "p7-x.mp4: rebuilt from saved SAM and Spark results, no API call\n")
    follower(job(tmp_path, "bbbbbbbbbbb1"))
    r = rows(models_used.collect(tmp_path, "bbbbbbbbbbb1"))
    assert r["sam31-trainer"]["status"] == "cached" and r["spark-sections"]["status"] == "cached"


def test_fallbacks_are_labelled_with_what_ran(tmp_path: Path) -> None:
    trainer(tmp_path, LIVE_PART1, spark="fallback")
    people = job(tmp_path, "ccccccccccc1", kind="people")
    write(people / "work" / "tracks.json",
          {"frames": [], "provenance": {"tracker": "local-open", "fallback_reason": "no_key"}})
    write(people / "work" / "steps" / "part2_track.api.log", "refused\n")
    write(people / "steps" / "part7.log", "x INFO job ccccccccccc1: part 2 exit 0 in 30.0 s (part2_track_retry.log)\n")
    d = job(tmp_path, "bbbbbbbbbbb1", people_job="ccccccccccc1", person_id="1")
    follower(d, tracker="local-open", models=[{"name": "motionbert"}], lifter="motionbert",
             phrasing={"requested": "live", "backend": "template", "fallback_reason": "live phrasing timed out",
                       "faults": [{"backend": "template", "fallback_reason": "live phrasing timed out"}]})
    r = rows(models_used.collect(tmp_path, "bbbbbbbbbbb1"))
    assert (r["spark-sections"]["status"], r["spark-sections"]["facts"]["ran"]) == ("fallback", "standard_phase_names")
    you = r["sam31-you"]
    assert (you["status"], you["facts"]["ran"], you["facts"]["reason"], you["seconds"]) == \
        ("fallback", "local-open", "no_key", 30.0)
    assert (r["sam3d-you"]["status"], r["sam3d-you"]["facts"]["ran"]) == ("fallback", "motionbert")
    assert (r["spark-phrasing"]["status"], r["spark-phrasing"]["facts"]["reason"]) == \
        ("fallback", "live phrasing timed out")


def test_people_job_with_api_tracker_is_live(tmp_path: Path) -> None:
    people = job(tmp_path, "ccccccccccc1", kind="people")
    write(people / "work" / "tracks.json", {"frames": [], "provenance": {"tracker": "api-sam31"}})
    write(people / "steps" / "part7.log", "x INFO job ccccccccccc1: part 2 exit 0 in 12.5 s (part2_track.api.log)\n")
    follower(job(tmp_path, "bbbbbbbbbbb1", people_job="ccccccccccc1"), tracker="api-sam31")
    you = rows(models_used.collect(tmp_path, "bbbbbbbbbbb1"))["sam31-you"]
    assert (you["status"], you["facts"]["via"], you["seconds"]) == ("live", "meta_api", 12.5)


def test_part3_keyframes_and_missing_records(tmp_path: Path) -> None:
    trainer(tmp_path, "", spark=None, keyframes_part=3)
    d = job(tmp_path, "bbbbbbbbbbb1")
    r = rows(models_used.collect(tmp_path, "bbbbbbbbbbb1"))
    assert r["sam31-trainer"]["status"] == "fallback" and r["sam31-trainer"]["facts"]["ran"] == "part3_keyframes"
    assert (r["sam3d-you"]["status"], r["sam31-you"]["status"], r["spark-phrasing"]["status"]) == \
        ("unknown", "unknown", "unknown")
    (tmp_path / "aaaaaaaaaaa1" / "job.json").unlink()  # no trainer job at all (sample entry, expired job)
    follower(d)
    r = rows(models_used.collect(tmp_path, "bbbbbbbbbbb1"))
    assert (r["sam31-trainer"]["status"], r["sam31-trainer"]["facts"]["reason"]) == ("unknown", "no_trainer_job")
    assert r["spark-phrasing"]["facts"]["reason"] == "template_chosen"


def test_only_done_follow_jobs(tmp_path: Path) -> None:
    trainer(tmp_path, LIVE_PART1)
    job(tmp_path, "bbbbbbbbbbb1", status="running")
    assert models_used.collect(tmp_path, "aaaaaaaaaaa1") is None
    assert models_used.collect(tmp_path, "bbbbbbbbbbb1") is None
    assert models_used.collect(tmp_path, "000000000000") is None


# ----- skeleton2d ----------------------------------------------------------------------------------------------
def pose_files(part2: Path, joint: dict[str, float], people_id: Any = 0) -> None:
    joints = {n: dict(joint) for n in skeleton2d.JOINTS}
    write(part2 / "pose3d.json", {"frames": [{"frame": 0, "t_ms": 500.0, "people": [{"id": people_id, "joints": joints}]}]})
    write(part2 / "camera.json", {"K": [[1000, 0, 640], [0, 1000, 360], [0, 0, 1]], "image_size": [1280, 720],
                                  "frames": [{"frame": 0, "people": [{"id": people_id, "R": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
                                                                      "t": [0.0, 0.0, 2.0]}]}]})


def test_skeleton_projects_through_camera(tmp_path: Path) -> None:
    pose_files(tmp_path, {"x": 0.2, "y": -0.1, "z": 0.0, "conf": 1.0})
    doc = skeleton2d.build(tmp_path)
    assert doc is not None and doc["image_size"] == [1280.0, 720.0] and len(doc["bones"]) == 18
    f = doc["frames"][0]
    # u = 1000 * 0.2 / 2 + 640 = 740 -> 740/1280; v = 1000 * -0.1 / 2 + 360 = 310 -> 310/720
    assert f["t"] == 0.5 and f["pts"][0] == [round(740 / 1280, 4), round(310 / 720, 4)]


def test_skeleton_drops_unseen_and_behind_and_bad_files(tmp_path: Path) -> None:
    pose_files(tmp_path, {"x": 0.0, "y": 0.0, "z": -3.0, "conf": 1.0})
    assert skeleton2d.build(tmp_path)["frames"][0]["pts"][0] is None
    pose_files(tmp_path, {"x": 0.0, "y": 0.0, "z": 0.0, "conf": 0.0})
    assert skeleton2d.build(tmp_path)["frames"][0]["pts"][0] is None
    (tmp_path / "camera.json").write_text("{", encoding="utf-8")
    assert skeleton2d.build(tmp_path) is None
    assert skeleton2d.build(tmp_path / "missing") is None


# ----- the routes ----------------------------------------------------------------------------------------------
def finished(api: Api, kind: str, fill: Callable[[Path], None]) -> str:
    def fn(ctx: jobs.JobContext) -> dict[str, Any]:
        fill(ctx.dir)
        return {"result": {}}

    rec = api.app.queue.submit(kind, fn, entry_id=ENTRY)
    assert api.app.queue.wait(rec["id"], 10)["status"] == "done"
    return rec["id"]


def test_routes_answer_done_follow_jobs_only(api: Api) -> None:
    def fill(d: Path) -> None:
        follower(d)
        pose_files(d / "work" / "follower" / "part2", {"x": 0.0, "y": 0.0, "z": 0.0, "conf": 1.0})

    jid = finished(api, "follow", fill)
    status, doc = api.json("GET", f"api/results/{jid}/models.json")
    assert status == 200 and rows(doc)["sam3d-you"]["status"] == "unknown"  # pose_files replaced the provenance
    assert rows(doc)["sam31-trainer"]["facts"]["reason"] == "no_trainer_job"
    status, sk = api.json("GET", f"api/results/{jid}/skeleton2d.json")
    assert status == 200 and sk["frames"][0]["pts"][0] == [0.5, 0.5]
    tid = finished(api, "trainer", lambda d: None)
    for path in (f"api/results/{tid}/models.json", f"api/results/{tid}/skeleton2d.json", "api/results/ffffffffffff/models.json",
                 "api/results/..%2Fx/models.json", "api/results/NOTANID/skeleton2d.json"):
        assert api.json("GET", path)[0] == 404, path
