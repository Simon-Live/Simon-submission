"""TICKET-091: anomaly lines, the job summary, the heartbeat, the client_error route and `part7 diagnose`."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import logging
from pathlib import Path
import sys
import time
from types import SimpleNamespace
from typing import Any

import pytest

from part7 import applog, client_log, diagnose, heartbeat, jobs, runner, server, stagelog
from part7.cli import main as cli_main
from support import Api

VISITOR = {"Cf-Connecting-Ip": "203.0.113.9"}


class Clock:
    """A fake monotonic clock: `tick(s)` moves it."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def tick(self, seconds: float) -> None:
        self.now += seconds


def _wait_for(caplog: pytest.LogCaptureFixture, prefix: str = "ANOMALY") -> list[str]:
    """The request line is logged by the server thread just after the answer is sent: wait for it."""
    deadline = time.monotonic() + 5
    while not _lines(caplog, prefix) and time.monotonic() < deadline:
        time.sleep(0.01)
    return _lines(caplog, prefix)


def _lines(caplog: pytest.LogCaptureFixture, prefix: str = "ANOMALY") -> list[str]:
    return [r.getMessage() for r in caplog.records if r.getMessage().startswith(prefix)]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("SIMON7_SLOW_STAGE_S", "SIMON7_SLOW_STAGE_POSE_S", "SIMON7_SLOW_JOB_S", "SIMON7_SLOW_REQUEST_S",
                 "SIMON7_BACKLOG_QUEUED", "SIMON7_BACKLOG_S", "SIMON7_STALE_RUNNING_S"):
        monkeypatch.delenv(name, raising=False)


# ----- the one convention ------------------------------------------------------------------------------------
def test_anomaly_line_format_quotes_values_and_ends_with_the_detail(caplog: pytest.LogCaptureFixture, tmp_path: Path) -> None:
    job_dir = tmp_path / "jobs" / "abc123def456"
    with caplog.at_level(logging.INFO, logger="part7"):
        applog.anomaly("slow_stage", "line one\nline  two", job="abc123def456", job_dir=job_dir, stage="pose",
                       seconds=412.34, limit=300.0, failed=None, why="a b", timed_out=True)
    record = caplog.records[0]
    assert record.levelno == logging.WARNING
    assert record.getMessage() == ('ANOMALY slow_stage job=abc123def456 stage=pose seconds=412.3 limit=300.0 '
                                   'why="a b" timed_out=true detail=line one line two')
    in_job = (job_dir / "steps" / "part7.log").read_text(encoding="utf-8")
    assert "WARNING ANOMALY slow_stage job=abc123def456" in in_job and in_job.count("\n") == 1


