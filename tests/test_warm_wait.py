"""TICKET-320: a take that cannot get the GPU waits for the warm Part 2 worker of its stage, bounded, and a warm tracker
is never stopped for a cold call that cannot fit beside the resident workers (docs/specs/parts-harness.md "GPU")."""

from __future__ import annotations

import contextlib
import logging
from pathlib import Path
import threading
import time
from typing import Any, Iterator

import pytest

from part7 import gpu_lock, job_gpu, p2_worker, queue_eta, selfheal, warm_wait
from part7.parts import p2_pose
from tests.part7.test_gpu_visible import held_by_child
from tests.test_perf import _Proc, _video
from tests.test_track_worker import _track_env

JOB = "abcdefabcdef"


def _trackers(ran: list[list[str]]) -> list[str]:
    return [a[a.index("--tracker") + 1] for a in ran if "--tracker" in a]


def _msgs(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records]


@pytest.fixture(autouse=True)
def _loads_settle() -> Iterator[None]:
    """A worker start a test left running (a stopped pool's spawn ends within a poll) is counted in every pool's load
    window (TICKET-320), so each test starts and ends with no load in flight."""
    def settle() -> None:
        deadline = time.monotonic() + 10
        while p2_worker._load_events()[1] and time.monotonic() < deadline:
            time.sleep(0.02)

    settle()
    if p2_worker._load_events()[1]:
        # A test in another file counted a worker load in and never out (it called a pool's _spawn on its own). The
        # count is process-wide, so clear it here; this file's own leaks are still caught after each test below.
        with p2_worker._LOAD_LOCK:
            p2_worker._LOAD["active"] = 0
    assert p2_worker._load_events()[1] == 0, "a worker load from an earlier test is still in flight"
    yield
    settle()
    assert p2_worker._load_events()[1] == 0, "this test left a worker load in flight"


@pytest.fixture
def job(tmp_path: Path) -> Iterator[tuple[Path, list[dict[str, Any]]]]:
    """A tracked job's work folder and the record updates sent for it."""
    root = tmp_path / "jobs" / JOB
    (root / "work").mkdir(parents=True)
    seen: list[dict[str, Any]] = []
    job_gpu.track(root, lambda **f: seen.append(f))
    yield root / "work", seen
    job_gpu.untrack(root)


def _waits(seen: list[dict[str, Any]]) -> list[Any]:
    return [f["wait"] for f in seen if "wait" in f]


def _admissions(monkeypatch: pytest.MonkeyPatch, refuse: Any) -> list[dict[str, Any]]:
    """A fake admission: `refuse(n, kw)` true makes call n (from 1) wait out its timeout and raise TimeoutError."""
    calls: list[dict[str, Any]] = []

    @contextlib.contextmanager
    def fake_acquire(**kw: Any) -> Iterator[None]:
        calls.append(kw)
        if refuse(len(calls), kw):
            time.sleep(min(kw.get("timeout_s", 0.0), 2.0))
            raise TimeoutError("busy")
        yield

    monkeypatch.setattr(p2_pose.gpu_lock, "acquire", fake_acquire)
    return calls


def _loaded_tracker(tmp_path: Path, state_dir: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, list[list[str]],
                                                                                                p2_worker.Pool]:
    lk, ran, pool = _track_env(tmp_path, state_dir, monkeypatch)
    with pool.lease() as sock:
        assert sock is not None  # the warm tracker holds its model now
    return lk, ran, pool


