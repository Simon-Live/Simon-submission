"""The result routes find a trainer job and parse job files without scanning every folder (TICKET-111 item 11)."""

from __future__ import annotations

import json
from pathlib import Path
import time

from part7 import job_lookup, mesh_files, models_used
from part7.jobs import JobQueue

ENTRY = "knee-raise-0a1b2c3d"


def _record(root: Path, job_id: str, **fields: object) -> None:
    folder = root / "jobs" / job_id
    folder.mkdir(parents=True)
    rec = {"id": job_id, "kind": "follow", "status": "done", "stages": [], "note": None,
           "created_at": "2026-10-31T10:00:00Z", **fields}
    (folder / "job.json").write_text(json.dumps(rec), encoding="utf-8")


def _tree(tmp_path: Path, n: int = 500) -> JobQueue:
    for i in range(n):
        _record(tmp_path, f"{i:012x}", kind="trainer", entry_id=f"other-{i}", finished_at=f"2026-10-31T10:{i % 60:02d}:00Z")
    _record(tmp_path, "aaaaaaaaaaaa", kind="trainer", entry_id=ENTRY, finished_at="2026-10-30T10:00:00Z")
    _record(tmp_path, "bbbbbbbbbbbb", kind="trainer", entry_id=ENTRY, finished_at="2026-10-31T11:00:00Z")
    _record(tmp_path, "cccccccccccc", kind="trainer", entry_id=ENTRY, status="failed", finished_at="2026-10-31T12:00:00Z")
    _record(tmp_path, "dddddddddddd", kind="follow", entry_id=ENTRY, finished_at="2026-10-31T12:30:00Z")
    return JobQueue(tmp_path, start=False)


def test_the_queue_names_the_newest_done_trainer_job_of_an_entry(tmp_path: Path) -> None:
    q = _tree(tmp_path)
    assert q.trainer_for(ENTRY) == "bbbbbbbbbbbb", "the newest done one; a failed or follow job is not a trainer take"
    assert q.trainer_for("no-such-entry") is None
    assert models_used.trainer_job(q.root, ENTRY) == q.root / "bbbbbbbbbbbb"
    q.forget("bbbbbbbbbbbb")
    assert q.trainer_for(ENTRY) == "aaaaaaaaaaaa", "a deleted trainer job leaves the index"
    q.close()


def test_a_folder_without_a_queue_is_still_scanned(tmp_path: Path) -> None:
    q = _tree(tmp_path, n=3)
    q.close()  # releases the lookup
    assert job_lookup.registered(q.root) is None
    assert models_used.trainer_job(q.root, ENTRY) == q.root / "bbbbbbbbbbbb"


def test_mesh_and_models_answer_fast_with_500_jobs(tmp_path: Path) -> None:
    q = _tree(tmp_path)
    for who in ("trainer", "you"):
        folder = q.root / "bbbbbbbbbbbb" / "work" / "trainer" / "part2" if who == "trainer" else q.root / "dddddddddddd" / "work" / "follower" / "part2"
        folder.mkdir(parents=True)
        (folder / "mesh3d.json").write_text("{}", encoding="utf-8")
        (folder / "mesh3d.bin").write_bytes(b"x")
    t0 = time.perf_counter()
    doc = mesh_files.index(q.root, "dddddddddddd")
    models = models_used.collect(q.root, "dddddddddddd")
    elapsed = time.perf_counter() - t0
    assert doc is not None and doc["trainer"] and doc["you"]
    assert models is not None and any(r["id"] == "sam31-trainer" for r in models["models"])
    assert elapsed < 0.2, f"both routes took {elapsed:.3f} s"
    q.close()


def test_read_json_reparses_only_when_the_file_changed(tmp_path: Path) -> None:
    path = tmp_path / "x.json"
    path.write_text('{"a": 1}', encoding="utf-8")
    first = job_lookup.read_json(path)
    assert job_lookup.read_json(path) is first, "unchanged: the parsed value is reused"
    path.write_text('{"a": 22}', encoding="utf-8")
    assert job_lookup.read_json(path) == {"a": 22}
    assert job_lookup.read_json(tmp_path / "missing.json") is None
    path.write_text("not json", encoding="utf-8")
    assert job_lookup.read_json(path) is None
