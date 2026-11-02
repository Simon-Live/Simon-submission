"""Staging yield (docs/specs/staging-yield.md): GPU-free, fake ticket files."""
import os
import subprocess
import sys
import time
from pathlib import Path

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
    (d / f"{pid}-1-{time.time_ns()}").write_text("")


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
    monkeypatch.setattr(sy, "install", lambda: None)
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


# ---- TICKET-056: the yield before every later GPU acquire (between clips and between a clip's phases) ----------

@pytest.fixture(autouse=True)
def fresh_budget():
    sy.reset_budget()
    yield
    sy.reset_budget()


@pytest.fixture
def fresh_trackers(monkeypatch):
    """part2.trackers.gpu_lock restored after a test that installs the yield."""
    from part2 import trackers

    current = trackers.gpu_lock  # another test's cli.main may have installed the wrapper already
    monkeypatch.setattr(trackers, "gpu_lock", getattr(current, "staging_original", current))
    return trackers


class Clock:
    """A clock that only moves when sleep is called."""

    def __init__(self):
        self.t = 0.0

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += s


def take_lock(wait_s=1):
    from part2 import gpu_guard

    return gpu_guard.gpu_lock(wait_s=wait_s, poll_s=0.01)


def fake_estimate(src, out):
    """A fake estimate whose output depends on its input bytes."""
    import hashlib

    out.write_text("pose-" + hashlib.sha256(src.read_bytes()).hexdigest())


def run_clips(clips, in_dir, out_dir):
    """What `part2 stock` does: one lock per clip, one result per clip computed from that clip's input."""
    for c in clips:
        with take_lock():
            fake_estimate(in_dir / c, out_dir / f"{c}.out")


def make_clips(in_dir):
    in_dir.mkdir()
    for c in ("a", "b", "c"):
        (in_dir / c).write_bytes(f"frames of {c}".encode())
    return ["a", "b", "c"]


def patch_yield(monkeypatch, **fixed):
    """The wrapper calls yield_to_staging(); give it a clock and a sleep that can end the wait."""
    real = sy.yield_to_staging
    monkeypatch.setattr(sy, "yield_to_staging", lambda *a, **k: real(*a, **{**fixed, **k}))


def test_ac1_ticket_between_clips_releases_waits_and_resumes(lock, live_pid, fresh_trackers, monkeypatch, capsys):
    path, d = lock
    monkeypatch.setenv(sy.GRACE_ENV, "0")
    sy.install()
    events = []

    def sleep(s):
        events.append("ticket gone")
        (d / os.listdir(d)[0]).unlink()

    patch_yield(monkeypatch, sleep=sleep)
    with take_lock():
        events.append("a holds")
    free = open(path, "a")  # between clips the flock is free: another process could take it now
    import fcntl

    fcntl.flock(free, fcntl.LOCK_EX | fcntl.LOCK_NB)
    fcntl.flock(free, fcntl.LOCK_UN)
    free.close()
    ticket(d, live_pid)
    with take_lock():
        events.append("b holds")
    assert events == ["a holds", "ticket gone", "b holds"]
    err = capsys.readouterr().err
    assert "waiting for a staging take (1 waiting)" in err and sy.RESUME_MESSAGE in err


def test_ac1_outputs_identical_with_and_without_a_ticket(lock, live_pid, fresh_trackers, monkeypatch, tmp_path):
    path, d = lock
    monkeypatch.setenv(sy.GRACE_ENV, "0")
    clips = make_clips(tmp_path / "in")
    plain, waited = tmp_path / "plain", tmp_path / "waited"
    plain.mkdir()
    waited.mkdir()
    run_clips(clips, tmp_path / "in", plain)
    sy.install()
    ticket(d, live_pid)
    patch_yield(monkeypatch, sleep=lambda s: [p.unlink() for p in d.iterdir()], log=lambda line: None)
    run_clips(clips, tmp_path / "in", waited)
    assert sorted(p.name for p in waited.iterdir()) == ["a.out", "b.out", "c.out"]
    assert len({p.read_bytes() for p in waited.iterdir()}) == 3  # the output depends on the input
    assert all(p.read_bytes() == (waited / p.name).read_bytes() for p in plain.iterdir())


