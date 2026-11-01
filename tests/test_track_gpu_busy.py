"""TICKET-191: an auto track that cannot get GPU admission in time goes to api-sam31 or local-open."""

from __future__ import annotations

import contextlib
import logging
from pathlib import Path
from typing import Any

import pytest

from part7 import p2_worker
from part7.parts import p2_pose
from tests.test_perf import _video
from tests.test_track_worker import _track_env

SEEN: dict[str, list[Any]] = {}  # the last _admission's waits and floors, readable when the run raises


def _admission(monkeypatch: pytest.MonkeyPatch, grant: bool, refuse_all: bool = False) -> list[float]:
    waits: list[float] = []
    floors: list[int] = []
    SEEN.update(waits=waits, floors=floors)

    @contextlib.contextmanager
    def fake_acquire(**kw: Any):
        waits.append(kw["timeout_s"] if "timeout_s" in kw else -1.0)
        floors.append(kw.get("min_free_mib", -1))
        if refuse_all and not grant:
            raise TimeoutError("busy")
        if not grant and kw.get("min_free_mib") and len(waits) == 1:
            raise TimeoutError("busy")
        yield

    monkeypatch.setattr(p2_pose.gpu_lock, "acquire", fake_acquire)
    monkeypatch.setattr(p2_pose.gpu_lock, "free_gpu_memory_mib", lambda: 8884)
    return waits


def _run(tmp_path: Path, state_dir: Path, monkeypatch: pytest.MonkeyPatch, tracker: str = "auto",
         creds: bool = True, grant: bool = False, refuse_all: bool = False) -> tuple[list[list[str]], list[float]]:
    monkeypatch.setenv(p2_pose.TRACK_WAIT_ENV, "7")
    lk, ran, _ = _track_env(tmp_path, state_dir, monkeypatch)
    monkeypatch.setattr(p2_pose, "api_tracker_allowed", lambda *a, **k: creds)
    waits = _admission(monkeypatch, grant, refuse_all)
    try:
        p2_pose.track(_video(tmp_path), tmp_path / "w", lock=lk, state=state_dir, acquire_lock=True, tracker=tracker)
    finally:
        p2_worker.stop_track_pool()
    return ran, waits


def _trackers(ran: list[list[str]]) -> list[str]:
    return [a[a.index("--tracker") + 1] for a in ran if "--tracker" in a]


def test_no_admission_in_time_routes_to_api_sam31_and_logs(
    tmp_path: Path, state_dir: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING):
        ran, waits = _run(tmp_path, state_dir, monkeypatch)
    assert _trackers(ran) == ["api-sam31"] and waits[0] == 7.0
    assert any("ANOMALY p2_track_gpu_busy" in r.message and "routed=api-sam31" in r.message
               and "waited_s=7" in r.message and "free_mib=8884" in r.message for r in caplog.records)


def test_no_admission_and_no_credential_routes_to_local_open(
    tmp_path: Path, state_dir: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING):
        ran, _ = _run(tmp_path, state_dir, monkeypatch, creds=False)
    assert _trackers(ran) == ["local-open"]
    assert any("routed=local-open" in r.message for r in caplog.records)


def test_admission_in_time_keeps_the_warm_local_sam31(
    tmp_path: Path, state_dir: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING):
        ran, _ = _run(tmp_path, state_dir, monkeypatch, grant=True)
    assert _trackers(ran) == ["local-sam31"]
    assert not any("p2_track_gpu_busy" in r.message for r in caplog.records)


def test_an_explicit_tracker_env_is_untouched(tmp_path: Path, state_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(p2_pose.TRACKER_ENV, "local-sam31")
    ran, waits = _run(tmp_path, state_dir, monkeypatch, grant=True)
    assert _trackers(ran) == ["local-sam31"] and -1.0 in waits and 7.0 not in waits


def test_an_explicit_tracker_env_still_raises_when_busy(
    tmp_path: Path, state_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(p2_pose.TRACKER_ENV, "local-sam31")
    with pytest.raises(TimeoutError):
        _run(tmp_path, state_dir, monkeypatch)


def test_every_admission_refused_fails_busy_within_a_bounded_wait(
    tmp_path: Path, state_dir: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING), pytest.raises(TimeoutError, match="try again in a few minutes"):
        _run(tmp_path, state_dir, monkeypatch, creds=False, refuse_all=True)
    floors = SEEN["floors"]
    assert SEEN["waits"] == [7.0, 7.0]  # bounded: two waits of the configured length, nothing at 1800
    # local-sam31 then local-open, each bounded by the 7 s test wait, local-open with its own modest floor
    assert floors == [12288, p2_pose.LOCAL_OPEN_MIN_FREE_MIB]
    assert any("ANOMALY p2_track_gpu_busy_final" in r.message for r in caplog.records)
