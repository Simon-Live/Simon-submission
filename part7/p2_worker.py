"""Warm Part 2 worker: one `part2 serve-worker` (TICKET-099), kept for the life of `part7 serve`.

A worker keeps the 3D model loaded (20 to 35 s of every `part2 run`). The pool starts only when the pinned Part 2
has `run --worker`; a `run` borrows the worker with `lease()` and passes `--worker <socket>`. The worker serves one
request at a time, so a call that cannot lease it within `LEASE_WAIT_S` runs in-process as before and never queues
behind it. An unhealthy worker logs `ANOMALY p2_worker_unhealthy`, is restarted once in the background (the
calls meanwhile run in-process) and, if that restart fails, is left down for `RETRY_DOWN_S`.
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

START_WAIT_S = 180.0  # a worker loads its model before it listens
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


def healthy(sock_path: Path) -> bool:
    """True when something accepts connections on the worker socket."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
            probe.settimeout(HEALTH_TIMEOUT_S)
            probe.connect(str(sock_path))
        return True
    except OSError:
        return False


def _reap_orphan(pidfile: Path) -> None:
    """Stop a `serve-worker` a killed server left behind (its pid is in `pidfile`); it still holds GPU memory."""
    try:
        pid = int(pidfile.read_text(encoding="utf-8").strip())
        cmd = Path(f"/proc/{pid}/cmdline").read_bytes()
    except (OSError, ValueError):
        return
    if pid > 1 and b"serve-worker" in cmd:
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


class Pool:
    """`slots` workers started from `argv_for(socket_path)`; `lease()` lends a healthy idle one."""

    def __init__(
        self, state_dir: Path, slots: int, argv_for: Callable[[Path], list[str]],
        launcher: Launcher = _launch, health: Callable[[Path], bool] = healthy, start_wait_s: float = START_WAIT_S,
        cwd: Path | None = None, env: dict[str, str] | None = None, lease_wait_s: float | None = None,
    ) -> None:
        root = Path(state_dir) / "p2-workers"
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
        _reap_orphan(slot.pidfile)
        slot.sock.unlink(missing_ok=True)
        slot.proc = self._launcher(self._argv_for(slot.sock), slot.log, self._cwd, self._env)
        slot.pidfile.write_text(str(getattr(slot.proc, "pid", 0)), encoding="utf-8")
        deadline = time.monotonic() + self._wait
        while time.monotonic() < deadline:
            if slot.proc.poll() is not None:
                return False
            if self._health(slot.sock):
                return True
            time.sleep(0.2)
        self._kill(slot)
        return False

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
            self._start_async(slot)

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
        if not ok:
            applog.anomaly("p2_worker_unhealthy", "the worker did not start or restart; calls run in-process",
                           slot=slot.index, retry_in_s=RETRY_DOWN_S)

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
        return "idle" if any(s.proc is not None and s.proc.poll() is None for s in slots) else "down"

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
            elif self._ok(slot):
                yield slot.sock
            else:
                applog.anomaly("p2_worker_unhealthy", "the worker failed its health check; restarting once",
                               slot=slot.index)
                self._start_async(slot)
                yield None
        finally:
            if slot is not None:
                with self._lock:
                    slot.busy = False
                    self._lock.notify_all()

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


_POOL: Pool | None = None


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
