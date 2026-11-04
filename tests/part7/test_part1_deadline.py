"""TICKET-380: Part 7 gives Part 1 `SIMON_P1_DEADLINE` from the step's time budget, and a run that gives up because no
time is left reads as a cut under the final-line rule (docs/specs/processor.md AC-R11, AC-R12)."""

from __future__ import annotations

import contextlib
from pathlib import Path
import subprocess
import time
from typing import Any, Iterator

import pytest

from part7 import config, part1_breaker, runner
from part7.parts import p1_keyframes

# Part 1's bytes at fe09c43: exit 1 from track_people with a near deadline, stream stubbed, frame count from the stub.
GAVE_UP = "  SAM 3.1 stream cut after 9 frames (IncompleteRead); giving up (no time left for another try)\n"
TRACEBACK = "Traceback (most recent call last):\n  File \"meta_client.py\", line 239, in track_people\n"
STREAM_CUT = "keyframe_finder.meta_client.StreamCut: SAM 3.1 stream cut after 9 frames (IncompleteRead)\n"


class _Lock:
    def __init__(self, clone: Path) -> None:
        self.clone = clone

    def path(self, part: Any) -> Path:
        return self.clone

    def sha12(self, part: Any) -> str:
        return "fe09c4357719"

    def sha(self, part: Any) -> str:
        return "fe09c43577197e1d7ffb6348c5ad038e09929fe0"


def _offline(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Path, Path]:
    """The adapter with no key and no ledger behind it; returns the clip and the job's work folder."""
    @contextlib.contextmanager
    def dotenv(*a: Any, **k: Any) -> Iterator[bool]:
        yield True

    monkeypatch.setattr(p1_keyframes, "total_spend_usd", lambda *a, **k: 0.0)
    monkeypatch.setattr(p1_keyframes.keys, "has_key", lambda *a, **k: True)
    monkeypatch.setattr(p1_keyframes.keys, "part1_dotenv", dotenv)
    video = tmp_path / "person.mp4"
    video.write_bytes(b"video bytes")
    return video, tmp_path / "jobs" / "cccccccccccc" / "work" / "trainer"


def _answer(monkeypatch: pytest.MonkeyPatch, seen: list[dict[str, Any]], step: dict[str, Any]) -> None:
    def fake_run(part: Any, argv: list[str], **kw: Any) -> runner.Step:
        seen.append(kw)
        return runner.Step(part=1, duration_s=30.0, log=str(kw["log_path"]), **step)

    monkeypatch.setattr(p1_keyframes.runner, "run", fake_run)


@pytest.mark.parametrize("budget", [90.0, 240.0])
def test_the_deadline_follows_the_budget_of_this_call(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, budget: float) -> None:
    video, work = _offline(monkeypatch, tmp_path)
    seen: list[dict[str, Any]] = []
    _answer(monkeypatch, seen, {"exit": 0, "timed_out": False, "stdout": "ok"})
    before = time.time()
    p1_keyframes.run(video, work, lock=_Lock(tmp_path / "clone"), state=tmp_path / "state", timeout_s=budget)  # type: ignore[arg-type]
    after = time.time()
    raw = seen[0]["env_extra"][p1_keyframes.DEADLINE_ENV]
    assert raw == str(int(raw))  # whole Unix seconds, which Part 1 reads with float()
    margin = p1_keyframes.DEADLINE_BEFORE_KILL_S
    term, grace = p1_keyframes._stop_times(budget)
    assert seen[0]["timeout_s"] == term and seen[0]["kill_grace_s"] == grace and term + grace == budget
    assert before + term - margin - 1 <= int(raw) <= after + term - margin


