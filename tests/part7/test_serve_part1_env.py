"""R1 and R2: `part7 serve` clears the Part 1 `.env` a SIGKILL left, at start and when a standby takes the queue over
(docs/specs/parts-harness.md AC-H5c). No Part 6, no network: the fakes stop `cli_serve` at the step under test."""

from __future__ import annotations

import fcntl
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any

import pytest

from part7 import keys, server
from part7.parts import p6_catalog
from support import Api


class _Child:
    healthy = False

    def __init__(self, **kwargs: Any) -> None:
        pass

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def health(self) -> dict[str, str] | None:
        return {} if self.healthy else None


class _Stop(Exception):
    pass


@pytest.fixture()
def tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    part1 = tmp_path / "modules" / "part-1"
    part1.mkdir(parents=True)
    monkeypatch.setenv("SIMON7_MODULES_DIR", str(tmp_path / "modules"))
    monkeypatch.setattr(p6_catalog, "Child", _Child)
    return part1


def _leave_files(part1: Path) -> tuple[Path, Path]:
    env, temp = part1 / ".env", part1 / (keys._ENV_TEMP_PREFIX + "a1b2c3d4")
    for path in (env, temp):
        path.write_text("MODEL_API_KEY=x\n", encoding="utf-8")
        path.chmod(0o600)
    return env, temp


def test_a_starting_server_clears_the_serving_tree(tree: Path, tmp_path: Path) -> None:
    env, temp = _leave_files(tree)
    assert server.cli_serve("127.0.0.1", 0, "/", tmp_path / "state") == 1  # the fake Part 6 ends the start here
    assert not env.exists() and not temp.exists()


def test_every_retention_sweep_clears_the_tree(api: Api, tmp_path: Path) -> None:
    """Each pass of the retention sweep clears the serving tree: the periodic one frees the key of a run that outlived its
    server and has exited since. (The takeover's own pass is the next test.)"""
    from part7 import modules
    api.app.lock = modules.load(tmp_path / "modules")
    part1 = tmp_path / "modules" / "part-1"
    part1.mkdir(parents=True)
    env, temp = _leave_files(part1)
    server._sweep(api.app)
    assert not env.exists() and not temp.exists() and part1.is_dir()


def test_a_standby_clears_the_tree_when_it_takes_the_queue_from_a_dead_owner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The new build of a restart is past its start when the old server dies: its real queue takes the lock, and the cleanup of
    that takeover runs the sweep, long before the periodic one (600 s)."""
    from types import SimpleNamespace
    from part7 import jobs, modules
    monkeypatch.delenv("SIMON7_CLEANUP_EVERY_S", raising=False)
    part1 = tmp_path / "modules" / "part-1"
    part1.mkdir(parents=True)
    state = tmp_path / "state"
    owner = jobs.JobQueue(state)
    app = server.build_app(state, "/", child=SimpleNamespace(catalog_dir=tmp_path / "catalog"),
                           lock=modules.load(tmp_path / "modules"), phrasing="template")
    try:
        assert owner.owner and not app.queue.owner
        env, temp = _leave_files(part1)
        owner.close()  # the old server is gone and its lock with it
        _wait_until(lambda: app.queue.owner)
        assert not env.exists() and not temp.exists()
    finally:
        app.queue.close()
        owner.close()


def _wait_until(cond: Any, seconds: float = 20.0) -> None:
    deadline = time.monotonic() + seconds
    while not cond() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert cond(), "the standby never took the queue"


# The server of a Part 1 call: the real `p1_keyframes.run` (so the real `part1_dotenv` and `runner.run`), then a SIGKILL.
SERVER = """
import sys
from pathlib import Path
from part7.parts import p1_keyframes
clone, kdir, video, work = map(Path, sys.argv[1:5])
class Lock:
    def path(self, part): return clone
    def sha12(self, part): return "0" * 12
    def sha(self, part): return "0" * 40
p1_keyframes.run(video, work, lock=Lock(), state=None, keys_dir=kdir, timeout_s=120.0)
"""
# Part 1's stand-in: says it is up, waits for `go`, then prints as Part 1 does (the pipe's reader died with the server, so
# this raises BrokenPipeError, as it does for a real orphan) and, in a `finally` like Part 1's, does what `delete_file` does
# first: read the key from `.env`.
RUN = """#!{python}
import pathlib, time
pathlib.Path("up").write_text("x")
while not pathlib.Path("go").exists(): time.sleep(0.05)
try:
    try:
        print("  tracking", flush=True)
    except BaseException as exc:
        pathlib.Path("print").write_text(type(exc).__name__)
        raise
