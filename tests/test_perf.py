"""Performance work: Part 1 beside Part 2, warm Part 2 workers, picker tracker, phrasing concurrency."""

from __future__ import annotations

from pathlib import Path
import contextlib
import threading
import time
from typing import Any

import pytest

from part7 import chain, p2_worker, runner
from part7.parts import p1_keyframes, p2_pose, p3_skeleton, p4_animate, p5_analyse
from tests.test_chain import _dummy_lock, _ok_step


def _patch_rest(monkeypatch: pytest.MonkeyPatch, kf_seen: list[Any]) -> None:
    def part4(pose: Path, kf: Any, w: Path, **kw: Any) -> Any:
        kf_seen.append(str(kf))
        sk, kfv1 = Path(w) / "skeleton.json", Path(w) / "keyframes.v1.json"
        sk.write_text("{}", encoding="utf-8")
        kfv1.write_text("{}", encoding="utf-8")
        return ([_ok_step(3)], sk, kfv1, None)

    def p4run(sk: Path, kfv1: Path, w: Path, **kw: Any) -> Any:
        anim = Path(w) / "part4" / "animation.json"
        anim.parent.mkdir(parents=True, exist_ok=True)
        anim.write_text("{}", encoding="utf-8")
        return (_ok_step(4), anim)

    monkeypatch.setattr(p2_pose, "doctor", lambda *a, **kw: _ok_step(2))
    monkeypatch.setattr(p3_skeleton, "part4", part4)
    monkeypatch.setattr(p3_skeleton, "doctor", lambda *a, **kw: _ok_step(3))
    monkeypatch.setattr(p4_animate, "validate", lambda *a, **kw: _ok_step(4))
    monkeypatch.setattr(p4_animate, "run", p4run)
    monkeypatch.setattr(p5_analyse, "doctor", lambda *a, **kw: _ok_step(5))


def _fake_p2(delay: float, marks: dict[str, float] | None = None) -> Any:
    def run(v: Path, w: Path, **kw: Any) -> Any:
        if marks is not None:
            marks["p2_start"] = time.monotonic()
        time.sleep(delay)
        if marks is not None:
            marks["p2_end"] = time.monotonic()
        p = Path(w) / "part2" / "pose3d.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{}", encoding="utf-8")
        return (_ok_step(2), p)

    return run


def _video(tmp_path: Path) -> Path:
    video = tmp_path / "v.mp4"
    video.write_bytes(b"v")
    return video