def test_the_default_budget_gets_a_deadline_too(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    video, work = _offline(monkeypatch, tmp_path)
    seen: list[dict[str, Any]] = []
    _answer(monkeypatch, seen, {"exit": 0, "timed_out": False, "stdout": "ok"})
    before = time.time()
    p1_keyframes.run(video, work, lock=_Lock(tmp_path / "clone"), state=tmp_path / "state")  # type: ignore[arg-type]
    term = p1_keyframes._stop_times(config.TIMEOUTS["1"])[0]
    assert int(seen[0]["env_extra"][p1_keyframes.DEADLINE_ENV]) >= before + term - p1_keyframes.DEADLINE_BEFORE_KILL_S - 1


def test_the_process_receives_the_deadline_and_it_is_earlier_than_the_kill(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The real runner and a real child that outlives its budget. SIGTERM cannot come before `Popen` plus its time, and
    the deadline is read before `Popen`, so this holds however loaded the host is."""
    video, work = _offline(monkeypatch, tmp_path)
    monkeypatch.setattr(p1_keyframes, "DEADLINE_BEFORE_KILL_S", 1.0)
    monkeypatch.setenv(p1_keyframes.DEADLINE_ENV, "1")  # a stale value in Part 7's own environment must not reach the child
    clone = tmp_path / "clone"
    fake_python = clone / ".venv" / "bin" / "python"
    fake_python.parent.mkdir(parents=True)
    fake_python.write_text('#!/bin/sh\nprintf %s "$SIMON_P1_DEADLINE" > seen_deadline\nexec sleep 30\n', encoding="utf-8")
    fake_python.chmod(0o755)

    started: list[float] = []
    real_popen = subprocess.Popen

    def popen(*a: Any, **k: Any) -> Any:
        started.append(time.time())
        return real_popen(*a, **k)

    monkeypatch.setattr(runner.subprocess, "Popen", popen)
    budget = 4.0
    term = p1_keyframes._stop_times(budget)[0]
    step, keyframes, note = p1_keyframes.run(video, work, lock=_Lock(clone), state=tmp_path / "state", timeout_s=budget)  # type: ignore[arg-type]
    assert step is not None and step.get("timed_out") and keyframes is None and step["duration_s"] >= term
    deadline = float((clone / "seen_deadline").read_text(encoding="utf-8"))
    assert 1 < deadline < started[0] + term


def test_no_time_left_reads_as_a_cut_with_its_own_log_wording(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    video, work = _offline(monkeypatch, tmp_path)
    state = tmp_path / "state"
    monkeypatch.setenv(part1_breaker.ENV, "on")
    _answer(monkeypatch, [], {"exit": 1, "timed_out": False, "stdout": GAVE_UP + TRACEBACK + STREAM_CUT})
    recorded: list[str] = []
    real_record = part1_breaker.record
    monkeypatch.setattr(part1_breaker, "record", lambda outcome, st: recorded.append(outcome) or real_record(outcome, st))
    step, keyframes, note = p1_keyframes.run(video, work, lock=_Lock(tmp_path / "clone"), state=state, timeout_s=90.0)  # type: ignore[arg-type]
    assert keyframes is None and note == p1_keyframes.CUT_NOTE == "key frames from Part 3, Part 1 lost its network stream"
    assert recorded == ["transient"]
    log = (tmp_path / "jobs" / "cccccccccccc" / "steps" / "part7.log").read_text(encoding="utf-8")
    assert "Part 1 lost its network stream after 30.0 s, no time left for another try: keyframe_finder.meta_client.StreamCut" in log
    assert "its own retry included" not in log and "tried again after a cut" not in log


def test_the_page_names_that_note_as_a_lost_connection() -> None:
    """The page reads the job note, never Part 1's output (`tests/part7/keyframes-note.dom.test.mjs` runs the mapping)."""
    page = (config.REPO_ROOT / "web" / "keyframes-note.js").read_text(encoding="utf-8")
    assert '["lost its network stream", "lost its connection on this take."]' in page
    assert "lost its network stream" in p1_keyframes.CUT_NOTE


@pytest.mark.parametrize(("stdout", "cut"), [
    (GAVE_UP + TRACEBACK + STREAM_CUT, True),
    (GAVE_UP, False),  # the line alone ended nothing: only the exception on the final line counts
    (GAVE_UP + TRACEBACK + "RuntimeError: Meta API 500 on /responses: bad gateway\n", False),
])
def test_the_final_line_decides_not_the_giving_up_line(stdout: str, cut: bool) -> None:
    step = runner.Step(part=1, exit=1, timed_out=False, duration_s=1.0, log="x", stdout=stdout)
    assert p1_keyframes.transient_failure(step) is cut
