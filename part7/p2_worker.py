"""Warm Part 2 worker: one `part2 serve-worker` (TICKET-099), kept for the life of `part7 serve`.

A worker keeps the 3D model loaded (20 to 35 s of every `part2 run`). The pool starts only when the pinned Part 2
has `run --worker`; a `run` borrows the worker with `lease()` and passes `--worker <socket>`. The worker serves one
request at a time, so a call that cannot lease it within `LEASE_WAIT_S` runs in-process as before and never queues
behind it. An unhealthy worker logs `ANOMALY p2_worker_unhealthy`, is restarted once in the background (the
calls meanwhile run in-process) and, if that restart fails, is left down for `RETRY_DOWN_S`.

The same `Pool` also runs Part 2's warm track worker (`part2 serve-worker --mode track`, TICKET-128; TICKET-117
began it) as a second, independent pool (`start_track_pool`). It differs in three ways, all opt-in on `Pool`: it may
start on the first call and not at boot (`on_demand`), it may give the GPU memory back after `idle_release_s`
without a call (`p2_tracker_released` is a log line), and it restarts at the next lease when the Part 2 pin it
started with is no longer the pin on disk (`version`), because Part 2 asks for a restart on every update.
"""

from __future__ import annotations

import collections
import contextlib
import os
import socket
import signal
import subprocess
import tempfile
import threading
import statistics
import time
from pathlib import Path
from typing import Callable, Iterator

from part7 import applog, config, gpu_lock, selfheal

START_WAIT_S = 180.0  # a worker loads its model before it listens (on an idle host)
START_LOAD_SCALE_MAX = 4.0  # a busy host (load1 per CPU above 1) stretches the start deadline by that factor, at most this
START_LOCK_CAP_ENV = "SIMON7_P2_START_LOCK_CAP_S"  # TICKET-188: most extra seconds a start may wait for another process's GPU lock
START_LOCK_CAP_S = 900.0
LOCK_POLL_S = 1.0
LOG_TAIL_LINES = 5
HEALTH_TIMEOUT_S = 2.0
LEASE_WAIT_S = 5.0  # env SIMON7_P2_LEASE_WAIT_S: the longest a call waits for the busy worker, then it runs in-process
SOCK_PATH_MAX = 96  # AF_UNIX paths are limited to 107 bytes
RETRY_DOWN_S = 300.0  # a worker whose restart failed is tried again no sooner than this
KILL_GRACE_S = 10.0  # a killed worker gets this long to end after SIGTERM before SIGKILL
LOCK_FREE_WAIT_S = 30.0  # after a kill, the longest to wait for the GPU file lock to be free
RESIDENT_RANGE_MIB = (3000, 4600)  # TICKET-320: a tracker load reading outside this is other work (fresh load 4038)
RESIDENT_KEEP = 5  # the resident size is the median of the last this many accepted readings
TRACK_MARKER = b"--mode\x00track"  # /proc/<pid>/cmdline of `part2 serve-worker --mode track`: NUL-separated arguments

Launcher = Callable[[list[str], Path, "Path | None", "dict[str, str] | None"], "subprocess.Popen[bytes]"]


def _launch(
    argv: list[str], log: Path, cwd: Path | None, env_extra: dict[str, str] | None
) -> "subprocess.Popen[bytes]":
    log.parent.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, **(env_extra or {})}
    env.pop("VIRTUAL_ENV", None)
    with log.open("ab") as sink:
        return subprocess.Popen(
            argv, cwd=cwd, env=env, stdout=sink, stderr=subprocess.STDOUT, start_new_session=True
        )


def start_scale(load1: float, cpus: int | None = None) -> float:
    """How far a busy host stretches the start deadline: load1 per CPU, between 1 and `START_LOAD_SCALE_MAX`."""
    return min(START_LOAD_SCALE_MAX, max(1.0, load1 / max(1, cpus or os.cpu_count() or 1)))


def _load1() -> float:
    try:
        return os.getloadavg()[0]
    except OSError:
        return 0.0


def _foreign_lock_holder(proc: "subprocess.Popen[bytes]", lock_path: Path | None) -> int | None:
    """Pid of a process other than the starting worker (and its children) that holds the GPU flock, else None."""
    try:
        pid = gpu_lock.lock_holder_pid(lock_path if lock_path is not None else config.gpu_lock_path())
    except OSError:
        return None
    own = getattr(proc, "pid", None)
    if pid is None or (own is not None and (pid == own or gpu_lock._read_ppid_and_age(pid)[0] == own)):
        return None
    return pid


