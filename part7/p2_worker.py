"""Warm Part 2 worker: one `part2 serve-worker` (TICKET-099), kept for the life of `part7 serve`.

A worker keeps the 3D model loaded (20 to 35 s of every `part2 run`). The pool starts only when the pinned Part 2
has `run --worker`; a `run` borrows the worker with `lease()` and passes `--worker <socket>`. The worker serves one
request at a time, so a call that cannot lease it within `LEASE_WAIT_S` runs in-process as before and never queues
behind it. An unhealthy worker logs `ANOMALY p2_worker_unhealthy`, is restarted once in the background (the
calls meanwhile run in-process) and, if that restart fails, is left down for `RETRY_DOWN_S`.

The same `Pool` also runs the warm SAM 3.1 tracker (TICKET-117, `part7/trackwarm/track_worker.py`) as a second,
independent pool (`start_track_pool`). It differs in two ways, both opt-in on `Pool`: it starts on the first call
and not at boot (`on_demand`), and it gives the GPU memory back after `idle_release_s` without a call
(`ANOMALY`-free: `p2_tracker_released` is a log line), so a quiet host holds only the 3D worker.
"""

from __future__ import annotations

import contextlib
import os
import socket
import signal
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable, Iterator

from part7 import applog

START_WAIT_S = 180.0  # a worker loads its model before it listens (on an idle host)
START_LOAD_SCALE_MAX = 4.0  # a busy host (load1 per CPU above 1) stretches the start deadline by that factor, at most this
LOG_TAIL_LINES = 5
HEALTH_TIMEOUT_S = 2.0
LEASE_WAIT_S = 5.0  # env SIMON7_P2_LEASE_WAIT_S: the longest a call waits for the busy worker, then it runs in-process
SOCK_PATH_MAX = 96  # AF_UNIX paths are limited to 107 bytes
RETRY_DOWN_S = 300.0  # a worker whose restart failed is tried again no sooner than this

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


def _reap_orphan(pidfile: Path, marker: bytes = b"serve-worker") -> None:
    """Stop a `serve-worker` a killed server left behind (its pid is in `pidfile`); it still holds GPU memory."""
    try:
        pid = int(pidfile.read_text(encoding="utf-8").strip())
        cmd = Path(f"/proc/{pid}/cmdline").read_bytes()
    except (OSError, ValueError):
        return
    if pid > 1 and marker in cmd:
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
        self.released = False  # stopped on purpose (idle or not yet needed); the next lease starts it
        self.last_used = time.monotonic()


class Pool:
    """`slots` workers started from `argv_for(socket_path)`; `lease()` lends a healthy idle one."""

    def __init__(
        self, state_dir: Path, slots: int, argv_for: Callable[[Path], list[str]],
        launcher: Launcher = _launch, health: Callable[[Path], bool] = healthy, start_wait_s: float = START_WAIT_S,
        cwd: Path | None = None, env: dict[str, str] | None = None, lease_wait_s: float | None = None,
        label: str = "p2_worker", folder: str = "p2-workers", marker: bytes = b"serve-worker",
        on_demand: bool = False, idle_release_s: float = 0.0, on_started: Callable[[], None] | None = None,
        load1: Callable[[], float] = _load1,
    ) -> None:
        self._load1 = load1
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
        if self._closed:
            slot.why = "the pool was stopped"
            return False
        proc = slot.proc = self._launcher(self._argv_for(slot.sock), slot.log, self._cwd, self._env)
        if self._closed:  # stop() ran while the process launched: it never saw this one, so end it here
            self._kill(slot)
            slot.why = "the pool was stopped"
            return False
        slot.pidfile.write_text(str(getattr(proc, "pid", 0)), encoding="utf-8")
        began = time.monotonic()
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
            load = self._load1()
            limit = self._wait * start_scale(load)  # re-read each pass: a host that gets busier gives it more time
            if elapsed >= limit:
                slot.why = (f"no answer within {elapsed:.0f} s (limit {limit:.0f} s, load1 {load:.1f} on "
                            f"{os.cpu_count() or 1} CPUs){_log_tail(slot.log)}")
                self._kill(slot)
                return False
            time.sleep(0.2)

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
        with self._lock:
            slot.starting = False
            slot.down_until = 0.0 if ok else time.monotonic() + RETRY_DOWN_S
            self._lock.notify_all()
        if not ok and not self._closed:
            applog.anomaly(f"{self.label}_unhealthy", "the worker did not start or restart; calls run in-process",
                           slot=slot.index, retry_in_s=RETRY_DOWN_S, why=slot.why or None)
        elif self._on_started is not None:
            self._on_started()

    def _ok(self, slot: _Slot) -> bool:
        return slot.proc is not None and slot.proc.poll() is None and self._health(slot.sock)

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
            elif slot.released and self._on_demand:
                self._start_async_blocking(slot)  # the first call after boot or an idle release pays the model load
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
                with self._lock:
                    slot.busy, slot.last_used = False, time.monotonic()
                    self._lock.notify_all()

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
def track_lease() -> Iterator[Path | None]:
    """The warm tracker pool's `lease`, or None when no pool runs."""
    if _TRACK_POOL is None:
        yield None
    else:
        with _TRACK_POOL.lease() as sock:
            yield sock


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
