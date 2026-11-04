"""No core dump and no same-user ptrace for the app process (docs/specs/go-live-readiness.md "No dump"; BYOK audit R1).

`forbid()` calls `prctl(PR_SET_DUMPABLE, 0)`: the kernel writes no core file of this process and refuses a ptrace or a
`/proc/<pid>/mem` read by another process of the same user, so a decrypted Modal token in memory stays in it. Children
start dumpable again after `execve` unless they call it too (`deploy/serverless/p2_client.py` `no_dump` does).
"""

from __future__ import annotations

import ctypes

PR_SET_DUMPABLE = 4
PR_GET_DUMPABLE = 3


def _prctl(option: int, value: int = 0) -> int:
    return ctypes.CDLL(None, use_errno=True).prctl(option, value, 0, 0, 0)


def forbid() -> bool:
    """Make this process not dumpable; True when the kernel took it (False off Linux)."""
    try:
        return _prctl(PR_SET_DUMPABLE, 0) == 0
    except (OSError, AttributeError):
        return False


def dumpable() -> bool | None:
    """The process's dumpable flag, or None when it cannot be read."""
    try:
        return _prctl(PR_GET_DUMPABLE) != 0
    except (OSError, AttributeError):
        return None