def _exit_text(code: int) -> str:
    return f"signal {-code}" if code < 0 else f"exit code {code}"


def _log_tail(log: Path) -> str:
    """The last lines of a worker log, for the reason a start was abandoned (`; log: a | b`)."""
    try:
        lines = [x.strip()[:200] for x in log.read_text(encoding="utf-8", errors="replace").splitlines() if x.strip()]
    except OSError:
        return "; no worker log"
    return f"; log: {' | '.join(lines[-LOG_TAIL_LINES:])}" if lines else "; the worker log is empty"


def healthy(sock_path: Path) -> bool:
    """True when something accepts connections on the worker socket."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
            probe.settimeout(HEALTH_TIMEOUT_S)
            probe.connect(str(sock_path))
        return True
    except OSError:
        return False


def _is_tracker(cmd: bytes) -> bool:
    """True when a /proc cmdline is a `serve-worker --mode track` (the warm tracker, not the 3D worker)."""
    return TRACK_MARKER in cmd or b"--mode=track" in cmd


def _marker_matches(cmd: bytes, marker: bytes) -> bool:
    """True when `cmd` is the kind of worker `marker` names. The tracker marker is `--mode` then `track`; the 3D
    marker `serve-worker` never matches a tracker, so a stale pidfile of one pool cannot kill the other's worker."""
    if marker == TRACK_MARKER:
        return _is_tracker(cmd) and b"serve-worker" in cmd
    return marker in cmd and not _is_tracker(cmd)


def _reap_orphan(pidfile: Path, marker: bytes = b"serve-worker") -> None:
    """Stop a `serve-worker` a killed server left behind (its pid is in `pidfile`); it still holds GPU memory."""
    try:
        pid = int(pidfile.read_text(encoding="utf-8").strip())
        cmd = Path(f"/proc/{pid}/cmdline").read_bytes()
    except (OSError, ValueError):
        return
    if pid > 1 and _marker_matches(cmd, marker):
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)  # the worker leads its own session (`_launch`)
        except OSError:
            pass


class _Slot:
    def __init__(self, index: int, sock: Path, log: Path) -> None:
        self.index, self.sock, self.log = index, sock, log
        self.pidfile = log.with_suffix(".pid")
        self.proc: "subprocess.Popen[bytes] | None" = None
        self.busy = False  # leased to a call
        self.starting = False  # being (re)started
        self.down_until = 0.0  # monotonic time before which a failed worker is not restarted
        self.why = ""  # why the last start was abandoned
        self.released = False  # stopped on purpose (idle, timed out or not yet needed); the next lease starts it
        self.restart = False  # the leased call timed out: stop the worker when the lease ends (`Pool.mark_restart`)
        self.last_used = time.monotonic()
        self.version: "str | None" = None  # the pin the running worker started with (Pool `version`)
        self.free_before: "int | None" = None  # TICKET-320: free GPU MiB just before this worker's launch
        self.marks: "tuple[int, tuple[int, int]] | None" = None  # load and GPU admission marks at that reading
        self.loading = False  # counted in `_LOADS` (any pool's worker loading now)


