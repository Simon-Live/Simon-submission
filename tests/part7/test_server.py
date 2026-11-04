"""Server routes, uploads, jobs, quota, proxy and static files (app.md "Server", AC-A1 to AC-A12)."""

from __future__ import annotations

import json
from pathlib import Path
import threading
from typing import Any

import pytest

from part7 import chain, config, jobs, quota, server
from support import VIDEO_BYTES, Api, ffmpeg_video

OK_ANALYSIS = {"format": "simon.analysis.v1", "status": {"code": "ok"}, "faults": [{"at_s": 1.0}],
               "score": {"value": 72, "grade": "C"}}


def _fake_trainer(entry_id: str = "squat", ok: bool = True, stage: str = "animation") -> Any:
    def run(video: Path, work: Path, report: Any = None, **kw: Any) -> dict[str, Any]:
        for name in ("keyframes", "pose", "skeleton", "animation", "catalog"):
            report(name)
            if not ok and name == stage:
                return {"ok": False, "stage": stage, "error": f"failed:{stage}: the animation step failed"}
        assert Path(video).is_file() and kw["name"] and kw["catalog"]
        return {"ok": True, "entry_id": entry_id, "parts": {"keyframes": 1, "skeleton": 3, "animation": 4}, "note": None}

    return run


def _fake_follower(with_replay: bool = True) -> Any:
    def run(video: Path, expected: Path, work: Path, report: Any = None, **kw: Any) -> dict[str, Any]:
        for name in ("pose", "skeleton", "analyse"):
            report(name)
        work.mkdir(parents=True, exist_ok=True)
        (work / "analysis.json").write_text(json.dumps(OK_ANALYSIS), encoding="utf-8")
        files = {"analysis": str(work / "analysis.json")}
        if with_replay:
            fixture = config.REPO_ROOT / "fixtures" / "input" / "replay.json"
            (work / "replay.json").write_bytes(fixture.read_bytes())
            files["replay"] = str(work / "replay.json")
        return {"ok": True, "files": files, "note": "template used"}

    return run


def _upload(api: Api, mp4: Path) -> str:
    status, doc = api.upload(mp4)
    assert status == 201, doc
    return doc["upload_id"]


def test_upload_limits_are_the_spec_values() -> None:
    assert config.MAX_UPLOAD_BYTES == 95_000_000 and config.MAX_UPLOAD_SECONDS == 90


def test_outside_base_path_is_404(api: Api) -> None:
    assert api.request("GET", "api/health", base="/")[0] == 404
    assert api.request("GET", "", base="/simon-part-7")[0] == 404


def test_health_and_config(api: Api) -> None:
    status, _, data = api.request("GET", "api/health")
    doc = json.loads(data)
    assert status == 200 and doc["ok"] and doc["part6"] == {"ok": True, "entries": 3}
    assert set(doc["pins"]) == set("123456") and doc["queue"] == {"running": 0, "waiting": 0}
    assert doc["gpu_jobs_today"] == 0
    cfg = json.loads(api.request("GET", "api/config")[2])
    assert cfg["base"] == "/simon-part-7/" and cfg["limits"] == {
        "max_seconds": 90, "max_clip_seconds": 60, "min_clip_seconds": 1, "max_bytes": 95000000,
        "recorder_bps": 2500000}
    assert cfg["phrasing"] == "template" and cfg["fixture_result"] is True


def test_config_reports_what_the_pinned_part5_offers(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server.p5_analyse, "_KNOWN", None)
    monkeypatch.setattr(server.p5_analyse, "capabilities",
                        lambda lock=None: {"lang": False, "video": True, "private": False})
    cfg = json.loads(api.request("GET", "api/config")[2])
    assert cfg["part5"] == {"lang": False, "video": False, "private": False}, "false until the warm-up has finished"
    server.p5_analyse.warm(api.app.lock).join(5)
    cfg = json.loads(api.request("GET", "api/config")[2])
    assert cfg["part5"] == {"lang": False, "video": True, "private": False}