def test_ac5_no_waiter_no_change(lock, fresh_trackers, monkeypatch, capsys):
    sy.install()
    monkeypatch.setattr(sy.time, "sleep", lambda s: pytest.fail("slept"))
    out = []
    with take_lock():
        out.append(1)
    assert out == [1] and capsys.readouterr().err == ""


def test_no_waiter_yield_returns_without_sleep_or_log(lock):
    assert sy.yield_to_staging(sleep=lambda s: pytest.fail("slept"), log=lambda line: pytest.fail("logged")) == 0


def test_ac3_staging_priority_never_yields_to_a_ticket_through_the_wrapper(lock, live_pid, fresh_trackers, monkeypatch,
                                                                            capsys):
    path, d = lock
    ticket(d, live_pid)
    monkeypatch.setenv(sy.RELAY_ENV, "staging")
    monkeypatch.setenv(sy.YIELD_TIMEOUT_ENV, "0")  # a wrong wait would time out and log at once instead of hanging
    sy.install()
    with take_lock():
        pass
    assert capsys.readouterr().err == "" and not sy._BUDGET["over"]


def test_ac3_ancestor_ticket_does_not_make_a_low_process_yield_through_the_wrapper(lock, fresh_trackers, monkeypatch,
                                                                                     capsys):
    path, d = lock
    monkeypatch.setattr(sy, "ancestors", lambda pid=None: {os.getpid(), os.getppid(), 1})
    monkeypatch.setenv(sy.YIELD_TIMEOUT_ENV, "0")
    ticket(d, os.getppid())
    sy.install()
    with take_lock():
        pass
    assert capsys.readouterr().err == "" and not sy._BUDGET["over"]


def test_r2_one_budget_per_process_and_no_yield_after_the_first_timeout(lock, live_pid, monkeypatch):
    path, d = lock
    ticket(d, live_pid)
    clock, logs = Clock(), []
    monkeypatch.setenv(sy.YIELD_TIMEOUT_ENV, "25")
    polls = sy.yield_to_staging(path, sleep=clock.sleep, clock=clock.now, log=logs.append)
    assert polls == 25 and logs[0].startswith("part2: waiting") and "gave up waiting" in logs[1]
    assert sy._BUDGET["over"]
    # the second acquire does not wait at all, ticket or not
    assert sy.yield_to_staging(path, sleep=lambda s: pytest.fail("slept"), log=lambda l: pytest.fail("logged")) == 0


def test_r2_budget_is_spent_across_acquires(lock, live_pid, monkeypatch):
    path, d = lock
    clock, logs = Clock(), []
    monkeypatch.setenv(sy.YIELD_TIMEOUT_ENV, "10")
    monkeypatch.setenv(sy.GRACE_ENV, "0")
    ticket(d, live_pid)
    t = d / os.listdir(d)[0]

    def sleep(s):
        clock.sleep(s)
        if clock.t >= 6:
            t.unlink(missing_ok=True)

    sy.yield_to_staging(path, sleep=sleep, clock=clock.now, log=logs.append)
    assert not sy._BUDGET["over"] and sy._BUDGET["spent"] >= 6
    ticket(d, live_pid)
    sy.yield_to_staging(path, sleep=clock.sleep, clock=clock.now, log=logs.append)  # only about 4 s are left
    assert sy._BUDGET["over"] and clock.t < 12


def test_r3_a_reused_pid_does_not_count(lock, live_pid):
    path, d = lock
    (d / f"{live_pid}-1-{time.time_ns() - 3600 * 10**9}").write_text("")  # the ticket is older than this process
    assert sy.staging_waiting(path) == 0
    ticket(d, live_pid)  # a ticket written now by the same pid is real
    assert sy.staging_waiting(path) == 1


def test_handoff_waits_the_grace_when_no_process_takes_the_lock(lock, live_pid, monkeypatch):
    path, d = lock
    ticket(d, live_pid)
    t = d / os.listdir(d)[0]
    clock, logs = Clock(), []
    monkeypatch.setenv(sy.GRACE_ENV, "5")

    def sleep(s):
        clock.sleep(s)
        t.unlink(missing_ok=True)

    sy.yield_to_staging(path, sleep=sleep, clock=clock.now, log=logs.append, handoff_poll_s=1.0)
    assert clock.t >= 5 and "within 5 s" in logs[1] and logs[-1] == sy.RESUME_MESSAGE


