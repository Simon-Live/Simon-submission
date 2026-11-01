"""TICKET-129: the independent review of release 17 (warm tracker): timeout restart, GPU memory for the cold repeat,
capability check, specific orphan reaping, fresh folders."""

from __future__ import annotations

import contextlib
import logging
import os
import signal
import socket
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from part7 import config, gpu_lock, p2_worker, runner
from part7.parts import p2_pose
from tests.test_chain import _ok_step
from tests.test_perf import _p2_env, _video
from tests.test_track_worker import _track_env

# ----- R1: a timed-out warm call stops the worker and frees the GPU lock -------------------------
HANG_WORKER = textwrap.dedent('''
    import fcntl, os, socket, sys, time
    args = sys.argv[1:]
    path = args[args.index("--socket") + 1]
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(path)
    srv.listen(4)
    while True:
        conn, _ = srv.accept()
        if conn.makefile("rb").readline():
            fd = os.open(os.environ["FAKE_GPU_LOCK"], os.O_CREAT | os.O_RDWR)
            fcntl.flock(fd, fcntl.LOCK_EX)  # Part 2's worker holds the host GPU lock for the call
            time.sleep(3600)  # and a disconnecting client does not stop the call
''')


def _hang_pool(tmp_path: Path, lock: Path) -> p2_worker.Pool:
    script = tmp_path / "hang_part2.py"
    script.write_text(HANG_WORKER, encoding="utf-8")
    return p2_worker.Pool(
        tmp_path / "pool", 1,
        lambda sock: [sys.executable, str(script), "serve-worker", "--mode", "track", "--socket", str(sock)],
        env={"FAKE_GPU_LOCK": str(lock)}, start_wait_s=20.0, lease_wait_s=0.0, label="p2_tracker", folder="p2-tracker",
        marker=p2_worker.TRACK_MARKER, gpu_lock_path=lock)


def _start_hanging_call(sock: Path, lock: Path) -> socket.socket:
    """Send a request the fake worker never answers, and wait until the worker holds the GPU lock."""
    conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    conn.connect(str(sock))
    conn.sendall(b'{"argv": ["track"], "cwd": "/", "env": {}}\n')
    deadline = time.monotonic() + 10
    while gpu_lock.wait_free(lock, 0.0) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not gpu_lock.wait_free(lock, 0.0), "the fake worker never took the lock"
    return conn


def _wait_started(pool: p2_worker.Pool) -> None:
    deadline = time.monotonic() + 20
    while pool.state() == "starting" and time.monotonic() < deadline:
        time.sleep(0.05)


def test_a_timed_out_lease_stops_the_worker_and_frees_the_gpu_lock(tmp_path: Path) -> None:
    lock = tmp_path / "gpu.lock"
    pool = _hang_pool(tmp_path, lock)
    pool.start()
    _wait_started(pool)
    try:
        proc = pool._slots[0].proc
        assert proc is not None
        with pool.lease() as sock:
            assert sock is not None
            conn = _start_hanging_call(sock, lock)
            pool.mark_restart(sock)  # the call timed out
        conn.close()
        assert proc.poll() is not None  # gone before the lease returned
        assert gpu_lock.wait_free(lock, 0.0)  # and the lock it held is free
        assert pool.state() == "released" and not pool._slots[0].sock.exists()
        with pool.lease() as sock:  # the next call starts a new worker
            assert sock is not None and pool._slots[0].proc is not proc
    finally:
        pool.stop()


