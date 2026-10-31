"""TICKET-067: the GPU admission wait is logged with its reason, and the api-sam31 track run skips admission."""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
from pathlib import Path
import threading
import time
from typing import Any, Iterator

import pytest

from part7 import gpu_lock, runner
from part7.parts import p2_pose


@pytest.fixture
def job_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(gpu_lock, "WAIT_LOG_S", 0.1)
    work = tmp_path / "jobs" / "abc123def456" / "work"
    work.mkdir(parents=True)
    return work


def _log(work: Path) -> str:
    path = work.parent / "steps" / "part7.log"
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def test_a_wait_for_free_memory_is_logged_with_the_reading(job_dir: Path, tmp_path: Path) -> None:
    readings = [4096, 4096, 14000]
    with gpu_lock.acquire(lock_path=tmp_path / "gpu.lock", poll_s=0.1, timeout_s=5.0, job_dir=job_dir,
                          memory_fn=lambda: readings.pop(0)):
        pass
    line = [x for x in _log(job_dir).splitlines() if "gpu wait" in x]
    assert len(line) == 1 and "job abc123def456: gpu wait 0." in line[0]
    assert line[0].endswith("s (reason: free 4096 MiB < 12288 MiB)")


def test_a_held_flock_is_named(job_dir: Path, tmp_path: Path) -> None:
    lpath = tmp_path / "gpu.lock"
    fd = os.open(str(lpath), os.O_CREAT | os.O_RDWR, 0o666)
    fcntl.flock(fd, fcntl.LOCK_EX)
    threading.Timer(0.3, lambda: fcntl.flock(fd, fcntl.LOCK_UN)).start()
    try:
        with gpu_lock.acquire(lock_path=lpath, min_free_mib=0, poll_s=0.05, timeout_s=5.0, job_dir=job_dir):
            pass
    finally:
        time.sleep(0.05)
        os.close(fd)
    assert "(reason: flock held)" in _log(job_dir)


def test_the_settle_gap_between_admissions_is_named(job_dir: Path, tmp_path: Path) -> None:
    kw: dict[str, Any] = {"lock_path": tmp_path / "gpu.lock", "min_free_mib": 0, "poll_s": 0.05, "timeout_s": 5.0,
                          "concurrent": True, "settle_s": 0.3}
    with gpu_lock.acquire(**kw):  # the first admission waits for nothing and logs nothing
        with gpu_lock.acquire(**kw, job_dir=job_dir):
            pass
    assert "(reason: settle)" in _log(job_dir)


def test_a_short_wait_is_not_logged(job_dir: Path, tmp_path: Path) -> None:
    with gpu_lock.acquire(lock_path=tmp_path / "gpu.lock", memory_fn=lambda: 20000, job_dir=job_dir):
        pass
    assert "gpu wait" not in _log(job_dir)


def test_a_timed_out_wait_is_logged_before_it_raises(job_dir: Path, tmp_path: Path) -> None:
    with pytest.raises(TimeoutError):
        with gpu_lock.acquire(lock_path=tmp_path / "gpu.lock", poll_s=0.05, timeout_s=0.3, job_dir=job_dir,
                              memory_fn=lambda: 1000):
            pass
    assert "(reason: free 1000 MiB < 12288 MiB, timed out)" in _log(job_dir)


# ----- p2_pose.track ---------------------------------------------------------------------------------------
class _Lock:
    def __init__(self, clone: Path) -> None:
        self.clone = clone

    def path(self, part: str) -> Path:
        return self.clone


class _Track:
    """Fake `runner.run` for `part2 track` and a recording `gpu_lock.acquire`."""

    def __init__(self, mp: pytest.MonkeyPatch, api_exit: int = 0) -> None:
        self.api_exit = api_exit
        self.runs: list[tuple[str | None, bool]] = []  # (tracker, admitted)
        self.logs: list[Path] = []  # step log of each run
        self.admitting = False
        self.admissions: list[dict[str, Any]] = []
        mp.setattr(runner, "run", self.run)
        mp.setattr(gpu_lock, "acquire", self.acquire)

    @contextlib.contextmanager
    def acquire(self, **kw: Any) -> Iterator[None]:
        self.admissions.append(kw)
        self.admitting = True
        try:
            yield
        finally:
            self.admitting = False

    def run(self, part: int, argv: list[str], **kw: Any) -> runner.Step:
        tracker = argv[argv.index("--tracker") + 1] if "--tracker" in argv else None
        self.runs.append((tracker, self.admitting))
        self.logs.append(kw["log_path"])
        code = self.api_exit if tracker == p2_pose.API_TRACKER else 0
        if code == 0:
            out = Path(argv[argv.index("--out") + 1])
            (out / "tracks.json").write_text(json.dumps({"frames": []}), encoding="utf-8")
        return runner.Step(part=2, argv=argv, exit=code, timed_out=False, duration_s=0.0, log="", stdout="")