def hold_flock_process(path, seconds=20):
    """A separate process that holds the flock on `path`; (process, pid) once it holds it."""
    code = ("import fcntl,sys,time; f=open(sys.argv[1],'a'); fcntl.flock(f, fcntl.LOCK_EX); print('held', flush=True); "
            "time.sleep(float(sys.argv[2]))")
    p = subprocess.Popen([sys.executable, "-c", code, str(path), str(seconds)], stdout=subprocess.PIPE, text=True)
    assert p.stdout.readline().strip() == "held"
    return p


TICKET_HOLDER = """
import fcntl, os, sys, time
from pathlib import Path
lock = sys.argv[1]
d = Path(lock + '.waiters'); d.mkdir(exist_ok=True)
t = d / f'{os.getpid()}-1-{time.time_ns()}'; t.write_text('')
f = open(lock, 'a'); fcntl.flock(f, fcntl.LOCK_EX)    # Part 7: _take_flock, then _wait_memory with the ticket live
print('held', flush=True)
time.sleep(float(sys.argv[2]))
"""


def ticket_holder(path, seconds=30):
    p = subprocess.Popen([sys.executable, "-c", TICKET_HOLDER, str(path), str(seconds)], stdout=subprocess.PIPE,
                         text=True)
    assert p.stdout.readline().strip() == "held"
    return p


def require_proc_locks(path, pid):
    if pid not in sy.flock_holders(path):
        pytest.skip("/proc/locks does not list the flock holder here")


def test_b2_a_ticket_process_holding_the_flock_past_the_span_makes_the_yield_stand_down(lock, monkeypatch):
    path, d = lock
    holder = ticket_holder(path)
    try:
        require_proc_locks(path, holder.pid)
        monkeypatch.setenv(sy.STUCK_ENV, "3")
        clock, logs = Clock(), []
        polls = sy.yield_to_staging(path, sleep=clock.sleep, clock=clock.now, log=logs.append)
        assert 3 <= polls <= 4 and clock.t < 6  # stood down at the span, long before the 1800 s budget
        assert logs[0].startswith("part2: waiting") and logs[-1].startswith("part2: a staging take has held")
        assert not sy._BUDGET["over"]
    finally:
        holder.kill()
        holder.wait()


def test_b2_a_short_hold_by_a_ticket_process_keeps_the_yield(lock, monkeypatch):
    path, d = lock
    holder = ticket_holder(path)
    try:
        require_proc_locks(path, holder.pid)
        monkeypatch.setenv(sy.STUCK_ENV, "100")
        monkeypatch.setenv(sy.YIELD_TIMEOUT_ENV, "5")
        clock, logs = Clock(), []
        sy.yield_to_staging(path, sleep=clock.sleep, clock=clock.now, log=logs.append)
        assert any("gave up waiting" in line for line in logs) and not any("held the GPU" in line for line in logs)
    finally:
        holder.kill()
        holder.wait()


def test_b2_a_third_party_holder_with_a_live_ticket_keeps_the_low_process_yielding(lock, live_pid, monkeypatch):
    path, d = lock
    holder = hold_flock_process(path)
    try:
        require_proc_locks(path, holder.pid)
        ticket(d, live_pid)
        monkeypatch.setenv(sy.STUCK_ENV, "1")
        monkeypatch.setenv(sy.YIELD_TIMEOUT_ENV, "5")
        clock, logs = Clock(), []
        polls = sy.yield_to_staging(path, sleep=clock.sleep, clock=clock.now, log=logs.append)
        assert polls == 5 and any("gave up waiting" in line for line in logs)
        assert not any("held the GPU" in line for line in logs)
    finally:
        holder.kill()
        holder.wait()


def test_b2_stand_down_falls_to_the_original_wait_which_ends_in_gpubusy(lock, fresh_trackers, monkeypatch):
    path, d = lock
    holder = ticket_holder(path)
    try:
        require_proc_locks(path, holder.pid)
        monkeypatch.setenv(sy.STUCK_ENV, "0")
        sy.install()
        with pytest.raises(fresh_trackers.GpuBusy):
            with take_lock(wait_s=0.3):
                pass
    finally:
        holder.kill()
        holder.wait()