# ----- the admission path: a busy warm tracker is waited for --------------------------------------------------
def test_a_take_behind_a_busy_warm_tracker_waits_and_runs_warm(
    tmp_path: Path, state_dir: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv(p2_pose.TRACK_WAIT_ENV, "0.2")
    lk, ran, pool = _loaded_tracker(tmp_path, state_dir, monkeypatch)
    calls = _admissions(monkeypatch, lambda n, kw: n == 1)  # the usual wait passes while another take's call runs
    monkeypatch.setattr(p2_pose, "api_tracker_allowed", lambda *a, **k: True)
    leases: list[float | None] = []
    real_lease = p2_worker.track_lease
    monkeypatch.setattr(p2_pose.p2_worker, "track_lease", lambda w=None: leases.append(w) or real_lease(w))
    other = threading.Thread(target=lambda: _hold(pool, 0.4))
    other.start()
    try:
        with caplog.at_level(logging.INFO, logger="part7"):
            step, tracks = p2_pose.track(_video(tmp_path), tmp_path / "w", lock=lk, state=state_dir, acquire_lock=True)
    finally:
        other.join()
        p2_worker.stop_track_pool()
    assert _trackers(ran) == ["local-sam31"] and "--worker" in ran[0] and step["exit"] == 0 and tracks.is_file()
    assert calls[0]["timeout_s"] == 0.2 and 0 < calls[1]["timeout_s"] <= warm_wait.MAX_DEFAULT_S
    assert calls[1]["wait_since"] <= time.time() and calls[0]["wait_since"] == calls[1]["wait_since"]
    assert len(leases) == 1 and leases[0] is not None and leases[0] <= warm_wait.MAX_DEFAULT_S  # R1: bounded, not 1200 s
    assert any("warm wait: got warm after " in m for m in _msgs(caplog))
    assert not any("p2_track_gpu_busy" in m or "gave up" in m for m in _msgs(caplog))


def _hold(pool: p2_worker.Pool, seconds: float) -> None:
    with pool.lease() as sock:
        assert sock is not None
        time.sleep(seconds)


def test_the_bound_is_hit_and_the_take_goes_cold_logged(
    tmp_path: Path, state_dir: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv(p2_pose.TRACK_WAIT_ENV, "0.2")
    monkeypatch.setenv(warm_wait.MAX_ENV, "0.5")
    lk, ran, _ = _loaded_tracker(tmp_path, state_dir, monkeypatch)
    calls = _admissions(monkeypatch, lambda n, kw: kw.get("min_free_mib") == p2_pose.TRACK_MIN_FREE_MIB)
    monkeypatch.setattr(p2_pose, "api_tracker_allowed", lambda *a, **k: True)
    try:
        with caplog.at_level(logging.INFO, logger="part7"):
            p2_pose.track(_video(tmp_path), tmp_path / "w", lock=lk, state=state_dir, acquire_lock=True)
    finally:
        p2_worker.stop_track_pool()
    assert _trackers(ran) == ["api-sam31"]  # the cold route of today, after the bound
    assert len(calls) == 2 and 0 < calls[1]["timeout_s"] <= 0.3
    gave = [m for m in _msgs(caplog) if "warm wait: gave up after " in m]
    assert len(gave) == 1 and gave[0].endswith(", cold (no GPU turn within 0.5 s)")
    busy = next(m for m in _msgs(caplog) if "ANOMALY p2_track_gpu_busy" in m)
    assert float(busy.split("waited_s=")[1].split()[0]) >= 0.5  # the real wait, not the usual limit


def test_no_warm_worker_keeps_todays_route(
    tmp_path: Path, state_dir: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The negative: the tracker pool runs but holds no model (released), so nothing waits beyond the usual limit."""
    monkeypatch.setenv(p2_pose.TRACK_WAIT_ENV, "0.2")
    lk, ran, _ = _track_env(tmp_path, state_dir, monkeypatch)
    calls = _admissions(monkeypatch, lambda n, kw: kw.get("min_free_mib") == p2_pose.TRACK_MIN_FREE_MIB)
    monkeypatch.setattr(p2_pose, "api_tracker_allowed", lambda *a, **k: True)
    try:
        with caplog.at_level(logging.INFO, logger="part7"):
            p2_pose.track(_video(tmp_path), tmp_path / "w", lock=lk, state=state_dir, acquire_lock=True)
    finally:
        p2_worker.stop_track_pool()
    assert _trackers(ran) == ["api-sam31"] and [c["timeout_s"] for c in calls] == [0.2]
    assert not any("warm wait" in m for m in _msgs(caplog))


# ----- the cold repeat: never stop the tracker for a call that cannot fit ----------------------------------------
def _pin_pool(tmp_path: Path, allow: list[bool], ver: list[str]) -> p2_worker.Pool:
    """A warm tracker whose pin can change (`ver`) and whose restart answers only while `allow[0]`."""
    return p2_worker.Pool(
        tmp_path / "pin", 1, lambda sock: ["part2", "serve-worker", "--mode", "track", "--socket", str(sock)],
        launcher=lambda *a: _Proc(), health=lambda sock: allow[0], start_wait_s=5.0, lease_wait_s=0.0, label="p2_tracker", folder="p2-tracker",
        on_demand=True, version=lambda: ver[0],
    )


def _restarting(tmp_path: Path, state_dir: Path, monkeypatch: pytest.MonkeyPatch, answers: bool) -> tuple[Any, ...]:
    """The 17:19Z shape: the tracker is loaded, then the pin changes, so the next lease restarts it and misses.
    `answers` false: the restarted tracker does not answer until the test ends."""
    monkeypatch.setenv(p2_pose.TRACK_WORKER_ENV, "1")
    lk, ran, _ = _track_env(tmp_path, state_dir, monkeypatch)
    ver, allow = ["348e246"], [True]
    pool = _pin_pool(tmp_path, allow, ver)
    p2_worker.start_track_pool(pool)
    with pool.lease() as sock:
        assert sock is not None
    ver[0], allow[0] = "8b08a27", answers
    stops: list[float] = []
    real_stop = p2_worker.stop_track_worker
    monkeypatch.setattr(p2_pose.p2_worker, "stop_track_worker", lambda w: stops.append(w) or real_stop(w))
    calls = _admissions(monkeypatch, lambda n, kw: False)
    return lk, ran, allow, stops, calls


def test_a_cold_call_that_cannot_fit_never_releases_the_warm_tracker_and_waits_for_it(
    job: tuple[Path, list[dict[str, Any]]], tmp_path: Path, state_dir: Path, monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture
) -> None:
    work, seen = job
    lk, ran, _, stops, _ = _restarting(tmp_path, state_dir, monkeypatch, True)
    try:
        with caplog.at_level(logging.INFO, logger="part7"):
            step, tracks = p2_pose.track(_video(tmp_path), work, lock=lk, state=state_dir, acquire_lock=True,
                                         tracker="local-sam31", gpu_lock_kwargs={"memory_fn": lambda: 19000})
    finally:
        p2_worker.stop_track_pool()
    assert stops == []  # 19000 MiB free plus the tracker's 5222 < 26624 MiB: the tracker is never stopped for it
    assert _trackers(ran) == ["local-sam31"] and "--worker" in ran[0] and step["exit"] == 0 and tracks.is_file()
    assert not any("p2_tracker_released" in m or "p2_cold_sam31_skipped" in m for m in _msgs(caplog))
    assert any(m.startswith(f"job {JOB}: warm wait: got warm after ") for m in _msgs(caplog))
    waits = _waits(seen)
    assert waits[0]["reason"] == job_gpu.ANOTHER_TAKE and waits[-1] is None  # TICKET-289 fields stay honest


def test_a_cold_call_that_cannot_fit_skips_to_local_open_at_the_bound_and_keeps_the_tracker(
    job: tuple[Path, list[dict[str, Any]]], tmp_path: Path, state_dir: Path, monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture
) -> None:
    work, seen = job
    monkeypatch.setenv(warm_wait.MAX_ENV, "0.4")
    lk, ran, allow, stops, _ = _restarting(tmp_path, state_dir, monkeypatch, False)  # no answer within the bound
    try:
        with caplog.at_level(logging.INFO, logger="part7"):
            step, tracks = p2_pose.track(_video(tmp_path), work, lock=lk, state=state_dir, acquire_lock=True,
                                         tracker="local-sam31", gpu_lock_kwargs={"memory_fn": lambda: 19000})
    finally:
        allow[0] = True
        p2_worker.stop_track_pool()
    assert stops == [] and _trackers(ran) == ["local-open"] and step["exit"] == 0 and tracks.is_file()
    text = " ".join(_msgs(caplog))
    assert "ANOMALY p2_cold_sam31_skipped" in text and "cannot fit beside the resident workers" in text
    assert "free_mib=19000" in text and "need_mib=26624" in text
    gave = [m for m in _msgs(caplog) if "warm wait: gave up after " in m]
    assert len(gave) == 1 and "cold local-sam31 cannot fit, local-open" in gave[0]
    assert _waits(seen)[-1] is None


def test_a_cold_call_that_fits_still_stops_the_tracker_and_runs_cold(
    tmp_path: Path, state_dir: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The negative of the two above: with room beside the resident workers the cold repeat runs as before."""
    lk, ran, _, stops, calls = _restarting(tmp_path, state_dir, monkeypatch, True)
    try:
        with caplog.at_level(logging.INFO, logger="part7"):
            p2_pose.track(_video(tmp_path), tmp_path / "w", lock=lk, state=state_dir, acquire_lock=True,
                          tracker="local-sam31", gpu_lock_kwargs={"memory_fn": lambda: 30000})
    finally:
        p2_worker.stop_track_pool()
    assert len(stops) == 1 and _trackers(ran) == ["local-sam31"] and "--worker" not in ran[0]
    assert calls[-1]["min_free_mib"] == p2_pose.COLD_SAM31_MIN_FREE_MIB
    assert not any("warm wait" in m for m in _msgs(caplog))


def test_cold_fits_counts_an_idle_trackers_memory_and_unknown_is_todays_behaviour(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(p2_pose.p2_worker, "track_state", lambda: "idle")
    assert p2_pose._cold_fits(26624, {"memory_fn": lambda: 26624 - p2_pose.TRACK_RESIDENT_MIB}) is True
    assert p2_pose._cold_fits(26624, {"memory_fn": lambda: 26623 - p2_pose.TRACK_RESIDENT_MIB}) is False
    monkeypatch.setattr(p2_pose.p2_worker, "track_state", lambda: "starting")
    assert p2_pose._cold_fits(26624, {"memory_fn": lambda: 23045}) is False  # staging da5275f0c143, 17:19Z
    assert p2_pose._cold_fits(26624, {"memory_fn": lambda: None}) is None


# ----- the pose worker -----------------------------------------------------------------------------------------
def _pose(monkeypatch: pytest.MonkeyPatch, socks: list[Path | None], states: list[str]) -> list[list[str]]:
    """Fakes for the 3D step: leases hand out `socks` in turn (then None), the pool reads `states` (then busy)."""
    ran: list[list[str]] = []

    @contextlib.contextmanager
    def fake_lease() -> Iterator[Path | None]:
        yield socks.pop(0) if socks else None

    def fake_launch(sub: list[str], s: Path | None, *a: Any) -> dict[str, Any]:
        ran.append([*sub, *(["--worker", str(s)] if s is not None else [])])
        return {"exit": 0}

    monkeypatch.setattr(p2_pose, "has_worker", lambda *a, **k: True)
    monkeypatch.setattr(p2_pose.p2_worker, "lease", fake_lease)
    monkeypatch.setattr(p2_pose.p2_worker, "state", lambda: states.pop(0) if states else "busy")
    monkeypatch.setattr(p2_pose.p2_worker, "holds_model", lambda: True)
    monkeypatch.setattr(p2_pose.p2_worker, "wait_ready", lambda w: time.sleep(min(w, 0.05)) is None)
    monkeypatch.setattr(p2_pose, "_launch", fake_launch)
    return ran


def _run_3d(work: Path) -> dict[str, Any]:
    return p2_pose._execute(["run", "--video", "v.mp4"], "gpu", work, "p2.log", None, Path("."), False, None)  # type: ignore[arg-type]


def test_a_3d_step_whose_warm_worker_was_leased_first_waits_and_runs_warm(
    job: tuple[Path, list[dict[str, Any]]], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture
) -> None:
    work, seen = job
    ran = _pose(monkeypatch, [None, tmp_path / "w0.sock"], ["idle", "busy"])
    with caplog.at_level(logging.INFO, logger="part7"):
        _run_3d(work)
    assert len(ran) == 1 and "--worker" in ran[0]  # no cold in-process run beside it
    assert _waits(seen)[0]["reason"] == job_gpu.ANOTHER_TAKE and _waits(seen)[-1] is None
    assert {"worker": "warm", "worker_reason": None} in seen
    assert any(m.startswith(f"job {JOB}: warm wait: got warm after ") for m in _msgs(caplog))


def test_a_3d_step_goes_in_process_at_the_bound_logged(
    job: tuple[Path, list[dict[str, Any]]], monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    work, seen = job
    monkeypatch.setenv(warm_wait.MAX_ENV, "0.3")
    ran = _pose(monkeypatch, [], ["idle", "busy"])
    with caplog.at_level(logging.INFO, logger="part7"):
        _run_3d(work)
    assert len(ran) == 1 and "--worker" not in ran[0]
    assert seen[-1] == {"worker": "cold", "worker_reason": job_gpu.COLD_BUSY}
    assert any("warm wait: gave up after " in m and "cold (no warm worker within 0.3 s)" in m for m in _msgs(caplog))


def test_a_3d_step_admitted_on_the_memory_floor_runs_cold_beside_a_busy_worker_as_before(
    job: tuple[Path, list[dict[str, Any]]], monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The negative: a worker busy at admission means the memory floor applied, so the cold run fits: no wait."""
    work, seen = job
    ran = _pose(monkeypatch, [], ["busy", "busy"])
    with caplog.at_level(logging.INFO, logger="part7"):
        _run_3d(work)
    assert len(ran) == 1 and "--worker" not in ran[0] and _waits(seen) == []
    assert not any("warm wait" in m for m in _msgs(caplog))


# ----- TICKET-317 handoff and TICKET-305 starvation with a warm wait ---------------------------------------------
def test_a_warm_wait_keeps_its_start_the_honest_reason_the_handoff_and_the_starvation_check(
    job: tuple[Path, list[dict[str, Any]]], tmp_path: Path, state_dir: Path, monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture
) -> None:
    work, seen = job
    monkeypatch.setattr(gpu_lock, "NOTE_AFTER_S", 0.1)
    monkeypatch.setattr(gpu_lock, "NOTE_POLL_S", 0.05)
    monkeypatch.setattr(gpu_lock, "_from_here", lambda pid, depth=8: False)  # as if an eval run outside held it
    monkeypatch.setenv(p2_pose.TRACK_WAIT_ENV, "0.3")
    lk, ran, _ = _loaded_tracker(tmp_path, state_dir, monkeypatch)
    lock = Path(gpu_lock.config.gpu_lock_path())
    tickets: list[int] = []
    done = threading.Event()

    def sample() -> None:
        folder = gpu_lock.waiters_dir(lock)
        while not done.is_set():
            tickets.append(len(list(folder.iterdir())) if folder.exists() else 0)
            time.sleep(0.02)

    sampler = threading.Thread(target=sample)
    sampler.start()
    kw = {"priority": gpu_lock.HIGH, "poll_s": 0.05, "settle_s": 0.0, "memory_fn": lambda: 40000}
    try:
        with caplog.at_level(logging.INFO, logger="part7"), held_by_child(lock, 1.2):
            step, _ = p2_pose.track(_video(tmp_path), work, lock=lk, state=state_dir, acquire_lock=True, gpu_lock_kwargs=kw)
    finally:
        done.set()
        sampler.join()
        p2_worker.stop_track_pool()
    assert _trackers(ran) == ["local-sam31"] and "--worker" in ran[0] and step["exit"] == 0
    shown = [w for w in _waits(seen) if isinstance(w, dict)]
    assert len(shown) >= 2 and {w["since"] for w in shown} == {shown[0]["since"]}  # one wait, one start
    # each admission names the outside holder as other GPU work, never another take (it may change once it lets go)
    assert [w["reason"] for w in shown][:2] == [job_gpu.OTHER_WORK, job_gpu.OTHER_WORK]
    assert _waits(seen)[-1] is None
    assert max(tickets) == 1 and not list(gpu_lock.waiters_dir(lock).glob("*"))  # TICKET-317: held, then dropped
    assert any(m.startswith(f"job {JOB}: warm wait: got warm after ") for m in _msgs(caplog))
    since = queue_eta.epoch(shown[0]["since"])
    assert since is not None
    selfheal.check_gpu_starved([(JOB, since, job_gpu.ANOTHER_TAKE)], lambda: "part7", now=since + 400)
    assert selfheal.open_findings() == []  # a wait behind another take is not starvation
    selfheal.check_gpu_starved([(JOB, since, job_gpu.OTHER_WORK)], lambda: "another process", now=since + 400)
    assert [f["check"] for f in selfheal.open_findings()] == ["gpu_starved"]  # the clock did not restart


# ----- review fixes (B1, R2 to R7) -------------------------------------------------------------------------------
def test_an_idle_tracker_at_22000_mib_free_is_never_stopped_for_a_cold_call(
    tmp_path: Path, state_dir: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """B1: a loaded tracker gives back about 4038 MiB, so 22000 MiB free cannot fit 26624 MiB once it stops."""
    monkeypatch.setenv(p2_pose.TRACK_WORKER_ENV, "1")
    lk, ran, pool = _track_env(tmp_path, state_dir, monkeypatch, script_exit=1)  # the warm call fails: a cold repeat
    with pool.lease():
        pass
    stops: list[float] = []
    monkeypatch.setattr(p2_pose.p2_worker, "stop_track_worker", lambda w: stops.append(w) or True)
    _admissions(monkeypatch, lambda n, kw: False)
    try:
        with caplog.at_level(logging.INFO, logger="part7"):
            p2_pose.track(_video(tmp_path), tmp_path / "w", lock=lk, state=state_dir, acquire_lock=True,
                          tracker="local-sam31", gpu_lock_kwargs={"memory_fn": lambda: 22000})
    finally:
        p2_worker.stop_track_pool()
    assert stops == [] and _trackers(ran) == ["local-sam31", "local-open"]
    assert any("ANOMALY p2_cold_sam31_skipped" in m and "free_mib=22000" in m for m in _msgs(caplog))


def test_the_trackers_resident_size_is_measured_at_load_and_the_lowest_plausible_one_kept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    readings = [23052, 19014, 23000, 23000, 30000, 10000]  # load 1: 4038; load 2: no drop; load 3: other work
    pool = p2_worker.Pool(tmp_path, 1, lambda s: ["part2", "serve-worker", "--mode", "track", "--socket", str(s)],
                          launcher=lambda *a: _Proc(), health=lambda s: True, start_wait_s=1.0, label="p2_tracker",
                          folder="p2-tracker", on_demand=True, measure_free=lambda: readings.pop(0))
    p2_worker.start_track_pool(pool)
    try:
        assert p2_pose._tracker_gives_back() == p2_pose.TRACK_RESIDENT_MIB == 4000  # nothing measured yet
        with caplog.at_level(logging.INFO, logger="part7"):
            for _ in range(3):
                with pool.lease() as sock:
                    assert sock is not None
                pool.release_all(1.0)
        assert pool.resident_mib == 4038 and p2_worker.track_resident_mib() == 4038
        assert p2_pose._tracker_gives_back() == 4038
        assert sum("p2_tracker: resident 4038 MiB measured at load (free 23052 to 19014 MiB)" in m
                   for m in _msgs(caplog)) == 1
    finally:
        p2_worker.stop_track_pool()


def test_an_unreadable_free_memory_at_load_is_no_measurement(tmp_path: Path) -> None:
    pool = p2_worker.Pool(tmp_path, 1, lambda s: ["serve-worker", "--mode", "track", "--socket", str(s)],
                          launcher=lambda *a: _Proc(), health=lambda s: True, start_wait_s=1.0, on_demand=True,
                          folder="p2-tracker", measure_free=lambda: None)
    pool.start()
    with pool.lease() as sock:
        assert sock is not None
    assert pool.resident_mib is None
    pool.stop()


def test_a_3d_warm_wait_is_bounded_from_the_first_admission_with_one_wait_start(
    job: tuple[Path, list[dict[str, Any]]], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R2: the 3D step's wait and its `wait.since` start at its first admission, not after it."""
    work, _ = job
    _pose(monkeypatch, [None, tmp_path / "w0.sock"], ["idle", "busy"])
    calls = _admissions(monkeypatch, lambda n, kw: False)
    p2_pose._execute(["run", "--video", "v.mp4"], "gpu", work, "p2.log", None, Path("."), True, None)  # type: ignore[arg-type]
    assert len(calls) == 2 and calls[0]["wait_since"] == calls[1]["wait_since"]
    assert calls[1]["timeout_s"] <= warm_wait.MAX_DEFAULT_S


def test_wait_for_never_spins_on_a_pool_that_stopped_but_still_reads_as_holding(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    """R3: `ready` returns at once (a closed pool), `holds` stays true: the loop sleeps out each look."""
    monkeypatch.setenv(warm_wait.MAX_ENV, "0.3")
    monkeypatch.setattr(warm_wait, "POLL_S", 0.1)
    looks: list[float] = []
    warm = warm_wait.WarmWait(None)
    got = warm_wait.wait_for(warm, None, lambda: True, lambda s: looks.append(s) and False, lambda kw: "never")
    assert got is None and 2 <= len(looks) <= 5


def test_wait_for_shows_the_wait_again_after_an_admission_cleared_it(
    job: tuple[Path, list[dict[str, Any]]]
) -> None:
    """R4: an attempt whose admission watcher cleared the record and missed the lease leaves the wait shown."""
    work, seen = job
    results: list[str | None] = [None, "warm"]

    def attempt(kw: dict[str, Any]) -> str | None:
        job_gpu.admitted(work)  # what the admission's own watcher does when it stops
        return results.pop(0)

    warm = warm_wait.WarmWait(work)
    assert warm_wait.wait_for(warm, None, lambda: True, lambda s: True, attempt) == "warm"
    waits = _waits(seen)
    assert [w is None for w in waits] == [False, True, False, True]  # shown, cleared, shown again, cleared by the attempt
    assert waits[2]["since"] == waits[0]["since"] and waits[2]["reason"] == job_gpu.ANOTHER_TAKE


@pytest.mark.parametrize("raw", ["0", "-5", "lots", ""])
def test_a_warm_wait_limit_that_is_not_a_positive_number_keeps_300_s(raw: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """R5: the documented behaviour of SIMON7_WARM_WAIT_MAX_S; a small positive value is honoured."""
    monkeypatch.setenv(warm_wait.MAX_ENV, raw)
    assert warm_wait.max_s() == 300.0
    monkeypatch.setenv(warm_wait.MAX_ENV, "0.5")
    assert warm_wait.max_s() == 0.5


def test_the_final_busy_anomaly_reports_the_real_wait(
    tmp_path: Path, state_dir: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """R6: two refused admissions of 0.2 s each: `waited_s` is what passed, not twice the setting."""
    monkeypatch.setenv(p2_pose.TRACK_WAIT_ENV, "0.2")
    lk, _, _ = _track_env(tmp_path, state_dir, monkeypatch)
    _admissions(monkeypatch, lambda n, kw: True)
    monkeypatch.setattr(p2_pose, "api_tracker_allowed", lambda *a, **k: False)
    try:
        with caplog.at_level(logging.WARNING, logger="part7"), pytest.raises(TimeoutError):
            p2_pose.track(_video(tmp_path), tmp_path / "w", lock=lk, state=state_dir, acquire_lock=True)
    finally:
        p2_worker.stop_track_pool()
    final = next(m for m in _msgs(caplog) if "ANOMALY p2_track_gpu_busy_final" in m)
    assert float(final.split("waited_s=")[1].split()[0]) >= 0.4


def test_a_failed_record_write_leaves_the_wait_open_to_clear_again(
    job: tuple[Path, list[dict[str, Any]]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """R7: `ended` is set only after the record write went through."""
    work, seen = job
    warm = warm_wait.WarmWait(work)
    warm.show()
    real = job_gpu.admitted
    monkeypatch.setattr(warm_wait.job_gpu, "admitted", lambda w: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError):
        warm.end()
    assert warm.ended is False
    monkeypatch.setattr(warm_wait.job_gpu, "admitted", real)
    warm.end()
    assert warm.ended is True and _waits(seen)[-1] is None


# ----- recheck fixes (B1', R1') -----------------------------------------------------------------------------------
def _measuring_tracker(tmp_path: Path, readings: list[int], during_load: Any = None) -> p2_worker.Pool:
    def launcher(*a: Any) -> Any:
        if during_load is not None:
            during_load()
        return _Proc()

    return p2_worker.Pool(tmp_path, 1, lambda s: ["part2", "serve-worker", "--mode", "track", "--socket", str(s)],
                          launcher=launcher, health=lambda s: True, start_wait_s=1.0, label="p2_tracker",
                          folder="p2-tracker", on_demand=True, measure_free=lambda: readings.pop(0))


def _load_once(pool: p2_worker.Pool) -> None:
    with pool.lease() as sock:
        assert sock is not None
    pool.release_all(1.0)


def test_a_tracker_load_beside_a_concurrent_pose_load_is_not_used(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """B1': at a server start both workers load in the same second (31548 to 19432 MiB): the tracker keeps 4000."""
    up = threading.Event()
    pose = p2_worker.Pool(tmp_path / "pose", 1, lambda s: ["serve-worker", "--socket", str(s)],
                          launcher=lambda *a: _Proc(), health=lambda s: up.is_set(), start_wait_s=10.0)
    pose.start()  # the pose worker is loading (no answer yet)
    tracker = _measuring_tracker(tmp_path, [31548, 19432, 31548, 27000])
    p2_worker.start_track_pool(tracker)
    try:
        deadline = time.monotonic() + 5
        while p2_worker._load_events()[1] < 1 and time.monotonic() < deadline:  # its load is counted, not just queued
            time.sleep(0.01)
        assert p2_worker._load_events()[1] == 1
        with caplog.at_level(logging.INFO, logger="part7"):
            _load_once(tracker)  # 12116 MiB: both loads
            _load_once(tracker)  # 4548 MiB would pass the range, but the pose worker still loads in the window
        assert tracker.resident_mib is None and p2_pose._tracker_gives_back() == 4000
        assert sum("not used (another load or GPU call in the window" in m for m in _msgs(caplog)) == 2
    finally:
        up.set()
        pose.stop()
        p2_worker.stop_track_pool()


def test_a_tracker_load_during_a_gpu_admission_is_not_used(tmp_path: Path) -> None:
    lock = tmp_path / "gpu.lock"

    def admit() -> None:
        with gpu_lock.acquire(lock_path=lock, min_free_mib=0, timeout_s=2.0, poll_s=0.05):
            pass

    tracker = _measuring_tracker(tmp_path, [23052, 19014], during_load=admit)
    p2_worker.start_track_pool(tracker)
    try:
        _load_once(tracker)
        assert tracker.resident_mib is None
    finally:
        p2_worker.stop_track_pool()


def test_load_readings_below_3000_or_above_4600_are_dropped_and_the_median_of_five_is_kept(tmp_path: Path) -> None:
    pairs = [(10000, 7001), (10000, 7000), (10000, 5399), (10000, 5400), (10000, 5961), (10000, 5500), (10000, 5961),
             (10000, 5962), (10000, 5399)]  # drops 2999, 3000, 4601, 4600, 4039, 4500, 4039, 4038, 4601
    readings = [r for pair in pairs for r in pair]
    tracker = _measuring_tracker(tmp_path, readings)
    p2_worker.start_track_pool(tracker)
    try:
        _load_once(tracker)
        assert tracker.resident_mib is None  # 2999: under the floor
        _load_once(tracker)
        assert tracker.resident_mib == 3000  # the floor itself is kept
        for _ in range(7):
            _load_once(tracker)
        assert list(tracker._readings) == [4600, 4039, 4500, 4039, 4038]  # the last five accepted; 4601 dropped
        assert tracker.resident_mib == 4039  # their median
        assert p2_pose._tracker_gives_back() == tracker.resident_mib
    finally:
        p2_worker.stop_track_pool()


def test_the_first_lease_is_bounded_by_the_warm_wait(
    tmp_path: Path, state_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R1': the first admission's lease waits at most the warm wait's bound, not the call timeout."""
    lk, ran, _ = _loaded_tracker(tmp_path, state_dir, monkeypatch)
    _admissions(monkeypatch, lambda n, kw: False)
    leases: list[float | None] = []
    real_lease = p2_worker.track_lease
    monkeypatch.setattr(p2_pose.p2_worker, "track_lease", lambda w=None: leases.append(w) or real_lease(w))
    try:
        p2_pose.track(_video(tmp_path), tmp_path / "w", lock=lk, state=state_dir, acquire_lock=True)
    finally:
        p2_worker.stop_track_pool()
    assert "--worker" in ran[0] and len(leases) == 1 and leases[0] is not None
    assert 0 < leases[0] <= warm_wait.MAX_DEFAULT_S < p2_pose.config.TIMEOUTS["2"]


def test_a_tracker_is_lendable_while_another_admission_settles(tmp_path: Path) -> None:
    """Follow-up R2: `_wait_settle` sleeps under `_ADMIT_LOCK`; the load window's `gpu_lock.activity()` has its own lock,
    so a tracker load finishes during another take's settle instead of waiting it out."""
    lock = tmp_path / "gpu.lock"
    admitted, release = threading.Event(), threading.Event()

    def running() -> None:  # an admitted take, so the next admission must settle
        with gpu_lock.acquire(lock_path=lock, min_free_mib=0, concurrent=True, hold_flock=False, settle_s=0.0,
                              timeout_s=5.0, poll_s=0.05):
            admitted.set()
            release.wait(10)

    def settling() -> None:
        with gpu_lock.acquire(lock_path=lock, min_free_mib=0, concurrent=True, hold_flock=False, settle_s=3.0,
                              timeout_s=10.0, poll_s=0.05):
            pass

    first, second = threading.Thread(target=running), threading.Thread(target=settling)
    first.start()
    assert admitted.wait(5)
    second.start()
    time.sleep(0.3)  # the second admission sleeps in its settle now
    tracker = _measuring_tracker(tmp_path, [23052, 19014])
    p2_worker.start_track_pool(tracker)
    try:
        began = time.monotonic()
        with tracker.lease() as sock:
            assert sock is not None
        assert time.monotonic() - began < 1.5 and second.is_alive()  # lent before the settle ended
    finally:
        release.set()
        first.join(10)
        second.join(10)
        p2_worker.stop_track_pool()
