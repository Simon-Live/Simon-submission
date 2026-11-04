"""TICKET-089: Part 1 circuit breaker (processor.md "Fallbacks"), fake clock and fake runner."""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any, Iterator

import pytest

from part7 import part1_breaker as pb
from part7.parts import p1_keyframes
from part7 import runner

T0 = 1_700_000_000.0
MIN = 60.0


class Clock:
    def __init__(self) -> None:
        self.t = T0

    def __call__(self) -> float:
        return self.t


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    c = Clock()
    monkeypatch.setattr(pb, "_now", c)
    monkeypatch.setenv(pb.ENV, "on")
    return c


def _fail3(state: Path, clock: Clock) -> float:
    opened = 0.0
    for _ in range(3):
        opened = pb.record("transient", state)
        clock.t += MIN
    return opened


def test_three_transient_failures_open_for_20_minutes(tmp_path: Path, clock: Clock) -> None:
    assert pb.record("transient", tmp_path) == 0.0 and pb.record("transient", tmp_path) == 0.0
    assert pb.allow(tmp_path) == (True, 0.0)
    until = pb.record("transient", tmp_path)
    assert until == T0 + 20 * MIN
    ok, got = pb.allow(tmp_path)
    assert (ok, got) == (False, until)
    assert pb.pause_note(until) == "key frames from Part 3, Part 1 paused after repeated network failures (until 22:33Z)"


def test_failures_older_than_30_minutes_do_not_count(tmp_path: Path, clock: Clock) -> None:
    pb.record("transient", tmp_path)
    pb.record("transient", tmp_path)
    clock.t += 31 * MIN
    assert pb.record("transient", tmp_path) == 0.0


def test_a_good_or_other_run_ends_the_streak(tmp_path: Path, clock: Clock) -> None:
    pb.record("transient", tmp_path)
    pb.record("transient", tmp_path)
    pb.record("other", tmp_path)
    assert pb.record("transient", tmp_path) == 0.0
    pb.record("ok", tmp_path)
    assert pb.allow(tmp_path) == (True, 0.0)


def test_half_open_allows_one_probe_and_success_closes(tmp_path: Path, clock: Clock) -> None:
    until = _fail3(tmp_path, clock)
    clock.t = until + 1
    assert pb.allow(tmp_path) == (True, 0.0)  # the probe
    assert pb.allow(tmp_path)[0] is False  # a second caller waits for the probe
    assert pb.record("ok", tmp_path) == 0.0
    assert pb.allow(tmp_path) == (True, 0.0) and pb.allow(tmp_path) == (True, 0.0)


def test_failed_probe_doubles_the_window_up_to_2_hours(tmp_path: Path, clock: Clock) -> None:
    until = _fail3(tmp_path, clock)
    windows = []
    for _ in range(5):
        clock.t = until + 1
        assert pb.allow(tmp_path)[0] is True
        until = pb.record("transient", tmp_path)
        windows.append(round((until - clock.t) / MIN))
    assert windows == [40, 80, 120, 120, 120]


def test_a_probe_that_never_reported_does_not_block_forever(tmp_path: Path, clock: Clock) -> None:
    until = _fail3(tmp_path, clock)
    clock.t = until + 1
    assert pb.allow(tmp_path)[0] is True
    clock.t += pb.PROBE_STALE_S + 1
    assert pb.allow(tmp_path)[0] is True


def test_disabled_by_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(pb.ENV, "off")
    assert pb.enabled() is False
    monkeypatch.setenv(pb.ENV, "on")
    assert pb.enabled() is True


# ----- through the adapter ---------------------------------------------------------------------------------------


class _Lock:
    def __init__(self, clone: Path) -> None:
        self.clone = clone

    def path(self, part: Any) -> Path:
        return self.clone

    def sha12(self, part: Any) -> str:
        return "e84e92b1d0b1"