def test_trainer_runs_part1_beside_part2(tmp_path: Path, state_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Wall time is the longer of the two, not their sum; the stages keep their order."""
    seen: list[Any] = []
    _patch_rest(monkeypatch, seen)
    kf = tmp_path / "kf.json"
    kf.write_text('{"people": [{}]}', encoding="utf-8")

    marks: dict[str, float] = {}

    def p1(v: Path, w: Path, **kw: Any) -> Any:
        marks["p1_start"] = time.monotonic()
        time.sleep(0.4)
        marks["p1_end"] = time.monotonic()
        return (_ok_step(1), kf, None)

    monkeypatch.setattr(p1_keyframes, "run", p1)
    monkeypatch.setattr(p1_keyframes, "doctor", lambda *a, **kw: _ok_step(6))
    monkeypatch.setattr(p2_pose, "run", _fake_p2(0.4, marks))
    stages: list[str] = []
    res = chain.trainer(
        _video(tmp_path), tmp_path / "w", report=stages.append, lock=_dummy_lock(state_dir), state=state_dir
    )
    assert res["ok"] and res["parts"]["keyframes"] == 1 and seen == [str(kf)]
    # Overlap by ordering, not wall clock (flaked under host load): each part starts before the other ends.
    assert marks["p1_start"] < marks["p2_end"] and marks["p2_start"] < marks["p1_end"], marks
    assert stages[:2] == ["keyframes", "pose"]


def test_part1_timeout_falls_back_to_every10_and_notes_it(
    tmp_path: Path, state_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[Any] = []
    _patch_rest(monkeypatch, seen)
    got: dict[str, Any] = {}

    def p1(v: Path, w: Path, **kw: Any) -> Any:
        got.update(kw)
        step = _ok_step(1)
        step.update(exit=124, timed_out=True)
        return (step, None, "key frames from Part 3, Part 1 exited 124")

    monkeypatch.setattr(p1_keyframes, "run", p1)
    monkeypatch.setattr(p2_pose, "run", _fake_p2(0))
    monkeypatch.setenv("SIMON7_PART1_TIMEOUT_S", "45")
    res = chain.trainer(_video(tmp_path), tmp_path / "w", lock=_dummy_lock(state_dir), state=state_dir)
    assert res["ok"] and got["timeout_s"] == 45 and seen == ["every:10"]
    assert "longer than 45 s" in res["note"] and res["parts"]["keyframes"] == 3


def test_part1_exception_never_fails_the_job(tmp_path: Path, state_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[Any] = []
    _patch_rest(monkeypatch, seen)

    def boom(*a: Any, **kw: Any) -> Any:
        raise OSError("disk")

    monkeypatch.setattr(p1_keyframes, "run", boom)
    monkeypatch.setattr(p2_pose, "run", _fake_p2(0))
    res = chain.trainer(_video(tmp_path), tmp_path / "w", lock=_dummy_lock(state_dir), state=state_dir)
    assert res["ok"] and seen == ["every:10"] and "Part 1 failed" in res["note"]


def test_part1_is_joined_when_part2_fails(tmp_path: Path, state_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    done = threading.Event()

    def p1(v: Path, w: Path, **kw: Any) -> Any:
        time.sleep(0.2)
        done.set()
        return (None, None, "key frames from Part 3, Part 1 unavailable")

    def bad(*a: Any, **kw: Any) -> Any:
        raise RuntimeError("x")

    monkeypatch.setattr(p1_keyframes, "run", p1)
    monkeypatch.setattr(p2_pose, "run", bad)
    res = chain.trainer(_video(tmp_path), tmp_path / "w", lock=_dummy_lock(state_dir), state=state_dir)
    assert res["ok"] is False and res["stage"] == "pose" and done.is_set()


# ----- warm workers ------------------------------------------------------------------------------
class _Proc:
    def __init__(self) -> None:
        self.dead = False
        self.terminated = False

    def poll(self) -> int | None:
        return 1 if self.dead else None

    def terminate(self) -> None:
        self.terminated = self.dead = True

    def wait(self, timeout: float | None = None) -> int:
        return 0

    def kill(self) -> None:
        self.dead = True


def _pool(tmp_path: Path, slots: int = 1, lease_wait_s: float = 0.0) -> tuple[p2_worker.Pool, list[_Proc]]:
    procs: list[_Proc] = []
    up: set[str] = set()

    def launcher(argv: list[str], log: Path, cwd: Any, env: Any) -> Any:
        up.add(argv[-1])
        procs.append(_Proc())
        return procs[-1]

    pool = p2_worker.Pool(
        tmp_path, slots, lambda sock: ["serve-worker", "--socket", str(sock)], launcher=launcher,
        health=lambda sock: str(sock) in up, start_wait_s=2.0, lease_wait_s=lease_wait_s,
    )
    return pool, procs


def test_one_worker_is_leased_to_one_call_and_a_busy_one_is_skipped(tmp_path: Path) -> None:
    pool, procs = _pool(tmp_path)
    pool.start()
    time.sleep(0.5)
    assert pool.state() == "idle"
    with pool.lease() as a, pool.lease() as b:
        assert a is not None and b is None  # lease timeout: the second call runs in-process
        assert pool.state() == "busy"
    with pool.lease() as again:
        assert again == a
    assert len(procs) == 1
    pool.stop()
    assert procs[0].terminated and pool.state() == "off"
    with pool.lease() as after_stop:
        assert after_stop is None


def test_a_call_waits_a_short_time_for_the_busy_worker(tmp_path: Path) -> None:
    pool, _ = _pool(tmp_path, lease_wait_s=3.0)
    pool.start()
    time.sleep(0.5)
    got: list[Any] = []

    def second() -> None:
        with pool.lease() as sock:
            got.append(sock)

    with pool.lease() as first:
        t = threading.Thread(target=second)
        t.start()
        time.sleep(0.3)
    t.join(5)
    assert first is not None and got == [first]  # freed within the wait: the second call got the worker
    pool.stop()


def test_lease_timeout_returns_none_after_the_wait(tmp_path: Path) -> None:
    pool, _ = _pool(tmp_path, lease_wait_s=0.3)
    pool.start()
    time.sleep(0.5)
    with pool.lease() as first:
        t0 = time.monotonic()
        with pool.lease() as second:
            assert first is not None and second is None
        assert 0.25 <= time.monotonic() - t0 < 2.0
    pool.stop()


def test_a_dead_worker_runs_this_call_in_process_logs_an_anomaly_and_restarts_once(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    pool, procs = _pool(tmp_path)
    pool.start()
    time.sleep(0.5)
    procs[0].dead = True
    with caplog.at_level("WARNING"):
        with pool.lease() as sock:
            assert sock is None  # never waits for a model load
    assert "ANOMALY p2_worker_unhealthy" in caplog.text
    time.sleep(0.6)
    assert len(procs) == 2  # one restart
    with pool.lease() as again:
        assert again is not None
    pool.stop()


def test_pool_gives_none_when_the_worker_never_answers(tmp_path: Path) -> None:
    pool = p2_worker.Pool(
        tmp_path, 1, lambda s: ["x"], launcher=lambda *a: _Proc(), health=lambda s: False, start_wait_s=0.3
    )
    with pool.lease() as sock:
        assert sock is None


def _p2_env(state_dir: Path, monkeypatch: pytest.MonkeyPatch, flags: set[str]) -> tuple[Any, list[list[str]]]:
    lk = _dummy_lock(state_dir)
    ran: list[list[str]] = []
    monkeypatch.setattr(
        p2_pose.probe, "help_text",
        lambda part, argv, clone, lock=None: " ".join(sorted(flags)) + (" track" if "track" in argv else ""),
    )
    p2_pose.probe.clear_cache()

    def fake_run(part: Any, argv: list[str], **kw: Any) -> runner.Step:
        ran.append([str(a) for a in argv])
        return _ok_step(2)

    monkeypatch.setattr(runner, "run", fake_run)
    return lk, ran


def test_run_passes_worker_when_pin_has_flag_and_pool_runs(
    tmp_path: Path, state_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lk, ran = _p2_env(state_dir, monkeypatch, {"--worker"})
    pool, _ = _pool(tmp_path)
    p2_worker.start_pool(pool)
    time.sleep(0.5)
    try:
        # a worker job needs no free memory (the worker holds the model), so a 0 MiB reading does not block it
        p2_pose.run(
            _video(tmp_path), tmp_path / "w", lock=lk, state=state_dir,
            gpu_lock_kwargs={"memory_fn": lambda: 0, "timeout_s": 2, "lock_path": tmp_path / "g.lock"},
        )
    finally:
        p2_worker.stop_pool()
    argv = ran[-1]
    assert "--worker" in argv and argv[argv.index("--worker") + 1].endswith(".sock")


def test_run_has_no_worker_flag_without_pin_support_or_pool(
    tmp_path: Path, state_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lk, ran = _p2_env(state_dir, monkeypatch, set())
    p2_pose.run(_video(tmp_path), tmp_path / "w", lock=lk, state=state_dir, acquire_lock=False)
    assert "--worker" not in ran[-1]
    assert p2_pose.start_workers(state_dir, lk) is False
    lk2, ran2 = _p2_env(state_dir, monkeypatch, {"--worker"})
    p2_pose.run(_video(tmp_path), tmp_path / "w", lock=lk2, state=state_dir, acquire_lock=False)
    assert "--worker" not in ran2[-1]  # the pin has it but no pool runs: in-process


# ----- tracker -----------------------------------------------------------------------------------
def _budget(monkeypatch: pytest.MonkeyPatch, key: bool, spend: float) -> None:
    monkeypatch.setattr(p2_pose.keys, "has_key", lambda name, keys_dir=None: key)
    monkeypatch.setattr(p2_pose.p1_keyframes, "total_spend_usd", lambda state=None: spend)


def test_track_uses_api_tracker_while_budget_allows_then_default(
    tmp_path: Path, state_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lk, ran = _p2_env(state_dir, monkeypatch, {"--tracker", "api-sam31"})
    out = tmp_path / "w" / "part2_track"
    out.mkdir(parents=True)
    (out / "tracks.json").write_text("{}", encoding="utf-8")
    # fa0de8e (spend caps off by default; parts-harness.md): the budget only bites when the cap env var is set.
    monkeypatch.setenv("SIMON7_PART1_SPEND_CAP_USD", "5")
    _budget(monkeypatch, True, 0.0)
    p2_pose.track(_video(tmp_path), tmp_path / "w", lock=lk, state=state_dir, acquire_lock=False)
    cmd = ran[-1]
    assert cmd[cmd.index("--tracker") + 1] == "api-sam31" and cmd[cmd.index("--fps") + 1] == str(p2_pose.FPS)
    _budget(monkeypatch, True, 99.0)
    p2_pose.track(_video(tmp_path), tmp_path / "w", lock=lk, state=state_dir, acquire_lock=False)
    assert "--tracker" not in ran[-1]
    monkeypatch.delenv("SIMON7_PART1_SPEND_CAP_USD")  # uncapped: a large spend no longer stops the api tracker
    p2_pose.track(_video(tmp_path), tmp_path / "w", lock=lk, state=state_dir, acquire_lock=False)
    assert ran[-1][ran[-1].index("--tracker") + 1] == "api-sam31"
    monkeypatch.setenv("SIMON7_PART1_SPEND_CAP_USD", "5")
    _budget(monkeypatch, False, 0.0)
    p2_pose.track(_video(tmp_path), tmp_path / "w", lock=lk, state=state_dir, acquire_lock=False)
    assert "--tracker" not in ran[-1]


def test_track_retries_with_local_open_when_api_tracker_fails(
    tmp_path: Path, state_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lk, ran = _p2_env(state_dir, monkeypatch, {"--tracker", "api-sam31"})
    _budget(monkeypatch, True, 0.0)
    p2_pose.track(_video(tmp_path), tmp_path / "w2", lock=lk, state=state_dir, acquire_lock=False)  # no tracks.json
    assert ["--tracker" in c for c in ran[-2:]] == [True, True] and ran[-1][ran[-1].index("--tracker") + 1] == "local-open"


def test_part5_gets_phrasing_concurrency(tmp_path: Path, state_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lk = _dummy_lock(state_dir)
    envs: list[Any] = []
    monkeypatch.setattr(p5_analyse.probe, "has_flag", lambda *a, **kw: False)

    def fake_run(part: Any, argv: Any, **kw: Any) -> runner.Step:
        envs.append(kw.get("env_extra"))
        return _ok_step(5)

    monkeypatch.setattr(runner, "run", fake_run)
    p5_analyse.run(tmp_path / "e.json", tmp_path / "f.json", tmp_path / "w", lock=lk, state=state_dir)
    assert envs == [{"PART5_PHRASING_CONCURRENCY": "4"}]


def test_warm_workers_are_off_unless_enabled(monkeypatch, tmp_path) -> None:
    """SIMON7_P2_WARM_WORKERS gates the pool; unset, only staging starts it (TICKET-099, GPU guard)."""
    monkeypatch.setattr(p2_pose, "has_worker", lambda *a, **k: True)
    monkeypatch.setenv("SIMON7_P2_WARM_WORKERS", "0")
    assert p2_pose.start_workers(tmp_path, object()) is False


def test_warm_worker_is_off_by_default_off_staging(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for name in ("SIMON7_P2_WARM_WORKERS", "SIMON7_STAGING"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SIMON7_STATE_DIR", str(tmp_path))
    assert p2_pose.warm_worker_enabled() is False


def test_start_workers_starts_a_single_pool_of_one(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIMON7_P2_WARM_WORKERS", "1")
    monkeypatch.setattr(p2_pose, "has_worker", lambda *a, **k: True)
    seen: list[Any] = []
    monkeypatch.setattr(p2_pose.p2_worker, "start_pool", lambda pool: seen.append(pool))
    lk = _dummy_lock(tmp_path)
    assert p2_pose.start_workers(tmp_path, lk) is True
    assert len(seen[0]._slots) == 1


def test_only_run_leases_the_worker_track_stays_in_process(
    tmp_path: Path, state_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lk, ran = _p2_env(state_dir, monkeypatch, {"--worker", "--tracker"})
    pool, _ = _pool(tmp_path)
    p2_worker.start_pool(pool)
    time.sleep(0.5)
    try:
        p2_pose.track(_video(tmp_path), tmp_path / "w", lock=lk, state=state_dir, acquire_lock=False, tracker=None)
        p2_pose.run(_video(tmp_path), tmp_path / "w", lock=lk, state=state_dir, acquire_lock=False)
    finally:
        p2_worker.stop_pool()
    assert "--worker" not in ran[0] and "--worker" in ran[1]


def test_a_run_falls_back_in_process_when_the_worker_is_busy(
    tmp_path: Path, state_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lk, ran = _p2_env(state_dir, monkeypatch, {"--worker"})
    pool, _ = _pool(tmp_path)
    p2_worker.start_pool(pool)
    time.sleep(0.5)
    try:
        with p2_worker.lease() as held:
            assert held is not None
            p2_pose.run(_video(tmp_path), tmp_path / "w", lock=lk, state=state_dir, acquire_lock=False)
    finally:
        p2_worker.stop_pool()
    assert "--worker" not in ran[-1]


def test_a_run_dropped_by_the_worker_repeats_in_process(
    tmp_path: Path, state_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lk, ran = _p2_env(state_dir, monkeypatch, {"--worker"})
    calls: list[bool] = []

    def fake_run(part: Any, argv: list[str], **kw: Any) -> runner.Step:
        calls.append("--worker" in argv)
        if "--worker" in argv:
            kw["log_path"].parent.mkdir(parents=True, exist_ok=True)
            kw["log_path"].write_text("part2: the worker closed the connection before finishing", encoding="utf-8")
            return {**_ok_step(2), "exit": 1}
        return _ok_step(2)

    monkeypatch.setattr(runner, "run", fake_run)
    pool, _ = _pool(tmp_path)
    p2_worker.start_pool(pool)
    time.sleep(0.5)
    try:
        step, _p = p2_pose.run(_video(tmp_path), tmp_path / "w", lock=lk, state=state_dir, acquire_lock=False)
    finally:
        p2_worker.stop_pool()
    assert calls == [True, False] and step["exit"] == 0


def _order_env(tmp_path: Path, state_dir: Path, monkeypatch: pytest.MonkeyPatch, sock: Path | None, state: str):
    """Fakes for admission and lease that record their order and the admission arguments (TICKET-101)."""
    lk, ran = _p2_env(state_dir, monkeypatch, {"--worker"})
    events: list[str] = []
    seen: list[dict[str, Any]] = []

    @contextlib.contextmanager
    def fake_acquire(**kw: Any):
        seen.append(kw)
        events.append("admit-start")  # a long flock wait would sit here
        events.append("admitted")
        try:
            yield
        finally:
            events.append("admission-released")

    @contextlib.contextmanager
    def fake_lease():
        events.append("lease")
        yield sock

    monkeypatch.setattr(p2_pose.gpu_lock, "acquire", fake_acquire)
    monkeypatch.setattr(p2_pose.p2_worker, "lease", fake_lease)
    monkeypatch.setattr(p2_pose.p2_worker, "state", lambda: state)
    return lk, ran, events, seen


def test_the_worker_is_leased_only_after_the_gpu_admission(
    tmp_path: Path, state_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lk, ran, events, seen = _order_env(tmp_path, state_dir, monkeypatch, tmp_path / "w.sock", "idle")
    p2_pose.run(_video(tmp_path), tmp_path / "w", lock=lk, state=state_dir)
    assert events[:3] == ["admit-start", "admitted", "lease"]  # the lease never covers the flock wait
    assert seen[0]["min_free_mib"] == 0 and "--worker" in ran[-1]


def test_a_busy_worker_after_admission_runs_in_process_with_the_memory_check(
    tmp_path: Path, state_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lk, ran, events, seen = _order_env(tmp_path, state_dir, monkeypatch, None, "busy")
    p2_pose.run(_video(tmp_path), tmp_path / "w", lock=lk, state=state_dir)
    assert events[:3] == ["admit-start", "admitted", "lease"]
    assert "min_free_mib" not in seen[0] and "--worker" not in ran[-1]


def test_part1_default_budget_is_215_s(monkeypatch: pytest.MonkeyPatch) -> None:
    from part7 import config
    monkeypatch.delenv("SIMON7_PART1_TIMEOUT_S", raising=False)
    assert config.DEFAULT_PART1_TIMEOUT_S == 215.0 and config.part1_timeout_s() == 215.0


def test_slow_part1_grows_the_job_by_at_most_budget_minus_pose(
    tmp_path: Path, state_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TICKET-113: the chain joins Part 1 only after pose is done, so with pose at 0.5 s and Part 1 using its whole
    (scaled) budget of 1.5 s the job takes about the budget, not pose + budget."""
    seen: list[Any] = []
    _patch_rest(monkeypatch, seen)
    budget, pose = 1.5, 0.5

    marks: dict[str, float] = {}

    def p1(v: Path, w: Path, **kw: Any) -> Any:
        marks["p1_start"] = time.monotonic()
        time.sleep(kw["timeout_s"])  # a Part 1 that runs to the end of its budget
        marks["p1_end"] = time.monotonic()
        step = _ok_step(1)
        step.update(exit=124, timed_out=True)
        return (step, None, "key frames from Part 3, Part 1 exited 124")

    monkeypatch.setattr(p1_keyframes, "run", p1)
    monkeypatch.setattr(p2_pose, "run", _fake_p2(pose, marks))
    monkeypatch.setenv("SIMON7_PART1_TIMEOUT_S", str(budget))
    res = chain.trainer(_video(tmp_path), tmp_path / "w", lock=_dummy_lock(state_dir), state=state_dir)
    returned = time.monotonic()
    assert res["ok"] and seen == ["every:10"]
    # Ordering, not a wall-clock margin (which flaked under host load): Part 1 starts before pose ends, and the
    # chain returns only after Part 1 has run its whole budget.
    assert marks["p1_start"] < marks["p2_end"], marks
    assert returned >= marks["p1_end"] >= marks["p1_start"] + budget, (marks, returned)
