"""Stage timings of a model import (TICKET-363, docs/specs/model-import.md AC-T1 to AC-T3), with a fake clock."""

from __future__ import annotations

import contextlib
import json
import logging
from pathlib import Path

import pytest

from part7 import avatar_jobs, import_timings, model_convert, model_import, model_store

HERE = Path(__file__).resolve().parent


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    fake = Clock()
    monkeypatch.setattr(import_timings, "clock", fake)
    return fake


def _status(folder: Path) -> dict:
    return json.loads((folder / "status.json").read_text(encoding="utf-8"))


def _part2_stubs(monkeypatch: pytest.MonkeyPatch, wait, run) -> None:
    monkeypatch.setattr(avatar_jobs, "_wait_for_card", wait)
    monkeypatch.setattr(avatar_jobs.gpu_lock, "acquire", lambda **k: contextlib.nullcontext())
    monkeypatch.setattr(avatar_jobs, "_run_part2", run)
    monkeypatch.setattr(avatar_jobs, "_environment", lambda *a, **k: {})
    monkeypatch.setattr(avatar_jobs, "_scratch", lambda *a, **k: None)


def test_a_stage_logs_one_line_and_writes_its_seconds(tmp_path: Path, clock: Clock, caplog: pytest.LogCaptureFixture) -> None:
    mid, folder = model_store.create(tmp_path, "o")
    began = import_timings.start()
    clock.now += 12.5
    with caplog.at_level(logging.INFO, logger="part7"):
        assert import_timings.done(folder, "autorig", began) == 12.5
    lines = [r.getMessage() for r in caplog.records if "took" in r.getMessage()]
    assert lines == [f"model {mid}: autorig took 12.5 s"]  # AC-T1
    assert _status(folder)["timings"] == {"autorig": 12.5}
    clock.now += 2
    import_timings.done(folder, "avatar", began)  # a second stage adds to the first
    assert _status(folder)["timings"] == {"autorig": 12.5, "avatar": 14.5}


def test_no_start_mark_writes_nothing(tmp_path: Path) -> None:
    _, folder = model_store.create(tmp_path, "o")
    assert import_timings.done(folder, "conversion", None) is None
    assert "timings" not in _status(folder)


def test_finalize_copies_the_timings_into_character_json(tmp_path: Path, clock: Clock) -> None:
    _, folder = model_store.create(tmp_path, "o")
    began = import_timings.start()
    clock.now += 3
    import_timings.done(folder, "upload", began)
    glb = HERE / "fixtures" / "models" / "riggedfigure.glb"
    assert model_import.finalize(folder, glb, {}) is not None
    saved = json.loads((folder / "character.json").read_text(encoding="utf-8"))
    assert saved["timings"] == {"upload": 3.0}  # AC-T2
    assert "route" not in saved


def test_the_converter_times_submit_to_result(tmp_path: Path, clock: Clock, caplog: pytest.LogCaptureFixture) -> None:
    mid, folder = model_store.create(tmp_path, "o")
    model_convert._started[mid] = import_timings.start()
    clock.now += 40
    with caplog.at_level(logging.INFO, logger="part7"):
        model_convert._finish(tmp_path / "models-spool", {"id": mid, "ok": False, "message": "no", "reason": "x"})
    assert _status(folder)["timings"] == {"conversion": 40.0}
    assert f"model {mid}: conversion took 40 s" in caplog.text
    assert mid not in model_convert._started


@pytest.mark.parametrize(("kind", "stage"), [("autorig", "autorig"), ("image3d", "image3d"), ("image", "avatar")])
def test_part2_runs_are_timed_by_kind_without_the_lock_wait(tmp_path: Path, clock: Clock, monkeypatch: pytest.MonkeyPatch,
                                                            kind: str, stage: str) -> None:
    _, folder = model_store.create(tmp_path, "o")
    _part2_stubs(monkeypatch, lambda *a, **k: (setattr(clock, "now", clock.now + 500), True)[1],
                 lambda *a, **k: (setattr(clock, "now", clock.now + 7), 0)[1])
    assert avatar_jobs._attempt(folder, kind, [], tmp_path, tmp_path) == (0, False)
    assert _status(folder)["timings"] == {stage: 7.0}  # AC-T3: the 500 s wait for the card is not in it


def test_a_failed_part2_run_writes_no_timing(tmp_path: Path, clock: Clock, monkeypatch: pytest.MonkeyPatch) -> None:
    _, folder = model_store.create(tmp_path, "o")
    _part2_stubs(monkeypatch, lambda *a, **k: True, lambda *a, **k: 2)
    assert avatar_jobs._attempt(folder, "autorig", [], tmp_path, tmp_path) == (2, False)
    assert "timings" not in _status(folder)
