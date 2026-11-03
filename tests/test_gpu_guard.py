"""GPU guard: warm Part 2 workers on staging only, and staging waits ahead of lane, dev, eval and avatar waits."""

from __future__ import annotations

import fcntl
import os
from pathlib import Path
import subprocess
import threading
import time
from typing import Any

import pytest

from part7 import gpu_lock
from part7.parts import p2_pose

REPO = Path(__file__).resolve().parents[1]


class _Lock:
    def path(self, part: str) -> Path:
        return Path("/nonexistent-part-2")


@pytest.fixture
def started(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[Any]:
    """A dev-like environment; returns the list of warm pools start_workers started."""
    for name in ("SIMON7_P2_WARM_WORKERS", "SIMON7_STAGING", "SIMON7_P2_TRACK_WORKER", "SIMON7_GPU_PRIORITY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SIMON7_STATE_DIR", str(tmp_path / "dev-state"))
    monkeypatch.setenv("SIMON7_STAGING_STATE_DIR", str(tmp_path / "staging-state"))
    monkeypatch.setattr(p2_pose, "has_worker", lambda *a, **k: True)
    seen: list[Any] = []
    monkeypatch.setattr(p2_pose.p2_worker, "start_pool", lambda pool: seen.append(pool))
    return seen


def test_a_dev_server_starts_no_warm_worker_by_default(started: list[Any], tmp_path: Path) -> None:
    state = tmp_path / "dev-state"
    assert p2_pose.start_workers(state, _Lock()) is False
    assert started == []
    assert p2_pose.warm_workers_note(state) == "p2 warm workers: 0 (dev default off)"


def test_staging_flag_starts_the_warm_worker(started: list[Any], monkeypatch: pytest.MonkeyPatch,
                                             tmp_path: Path) -> None:
    monkeypatch.setenv("SIMON7_STAGING", "1")
    assert p2_pose.start_workers(tmp_path / "dev-state", _Lock()) is True
    assert len(started) == 1 and len(started[0]._slots) == 1
    assert p2_pose.warm_workers_note(tmp_path) == "p2 warm workers: 1 (staging)"


def test_the_staging_state_folder_starts_the_warm_worker(started: list[Any], tmp_path: Path) -> None:
    state = tmp_path / "staging-state"
    assert p2_pose.start_workers(state, _Lock()) is True
    assert p2_pose.warm_workers_decision(state) == (1, "staging")


def test_an_explicit_value_overrides_both_ways(started: list[Any], monkeypatch: pytest.MonkeyPatch,
                                               tmp_path: Path) -> None:
    monkeypatch.setenv("SIMON7_P2_WARM_WORKERS", "1")
    assert p2_pose.start_workers(tmp_path / "dev-state", _Lock()) is True
    assert p2_pose.warm_workers_note(tmp_path / "dev-state") == "p2 warm workers: 1 (explicit)"
    monkeypatch.setenv("SIMON7_STAGING", "1")
    monkeypatch.setenv("SIMON7_P2_WARM_WORKERS", "0")
    assert p2_pose.start_workers(tmp_path / "staging-state", _Lock()) is False
    assert len(started) == 1
    assert p2_pose.warm_workers_note(tmp_path / "staging-state") == "p2 warm workers: 0 (explicit)"


def test_staging_env_marks_the_server_as_staging(tmp_path: Path) -> None:
    env = {"HOME": str(tmp_path), "PATH": os.environ.get("PATH", "/usr/bin:/bin")}
    out = subprocess.run(
        ["bash", "-c", 'source staging/env.sh; echo "$SIMON7_STAGING|$SIMON7_STAGING_STATE_DIR|${SIMON7_P2_WARM_WORKERS-unset}"'],
        cwd=REPO, env=env, capture_output=True, text=True, check=True).stdout.strip()
    assert out == f"1|{tmp_path}/.local/state/simon-part-7/staging|unset"


def test_default_priority_follows_the_server(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("SIMON7_GPU_PRIORITY", raising=False)
    monkeypatch.delenv("SIMON7_STAGING", raising=False)
    monkeypatch.setenv("SIMON7_STATE_DIR", str(tmp_path / "dev"))
    monkeypatch.setenv("SIMON7_STAGING_STATE_DIR", str(tmp_path / "staging"))
    assert gpu_lock.default_priority() == gpu_lock.LOW
    monkeypatch.setenv("SIMON7_STATE_DIR", str(tmp_path / "staging"))
    assert gpu_lock.default_priority() == gpu_lock.HIGH
    monkeypatch.setenv("SIMON7_GPU_PRIORITY", "low")
    assert gpu_lock.default_priority() == gpu_lock.LOW


def _waiter(lpath: Path, priority: str, order: list[str], name: str, hold_s: float = 0.05,
            timeout_s: float = 10.0, errors: list[str] | None = None) -> threading.Thread:
    def run() -> None:
        try:
            with gpu_lock.acquire(lock_path=lpath, min_free_mib=1, poll_s=0.01, timeout_s=timeout_s,
                                  memory_fn=lambda: 32768, priority=priority):
                order.append(f"{name}+")
                time.sleep(hold_s)
                order.append(f"{name}-")
        except TimeoutError:
            (errors if errors is not None else order).append(f"{name} timeout")
    t = threading.Thread(target=run)
    t.start()
    return t


def _hold(lpath: Path) -> int:
    fd = os.open(str(lpath), os.O_CREAT | os.O_RDWR, 0o666)
    fcntl.flock(fd, fcntl.LOCK_EX)
    return fd


def test_a_staging_waiter_is_admitted_before_an_earlier_eval_waiter(tmp_path: Path) -> None:
    lpath = tmp_path / "gpu.lock"
    holder = _hold(lpath)  # another process's job (Part 2 itself) holds the lock
    order: list[str] = []
    try:
        eval_t = _waiter(lpath, gpu_lock.LOW, order, "eval")
        time.sleep(0.3)  # the eval waiter queued first and sits in the flock wait
        staging_t = _waiter(lpath, gpu_lock.HIGH, order, "staging")
        time.sleep(0.3)
        assert order == []
        assert list(gpu_lock.waiters_dir(lpath).iterdir())  # the staging ticket is visible while it waits
    finally:
        fcntl.flock(holder, fcntl.LOCK_UN)
        os.close(holder)
    eval_t.join(10)
    staging_t.join(10)
    assert order == ["staging+", "staging-", "eval+", "eval-"]
    assert list(gpu_lock.waiters_dir(lpath).iterdir()) == []


def test_a_low_holder_is_never_preempted(tmp_path: Path) -> None:
    lpath = tmp_path / "gpu.lock"
    order: list[str] = []
    errors: list[str] = []
    eval_t = _waiter(lpath, gpu_lock.LOW, order, "eval", hold_s=0.8)
    time.sleep(0.2)
    assert order == ["eval+"]
    short = _waiter(lpath, gpu_lock.HIGH, order, "early", timeout_s=0.3, errors=errors)
    short.join(5)
    assert errors == ["early timeout"]  # the staging waiter waited and gave up; the holder kept running
    staging_t = _waiter(lpath, gpu_lock.HIGH, order, "staging")
    eval_t.join(5)
    staging_t.join(5)
    assert order == ["eval+", "eval-", "staging+", "staging-"]


def test_a_dead_waiters_ticket_is_ignored(tmp_path: Path) -> None:
    lpath = tmp_path / "gpu.lock"
    folder = gpu_lock.waiters_dir(lpath)
    folder.mkdir(parents=True)
    (folder / "999999999-1-1").write_text("", encoding="utf-8")
    assert gpu_lock.high_waiting(lpath) is False
    assert list(folder.iterdir()) == []
    with gpu_lock.acquire(lock_path=lpath, min_free_mib=0, timeout_s=1.0, priority=gpu_lock.LOW):
        pass