RETAKE_SCRIPT = """
import fcntl, os, sys, time
from pathlib import Path
lock = sys.argv[1]
d = Path(lock + '.waiters'); d.mkdir(exist_ok=True)
t = d / f'{os.getpid()}-1-{time.time_ns()}'; t.write_text('')
f = open(lock, 'a'); fcntl.flock(f, fcntl.LOCK_EX)
time.sleep(1.0)
t.unlink(); time.sleep(0.3); fcntl.flock(f, fcntl.LOCK_UN)      # admitted: ticket dropped, flock released
time.sleep(1.5)                                                   # the take starts in this same pid
g = open(lock, 'a'); fcntl.flock(g, fcntl.LOCK_EX); time.sleep(float(sys.argv[2])); fcntl.flock(g, fcntl.LOCK_UN)
print('done', flush=True)
"""


def test_r5_the_ticket_pid_taking_and_releasing_after_its_ticket_went_is_the_handoff(lock, monkeypatch):
    path, d = lock
    monkeypatch.setenv(sy.GRACE_ENV, "20")
    stg = subprocess.Popen([sys.executable, "-c", RETAKE_SCRIPT, str(path), "0.7"], stdout=subprocess.PIPE, text=True)
    try:
        time.sleep(0.4)  # its ticket is live and it holds the flock
        logs, t0 = [], time.monotonic()
        sy.yield_to_staging(path, log=logs.append, poll_s=0.1)
        waited = time.monotonic() - t0
        if not sy.flock_holders(path) and stg.poll() is None and waited < 1.0:
            pytest.skip("/proc/locks does not list the flock holder here")
        assert 3.0 < waited < 8.0, waited  # returned about when the take let go, not at the 20 s grace
        assert logs[-1] == sy.RESUME_MESSAGE and not any("within" in line for line in logs)
    finally:
        stg.kill()
        stg.wait()


def test_r6_the_warm_worker_resets_the_budget_for_each_request(tmp_path):
    from part2 import worker

    sy._BUDGET.update(spent=99.0, over=True)
    with worker._job_context(str(tmp_path), {}):
        assert sy._BUDGET == {"spent": 0.0, "over": False}


def test_r7_a_lock_on_another_device_with_the_same_inode_is_not_ours(tmp_path, monkeypatch):
    f = tmp_path / "gpu.lock"
    f.write_text("")
    st = os.stat(f)
    mine = f"{os.major(st.st_dev):02x}:{os.minor(st.st_dev):02x}:{st.st_ino}"
    other = f"{(os.major(st.st_dev) + 1) & 0xff:02x}:{os.minor(st.st_dev):02x}:{st.st_ino}"
    table = tmp_path / "locks"
    table.write_text(f"1: FLOCK  ADVISORY  WRITE 111 {mine} 0 EOF\n2: FLOCK  ADVISORY  WRITE 222 {other} 0 EOF\n"
                     f"3: POSIX  ADVISORY  WRITE 333 {mine} 0 EOF\n")
    monkeypatch.setattr(sy, "PROC_LOCKS", str(table))
    assert sy.flock_holders(f) == {111}


LOW_SCRIPT = """
import os, sys, time
from pathlib import Path
from part2 import gpu_guard, staging_yield
events = Path(sys.argv[1])
def note(s):
    with open(events, 'a') as f:
        f.write(s + '\\n')
staging_yield.install()
for c in range(3):
    with gpu_guard.gpu_lock(wait_s=60, poll_s=0.05):
        note(f'low clip{c}')
        time.sleep(1.5)
"""
CHILD_SCRIPT = """
import fcntl, sys, time
time.sleep(float(sys.argv[3]))
f = open(sys.argv[1], 'a')
while True:
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        break
    except BlockingIOError:
        time.sleep(0.05)
open(sys.argv[2], 'a').write('child holds\\n')
time.sleep(0.5)
fcntl.flock(f, fcntl.LOCK_UN)
"""
STAGING_SCRIPT = """
import fcntl, os, subprocess, sys, time
from pathlib import Path
lock, events, startup = sys.argv[1], sys.argv[2], sys.argv[3]
time.sleep(1.0)
waiters = Path(lock + '.waiters'); waiters.mkdir(exist_ok=True)
tk = waiters / f'{os.getpid()}-1-{time.time_ns()}'; tk.write_text('')
f = open(lock, 'a')
while True:
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        break
    except BlockingIOError:
        time.sleep(0.05)
tk.unlink()                                  # Part 7: the ticket goes on admission ...
fcntl.flock(f, fcntl.LOCK_UN)                # ... hold_flock=False
open(events, 'a').write('admitted\\n')
subprocess.run([sys.executable, '-c', sys.argv[4], lock, events, startup])   # the Part 2 child starts later
"""


