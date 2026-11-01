"""TICKET-117/128: the warm SAM 3.1 tracker as Part 2's `serve-worker --mode track` (lifecycle, pin restart, fallback,
GPU lock, idle release, drain) and the fps settings."""

from __future__ import annotations

import fcntl
import importlib
import json
import logging
import sys
import textwrap
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from part7 import gpu_lock, heartbeat, p2_worker, runner
from part7.parts import p2_pose
from tests.test_chain import _ok_step
from tests.test_perf import _Proc, _p2_env, _video

# ----- the pool: on demand, idle release, drain --------------------------------------------------
def _tpool(tmp_path: Path, idle_s: float = 0.0, start_ok: bool = True, **kw: Any) -> tuple[p2_worker.Pool, list[_Proc]]:
    procs: list[_Proc] = []
    up: set[str] = set()

    def launcher(argv: list[str], log: Path, cwd: Any, env: Any) -> Any:
        if start_ok:
            up.add(argv[-1])
        procs.append(_Proc())
        return procs[-1]

    pool = p2_worker.Pool(
        tmp_path, 1, lambda sock: ["part2", "serve-worker", "--mode", "track", "--socket", str(sock)], launcher=launcher,
        health=lambda sock: str(sock) in up, start_wait_s=0.5, lease_wait_s=0.0, label="p2_tracker",
        folder="p2-tracker", on_demand=True, idle_release_s=idle_s, **kw,
    )
    return pool, procs


def test_the_tracker_loads_on_the_first_call_and_not_at_boot(tmp_path: Path) -> None:
    started: list[int] = []
    pool, procs = _tpool(tmp_path, on_started=lambda: started.append(1))
    pool.start()
    assert pool.state() == "released" and procs == []  # nothing resident until a people step asks
    with pool.lease() as sock:
        assert sock is not None and sock.name == "w0.sock"
    assert len(procs) == 1 and pool.state() == "idle" and started == [1]
    with pool.lease() as again:
        assert again == sock and len(procs) == 1  # warm: the same process
    pool.stop()


