"""The Part 6 supervisor: restart, backoff, one notice, no restart while draining (self-healing.md AC-AH1 to AC-AH4)."""

from __future__ import annotations

import logging
from pathlib import Path
import subprocess
import sys
from typing import Any

import pytest

from part7 import ops_notice, part6_supervisor as sup, selfheal
from part7.parts import p6_catalog


class _Child:
    def __init__(self, heals: bool = True) -> None:
        self.alive, self.answers, self.heals, self.starts, self.stops = False, False, heals, 0, 0

    def running(self) -> bool:
        return self.alive

    def returncode(self) -> int | None:
        return None if self.alive else -9

    def health(self) -> dict[str, Any] | None:
        return {"ok": True} if self.alive and self.answers else None

    def stop(self) -> None:
        self.stops += 1

    def start(self) -> int:
        self.starts += 1
        self.alive, self.answers = self.heals, self.heals
        return 1


class _Clock:
    now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def notices(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    sent: list[str] = []
    monkeypatch.setattr(ops_notice, "send", lambda subject, body, state: sent.append(subject) or True)
    return sent


def _make(tmp_path: Path, child: _Child, **kw: Any) -> tuple[sup.Part6Supervisor, _Clock]:
    selfheal.configure(tmp_path)
    clock = _Clock()
    return sup.Part6Supervisor(child, tmp_path, clock=clock, interval=999, **kw), clock


def test_a_dead_child_is_restarted_logged_and_visible(tmp_path: Path, caplog: pytest.LogCaptureFixture, notices: list[str]) -> None:  # AC-AH1
    child = _Child()
    s, _ = _make(tmp_path, child)
    with caplog.at_level(logging.INFO, logger="part7"):
        s.tick()
    assert child.starts == 1 and child.stops == 1 and notices == []
    text = caplog.text
    assert "ANOMALY part6_down" in text and "exited with code -9" in text and "SELFHEAL action=part6_restart" in text
    doc = selfheal.status(tmp_path)
    assert doc["actions"][-1]["action"] == "part6_restart" and "answering" in doc["actions"][-1]["detail"]
    assert "part6_supervisor" in doc["open"]


def test_a_healthy_child_is_left_alone(tmp_path: Path, notices: list[str]) -> None:
    child = _Child()
    child.alive = child.answers = True
    s, _ = _make(tmp_path, child)
    s.tick()
    assert child.starts == 0


def test_a_hung_child_is_restarted_only_after_the_limit(tmp_path: Path, notices: list[str]) -> None:
    child = _Child()
    child.alive = True
    s, clock = _make(tmp_path, child)
    s.tick()
    clock.now += sup.HUNG_S - 1
    s.tick()
    assert child.starts == 0
    clock.now += 2
    s.tick()
    assert child.starts == 1


def test_the_backoff_grows_and_caps(tmp_path: Path, notices: list[str]) -> None:  # AC-AH2
    child = _Child(heals=False)
    s, clock = _make(tmp_path, child)
    gaps = []
    for _ in range(8):
        s.tick()
        gaps.append(s._next_at - clock.now)
        clock.now = s._next_at
    assert gaps == [2, 4, 8, 16, 32, 60, 60, 60]
    assert child.starts == 8
    s.tick()  # the wait has not passed for this attempt's own backoff until the clock moves
    assert child.starts == 9
    start = child.starts
    clock.now += 1
    s.tick()
    assert child.starts == start  # inside the backoff nothing is started


def test_repeated_failure_raises_one_notice(tmp_path: Path, notices: list[str]) -> None:  # AC-AH3
    child = _Child(heals=False)
    s, clock = _make(tmp_path, child)
    for _ in range(6):
        s.tick()
        clock.now = s._next_at
    assert notices == ["The catalog keeps failing"]


def test_a_stable_child_clears_the_count(tmp_path: Path, notices: list[str]) -> None:  # AC-AH3
    child = _Child()
    s, clock = _make(tmp_path, child)
    s.tick()
    assert s.restarts == 1
    clock.now += sup.STABLE_S + 1
    s.tick()
    assert s.restarts == 0 and notices == [] and "part6_supervisor" not in selfheal.status(tmp_path)["open"]


def test_nothing_is_restarted_while_draining(tmp_path: Path, notices: list[str]) -> None:  # AC-AH4
    child = _Child()
    s, _ = _make(tmp_path, child, paused=lambda: True)
    s.tick()
    assert child.starts == 0


def test_the_real_child_accessors_follow_its_process() -> None:
    child = p6_catalog.Child(catalog_dir="/nonexistent/x", state="/nonexistent", port=1)
    assert child.running() is False and child.returncode() is None
    child._proc = subprocess.Popen([sys.executable, "-c", "raise SystemExit(7)"])
    child._proc.wait()
    assert child.running() is False and child.returncode() == 7
    child._proc = None
