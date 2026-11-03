"""tools/cost_per_take.py (TICKET-261, docs/specs/cost-per-take.md AC-001 to AC-005)."""

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import cost_per_take as cpt  # noqa: E402


def job(state: Path, jid: str, entry: str, pose: float, wait: float = 0.0, kind: str = "follow", status: str = "done") -> None:
    d = state / "jobs" / jid
    (d / "steps").mkdir(parents=True)
    (d / "job.json").write_text(json.dumps({"id": jid, "kind": kind, "status": status, "entry_id": entry}))
    w = f"(gpu_wait={wait}s)" if wait else ""
    (d / "steps" / "part7.log").write_text(
        f"2026-11-01T00:00:00Z INFO job {jid} summary: kind=follow status=ok total=9.0s upload=0.0s pose={pose}s{w} skeleton=0.3s\n")


def fixture(tmp_path: Path) -> Path:
    job(tmp_path, "a1", "real-1", 100.0)
    job(tmp_path, "a2", "real-1", 60.0, wait=20.0)  # 40 after the wait
    job(tmp_path, "a3", "real-2", 80.0)
    job(tmp_path, "b1", "verify-x", 5000.0)
    job(tmp_path, "b2", "qa-journey-1", 5000.0)
    job(tmp_path, "b3", "check-7-abc", 5000.0)
    job(tmp_path, "c1", "real-3", 5000.0, status="failed")
    job(tmp_path, "c2", "real-3", 5000.0, kind="people")
    (tmp_path / "history").mkdir()
    (tmp_path / "history" / "spend.jsonl").write_text("\n".join([
        json.dumps({"call": "x", "kind": "reserve", "usd": 0.02}),
        json.dumps({"call": "x", "kind": "settle", "usd": 0.01}),
        "not json",
        json.dumps({"call": "y", "kind": "reserve", "usd": 0.02}),
    ]))
    return tmp_path


def test_excluded_and_unfinished_jobs_never_counted(tmp_path):  # AC-001
    rows = cpt.read_jobs(fixture(tmp_path))
    assert sorted(rows) == [("real-1", 40.0), ("real-1", 100.0), ("real-2", 80.0)]


def test_report_names_count_date_rule_and_figures(tmp_path):  # AC-002, AC-003
    text = cpt.report(fixture(tmp_path), "2026-11-02")
    assert "follow takes counted: 3" in text and "run 2026-11-02" in text and "verify-" in text
    assert "p50 80.0, p90 96.0, mean 73.3" in text
    assert "takes per GPU-hour (derived: 3600 / mean GPU seconds): 49.1" in text
    assert "max 2, median 1.5" in text
    assert "GPU price: none used" in text


def test_ledger_uses_settle_else_reserve(tmp_path):  # AC-004
    assert abs(cpt.settled_usd(fixture(tmp_path) / "history" / "spend.jsonl") - 0.03) < 1e-9
    assert "mean $0.0100 USD per take" in cpt.report(tmp_path, "d")


def test_missing_state_exits_2(tmp_path, capsys):  # AC-005
    assert cpt.main([str(tmp_path / "nope")]) == 2
    assert "no jobs dir" in capsys.readouterr().err


def test_no_counted_takes(tmp_path):
    (tmp_path / "jobs").mkdir()
    assert "no counted takes" in cpt.report(tmp_path, "d")