class Pool:
    """`slots` workers started from `argv_for(socket_path)`; `lease()` lends a healthy idle one."""

    def __init__(
        self, state_dir: Path, slots: int, argv_for: Callable[[Path], list[str]],
        launcher: Launcher = _launch, health: Callable[[Path], bool] = healthy, start_wait_s: float = START_WAIT_S,
        cwd: Path | None = None, env: dict[str, str] | None = None, lease_wait_s: float | None = None,
        label: str = "p2_worker", folder: str = "p2-workers", marker: bytes = b"serve-worker",
        on_demand: bool = False, idle_release_s: float = 0.0, on_started: Callable[[], None] | None = None,
        load1: Callable[[], float] = _load1, version: Callable[[], "str | None"] | None = None,
        gpu_lock_path: Path | None = None,
        measure_free: Callable[[], "int | None"] | None = None,
    ) -> None:
        self._load1, self._version, self._gpu_lock_path = load1, version, gpu_lock_path
        self._measure_free = measure_free  # TICKET-320: free GPU MiB, read around each load (`resident_mib`)
        self._readings: "collections.deque[int]" = collections.deque(maxlen=RESIDENT_KEEP)
        self.label, self._marker, self._on_demand = label, marker, on_demand
        self._idle_release_s, self._on_started = idle_release_s, on_started
        root = Path(state_dir) / folder
        root.mkdir(parents=True, exist_ok=True)
        # an AF_UNIX path holds about 100 bytes; a long state folder keeps its sockets in a short private one
        sock_root = root if len(str(root / "w0.sock")) <= SOCK_PATH_MAX else Path(tempfile.mkdtemp(prefix="s7p2-"))
        self._slots = [_Slot(i, sock_root / f"w{i}.sock", root / f"w{i}.log") for i in range(slots)]
        self._argv_for, self._launcher, self._health, self._wait = argv_for, launcher, health, start_wait_s
        self._cwd, self._env = cwd, env
        self._lease_wait_s = lease_wait_s if lease_wait_s is not None else applog.env_float(
            "SIMON7_P2_LEASE_WAIT_S", LEASE_WAIT_S)
        self._lock = threading.Condition()
        self._closed = False

    def _spawn(self, slot: _Slot) -> bool:
        """Start the worker of `slot` and wait for its socket; False when it never answers."""
        self._kill(slot)
        _reap_orphan(slot.pidfile, self._marker)
        slot.sock.unlink(missing_ok=True)
        _loads(slot, 1)
        slot.free_before = self._measure_free() if self._measure_free else None  # the old worker is gone by now
        slot.marks = (_load_events(), gpu_lock.activity())
        if self._closed:
            slot.why = "the pool was stopped"
            return False
        slot.version = self._version() if self._version else None  # read before launch: the worker loads this pin
        proc = slot.proc = self._launcher(self._argv_for(slot.sock), slot.log, self._cwd, self._env)
        if self._closed:  # stop() ran while the process launched: it never saw this one, so end it here
            self._kill(slot)
            slot.why = "the pool was stopped"
            return False
        slot.pidfile.write_text(str(getattr(proc, "pid", 0)), encoding="utf-8")
        began = time.monotonic()
        lock_wait, last_poll, announced = 0.0, began, False  # TICKET-188: time spent behind another process's GPU lock
        cap = applog.env_float(START_LOCK_CAP_ENV, START_LOCK_CAP_S)
        while True:
            if self._closed:  # stop() killed the process and cleared slot.proc under this loop
                self._kill(slot)
                slot.why = "the pool was stopped"
                return False
            elapsed = time.monotonic() - began
            code = proc.poll()
            if code is not None:
                slot.why = f"the process exited with {_exit_text(code)} after {elapsed:.0f} s{_log_tail(slot.log)}"
                return False
            if self._health(slot.sock):
                slot.released, slot.last_used = False, time.monotonic()
                return True
            now = time.monotonic()
            if now - last_poll >= LOCK_POLL_S and lock_wait < cap:
                holder = _foreign_lock_holder(proc, self._gpu_lock_path)
                if holder is not None:  # Part 2 builds its model under the host GPU lock: that wait is not the worker's
                    lock_wait = min(cap, lock_wait + now - last_poll)
                    if not announced:
                        announced = True
                        applog.log(f"{self.label}: worker start waiting for the GPU lock held by pid {holder} "
                                   f"({gpu_lock._read_cmdline(holder)})")
                last_poll = now
            elif now - last_poll >= LOCK_POLL_S:
                last_poll = now
            load = self._load1()
            limit = self._wait * start_scale(load) + lock_wait  # re-read each pass: a host that gets busier gives it more time
            if elapsed >= limit:
                slot.why = (f"no answer within {elapsed:.0f} s (limit {limit:.0f} s, load1 {load:.1f} on "
                            f"{os.cpu_count() or 1} CPUs){_log_tail(slot.log)}")
                self._kill(slot)
                return False
            time.sleep(0.2)

    def _kill_group(self, slot: _Slot) -> None:
        """End the worker of `slot` and its process group, returning only when the process is gone (TICKET-129).

        The worker leads its own session (`_launch`), so the group is its own; the pid is checked against the
        worker's command line first. A process that cannot be verified is ended with `_kill` alone.
        """
        proc = slot.proc
        pid = getattr(proc, "pid", None)
        if proc is None or not isinstance(pid, int) or pid <= 1 or proc.poll() is not None or not self._ours(pid):
            self._kill(slot)
            return
        slot.proc = None
        try:
            pgid = os.getpgid(pid)
            os.killpg(pgid, signal.SIGTERM) if pgid == pid else os.kill(pid, signal.SIGTERM)
            try:
                proc.wait(timeout=KILL_GRACE_S)
            except subprocess.TimeoutExpired:
                os.killpg(pgid, signal.SIGKILL) if pgid == pid else os.kill(pid, signal.SIGKILL)
                proc.wait(timeout=KILL_GRACE_S)
            if pgid == pid:
                os.killpg(pgid, signal.SIGKILL)  # children the leader left behind (ESRCH when none)
        except OSError:
            pass

    def _ours(self, pid: int) -> bool:
        try:
            return _marker_matches(Path(f"/proc/{pid}/cmdline").read_bytes(), self._marker)
        except OSError:
            return False

    def _stop_hard(self, slot: _Slot) -> None:
        """Stop the worker, drop its files and wait until the GPU file lock is free; the next lease starts it again.

        Callable only for a slot nobody else holds (leased by this caller). The GPU memory and any lock the worker
        held go back to the host before the caller runs a cold call.
        """
        self._kill_group(slot)
        slot.sock.unlink(missing_ok=True)
        slot.pidfile.unlink(missing_ok=True)
        if not gpu_lock.wait_free(self._gpu_lock_path, LOCK_FREE_WAIT_S):
            applog.anomaly(f"{self.label}_unhealthy", "the GPU lock is still held after the worker was stopped",
                           slot=slot.index)
        with self._lock:
            slot.released, slot.restart = True, False

    def mark_restart(self, sock: Path) -> None:
        """The call leased on `sock` timed out: the worker still runs it and holds the GPU lock, so it is stopped
        when the lease ends (before the caller's next step) and started again at the next lease."""
        with self._lock:
            for slot in self._slots:
                if slot.sock == sock and slot.busy:
                    slot.restart = True

    def holds_model(self) -> bool:
        """True when a worker process runs or is starting (its model is, or is about to be, in GPU memory)."""
        with self._lock:
            return any(s.starting or (s.proc is not None and s.proc.poll() is None) for s in self._slots)

    def _measure_loaded(self, slot: _Slot) -> None:
        """TICKET-320: the drop in free GPU memory across this load is a reading of the worker's resident size, taken
        before the slot is lendable (no call can grow it yet). Kept only when the window was clean (this was the only
        worker loading, in any pool, and no GPU admission of this process waited, ran or ended) and the drop is inside
        `RESIDENT_RANGE_MIB`; both warm workers start in the same second at a server start, and that drop is both."""
        before, marks, slot.free_before, slot.marks = slot.free_before, slot.marks, None, None
        after = self._measure_free() if self._measure_free and before is not None else None
        clean = (marks is not None and marks == (_load_events(), gpu_lock.activity())
                 and marks[0][1] == 1 and marks[1][1] == 0)
        if before is None or after is None:
            return
        low, high = RESIDENT_RANGE_MIB
        drop = before - after
        if not clean or not low <= drop <= high:
            why = "another load or GPU call in the window" if not clean else f"outside {low} to {high} MiB"
            applog.log(f"{self.label}: load reading {drop} MiB not used ({why}; free {before} to {after} MiB)")
            return
        with self._lock:
            self._readings.append(drop)
        applog.log(f"{self.label}: resident {drop} MiB measured at load (free {before} to {after} MiB)")

    @property
    def resident_mib(self) -> int | None:
        """The median of the last `RESIDENT_KEEP` accepted load readings, else None (TICKET-320)."""
        with self._lock:
            kept = list(self._readings)
        return int(statistics.median(kept)) if kept else None

    def wait_ready(self, wait_s: float) -> bool:
        """TICKET-320: True once a worker runs and nobody leases it (`lease` would lend it now). Waits at most `wait_s`
        while a worker is leased or starting; False at once when none runs, is leased or starts, and when stopped."""
        deadline = time.monotonic() + max(0.0, wait_s)
        with self._lock:
            while not self._closed:
                if any(not s.busy and not s.starting and s.proc is not None and s.proc.poll() is None
                       for s in self._slots):
                    return True
                if not any(s.busy or s.starting or (s.proc is not None and s.proc.poll() is None) for s in self._slots):
                    return False
                left = deadline - time.monotonic()
                if left <= 0:
                    return False
                self._lock.wait(min(left, 1.0))
        return False

    def release_all(self, wait_s: float) -> bool:
        """Stop every worker so a cold call has the GPU memory; a lease starts it again. Waits up to `wait_s` for a
        slot that is leased or starting; False when one stayed (its model stays loaded)."""
        deadline = time.monotonic() + max(0.0, wait_s)
        done = True
        for slot in self._slots:
            with self._lock:
                while (slot.busy or slot.starting) and not self._closed and time.monotonic() < deadline:
                    self._lock.wait(max(0.01, deadline - time.monotonic()))
                if slot.busy or slot.starting or self._closed:
                    done = done and not (slot.busy or slot.starting)
                    continue
                slot.busy = True
            try:
                self._stop_hard(slot)
                applog.log(f"{self.label}_released: stopped before a cold call, the model's GPU memory is freed")
            finally:
                with self._lock:
                    slot.busy = False
                    self._lock.notify_all()
        return done

    @staticmethod
    def _kill(slot: _Slot) -> None:
        proc, slot.proc = slot.proc, None
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()

    def start(self) -> None:
        """Start every worker in the background; leases return None until a worker answers."""
        for slot in self._slots:
            _reap_orphan(slot.pidfile, self._marker)  # a killed server's worker still holds GPU memory (both modes)
            if self._on_demand:
                slot.released = True  # started by the first lease
            else:
                self._start_async(slot)
        if self._idle_release_s > 0:
            threading.Thread(target=self._watch_idle, name=f"part7-{self.label}-idle", daemon=True).start()

    def _watch_idle(self) -> None:
        """Release a worker that has been idle for `idle_release_s`: its GPU memory goes back to the host."""
        period = max(0.05, min(5.0, self._idle_release_s / 4))
        while True:
            with self._lock:
                if self._closed:
                    return
                self._lock.wait(period)
                if self._closed:
                    return
                now = time.monotonic()
                due = [s for s in self._slots if not s.busy and not s.starting and not s.released
                       and s.proc is not None and now - s.last_used >= self._idle_release_s]
                for s in due:
                    s.busy = True  # not lendable while it is stopped
            for s in due:
                self._kill(s)
                s.sock.unlink(missing_ok=True)
                applog.log(f"{self.label}_released: idle for {self._idle_release_s:.0f} s, the model's GPU memory is freed")
                with self._lock:
                    s.released, s.busy = True, False
                    self._lock.notify_all()

    def _start_async(self, slot: _Slot) -> None:
        with self._lock:
            if self._closed or slot.starting:
                return
            slot.starting = True  # not lendable while it starts
        threading.Thread(target=self._start_slot, args=(slot,), name=f"part7-p2w{slot.index}", daemon=True).start()

    def _start_slot(self, slot: _Slot) -> None:
        ok = self._spawn(slot)
        if ok:
            self._measure_loaded(slot)  # before the slot is lendable: no call grows it while `after` is read
        _loads(slot, -1)
        with self._lock:
            slot.starting = False
            slot.down_until = 0.0 if ok else time.monotonic() + RETRY_DOWN_S
            self._lock.notify_all()
        if not ok and not self._closed:
            applog.anomaly(f"{self.label}_unhealthy", "the worker did not start or restart; calls run in-process",
                           slot=slot.index, retry_in_s=RETRY_DOWN_S, why=slot.why or None)
        elif self._on_started is not None:
            self._on_started()
        if ok:
            selfheal.record("warm_worker")  # started or restarted clean

    def _ok(self, slot: _Slot) -> bool:
        return slot.proc is not None and slot.proc.poll() is None and self._health(slot.sock)

    def life(self) -> int | None:
        """Pid of the first slot's running worker process, or None when none runs (a restart gives a new pid)."""
        with self._lock:
            proc = self._slots[0].proc if self._slots else None
        return getattr(proc, "pid", None) if proc is not None and proc.poll() is None else None

    def state(self) -> str:
        """`starting`, `busy` (leased), `idle`, or `down` (no healthy worker); read without waiting."""
        with self._lock:
            slots = list(self._slots)
            closed = self._closed
        if closed:
            return "off"
        if any(s.starting for s in slots):
            return "starting"
        if any(s.busy for s in slots):
            return "busy"
        if any(s.proc is not None and s.proc.poll() is None for s in slots):
            return "idle"
        return "released" if slots and all(s.released for s in slots) else "down"

    @contextlib.contextmanager
    def lease(self, wait_s: float | None = None) -> Iterator[Path | None]:
        """Lend a healthy idle worker's socket, waiting at most `wait_s` (default `LEASE_WAIT_S`) for a busy one.

        None when none is free in time, one is starting or down, or the worker failed its health check (it is then
        restarted once in the background, with `ANOMALY p2_worker_unhealthy`). Never waits for a model load.
        """
        slot = self._take(self._lease_wait_s if wait_s is None else wait_s)
        try:
            if slot is None:
                yield None
            elif self._pin_changed(slot):
                applog.log(f"{self.label}_restart: the Part 2 pin changed ({slot.version} to {self._version()}); "
                           "the worker restarts and this call runs per-call")
                self._start_async(slot)
                yield None
            elif slot.released:
                self._start_async_blocking(slot)  # the first call after boot, an idle release or a stop pays the load
                yield slot.sock if self._ok(slot) else None
            elif self._ok(slot):
                yield slot.sock
            else:
                applog.anomaly(f"{self.label}_unhealthy", "the worker failed its health check; restarting once",
                               slot=slot.index)
                self._start_async(slot)
                yield None
        finally:
            if slot is not None:
                if slot.restart:
                    self._stop_hard(slot)  # a timed-out call: gone, and the GPU lock free, before the caller goes on
                with self._lock:
                    slot.busy, slot.last_used = False, time.monotonic()
                    self._lock.notify_all()

    def _pin_changed(self, slot: _Slot) -> bool:
        """True when a running worker started with a pin that is no longer the one on disk (unknown reads never restart)."""
        if self._version is None or slot.released or slot.proc is None or slot.version is None:
            return False
        now = self._version()
        return now is not None and now != slot.version

    def _start_async_blocking(self, slot: _Slot) -> None:
        """Start the leased `slot` here and wait for it (no other call can lease it: it is busy)."""
        self._start_slot(slot)

    def _take(self, wait_s: float) -> _Slot | None:
        deadline = time.monotonic() + max(0.0, wait_s)
        with self._lock:
            while not self._closed:
                live = [s for s in self._slots if not s.starting and time.monotonic() >= s.down_until]
                for slot in live:
                    if not slot.busy:
                        slot.busy = True
                        return slot
                left = deadline - time.monotonic()
                if left <= 0 or not live:
                    return None  # starting or down workers are not waited for, only a busy one is
                self._lock.wait(left)
        return None

    def stop(self) -> None:
        with self._lock:
            self._closed = True
            self._lock.notify_all()
        for slot in self._slots:
            self._kill(slot)
            slot.sock.unlink(missing_ok=True)
            slot.pidfile.unlink(missing_ok=True)
        # a spawn that was mid-launch kills its own process on seeing _closed (see _spawn)


