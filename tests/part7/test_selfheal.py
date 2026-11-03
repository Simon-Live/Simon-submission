"""TICKET-204: the self-heal report, the saved-entry content check and the review mark (docs/specs/self-healing.md)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pytest

from part7 import applog, cli, entry_check, heartbeat, labels, selfheal
from support import Api, ffmpeg_video


class _Queue:
    """Just what the sweep reads: recent trainer entries and job folders."""

    def __init__(self, root: Path, jobs: list[tuple[str, str]]) -> None:
        self.root, self.jobs = root, jobs

    def recent_trainer_entries(self, limit: int) -> list[tuple[str, str]]:
        return self.jobs[:limit]

    def job_dir(self, job_id: str) -> Path:
        return self.root / job_id


def _entry(catalog: Path, entry_id: str, seconds: float, manifest: dict[str, Any] | None = None) -> Path:
    folder = catalog / entry_id
    folder.mkdir(parents=True)
    video = ffmpeg_video(folder / "video.mp4", seconds)
    (folder / "manifest.json").write_text(json.dumps(manifest or {"video_uri": "video.mp4"}), encoding="utf-8")
    return video


def _upload(root: Path, job: str, seconds: float) -> Path:
    work = root / job / "work"
    work.mkdir(parents=True)
    return ffmpeg_video(work / "video.mp4", seconds)


# ----- the content check ------------------------------------------------------------------------------------
def test_a_matching_entry_passes_and_is_not_flagged(tmp_path: Path) -> None:
    _entry(tmp_path / "cat", "squat", 3)
    up = _upload(tmp_path / "jobs", "j1", 3)
    assert entry_check.check_entry(tmp_path, tmp_path / "cat", "squat", up, "j1") is True
    assert not labels.needs_review(tmp_path, "squat")


def test_a_different_length_is_logged_flagged_and_reported(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    _entry(tmp_path / "cat", "squat", 3)  # the test pattern the server showed
    up = _upload(tmp_path / "jobs", "j1", 9)
    with caplog.at_level(logging.WARNING):
        assert entry_check.check_entry(tmp_path, tmp_path / "cat", "squat", up, "j1") is False
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "ANOMALY entry_video_mismatch job=j1 entry=squat entry_s=3.0 upload_s=9.0" in text
    assert "may not match what was recorded" in text
    assert labels.needs_review(tmp_path, "squat")
    assert labels.all_labels(tmp_path)["squat"] == {"tags": [], "notes": "", "needs_review": True}
    row = next(r for r in selfheal.status()["checks"] if r["name"] == "entry_content")
    assert row["open"] and "entry_video_mismatch" in row["last_finding"]


def test_the_same_mismatch_is_logged_once_and_a_later_match_clears_the_mark(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    _entry(tmp_path / "cat", "squat", 3)
    bad = _upload(tmp_path / "jobs", "j1", 9)
    good = _upload(tmp_path / "jobs", "j2", 3)
    with caplog.at_level(logging.WARNING):
        entry_check.check_entry(tmp_path, tmp_path / "cat", "squat", bad)
        entry_check.check_entry(tmp_path, tmp_path / "cat", "squat", bad)
    assert sum("ANOMALY entry_video_mismatch" in r.getMessage() for r in caplog.records) == 1
    assert entry_check.check_entry(tmp_path, tmp_path / "cat", "squat", good) is True
    assert not labels.needs_review(tmp_path, "squat")


def test_a_tiny_file_for_its_length_is_flagged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _entry(tmp_path / "cat", "squat", 3)
    up = _upload(tmp_path / "jobs", "j1", 3)
    monkeypatch.setattr(entry_check, "MIN_BYTES_PER_S", 10_000_000)
    found = entry_check.compare(tmp_path / "cat" / "squat" / "video.mp4", up)
    assert found and found["why"] == "the file is too small for its length"


def test_an_unreadable_entry_video_is_flagged_and_an_unreadable_upload_is_not(tmp_path: Path) -> None:
    _entry(tmp_path / "cat", "squat", 3)
    (tmp_path / "cat" / "squat" / "video.mp4").write_bytes(b"not a video")
    up = _upload(tmp_path / "jobs", "j1", 3)
    assert entry_check.check_entry(tmp_path, tmp_path / "cat", "squat", up) is False
    broken = tmp_path / "jobs" / "j2" / "work" / "video.mp4"
    broken.parent.mkdir(parents=True)
    broken.write_bytes(b"x")
    _entry(tmp_path / "cat", "lunge", 3)
    assert entry_check.check_entry(tmp_path, tmp_path / "cat", "lunge", broken) is True


def test_an_entry_without_a_video_has_nothing_to_mismatch(tmp_path: Path) -> None:
    _entry(tmp_path / "cat", "squat", 3, manifest={"video_uri": None})
    up = _upload(tmp_path / "jobs", "j1", 9)
    assert entry_check.check_entry(tmp_path, tmp_path / "cat", "squat", up) is True
    assert entry_check.check_entry(tmp_path, tmp_path / "cat", "ghost", up) is True  # no folder at all


def test_the_sweep_checks_recent_entries_and_counts_mismatches(tmp_path: Path) -> None:
    _entry(tmp_path / "cat", "a", 3)
    _entry(tmp_path / "cat", "b", 3)
    _upload(tmp_path / "jobs", "ja", 3)
    _upload(tmp_path / "jobs", "jb", 8)
    queue = _Queue(tmp_path / "jobs", [("ja", "a"), ("jb", "b"), ("gone", "c")])
    assert entry_check.sweep(tmp_path, tmp_path / "cat", queue) == 1
    assert labels.needs_review(tmp_path, "b") and not labels.needs_review(tmp_path, "a")


def test_a_clean_sweep_marks_the_check_clean(tmp_path: Path) -> None:
    selfheal.record("entry_content", "entry_video_mismatch earlier")
    _entry(tmp_path / "cat", "a", 3)
    _upload(tmp_path / "jobs", "ja", 3)
    assert entry_check.sweep(tmp_path, tmp_path / "cat", _Queue(tmp_path / "jobs", [("ja", "a")])) == 0
    assert selfheal.status()["issues"] == 0


# ----- the report -------------------------------------------------------------------------------------------
def test_status_lists_every_check_and_an_anomaly_marks_its_check(tmp_path: Path) -> None:
    selfheal.configure(tmp_path)
    doc = selfheal.status(tmp_path)
    assert [c["name"] for c in doc["checks"]] == list(selfheal.NAMES) and doc["summary"] == "ok"
    applog.anomaly("p2_track_gpu_busy", "no admission", waited_s=5)
    doc = selfheal.status(tmp_path)
    busy = next(c for c in doc["checks"] if c["name"] == "gpu_busy_routing")
    assert busy["open"] and busy["last_run"] and "p2_track_gpu_busy" in busy["last_finding"]
    assert doc["summary"] == "issues:1"
    selfheal.record("gpu_busy_routing")
    assert selfheal.summary(tmp_path) == "ok"


def test_a_refused_upload_is_shown_but_is_not_an_open_issue(tmp_path: Path) -> None:
    applog.anomaly("upload_refused", "not a video", reason="probe")
    row = next(c for c in selfheal.status()["checks"] if c["name"] == "refused_upload_logging")
    assert row["last_finding"] and not row["open"]


def test_an_old_finding_is_history(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    selfheal.record("parts_gate", "parts_gate_red part=2")
    monkeypatch.setattr(selfheal, "ISSUE_WINDOW_S", -1.0)
    assert selfheal.summary() == "ok"


def test_another_process_reads_the_file_and_the_staging_log(tmp_path: Path) -> None:
    selfheal.configure(tmp_path)
    selfheal.record("restart_drain", "drain_cut_off job=x")
    (tmp_path / "stale.log").write_text("2026-11-01T10:00:00Z stale.sh: stale: a part's remote main moved\n", encoding="utf-8")
    selfheal.configure(None)  # as in the CLI process: memory empty, file present
    rows = {c["name"]: c for c in selfheal.status(tmp_path)["checks"]}
    assert rows["restart_drain"]["open"] and "drain_cut_off" in rows["restart_drain"]["last_finding"]
    assert "remote main moved" in rows["stale_restart"]["last_finding"] and not rows["stale_restart"]["open"]
    assert rows["parts_gate"]["last_run"] is None


def test_cli_prints_the_report_and_exits_1_with_an_open_issue(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["selfheal-status", "--state", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "self-heal: ok" in out and "entry_content" in out and "not run in this state folder" in out
    selfheal.configure(tmp_path)
    selfheal.record("warm_worker", "p2_worker_unhealthy slot=0")
    selfheal.configure(None)
    assert cli.main(["selfheal-status", "--state", str(tmp_path), "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["summary"] == "issues:1"


def test_the_heartbeat_line_carries_the_summary(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    class Q:
        def snapshot(self) -> dict[str, Any]:
            return {"queued": 0, "running": 0, "oldest_running_s": None}

    selfheal.record("warm_worker", "p2_worker_unhealthy slot=0")
    with caplog.at_level(logging.INFO, logger="part7"):
        heartbeat.Heartbeat(Q(), tmp_path, gpu_free=lambda: None).tick()
    assert any(r.getMessage().endswith("selfheal=issues:1 open=warm_worker") for r in caplog.records)


def test_api_health_carries_the_report_and_says_it_is_not_fake(api: Api) -> None:
    status, doc = api.json("GET", "api/health")
    assert status == 200 and doc["fake"] is False
    assert doc["selfheal"]["summary"] == "ok" and len(doc["selfheal"]["checks"]) == len(selfheal.NAMES)


def test_labels_map_reports_the_review_mark_and_a_delete_keeps_none(tmp_path: Path) -> None:
    labels.save(tmp_path, "squat", {"tags": ["legs"], "notes": "x"})
    assert labels.mark_review(tmp_path, "squat", "why") is True and labels.mark_review(tmp_path, "squat", "why") is False
    assert labels.all_labels(tmp_path)["squat"] == {"tags": ["legs"], "notes": "x", "needs_review": True}
    assert labels.get(tmp_path, "squat") == {"tags": ["legs"], "notes": "x"}  # the per-entry route is unchanged
    assert labels.clear_review(tmp_path, "squat") is True and "needs_review" not in labels.all_labels(tmp_path)["squat"]
    assert labels.mark_review(tmp_path, "../x", "why") is False


# ----- route_errors and client_errors (operator ruling moalborati/simon#61) ---------------------------------------
def _msgs(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records]


def _age(check: str, seconds: float) -> None:
    """Make every finding of `check` look `seconds` old."""
    for f in selfheal._FINDINGS.values():
        if f["check"] == check:
            f["ts"] -= seconds


def test_repeated_500s_on_one_route_open_route_errors_naming_route_and_error(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="part7"):
        selfheal.note_crash("GET", "api/me/profile", TypeError("set"))
        for _ in range(3):
            applog.anomaly("http_5xx", method="GET", path="api/me/profile", status=500, seconds=0.1)
    doc = selfheal.status()
    [f] = doc["findings"]
    assert f["check"] == "route_errors" and f["count"] == 3 and f["first_seen"] and f["last_seen"]
    assert "GET api/me/profile" in f["finding"] and "TypeError" in f["finding"]
    assert doc["summary"] == "issues:1" and doc["open"] == ["route_errors"]
    opened = [m for m in _msgs(caplog) if m.startswith("selfheal: open route_errors: ")]
    assert len(opened) == 1  # opening is logged once, not per error


def test_a_quiet_period_closes_route_errors_and_logs_it(caplog: pytest.LogCaptureFixture) -> None:
    applog.anomaly("http_5xx", method="GET", path="api/x", status=500)
    _age("route_errors", 14 * 60)
    assert selfheal.summary() == "issues:1"  # still failing within the quiet period
    with caplog.at_level(logging.INFO, logger="part7"):
        _age("route_errors", 2 * 60)
        assert selfheal.summary() == "ok"
    assert "selfheal: closed route_errors after 15 min quiet" in _msgs(caplog)
    assert selfheal.status()["findings"] == []


def test_the_designed_busy_503_does_not_open_route_errors(api: Api) -> None:
    from part7 import speech

    assert speech._SLOT.acquire(blocking=False)
    try:
        status = api.request("GET", "api/jobs/nojob/speech/0.wav")[0]
    finally:
        speech._SLOT.release()
    assert status in (404, 429, 503)  # whichever the stand-in gives, never a finding
    import time

    time.sleep(0.2)  # the request is reported after the answer is sent
    assert selfheal.status()["findings"] == []


def test_five_client_errors_of_one_kind_open_client_errors(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="part7"):
        for _ in range(4):
            applog.anomaly("client_error", page="#/home", source="fetch", status=404, path="api/gone")
        assert selfheal.status()["findings"] == []
        applog.anomaly("client_error", page="#/home", source="fetch", status=404, path="api/gone")
    [f] = selfheal.status()["findings"]
    assert f["check"] == "client_errors" and "source=fetch" in f["finding"] and "api/gone" in f["finding"]
    assert any(m.startswith("selfheal: open client_errors: ") for m in _msgs(caplog))
    _age("client_errors", 11 * 60)
    assert selfheal.summary() == "ok"


def test_benign_and_scattered_client_errors_do_not_count() -> None:
    for _ in range(8):  # the designed busy answer on a spoken line, as web/errors.js excludes it
        applog.anomaly("client_error", page="#/result", source="fetch", status=503, path="api/jobs/j1/speech/0.wav")
    for kind in ("a", "b", "c", "d"):  # four kinds, two each: no single kind reaches 5
        for _ in range(2):
            applog.anomaly("client_error", page="#/home", source=kind, path="x")
    assert selfheal.status()["findings"] == []


def test_the_health_block_lists_the_open_findings(api: Api) -> None:
    for _ in range(2):
        applog.anomaly("http_5xx", method="GET", path="api/me/profile", status=500)
    status, doc = api.json("GET", "api/health")
    [f] = doc["selfheal"]["findings"]
    assert status == 200 and set(f) == {"check", "finding", "first_seen", "count", "last_seen"} and f["count"] == 2
    assert doc["selfheal"]["state"] == "ok" and doc["selfheal"]["summary"] == "issues:1"


def test_a_real_handler_crash_is_a_route_errors_finding_with_the_error_type(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    import time

    from part7 import server

    def boom(self: Any) -> None:
        raise TypeError("Object of type set is not JSON serializable")

    monkeypatch.setattr(server._Handler, "_health", boom)
    assert api.request("GET", "api/health")[0] == 500
    end = time.monotonic() + 5
    while not selfheal.status()["findings"] and time.monotonic() < end:
        time.sleep(0.05)
    [f] = selfheal.status()["findings"]
    assert "TypeError" in f["finding"] and "api/health" in f["finding"]


def test_a_state_file_write_failure_reports_degraded_logs_once_and_never_raises(
        tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    selfheal.configure(tmp_path / "missing" / "deeper")  # the folder is not there: every write fails
    with caplog.at_level(logging.INFO, logger="part7"):
        selfheal.record("warm_worker", "p2_worker_unhealthy slot=0")
        selfheal.record("warm_worker", "p2_worker_unhealthy slot=1")
    errors = [r for r in caplog.records if r.getMessage().startswith("selfheal: not recording (")]
    assert len(errors) == 1 and errors[0].levelno == logging.ERROR  # once a minute at most
    doc = selfheal.status()
    assert doc["state"] == "degraded" and doc["summary"].startswith("degraded") and doc["degraded"]
    (tmp_path / "missing" / "deeper").mkdir(parents=True)
    monkeypatch.setattr(selfheal, "WRITE_EVERY_S", 0.0)
    selfheal.record("warm_worker", "p2_worker_unhealthy slot=2")
    assert selfheal.status()["state"] == "ok"  # a write that works clears it


def test_a_record_that_raises_is_reported_not_raised(caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(selfheal, "_now", lambda: 1 / 0)
    with caplog.at_level(logging.INFO, logger="part7"):
        selfheal.record("warm_worker", "x")
    assert any("selfheal: not recording (record failed: ZeroDivisionError" in m for m in _msgs(caplog))
    assert selfheal.status()["state"] == "degraded"


def test_open_findings_survive_to_another_process(tmp_path: Path) -> None:
    selfheal.configure(tmp_path)
    applog.anomaly("http_5xx", method="POST", path="api/uploads", status=500)
    selfheal.configure(None)  # the CLI process: memory empty, file present
    assert [f["check"] for f in selfheal.status(tmp_path)["findings"]] == ["route_errors"]


# ----- gpu_starved (TICKET-305) -------------------------------------------------------------------------------
OUTSIDE = "part2 run outside staging (research-1)"


def _starve(waited: float, reason: str = "other GPU work", job: str = "f8e4c1992cd2", holder: str = OUTSIDE) -> None:
    selfheal.check_gpu_starved([(job, 1000.0, reason)], lambda: holder, now=1000.0 + waited)


def test_gpu_starved_opens_at_301_s_behind_outside_work(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    selfheal.configure(tmp_path)
    with caplog.at_level(logging.INFO, logger="part7"):
        _starve(301)
    [finding] = selfheal.open_findings()
    assert finding["check"] == "gpu_starved"
    assert "f8e4c1992cd2" in finding["finding"] and "301 s" in finding["finding"] and OUTSIDE in finding["finding"]
    assert "pid" not in finding["finding"] and "/" not in finding["finding"]
    assert selfheal.heartbeat_text().endswith("open=gpu_starved") and selfheal.summary() == "issues:1"
    assert any(m.startswith("selfheal: open gpu_starved") for m in _msgs(caplog))


def test_gpu_starved_stays_closed_at_299_s_and_when_the_holder_is_this_server() -> None:
    _starve(299)
    _starve(2000, reason="another take", holder="part7")
    assert selfheal.open_findings() == [] and selfheal.summary() == "ok"


def test_gpu_starved_closes_when_the_wait_ends(tmp_path: Path) -> None:
    selfheal.configure(tmp_path)
    _starve(400)
    assert selfheal.summary() == "issues:1"
    selfheal.check_gpu_starved([], lambda: OUTSIDE, now=2000.0)
    assert selfheal.open_findings() == [] and selfheal.summary() == "ok"
    assert json.loads((tmp_path / "selfheal.json").read_text()).get("_findings", {}) == {}


def test_gpu_starved_logs_one_anomaly_per_job(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="part7"):
        _starve(310)
        _starve(370)
        _starve(330, job="aaaa11112222")
    lines = [m for m in _msgs(caplog) if m.startswith("ANOMALY gpu_starved")]
    assert len(lines) == 2 and lines[0].startswith("ANOMALY gpu_starved job=f8e4c1992cd2 waited=310 holder=")
    assert all(r.levelno == logging.WARNING for r in caplog.records if r.getMessage().startswith("ANOMALY gpu_starved"))


def test_gpu_starve_limit_comes_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIMON7_GPU_STARVE_S", "60")
    _starve(61)
    assert selfheal.summary() == "issues:1"


def test_the_heartbeat_feeds_gpu_starved_from_the_queue(tmp_path: Path, caplog: pytest.LogCaptureFixture,
                                                         monkeypatch: pytest.MonkeyPatch) -> None:
    import time as _time

    class Q:
        def snapshot(self) -> dict[str, Any]:
            return {"queued": 0, "running": 1, "oldest_running_s": 5.0}

        def gpu_waits(self) -> list[tuple[str, float, str]]:
            return [("f8e4c1992cd2", _time.time() - 500, "other GPU work")]

    monkeypatch.setattr(heartbeat.gpu_lock, "holder_class", lambda _p: OUTSIDE)
    with caplog.at_level(logging.INFO, logger="part7"):
        heartbeat.Heartbeat(Q(), tmp_path, gpu_free=lambda: None).tick()
    assert any(m.endswith("selfheal=issues:1 open=gpu_starved") for m in _msgs(caplog))
    assert any("ANOMALY gpu_starved job=f8e4c1992cd2" in m for m in _msgs(caplog))
