"""The run API over HTTP (docs/specs/run-app.md: AC-A04 to AC-A12), split from tests/test_server.py by topic. The
synthetic repo, the server runner, the request helpers and the per-test isolation are tests/server_helpers.py's;
jobs run the fake runner of tests/test_jobs.py."""
import json
import shutil
import subprocess
import time

import pytest
from test_jobs import FAKE_RUN, fake_command
from test_runapi import form, jpeg
from server_helpers import (  # noqa: F401  (repo and isolated_jobs are fixtures pytest finds by name)
    fake_smi, fetch, get_json, isolated_jobs, raw_exchange, repo, running, snapshot)

from part2 import jobs, runapi


# ---- the run API over HTTP (AC-A04 to AC-A12) ----------------------------------------------------------------------

@pytest.fixture
def runner(tmp_path):
    """A fake `part2 run` whose behaviour the test sets: runner["behaviour"] = "ok" | "class-fallback" | "sleep" ..."""
    script = tmp_path / "fake_run.py"
    script.write_text(FAKE_RUN)
    state = {"behaviour": "ok"}
    state["command"] = fake_command(script, lambda job: state["behaviour"])
    return state


@pytest.fixture
def run_port(repo, runner, tmp_path, monkeypatch):
    fake_smi(tmp_path, monkeypatch)                        # 20 GiB free
    with running(repo, command=runner["command"]) as p:
        yield p


def post_job(port, fields, file=None, extra=None, filename="clip.mp4"):
    body, ctype = form(fields, file, filename=filename)
    status, headers, raw = fetch(port, "/api/jobs", "POST", body, {"Content-Type": ctype, **(extra or {})})
    return status, headers, json.loads(raw)


