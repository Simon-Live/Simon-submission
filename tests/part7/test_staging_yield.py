"""TICKET-089: check-7 yields to live staging jobs (check-7.md "Yielding to staging")."""

from __future__ import annotations

import json
import os
from pathlib import Path
import time
from typing import Any

import pytest

from part7 import chain, check7, modules, staging_live
from support import stub_modules


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(staging_live.ENV_IGNORE, raising=False)
    monkeypatch.delenv(staging_live.ENV_YIELD_MAX, raising=False)


def _job(state: Path, name: str, status: str, age_s: float = 0.0, now: float | None = None) -> None:
    now = time.time() if now is None else now
    d = state / "jobs" / name
    d.mkdir(parents=True)
    f = d / "job.json"
    f.write_text(json.dumps({"id": name, "status": status}), encoding="utf-8")
    os.utime(f, (now - age_s, now - age_s))


def test_live_jobs_counts_fresh_queued_and_running_only(tmp_path: Path) -> None:
    now = 1_000_000.0
    _job(tmp_path, "a", "queued", now=now)
    _job(tmp_path, "b", "running", 60, now=now)
    _job(tmp_path, "c", "done", now=now)
    _job(tmp_path, "d", "failed", now=now)
    _job(tmp_path, "e", "running", 31 * 60, now=now)  # died with its server
    (tmp_path / "jobs" / "f").mkdir()
    (tmp_path / "jobs" / "f" / "job.json").write_text("{not json")
    assert staging_live.live_jobs(tmp_path, now=lambda: now) == 2
    assert staging_live.live_jobs(tmp_path / "none") == 0


class Clock:
    def __init__(self) -> None:
        self.t = 0.0
        self.sleeps: list[float] = []

    def now(self) -> float:
        return self.t

    def sleep(self, s: float) -> None:
        self.sleeps.append(s)
        self.t += s


def test_at_start_defers_with_the_count() -> None:
    gate = staging_live.Gate(count=lambda: 3)
    with pytest.raises(staging_live.Deferred, match="staging has 3 live job"):
        gate.at_start()
    staging_live.Gate(count=lambda: 0).at_start()


def test_mid_run_waits_until_staging_is_quiet() -> None:
    clock, counts = Clock(), [2, 1, 0]
    gate = staging_live.Gate(count=lambda: counts.pop(0), max_wait_s=100, clock=clock.now, sleep=clock.sleep)
    gate.before_stage("direct")
    assert clock.sleeps == [15.0, 15.0] and counts == []


def test_mid_run_defers_after_the_max_wait() -> None:
    clock = Clock()
    gate = staging_live.Gate(count=lambda: 1, max_wait_s=60, clock=clock.now, sleep=clock.sleep)
    with pytest.raises(staging_live.Deferred, match="staging has 1 live job"):
        gate.before_stage("direct")
    assert clock.t == 60.0


def test_env_sets_the_max_wait_and_the_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(staging_live.ENV_YIELD_MAX, "30")
    clock = Clock()
    gate = staging_live.Gate(count=lambda: 1, clock=clock.now, sleep=clock.sleep)
    with pytest.raises(staging_live.Deferred):
        gate.before_stage()
    assert clock.t == 30.0
    monkeypatch.setenv(staging_live.ENV_IGNORE, "1")
    ign = staging_live.Gate(count=lambda: 5)
    ign.at_start()
    ign.before_stage()


def test_cli_check_defers_at_start_with_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                              capsys: pytest.CaptureFixture[str]) -> None:
    _job(tmp_path, "a", "running")
    monkeypatch.setattr(staging_live.config, "staging_dir", lambda state=None: tmp_path)
    monkeypatch.setattr(modules, "load", lambda: pytest.fail("work started"))
    assert check7.cli_check() == 2
    out, err = capsys.readouterr()
    assert err.strip() == "check-7: deferred: staging has 1 live job(s)"
    assert json.loads(out) == {"part": 7, "pass": False, "deferred": True, "reason": "staging has 1 live job(s)"}


