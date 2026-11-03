"""Judge-URL warm-up of the warm Part 2 worker (docs/specs/p2-warmup.md, TICKET-260 warm-up half)."""

from __future__ import annotations

import contextlib
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from part7 import gpu_lock, judge_view, p2_warmup, p2_worker
from part7.parts import p2_pose
from support import Api


REAL_LIFE = p2_worker.worker_life


class Queue:
    def __init__(self, running: int = 0, waiting: int = 0) -> None:
        self.n = {"running": running, "waiting": waiting}

    def counts(self) -> dict[str, int]:
        return self.n


def fake_app(tmp_path: Path, running: int = 0, waiting: int = 0) -> Any:
    return SimpleNamespace(backend="gpu", queue=Queue(running, waiting), state=tmp_path, lock=object())


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    p2_warmup.reset()
    monkeypatch.setenv(judge_view.PROFILE_ENV, "submission")
    monkeypatch.delenv("SIMON7_P2_WARM_WORKERS", raising=False)
    monkeypatch.setenv("SIMON7_STAGING", "1")  # GPU guard: only the staging server keeps a warm worker to prime
    monkeypatch.setattr(p2_worker, "state", lambda: "idle")
    monkeypatch.setattr(p2_worker, "worker_life", lambda: 4242)
    monkeypatch.setattr(gpu_lock, "lock_holder_pid", lambda path: None)