def wait_job(port, jid, states=("done", "failed", "cancelled"), timeout=20.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status, doc = get_json(port, f"/api/jobs/{jid}")
        assert status == 200
        if doc["state"] in states:
            return doc
        time.sleep(0.05)
    raise AssertionError(f"job stayed {doc['state']}")


def test_capabilities_list_backends_trackers_samples_and_limits(run_port):
    status, headers, body = fetch(run_port, "/api/capabilities")
    doc = json.loads(body)
    assert status == 200 and headers["cache-control"] == "no-store"
    assert [b["name"] for b in doc["backends"]] == ["gpu", "cpu"]
    assert [t["name"] for t in doc["trackers"]] == ["automatic", "local-open", "bytetrack"]
    assert [s["id"] for s in doc["samples"]] == ["single", "class"]
    assert doc["limits"]["video_s"] == 60 and doc["limits"]["queue"] == 5
    assert "/" not in json.dumps({k: doc[k] for k in ("backends", "trackers", "samples")}).replace("/s", "")


def test_capabilities_say_why_something_cannot_run(repo):
    with running(repo, probe=lambda: {}) as p:
        doc = get_json(p, "/api/capabilities")[1]
        assert not any(b["available"] for b in doc["backends"])
        status, _, body = post_job(p, {"mode": "single", "sample": "single"})
        assert status == 503 and body == {"error": "No backend is available here right now.", "code": "no_backend"}


def test_a_sample_job_runs_and_its_files_download(run_port):
    status, headers, created = post_job(run_port, {"mode": "single", "sample": "single", "backend": "gpu"})
    assert status == 202 and set(created) == {"id", "state"} and headers["cache-control"] == "no-store"
    doc = wait_job(run_port, created["id"])
    assert doc["state"] == "done" and doc["backend"] == "gpu" and doc["tracker"] is None and doc["error"] is None
    assert doc["progress"] == {"stage": "write", "done": 1, "total": 1} and doc["files"] == ["pose3d.json", "camera.json"]
    base = f"/api/jobs/{created['id']}/files/"
    status, headers, body = fetch(run_port, base + "pose3d.json")
    assert status == 200 and headers["content-type"] == "application/json"
    assert headers["content-disposition"] == 'attachment; filename="pose3d.json"'
    assert json.loads(body)["provenance"]["backend"] == "gpu"
    assert fetch(run_port, base + "camera.json")[0] == 200
    assert fetch(run_port, base + "tracks.json")[0] == 404                       # a one-person run has none
    status, headers, body = fetch(run_port, base + "frames/2.jpg")
    assert status == 200 and headers["content-type"] == "image/jpeg" and body.startswith(b"\xff\xd8")
    for bad in ("frames/3.jpg", "frames/02.jpg", "frames/x.jpg", "frames/..%2fjob.json", "job.json", "run.err",
                "run.out", "body3d.json", "..%2fjob.json", "%2e%2e/job.json", "frames", "frames/1.jpg/x"):
        status, _, body = fetch(run_port, base + bad)
        assert status == 404 and json.loads(body) == {"error": "Not found.", "code": "not_found"}, bad
    assert fetch(run_port, base + "pose3d.json", "HEAD")[0] == 200


def test_a_class_job_names_its_fallback_tracker_and_offers_tracks(run_port, runner):
    runner["behaviour"] = "class-fallback"
    status, _, created = post_job(run_port, {"mode": "class", "sample": "class"})
    assert status == 202
    queued = get_json(run_port, f"/api/jobs/{created['id']}")[1]
    assert queued["tracker"] in ("automatic", "local-open") and queued["mode"] == "class"
    doc = wait_job(run_port, created["id"])
    assert doc["tracker"] == "local-open" and doc["fallback"] == {"from": "api-sam31", "reason": "budget"}
    assert doc["notice"] == "SAM 3.1 spend cap reached; tracked with local-open"
    status, headers, _ = fetch(run_port, f"/api/jobs/{created['id']}/files/tracks.json")
    assert status == 200 and headers["content-disposition"] == 'attachment; filename="tracks.json"'


def test_a_photo_job_runs_from_one_upright_frame(run_port):
    status, _, created = post_job(run_port, {"mode": "single"}, jpeg(), filename="photo.jpg")
    assert status == 202
    doc = wait_job(run_port, created["id"])
    assert doc["state"] == "done" and doc["kind"] == "photo"


def test_upload_errors_are_plain_and_leave_no_job(run_port):
    status, _, body = post_job(run_port, {"mode": "single"}, b"just text, renamed\n" * 30, filename="clip.mp4")
    assert status == 415 and body == {"error": "This file is not a video or photo the app can read.", "code": "unsupported"}
    status, _, body = post_job(run_port, {"mode": "single", "tracker": "api-sam31", "sample": "single"})
    assert status == 400 and "chosen by the app" in body["error"]
    status, _, body = post_job(run_port, {"mode": "class", "tracker": "local-sam31", "sample": "class"})
    assert status == 400 and body["code"] == "tracker_by_order"
    status, _, body = post_job(run_port, {"sample": "single"})
    assert status == 400 and body["code"] == "bad_mode"
    assert get_json(run_port, "/api/jobs")[1] == []


def test_the_test_header_lowers_the_body_cap(run_port):
    status, _, body = post_job(run_port, {"mode": "single"}, jpeg(), extra={"X-Part2-Test-Max-Body": "100"})
    assert status == 413 and body["error"] == "The file is too large. Videos can be up to 200 MB and photos up to 20 MB."


def test_a_body_over_the_cap_is_413_without_being_read(repo):
    with running(repo, limits=runapi.Limits(video_bytes=1000, form_slack=0)) as p:
        head, body = raw_exchange(p, b"POST /api/jobs HTTP/1.1\r\nHost: x\r\nContent-Type: multipart/form-data; boundary=b\r\n"
                                     b"Content-Length: 201000000\r\n\r\n")
        assert " 413 " in head.split("\r\n")[0] and json.loads(body)["code"] == "too_large"
        assert "X-Content-Type-Options: nosniff" in head


def test_content_length_missing_or_not_digits(run_port):
    head, body = raw_exchange(run_port, b"POST /api/jobs HTTP/1.1\r\nHost: x\r\nContent-Type: multipart/form-data; boundary=b\r\n\r\n")
    assert " 411 " in head.split("\r\n")[0] and json.loads(body)["code"] == "length_required"
    head, body = raw_exchange(run_port, b"POST /api/jobs HTTP/1.1\r\nHost: x\r\nContent-Length: lots\r\n\r\n")
    assert " 400 " in head.split("\r\n")[0] and json.loads(body)["code"] == "bad_length"


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg is not installed")
def test_a_61_second_video_is_422(run_port, tmp_path):
    clip = tmp_path / "long.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=gray:s=32x32:r=1", "-t", "61",
                    "-c:v", "mpeg4", str(clip)], check=True, timeout=120)
    status, _, body = post_job(run_port, {"mode": "single"}, clip.read_bytes())
    assert status == 422 and body == {"error": "Videos can be at most 60 seconds long.", "code": "too_long"}


