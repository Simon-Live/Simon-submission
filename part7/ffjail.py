"""Read-only root for one sandboxed media call (docs/specs/ffsafe.md AC-F8; go-live-readiness.md "Sandbox", HARDENING 3.5).

Run by `ffsafe.wrap` as `unshare -rnm -- python3 -I ffjail.py [--mask P | --keep P]... <writable dir>... -- <argv>`:
inside the new user and mount namespace it hides every `--mask` path (an empty read-only tmpfs over a folder, `/dev/null`
over a file: the secrets folder, the keys, the BYOK credentials, the identity store; review R2), binds each writable
directory onto itself, remounts every other mount read-only, checks that `/` is now read-only and every mask reads empty
(exit 125 when not, so nothing runs with a writable root or a readable secret) and then execs `argv`. A mask that holds a
path the call needs (a `--keep` path, a writable directory, the working directory) is not hidden whole: each of its
entries is, but the ones on the way to that path (the prod state dir lives inside the secrets folder). Imports nothing
from `part7`: `-I` keeps the working directory and `PYTHONPATH` off the module path.
"""

from __future__ import annotations

import ctypes
import os
import re
import sys

MS_RDONLY = 0x1
MS_NOSUID = 0x2
MS_NODEV = 0x4
MS_NOEXEC = 0x8
MS_REMOUNT = 0x20
MS_NOATIME = 0x400
MS_NODIRATIME = 0x800
MS_BIND = 0x1000
MS_REC = 0x4000
# Flags a remount inside a user namespace must keep as they are; statvfs `f_flag` uses the same bits for these.
LOCKED = MS_NOSUID | MS_NODEV | MS_NOEXEC | MS_NOATIME | MS_NODIRATIME
_OCTAL = re.compile(r"\\([0-7]{3})")  # mountinfo writes a space as \040
REFUSED = 125  # the jail could not be made: the media call does not run


def _libc() -> ctypes.CDLL:
    return ctypes.CDLL(None, use_errno=True)


def _mount(libc: ctypes.CDLL, source: str, target: str, flags: int) -> bool:
    return libc.mount(source.encode(), target.encode(), None, flags, None) == 0


def mount_points() -> list[str]:
    """Every mount point of this mount namespace, from /proc/self/mountinfo (octal escapes decoded)."""
    out = []
    with open("/proc/self/mountinfo", encoding="utf-8") as info:
        for row in info:
            fields = row.split(" ")
            if len(fields) > 4:
                out.append(_OCTAL.sub(lambda m: chr(int(m.group(1), 8)), fields[4]))
    return out


def _inside(path: str, folder: str) -> bool:
    return path == folder or path.startswith(folder.rstrip("/") + "/")


def _hide(libc: ctypes.CDLL, target: str) -> bool:
    """An empty read-only tmpfs over the folder `target`, or `/dev/null` bound over the file `target`."""
    if os.path.isdir(target):
        return libc.mount(b"tmpfs", target.encode(), b"tmpfs", MS_RDONLY | MS_NOSUID | MS_NODEV | MS_NOEXEC,
                          b"size=4k,mode=0500") == 0
    return _mount(libc, "/dev/null", target, MS_BIND)


def mask_targets(masks: list[str], keep: list[str]) -> list[str]:
    """The paths to hide: each mask, or, when it holds a kept path, each of its entries but the ones that lead to one."""
    kept = [os.path.realpath(k) for k in keep]
    out: list[str] = []
    todo = [os.path.realpath(m) for m in masks if os.path.lexists(m)]
    while todo:
        path = todo.pop()
        inner = [k for k in kept if _inside(k, path)]
        if not inner:
            out.append(path)
        elif path not in inner and os.path.isdir(path):
            try:
                todo += [os.path.join(path, name) for name in sorted(os.listdir(path))]
            except OSError:
                out.append(path)  # cannot be looked into: hidden whole (the call then fails, it never reads a secret)
    return sorted(set(p for p in out if not os.path.islink(p)))


def _reads_empty(path: str) -> bool:
    try:
        if os.path.isdir(path):
            return os.listdir(path) == []
        with open(path, "rb") as handle:
            return handle.read(1) == b""
    except OSError:
        return True  # nothing can be read from it either


def _flags_of(path: str) -> int:
    """The per-mount flags a remount must repeat (statvfs `f_flag` bits match the MS_ bits for these)."""
    try:
        return os.statvfs(path).f_flag & LOCKED
    except OSError:
        return 0


def jail(writable: list[str], masks: list[str] | None = None, keep: list[str] | None = None) -> bool:
    """Hide the masks, bind each writable directory onto itself, then remount every other mount read-only; True when `/`
    is read-only and every mask reads empty."""
    libc = _libc()
    hidden = mask_targets(masks or [], [*(keep or []), *writable, os.getcwd()])
    for target in hidden:
        if not _hide(libc, target):
            return False  # a secret that cannot be hidden: nothing runs
    kept = []
    for path in writable:
        if os.path.isdir(path) and _mount(libc, path, path, MS_BIND | MS_REC):
            kept.append(os.path.realpath(path))
    for point in mount_points():
        if os.path.realpath(point) in kept:
            continue
        _mount(libc, "none", point, MS_REMOUNT | MS_BIND | MS_RDONLY | _flags_of(point))  # a mount that refuses stays as it is
    return bool(os.statvfs("/").f_flag & MS_RDONLY) and all(_reads_empty(t) for t in hidden)


def _options(head: list[str]) -> tuple[list[str], list[str], list[str]] | None:
    """`(masks, keep, writable)` from the words before `--`; None when a `--mask` or `--keep` has no path."""
    masks: list[str] = []
    keep: list[str] = []
    writable: list[str] = []
    i = 0
    while i < len(head):
        if head[i] in ("--mask", "--keep"):
            if i + 1 >= len(head):
                return None
            (masks if head[i] == "--mask" else keep).append(head[i + 1])
            i += 2
            continue
        writable.append(head[i])
        i += 1
    return masks, keep, writable


def main(argv: list[str]) -> int:
    if "--" not in argv:
        print("ffjail: usage: ffjail.py [--mask P | --keep P]... <writable dir>... -- <argv>", file=sys.stderr)
        return 2
    cut = argv.index("--")
    parsed, command = _options(argv[:cut]), argv[cut + 1:]
    if not command or parsed is None:
        print("ffjail: no command" if parsed is not None else "ffjail: --mask and --keep need a path", file=sys.stderr)
        return 2
    masks, keep, writable = parsed
    if not jail(writable, masks, keep):
        print("ffjail: the root could not be made read-only or a secret could not be hidden", file=sys.stderr)
        return REFUSED
    os.execvp(command[0], command)
    return REFUSED  # not reached: execvp replaces this process or raises


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