def test_cli_check_ignore_override_proceeds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                            capsys: pytest.CaptureFixture[str]) -> None:
    _job(tmp_path, "a", "running")
    monkeypatch.setattr(staging_live.config, "staging_dir", lambda state=None: tmp_path)
    monkeypatch.setenv(staging_live.ENV_IGNORE, "1")
    monkeypatch.setattr(modules, "load", lambda: stub_modules(Path("unused-modules")))
    monkeypatch.setattr(check7, "gpu_visible", lambda: False)
    assert check7.cli_check() == 2
    assert "nvidia-smi found no GPU" in capsys.readouterr().err


def test_gate_runs_before_each_gpu_stage(tmp_path: Path) -> None:
    seen: list[str] = []

    class Boom(Exception):
        pass

    def gate(label: str) -> None:
        seen.append(label)
        raise Boom

    app = check7.AppClient("http://127.0.0.1:1/", gate=gate)
    with pytest.raises(Boom):
        app.trainer(tmp_path / "c.mp4", "x")
    with pytest.raises(Boom):
        app.follow(tmp_path / "c.mp4", "e")
    direct = check7.DirectPath(stub_modules(Path("unused-modules")), tmp_path, gate=gate)
    with pytest.raises(Boom):
        direct._pose(tmp_path / "t" / "clip.mp4", tmp_path)
    assert seen == ["app path, trainer", "app path, follower", "direct path, Part 2 on t"]


def test_mid_run_deferral_exits_2_with_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                            capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(staging_live.config, "staging_dir", lambda state=None: tmp_path)
    monkeypatch.setattr(modules, "load", lambda: stub_modules(Path("unused-modules")))
    monkeypatch.setattr(check7, "prerequisites", lambda lock: None)
    monkeypatch.setattr(check7.videos, "load_manifest", lambda: {"clips": []})
    monkeypatch.setattr(check7.movement, "check_movement", lambda: {})
    monkeypatch.setattr(check7.config, "check_dir", lambda: tmp_path / "check")
    monkeypatch.setattr(check7, "_wait_healthy", lambda c, p: None)
    monkeypatch.setattr(check7, "_stop", lambda p: None)
    monkeypatch.setattr(check7.subprocess, "Popen", lambda *a, **k: object())

    def deferred(*a: Any, **k: Any) -> None:
        raise staging_live.Deferred("staging has 2 live job(s)")

    monkeypatch.setattr(check7, "run_check", deferred)
    monkeypatch.setattr(check7.AppClient, "health", lambda self: {})
    assert check7.cli_check() == 2
    out, err = capsys.readouterr()
    assert "check-7: deferred: staging has 2 live job(s)" in err
    assert json.loads(out)["deferred"] is True


def test_part1_timeout_warning_carries_the_load(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chain.os, "getloadavg", lambda: (42.43, 30.0, 20.0))
    assert chain._load_1m() == "42.4"

    def nope() -> tuple[float, float, float]:
        raise OSError

    monkeypatch.setattr(chain.os, "getloadavg", nope)
    assert chain._load_1m() == "unknown"


def test_part1_timeout_logs_the_load_in_the_job_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    work = tmp_path / "jobs" / "abc123def456" / "work"
    work.mkdir(parents=True)
    step = {"part": 1, "exit": None, "timed_out": True, "duration_s": 150.0}
    monkeypatch.setattr(chain.p1_keyframes, "run", lambda *a, **k: (step, None, "x"))
    monkeypatch.setattr(chain.os, "getloadavg", lambda: (42.4, 1.0, 1.0))
    run = chain._Run(tmp_path / "v.mp4", None, {})
    assert chain._keyframes(run, tmp_path / "v.mp4", work, stub_modules(Path("unused-modules")), None, None) == (None, 3)
    log = (work.parent / "steps" / "part7.log").read_text(encoding="utf-8")
    assert "Part 1 timed out after 150 s (load 42.4)" in log
