"""TICKET-388: a Part 1 run the budget stops deletes its upload, exits 143 and has the time to do so, inside the budget;
the upload and delete lines reach `part7.log` (docs/specs/processor.md AC-R13 to AC-R15). No network anywhere here."""

from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any, Iterator

import pytest

from part7 import config, part1_breaker, runner
from part7.parts import p1_keyframes

JOB = "cccccccccccc"
# Part 1's bytes at cdd4a522 around the upload, with a delete that takes `delete_s` and answers from `.env` like the real one.
FAKE_PART1 = """#!{python}
import pathlib, signal, time
def stop(signum, frame):
    raise SystemExit(128 + signum)
signal.signal(signal.SIGTERM, stop)
print("  uploading", flush=True)
try:
    print("  uploaded file_id=file-7", flush=True)
    time.sleep(60)
finally:
    time.sleep({delete_s})
    pathlib.Path("deleted").write_text("yes")
    if pathlib.Path(".env").is_file():
        print("  delete_file ok file_id=file-7", flush=True)
    else:
        print("  delete_file failed file_id=file-7: MODEL_API_KEY is missing. Add it to .env.", flush=True)
"""
# The real `main`, `process`, handler and `delete_file` of a Part 1 checkout, with everything that would reach Meta or
# need a real clip replaced. The sockets refuse too, so a call that slipped through fails instead of spending.
REAL_PART1_DRIVER = """
import os, socket, sys, time
from pathlib import Path
def no_network(*a, **k):
    raise OSError("no network in this test")
socket.create_connection = socket.getaddrinfo = no_network
sys.path.insert(0, {checkout!r})
from keyframe_finder import from_video as fv, meta_client as mc
class Decision:
    verdict, width, filtergraph, crf = "ok", 640, "", 23
    def as_dict(self):
        return {{}}
class Answer:
    def __enter__(self):
        return self
    def __exit__(self, *exc):
        return False
def slow_answer(method, path, **kw):
    assert method == "DELETE"
    time.sleep(1)
    return Answer()
scratch = Path({scratch!r})
fv.assess = lambda path: Decision()
fv.format_report = lambda decision, name: "report"
fv.media_info = lambda path: {{"duration_s": 5.0, "fps": 30.0, "width": 640, "height": 360}}
fv.transcode = lambda *a, **k: None
fv.saved_paths = lambda stem: (scratch / "run.json", scratch / "tracks.json", scratch / "spark.txt")
fv.upload_video = lambda work: "file-real"
fv.track_people = lambda *a, **k: time.sleep(3600)  # far past any stop; SIGKILL ends it, never a loaded host
if os.environ.get("P1_STOP_AT") == "uploaded":  # the stop lands right after `upload_video` returned, before the `try`
    real_print = print
    def print(*args, **kw):
        real_print(*args, **kw)
        if args and "uploaded file_id" in str(args[0]):
            time.sleep(3600)
    fv.print = print
mc._request = slow_answer
raise SystemExit(fv.main([sys.argv[-1]]))
"""


class _Lock:
    def __init__(self, clone: Path) -> None:
        self.clone = clone

    def path(self, part: Any) -> Path:
        return self.clone

    def sha12(self, part: Any) -> str:
        return "29b018b0fdb6"

    def sha(self, part: Any) -> str:
        return "29b018b0fdb60f14e5a7bf9b2668d2445b60b546"


def _clip(tmp_path: Path) -> tuple[Path, Path]:
    video = tmp_path / "person.mp4"
    video.write_bytes(b"video bytes")
    return video, tmp_path / "jobs" / JOB / "work" / "trainer"


def _keys(tmp_path: Path) -> Path:
    keys_dir = tmp_path / "keys"
    keys_dir.mkdir()
    (keys_dir / "MODEL_API_KEY").write_text("dummy-key-value\n", encoding="utf-8")
    return keys_dir


