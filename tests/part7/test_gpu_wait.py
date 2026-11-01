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
    assert fake.runs == [(p2_pose.API_TRACKER, False), ("local-open", True)]  # moalborati/simon#61: by name, not Part 2's order
    assert len(fake.admissions) == 1 and fake.admissions[0]["job_dir"] == job_dir
    # both attempts are kept, each with its own log (TICKET-067 review)
    assert step["exit"] == 0 and step["first_try"]["exit"] == 1
    assert fake.logs == [job_dir / "steps" / "part2_track.api.log", job_dir / "steps" / "part2_track_retry.log"]


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
    assert fake.runs == [(p2_pose.API_TRACKER, False), ("local-open", False)] and fake.admissions == []


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


# ----- TICKET-089: a long flock wait names the holder -----------------------------------------------------------


def test_lock_holder_reads_proc_locks_and_cmdline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lpath = tmp_path / "gpu.lock"
    lpath.write_text("")
    ino = lpath.stat().st_ino
    locks = f"1: POSIX  ADVISORY  WRITE 99 00:01:{ino} 0 EOF\n2: FLOCK  ADVISORY  WRITE 4242 08:01:{ino} 0 EOF\n"
    monkeypatch.setattr(gpu_lock, "_read_proc_locks", lambda: locks)
    monkeypatch.setattr(gpu_lock, "_read_cmdline", lambda pid, limit=120: f"python -m part7 check {pid}")
    assert gpu_lock.lock_holder_pid(lpath) == 4242
    assert gpu_lock.lock_holder(lpath).startswith("pid 4242 owner=")  # type: ignore[union-attr]
    assert gpu_lock.lock_holder(lpath).endswith("cmd=python -m part7 check 4242")  # type: ignore[union-attr]
    monkeypatch.setattr(gpu_lock, "_read_proc_locks", lambda: "2: FLOCK  ADVISORY  WRITE 4242 08:01:1 0 EOF\n")
    assert gpu_lock.lock_holder(lpath) is None


def test_cmdline_is_cut_at_120_chars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Path, "read_bytes", lambda self: b"a\0" + b"b" * 300)
    assert len(gpu_lock._read_cmdline(1)) == 120