def test_an_idle_tracker_frees_its_gpu_memory_and_the_next_call_reloads(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    pool, procs = _tpool(tmp_path, idle_s=0.3)
    with caplog.at_level(logging.INFO, logger="part7"):
        pool.start()
        with pool.lease() as sock:
            assert sock is not None
        deadline = time.monotonic() + 5
        while pool.state() != "released" and time.monotonic() < deadline:
            time.sleep(0.05)
    assert pool.state() == "released" and procs[0].terminated
    assert any("p2_tracker_released" in r.getMessage() for r in caplog.records)
    with pool.lease() as sock:
        assert sock is not None and len(procs) == 2  # a new process loads the model again
    pool.stop()


def test_a_busy_tracker_is_not_released(tmp_path: Path) -> None:
    pool, procs = _tpool(tmp_path, idle_s=0.2)
    pool.start()
    with pool.lease() as sock:
        assert sock is not None
        time.sleep(0.8)  # longer than the idle limit, but the call is running
        assert not procs[0].terminated and pool.state() == "busy"
    pool.stop()


def test_a_tracker_that_never_starts_gives_none_and_an_anomaly(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    pool, _ = _tpool(tmp_path, start_ok=False)
    pool.start()
    with caplog.at_level(logging.WARNING, logger="part7"):
        with pool.lease() as sock:
            assert sock is None
    assert any("ANOMALY p2_tracker_unhealthy" in r.getMessage() for r in caplog.records)
    with pool.lease() as sock:  # down for RETRY_DOWN_S: no second load attempt per call
        assert sock is None
    pool.stop()


def test_stop_drains_the_tracker_and_removes_its_files(tmp_path: Path) -> None:
    pool, procs = _tpool(tmp_path, idle_s=60)
    pool.start()
    with pool.lease():
        pass
    pool.stop()
    assert procs[0].terminated and pool.state() == "off"
    assert not list((tmp_path / "p2-tracker").glob("*.sock")) and not list((tmp_path / "p2-tracker").glob("*.pid"))
    with pool.lease() as sock:
        assert sock is None  # a stopped pool lends nothing


def test_the_run_worker_pool_is_unchanged(tmp_path: Path) -> None:
    """The 3D worker still starts at boot and keeps its anomaly name."""
    procs: list[_Proc] = []
    up: set[str] = set()

    def launcher(argv: list[str], log: Path, cwd: Any, env: Any) -> Any:
        up.add(argv[-1])
        procs.append(_Proc())
        return procs[-1]

    pool = p2_worker.Pool(tmp_path, 1, lambda s: ["serve-worker", "--socket", str(s)], launcher=launcher,
                          health=lambda s: str(s) in up, start_wait_s=1.0)
    pool.start()
    time.sleep(0.4)
    assert pool.state() == "idle" and (tmp_path / "p2-workers").is_dir()
    pool.stop()


# ----- Part 7's use of it ------------------------------------------------------------------------
def _track_env(tmp_path: Path, state_dir: Path, monkeypatch: pytest.MonkeyPatch, script_exit: int = 0) -> tuple[Any, list[list[str]], p2_worker.Pool]:
    lk, ran = _p2_env(state_dir, monkeypatch, {"--tracker", "api-sam31", "local-sam31", "--worker"})
    out = tmp_path / "w" / "part2_track"
    out.mkdir(parents=True, exist_ok=True)

    def fake_run(part: Any, argv: list[str], **kw: Any) -> runner.Step:
        ran.append([str(a) for a in argv])
        code = script_exit if "--worker" in argv else 0
        if code == 0:
            target = Path(argv[argv.index("--out") + 1]) if "--out" in argv else out
            target.mkdir(parents=True, exist_ok=True)
            (target / "tracks.json").write_text("{}", encoding="utf-8")
        return {**_ok_step(2), "exit": code}

    monkeypatch.setattr(runner, "run", fake_run)
    pool, _ = _tpool(tmp_path / "pool")
    p2_worker.start_track_pool(pool)
    return lk, ran, pool


def test_a_local_sam31_track_goes_to_the_warm_worker(tmp_path: Path, state_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lk, ran, _ = _track_env(tmp_path, state_dir, monkeypatch)
    try:
        step, tracks = p2_pose.track(_video(tmp_path), tmp_path / "w", lock=lk, state=state_dir, acquire_lock=False)
    finally:
        p2_worker.stop_track_pool()
    assert step["exit"] == 0 and len(ran) == 1
    argv = ran[0]
    assert argv[argv.index("part2") + 1] == "track"  # `python -m part2 track ... --worker <sock>`
    assert argv[argv.index("--tracker") + 1] == "local-sam31"
    assert argv[argv.index("--worker") + 1].endswith("w0.sock")


def test_an_auto_tracker_is_local_sam31_while_the_warm_worker_runs(
    tmp_path: Path, state_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lk, ran, _ = _track_env(tmp_path, state_dir, monkeypatch)
    monkeypatch.setattr(p2_pose, "api_tracker_allowed", lambda *a, **k: True)  # the paid API would be next otherwise
    try:
        p2_pose.track(_video(tmp_path), tmp_path / "w", lock=lk, state=state_dir, acquire_lock=False)
    finally:
        p2_worker.stop_track_pool()
    assert ran[0][ran[0].index("--tracker") + 1] == "local-sam31"


def test_exit_1_from_the_worker_repeats_cold_in_a_fresh_out_dir_with_an_anomaly(
    tmp_path: Path, state_dir: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    lk, ran, _ = _track_env(tmp_path, state_dir, monkeypatch, script_exit=1)
    try:
        with caplog.at_level(logging.WARNING, logger="part7"):
            step, tracks = p2_pose.track(
                _video(tmp_path), tmp_path / "w", lock=lk, state=state_dir, acquire_lock=False, tracker="local-sam31")
    finally:
        p2_worker.stop_track_pool()
    assert step["exit"] == 0 and tracks.is_file()
    assert "--worker" in ran[0] and "--worker" not in ran[1]  # the second run is the cold `part2 track`
    assert ran[1][ran[1].index("--tracker") + 1] == "local-sam31"
    assert ran[1][ran[1].index("--out") + 1] != ran[0][ran[0].index("--out") + 1]
    assert any("ANOMALY p2_tracker_unhealthy" in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize("code", [4, 2])
def test_exit_4_and_2_from_the_worker_are_answers_not_failures(
    tmp_path: Path, state_dir: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, code: int
) -> None:
    lk, ran, _ = _track_env(tmp_path, state_dir, monkeypatch, script_exit=code)
    try:
        with caplog.at_level(logging.WARNING, logger="part7"):
            step = p2_pose._execute_warm_track(
                ["track", "--input", "x", "--out", str(tmp_path / "o"), "--tracker", "local-sam31"], "gpu",
                tmp_path / "w", "t.log", lk, lk.path("2"), False, None)
    finally:
        p2_worker.stop_track_pool()
    assert step["exit"] == code and len(ran) == 1  # no cold repeat
    assert not any("p2_tracker_unhealthy" in r.getMessage() for r in caplog.records)


def test_the_warm_call_and_a_worker_taking_the_host_gpu_lock_do_not_deadlock(
    tmp_path: Path, state_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Part 2's worker takes the host GPU lock per call (CONTRACT.md); Part 7 must not hold it across the call."""
    lk, _, _ = _track_env(tmp_path, state_dir, monkeypatch)
    lock_path = tmp_path / "gpu.lock"
    took: list[bool] = []

    def worker_like_run(part: Any, argv: list[str], **kw: Any) -> runner.Step:
        with lock_path.open("a+") as fd:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)  # the worker's own flock: fails if Part 7 still holds it
                got = gpu_lock._THREAD_LOCK.acquire(blocking=False)  # nor may Part 7 keep its in-process lock
                if got:
                    gpu_lock._THREAD_LOCK.release()
                took.append(got)
            except BlockingIOError:
                took.append(False)
        return {**_ok_step(2), "exit": 0}

    monkeypatch.setattr(runner, "run", worker_like_run)
    done = threading.Thread(target=lambda: p2_pose._execute_warm_track(
        ["track", "--input", "x", "--out", str(tmp_path / "o"), "--tracker", "local-sam31"], "gpu", tmp_path / "w",
        "t.log", lk, lk.path("2"), True,
        {"memory_fn": lambda: 20000, "timeout_s": 5, "lock_path": lock_path}), daemon=True)
    done.start()
    done.join(10)
    p2_worker.stop_track_pool()
    assert not done.is_alive() and took == [True]


def test_admission_refuses_a_warm_call_below_12288_mib_free(
    tmp_path: Path, state_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lk, ran, _ = _track_env(tmp_path, state_dir, monkeypatch)
    with pytest.raises(TimeoutError):
        p2_pose._execute_warm_track(
            ["track", "--input", "x", "--out", str(tmp_path / "o"), "--tracker", "local-sam31"], "gpu", tmp_path / "w",
            "t.log", lk, lk.path("2"), True,
            {"memory_fn": lambda: 12287, "timeout_s": 0.3, "poll_s": 0.05, "lock_path": tmp_path / "gpu.lock"})
    p2_worker.stop_track_pool()
    assert ran == []


def test_no_pool_means_the_per_call_tracker(tmp_path: Path, state_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lk, ran, _ = _track_env(tmp_path, state_dir, monkeypatch)
    p2_worker.stop_track_pool()
    p2_pose.track(_video(tmp_path), tmp_path / "w", lock=lk, state=state_dir, acquire_lock=False, tracker="local-sam31")
    assert "--worker" not in ran[0] and ran[0][ran[0].index("--tracker") + 1] == "local-sam31"


def test_an_unreachable_worker_runs_per_call(tmp_path: Path, state_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lk, ran, pool = _track_env(tmp_path, state_dir, monkeypatch)
    pool._health = lambda sock: False  # type: ignore[assignment]  # the worker never answers: no lease
    try:
        p2_pose.track(_video(tmp_path), tmp_path / "w", lock=lk, state=state_dir, acquire_lock=False, tracker="local-sam31")
    finally:
        p2_worker.stop_track_pool()
    assert ["--worker" in a for a in ran] == [False]


def test_failed_local_sam31_retries_local_open_only_with_the_worker_on(
    tmp_path: Path, state_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lk, ran = _p2_env(state_dir, monkeypatch, {"--tracker", "local-sam31"})
    p2_worker.stop_track_pool()
    for on in (False, True):
        ran.clear()
        monkeypatch.setenv(p2_pose.TRACK_WORKER_ENV, "1" if on else "0")
        p2_pose.track(_video(tmp_path), tmp_path / f"w{on}", lock=lk, state=state_dir, acquire_lock=False,
                      tracker="local-sam31")  # no tracks.json: the first run "failed"
        retry = ran[-1]
        if on:
            assert retry[retry.index("--tracker") + 1] == "local-open"
        else:
            assert "--tracker" not in retry  # Part 7's default-order retry, unchanged


def test_start_track_worker_needs_the_opt_in_the_gpu_venv_and_the_pin(
    tmp_path: Path, state_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lk, _ = _p2_env(state_dir, monkeypatch, {"--tracker", "local-sam31", "--worker"})
    venv = tmp_path / "venv"
    (venv / "bin").mkdir(parents=True)
    (venv / "bin" / "python").write_text("", encoding="utf-8")
    monkeypatch.setenv("SIMON7_PART2_GPU_VENV", str(venv))
    monkeypatch.delenv(p2_pose.TRACK_WORKER_ENV, raising=False)
    assert p2_pose.start_track_worker(state_dir, lk) is False and p2_worker.track_state() == "off"  # off by default
    monkeypatch.setenv(p2_pose.TRACK_WORKER_ENV, "1")
    assert p2_pose.start_track_worker(state_dir, lk, backend="cpu") is False
    monkeypatch.setattr(p2_pose.probe, "help_text", lambda *a, **k: "--tracker api-sam31")  # the pin lacks local-sam31
    assert p2_pose.start_track_worker(state_dir, lk) is False
    monkeypatch.setattr(p2_pose.probe, "help_text", lambda *a, **k: "track --tracker local-sam31")  # no --worker
    assert p2_pose.start_track_worker(state_dir, lk) is False
    monkeypatch.setattr(p2_pose.probe, "help_text", lambda *a, **k: "track --tracker local-sam31 --worker --mode")
    p2_pose.probe.clear_cache()  # the earlier answers (no --mode) are cached per command
    monkeypatch.setattr(p2_worker.Pool, "start", lambda self: None)  # no process in a unit test
    try:
        assert p2_pose.start_track_worker(state_dir, lk) is True
        pool = p2_worker._TRACK_POOL
        assert pool is not None and pool._version is not None
        assert pool._argv_for(Path("/s.sock"))[-6:] == ["part2", "serve-worker", "--mode", "track", "--socket", "/s.sock"]
        assert pool._on_demand is False and pool._idle_release_s == 0  # default: loads at boot, stays
        monkeypatch.setenv(p2_pose.TRACK_IDLE_ENV, "600")
        assert p2_pose.start_track_worker(state_dir, lk) is True
        pool = p2_worker._TRACK_POOL
        assert pool is not None and pool._on_demand is True and pool._idle_release_s == 600  # released between bursts
    finally:
        p2_worker.stop_track_pool()


def test_idle_release_setting_reads_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(p2_pose.TRACK_IDLE_ENV, raising=False)
    assert p2_pose.track_idle_s() == 0.0
    for raw, want in (("120", 120.0), ("0", 0.0), ("-5", 0.0), ("soon", 0.0), (" 30 ", 30.0)):
        monkeypatch.setenv(p2_pose.TRACK_IDLE_ENV, raw)
        assert p2_pose.track_idle_s() == want


def test_the_heartbeat_names_the_tracker_only_while_its_pool_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(p2_worker, "track_state", lambda: "off")
    assert heartbeat._tracker_note() == ""
    monkeypatch.setattr(p2_worker, "track_state", lambda: "idle")
    assert heartbeat._tracker_note() == " p2_tracker=idle"


# ----- fps settings ------------------------------------------------------------------------------
def test_fps_defaults_are_unchanged_and_the_environment_sets_them(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (p2_pose.FPS_ENV, p2_pose.TRACK_FPS_ENV):
        monkeypatch.delenv(name, raising=False)
    mod = importlib.reload(p2_pose)
    try:
        assert (mod.FPS, mod.TRACK_FPS) == (10, 10)  # nothing changes unless set
        monkeypatch.setenv("SIMON7_P2_FPS", "5")
        monkeypatch.setenv("SIMON7_P2_TRACK_FPS", "3")
        mod = importlib.reload(p2_pose)
        assert (mod.FPS, mod.TRACK_FPS) == (5, 3)
        monkeypatch.delenv("SIMON7_P2_TRACK_FPS")
        assert importlib.reload(p2_pose).TRACK_FPS == 5  # the track rate follows the 3D rate by default
    finally:
        monkeypatch.delenv("SIMON7_P2_FPS", raising=False)
        importlib.reload(p2_pose)


def test_track_asks_part2_for_the_track_fps(tmp_path: Path, state_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lk, ran = _p2_env(state_dir, monkeypatch, set())
    monkeypatch.setattr(p2_pose, "TRACK_FPS", 3)
    monkeypatch.setattr(p2_pose, "FPS", 5)
    (tmp_path / "w" / "part2_track").mkdir(parents=True)
    (tmp_path / "w" / "part2_track" / "tracks.json").write_text("{}", encoding="utf-8")
    p2_pose.track(_video(tmp_path), tmp_path / "w", lock=lk, state=state_dir, acquire_lock=False, tracker=None)
    assert ran[-1][ran[-1].index("--fps") + 1] == "3"
    monkeypatch.setenv(p2_pose.TRACKER_ENV, "local-open")
    p2_pose.track(_video(tmp_path), tmp_path / "w", lock=lk, state=state_dir, acquire_lock=False)
    assert ran[-1][ran[-1].index("--tracker") + 1] == "local-open"  # SIMON7_P2_TRACKER names it instead of "auto"


def test_tracks_resampled_from_3_to_5_fps() -> None:
    """People tracked at 3 fps give the 3D run a box in every 5 fps frame: interpolated in time, mask from the
    nearer tracked frame, nobody invented past a person's last tracked step (moalborati/simon#62, 91cbe07)."""
    from part7 import track_resample

    def person(x: int) -> dict[str, Any]:
        return {"id": 0, "bbox": [x, 100, 50, 200], "mask_rle": {"size": [480, 640], "counts": f"m{x}"}, "confidence": 0.9}

    doc = {"frames": [{"frame": n, "people": [person(100 + 30 * n)]} for n in range(4)],  # t = 0, 1/3, 2/3, 1 s
           "provenance": {"tracker": "local-sam31"}}
    out = track_resample.resample(doc, 3, 5, 1.0)
    assert [f["frame"] for f in out["frames"]] == list(range(7))  # 0..1.2 s at 5 fps
    xs = [f["people"][0]["bbox"][0] if f["people"] else None for f in out["frames"]]
    assert xs[:6] == [100, 118, 136, 154, 172, 190]  # x moves 90 px per second
    assert xs[6] == 190  # 0.2 s past the last tracked frame: held (within one tracked step)
    assert out["frames"][1]["people"][0]["mask_rle"]["counts"] == "m130"  # t 0.2 s: the frame at 1/3 s is nearer than 0 s
    assert out["provenance"]["tracker"] == "local-sam31" and out["provenance"]["resampled"]["to_fps"] == 5


def test_write_at_rate_uses_the_frame_times_and_drops_a_gap(tmp_path: Path) -> None:
    from part7 import track_resample

    doc = {"frames": [{"frame": 0, "people": [{"id": 1, "bbox": [0, 0, 10, 10], "confidence": 0.9}]},
                      {"frame": 1, "people": []},
                      {"frame": 2, "people": [{"id": 1, "bbox": [20, 0, 10, 10], "confidence": 0.9}]}]}
    src, dst = tmp_path / "tracks.json", tmp_path / "out.json"
    src.write_text(json.dumps(doc), encoding="utf-8")
    track_resample.write_at_rate(src, dst, 3, 10, 1.0, {0: 0.0, 1: 0.5, 2: 2.0})  # a 1.5 s hole between frames 0 and 2
    frames = json.loads(dst.read_text(encoding="utf-8"))["frames"]
    assert len(frames) == 12 and frames[0]["people"][0]["bbox"][0] == 0
    assert frames[5]["people"] == []  # 0.5 s is more than one tracked step (1/3 s) from either end of the hole


# ----- start robustness (both workers) -----------------------------------------------------------
class _SlowStart:
    """A worker that answers its health check `delay_s` after launch."""

    def __init__(self, tmp_path: Path, delay_s: float, load: float, wait_s: float = 0.4, exit_code: int | None = None) -> None:
        self.t0 = 0.0
        self.proc = _Proc()
        self.delay_s, self.exit_code = delay_s, exit_code

        def launcher(argv: list[str], log: Path, cwd: Any, env: Any) -> Any:
            self.t0 = time.monotonic()
            log.parent.mkdir(parents=True, exist_ok=True)
            log.write_text("loading weights\nstill loading\n", encoding="utf-8")
            if exit_code is not None:
                self.proc.dead = True
                self.proc.poll = lambda: exit_code  # type: ignore[method-assign]
            return self.proc

        self.pool = p2_worker.Pool(
            tmp_path, 1, lambda s: ["w", str(s)], launcher=launcher, start_wait_s=wait_s, load1=lambda: load,
            health=lambda s: time.monotonic() - self.t0 >= delay_s, label="p2_worker",
        )


def test_start_scale_follows_load_per_cpu_and_is_capped() -> None:
    assert p2_worker.start_scale(0.5, 8) == 1.0 and p2_worker.start_scale(16, 8) == 2.0
    assert p2_worker.start_scale(96, 8) == p2_worker.START_LOAD_SCALE_MAX


def test_a_slow_start_on_a_busy_host_is_waited_for(tmp_path: Path) -> None:
    import os

    busy = 4.0 * (os.cpu_count() or 1)  # load1 per CPU of 4: the 0.4 s base deadline becomes 1.6 s
    w = _SlowStart(tmp_path, delay_s=1.0, load=busy)
    assert w.pool._spawn(w.pool._slots[0]) is True and not w.proc.terminated


def test_a_start_that_runs_out_of_time_logs_why(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    w = _SlowStart(tmp_path, delay_s=5.0, load=0.0)
    with caplog.at_level(logging.WARNING, logger="part7"):
        w.pool._start_slot(w.pool._slots[0])
    assert w.proc.terminated
    text = " ".join(r.getMessage() for r in caplog.records)
    assert "ANOMALY p2_worker_unhealthy" in text and "no answer within" in text and "load1" in text
    assert "still loading" in text  # the last lines of the worker log


def test_a_worker_that_dies_while_loading_logs_its_exit(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    w = _SlowStart(tmp_path, delay_s=5.0, load=0.0, exit_code=-9)
    with caplog.at_level(logging.WARNING, logger="part7"):
        w.pool._start_slot(w.pool._slots[0])
    text = " ".join(r.getMessage() for r in caplog.records)
    assert "exited with signal 9" in text and "loading weights" in text


# ----- TICKET-125 review fixes -------------------------------------------------------------------
def test_a_warm_track_admission_checks_free_memory(tmp_path: Path, state_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import contextlib

    lk, _, _ = _track_env(tmp_path, state_dir, monkeypatch)
    seen: list[dict[str, Any]] = []

    @contextlib.contextmanager
    def fake_acquire(**kw: Any):
        seen.append(kw)
        yield

    monkeypatch.setattr(p2_pose.gpu_lock, "acquire", fake_acquire)
    try:
        p2_pose.track(_video(tmp_path), tmp_path / "w", lock=lk, state=state_dir, acquire_lock=True, tracker="local-sam31")
    finally:
        p2_worker.stop_track_pool()
    assert seen and seen[0]["min_free_mib"] == p2_pose.TRACK_MIN_FREE_MIB >= 12288


def test_a_timed_out_warm_call_repeats_per_call_in_a_fresh_out_dir(
    tmp_path: Path, state_dir: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The runner's timeout step has exit None (not 1): only `timed_out` sends the call to the cold retry (B1)."""
    lk, ran, _ = _track_env(tmp_path, state_dir, monkeypatch)
    real = runner.run

    def timing_out(part: Any, argv: list[str], **kw: Any) -> runner.Step:
        step = real(part, argv, **kw)
        return runner.Step({**step, "exit": None, "timed_out": True}) if "--worker" in argv else step

    monkeypatch.setattr(runner, "run", timing_out)
    try:
        with caplog.at_level(logging.WARNING, logger="part7"):
            step, tracks = p2_pose.track(
                _video(tmp_path), tmp_path / "w", lock=lk, state=state_dir, acquire_lock=False, tracker="local-sam31")
    finally:
        p2_worker.stop_track_pool()
    assert any("ANOMALY p2_tracker_unhealthy" in r.getMessage() for r in caplog.records)
    assert step["exit"] == 0 and len(ran) == 2
    first_out = ran[0][ran[0].index("--out") + 1]
    second_out = ran[1][ran[1].index("--out") + 1]
    assert "--worker" not in ran[1] and second_out != first_out
    assert tracks.parent == Path(second_out) and tracks.is_file()


def test_start_reaps_an_orphan_in_both_modes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for on_demand in (True, False):
        reaped: list[Path] = []
        monkeypatch.setattr(p2_worker, "_reap_orphan", lambda pidfile, marker=b"", r=reaped: r.append(pidfile))
        pool = p2_worker.Pool(tmp_path / str(on_demand), 1, lambda s: ["x", str(s)],
                              launcher=lambda *a: _Proc(), health=lambda s: True, on_demand=on_demand)
        pool.start()
        time.sleep(0.2)
        pool.stop()
        assert reaped and reaped[0].name == "w0.pid"


def test_stop_during_a_spawn_leaves_no_process_and_no_error(tmp_path: Path) -> None:
    gate = threading.Event()
    procs: list[_Proc] = []

    def slow_launcher(argv: list[str], log: Path, cwd: Any, env: Any) -> Any:
        gate.wait(5)
        procs.append(_Proc())
        return procs[-1]

    pool = p2_worker.Pool(tmp_path, 1, lambda s: ["serve-worker", str(s)], launcher=slow_launcher,
                          health=lambda s: False, start_wait_s=5.0)
    errors: list[BaseException] = []
    old_hook = threading.excepthook
    threading.excepthook = lambda args: errors.append(args.exc_value)
    try:
        pool.start()
        time.sleep(0.2)
        pool.stop()
        gate.set()
        time.sleep(0.5)
    finally:
        threading.excepthook = old_hook
    assert not errors and procs and all(p.dead for p in procs)


def test_bad_fps_settings_are_logged_and_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIMON7_P2_FPS", "ten")
    monkeypatch.setenv("SIMON7_P2_TRACK_FPS", "-2")
    try:
        mod = importlib.reload(p2_pose)
        assert (mod.FPS, mod.TRACK_FPS) == (10, 10)
    finally:
        monkeypatch.delenv("SIMON7_P2_FPS")
        monkeypatch.delenv("SIMON7_P2_TRACK_FPS")
        importlib.reload(p2_pose)


# ----- lifecycle with a fake `part2 serve-worker --mode track` (a real process, the real launcher) ----------------
FAKE_WORKER = textwrap.dedent('''
    import json, os, socket, sys
    args = sys.argv[1:]
    assert args[:3] == ["serve-worker", "--mode", "track"], args
    path = args[args.index("--socket") + 1]
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(path)
    srv.listen(4)
    print(f"part2 worker (track: local-sam31) listening on {path}", flush=True)
    while True:
        conn, _ = srv.accept()
        line = conn.makefile("rb").readline()
        if line:
            conn.sendall(b'{"keepalive": true}\\n{"exit": 0}\\n')
        conn.close()
''')


def _fake_pool(tmp_path: Path, version: Any = None) -> p2_worker.Pool:
    script = tmp_path / "fake_part2.py"
    script.write_text(FAKE_WORKER, encoding="utf-8")
    return p2_worker.Pool(
        tmp_path, 1, lambda sock: [sys.executable, str(script), "serve-worker", "--mode", "track", "--socket", str(sock)],
        start_wait_s=20.0, lease_wait_s=0.0, label="p2_tracker", folder="p2-tracker", version=version)


def _call(sock: Path) -> dict[str, Any]:
    import socket

    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as c:
        c.connect(str(sock))
        c.sendall(b'{"argv": ["track"], "cwd": "/", "env": {}}\n')
        return json.loads(c.makefile("rb").readlines()[-1])


def _settle(pool: p2_worker.Pool) -> None:
    deadline = time.monotonic() + 20
    while pool.state() == "starting" and time.monotonic() < deadline:
        time.sleep(0.05)


def test_a_fake_track_worker_starts_serves_a_call_and_drains(tmp_path: Path) -> None:
    pool = _fake_pool(tmp_path)
    pool.start()
    _settle(pool)
    try:
        assert pool.state() == "idle"
        proc = pool._slots[0].proc
        with pool.lease() as sock:
            assert sock is not None and _call(sock) == {"exit": 0}
        assert "listening on" in (tmp_path / "p2-tracker" / "w0.log").read_text(encoding="utf-8")
    finally:
        pool.stop()
    assert proc is not None and proc.poll() is not None and pool.state() == "off"
    assert not list((tmp_path / "p2-tracker").glob("*.sock")) and not list((tmp_path / "p2-tracker").glob("*.pid"))


def test_a_worker_that_removed_its_socket_is_restarted_on_the_next_lease(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    pool = _fake_pool(tmp_path)
    pool.start()
    _settle(pool)
    try:
        first = pool._slots[0].proc
        assert first is not None
        first.kill()
        first.wait()
        pool._slots[0].sock.unlink(missing_ok=True)  # a worker that stopped on a model failure removes its socket
        with caplog.at_level(logging.WARNING, logger="part7"):
            with pool.lease() as sock:
                assert sock is None  # this call runs cold
        assert any("ANOMALY p2_tracker_unhealthy" in r.getMessage() for r in caplog.records)
        _settle(pool)
        with pool.lease() as sock:
            assert sock is not None and _call(sock) == {"exit": 0}
        assert pool._slots[0].proc is not first
    finally:
        pool.stop()


def test_a_changed_part2_pin_restarts_the_worker_at_the_next_lease(tmp_path: Path) -> None:
    pin = ["a" * 40]
    pool = _fake_pool(tmp_path, version=lambda: pin[0])
    pool.start()
    _settle(pool)
    try:
        first = pool._slots[0].proc
        with pool.lease() as sock:
            assert sock is not None  # same pin: the same warm worker
        assert pool._slots[0].proc is first
        pin[0] = "b" * 40  # Part 2 was updated on disk
        with pool.lease() as sock:
            assert sock is None  # this call runs cold while the worker restarts
        _settle(pool)
        with pool.lease() as sock:
            assert sock is not None and _call(sock) == {"exit": 0}
        assert pool._slots[0].proc is not first and first is not None and first.poll() is not None
        assert pool._slots[0].version == "b" * 40
        with pool.lease() as sock:
            assert sock is not None  # and it is not restarted again
    finally:
        pool.stop()


def test_an_unreadable_pin_never_restarts_the_worker(tmp_path: Path) -> None:
    pin: list[str | None] = ["a" * 40]
    pool = _fake_pool(tmp_path, version=lambda: pin[0])
    pool.start()
    _settle(pool)
    try:
        first = pool._slots[0].proc
        pin[0] = None
        with pool.lease() as sock:
            assert sock is not None
        assert pool._slots[0].proc is first
    finally:
        pool.stop()
