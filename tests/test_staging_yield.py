"""Staging yield (docs/specs/staging-yield.md): GPU-free, fake ticket files."""
import os
import subprocess
import sys

import pytest

from part2 import cli
from part2 import staging_yield as sy


@pytest.fixture
def lock(tmp_path, monkeypatch):
    path = tmp_path / "gpu.lock"
    monkeypatch.setenv("PART2_GPU_LOCK", str(path))
    for k in (sy.PRIORITY_ENV, sy.RELAY_ENV):
        monkeypatch.delenv(k, raising=False)
    d = tmp_path / "gpu.lock.waiters"
    d.mkdir()
    return path, d


@pytest.fixture
def live_pid():
    """A live process that is not us or an ancestor (a sibling's pid)."""
    p = subprocess.Popen(["sleep", "30"])
    yield p.pid
    p.kill()
    p.wait()


def dead_pid():
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


def ticket(d, pid):
    (d / f"{pid}-1-123").write_text("")


def test_live_ticket_waits_then_releases(lock, live_pid):
    path, d = lock
    ticket(d, live_pid)
    logs, calls = [], []

    def sleep(s):
        calls.append(s)
        if len(calls) == 3:
            (d / os.listdir(d)[0]).unlink()

    polls = sy.wait_for_staging(path, sleep=sleep, log=logs.append)
    assert polls == 3 and calls == [1.0] * 3
    assert logs == ["part2: waiting for a staging take (1 waiting)"]


def test_dead_pid_does_not_wait(lock):
    path, d = lock
    ticket(d, dead_pid())
    assert sy.staging_waiting(path) == 0
    assert sy.wait_for_staging(path, sleep=lambda s: pytest.fail("slept")) == 0
    assert len(os.listdir(d)) == 1  # left alone


def test_count_mixes_live_dead_and_junk(lock, live_pid):
    path, d = lock
    ticket(d, live_pid)
    ticket(d, dead_pid())
    (d / "notapid-1-2").write_text("")
    assert sy.staging_waiting(path) == 1


@pytest.mark.parametrize("var,val", [(sy.PRIORITY_ENV, "staging"), (sy.PRIORITY_ENV, "HIGH"), (sy.RELAY_ENV, "staging")])
def test_staging_take_never_waits(lock, live_pid, monkeypatch, var, val):
    path, d = lock
    ticket(d, live_pid)
    monkeypatch.setenv(var, val)
    assert sy.wait_for_staging(path, sleep=lambda s: pytest.fail("slept")) == 0


def test_low_priority_value_still_waits(lock, live_pid, monkeypatch):
    path, d = lock
    ticket(d, live_pid)
    monkeypatch.setenv(sy.PRIORITY_ENV, "low")
    with pytest.raises(RuntimeError):
        sy.wait_for_staging(path, sleep=lambda s: (_ for _ in ()).throw(RuntimeError()), log=lambda l: None)


def test_no_folder_no_wait(tmp_path):
    assert sy.wait_for_staging(tmp_path / "none.lock", sleep=lambda s: pytest.fail("slept")) == 0


def test_default_lock_path_follows_env(lock):
    _path, d = lock
    assert sy.waiters_dir() == d


@pytest.mark.parametrize("command,gated", [("run", True), ("track", True), ("serve-worker", True), ("avatar", True),
                                           ("autorig", True), ("image3d", True), ("stock", True),
                                           ("frames", False), ("check", False), ("contract", False)])
def test_gate_by_command(monkeypatch, command, gated):
    seen = []
    monkeypatch.setattr(sy, "wait_for_staging", lambda *a, **k: seen.append(1))
    sy.gate(command)
    assert bool(seen) is gated


def test_main_gates_run(monkeypatch):
    seen = []
    monkeypatch.setattr(sy, "gate", seen.append)
    cli.main(["contract", "--json"])
    assert seen == ["contract"]


def test_worker_relay_marks_staging(monkeypatch):
    monkeypatch.delenv(sy.RELAY_ENV, raising=False)
    monkeypatch.delenv(sy.PRIORITY_ENV, raising=False)
    sy.mark_staging_for_worker()
    assert sy.RELAY_ENV not in os.environ
    monkeypatch.setenv(sy.PRIORITY_ENV, "staging")
    sy.mark_staging_for_worker()
    assert os.environ[sy.RELAY_ENV] == "staging"
    monkeypatch.delenv(sy.RELAY_ENV)


def test_ancestors_include_self_and_parent():
    a = sy.ancestors()
    assert os.getpid() in a and os.getppid() in a and 1 in a


def test_parent_and_ancestor_tickets_do_not_block(lock, monkeypatch):
    path, d = lock
    monkeypatch.setattr(sy, "ancestors", lambda pid=None: {os.getpid(), os.getppid(), 1})
    ticket(d, os.getppid())
    ticket(d, os.getpid())
    assert sy.staging_waiting(path) == 0
    assert sy.wait_for_staging(path, sleep=lambda s: pytest.fail("slept")) == 0


def test_real_child_ignores_its_parents_ticket_but_not_a_sibling(lock):
    path, d = lock
    sib = subprocess.Popen(["sleep", "30"])
    try:
        ticket(d, os.getpid())  # the parent of the child below
        code = ("import sys; from part2 import staging_yield as s; print(s.staging_waiting(sys.argv[1]))")
        run = lambda: subprocess.run([sys.executable, "-c", code, str(path)], capture_output=True, text=True,
                                     check=True, env=os.environ).stdout.strip()
        assert run() == "0"
        ticket(d, sib.pid)
        assert run() == "1"
    finally:
        sib.kill()
        sib.wait()