_POOL: Pool | None = None
_TRACK_POOL: Pool | None = None
_LOAD_LOCK = threading.Lock()
_LOAD = {"active": 0, "events": 0}  # TICKET-320: workers loading now in any pool, and every load start and end


def _loads(slot: _Slot, step: int) -> None:
    """Count `slot`'s load in or out (once each way) across every pool."""
    with _LOAD_LOCK:
        if (step > 0) == slot.loading:
            return
        slot.loading = step > 0
        _LOAD["active"] = max(0, _LOAD["active"] + step)
        _LOAD["events"] += 1


def _load_events() -> tuple[int, int]:
    """`(events, active)`: equal readings with active 1 (this load) mean no other worker started or ended meanwhile."""
    with _LOAD_LOCK:
        return _LOAD["events"], _LOAD["active"]


def start_pool(pool: Pool) -> None:
    """Make `pool` the process-wide pool and start its workers."""
    global _POOL
    stop_pool()
    _POOL = pool
    pool.start()


def stop_pool() -> None:
    global _POOL
    pool, _POOL = _POOL, None
    if pool is not None:
        pool.stop()


def start_track_pool(pool: Pool) -> None:
    """Make `pool` the process-wide warm tracker pool (`stop_track_pool` stops it)."""
    global _TRACK_POOL
    stop_track_pool()
    _TRACK_POOL = pool
    pool.start()