def test_a_flock_wait_names_the_holder_once(job_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lpath = tmp_path / "gpu.lock"
    fd = os.open(str(lpath), os.O_CREAT | os.O_RDWR, 0o666)
    fcntl.flock(fd, fcntl.LOCK_EX)
    ino = lpath.stat().st_ino
    monkeypatch.setattr(gpu_lock, "HOLDER_LOG_S", 0.1)
    monkeypatch.setattr(gpu_lock, "_read_proc_locks", lambda: f"1: FLOCK  ADVISORY  WRITE 4242 08:01:{ino} 0 EOF\n")
    monkeypatch.setattr(gpu_lock, "_read_cmdline", lambda pid, limit=120: "python -m part7 check")
    threading.Timer(0.5, lambda: fcntl.flock(fd, fcntl.LOCK_UN)).start()
    try:
        with gpu_lock.acquire(lock_path=lpath, min_free_mib=0, poll_s=0.05, timeout_s=5.0, job_dir=job_dir):
            pass
    finally:
        time.sleep(0.05)
        os.close(fd)
    named = [x for x in _log(job_dir).splitlines() if "lock held by" in x]
    assert len(named) == 1 and named[0].endswith("cmd=python -m part7 check")
    assert "gpu wait: lock held by pid 4242 owner=" in named[0]


def test_no_holder_line_when_the_wait_is_short(job_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gpu_lock, "_read_proc_locks", lambda: pytest.fail("not read"))
    with gpu_lock.acquire(lock_path=tmp_path / "gpu.lock", min_free_mib=0, timeout_s=5.0, job_dir=job_dir):
        pass
    assert "lock held by" not in _log(job_dir)


def _fake_proc(root: Path, pid: int, *, cmd: str, cwd: Path, ppid: int, age_s: float, parent_cmd: str = "") -> None:
    """A fake /proc entry: cmdline, cwd symlink, stat with start time, and the parent's cmdline."""
    (root / "uptime").write_text("5000.00 4000.00\n")
    d = root / str(pid)
    d.mkdir(parents=True)
    (d / "cmdline").write_bytes(cmd.replace(" ", "\0").encode())
    (d / "cwd").symlink_to(cwd)
    start = int((5000 - age_s) * os.sysconf("SC_CLK_TCK"))
    fields = ["S", str(ppid)] + ["0"] * 17 + [str(start)] + ["0"] * 5
    (d / "stat").write_text(f"{pid} (python m) " + " ".join(fields) + "\n")
    if parent_cmd:
        p = root / str(ppid)
        p.mkdir(exist_ok=True)
        (p / "cmdline").write_bytes(parent_cmd.replace(" ", "\0").encode())


@pytest.fixture
def fake_proc(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "proc"
    root.mkdir()
    monkeypatch.setattr(gpu_lock, "PROC_ROOT", str(root))
    monkeypatch.setenv("SIMON7_STATE_DIR", str(tmp_path / "state7"))
    return root


def test_the_holder_line_is_self_sufficient(fake_proc: Path, tmp_path: Path) -> None:
    jobs = tmp_path / "state7" / "staging" / "jobs" / "abc"
    jobs.mkdir(parents=True)
    _fake_proc(fake_proc, 777, cmd="python -m part2 run --mode multi", cwd=jobs, ppid=os.getpid(),
               age_s=42.0, parent_cmd="python -m part7 serve " + "x" * 300)
    text = gpu_lock.describe_holder(777, tmp_path / "p2" / "gpu.lock")
    assert text.startswith("pid 777 owner=staging ")
    assert f"cwd={jobs} " in text and f"ppid={os.getpid()} " in text
    assert "elapsed=42.0 s" in text and text.endswith("cmd=python -m part2 run --mode multi")
    parent = text.split("parent=")[1].split(" elapsed=")[0]
    assert parent.startswith("python -m part7 serve") and len(parent) == 160 and "\n" not in text


def test_owner_guesses(fake_proc: Path, tmp_path: Path) -> None:
    state_job = tmp_path / "state7" / "staging" / "jobs" / "abc"
    lock = tmp_path / "simon-part-2" / "gpu.lock"
    # under the staging jobs dir but not this server's child: part7-other
    assert gpu_lock.holder_owner(str(state_job), "python x", 1, lock) == "part7-other"
    assert gpu_lock.holder_owner(str(tmp_path / "state7" / "check"), "python x", os.getpid(), lock) == "part7-other"
    assert gpu_lock.holder_owner(str(tmp_path / "simon-part-2" / "run"), "python x", 1, lock) == "part2"
    assert gpu_lock.holder_owner("/", "python -m part2 run", 1, lock) == "part2"
    assert gpu_lock.holder_owner("/", "sleep 5", 1, lock) == "other"
    assert gpu_lock.holder_owner("/", f"cat {state_job}/video.mp4", os.getpid(), lock) == "staging"


def test_an_exited_holder_still_gets_a_line(fake_proc: Path, tmp_path: Path) -> None:
    text = gpu_lock.describe_holder(31337, tmp_path / "gpu.lock")
    assert text == "pid 31337 owner=other cwd=? ppid=? parent=? elapsed=? s cmd="


def test_a_changed_holder_is_named_again_after_300_s(job_dir: Path, tmp_path: Path,
                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    lpath = tmp_path / "gpu.lock"
    fd = os.open(str(lpath), os.O_CREAT | os.O_RDWR, 0o666)
    fcntl.flock(fd, fcntl.LOCK_EX)
    pids = iter([111] * 3 + [222] * 1000)
    monkeypatch.setattr(gpu_lock, "HOLDER_LOG_S", 0.05)
    monkeypatch.setattr(gpu_lock, "HOLDER_RELOG_S", 0.3)
    monkeypatch.setattr(gpu_lock, "lock_holder_pid", lambda p: next(pids))
    monkeypatch.setattr(gpu_lock, "describe_holder", lambda pid, p: f"pid {pid}")
    threading.Timer(0.8, lambda: fcntl.flock(fd, fcntl.LOCK_UN)).start()
    try:
        with gpu_lock.acquire(lock_path=lpath, min_free_mib=0, poll_s=0.02, timeout_s=5.0, job_dir=job_dir):
            pass
    finally:
        time.sleep(0.05)
        os.close(fd)
    named = [x.split("lock held by ")[1] for x in _log(job_dir).splitlines() if "lock held by" in x]
    assert named == ["pid 111", "pid 222"]
