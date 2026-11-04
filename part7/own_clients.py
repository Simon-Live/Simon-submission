"""The own-route Modal clients this server started, and stopping them (docs/specs/byok-prod.md BYOK-M6; prod verify
nofallback D4).

A take on a user's own Modal account runs `deploy/serverless/p2_client.py --own` in its own session (runner.run), so
neither the drain nor the end of the server's process group reaches it, and it holds the owner's decrypted token in
its environment while it polls for up to 1900 s. Three things stop it:

- The launcher registers itself: `<state>/own-clients/<pid>.json` holds `{pid, parent, owner, start}` (the server
  that started it, the owner's user id and the kernel start time of the process, never a value of the token) and
  goes when it ends. The server writes the same file first (`register`), under the owner's credentials lock, the
  moment the process starts (go-live BYOK N1).
- `stop_owner` (the owner's Remove and account deletion, `modal_creds.remove`) and `stop_all` end the process group
  of each registered launcher: SIGTERM, then SIGKILL after `GRACE_S`. `stop_all` runs at the end of the server for
  the launchers it started (an atexit hook, after the drain; a new build serving beside it keeps its own), and from
  a full `prod/down.sh` for all of them (`python3 -m part7.own_clients stop --state <state>`). A file whose pid now names another
  process (other start time, other command line) is dropped, never signalled.
- The launcher also ends itself when its parent, the server, is gone (p2_client.py `watch_parent`).

`job(state, owner)` marks the Part 2 calls of one job; `launcher_args()` is what `byok_route.command` adds to the
launcher argv for them. Standard library only: down.sh runs this module without the app.
"""

from __future__ import annotations

import argparse
import atexit
import contextlib
import contextvars
import json
import os
from pathlib import Path
import re
import signal
import sys
import threading
import time
from typing import Iterator

DIR = "own-clients"
GRACE_S = 5.0
LAUNCHER = "p2_client.py"
_USER_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_JOB: contextvars.ContextVar[tuple[str, str] | None] = contextvars.ContextVar("own_client_job", default=None)
_HOOKED: set[str] = set()
_HOOK_LOCK = threading.Lock()


def registry(state: Path | str) -> Path:
    return Path(state) / DIR


def start_time(pid: int) -> str | None:
    """The kernel start time of `pid` (field 22 of /proc/<pid>/stat), or None when there is no such process."""
    try:
        raw = Path(f"/proc/{pid}/stat").read_text(encoding="ascii", errors="replace")
    except OSError:
        return None
    fields = raw[raw.rfind(")") + 2:].split()
    return fields[19] if len(fields) > 19 else None


@contextlib.contextmanager
def job(state: Path | str | None, owner: str | None) -> Iterator[None]:
    """Within the block, own-route launchers of this thread register under `state` for `owner`."""
    if state is None or not owner or not _USER_RE.match(owner):
        yield
        return
    _hook(state)
    token = _JOB.set((str(registry(state)), owner))
    try:
        yield
    finally:
        _JOB.reset(token)


def launcher_args() -> list[str]:
    """`--registry <dir> --owner <user id>` for the launcher of the current job, or nothing outside `job`."""
    found = _JOB.get()
    return ["--registry", found[0], "--owner", found[1]] if found else []


def register(state: Path | str, owner: str, pid: int) -> Path | None:
    """The server's own registration of a launcher it just started (`modal_creds.launch_gate`, go-live BYOK N1): the
    launcher's file (`<pid>.json`, same fields) written before the owner's lock is let go, so a Remove that comes next
    finds the process even before the launcher registered itself. None when `owner` could not be a file name."""
    if not _USER_RE.match(owner or ""):
        return None
    folder = registry(state)
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    path, tmp = folder / f"{pid}.json", folder / f".{pid}.server.tmp"
    tmp.write_text(json.dumps({"pid": pid, "parent": os.getpid(), "owner": owner, "start": start_time(pid)}),
                   encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    return path


def _hook(state: Path | str) -> None:
    """Stop every launcher of `state` when this server process ends (after the drain, or on any normal exit)."""
    key = str(Path(state).resolve())
    with _HOOK_LOCK:
        if key not in _HOOKED:
            _HOOKED.add(key)
            atexit.register(stop_all, key, parent=os.getpid())


def _entries(state: Path | str) -> list[tuple[Path, dict]]:
    out = []
    folder = registry(state)
    if not folder.is_dir():
        return out
    for path in sorted(folder.glob("*.json")):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            doc = None
        if isinstance(doc, dict) and isinstance(doc.get("pid"), int) and doc["pid"] > 1:
            out.append((path, doc))
        else:
            path.unlink(missing_ok=True)
    return out


def _is_launcher(doc: dict) -> bool:
    """The pid still names the launcher that wrote the file: same start time, and its argv runs p2_client.py --own."""
    pid = doc["pid"]
    if start_time(pid) != doc.get("start"):
        return False
    try:
        argv = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
    except OSError:
        return False
    return any(a.endswith(LAUNCHER.encode()) for a in argv) and b"--own" in argv


def _signal_group(pid: int, sig: int) -> None:
    """runner.run starts the launcher in its own session, so its group is its pid and holds the Modal client. A
    launcher in any other group (never this process's own) gets the signal alone."""
    with contextlib.suppress(OSError):
        if os.getpgid(pid) == pid and pid != os.getpgid(0):
            os.killpg(pid, sig)
        else:
            os.kill(pid, sig)


def _stop(found: list[tuple[Path, dict]], grace_s: float) -> int:
    live = []
    for path, doc in found:
        if _is_launcher(doc):
            _signal_group(doc["pid"], signal.SIGTERM)
            live.append((path, doc))
        else:
            path.unlink(missing_ok=True)
    deadline = time.monotonic() + grace_s
    while live and time.monotonic() < deadline and any(_is_launcher(d) for _, d in live):
        time.sleep(0.1)
    for path, doc in live:
        if _is_launcher(doc):
            _signal_group(doc["pid"], signal.SIGKILL)
        path.unlink(missing_ok=True)
    return len(live)


def stop_owner(state: Path | str, owner: str, grace_s: float = GRACE_S) -> int:
    """End every registered launcher of `owner` (their token was removed); how many were running."""
    return _stop([(p, d) for p, d in _entries(state) if d.get("owner") == owner], grace_s)


def stop_all(state: Path | str, grace_s: float = GRACE_S, parent: int | None = None) -> int:
    """End every registered launcher of `state` (only those `parent` started, when given); how many were running."""
    return _stop([(p, d) for p, d in _entries(state) if parent is None or d.get("parent") == parent], grace_s)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="stop the own-route Modal clients of a Simon state dir")
    ap.add_argument("command", choices=["stop"])
    ap.add_argument("--state", required=True)
    args = ap.parse_args(argv)
    count = stop_all(args.state)
    print(f"own-route Modal clients stopped: {count}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