def test_the_cold_retry_of_a_timed_out_call_starts_after_the_worker_is_gone(
    tmp_path: Path, state_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lock = tmp_path / "gpu.lock"
    lk, ran = _p2_env(state_dir, monkeypatch, {"--tracker", "api-sam31", "local-sam31", "--worker"})
    pool = _hang_pool(tmp_path, lock)
    p2_worker.start_track_pool(pool)
    _wait_started(pool)
    proc = pool._slots[0].proc
    seen: list[tuple[bool, bool]] = []
    conns: list[socket.socket] = []

    def fake_run(part: Any, argv: list[str], **kw: Any) -> runner.Step:
        ran.append([str(a) for a in argv])
        if "--worker" in argv:  # the warm call: the worker takes the lock and never answers
            conns.append(_start_hanging_call(Path(argv[argv.index("--worker") + 1]), lock))
            return runner.Step({**_ok_step(2), "exit": None, "timed_out": True})
        seen.append((proc is not None and proc.poll() is not None, gpu_lock.wait_free(lock, 0.0)))
        out = Path(argv[argv.index("--out") + 1])
        out.mkdir(parents=True, exist_ok=True)
        (out / "tracks.json").write_text("{}", encoding="utf-8")
        return _ok_step(2)

    monkeypatch.setattr(runner, "run", fake_run)
    try:
        step, tracks = p2_pose.track(_video(tmp_path), tmp_path / "w", lock=lk, state=state_dir, acquire_lock=False,
                                     tracker="local-sam31")
    finally:
        p2_worker.stop_track_pool()
        for c in conns:
            c.close()
    assert step["exit"] == 0 and tracks.is_file()
    assert seen == [(True, True)]  # at the cold run: the worker process had ended and the GPU lock was free


# ----- R2: no cold local-sam31 beside the warm worker --------------------------------------------
def test_a_busy_warm_worker_is_waited_for_not_bypassed(
    tmp_path: Path, state_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lk, ran, pool = _track_env(tmp_path, state_dir, monkeypatch)
    pool.start()
    started = threading.Event()

    def hold() -> None:
        with pool.lease() as sock:
            assert sock is not None
            started.set()
            time.sleep(0.6)

    holder = threading.Thread(target=hold)
    holder.start()
    assert started.wait(5)
    try:
        step = p2_pose._execute_warm_track(
            ["track", "--input", "x", "--out", str(tmp_path / "o"), "--tracker", "local-sam31"], "gpu",
            tmp_path / "w", "t.log", lk, lk.path("2"), False, None)
    finally:
        holder.join()
        p2_worker.stop_track_pool()
    assert step["exit"] == 0 and len(ran) == 1 and "--worker" in ran[0]  # waited, then used the warm worker


def _capture_admissions(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    seen: list[int] = []

    @contextlib.contextmanager
    def fake_acquire(**kw: Any):
        seen.append(kw["min_free_mib"])
        yield

    monkeypatch.setattr(p2_pose.gpu_lock, "acquire", fake_acquire)
    return seen


def test_the_cold_repeat_stops_the_tracker_first_and_needs_26_gib_free(
    tmp_path: Path, state_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert p2_pose.COLD_SAM31_MIN_FREE_MIB == 26624
    lk, _, pool = _track_env(tmp_path, state_dir, monkeypatch, script_exit=1)
    pool.start()
    held: list[bool] = []
    inner = runner.run

    def spy(part: Any, argv: list[str], **kw: Any) -> runner.Step:
        if "--worker" not in argv:
            held.append(p2_worker.track_holds_model())
        return inner(part, argv, **kw)

    seen = _capture_admissions(monkeypatch)
    monkeypatch.setattr(runner, "run", spy)
    try:
        step, tracks = p2_pose.track(_video(tmp_path), tmp_path / "w", lock=lk, state=state_dir, acquire_lock=True,
                                     tracker="local-sam31")
        assert step["exit"] == 0 and tracks.is_file()
        assert held == [False]  # the tracker worker was stopped before the cold run
        assert seen == [p2_pose.TRACK_MIN_FREE_MIB, 26624]
        assert p2_worker.track_state() == "released"
        with p2_worker.track_lease() as sock:
            assert sock is not None  # the next people step starts it again
    finally:
        p2_worker.stop_track_pool()


def test_a_cold_repeat_with_no_tracker_model_loaded_still_needs_26_gib(
    tmp_path: Path, state_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The warm worker does not answer: the call runs per-call, on the larger admission."""
    lk, ran, pool = _track_env(tmp_path, state_dir, monkeypatch)
    pool._health = lambda sock: False  # type: ignore[assignment]
    seen = _capture_admissions(monkeypatch)
    try:
        p2_pose.track(_video(tmp_path), tmp_path / "w", lock=lk, state=state_dir, acquire_lock=True, tracker="local-sam31")
    finally:
        p2_worker.stop_track_pool()
    assert seen[-1] == 26624 and "--worker" not in ran[-1]


def test_the_cold_admission_figure_can_be_overridden(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(p2_pose.COLD_MIN_FREE_ENV, raising=False)
    assert p2_pose.cold_min_free_mib() == 26624
    monkeypatch.setenv(p2_pose.COLD_MIN_FREE_ENV, "20480")
    assert p2_pose.cold_min_free_mib() == 20480
    monkeypatch.setenv(p2_pose.COLD_MIN_FREE_ENV, "lots")
    assert p2_pose.cold_min_free_mib() == 26624


# ----- R3: `serve-worker --mode` is the capability --------------------------------------------------
def _help(monkeypatch: pytest.MonkeyPatch, serve_worker: str) -> None:
    def help_text(part: Any, argv: list[str], clone: Any, lock: Any = None) -> str:
        if "serve-worker" in argv:
            return serve_worker
        return "--tracker local-sam31 api-sam31 --worker" if "track" in argv else ""

    monkeypatch.setattr(p2_pose.probe, "help_text", help_text)
    p2_pose.probe.clear_cache()


def _gpu_venv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    venv = tmp_path / "venv"
    (venv / "bin").mkdir(parents=True)
    (venv / "bin" / "python").write_text("", encoding="utf-8")
    monkeypatch.setattr(config, "part2_gpu_venv_path", lambda: venv)
    monkeypatch.setenv(p2_pose.TRACK_WORKER_ENV, "1")


def test_a_pin_with_track_worker_but_no_serve_worker_mode_gets_no_tracker_pool(
    tmp_path: Path, state_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lk, _ = _p2_env(state_dir, monkeypatch, set())
    clone = lk.path("2")
    _gpu_venv(tmp_path, monkeypatch)
    started: list[Any] = []
    monkeypatch.setattr(p2_worker, "start_track_pool", started.append)
    _help(monkeypatch, "usage: part2 serve-worker [--socket PATH]")  # an old pin: track --worker, no --mode
    assert p2_pose._offers_warm_track(lk, clone) is False
    assert p2_pose.start_track_worker(state_dir, lk) is False and started == []
    _help(monkeypatch, "usage: part2 serve-worker [--socket PATH] [--mode {run,track}]")
    assert p2_pose._offers_warm_track(lk, clone) is True
    assert p2_pose.start_track_worker(state_dir, lk) is True and len(started) == 1
    assert started[0]._marker == p2_worker.TRACK_MARKER == b"--mode\x00track"


# ----- R4: orphan reaping is specific to the worker kind --------------------------------------------
def _sleeper(*extra: str) -> subprocess.Popen[bytes]:
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)", "serve-worker", *extra],
                            start_new_session=True)


def _reap(proc: subprocess.Popen[bytes], tmp_path: Path, marker: bytes) -> bool:
    """True when `_reap_orphan` with `marker` ended `proc`."""
    pidfile = tmp_path / "w0.pid"
    pidfile.write_text(str(proc.pid), encoding="utf-8")
    p2_worker._reap_orphan(pidfile, marker)
    try:
        proc.wait(timeout=2)
        return True
    except subprocess.TimeoutExpired:
        return False


def _end(proc: subprocess.Popen[bytes]) -> None:
    with contextlib.suppress(OSError):
        os.killpg(proc.pid, signal.SIGKILL)
    proc.wait()


def test_a_stale_tracker_pidfile_does_not_kill_a_live_3d_worker(tmp_path: Path) -> None:
    three_d = _sleeper("--socket", "w0.sock")
    try:
        assert _reap(three_d, tmp_path, p2_worker.TRACK_MARKER) is False
        assert three_d.poll() is None
    finally:
        _end(three_d)


def test_a_stale_3d_pidfile_does_not_kill_a_live_tracker(tmp_path: Path) -> None:
    tracker = _sleeper("--mode", "track", "--socket", "w0.sock")
    try:
        assert _reap(tracker, tmp_path, b"serve-worker") is False
        assert tracker.poll() is None
        assert _reap(tracker, tmp_path, p2_worker.TRACK_MARKER) is True  # its own pool's reap does
    finally:
        _end(tracker)


def test_the_3d_pool_reaps_its_own_orphan(tmp_path: Path) -> None:
    three_d = _sleeper("--socket", "w0.sock")
    try:
        assert _reap(three_d, tmp_path, b"serve-worker") is True
    finally:
        _end(three_d)


# ----- R5: the local-open fallback gets a fresh folder too ----------------------------------------------
def test_the_local_open_fallback_after_a_failed_cold_retry_writes_to_a_fresh_folder(
    tmp_path: Path, state_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(p2_pose.TRACK_WORKER_ENV, "1")
    lk, ran, _ = _track_env(tmp_path, state_dir, monkeypatch)

    def fake_run(part: Any, argv: list[str], **kw: Any) -> runner.Step:
        ran.append([str(a) for a in argv])
        if argv[argv.index("--tracker") + 1] == "local-sam31":
            return {**_ok_step(2), "exit": 1}  # the warm call and the cold repeat both fail
        out = Path(argv[argv.index("--out") + 1])
        out.mkdir(parents=True, exist_ok=True)
        (out / "tracks.json").write_text("{}", encoding="utf-8")
        return _ok_step(2)

    monkeypatch.setattr(runner, "run", fake_run)
    try:
        step, tracks = p2_pose.track(_video(tmp_path), tmp_path / "w", lock=lk, state=state_dir, acquire_lock=False,
                                     tracker="local-sam31")
    finally:
        p2_worker.stop_track_pool()
    outs = [Path(a[a.index("--out") + 1]) for a in ran]
    assert [a[a.index("--tracker") + 1] for a in ran] == ["local-sam31", "local-sam31", "local-open"]
    assert len(set(outs)) == 3  # every attempt has its own folder
    assert step["exit"] == 0 and tracks == outs[2] / "tracks.json" and step["out_dir"] == str(outs[2])


# ----- R9: check-7's app runs the cold tracker unless asked ----------------------------------------------
def test_check7_app_env_is_cold_unless_asked() -> None:
    from part7 import check7

    assert check7.app_env({"SIMON7_P2_TRACK_WORKER": "1"})["SIMON7_P2_TRACK_WORKER"] == "0"  # staging's value does not leak
    assert check7.app_env({})["SIMON7_P2_TRACK_WORKER"] == "0"
    warm = check7.app_env({check7.CHECK_TRACK_WORKER_ENV: "1"})
    assert warm["SIMON7_P2_TRACK_WORKER"] == "1" and warm["SIMON7_PHRASING"] == check7.PHRASING


# ----- R2 decision: a cold local-sam31 repeat never waits for memory that will not free -------------------
def _cold_wait_run(tmp_path: Path, state_dir: Path, monkeypatch: pytest.MonkeyPatch, free_mib: int) -> tuple[Any, ...]:
    monkeypatch.setenv(p2_pose.TRACK_WORKER_ENV, "1")
    monkeypatch.setenv(p2_pose.COLD_WAIT_ENV, "0.3")
    lk, ran, _ = _track_env(tmp_path, state_dir, monkeypatch, script_exit=1)
    kw = {"memory_fn": lambda: free_mib, "poll_s": 0.05, "lock_path": tmp_path / "gpu.lock", "settle_s": 0.0}
    try:
        step, tracks = p2_pose.track(_video(tmp_path), tmp_path / "w", lock=lk, state=state_dir, acquire_lock=True,
                                     tracker="local-sam31", gpu_lock_kwargs=kw)
    finally:
        p2_worker.stop_track_pool()
    return step, tracks, ran


def test_the_cold_repeat_is_admitted_when_the_memory_frees_within_the_wait(
    tmp_path: Path, state_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    step, tracks, ran = _cold_wait_run(tmp_path, state_dir, monkeypatch, 30000)
    assert [a[a.index("--tracker") + 1] for a in ran] == ["local-sam31", "local-sam31"]  # warm, then the cold repeat
    assert step["exit"] == 0 and tracks.is_file()


def test_a_cold_repeat_that_is_not_admitted_in_time_is_skipped_for_local_open(
    tmp_path: Path, state_dir: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="part7"):
        step, tracks, ran = _cold_wait_run(tmp_path, state_dir, monkeypatch, 20000)
    assert [a[a.index("--tracker") + 1] for a in ran] == ["local-sam31", "local-open"]  # no cold local-sam31 run
    outs = [Path(a[a.index("--out") + 1]) for a in ran]
    assert outs[0] != outs[1] and step["exit"] == 0 and tracks == outs[1] / "tracks.json"
    text = " ".join(r.getMessage() for r in caplog.records)
    assert "ANOMALY p2_cold_sam31_skipped" in text and "need_mib=26624" in text and "free_mib=" in text