PROBER_SCRIPT = """
import fcntl, os, sys, time
end = time.monotonic() + 12
while time.monotonic() < end:                 # Part 7 wait_free(0), Part 2 try_lock, any reader
    fd = os.open(sys.argv[1], os.O_CREAT | os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB); fcntl.flock(fd, fcntl.LOCK_UN)
    except BlockingIOError:
        pass
    os.close(fd)
    time.sleep(0.05)
"""


@pytest.mark.parametrize("startup,prober", [("2.0", False), ("3.0", True)])
def test_b1_handoff_the_take_child_gets_the_lock_before_the_low_process_retakes_it(tmp_path, startup, prober):
    """Modelled on the integrator's race.py and race3.py: the child starts 2 or 3 s after the ticket is gone, with a
    prober opening and locking the file meanwhile (an open of the lock file is not a take)."""
    lock = tmp_path / "gpu.lock"
    events = tmp_path / "events.log"
    env = {**os.environ, "PART2_GPU_LOCK": str(lock), sy.GRACE_ENV: "10"}
    for k in (sy.PRIORITY_ENV, sy.RELAY_ENV):
        env.pop(k, None)
    root = str(Path(__file__).resolve().parent.parent)
    env["PYTHONPATH"] = root + os.pathsep + env.get("PYTHONPATH", "")
    low = subprocess.Popen([sys.executable, "-c", LOW_SCRIPT, str(events)], env=env, cwd=root)
    stg = subprocess.Popen([sys.executable, "-c", STAGING_SCRIPT, str(lock), str(events), startup, CHILD_SCRIPT], env=env)
    probe = subprocess.Popen([sys.executable, "-c", PROBER_SCRIPT, str(lock)]) if prober else None
    assert stg.wait(timeout=60) == 0 and low.wait(timeout=60) == 0
    if probe:
        probe.kill()
        probe.wait()
    lines = events.read_text().splitlines()
    assert lines.index("child holds") < lines.index("low clip1"), lines
    assert lines.index("admitted") < lines.index("child holds") and "low clip2" in lines


def test_b3_cli_main_installs_the_wrapper_for_a_gpu_command(lock, fresh_trackers, monkeypatch, tmp_path):
    from test_cli import _fake_estimate, _image_dir, _use_fake_backend

    _use_fake_backend(monkeypatch, _fake_estimate)
    seen = []
    real = sy.yield_to_staging
    monkeypatch.setattr(sy, "yield_to_staging", lambda *a, **k: seen.append(1) or real(*a, **k))
    assert not getattr(fresh_trackers.gpu_lock, "staging_yield", False)
    code = cli.main(["run", "--mode", "single", "--input", str(_image_dir(tmp_path)), "--out", str(tmp_path / "o"),
                     "--fps", "10"])
    assert code == 0
    assert fresh_trackers.gpu_lock.staging_yield is True
    assert seen == [1]  # the run's estimate took the lock through the yield point


def test_yield_timeout_env(monkeypatch):
    monkeypatch.setenv(sy.YIELD_TIMEOUT_ENV, "12")
    assert sy.yield_timeout_s() == 12.0
    monkeypatch.setenv(sy.YIELD_TIMEOUT_ENV, "junk")
    assert sy.yield_timeout_s() == sy.YIELD_TIMEOUT_S
    monkeypatch.setenv(sy.GRACE_ENV, "3")
    assert sy.grace_s() == 3.0


def test_install_is_idempotent(fresh_trackers):
    assert sy.install() is True
    wrapped = fresh_trackers.gpu_lock
    assert sy.install() is False
    assert fresh_trackers.gpu_lock is wrapped
