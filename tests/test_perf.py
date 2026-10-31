"""Performance work: Part 1 beside Part 2, warm Part 2 workers, picker tracker, phrasing concurrency."""

from __future__ import annotations

from pathlib import Path
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


def _fake_p2(delay: float) -> Any:
    def run(v: Path, w: Path, **kw: Any) -> Any:
        time.sleep(delay)
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

    def p1(v: Path, w: Path, **kw: Any) -> Any:
        time.sleep(0.4)
        return (_ok_step(1), kf, None)

    monkeypatch.setattr(p1_keyframes, "run", p1)
    monkeypatch.setattr(p1_keyframes, "doctor", lambda *a, **kw: _ok_step(6))
    monkeypatch.setattr(p2_pose, "run", _fake_p2(0.4))
    stages: list[str] = []
    t0 = time.monotonic()
    res = chain.trainer(
        _video(tmp_path), tmp_path / "w", report=stages.append, lock=_dummy_lock(state_dir), state=state_dir
    )
    elapsed = time.monotonic() - t0
    assert res["ok"] and res["parts"]["keyframes"] == 1 and seen == [str(kf)]
    assert elapsed < 0.75, elapsed  # sequential would be 0.8 s
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


def _pool(tmp_path: Path, slots: int = 2) -> tuple[p2_worker.Pool, list[_Proc]]:
    procs: list[_Proc] = []
    up: set[str] = set()

    def launcher(argv: list[str], log: Path, cwd: Any, env: Any) -> Any:
        up.add(argv[-1])
        procs.append(_Proc())
        return procs[-1]

    pool = p2_worker.Pool(
        tmp_path, slots, lambda sock: ["serve-worker", "--socket", str(sock)], launcher=launcher,
        health=lambda sock: str(sock) in up, start_wait_s=2.0,
    )
    return pool, procs


def test_pool_leases_one_worker_per_slot_and_never_waits(tmp_path: Path) -> None:
    pool, procs = _pool(tmp_path)
    pool.start()
    time.sleep(0.5)
    with pool.lease() as a, pool.lease() as b, pool.lease() as c:
        assert a != b and a is not None and b is not None and c is None
    with pool.lease() as again:
        assert again in (a, b)
    assert len(procs) == 2
    pool.stop()
    assert all(p.terminated for p in procs)
    with pool.lease() as after_stop:
        assert after_stop is None


def test_pool_restarts_a_dead_worker_on_lease(tmp_path: Path) -> None:
    pool, procs = _pool(tmp_path, slots=1)
    pool.start()
    time.sleep(0.5)
    procs[0].dead = True
    with pool.lease() as sock:
        assert sock is not None
    assert len(procs) == 2
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
    assert p2_pose.start_workers(2, state_dir, lk) is False
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
    _budget(monkeypatch, True, 0.0)
    p2_pose.track(_video(tmp_path), tmp_path / "w", lock=lk, state=state_dir, acquire_lock=False)
    cmd = ran[-1]
    assert cmd[cmd.index("--tracker") + 1] == "api-sam31" and cmd[cmd.index("--fps") + 1] == str(p2_pose.FPS)
    _budget(monkeypatch, True, 99.0)
    p2_pose.track(_video(tmp_path), tmp_path / "w", lock=lk, state=state_dir, acquire_lock=False)
    assert "--tracker" not in ran[-1]
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
    """SIMON7_P2_WARM_WORKERS gates the pool (off by default after the staging stall of 2026-10-30)."""
    monkeypatch.delenv("SIMON7_P2_WARM_WORKERS", raising=False)
    monkeypatch.setattr(p2_pose, "has_worker", lambda *a, **k: True)
    assert p2_pose.start_workers(2, tmp_path, object()) is False