def stop_track_pool() -> None:
    global _TRACK_POOL
    pool, _TRACK_POOL = _TRACK_POOL, None
    if pool is not None:
        pool.stop()


def track_state() -> str:
    """The warm tracker pool's state (`off`, `released`, `starting`, `busy`, `idle` or `down`)."""
    return "off" if _TRACK_POOL is None else _TRACK_POOL.state()


@contextlib.contextmanager
def track_lease(wait_s: float | None = None) -> Iterator[Path | None]:
    """The warm tracker pool's `lease` (waiting at most `wait_s` for a busy worker), or None when no pool runs."""
    if _TRACK_POOL is None:
        yield None
    else:
        with _TRACK_POOL.lease(wait_s) as sock:
            yield sock


def track_mark_restart(sock: Path) -> None:
    """The warm call on `sock` timed out: stop that worker when its lease ends (see `Pool.mark_restart`)."""
    if _TRACK_POOL is not None:
        _TRACK_POOL.mark_restart(sock)


def track_holds_model() -> bool:
    """True when the warm tracker pool has a worker running or starting."""
    return _TRACK_POOL is not None and _TRACK_POOL.holds_model()


def stop_track_worker(wait_s: float) -> bool:
    """Stop the warm tracker's worker process (the pool stays; the next lease starts it). False when it stayed up."""
    return _TRACK_POOL is None or _TRACK_POOL.release_all(wait_s)


