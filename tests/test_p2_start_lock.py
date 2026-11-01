"""TICKET-188: a worker start does not count time spent behind another process's GPU flock (tracker and 3D pools)."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest

from part7 import gpu_lock, p2_worker
from tests.test_perf import _Proc

OTHER_PID = 2_999_999


def _pool(tmp_path: Path, answer_after_s: float, **kw: Any) -> p2_worker.Pool:
    began = time.monotonic()
    return p2_worker.Pool(
        tmp_path, 1, lambda s: ["serve-worker", "--socket", str(s)], launcher=lambda *a: _Proc(),
        health=lambda s: time.monotonic() - began >= answer_after_s, start_wait_s=0.4, load1=lambda: 0.0, **kw)


@pytest.fixture(autouse=True)
def _fast_poll(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(p2_worker, "LOCK_POLL_S", 0.05)


def _held_by_other(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gpu_lock, "lock_holder_pid", lambda path: OTHER_PID)


def _spawn(pool: p2_worker.Pool) -> bool:
    return pool._spawn(pool._slots[0])


@pytest.mark.parametrize("kw", [{}, {"label": "p2_tracker", "folder": "p2-tracker", "marker": p2_worker.TRACK_MARKER}])
def test_a_start_behind_a_held_gpu_lock_outlasts_its_deadline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                              caplog: pytest.LogCaptureFixture, kw: dict[str, Any]) -> None:
    _held_by_other(monkeypatch)
    pool = _pool(tmp_path, answer_after_s=1.0, **kw)  # the answer comes 2.5 times after the 0.4 s deadline
    with caplog.at_level("INFO"):
        assert _spawn(pool) is True
    waits = [r.getMessage() for r in caplog.records if "waiting for the GPU lock held by pid" in r.getMessage()]
    assert len(waits) == 1 and f"pid {OTHER_PID}" in waits[0]  # logged once


def test_without_a_lock_holder_the_deadline_still_applies(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gpu_lock, "lock_holder_pid", lambda path: None)
    pool = _pool(tmp_path, answer_after_s=5.0)
    assert _spawn(pool) is False and "no answer within" in pool._slots[0].why


def test_the_lock_wait_is_bounded_by_the_cap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _held_by_other(monkeypatch)
    monkeypatch.setenv(p2_worker.START_LOCK_CAP_ENV, "0.5")
    pool = _pool(tmp_path, answer_after_s=10.0)
    began = time.monotonic()
    assert _spawn(pool) is False and "no answer within" in pool._slots[0].why
    assert time.monotonic() - began < 3.0


def test_the_starting_worker_holding_the_lock_itself_gets_no_extension(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    proc = _Proc()
    proc.pid = 4242  # type: ignore[attr-defined]
    monkeypatch.setattr(gpu_lock, "lock_holder_pid", lambda path: 4242)
    pool = p2_worker.Pool(tmp_path, 1, lambda s: ["serve-worker"], launcher=lambda *a: proc,
                          health=lambda s: False, start_wait_s=0.4, load1=lambda: 0.0)
    assert _spawn(pool) is False and "no answer within" in pool._slots[0].why