finally:
    env = pathlib.Path(".env")
    pathlib.Path("answer").write_text("ok" if env.is_file() and "MODEL_API_KEY=" in env.read_text() else "MODEL_API_KEY is missing")
"""


def _wait(path: Path, seconds: float = 60.0) -> None:
    deadline = time.monotonic() + seconds
    while not path.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert path.exists(), f"{path.name} never appeared"


def _lock_refused(directory: Path) -> bool:
    """True while some process still holds a lock on `directory`: an exclusive try fails."""
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return True
    finally:
        os.close(fd)
    return False


def test_a_run_that_outlives_its_killed_server_keeps_its_key_and_then_frees_it(tmp_path: Path) -> None:
    """B1: the server is SIGKILLed mid-call, a sweep runs (start, takeover or the periodic pass), and the live Part 1 run still
    finds its key for the delete; once it has exited a sweep removes the file."""
    clone, kdir = tmp_path / "clone", tmp_path / "keys"
    python = clone / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text(RUN.format(python=sys.executable), encoding="utf-8")
    python.chmod(0o755)
    kdir.mkdir()
    (kdir / "MODEL_API_KEY").write_text("fake-not-a-key-000000\n", encoding="utf-8")
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    server_proc = subprocess.Popen([sys.executable, "-c", SERVER, str(clone), str(kdir), str(video), str(tmp_path / "work")],
                                   cwd=Path(__file__).resolve().parents[2])
    try:
        _wait(clone / "up")
        server_proc.kill()
        server_proc.wait(timeout=30)
        assert _lock_refused(clone), "the run does not hold the lock itself: the server's descriptor was all that kept it"
        keys.drop_part1_env(clone)  # the sweep the new server runs
        assert (clone / ".env").is_file(), "the sweep removed the key under a live Part 1 run"
        (clone / "go").write_text("x")
        _wait(clone / "answer")
        assert (clone / "answer").read_text() == "ok"
        assert (clone / "print").read_text() == "BrokenPipeError"  # the orphan's first print raises; its finally still deletes
        deadline = time.monotonic() + 30
        while (clone / ".env").exists() and time.monotonic() < deadline:  # the run exits right after its answer
            keys.drop_part1_env(clone)
            time.sleep(0.1)
        assert not (clone / ".env").exists(), "the key stayed after the run exited"
    finally:
        (clone / "go").write_text("x")
        if server_proc.poll() is None:
            server_proc.kill()


def test_a_prod_start_clears_the_copies_where_the_key_sits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """R4: prod's key is in `part1/<pin>`, not in the read-only release the start clear covered; a restart sweeps it at once."""
    from part7 import modules
    monkeypatch.setenv("FIRM_ENV", "prod")
    part1 = tmp_path / "modules" / "part-1"
    part1.mkdir(parents=True)
    copy = tmp_path / "state" / "part1" / "abcdef012345"
    copy.mkdir(parents=True)
    env = copy / ".env"
    env.write_text("MODEL_API_KEY=x\n", encoding="utf-8")
    server._clear_part1_env(modules.load(tmp_path / "modules"), tmp_path / "state")
    assert not env.exists()


def test_a_tree_that_cannot_be_cleared_does_not_stop_the_server(tree: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                                caplog: pytest.LogCaptureFixture) -> None:
    """A read-only release tree: the start goes on, and the log says so without a value."""

    def refuse(_path: Any) -> None:
        raise PermissionError("read-only")

    monkeypatch.setattr(server.keys, "drop_part1_env", refuse)
    assert server.cli_serve("127.0.0.1", 0, "/", tmp_path / "state") == 1
    assert "Part 1 .env not cleared: PermissionError" in caplog.text and "read-only" not in caplog.text


@pytest.mark.parametrize("err, warned", [(30, False), (13, True)])
def test_a_failed_release_clear_does_not_skip_the_prod_sweep(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                              caplog: pytest.LogCaptureFixture, err: int, warned: bool) -> None:
    """R2, AC-H5c: a read-only release tree (EROFS) raises from the first call; the sweep still runs, and EROFS logs no warning."""
    from part7 import modules
    (tmp_path / "modules" / "part-1").mkdir(parents=True)
    swept: list[object] = []

    def refuse(_path: Any) -> None:
        raise OSError(err, "refused")

    monkeypatch.setattr(server.keys, "drop_part1_env", refuse)
    monkeypatch.setattr(server.p1_keyframes, "sweep", lambda state: swept.append(state))
    server._clear_part1_env(modules.load(tmp_path / "modules"), tmp_path / "state")
    assert swept == [tmp_path / "state"] and ("Part 1 .env not cleared" in caplog.text) is warned