def release_idle_workers() -> list[str]:
    """Give the GPU memory of every idle warm worker back (the process pool and the tracker); a leased or starting
    worker is never touched, so a running take keeps its model. Returns the labels released (the next lease restarts them)."""
    out = []
    for pool in (_POOL, _TRACK_POOL):
        if pool is not None and pool.state() == "idle" and pool.release_all(0.0):
            out.append(pool.label)
    return out


def own_warm_worker(pid: int | None) -> bool:
    """True when `pid` is a warm worker this server started (or a child of one): a worker `release_idle_workers` is
    stopping still holds the GPU lock and memory for a moment, and that is not another job (avatar_jobs._why_busy)."""
    if not pid:
        return False
    me = os.getpid()
    parent = gpu_lock._read_ppid_and_age(pid)[0]
    for cand in (pid, parent):
        if cand and gpu_lock._read_ppid_and_age(cand)[0] == me \
                and any(pool is not None and pool._ours(cand) for pool in (_POOL, _TRACK_POOL)):
            return True
    return False


def state() -> str:
    """The process pool's worker state for the heartbeat: `off` when no pool runs, else `Pool.state()`."""
    return "off" if _POOL is None else _POOL.state()


@contextlib.contextmanager
def lease() -> Iterator[Path | None]:
    """The process pool's `lease`, or None when no pool runs."""
    if _POOL is None:
        yield None
    else:
        with _POOL.lease() as sock:
            yield sock


def worker_life() -> int | None:
    """The pid of the process pool's running worker (one value per worker life, TICKET-260), else None."""
    return None if _POOL is None else _POOL.life()


def holds_model() -> bool:
    """True when the process pool (the 3D pose worker) has a worker running or starting (TICKET-320)."""
    return _POOL is not None and _POOL.holds_model()


def wait_ready(wait_s: float) -> bool:
    """The process pool's `Pool.wait_ready`: False at once when no pool runs."""
    return _POOL is not None and _POOL.wait_ready(wait_s)


def track_wait_ready(wait_s: float) -> bool:
    """The warm tracker pool's `Pool.wait_ready`: False at once when no pool runs."""
    return _TRACK_POOL is not None and _TRACK_POOL.wait_ready(wait_s)


def track_resident_mib() -> int | None:
    """The warm tracker's resident size measured at its loads (`Pool.resident_mib`), else None (TICKET-320)."""
    return None if _TRACK_POOL is None else _TRACK_POOL.resident_mib