def test_config_never_waits_on_the_part5_probes(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    import threading

    release = threading.Event()
    monkeypatch.setattr(server.p5_analyse, "_KNOWN", None)
    monkeypatch.setattr(server.p5_analyse, "capabilities",
                        lambda lock=None: release.wait(10) and {"lang": True, "video": True, "private": True})
    thread = server.p5_analyse.warm(api.app.lock)
    try:
        assert api.request("GET", "api/config")[0] == 200  # answers while the probes are still running
    finally:
        release.set()
        thread.join(5)


def test_health_503_when_part6_is_down(api: Api) -> None:
    api.app.child.up = False
    status, _, data = api.request("GET", "api/health")
    assert status == 503 and json.loads(data)["part6"]["ok"] is False


def test_fixture_result_serves_part5_schema_1_2_0(api: Api) -> None:
    status, doc = api.json("GET", "api/fixture-result")
    assert status == 200
    assert doc["analysis"]["score"]["grade"] in "ABCDF" and doc["replay"]["format"] == "simon.replay.v1"
    fault = doc["analysis"]["faults"][0]
    assert {"follower_t_s", "at_s", "follower_runs", "lateral", "text_timed"} <= set(fault)


def test_upload_ok_returns_metadata_and_stores_the_file(api: Api, tiny_mp4: Path) -> None:
    status, doc = api.upload(tiny_mp4, "video/mp4;codecs=avc1")
    assert status == 201 and doc["width"] == 160 and doc["height"] == 120 and 1900 <= doc["duration_ms"] <= 2100
    assert api.app.upload_file(doc["upload_id"]).is_file()


def test_upload_webm_is_accepted(api: Api, tmp_path: Path) -> None:
    webm = ffmpeg_video(tmp_path / "t.webm", 1, "libvpx")
    assert api.upload(webm, "video/webm")[0] == 201


def test_upload_not_a_video_is_400_and_nothing_is_kept(api: Api, tmp_path: Path) -> None:
    junk = tmp_path / "junk.mp4"
    junk.write_bytes(b"not a video" * 100)
    status, doc = api.upload(junk)
    assert status == 400 and doc["error"] == server.MSG_NOT_VIDEO
    assert api.upload(junk, "text/plain")[0] == 400
    assert list(api.app.uploads.iterdir()) == []


def test_upload_over_byte_cap_is_413(api: Api, tiny_mp4: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "MAX_UPLOAD_BYTES", tiny_mp4.stat().st_size - 1)
    status, doc = api.upload(tiny_mp4)
    assert status == 413 and doc["error"] == server.MSG_TOO_LARGE and list(api.app.uploads.iterdir()) == []


def test_upload_over_90_seconds_is_413_and_nothing_queued(api: Api, tmp_path: Path) -> None:
    status, doc = api.upload(ffmpeg_video(tmp_path / "over.mp4", 91))
    assert status == 413 and doc["error"] == server.MSG_TOO_LONG_RAW
    assert list(api.app.uploads.iterdir()) == [] and api.app.queue.counts() == {"running": 0, "waiting": 0}


def test_trainer_job_runs_stages_and_returns_the_entry(api: Api, tiny_mp4: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chain, "trainer", _fake_trainer())
    upload_id = _upload(api, tiny_mp4)
    status, doc = api.json("POST", "api/trainer", {"upload_id": upload_id, "name": " Squat ", "category": "exercise"})
    assert status == 202 and doc["job"] == doc["id"] and doc["kind"] == "trainer"
    done = api.app.queue.wait(doc["job"], 60)
    assert done["status"] == "done" and done["entry_id"] == "squat"
    assert done["stages"] == ["upload", "keyframes", "pose", "skeleton", "animation", "catalog"]
    assert api.json("GET", f"api/jobs/{doc['job']}")[1]["result"]["parts"]["keyframes"] == 1
    assert api.app.quota.gpu_jobs_today() == 1


def test_trainer_validation_errors(api: Api, tiny_mp4: Path) -> None:
    upload_id = _upload(api, tiny_mp4)
    assert api.json("POST", "api/trainer", {"upload_id": upload_id, "name": "", "category": "exercise"})[0] == 400
    assert api.json("POST", "api/trainer", {"upload_id": upload_id, "name": "x" * 81, "category": "exercise"})[0] == 400
    assert api.json("POST", "api/trainer", {"upload_id": upload_id, "name": "A", "category": "yoga"})[1]["error"] == server.MSG_CATEGORY
    assert api.json("POST", "api/trainer", {"upload_id": "../../etc", "name": "A", "category": "dance"})[0] == 400
    assert api.app.queue.counts() == {"running": 0, "waiting": 0} and api.app.quota.gpu_jobs_today() == 0


def test_failed_job_reports_stage_and_a_clean_reason(api: Api, tiny_mp4: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chain, "trainer", _fake_trainer(ok=False))
    upload_id = _upload(api, tiny_mp4)
    job = api.json("POST", "api/trainer", {"upload_id": upload_id, "name": "A", "category": "dance"})[1]["job"]
    done = api.app.queue.wait(job, 60)
    assert done["status"] == "failed" and done["stage"] == "animation"
    assert done["error"] == "failed:animation: the animation step failed"


def test_follow_unknown_entry_is_404_and_no_animation_is_409(api: Api, tiny_mp4: Path) -> None:
    upload_id = _upload(api, tiny_mp4)
    assert api.json("POST", "api/follow", {"upload_id": upload_id, "entry_id": "nope"})[0] == 404
    status, doc = api.json("POST", "api/follow", {"upload_id": upload_id, "entry_id": "empty"})
    assert status == 409 and doc["error"] == server.MSG_NO_ANIMATION
    assert api.app.queue.counts() == {"running": 0, "waiting": 0}


def test_follow_job_serves_analysis_and_validated_replay(api: Api, tiny_mp4: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chain, "follower", _fake_follower())
    upload_id = _upload(api, tiny_mp4)
    status, doc = api.json("POST", "api/follow", {"upload_id": upload_id, "entry_id": "lateral-raise"})
    assert status == 202 and doc["entry_id"] == "lateral-raise"
    done = api.app.queue.wait(doc["job"], 60)
    assert done["status"] == "done" and done["result"]["score"] == 72 and done["result"]["grade"] == "C"
    assert done["stages"] == ["upload", "pose", "skeleton", "analyse"] and done["note"] == "template used"
    status, _, body = api.request("GET", f"api/results/{doc['job']}/analysis.json")
    assert status == 200 and json.loads(body) == OK_ANALYSIS
    status, _, body = api.request("GET", f"api/results/{doc['job']}/replay.json")
    assert status == 200 and json.loads(body)["format"] == "simon.replay.v1"


@pytest.mark.parts("5")
def test_served_replay_carries_the_followers_unseen_joints_from_part2(api: Api, tiny_mp4: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chain, "follower", _fake_follower())  # TICKET-376
    job = api.json("POST", "api/follow", {"upload_id": _upload(api, tiny_mp4), "entry_id": "lateral-raise"})[1]["job"]
    api.app.queue.wait(job, 60)
    follower = api.app.queue.job_dir(job) / "work" / "follower"
    doc = json.loads((follower / "replay.json").read_text())
    names, times = doc["joints"], doc["follower_t"]
    (follower / "part2").mkdir()
    pose = {"frames": [{"frame": i, "t_ms": t * 1000.0, "people": [{"id": 0, "joints": {
        n: {"x": 0.0, "y": 0.0, "z": 0.0, "conf": 0.3 if n.endswith("_ankle") else 1.0} for n in names}}]}
        for i, t in enumerate(times)]}
    (follower / "part2" / "pose3d.json").write_text(json.dumps(pose))
    status, _, body = api.request("GET", f"api/results/{job}/replay.json")
    served = json.loads(body)
    ankles = sorted(i for i, n in enumerate(names) if n.endswith("_ankle"))
    assert status == 200 and served["follower_unseen"] == [ankles] * len(times)


def test_replay_that_fails_its_contract_is_422(api: Api, tiny_mp4: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chain, "follower", _fake_follower())
    job = api.json("POST", "api/follow", {"upload_id": _upload(api, tiny_mp4), "entry_id": "lateral-raise"})[1]["job"]
    api.app.queue.wait(job, 60)
    path = api.app.queue.job_dir(job) / "work" / "follower" / "replay.json"
    broken = json.loads(path.read_text())
    del broken["exp_to_fol"]
    path.write_text(json.dumps(broken))
    status, _, body = api.request("GET", f"api/results/{job}/replay.json")
    assert status == 422 and "exp_to_fol" in json.dumps(json.loads(body)["problems"])
    assert api.request("GET", "api/results/zzzz/replay.json")[0] == 404
    assert api.request("GET", f"api/results/{job}/other.json")[0] == 404


def test_visitor_quota_gives_429_and_queues_nothing(api: Api, tiny_mp4: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chain, "trainer", _fake_trainer())
    upload_id = _upload(api, tiny_mp4)
    hdr = {"Cf-Connecting-Ip": "203.0.113.9"}
    body = {"upload_id": upload_id, "name": "A", "category": "dance"}
    for _ in range(config.VISITOR_TRAINER_PER_DAY):
        status, doc = api.json("POST", "api/trainer", body, hdr)
        assert status == 202
        api.app.queue.wait(doc["job"], 60)
    status, doc = api.json("POST", "api/trainer", body, hdr)
    assert status == 429 and doc["error"] == quota.VISITOR_MESSAGE
    assert api.json("POST", "api/trainer", body, {"Cf-Connecting-Ip": "203.0.113.10"})[0] == 202
    assert api.json("POST", "api/trainer", body)[0] == 202  # no header, no visitor quota


def test_daily_cap_gives_503_with_its_message(api: Api, tiny_mp4: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chain, "trainer", _fake_trainer())
    api.app.quota.daily_gpu = 0
    status, doc = api.json("POST", "api/trainer", {"upload_id": _upload(api, tiny_mp4), "name": "A", "category": "dance"})
    assert status == 503 and doc["error"] == quota.DAILY_MESSAGE


def test_queue_full_is_503_and_returns_the_quota(api: Api, tiny_mp4: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    gate = threading.Event()

    def blocked(video: Path, work: Path, report: Any = None, **kw: Any) -> dict[str, Any]:
        gate.wait(30)
        return {"ok": True, "entry_id": "x", "parts": {}}

    monkeypatch.setattr(chain, "trainer", blocked)
    api.app.queue.limit = 2
    upload_id = _upload(api, tiny_mp4)
    body = {"upload_id": upload_id, "name": "A", "category": "dance"}
    ids = [api.json("POST", "api/trainer", body)[1]["job"] for _ in range(2)]
    status, doc = api.json("POST", "api/trainer", body)
    assert status == 503 and doc["error"] == jobs.QUEUE_FULL_MESSAGE and api.app.quota.gpu_jobs_today() == 2
    assert api.json("GET", f"api/jobs/{ids[1]}")[1]["status"] in ("queued", "running")  # two workers: both may run
    gate.set()
    assert api.app.queue.wait(ids[1], 60)["status"] == "done"


def test_unknown_job_is_404(api: Api) -> None:
    assert api.request("GET", "api/jobs/0123456789ab")[0] == 404
    assert api.request("GET", "api/jobs/../../etc")[0] == 404


def test_catalog_proxy_passes_range_206_headers_and_posts(api: Api) -> None:
    status, headers, body = api.request("GET", "catalog/video.mp4", headers={"Range": "bytes=100-199"})
    assert status == 206 and body == VIDEO_BYTES[100:200]
    assert headers["content-range"] == f"bytes 100-199/{len(VIDEO_BYTES)}"
    status, headers, body = api.request("GET", "catalog/api/entries?q=x", headers={"X-Custom": "yes"})
    assert status == 200 and json.loads(body)["path"] == "/simon-part-7/catalog/api/entries?q=x" and headers["x-seen-custom"] == "yes"
    assert headers["x-seen-host"] == f"127.0.0.1:{api.app.child.port}"
    status, _, body = api.request("POST", "catalog/api/import", b"payload", {"Content-Type": "application/json"})
    assert status == 201 and body == b"payload"


def test_catalog_proxy_503_when_the_child_is_gone(api: Api) -> None:
    api.app.child.close()
    assert api.request("GET", "catalog/api/entries")[0] == 503


def test_static_files_and_traversal(api: Api) -> None:
    assert api.request("GET", "")[2] == b"<h1>Simon</h1>"
    status, headers, _ = api.request("GET", "app.js")
    assert status == 200 and headers["content-type"].startswith("text/javascript")
    assert api.request("GET", "../secret.txt")[0] == 404
    assert api.request("GET", "%2e%2e/secret.txt")[0] == 404
    assert api.request("GET", "missing.css")[0] == 404
