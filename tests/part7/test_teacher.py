"""The teacher page: per-movement takes, score history and cues (docs/specs/teacher-dashboard.md AC-T1 to AC-T9)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pytest

from auth_support import authenv, get, sign_in  # noqa: F401  authenv is a fixture
from part7 import auth, teacher_stats
from support import Api

ENTRY = "lateral-raise"


def _score(value: Any, grade: str, windows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {"value": value, "grade": grade, "timeline": windows or []}


def _window(*cues: str, tempo: str | None = None) -> dict[str, Any]:
    return {"compared": True, "misses": [{"text": f"t {c}", "cue": c} for c in cues], "tempo": {"ratio": 1.0, "cue": tempo}}


def _job(root: Path, job_id: str, *, score: Any = None, code: str = "ok", entry: str = ENTRY, kind: str = "follow",
         status: str = "done", at: str = "2026-10-31T10:00:00Z", analysis: Any = "auto", shared: bool = True,
         **extra: Any) -> None:
    """A job folder; `shared` is the take owner's choice to show it to the movement's owner (private-default D3)."""
    folder = root / job_id
    (folder / "work" / "follower").mkdir(parents=True)
    if shared:
        teacher_stats.set_shared(folder, True)
    record = {"id": job_id, "kind": kind, "status": status, "entry_id": entry, "finished_at": at, "created_at": at, **extra}
    (folder / "job.json").write_text(json.dumps(record), encoding="utf-8")
    if analysis == "auto":
        analysis = {"status": {"code": code}, "score": score if score is not None else _score(80, "B")}
    if analysis is not None:
        (folder / "work" / "follower" / "analysis.json").write_text(json.dumps(analysis), encoding="utf-8")


def test_empty_when_no_jobs(tmp_path: Path) -> None:  # AC-T1
    assert teacher_stats.collect(tmp_path, ENTRY) == {"entry": ENTRY, "takes": [], "cue_counts": []}
    assert teacher_stats.collect(tmp_path / "missing", ENTRY)["takes"] == []


def test_one_take_reads_score_grade_and_cues_from_its_analysis(tmp_path: Path) -> None:  # AC-T2
    _job(tmp_path, "aaaaaaaaaaaa", score=_score(77, "C", [_window("Keep your chest up", tempo="Slow down"), _window("Keep your chest up")]),
         result={"score": 1, "grade": "F"})
    doc = teacher_stats.collect(tmp_path, ENTRY)
    assert doc["entry"] == ENTRY and len(doc["takes"]) == 1
    take = doc["takes"][0]
    assert (take["score"], take["grade"], take["at"]) == (77, "C", "2026-10-31T10:00:00Z")  # not the job record's 1 and F
    assert take["top_cues"] == ["Keep your chest up", "Slow down"]
    assert doc["cue_counts"] == [{"text": "Keep your chest up", "count": 1}, {"text": "Slow down", "count": 1}]


def test_many_takes_oldest_first_cues_counted_per_take_and_top_three(tmp_path: Path) -> None:  # AC-T3
    _job(tmp_path, "bbbbbbbbbbbb", at="2026-10-31T12:00:00Z", score=_score(90, "A", [_window("A cue")]))
    _job(tmp_path, "aaaaaaaaaaaa", at="2026-10-30T12:00:00Z", score=_score(60, "D", [_window("A cue", "B cue", "C cue", "D cue"), _window("B cue")]))
    _job(tmp_path, "cccccccccccc", at="2026-10-31T13:00:00Z", score=_score(75, "C", [_window("A cue")]))
    doc = teacher_stats.collect(tmp_path, ENTRY)
    assert [t["score"] for t in doc["takes"]] == [60, 90, 75]
    assert doc["takes"][0]["top_cues"] == ["B cue", "A cue", "C cue"]  # B twice, then the order shown
    assert doc["cue_counts"][0] == {"text": "A cue", "count": 3}
    assert {"text": "B cue", "count": 1} in doc["cue_counts"]
    assert all(c["count"] <= 3 for c in doc["cue_counts"])


def test_failed_unfinished_unscored_and_other_kinds_are_ignored(tmp_path: Path) -> None:  # AC-T4
    _job(tmp_path, "aaaaaaaaaaaa", status="failed", analysis=None)
    _job(tmp_path, "bbbbbbbbbbbb", status="running", analysis=None)
    _job(tmp_path, "cccccccccccc", code="no_person")
    _job(tmp_path, "dddddddddddd", kind="trainer")
    _job(tmp_path, "eeeeeeeeeeee", analysis=None)  # done, but the analysis is gone
    _job(tmp_path, "ffffffffffff", score={"value": "9", "grade": "A"})
    _job(tmp_path, "111111111111", score={"value": True, "grade": "A"})
    _job(tmp_path, "222222222222", analysis=["not", "an", "object"])
    _job(tmp_path, "333333333333", score=_score(88, "B"))
    assert [t["score"] for t in teacher_stats.collect(tmp_path, ENTRY)["takes"]] == [88]


def test_other_entries_are_ignored(tmp_path: Path) -> None:  # AC-T5
    _job(tmp_path, "aaaaaaaaaaaa", entry="reverse-lunge", score=_score(10, "F"))
    _job(tmp_path, "bbbbbbbbbbbb", score=_score(70, "C"))
    assert [t["score"] for t in teacher_stats.collect(tmp_path, ENTRY)["takes"]] == [70]
    assert [t["score"] for t in teacher_stats.collect(tmp_path, "reverse-lunge")["takes"]] == [10]


def test_malformed_job_is_skipped_with_a_log_line(tmp_path: Path, caplog: Any) -> None:  # AC-T6
    (tmp_path / "badbadbadbad").mkdir()
    (tmp_path / "badbadbadbad" / "job.json").write_text("{not json", encoding="utf-8")
    (tmp_path / "ccccccccccc1").mkdir()
    (tmp_path / "ccccccccccc1" / "job.json").write_text("[]", encoding="utf-8")
    _job(tmp_path, "aaaaaaaaaaaa", score=_score(70, "C"))
    _job(tmp_path, "999999999999", analysis=None)
    (tmp_path / "999999999999" / "work" / "follower" / "analysis.json").write_text("nope", encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="part7"):
        doc = teacher_stats.collect(tmp_path, ENTRY)
    assert [t["score"] for t in doc["takes"]] == [70]
    assert "teacher: skipped badbadbadbad" in caplog.text
    assert "teacher: skipped ccccccccccc1" in caplog.text
    assert "teacher: skipped 999999999999" in caplog.text


def test_a_folder_that_is_not_a_job_id_is_not_read(tmp_path: Path) -> None:
    _job(tmp_path, "not-a-job-id", score=_score(70, "C"))
    assert teacher_stats.collect(tmp_path, ENTRY)["takes"] == []


def test_answer_has_no_job_id_and_no_substring_derived_from_one(tmp_path: Path) -> None:  # AC-T7
    import hashlib

    ids = ["aaaaaaaaaaaa", "0123456789ab", "fedcba987654"]
    for n, job_id in enumerate(ids):
        _job(tmp_path, job_id, at=f"2026-10-3{n}T10:00:00Z", score=_score(60 + n, "C", [_window("Keep your chest up")]))
    doc = teacher_stats.collect(tmp_path, ENTRY)
    text = json.dumps(doc)
    assert [t["n"] for t in doc["takes"]] == [1, 2, 3]  # the position, oldest first
    assert all(set(t) == {"n", "at", "score", "grade", "top_cues", "shown"} for t in doc["takes"])  # shown: one-letter.md
    for job_id in ids:
        derived = {job_id, job_id.upper(), "t" + job_id}
        for algo in ("sha256", "sha1", "md5", "sha512"):
            digest = hashlib.new(algo, job_id.encode()).hexdigest()
            derived |= {digest[:k] for k in range(6, 17)}
        derived |= {job_id[i:i + 6] for i in range(0, 7)}  # any 6-character slice of the id itself
        assert not [d for d in derived if d in text], job_id
    assert "work" not in text


def test_unchanged_folders_are_not_parsed_again_and_changes_are_seen(tmp_path: Path, monkeypatch: Any) -> None:  # AC-T12
    import os

    _job(tmp_path, "aaaaaaaaaaaa", score=_score(70, "C"))
    calls = []
    real = teacher_stats._parse_folder
    monkeypatch.setattr(teacher_stats, "_parse_folder", lambda folder: calls.append(folder.name) or real(folder))
    assert [t["score"] for t in teacher_stats.collect(tmp_path, ENTRY)["takes"]] == [70]
    teacher_stats.collect(tmp_path, ENTRY)
    teacher_stats.collect(tmp_path, "reverse-lunge")
    assert calls == ["aaaaaaaaaaaa"]  # one parse for three requests
    path = tmp_path / "aaaaaaaaaaaa" / "work" / "follower" / "analysis.json"
    path.write_text(json.dumps({"status": {"code": "ok"}, "score": _score(95, "A")}), encoding="utf-8")
    os.utime(path, ns=(1, 1))  # a changed file has a new stamp
    assert [t["score"] for t in teacher_stats.collect(tmp_path, ENTRY)["takes"]] == [95]
    import shutil

    shutil.rmtree(tmp_path / "aaaaaaaaaaaa")
    assert teacher_stats.collect(tmp_path, ENTRY)["takes"] == []  # a removed job is gone and its cache entry dropped
    assert teacher_stats._CACHE[str(tmp_path)] == {}


def test_takes_and_cue_rows_are_capped(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setattr(teacher_stats, "TAKES_MAX", 2)
    monkeypatch.setattr(teacher_stats, "CUES_MAX", 1)
    for n, day in enumerate(("28", "29", "30")):
        _job(tmp_path, f"{n}" * 12, at=f"2026-10-{day}T10:00:00Z", score=_score(50 + n, "C", [_window(f"cue {n}")]))
    doc = teacher_stats.collect(tmp_path, ENTRY)
    assert [t["score"] for t in doc["takes"]] == [51, 52]  # the newest two
    assert len(doc["cue_counts"]) == 1


def test_cue_text_is_trimmed_and_cut(tmp_path: Path) -> None:
    _job(tmp_path, "aaaaaaaaaaaa", score=_score(70, "C", [_window("  " + "x" * 300 + " ", "   ", tempo=None)]))
    cues = teacher_stats.collect(tmp_path, ENTRY)["takes"][0]["top_cues"]
    assert cues == ["x" * teacher_stats.CUE_MAX]


# ----- the route ----------------------------------------------------------------------------------------
@pytest.mark.usefixtures("authenv")
def test_route_answers_takes_for_a_catalog_entry(api: Api) -> None:  # AC-T8, private-default D3
    _job(api.app.queue.root, "aaaaaaaaaaaa", score=_score(64, "C", [_window("Keep your chest up")]))
    _job(api.app.queue.root, "bbbbbbbbbbbb", score=_score(91, "A", [_window("Not shared cue")]), shared=False)
    owner = sign_in(api)
    auth.identity(api.app).attach_entry(ENTRY, get(api, "api/auth/me", cookie=owner)[2]["user_id"], "")
    status, _, doc = get(api, f"api/teacher/{ENTRY}", cookie=owner)
    assert status == 200 and [t["score"] for t in doc["takes"]] == [64]  # the shared take only
    assert doc["cue_counts"] == [{"text": "Keep your chest up", "count": 1}] and doc["take_count"] == 1
    assert "aaaaaaaaaaaa" not in json.dumps(doc) and "Not shared cue" not in json.dumps(doc) and doc["takes"][0]["n"] == 1
    status, anon = api.json("GET", f"api/teacher/{ENTRY}")  # everyone else: the count of shared takes, no row
    assert status == 200 and anon["takes"] == [] and anon["cue_counts"] == [] and anon["class_table"] is None
    assert anon["take_count"] == 1 and "64" not in json.dumps(anon["takes"])


def test_route_empty_entry_is_200_with_no_takes(api: Api) -> None:
    status, doc = api.json("GET", "api/teacher/skel-only")
    assert status == 200 and doc.pop("attribution")["author"] is None  # an entry made signed out is unattributed
    assert doc.pop("class_table") is None  # not the owner: no class table (private-default D3)
    assert doc == {"entry": "skel-only", "takes": [], "cue_counts": [], "take_count": 0}


def test_route_unknown_or_malformed_entry_is_404_and_never_traverses(api: Api) -> None:  # AC-T9
    for bad in ("nope", "Bad_Id", "%2e%2e", "..%2f..%2fetc", "a%00b", "-x", "x" * 80):
        status, doc = api.json("GET", f"api/teacher/{bad}")
        assert status == 404, bad
        assert doc["message"] == "This movement is not in the catalog."
    assert api.json("GET", "api/teacher/lateral-raise/extra")[0] == 404
    assert api.json("GET", "api/teacher")[0] == 404


def test_route_methods(api: Api) -> None:
    assert api.json("POST", f"api/teacher/{ENTRY}", {})[0] == 405
    assert api.request("HEAD", f"api/teacher/{ENTRY}")[0] == 200


def test_a_private_take_is_left_out_of_the_public_page(api: Api) -> None:  # TICKET-106 R4
    root = api.app.queue.root
    _job(root, "aaaaaaaaaaaa", score=_score(64, "C", [_window("Keep your chest up")]))
    _job(root, "bbbbbbbbbbbb", score=_score(91, "A", [_window("Secret cue")]), private=True)
    assert [t["score"] for t in teacher_stats.collect(root, ENTRY)["takes"]] == [64]  # even shared, a private take stays out
    status, doc = api.json("GET", f"api/teacher/{ENTRY}")
    assert status == 200 and doc["take_count"] == 1
    assert "Secret cue" not in json.dumps(doc) and "bbbbbbbbbbbb" not in json.dumps(doc)