class Started:
    """Replaces the background thread so a test decides when the warm-up body runs."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.targets: list[Any] = []
        monkeypatch.setattr(p2_warmup.threading, "Thread", lambda target, args, **kw: SimpleNamespace(
            start=lambda: self.targets.append((target, args))))


# ----- the page decides -----------------------------------------------------------------------------------
@pytest.mark.parametrize("query,default,expected", [
    ("", "submission", True), ("profile=submission", "", True), ("profile=default", "submission", False),
    ("", "", False), ("x=1", "", False), ("profile=submission&x=1", "", True),
])
def test_only_the_judge_page_asks_for_a_warmup(monkeypatch: pytest.MonkeyPatch, query: str, default: str, expected: bool) -> None:
    monkeypatch.setenv(judge_view.PROFILE_ENV, default)
    assert p2_warmup.wanted(query) is expected


def test_a_free_idle_worker_on_the_judge_page_starts_one_warmup(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    run = Started(monkeypatch)
    assert p2_warmup.maybe_start(fake_app(tmp_path)) == "started"
    assert len(run.targets) == 1


def test_it_runs_once_per_worker_life_and_again_after_a_restart(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    run = Started(monkeypatch)
    app = fake_app(tmp_path)
    assert p2_warmup.maybe_start(app) == "started"
    p2_warmup._running = False  # the first one ended
    assert p2_warmup.maybe_start(app) == "already warmed or running"
    monkeypatch.setattr(p2_worker, "worker_life", lambda: 4343)  # the worker restarted: a new life
    assert p2_warmup.maybe_start(app) == "started"
    assert len(run.targets) == 2


def test_one_runs_at_a_time(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    Started(monkeypatch)
    app = fake_app(tmp_path)
    assert p2_warmup.maybe_start(app) == "started"
    monkeypatch.setattr(p2_worker, "worker_life", lambda: 5)
    assert p2_warmup.maybe_start(app) == "already warmed or running"


# ----- AC: never beside a take, a held lock or a busy worker (negative assertions) ---------------------------
def test_a_running_or_queued_take_blocks_it(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    run = Started(monkeypatch)
    assert p2_warmup.maybe_start(fake_app(tmp_path, running=1)) == "a take is queued or running"
    assert p2_warmup.maybe_start(fake_app(tmp_path, waiting=1)) == "a take is queued or running"
    assert run.targets == []


def test_a_held_gpu_lock_blocks_it(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    run = Started(monkeypatch)
    monkeypatch.setattr(gpu_lock, "lock_holder_pid", lambda path: 99)
    assert p2_warmup.maybe_start(fake_app(tmp_path)) == "GPU lock held by pid 99"
    assert run.targets == []
    assert p2_warmup._warmed == set()  # a skipped warm-up does not use up the worker's one try


@pytest.mark.parametrize("state", ["busy", "starting", "down", "off", "released"])
def test_a_worker_that_is_not_idle_blocks_it(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, state: str) -> None:
    run = Started(monkeypatch)
    monkeypatch.setattr(p2_worker, "state", lambda: state)
    assert p2_warmup.maybe_start(fake_app(tmp_path)) == f"worker {state}"
    assert run.targets == []


def test_the_full_app_page_and_a_cpu_host_do_not_warm(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    run = Started(monkeypatch)
    monkeypatch.setenv(judge_view.PROFILE_ENV, "")
    assert p2_warmup.maybe_start(fake_app(tmp_path)) == "not the judge page"
    monkeypatch.setenv(judge_view.PROFILE_ENV, "submission")
    app = fake_app(tmp_path)
    app.backend = "cpu"
    assert p2_warmup.maybe_start(app) == "no warm worker"
    monkeypatch.setenv("SIMON7_P2_WARM_WORKERS", "0")
    assert p2_warmup.maybe_start(fake_app(tmp_path)) == "no warm worker"
    monkeypatch.delenv("SIMON7_P2_WARM_WORKERS")
    monkeypatch.delenv("SIMON7_STAGING")
    assert p2_warmup.maybe_start(fake_app(tmp_path)) == "no warm worker", "a lane or dev server has no warm worker (GPU guard)"
    assert run.targets == []


# ----- the body --------------------------------------------------------------------------------------------
def logged(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    lines: list[str] = []
    monkeypatch.setattr(p2_warmup.applog, "log", lambda msg, *a, **kw: lines.append(msg))
    return lines


def test_the_body_runs_one_step_on_the_leased_socket_and_logs_the_seconds(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    lines = logged(monkeypatch)
    seen: list[Any] = []
    monkeypatch.setattr(gpu_lock, "acquire", lambda **kw: contextlib.nullcontext())
    monkeypatch.setattr(p2_worker, "lease", lambda: contextlib.nullcontext(tmp_path / "w0.sock"))
    monkeypatch.setattr(p2_pose, "warmup_step", lambda state, lk, sock: seen.append(sock) or ({"exit": 0}, ""))
    p2_warmup._running = True
    p2_warmup._run(fake_app(tmp_path))
    assert seen == [tmp_path / "w0.sock"]
    assert len(lines) == 1 and lines[0].startswith("p2_warmup seconds=") and lines[0].endswith("exit=0")
    assert p2_warmup._running is False


def test_a_take_that_arrives_after_the_turn_gets_the_worker(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    lines = logged(monkeypatch)
    monkeypatch.setattr(gpu_lock, "acquire", lambda **kw: contextlib.nullcontext())
    monkeypatch.setattr(p2_worker, "lease", lambda: pytest.fail("the warm-up must not lease beside a take"))
    p2_warmup._run(fake_app(tmp_path, running=1))
    assert "exit=skipped" in lines[0]


def test_a_busy_gpu_and_a_crash_are_logged_not_raised(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    lines = logged(monkeypatch)

    def busy(**kw: Any) -> Any:
        raise TimeoutError("busy")

    monkeypatch.setattr(gpu_lock, "acquire", busy)
    p2_warmup._run(fake_app(tmp_path))
    monkeypatch.setattr(gpu_lock, "acquire", lambda **kw: contextlib.nullcontext())
    monkeypatch.setattr(p2_worker, "lease", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    p2_warmup._run(fake_app(tmp_path))
    assert "exit=gpu busy" in lines[0] and "exit=error" in lines[1]


# ----- the step ---------------------------------------------------------------------------------------------
def test_the_step_sends_one_fixture_frame_through_the_worker(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    clone = tmp_path / "part-2"
    frames = clone / "fixtures" / "input" / "single" / "frames"
    frames.mkdir(parents=True)
    (frames / "000000.jpg").write_bytes(b"jpg")
    (frames / "000001.jpg").write_bytes(b"jpg")
    captured: dict[str, Any] = {}
    monkeypatch.setattr(p2_pose, "has_mesh", lambda lk, c: True)
    monkeypatch.setattr(p2_pose, "_launch", lambda sub, sock, work, log, lk, c, backend: captured.update(sub=sub, sock=sock) or {"exit": 0})
    state = tmp_path / "state"
    step, why = p2_pose.warmup_step(state, SimpleNamespace(path=lambda n: clone), Path("/x/w0.sock"))
    assert step == {"exit": 0} and why == ""
    assert sorted(p.name for p in (state / "p2-warmup" / "in").iterdir()) == ["000000.jpg"]
    assert captured["sock"] == Path("/x/w0.sock") and captured["sub"][0] == "run" and "--mesh" in captured["sub"]


def test_a_missing_fixture_is_a_reason_not_a_crash(tmp_path: Path) -> None:
    step, why = p2_pose.warmup_step(tmp_path, SimpleNamespace(path=lambda n: tmp_path / "none"), Path("/x/w0.sock"))
    assert step is None and "fixture" in why


def test_worker_life_is_the_running_pid_or_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(p2_worker, "_POOL", None)
    assert REAL_LIFE() is None  # no pool in this process
    pool = p2_worker.Pool.__new__(p2_worker.Pool)
    pool._lock = threading.Condition()
    pool._slots = [SimpleNamespace(proc=SimpleNamespace(pid=77, poll=lambda: None))]
    assert pool.life() == 77
    monkeypatch.setattr(p2_worker, "_POOL", pool)
    assert REAL_LIFE() == 77
    pool._slots = [SimpleNamespace(proc=SimpleNamespace(pid=77, poll=lambda: 1))]
    assert pool.life() is None


# ----- the page-load hook -----------------------------------------------------------------------------------
def test_loading_the_page_asks_for_a_warmup_with_its_query(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    (api.app.web_dir / "index.html").write_text("<head></head>", encoding="utf-8")
    asked: list[str] = []
    monkeypatch.setattr(p2_warmup, "maybe_start", lambda app, query="": asked.append(query) or "started")
    assert api.request("GET", "?profile=submission")[0] == 200
    assert asked == ["profile=submission"]
    assert api.request("GET", "api/config")[0] in (200, 404)
    assert asked == ["profile=submission"]  # an API call is not a page load
