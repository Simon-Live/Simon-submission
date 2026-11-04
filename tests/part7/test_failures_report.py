"""`part7 failures`: per route, per job, self-heal actions and notices from part7.log (observability.md)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys

from part7 import applog, cli, failures

NOW = datetime(2026, 11, 4, 4, 0, 0, tzinfo=timezone.utc)


def _at(minutes_ago: int) -> str:
    return (NOW - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write(state: Path) -> None:
    http = applog.anomaly_text("http_5xx", method="GET", path="catalog/api/entries", status=503, rid="aaa111aaa111",
                               route="GET catalog/api/entries", reason="Part 6 is down.")
    client = applog.anomaly_text("client_error", detail="status 503", page="#/x", source="fetch", status=503, path="api/x", route="GET api/x", rid="bbb")
    job = applog.anomaly_text("job_failed", "abc123", "the app restarted", stage="pose", cause="restart", kind="follow")
    (state / "part7.log.1").write_text(f"{_at(300)} WARNING {http}\n{_at(50)} WARNING {http}\n", encoding="utf-8")
    (state / "part7.log").write_text("\n".join([
        f"{_at(10)} WARNING {http}", f"{_at(9)} WARNING {client}", f"{_at(8)} WARNING {job}",
        f"{_at(7)} WARNING ANOMALY mail_failed reason=SMTPException", f"{_at(6)} WARNING SELFHEAL action=part6_restart restart 1: exited",
        f"{_at(5)} INFO NOTICE sent: Failure rate is high", f"{_at(4)} INFO heartbeat queued=0", "a traceback line with no time",
    ]) + "\n", encoding="utf-8")


def test_the_report_groups_failures_inside_the_window(tmp_path: Path) -> None:
    _write(tmp_path)
    doc = failures.report(tmp_path, 1.0, NOW)
    route = doc["routes"]["GET catalog/api/entries"]
    assert route["count"] == 2 and route["rid"] == "aaa111aaa111" and route["reason"] == "Part 6 is down." and "503" in route["statuses"]
    assert doc["browser"]["fetch GET api/x"]["count"] == 1
    assert doc["jobs"][0]["job"] == "abc123" and doc["jobs"][0]["cause"] == "restart" and doc["jobs"][0]["reason"] == "the app restarted"
    assert doc["other"]["mail_failed"] == 1
    assert "part6_restart" in doc["selfheal"][0] and "Failure rate" in doc["notices"][0]
    text = failures.render(doc)
    assert "GET catalog/api/entries" in text and "abc123" in text and "part6_restart" in text


def test_no_log_is_a_clean_report(tmp_path: Path) -> None:
    text = failures.render(failures.report(tmp_path, 1.0, NOW))
    assert "routes (5xx): none" in text and "jobs failed: none" in text


def test_the_cli_prints_json(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    assert cli.main(["failures", "--state", str(tmp_path), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["routes"] == {}


def test_it_runs_by_path_without_the_package(tmp_path: Path) -> None:
    r = subprocess.run([sys.executable, "-I", "part7/failures.py", "--state", str(tmp_path)], capture_output=True, text=True, check=False)
    assert r.returncode == 0 and "failures since" in r.stdout
