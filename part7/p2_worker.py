"""Warm Part 2 workers: one `part2 serve-worker` per GPU worker slot, kept for the life of `part7 serve`.

A worker keeps the 3D model loaded (about 35 s of every follow job). The pool starts only when the pinned Part 2
has `run --worker`; jobs borrow a worker with `lease()` and pass `--worker <socket>`. A dead or unhealthy worker is
restarted on the next lease; with none free, the job runs in-process as before.
"""

from __future__ import annotations

import contextlib
import os
import socket
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable, Iterator

START_WAIT_S = 180.0  # a worker loads its model before it listens
HEALTH_TIMEOUT_S = 2.0

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


class _Slot:
    def __init__(self, index: int, sock: Path, log: Path) -> None:
        self.index, self.sock, self.log = index, sock, log
        self.proc: "subprocess.Popen[bytes] | None" = None
        self.busy = False


class Pool:
    """`slots` workers started from `argv_for(socket_path)`; `lease()` lends a healthy idle one."""

    def __init__(
        self, state_dir: Path, slots: int, argv_for: Callable[[Path], list[str]],
        launcher: Launcher = _launch, health: Callable[[Path], bool] = healthy, start_wait_s: float = START_WAIT_S,
        cwd: Path | None = None, env: dict[str, str] | None = None,
    ) -> None:
        root = Path(state_dir) / "p2-workers"
        root.mkdir(parents=True, exist_ok=True)
        self._slots = [_Slot(i, root / f"w{i}.sock", root / f"w{i}.log") for i in range(slots)]
        self._argv_for, self._launcher, self._health, self._wait = argv_for, launcher, health, start_wait_s
        self._cwd, self._env = cwd, env
        self._lock = threading.Lock()
        self._closed = False

    def _spawn(self, slot: _Slot) -> bool:
        """Start the worker of `slot` and wait for its socket; False when it never answers."""
        self._kill(slot)
        slot.sock.unlink(missing_ok=True)
        slot.proc = self._launcher(self._argv_for(slot.sock), slot.log, self._cwd, self._env)
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
            threading.Thread(target=self._start_slot, args=(slot,), name=f"part7-p2w{slot.index}", daemon=True).start()

    def _start_slot(self, slot: _Slot) -> None:
        with self._lock:
            if self._closed:
                return
            slot.busy = True  # not lendable while it starts
        self._spawn(slot)
        with self._lock:
            slot.busy = False  # a worker that failed to start is retried by `lease`

    def _ok(self, slot: _Slot) -> bool:
        return slot.proc is not None and slot.proc.poll() is None and self._health(slot.sock)

    @contextlib.contextmanager
    def lease(self) -> Iterator[Path | None]:
        """Lend one healthy idle worker's socket (restarting a failed one once), else None; never waits."""
        slot = self._take()
        try:
            if slot is None:
                yield None
            elif self._ok(slot) or self._spawn(slot):
                yield slot.sock
            else:
                yield None
        finally:
            if slot is not None:
                with self._lock:
                    slot.busy = False

    def _take(self) -> _Slot | None:
        with self._lock:
            if self._closed:
                return None
            for slot in self._slots:
                if not slot.busy:
                    slot.busy = True
                    return slot
        return None

    def stop(self) -> None:
        with self._lock:
            self._closed = True
        for slot in self._slots:
            self._kill(slot)
            slot.sock.unlink(missing_ok=True)


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


@contextlib.contextmanager
def lease() -> Iterator[Path | None]:
    """The process pool's `lease`, or None when no pool runs."""
    if _POOL is None:
        yield None
    else:
        with _POOL.lease() as sock:
            yield sock
