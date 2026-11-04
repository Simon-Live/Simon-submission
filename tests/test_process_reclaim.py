"""docs/specs/test-process-reclaim.md (TICKET-379): no test leaves a process behind, and a finished run's orphans are
reaped only by path and only when their parent is init."""

from __future__ import annotations

import os
from pathlib import Path
import signal
import subprocess
import sys
import textwrap
import time

import pytest

import process_reclaim as pr

TESTS = Path(__file__).resolve().parent
SLEEP = "import time; time.sleep(60)"
STUBBORN = "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)"


@pytest.fixture
def spawned() -> list[subprocess.Popen]:
    procs: list[subprocess.Popen] = []
    yield procs
    for p in procs:
        if p.poll() is None:
            p.kill()
        p.wait()


def _daemon(spawned: list, code: str, *args: str) -> subprocess.Popen:
    p = subprocess.Popen([sys.executable, "-c", code, *args], start_new_session=True)
    spawned.append(p)
    return p


def _gone(p: subprocess.Popen, timeout: float = 5.0) -> bool:
    try:
        p.wait(timeout)
    except subprocess.TimeoutExpired:
        return False
    return True


def test_find_under_matches_a_path_argument_not_a_name(tmp_path: Path, spawned: list) -> None:
    mine = _daemon(spawned, SLEEP, "--spool", str(tmp_path / "state" / "models-spool"))
    flagged = _daemon(spawned, SLEEP, f"--config={tmp_path}/Caddyfile")
    same_program = _daemon(spawned, SLEEP, "--spool", str(tmp_path.parent / (tmp_path.name + "-other") / "spool"))
    nameless = _daemon(spawned, SLEEP)
    time.sleep(0.2)
    found = {pid for pid, _, _ in pr.find_under([tmp_path])}
    assert found == {mine.pid, flagged.pid}
    assert same_program.pid not in found and nameless.pid not in found  # a sibling path and the bare name are not matched


def test_reap_stops_a_detached_daemon_and_one_that_ignores_sigterm(tmp_path: Path, spawned: list) -> None:
    polite = _daemon(spawned, SLEEP, str(tmp_path / "a"))
    stubborn = _daemon(spawned, STUBBORN, str(tmp_path / "b"))
    bystander = _daemon(spawned, SLEEP, "/not/the/tmp/dir")
    time.sleep(0.3)
    stopped = pr.reap([tmp_path], grace=0.5)
    assert sorted(stopped) == sorted([polite.pid, stubborn.pid])
    assert _gone(polite) and _gone(stubborn) and stubborn.returncode == -signal.SIGKILL
    assert bystander.poll() is None


def test_the_autouse_fixture_leaves_no_process_behind(tmp_path: Path) -> None:
    """A nested session whose tests start a detached daemon (one passes, one fails): after it, none names its temp dir."""
    (tmp_path / "proj").mkdir()
    (tmp_path / "proj" / "test_leaky.py").write_text(textwrap.dedent(f'''
        import subprocess, sys
        from pathlib import Path

        def _leak(tmp_path):
            p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)", "--spool", str(tmp_path / "models-spool")],
                                 start_new_session=True)
            Path({str(tmp_path)!r}, f"pid-{{tmp_path.name}}").write_text(str(p.pid))

        def test_passes(tmp_path):
            _leak(tmp_path)

        def test_fails(tmp_path):
            _leak(tmp_path)
            assert False
        '''))
    base = tmp_path / "base"
    env = {**os.environ, "PYTHONPATH": f"{TESTS}{os.pathsep}{os.environ.get('PYTHONPATH', '')}"}
    done = subprocess.run([sys.executable, "-m", "pytest", "-p", "reclaim_plugin", "-p", "no:cacheprovider", "-q",
                           "--basetemp", str(base), "--rootdir", str(tmp_path / "proj"), str(tmp_path / "proj")],
                          env=env, capture_output=True, text=True, timeout=120)
    assert "1 failed, 1 passed" in done.stdout, done.stdout + done.stderr
    pids = [int(p.read_text()) for p in tmp_path.glob("pid-*")]
    assert len(pids) == 2
    assert pr.find_under([base]) == []  # nothing alive names the session's temp dirs
    assert not [p for p in pids if pr._alive(p)]


def test_stale_refuses_pytest_current_and_foreign_roots(tmp_path: Path) -> None:
    base = tmp_path / "pytest-of-x"
    (base / "pytest-12").mkdir(parents=True)
    (base / "pytest-13").mkdir()
    (base / "pytest-current").symlink_to(base / "pytest-13")
    (base / "other").mkdir()
    assert pr.check_stale_root(str(base / "pytest-12"), base) == (base / "pytest-12").resolve()
    for bad in (base / "pytest-current", base / "pytest-13", base / "other", base, tmp_path, "/", "/tmp"):
        with pytest.raises(ValueError):
            pr.check_stale_root(str(bad), base)
    assert pr.main(["--stale", str(base / "pytest-current"), "--base", str(base)]) == 2
    assert pr.main(["--stale", "/tmp", "--dry-run"]) == 2


def test_stale_refuses_a_root_a_live_pytest_process_names(tmp_path: Path, spawned: list) -> None:
    base = tmp_path / "pytest-of-x"
    root = base / "pytest-21"
    (root / "t").mkdir(parents=True)
    assert pr.check_stale_root(str(root), base) == root.resolve()  # nothing names it yet
    live = _daemon(spawned, SLEEP, "pytest", str(root / "t"))  # `python -m pytest <path>` has the same argv shape
    time.sleep(0.2)
    with pytest.raises(ValueError, match="live pytest process"):
        pr.check_stale_root(str(root), base)
    assert pr.main(["--stale", str(root), "--base", str(base)]) == 2
    assert pr._alive(live.pid)  # refused: nothing was signalled


def test_stale_only_takes_orphans(tmp_path: Path, spawned: list, capsys: pytest.CaptureFixture) -> None:
    base = tmp_path / "pytest-of-x"
    root = base / "pytest-77"
    (root / "t").mkdir(parents=True)
    child = _daemon(spawned, SLEEP, "--spool", str(root / "t" / "models-spool"))  # its parent is this live test run
    pidfile = tmp_path / "orphan.pid"
    subprocess.run(["sh", "-c", f'setsid {sys.executable} -c "{SLEEP}" --spool "{root}/t/state/models-spool" '
                    f'>/dev/null 2>&1 & echo $! > "{pidfile}"'], check=True)
    orphan = int(pidfile.read_text())
    time.sleep(0.4)
    try:
        if not pr.is_orphan(pr._ppid_of(orphan)):
            pytest.skip("this host reparents detached processes to a subreaper that is not init")
        assert pr.main(["--stale", str(root), "--base", str(base), "--dry-run"]) == 0
        assert pr._alive(orphan)  # dry run signals nothing
        assert pr.main(["--stale", str(root), "--base", str(base)]) == 0
        out = capsys.readouterr().out
        assert f"stopped {orphan} " in out and f"left alone {child.pid} " in out
        deadline = time.monotonic() + 5
        while pr._alive(orphan) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert not pr._alive(orphan) and child.poll() is None
    finally:
        pr._signal(orphan, signal.SIGKILL)
