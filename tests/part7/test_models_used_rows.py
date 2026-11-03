"""Models-used rows for the second opinion, narration, history and avatar (TICKET-262 AC-1)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from part7 import history_report, history_store, models_used, narration_api
from test_models_used import ENTRY, follower, job, rows, trainer, write

JOB = "bbbbbbbbbbb1"
USER = "u" + "1" * 15


def setup(tmp_path: Path, **analysis: Any) -> Path:
    trainer(tmp_path, "")
    d = job(tmp_path, JOB)
    follower(d)
    if analysis:
        path = d / "work" / "follower" / "analysis.json"
        write(path, {**json.loads(path.read_text()), **analysis})
    return d


def collect(tmp_path: Path, **kw: Any) -> dict[str, dict[str, Any]]:
    return rows(models_used.collect(tmp_path, JOB, **kw))


def narration_doc(catalog: Path, source: str = narration_api.MODEL, cues: Any = None) -> None:
    cues = [{"index": 0, "text": "knees out", "clip": {"file": "cue-0.wav", "ms": 900}}, {"index": 1, "text": "chest up"}] \
        if cues is None else cues
    write(catalog / ENTRY / "narration.json", {"source": source, "cues": cues})


# ----- the second opinion ----------------------------------------------------------------------------------------
def test_second_opinion_ok_is_live_and_counts_what_it_returned(tmp_path: Path) -> None:
    setup(tmp_path, second_opinion={"status": "ok", "model": "muse-spark-1.3", "verdicts": [{}, {}], "observations": [{}],
                                    "usage": {"cached_tokens": 120}})
    r = collect(tmp_path)["spark-opinion"]
    assert (r["status"], r["model"], r["clip"]) == ("live", "Muse Spark", "you")
    assert (r["facts"]["verdicts"], r["facts"]["observations"], r["facts"]["cached_tokens"]) == (2, 1, 120)


def test_second_opinion_fallback_and_skipped_are_never_live(tmp_path: Path) -> None:
    setup(tmp_path, second_opinion={"status": "fallback", "reason": "unreadable answer"})
    r = collect(tmp_path)["spark-opinion"]
    assert (r["status"], r["facts"]["ran"], r["facts"]["reason"]) == ("fallback", "measured_faults", "unreadable answer")
    setup(tmp_path, second_opinion={"status": "skipped", "reason": "no Meta key on this server"})
    assert collect(tmp_path)["spark-opinion"]["status"] == "not_run"


@pytest.mark.parametrize("block", [None, "ok", {"status": "weird"}, {}, {"reason": "x" * 200, "status": "skipped"}])
def test_second_opinion_missing_or_unreadable_is_not_run(tmp_path: Path, block: Any) -> None:
    setup(tmp_path, **({"second_opinion": block} if block is not None else {}))
    r = collect(tmp_path)["spark-opinion"]
    assert r["status"] == "not_run" and "x" * 100 not in json.dumps(r)


# ----- narration -------------------------------------------------------------------------------------------------
def test_narration_live_only_from_a_file_the_transcribe_call_wrote(tmp_path: Path) -> None:
    setup(tmp_path)
    catalog = tmp_path / "catalog"
    narration_doc(catalog)
    r = collect(tmp_path, catalog_dir=catalog)["narration"]
    assert (r["status"], r["model"], r["clip"], r["facts"]["cues"], r["facts"]["clips"]) == \
        ("live", "Muse Voice Transcribe", "trainer", 2, 1)


def test_narration_missing_or_foreign_is_not_run(tmp_path: Path) -> None:  # AC-2 negative
    setup(tmp_path)
    catalog = tmp_path / "catalog"
    assert collect(tmp_path)["narration"]["status"] == "not_run"  # no catalog given
    assert collect(tmp_path, catalog_dir=catalog)["narration"]["status"] == "not_run"  # no file
    narration_doc(catalog, source="someone-else")
    assert collect(tmp_path, catalog_dir=catalog)["narration"]["status"] == "not_run"
    narration_doc(catalog, cues=[])
    assert collect(tmp_path, catalog_dir=catalog)["narration"]["status"] == "not_run"
    (catalog / ENTRY / "narration.json").write_text("{broken")
    assert collect(tmp_path, catalog_dir=catalog)["narration"]["status"] == "not_run"


# ----- history and avatar: the owner only ------------------------------------------------------------------------
def history_report_file(state: Path, status: str = "ok", takes: Any = None, **extra: Any) -> None:
    doc = {"format": history_report.FORMAT, "status": status, "reason": "", "created_at": "2026-11-01T10:00:00Z",
           "takes": [{"job_id": JOB}] if takes is None else takes, "usage": {"input_tokens": 9000, "cached_tokens": 4000},
           "sent": {"clip_takes": [1, 2]}, **extra}
    write(history_store.reports_dir(state, USER, ENTRY) / "r1.json", doc)


def avatar_card(state: Path, kind: str = "image", status: str = "ready", model_id: str = "a" * 32) -> None:
    write(state / "models" / model_id / "status.json", {"id": model_id, "status": status, "owner": USER, "created_at": "x"})
    write(state / "models" / model_id / "character.json",
          {"kind": "generated", "generated": {"schema": "simon.avatar.v1", "kind": kind}})


def test_history_row_live_from_the_owners_report_with_cache_hit_tokens(tmp_path: Path) -> None:
    setup(tmp_path)
    state = tmp_path / "state"
    history_report_file(state)
    r = collect(tmp_path, state=state, owner=USER)["spark-history"]
    assert (r["status"], r["clip"], r["facts"]["videos"], r["facts"]["cached_tokens"], r["facts"]["input_tokens"]) == \
        ("live", "account", 2, 4000, 9000)


def test_history_row_not_live_without_a_report_that_compared_this_take(tmp_path: Path) -> None:
    setup(tmp_path)
    state = tmp_path / "state"
    assert collect(tmp_path, state=state, owner=USER)["spark-history"]["status"] == "not_run"
    history_report_file(state, takes=[{"job_id": "ccccccccccc1"}])
    assert collect(tmp_path, state=state, owner=USER)["spark-history"]["status"] == "not_run"
    history_report_file(state, status="fallback", reason="the model step is not available")
    r = collect(tmp_path, state=state, owner=USER)["spark-history"]
    assert (r["status"], r["facts"]["ran"]) == ("fallback", "fact_table")


def test_avatar_row_from_generated_models_only(tmp_path: Path) -> None:
    setup(tmp_path)
    state = tmp_path / "state"
    assert collect(tmp_path, state=state, owner=USER)["avatar"]["status"] == "not_run"
    avatar_card(state, status="failed")
    assert collect(tmp_path, state=state, owner=USER)["avatar"]["status"] == "not_run"
    avatar_card(state, kind="autorig", status="ready", model_id="b" * 32)
    r = collect(tmp_path, state=state, owner=USER)["avatar"]
    assert (r["status"], r["model"], r["facts"]["avatars"], r["facts"]["from_mesh"]) == ("live", "SAM 3D Body", 1, 1)


def test_account_rows_never_appear_for_anyone_but_the_owner(tmp_path: Path) -> None:
    setup(tmp_path)
    state = tmp_path / "state"
    history_report_file(state)
    avatar_card(state)
    assert not {"spark-history", "avatar"} & set(collect(tmp_path, state=state))  # signed out or not the owner
    assert {"spark-history", "avatar"} <= set(collect(tmp_path, state=state, owner=USER))
    assert "estimated_usd" not in json.dumps(models_used.collect(tmp_path, JOB, state=state, owner=USER))


def test_rows_come_in_the_listed_order(tmp_path: Path) -> None:
    setup(tmp_path)
    doc = models_used.collect(tmp_path, JOB, catalog_dir=tmp_path / "c", state=tmp_path / "s", owner=USER)
    ids = [m["id"] for m in doc["models"]]
    assert ids == [i for i in models_used.ORDER if i in ids] and len(ids) == len(models_used.ORDER)


class Handler:
    def __init__(self, state: Path) -> None:
        self.app = type("A", (), {"state": state})()


def test_viewer_owns_needs_a_signed_in_owner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from part7 import auth

    h = Handler(tmp_path)
    monkeypatch.setattr(history_store, "owner_of", lambda state, job_id: USER)
    for viewer in (None, "u" + "2" * 15, "not a user"):
        monkeypatch.setattr(auth, "current_user", lambda handler, v=viewer: v)
        assert models_used._viewer_owns(h, JOB) is None
    monkeypatch.setattr(auth, "current_user", lambda handler: USER)
    assert models_used._viewer_owns(h, JOB) == USER