def _adapter(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, state: Path, outcomes: list[dict[str, Any]]) -> Any:
    calls: list[int] = []

    @contextlib.contextmanager
    def dotenv(*a: Any, **k: Any) -> Iterator[bool]:
        yield True

    def fake_run(part: Any, argv: list[str], cwd: Path, env_extra: dict[str, str], timeout_s: float, log_path: Path,
                 lock: Any, kill_grace_s: float, **kw: Any) -> runner.Step:
        out = outcomes[len(calls)]
        calls.append(1)
        if out["exit"] == 0:
            stem = Path(argv[-1]).stem
            (cwd / "out" / stem).mkdir(parents=True, exist_ok=True)
            (cwd / "out" / stem / "keyframes.json").write_text("{}", encoding="utf-8")
        return runner.Step(part=1, exit=out["exit"], timed_out=out.get("timed_out", False), duration_s=90.0,
                           log=str(log_path), stdout=out.get("stdout", ""))

    monkeypatch.setattr(p1_keyframes, "total_spend_usd", lambda *a, **k: 0.0)
    monkeypatch.setattr(p1_keyframes.keys, "has_key", lambda *a, **k: True)
    monkeypatch.setattr(p1_keyframes.keys, "part1_dotenv", dotenv)
    monkeypatch.setattr(p1_keyframes.runner, "run", fake_run)
    video = tmp_path / "person.mp4"
    video.write_bytes(b"video bytes")

    def call() -> tuple[Any, Any, Any]:
        work = tmp_path / "jobs" / "cccccccccccc" / "work"
        return p1_keyframes.run(video, work, lock=_Lock(tmp_path / "clone"), state=state, timeout_s=90.0)  # type: ignore[arg-type]

    return calls, call


def test_adapter_opens_skips_without_a_call_and_probes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
                                                       clock: Clock) -> None:
    state = tmp_path / "state"
    timeout = {"exit": None, "timed_out": True}
    calls, call = _adapter(monkeypatch, tmp_path, state, [timeout] * 3 + [{"exit": 0}])
    for _ in range(3):
        call()
        clock.t += MIN
    assert len(calls) == 3
    step, kf, note = call()  # open: no Meta call
    assert (step, kf) == (None, None) and len(calls) == 3
    assert note is not None and "paused after repeated network failures (until 22:35Z)" in note
    log = (tmp_path / "jobs" / "cccccccccccc" / "steps" / "part7.log").read_text(encoding="utf-8")
    assert "ANOMALY part1_circuit_open" in log and "part 1 circuit open until 22:35Z" in log
    clock.t = T0 + 25 * MIN
    step, kf, note = call()  # the half-open probe succeeds and closes the circuit
    assert len(calls) == 4 and kf is not None and note is None
    assert pb.allow(state) == (True, 0.0)


def test_adapter_counts_cut_streams_but_not_other_exits(monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
                                                        clock: Clock) -> None:
    state = tmp_path / "state"
    cut = {"exit": 1, "stdout": "IncompleteRead(5 bytes read)"}
    other = {"exit": 2, "stdout": "bad clip"}
    calls, call = _adapter(monkeypatch, tmp_path, state, [cut, cut, other, cut, cut])
    for _ in range(5):
        call()
    assert len(calls) == 5 and pb.allow(state) == (True, 0.0)


def test_adapter_counts_stream_cut_without_another_marker(monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
                                                          clock: Clock) -> None:
    """TICKET-380: a stream closed without `response.completed` is a network failure, not `other`."""
    state = tmp_path / "state"
    closed = {"exit": 1, "stdout": "StreamCut: SAM 3.1 stream closed after 12 frames without response.completed"}
    calls, call = _adapter(monkeypatch, tmp_path, state, [closed] * 3)
    for _ in range(3):
        call()
    assert len(calls) == 3 and pb.allow(state)[0] is False


def test_adapter_does_not_pause_part1_for_failures_after_a_survived_cut(monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
                                                                        clock: Clock) -> None:
    """B1: three runs that each survived a cut and then failed on something else leave Part 1 running."""
    state = tmp_path / "state"
    later = {"exit": 1, "stdout": "  SAM 3.1 stream cut after 58 frames (IncompleteRead); trying again\n"
                                  "RuntimeError: Meta API 500 on /responses/input_tokens: x\n"}
    calls, call = _adapter(monkeypatch, tmp_path, state, [later] * 3)
    for _ in range(3):
        call()
    assert len(calls) == 3 and pb.allow(state) == (True, 0.0)


def test_adapter_ignores_the_breaker_when_off(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, clock: Clock) -> None:
    monkeypatch.setenv(pb.ENV, "off")
    state = tmp_path / "state"
    calls, call = _adapter(monkeypatch, tmp_path, state, [{"exit": None, "timed_out": True}] * 5)
    for _ in range(5):
        call()
    assert len(calls) == 5 and not (state / "part1_health.json").exists()