def test_the_api_tracker_run_skips_gpu_admission(job_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _Track(monkeypatch)
    step, tracks = p2_pose.track(tmp_path / "clip.mp4", job_dir, lock=_Lock(tmp_path), tracker=p2_pose.API_TRACKER)
    assert step["exit"] == 0 and tracks.is_file()
    assert fake.runs == [(p2_pose.API_TRACKER, False)] and fake.admissions == []


def test_the_default_order_fallback_keeps_gpu_admission_and_names_the_job(
    job_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _Track(monkeypatch, api_exit=1)
    step, _ = p2_pose.track(tmp_path / "clip.mp4", job_dir, lock=_Lock(tmp_path), tracker=p2_pose.API_TRACKER)
    assert fake.runs == [(p2_pose.API_TRACKER, False), (None, True)]  # local SAM may run in Part 2's own order
    assert len(fake.admissions) == 1 and fake.admissions[0]["job_dir"] == job_dir
    # both attempts are kept, each with its own log (TICKET-067 review)
    assert step["exit"] == 0 and step["first_try"]["exit"] == 1
    assert fake.logs == [job_dir / "steps" / "part2_track.api.log", job_dir / "steps" / "part2_track.log"]


def test_a_successful_api_tracker_run_has_no_first_try_and_its_own_log(
    job_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _Track(monkeypatch)
    step, _ = p2_pose.track(tmp_path / "clip.mp4", job_dir, lock=_Lock(tmp_path), tracker=p2_pose.API_TRACKER)
    assert "first_try" not in step and fake.logs == [job_dir / "steps" / "part2_track.api.log"]


def test_a_local_tracker_by_name_keeps_gpu_admission(job_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _Track(monkeypatch)
    p2_pose.track(tmp_path / "clip.mp4", job_dir, lock=_Lock(tmp_path), tracker="local-sam31")
    assert fake.runs == [("local-sam31", True)]


def test_without_admission_a_caller_that_asked_for_none_gets_none(
    job_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _Track(monkeypatch, api_exit=1)
    p2_pose.track(tmp_path / "clip.mp4", job_dir, lock=_Lock(tmp_path), tracker=p2_pose.API_TRACKER, acquire_lock=False)
    assert fake.runs == [(p2_pose.API_TRACKER, False), (None, False)] and fake.admissions == []


# TICKET-069: nvidia-smi is found at the WSL2 path, and an unknown reading admits at once with a warning.


def test_resolver_prefers_path_then_the_wsl_location(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gpu_lock.shutil, "which", lambda name: "/opt/bin/nvidia-smi")
    assert gpu_lock.nvidia_smi_path() == "/opt/bin/nvidia-smi"
    monkeypatch.setattr(gpu_lock.shutil, "which", lambda name: None)
    monkeypatch.setattr(gpu_lock.os.path, "isfile", lambda p: p == gpu_lock.WSL_NVIDIA_SMI)
    monkeypatch.setattr(gpu_lock.os, "access", lambda p, mode: True)
    assert gpu_lock.nvidia_smi_path() == "/usr/lib/wsl/lib/nvidia-smi"
    monkeypatch.setattr(gpu_lock.os, "access", lambda p, mode: False)
    assert gpu_lock.nvidia_smi_path() is None
    monkeypatch.setattr(gpu_lock.os.path, "isfile", lambda p: False)
    assert gpu_lock.nvidia_smi_path() is None


def test_free_memory_runs_the_resolved_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[list[str]] = []

    def fake_run(cmd: list[str], **kw: Any) -> Any:
        seen.append(cmd)
        return type("R", (), {"returncode": 0, "stdout": "28000\n"})()

    monkeypatch.setattr(gpu_lock, "nvidia_smi_path", lambda: "/usr/lib/wsl/lib/nvidia-smi")
    monkeypatch.setattr(gpu_lock.subprocess, "run", fake_run)
    assert gpu_lock.free_gpu_memory_mib() == 28000
    assert seen[0][0] == "/usr/lib/wsl/lib/nvidia-smi"
    monkeypatch.setattr(gpu_lock, "nvidia_smi_path", lambda: None)
    assert gpu_lock.free_gpu_memory_mib() is None


def test_unknown_reading_admits_at_once_with_a_warning(job_dir: Path, tmp_path: Path,
                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gpu_lock, "_warned_unknown", False)
    slept: list[float] = []
    monkeypatch.setattr(gpu_lock.time, "sleep", lambda s: slept.append(s))
    t0 = time.monotonic()
    with gpu_lock.acquire(lock_path=tmp_path / "gpu.lock", poll_s=15.0, timeout_s=1800.0, job_dir=job_dir,
                          memory_fn=lambda: None):
        pass
    assert time.monotonic() - t0 < 1.0 and slept == []
    log = _log(job_dir)
    assert "WARNING" in log and gpu_lock.UNKNOWN_MESSAGE in log


def test_unknown_after_a_short_reading_also_admits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gpu_lock, "_warned_unknown", False)
    readings: list[int | None] = [4096, None]
    with gpu_lock.acquire(lock_path=tmp_path / "gpu.lock", poll_s=0.05, timeout_s=5.0,
                          memory_fn=lambda: readings.pop(0)):
        pass
    assert readings == []


def test_the_process_warning_is_logged_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gpu_lock, "_warned_unknown", False)
    lines: list[str] = []
    monkeypatch.setattr(gpu_lock.applog, "log", lambda msg, *a, **k: lines.append(msg))
    for _ in range(2):
        with gpu_lock.acquire(lock_path=tmp_path / "gpu.lock", memory_fn=lambda: None):
            pass
    assert lines == [gpu_lock.UNKNOWN_MESSAGE]


def test_a_short_real_reading_still_times_out(tmp_path: Path) -> None:
    with pytest.raises(TimeoutError):
        with gpu_lock.acquire(lock_path=tmp_path / "gpu.lock", poll_s=0.05, timeout_s=0.3,
                              memory_fn=lambda: 1000):
            pass