def test_the_sixth_job_is_429_and_cancel_answers_409_and_404(run_port, runner):
    runner["behaviour"] = "sleep"
    ids = [post_job(run_port, {"mode": "single", "sample": "single"})[2]["id"] for _ in range(5)]
    status, _, body = post_job(run_port, {"mode": "single", "sample": "single"})
    assert status == 429 and body == {"error": "The queue is full. Try again in a few minutes.", "code": "queue_full"}
    listing = get_json(run_port, "/api/jobs")[1]
    assert [r["position"] for r in listing][1:] == [1, 2, 3, 4] and all(i not in json.dumps(listing) for i in ids)
    for jid in reversed(ids):
        status, _, body = fetch(run_port, f"/api/jobs/{jid}/cancel", "POST")
        assert status == 200 and json.loads(body) == {"state": "cancelled"}
    status, _, body = fetch(run_port, f"/api/jobs/{ids[0]}/cancel", "POST")
    assert status == 409 and json.loads(body) == {"error": "This job has already finished.", "code": "finished"}
    assert fetch(run_port, "/api/jobs/0123456789ab/cancel", "POST")[0] == 404
    assert fetch(run_port, "/api/jobs/..%2f..%2fcancel/cancel", "POST")[0] == 404
    assert get_json(run_port, f"/api/jobs/{ids[0]}")[1]["state"] == "cancelled"
    assert fetch(run_port, f"/api/jobs/{ids[0]}/files/pose3d.json")[0] == 404     # nothing to download


def test_a_failed_job_reports_a_plain_message(run_port, runner):
    runner["behaviour"] = "noperson"
    doc = wait_job(run_port, post_job(run_port, {"mode": "single", "sample": "single"})[2]["id"])
    assert doc["state"] == "failed" and doc["error"] == "No person was found in this file."
    runner["behaviour"] = "crash"
    doc = wait_job(run_port, post_job(run_port, {"mode": "single", "sample": "single"})[2]["id"])
    text = json.dumps(doc)
    assert "Traceback" not in text and "KeyError" not in text and "/home" not in text and ".py" not in text


def test_a_gpu_job_waits_while_memory_is_short(repo, runner, tmp_path, monkeypatch):
    fake_smi(tmp_path, monkeypatch, "4096, 32768")
    with running(repo, command=runner["command"]) as p:
        jid = post_job(p, {"mode": "single", "sample": "single", "backend": "gpu"})[2]["id"]
        assert wait_job(p, jid, ("waiting-gpu",))["position"] == 0
        assert get_json(p, "/api/health")[1]["worker"] == "busy"
        doc = wait_job(p, jid)
        assert doc["error"] == "The GPU is busy with other work; try again later."


def test_unknown_jobs_are_404(run_port):
    for path in ("/api/jobs/0123456789ab", "/api/jobs/xyz", "/api/jobs/..%2f..%2fsecret.txt", "/api/jobs/%2e%2e",
                 "/api/jobs/0123456789ab/files/pose3d.json", "/api/jobs/0123456789AB", "/api/jobs/"):
        status, _, body = fetch(run_port, path)
        assert status == 404 and json.loads(body)["code"] == "not_found", path


def test_running_jobs_write_nothing_in_the_tree(repo, runner, tmp_path, monkeypatch):
    fake_smi(tmp_path, monkeypatch)
    before = snapshot(repo)
    jobs_dir = tmp_path / "server-jobs"
    with running(repo, command=runner["command"], jobs_dir=jobs_dir) as p:
        for fields, file in (({"mode": "single", "sample": "single"}, None), ({"mode": "single"}, jpeg()),
                             ({"mode": "single"}, b"text"), ({"mode": "class", "sample": "class"}, None)):
            status, _, body = post_job(p, fields, file)
            if status == 202:
                wait_job(p, body["id"])
    assert snapshot(repo) == before
    assert len([d for d in jobs_dir.iterdir() if jobs.JOB_ID.fullmatch(d.name)]) == 3


def test_a_restart_reports_unfinished_jobs_as_failed(repo, runner, tmp_path, monkeypatch):
    fake_smi(tmp_path, monkeypatch)
    runner["behaviour"] = "sleep"
    jobs_dir = tmp_path / "server-jobs"
    with running(repo, command=runner["command"], jobs_dir=jobs_dir) as p:
        jid = post_job(p, {"mode": "single", "sample": "single"})[2]["id"]
        wait_job(p, jid, ("running",))
    with running(repo, command=runner["command"], jobs_dir=jobs_dir) as p:
        doc = get_json(p, f"/api/jobs/{jid}")[1]
        assert doc["state"] == "failed" and doc["error"] == "The server restarted."
