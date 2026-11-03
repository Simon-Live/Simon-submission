"""Find and stop processes a test left behind (docs/specs/test-process-reclaim.md, TICKET-379).

Match is on a path argument under a root, never on a bare process name. Library for tests/conftest.py and a CLI for
finished runs:  python3 tests/process_reclaim.py --stale <pytest-N dir>... [--dry-run]
"""

from __future__ import annotations

import argparse
import getpass
import os
from pathlib import Path
import signal
import sys
import tempfile
import time

GRACE_S = 3.0
PYTEST_NAMES = ("pytest", "py.test")  # an argv element with one of these names marks a pytest process


def _read(path: str | Path) -> bytes:
    """Read a /proc file with plain open(), never Path.read_text/read_bytes: a test may monkeypatch those (to prove it
    reads no secret file), and this code runs in that test's teardown (TICKET-379)."""
    with open(path, "rb") as f:
        return f.read()


def _ppid_of(pid: int) -> int:
    return int(_read(f"/proc/{pid}/stat").decode().rsplit(")", 1)[1].split()[1])


def _ancestors() -> set[int]:
    found, pid = {os.getpid()}, os.getppid()
    while pid > 1 and pid not in found:
        found.add(pid)
        try:
            pid = _ppid_of(pid)
        except (OSError, ValueError, IndexError):
            break
    return found


def _roots(roots) -> list[str]:
    out: set[str] = set()
    for root in roots:
        out.add(str(root).rstrip("/"))
        out.add(os.path.realpath(root))
    return sorted(r for r in out if r and r != "/")


def _names(arg: str, roots: list[str]) -> bool:
    """The argument is a path under a root, bare or after `--opt=`."""
    value = arg.split("=", 1)[1] if arg.startswith("-") and "=" in arg else arg
    return any(value == r or value.startswith(r + "/") for r in roots)


def find_under(roots) -> list[tuple[int, int, list[str]]]:
    """(pid, ppid, argv) of every process whose argv names a path under one of the roots; not this process or its parents."""
    wanted, skip, found = _roots(roots), _ancestors(), []
    if not wanted:
        return found
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit() or int(entry.name) in skip:
            continue
        try:
            argv = [a for a in _read(entry / "cmdline").decode("utf-8", "replace").split("\0") if a]
            ppid = _ppid_of(int(entry.name))
        except (OSError, ValueError, IndexError):
            continue
        if any(_names(a, wanted) for a in argv):
            found.append((int(entry.name), ppid, argv))
    return found


def _alive(pid: int) -> bool:
    try:
        state = _read(f"/proc/{pid}/stat").decode().rsplit(")", 1)[1].split()[0]
    except (OSError, IndexError):
        return False
    return state != "Z"


def _signal(pid: int, sig: int) -> bool:
    try:
        os.kill(pid, sig)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    return True


def stop(pids: list[int], grace: float = GRACE_S) -> list[int]:
    """SIGTERM, then SIGKILL after the grace. Returns the pids that could not be signalled."""
    denied = [p for p in pids if not _signal(p, signal.SIGTERM)]
    live = [p for p in pids if p not in denied]
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline and any(_alive(p) for p in live):
        time.sleep(0.05)
    denied += [p for p in live if _alive(p) and not _signal(p, signal.SIGKILL)]
    return denied


def reap(roots, grace: float = GRACE_S) -> list[int]:
    """Stop everything whose argv names a path under the roots; returns the pids it stopped."""
    pids = [pid for pid, _, _ in find_under(roots)]
    if pids:
        stop(pids, grace)
    return pids


def pytest_base() -> Path:
    return Path(tempfile.gettempdir()) / f"pytest-of-{getpass.getuser()}"


def check_stale_root(root: str, base: Path | None = None) -> Path:
    """A finished run's own `pytest-N` folder under the pytest base dir; pytest-current and anything else is refused."""
    base = (base or pytest_base()).resolve()
    path = Path(root)
    if path.name == "pytest-current" or path.is_symlink():
        raise ValueError(f"{root}: pytest-current or a link is never a stale root")
    path = path.resolve()
    if path == (base / "pytest-current").resolve():
        raise ValueError(f"{root}: it is what pytest-current points at, the run in progress")
    if path.parent != base or not path.name.startswith("pytest-") or not path.name[7:].isdigit():
        raise ValueError(f"{root}: not a pytest-N folder of {base}")
    live = [pid for pid, _, argv in find_under([path]) if any(os.path.basename(a) in PYTEST_NAMES for a in argv)]
    if live:
        raise ValueError(f"{root}: a live pytest process (pid {live[0]}) names it")
    return path


def is_orphan(ppid: int) -> bool:
    """Reparented to init: pid 1, or (WSL) the session's `/init` reaper that adopts a detached process.

    The `/init` test alone is loose (any process `/init` adopted passes); it is safe only because reap_stale matches
    the path first, so only a process that names a stale root can reach it."""
    if ppid == 1:
        return True
    try:
        argv = _read(f"/proc/{ppid}/cmdline").split(b"\0")
    except OSError:
        return False
    return argv[0] == b"/init"


def reap_stale(roots, require_orphan: bool = True, dry_run: bool = False, grace: float = GRACE_S):
    """Stop the processes (orphans by default, see is_orphan) whose argv names one of the roots. Returns (stopped, left_alone)."""
    mine, left = [], []
    for item in find_under(roots):
        (mine if not require_orphan or is_orphan(item[1]) else left).append(item)
    if not dry_run and mine:
        stop([p for p, _, _ in mine], grace)
    return mine, left


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--stale", nargs="+", required=True, metavar="DIR")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--base", help="the pytest base dir (default <tmp>/pytest-of-<user>)")
    args = parser.parse_args(argv)
    try:
        roots = [check_stale_root(r, Path(args.base) if args.base else None) for r in args.stale]
    except ValueError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    stopped, left = reap_stale(roots, True, args.dry_run)
    for pid, ppid, a in stopped:
        print(f"{'would stop' if args.dry_run else 'stopped'} {pid} (ppid {ppid}): {' '.join(a)[:200]}")
    for pid, ppid, a in left:
        print(f"left alone {pid} (ppid {ppid}, live parent): {' '.join(a)[:200]}")
    print(f"{len(stopped)} {'matched' if args.dry_run else 'stopped'}, {len(left)} left alone")
    return 0


if __name__ == "__main__":
    sys.exit(main())