def _job_log(tmp_path: Path) -> str:
    return (tmp_path / "jobs" / JOB / "steps" / "part7.log").read_text(encoding="utf-8")


def _fake_part1(tmp_path: Path, delete_s: float) -> Path:
    clone = tmp_path / "clone"
    python = clone / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text(FAKE_PART1.format(python=sys.executable, delete_s=delete_s), encoding="utf-8")
    python.chmod(0o755)
    return clone


def test_a_stopped_run_deletes_and_exits_143_inside_the_budget(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A real child under the real runner, with the real `.env` handling: SIGTERM at 4 s, the delete still has its key
    and its time, and the step reads as a timeout that the breaker counts once."""
    monkeypatch.setattr(p1_keyframes, "STOP_GRACE_S", 4.0)
    monkeypatch.setenv(part1_breaker.ENV, "on")
    video, work = _clip(tmp_path)
    clone, state = _fake_part1(tmp_path, delete_s=1.0), tmp_path / "state"
    step, keyframes, note = p1_keyframes.run(video, work, lock=_Lock(clone), state=state, keys_dir=_keys(tmp_path), timeout_s=8.0)  # type: ignore[arg-type]

    assert step is not None and step["timed_out"] and step["exit"] is None and step["stop_exit"] == 143
    assert step["timeout_s"] == 4.0 and keyframes is None and note != p1_keyframes.CUT_NOTE
    assert (clone / "deleted").is_file() and not (clone / ".env").exists()
    assert "delete_file ok file_id=file-7" in step.stdout
    assert not p1_keyframes.transient_failure(step)
    assert part1_breaker.allow(state) == (True, 0.0)
    assert len(json.loads((state / "part1_health.json").read_text())["failures"]) == 1
    log = _job_log(tmp_path)
    assert "Part 1 uploaded file_id=file-7" in log and "Part 1 delete_file ok file_id=file-7" in log
    assert "Part 1 stopped at 4 s: exit 143" in log and "delete_file missing" not in log


def test_a_grace_too_short_for_the_delete_is_a_kill_and_the_log_says_so(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The negative of the test above: what the old 10 s grace did to a slow delete, and how `part7.log` shows it."""
    monkeypatch.setattr(p1_keyframes, "_stop_times", lambda budget: (2.0, 0.3))
    video, work = _clip(tmp_path)
    clone = _fake_part1(tmp_path, delete_s=30.0)
    step, _keyframes, _note = p1_keyframes.run(video, work, lock=_Lock(clone), state=tmp_path / "state", keys_dir=_keys(tmp_path), timeout_s=8.0)  # type: ignore[arg-type]
    assert step is not None and step["timed_out"] and step["stop_exit"] == -9
    assert not (clone / "deleted").exists()
    log = _job_log(tmp_path)
    assert "Part 1 delete_file missing file_id=file-7" in log and "Part 1 stopped at 2 s: exit -9" in log


@pytest.mark.parametrize("stop_at", ["track", "uploaded"])
def test_the_real_part1_code_deletes_and_exits_143(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, stop_at: str) -> None:
    """Part 1's own `main`, handler, `finally` and `delete_file` from a checkout at the pin; only Meta is replaced. `track`
    stops inside `track_people`; `uploaded` stops on the `uploaded` print, the gap between the upload and the `try` that
    29b018b left and cdd4a522 closed (B2: run it with SIMON7_P1_CHECKOUT at 29b018b and it fails)."""
    checkout = Path(os.environ.get("SIMON7_P1_CHECKOUT") or config.REPO_ROOT / "modules" / "part-1")
    python = checkout / ".venv" / "bin" / "python"
    source = checkout / "keyframe_finder" / "from_video.py"
    if not python.exists() or not source.is_file() or "install_stop_handler" not in source.read_text(encoding="utf-8"):
        pytest.skip("no Part 1 checkout at 29b018b or later (cdd4a522 for the `uploaded` case) with its .venv")
    monkeypatch.setenv("P1_STOP_AT", stop_at)
    stop_s = _time_to_the_handler(python, checkout)
    monkeypatch.setattr(p1_keyframes, "STOP_GRACE_S", stop_s)
    driver = tmp_path / "driver.py"
    driver.write_text(REAL_PART1_DRIVER.format(checkout=str(checkout), scratch=str(tmp_path)), encoding="utf-8")
    clone = tmp_path / "clone"
    wrapper = clone / ".venv" / "bin" / "python"
    wrapper.parent.mkdir(parents=True)
    wrapper.write_text(f'#!/bin/sh\nexec "{python}" "{driver}" "$@"\n', encoding="utf-8")
    wrapper.chmod(0o755)
    video, work = _clip(tmp_path)
    step, _keyframes, _note = p1_keyframes.run(video, work, lock=_Lock(clone), state=tmp_path / "state", keys_dir=_keys(tmp_path), timeout_s=2 * stop_s)  # type: ignore[arg-type]
    assert step is not None, "no step"
    log = _job_log(tmp_path)
    seen = f"stop after {stop_s:.1f} s\nstep: {dict(step)}\nstdout: {step.stdout}\npart7.log: {log}"
    assert step["stop_exit"] != -15, f"the SIGTERM came before Part 1's handler was installed\n{seen}"
    assert step["stop_exit"] == 143 and step["exit"] is None, seen
    assert "Part 1 uploaded file_id=file-real" in log and "Part 1 delete_file ok file_id=file-real" in log, seen


def _time_to_the_handler(python: Path, checkout: Path) -> float:
    """Seconds to let Part 1 reach its handler before the stop, from a real import on this host at its present load.
    A fixed 8 s can lose to a busy host (TICKET-388 R9); this run also leaves the bytecode the driver's import reads."""
    started = time.monotonic()
    subprocess.run([str(python), "-c", f"import sys; sys.path.insert(0, {str(checkout)!r}); import keyframe_finder.from_video"],
                   check=True, capture_output=True, timeout=120)
    return max(8.0, 4 * (time.monotonic() - started))


@pytest.mark.parametrize("budget, term, grace", [(215.0, 150.0, 65.0), (305.0, 240.0, 65.0), (150.0, 85.0, 65.0), (90.0, 45.0, 45.0)])
def test_the_stop_fits_inside_the_budget(budget: float, term: float, grace: float) -> None:
    assert p1_keyframes._stop_times(budget) == (term, grace) and term + grace == budget


def test_each_setup_keeps_its_working_time(monkeypatch: pytest.MonkeyPatch) -> None:
    """The default and staging budgets grew by the stop, so Part 1 has the 150 s and 240 s of work it had before."""
    monkeypatch.delenv("SIMON7_PART1_TIMEOUT_S", raising=False)
    assert p1_keyframes._stop_times(config.part1_timeout_s())[0] == 150.0
    staging = (config.REPO_ROOT / "staging" / "env.sh").read_text(encoding="utf-8")
    found = re.search(r'SIMON7_PART1_TIMEOUT_S="\$\{SIMON7_PART1_TIMEOUT_S:-(\d+)\}"', staging)
    assert found and p1_keyframes._stop_times(float(found.group(1)))[0] == 240.0


def test_the_grace_covers_the_delete_timeout_of_part1() -> None:
    source = Path(os.environ.get("SIMON7_P1_CHECKOUT") or config.REPO_ROOT / "modules" / "part-1") / "keyframe_finder" / "meta_client.py"
    if not source.is_file():
        pytest.skip("no Part 1 checkout")
    found = re.search(r'_request\("DELETE", [^)]*timeout=(\d+)\)', source.read_text(encoding="utf-8"))
    assert found and float(found.group(1)) < p1_keyframes.STOP_GRACE_S


@pytest.mark.parametrize("final_line", [
    "  delete_file ok file_id=file-7",
    "  delete_file failed file_id=file-7: ConnectionResetError",
    "ConnectionResetError: a stop that quotes a marker on its last line",
])
@pytest.mark.parametrize("code", [143, -15])
def test_a_sigterm_exit_is_never_a_cut(final_line: str, code: int) -> None:
    assert not p1_keyframes.transient_failure(runner.Step(exit=code, timed_out=False, stdout=f"  uploading\n{final_line}\n"))


def test_a_cut_still_reads_as_a_cut_with_the_delete_line_before_it() -> None:
    """`finally` prints before Python prints the traceback, so the delete line never becomes the final line of a crash."""
    out = "  delete_file ok file_id=file-7\nTraceback ...\nkeyframe_finder.meta_client.StreamCut: SAM 3.1 stream cut after 9 frames\n"
    assert p1_keyframes.transient_failure(runner.Step(exit=1, timed_out=False, stdout=out))


def _answering(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, **step: Any) -> tuple[Path, Path, Path]:
    @contextlib.contextmanager
    def dotenv(*a: Any, **k: Any) -> Iterator[bool]:
        yield True

    def fake_run(part: Any, argv: list[str], **kw: Any) -> runner.Step:
        return runner.Step(part=1, duration_s=30.0, log=str(kw["log_path"]), **step)

    monkeypatch.setattr(p1_keyframes, "total_spend_usd", lambda *a, **k: 0.0)
    monkeypatch.setattr(p1_keyframes.keys, "has_key", lambda *a, **k: True)
    monkeypatch.setattr(p1_keyframes.keys, "part1_dotenv", dotenv)
    monkeypatch.setattr(p1_keyframes.runner, "run", fake_run)
    monkeypatch.setenv(part1_breaker.ENV, "on")
    video, work = _clip(tmp_path)
    return video, work, tmp_path / "state"


@pytest.mark.parametrize("code", [143, -15])
def test_a_stop_from_outside_leaves_the_breaker_as_it_was(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, code: int) -> None:
    """A restart or the memory guard says nothing about Meta: it neither adds to the streak nor clears it, as `other` would."""
    video, work, state = _answering(monkeypatch, tmp_path, exit=code, timed_out=False, stdout="  uploading\n")
    part1_breaker.record("transient", state)
    part1_breaker.record("transient", state)
    before = (state / "part1_health.json").read_text(encoding="utf-8")
    _step, keyframes, note = p1_keyframes.run(video, work, lock=_Lock(tmp_path / "clone"), state=state, timeout_s=90.0)  # type: ignore[arg-type]
    assert keyframes is None and note == f"key frames from Part 3, Part 1 exited {code}"
    assert (state / "part1_health.json").read_text(encoding="utf-8") == before


def test_upload_and_delete_lines_reach_the_job_log(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    out = ("  uploaded file_id=file-a\n  delete_file failed file_id=file-a: Meta API 403 on /files/file-a: no\n"
           "  uploaded file_id=file-b\n  delete_file ok file_id=file-b\n  uploaded file_id=file-c\n"
           "this line is not about a clip file_id=file-z\n")
    video, work, state = _answering(monkeypatch, tmp_path, exit=1, timed_out=False, stdout=out)
    p1_keyframes.run(video, work, lock=_Lock(tmp_path / "clone"), state=state, timeout_s=90.0)  # type: ignore[arg-type]
    log = _job_log(tmp_path).splitlines()
    delete_lines = [line for line in log if "delete_file" in line]
    assert len(delete_lines) == 3
    assert any(f"job {JOB}: Part 1 delete_file failed file_id=file-a: Meta API 403 on /files/file-a: no" in line for line in delete_lines)
    assert any("Part 1 delete_file ok file_id=file-b" in line for line in delete_lines)
    assert any("Part 1 delete_file missing file_id=file-c" in line for line in delete_lines)
    assert not any("file-z" in line for line in log)
    assert sum(" uploaded file_id=" in line for line in log) == 3
    assert any("WARNING" in line and "delete_file failed" in line for line in delete_lines)