def test_anomaly_text_is_redacted(caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(applog.keys, "redact", lambda text: text.replace("hunter2", "<redacted>"))
    with caplog.at_level(logging.INFO, logger="part7"):
        applog.anomaly("job_failed", "token hunter2 leaked")
    assert caplog.records[0].getMessage() == "ANOMALY job_failed detail=token <redacted> leaked"


def test_stage_limits_default_per_stage_and_env(monkeypatch: pytest.MonkeyPatch) -> None:
    assert applog.slow_stage_limit("pose") == 300.0
    monkeypatch.setenv("SIMON7_SLOW_STAGE_S", "100")
    monkeypatch.setenv("SIMON7_SLOW_STAGE_POSE_S", "50")
    assert (applog.slow_stage_limit("pose"), applog.slow_stage_limit("skeleton")) == (50.0, 100.0)
    monkeypatch.setenv("SIMON7_SLOW_STAGE_S", "nonsense")
    assert applog.slow_stage_limit("skeleton") == 300.0


# ----- slow_stage and part_failed ---------------------------------------------------------------------------
def test_a_slow_stage_logs_an_anomaly_once_it_passes_the_limit(caplog: pytest.LogCaptureFixture, tmp_path: Path,
                                                               monkeypatch: pytest.MonkeyPatch) -> None:
    clock = Clock()
    monkeypatch.setattr(stagelog, "time", SimpleNamespace(monotonic=clock))
    work = tmp_path / "jobs" / "aaaabbbbcccc" / "work"
    with caplog.at_level(logging.INFO, logger="part7"):
        with stagelog.stage(work, "skeleton", []):
            clock.tick(299)
        with stagelog.stage(work, "pose", []):
            clock.tick(301)
        with pytest.raises(RuntimeError), stagelog.stage(work, "keyframes", []):
            clock.tick(400)
            raise RuntimeError("boom")
    assert _lines(caplog) == [
        "ANOMALY slow_stage job=aaaabbbbcccc stage=pose seconds=301.0 limit=300.0",
        "ANOMALY slow_stage job=aaaabbbbcccc stage=keyframes seconds=400.0 limit=300.0 failed=true",
    ]


def test_a_failed_part_logs_part_failed_with_the_last_meaningful_log_line(caplog: pytest.LogCaptureFixture,
                                                                         tmp_path: Path) -> None:
    job = tmp_path / "jobs" / "0123456789ab"
    steps = job / "work" / "steps"
    code = "import sys; print('loading', flush=True); print('Traceback boom: no CUDA device', flush=True); " \
           "print(' 50%|#####     | 5/10', flush=True); print('', flush=True); sys.exit(3)"
    with caplog.at_level(logging.INFO, logger="part7"):
        step = runner.run(1, [sys.executable, "-c", code], cwd=tmp_path, log_path=steps / "part1.log")
    assert step["exit"] == 3
    line = _lines(caplog)[0]
    assert line.startswith("ANOMALY part_failed job=0123456789ab part=1 exit=3 timed_out=false seconds=")
    assert line.endswith("detail=Traceback boom: no CUDA device")
    assert applog.pop_facts("0123456789ab")["part1"] == "failed"


def test_a_timed_out_part_one_is_marked_for_the_summary(caplog: pytest.LogCaptureFixture, tmp_path: Path) -> None:
    job = tmp_path / "jobs" / "ffffeeeedddd"
    with caplog.at_level(logging.INFO, logger="part7"):
        runner.run(1, [sys.executable, "-c", "import time; print('working on it'); time.sleep(30)"], cwd=tmp_path,
                   log_path=job / "work" / "steps" / "part1.log", timeout_s=1)
    line = _lines(caplog)[0]
    assert "part=1 exit=none timed_out=true" in line and line.endswith("detail=part 1 timed out after 1 s")
    assert applog.pop_facts("ffffeeeedddd")["part1"] == "timeout"


def test_a_float_timeout_is_rounded_in_the_note_and_the_anomaly(caplog: pytest.LogCaptureFixture, tmp_path: Path) -> None:
    job = tmp_path / "jobs" / "ffffeeeedddd"
    log_file = job / "work" / "steps" / "part1.log"
    with caplog.at_level(logging.INFO, logger="part7"):
        runner.run(1, [sys.executable, "-c", "import time; time.sleep(30)"], cwd=tmp_path,
                   log_path=log_file, timeout_s=0.1 + 0.2 + 26.2999999)
    assert "part 1 timed out after 26.6 s" in log_file.read_text(encoding="utf-8")
    assert _lines(caplog)[0].endswith("detail=part 1 timed out after 26.6 s")
    applog.pop_facts("ffffeeeedddd")


def test_secs_rounds_to_one_decimal() -> None:
    assert [applog.secs(x) for x in (26.502899999999997, 90.0, 1, 0.04, 0.25)] == ["26.5", "90", "1", "0", "0.2"]


def test_last_meaningful_skips_progress_and_blank_lines(tmp_path: Path) -> None:
    log = tmp_path / "x.log"
    log.write_text("real error here\n\n  12%|##  | 1/8\n----\n", encoding="utf-8")
    assert stagelog.last_meaningful(log) == "real error here"
    assert stagelog.last_meaningful(tmp_path / "missing.log") == "" and stagelog.last_meaningful(None) == ""


# ----- jobs: summary, job_failed, slow_job ------------------------------------------------------------------
def _queue(tmp_path: Path, clock: Clock) -> jobs.JobQueue:
    queue = jobs.JobQueue(tmp_path / "state", workers=1)
    queue._clock = clock
    return queue


def test_the_summary_line_carries_kind_status_total_stages_gpu_wait_and_part1(caplog: pytest.LogCaptureFixture,
                                                                              tmp_path: Path) -> None:
    clock = Clock()
    queue = _queue(tmp_path, clock)

    def fn(ctx: jobs.JobContext) -> dict[str, Any]:
        ctx.set_stage("upload")
        clock.tick(2)
        ctx.set_stage("keyframes")
        clock.tick(10)
        ctx.set_stage("pose")
        applog.log("gpu wait 1005.1 s (reason: flock held)", ctx.id, ctx.dir)  # as gpu_lock logs it
        clock.tick(1200)
        applog.fact(ctx.id, "part1", "timeout")
        ctx.set_stage("analyse")
        clock.tick(5.5)
        return {}

    with caplog.at_level(logging.INFO, logger="part7"):
        job = queue.submit("follow", fn, mode="dance", section={"start_ms": 0, "end_ms": 5000, "index": 2, "count": 4},
                           challenge_id="ch1")
        assert queue.wait(job["id"], 10)["status"] == "done"
    queue.close()
    summary = _lines(caplog, f"job {job['id']} summary:")[0]
    assert summary == (f"job {job['id']} summary: kind=follow status=ok total=1217.5s upload=2.0s keyframes=10.0s "
                       "pose=1200.0s(gpu_wait=1005.1s) analyse=5.5s part1=timeout mode=dance section=2/4 challenge=ch1")
    assert _lines(caplog) == [f"ANOMALY slow_job job={job['id']} kind=follow seconds=1217.5 limit=900.0"]
    assert summary in (tmp_path / "state" / "jobs" / job["id"] / "steps" / "part7.log").read_text(encoding="utf-8")
    assert applog.pop_facts(job["id"]) == {}  # forgotten at the end


def test_a_failed_job_logs_job_failed_with_stage_and_reason_and_a_failed_summary(caplog: pytest.LogCaptureFixture,
                                                                                tmp_path: Path) -> None:
    clock = Clock()
    queue = _queue(tmp_path, clock)

    def fn(ctx: jobs.JobContext) -> None:
        ctx.set_stage("pose")
        clock.tick(7)
        raise jobs.JobFailed("pose", "the pose step failed")

    with caplog.at_level(logging.INFO, logger="part7"):
        job = queue.submit("trainer", fn)
        assert queue.wait(job["id"], 10)["status"] == "failed"
    queue.close()
    assert _lines(caplog) == [f"ANOMALY job_failed job={job['id']} stage=pose cause=failed kind=trainer seconds=7.0 detail=the pose step failed"]
    assert _lines(caplog, f"job {job['id']} summary:") == [f"job {job['id']} summary: kind=trainer status=failed total=7.0s pose=7.0s"]


def test_a_crashing_job_is_job_failed_too(caplog: pytest.LogCaptureFixture, tmp_path: Path) -> None:
    queue = _queue(tmp_path, Clock())

    def fn(ctx: jobs.JobContext) -> None:
        ctx.set_stage("skeleton")
        raise ValueError("bug")

    with caplog.at_level(logging.INFO, logger="part7"):
        job = queue.submit("follow", fn)
        queue.wait(job["id"], 10)
    queue.close()
    assert _lines(caplog)[0].startswith(f"ANOMALY job_failed job={job['id']} stage=skeleton cause=crash kind=follow")


def test_gpu_wait_lines_are_captured_per_stage_without_gpu_lock() -> None:
    applog.fact("j1", "_stage", "pose")
    applog.log("gpu wait 12.5 s (reason: settle)", "j1")
    applog.log("gpu wait 2.5 s (reason: settle)", "j1")
    applog.log("gpu wait 99.0 s (reason: settle)")  # no job: nobody to credit
    facts = applog.pop_facts("j1")
    assert (facts["gpu_wait"], facts["gpu_wait.pose"]) == (15.0, 15.0)


# ----- heartbeat -------------------------------------------------------------------------------------------
class FakeQueue:
    def __init__(self, queued: int = 0, running: int = 0, oldest: float | None = None) -> None:
        self.state = {"queued": queued, "running": running, "oldest_running_s": oldest}

    def snapshot(self) -> dict[str, Any]:
        return dict(self.state)


def test_heartbeat_line_and_na_for_unreadable_values(caplog: pytest.LogCaptureFixture, tmp_path: Path) -> None:
    beat = heartbeat.Heartbeat(FakeQueue(1, 2, 33.0), tmp_path, gpu_free=lambda: 14000)
    with caplog.at_level(logging.INFO, logger="part7"):
        beat.tick()
        heartbeat.Heartbeat(FakeQueue(), tmp_path, gpu_free=lambda: None).tick()
    first, second = _lines(caplog, "heartbeat")
    assert first.startswith("heartbeat queued=1 running=2 oldest_running_s=33.0 load1=")
    assert " gpu_free_mib=14000 disk_free_gb=" in first and "gpu_free_mib=na" in second and "oldest_running_s=na" in second
    assert not _lines(caplog)
    assert first.endswith(" p2_worker=off")  # no warm worker pool in this process (TICKET-099)


def test_heartbeat_reports_the_warm_worker_state(caplog: pytest.LogCaptureFixture, tmp_path: Path,
                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    from part7 import p2_worker
    monkeypatch.setattr(p2_worker, "state", lambda: "busy")
    with caplog.at_level(logging.INFO, logger="part7"):
        heartbeat.Heartbeat(FakeQueue(), tmp_path, gpu_free=lambda: 1).tick()
    assert _lines(caplog, "heartbeat")[0].endswith(" p2_worker=busy")


def test_queue_backlog_needs_more_than_two_queued_for_over_120_s(caplog: pytest.LogCaptureFixture, tmp_path: Path) -> None:
    clock, queue = Clock(), FakeQueue(3, 1, 10.0)
    beat = heartbeat.Heartbeat(queue, tmp_path, clock=clock, gpu_free=lambda: 9000)
    with caplog.at_level(logging.INFO, logger="part7"):
        beat.tick()
        clock.tick(120)
        beat.tick()  # exactly 120 s: not over
        assert not _lines(caplog)
        clock.tick(1)
        beat.tick()
        assert _lines(caplog) == ["ANOMALY queue_backlog queued=3 running=1 seconds=121.0 gpu_free_mib=9000 oldest_running_s=10.0"]
        queue.state["queued"] = 2  # drained to the limit: the timer resets
        beat.tick()
        queue.state["queued"] = 5
        clock.tick(500)
        beat.tick()
        assert len(_lines(caplog)) == 1


def test_stale_running_job_and_low_disk(caplog: pytest.LogCaptureFixture, tmp_path: Path,
                                        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(heartbeat.shutil, "disk_usage", lambda p: SimpleNamespace(free=1_500_000_000))
    beat = heartbeat.Heartbeat(FakeQueue(0, 1, 1801.0), tmp_path, gpu_free=lambda: 5000)
    with caplog.at_level(logging.INFO, logger="part7"):
        beat.tick()
    kinds = [x.split()[1] for x in _lines(caplog)]
    assert kinds == ["heartbeat_stale", "disk_low"]
    assert "oldest_running_s=1801.0" in _lines(caplog)[0] and "disk_free_gb=1.5" in _lines(caplog)[1]


def test_heartbeat_thread_beats_survives_a_failing_reading_and_stops(caplog: pytest.LogCaptureFixture, tmp_path: Path) -> None:
    calls: list[int] = []

    def gpu() -> int:
        calls.append(1)
        if len(calls) == 1:
            raise OSError("nvidia-smi gone")
        return 8000

    beat = heartbeat.Heartbeat(FakeQueue(), tmp_path, interval=0.05, gpu_free=gpu)
    with caplog.at_level(logging.INFO, logger="part7"):
        beat.start()
        deadline = time.monotonic() + 5
        while len(calls) < 3 and time.monotonic() < deadline:
            time.sleep(0.02)
        beat.stop()
    assert len(calls) >= 3 and "gpu_free_mib=na" in _lines(caplog, "heartbeat")[0]
    assert beat._thread is not None and not beat._thread.is_alive() and beat._thread.daemon
    seen = len(calls)
    time.sleep(0.2)
    assert len(calls) == seen  # stopped for good


def test_queue_snapshot_counts_waiting_and_running(tmp_path: Path) -> None:
    clock = Clock()
    queue = jobs.JobQueue(tmp_path / "state", workers=1, start=False)
    queue._clock = clock
    queue.submit("trainer", lambda ctx: None)
    queue.submit("trainer", lambda ctx: None)
    assert queue.snapshot() == {"queued": 2, "running": 0, "oldest_running_s": None}


# ----- HTTP: slow_request, http_5xx, client_error ------------------------------------------------------------
def test_slow_request_logs_method_path_without_query_and_status(api: Api, caplog: pytest.LogCaptureFixture,
                                                                monkeypatch: pytest.MonkeyPatch) -> None:
    ticks = iter(float(n) for n in range(0, 1000, 3))  # every reading is 3 s later: start, first byte, end
    monkeypatch.setattr(server, "time", SimpleNamespace(monotonic=lambda: next(ticks), time=time.time))
    with caplog.at_level(logging.INFO, logger="part7"):
        status, _, _ = api.request("GET", "api/health?who=me")
    assert status == 200
    assert _wait_for(caplog) == ["ANOMALY slow_request method=GET path=api/health status=200 seconds=6.0"]


def _report(api: Api, caplog: pytest.LogCaptureFixture, method: str, rest: str, seconds: float, first: float | None = None,
            length: str | None = None, status: int = 200) -> list[str]:
    """Run the request report for a stub request `method` `<base><rest>` and return the anomaly lines."""
    h = object.__new__(server._Handler)
    h.app, h.command, h.path, h._status = api.app, method, f"{api.app.base}{rest}?q=1", status
    h.headers = {} if length is None else {"Content-Length": length}  # type: ignore[assignment]
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="part7"):
        h._report_request(seconds, first)
    return _lines(caplog)


def test_a_normal_upload_is_not_slow_but_a_20s_one_is(api: Api, caplog: pytest.LogCaptureFixture) -> None:
    assert _report(api, caplog, "POST", "api/uploads", 2.2, length="2097152", status=201) == []
    assert _report(api, caplog, "POST", "api/uploads", 20.0, length="2097152", status=201) == []
    assert _report(api, caplog, "POST", "api/uploads", 20.5, length="2097152", status=201) == [
        "ANOMALY slow_request method=POST path=api/uploads status=201 seconds=20.5 bytes=2097152"]


def test_the_upload_limit_comes_from_the_environment(api: Api, caplog: pytest.LogCaptureFixture,
                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIMON7_SLOW_UPLOAD_S", "1")
    assert len(_report(api, caplog, "POST", "api/uploads", 2.2, length="10", status=201)) == 1


def test_other_routes_keep_the_2s_limit_and_other_posts_are_not_uploads(api: Api, caplog: pytest.LogCaptureFixture) -> None:
    assert _report(api, caplog, "GET", "api/health", 1.9) == []
    assert _report(api, caplog, "GET", "api/health", 2.1) == ["ANOMALY slow_request method=GET path=api/health status=200 seconds=2.1"]
    assert len(_report(api, caplog, "POST", "api/trainer", 2.1, length="40")) == 1


def test_media_routes_are_judged_by_time_to_first_byte(api: Api, caplog: pytest.LogCaptureFixture) -> None:
    for rest in ("api/results/abc123abc123/video.mp4", "catalog/media/clip.webm"):
        assert _report(api, caplog, "GET", rest, 60.0, 0.05, status=206) == []  # streamed for a minute, started at once
        assert _report(api, caplog, "GET", rest, 60.0, 9.9) == []
        assert len(_report(api, caplog, "GET", rest, 60.0, 10.5)) == 1  # the server itself was slow to begin


def test_the_media_limit_comes_from_the_environment(api: Api, caplog: pytest.LogCaptureFixture,
                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIMON7_SLOW_MEDIA_S", "1")
    assert len(_report(api, caplog, "GET", "api/results/abc123abc123/video.mp4", 5.0, 1.5)) == 1


def test_the_path_is_below_the_base_path_and_a_5xx_has_bytes_too(api: Api, caplog: pytest.LogCaptureFixture) -> None:
    lines = _report(api, caplog, "POST", "api/uploads", 0.1, length="5", status=500)
    assert len(lines) == 1 and lines[0].startswith("ANOMALY http_5xx method=POST path=api/uploads status=500")
    assert lines[0].endswith("bytes=5") and api.app.base.strip("/") not in lines[0].split("path=")[1].split()[0]


def test_a_fast_request_logs_nothing(api: Api, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="part7"):
        api.request("GET", "api/health")
        time.sleep(0.2)
    assert not _lines(caplog)


def test_a_crashing_handler_is_http_5xx(api: Api, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(self: Any) -> None:
        raise RuntimeError("handler bug")

    monkeypatch.setattr(server._Handler, "_route", broken)
    with caplog.at_level(logging.INFO, logger="part7"):
        status, _, _ = api.request("GET", "api/health?secret=1")
    assert status == 500
    lines = _wait_for(caplog)
    assert len(lines) == 1 and lines[0].startswith("ANOMALY http_5xx method=GET path=api/health status=500 seconds=")
    assert "secret" not in lines[0]


def _post(api: Api, doc: dict[str, Any]) -> int:
    return api.request("POST", "api/client-log", json.dumps(doc).encode(), {"Content-Type": "application/json", **VISITOR})[0]


def test_client_error_events_become_anomalies_with_the_page_and_cut_fields(api: Api, caplog: pytest.LogCaptureFixture) -> None:
    detail = {"source": "fetch", "message": "status 502", "path": "api/jobs/ab12", "status": 502, "junk": [1, 2], "line": True}
    with caplog.at_level(logging.INFO, logger="part7"):
        assert _post(api, {"level": "error", "event": "client_error", "detail": detail, "page": "#/follow/e1"}) == 204
        assert _post(api, {"level": "warn", "event": "camera_dark", "detail": {"a": 1}, "page": "#/record"}) == 204
    assert _lines(caplog) == ["ANOMALY client_error page=#/follow source=fetch status=502 path=api/jobs/ab12 detail=status 502"]
    assert _lines(caplog, "client warn camera_dark") == ['client warn camera_dark page=#/record {"a":1}']


def test_client_error_without_message_or_with_odd_detail(caplog: pytest.LogCaptureFixture) -> None:
    fields = client_log.error_fields({"detail": "[1]", "page": ""})
    assert fields == {"page": "-", "detail": ""}
    assert client_log.error_fields({"detail": "not json", "page": "#/x"})["page"] == "#/x"


# ----- diagnose --------------------------------------------------------------------------------------------
FIXTURE_LOG = """\
2026-10-31T10:00:00Z INFO serve start: pid 1 on 127.0.0.1:8000/, state /s, log /s/part7.log
2026-10-31T10:01:00Z INFO job aaa111aaa111: gpu wait 1005.1 s (reason: flock held)
2026-10-31T10:01:30Z INFO job bbb222bbb222: gpu wait 1.4 s (reason: settle)
2026-10-31T10:02:00Z WARNING job aaa111aaa111: part 1 failed in 90.0 s: part 1 exit None (timed out), log /s/steps/part1.log
2026-10-31T10:02:01Z WARNING ANOMALY part_failed job=aaa111aaa111 part=1 exit=none timed_out=true seconds=90.0 detail=working on it
2026-10-31T10:03:00Z WARNING job ccc333ccc333: part 1 failed in 91.5 s: part 1 exit None (timed out)
2026-10-31T10:04:00Z WARNING ANOMALY slow_stage job=aaa111aaa111 stage=pose seconds=1012.0 limit=300.0
2026-10-31T10:04:30Z WARNING ANOMALY slow_stage job=ccc333ccc333 stage=skeleton seconds=320.5 limit=300.0
2026-10-31T10:05:00Z WARNING job ddd444ddd444: failed at pose after 5.0 s: JobFailed: pose failed
2026-10-31T10:05:01Z WARNING ANOMALY job_failed job=ddd444ddd444 stage=pose kind=follow seconds=5.0 detail=the pose step failed
2026-10-31T10:05:30Z WARNING job eee555eee555: crashed at analyse: ValueError: x (traceback in steps/error.log)
2026-10-31T10:06:00Z WARNING ANOMALY http_5xx method=GET path=/api/jobs/x status=500 seconds=0.1
2026-10-31T10:07:00Z WARNING ANOMALY client_error page=#/follow/e1 source=onerror file=watch.js line=10 detail=Uncaught TypeError: x is null
2026-10-31T10:08:00Z WARNING client warn body_dimmed page=#/result/abc {"view":"overlay","report":{"dimmed":3}}
2026-10-31T10:09:00Z INFO heartbeat queued=0 running=0 oldest_running_s=na load1=0.10 gpu_free_mib=14000 disk_free_gb=50.0
2026-10-31T10:10:00Z WARNING ANOMALY queue_backlog queued=4 running=1 seconds=130.0 gpu_free_mib=900 oldest_running_s=10.0
continuation line without a stamp
"""


def _state(tmp_path: Path, text: str = FIXTURE_LOG, rotated: str = "") -> Path:
    state = tmp_path / "st"
    state.mkdir()
    (state / "part7.log").write_text(text, encoding="utf-8")
    if rotated:
        (state / "part7.log.1").write_text(rotated, encoding="utf-8")
    return state


def test_parse_fields_handles_quotes_detail_and_missing_values() -> None:
    assert diagnose.parse_fields('job=a why="x y" n=3 detail=has = signs and "quotes"') == {
        "job": "a", "why": "x y", "n": "3", "detail": 'has = signs and "quotes"'}
    assert diagnose.parse_fields("detail=only") == {"detail": "only"}
    assert diagnose.parse_fields("") == {}
    text = applog.anomaly_text("x", "j1", "d", why='say "hi" \\ there')
    assert diagnose.parse_fields(text.split(" ", 2)[2])["why"] == 'say "hi" \\ there'


def test_since_parses_units_and_rejects_nonsense() -> None:
    assert diagnose.parse_since("2h").total_seconds() == 7200 and diagnose.parse_since("90m").total_seconds() == 5400
    with pytest.raises(ValueError):
        diagnose.parse_since("soon")


def test_diagnose_ranks_findings_counts_jobs_and_names_a_cause(tmp_path: Path) -> None:
    found, lines, files = diagnose.scan_state(_state(tmp_path), None)
    doc = diagnose.report(found, lines, files, "all")
    kinds = [f["kind"] for f in doc["findings"]]
    assert kinds == ["job_failed", "part_failed", "http_5xx", "part1_timeout", "queue_backlog", "client_error",
                     "slow_stage", "gpu_wait", "body_dimmed"]
    by = {f["kind"]: f for f in doc["findings"]}
    assert by["job_failed"]["count"] == 2 and by["job_failed"]["jobs"] == ["ddd444ddd444", "eee555eee555"]  # the crash has no ANOMALY line
    assert by["part1_timeout"]["jobs"] == ["ccc333ccc333"]  # aaa111 is covered by its part_failed anomaly
    assert by["gpu_wait"]["count"] == 1 and by["gpu_wait"]["worst"]["seconds"] == "1005.1"
    assert by["slow_stage"]["worst"]["stage"] == "pose" and "GPU" in by["slow_stage"]["likely_cause"]
    assert "flock" in diagnose.cause_of(diagnose.Finding("gpu_wait", worst={"reason": "flock held"}))
    assert by["client_error"]["worst"]["file"] == "watch.js" and by["body_dimmed"]["worst"]["page"] == "#/result/abc"
    assert doc["clean"] is False and lines == 16
    assert "likely:" in diagnose.render(doc) and "1. job_failed x2" in diagnose.render(doc)


def test_diagnose_since_cuts_old_lines_and_reads_the_rotated_file(tmp_path: Path) -> None:
    now = datetime(2026, 10, 31, 10, 11, 0, tzinfo=timezone.utc)
    state = _state(tmp_path, FIXTURE_LOG, rotated="2026-10-31T09:00:00Z WARNING ANOMALY slow_job job=old000old000 seconds=2000.0 limit=900.0\n")
    found, _, files = diagnose.scan_state(state, timedelta(minutes=6), now)
    assert len(files) == 2 and {"slow_job", "gpu_wait", "part_failed"}.isdisjoint(found)
    assert found["job_failed"].jobs == ["ddd444ddd444", "eee555eee555"] and "queue_backlog" in found
    found_all, _, _ = diagnose.scan_state(state, timedelta(hours=3), now)
    assert found_all["slow_job"].jobs == ["old000old000"]


def test_diagnose_cli_exit_codes_and_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    clean = _state(tmp_path, "2026-10-31T10:00:00Z INFO serve ready\n2026-10-31T10:01:00Z INFO job a: gpu wait 1.1 s (reason: settle)\n")
    assert cli_main(["diagnose", "--state", str(clean), "--since", "100d"]) == 0
    assert "clean" in capsys.readouterr().out
    dirty = tmp_path / "dirty"
    dirty.mkdir()
    (dirty / "part7.log").write_text(FIXTURE_LOG, encoding="utf-8")
    assert cli_main(["diagnose", "--since", "3650d", "--json", "--state", str(dirty)]) == 1
    doc = json.loads(capsys.readouterr().out)
    assert doc["clean"] is False and doc["findings"][0]["kind"] == "job_failed"
    assert cli_main(["diagnose", "--state", str(dirty), "--since", "yesterday"]) == 2
    assert cli_main(["diagnose", "--since", "1h", "--state", str(tmp_path / "nowhere")]) == 0
