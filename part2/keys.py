"""Operator key files: a presence check that never reads the value, and the single read path.

Spec: docs/specs/tracker-registry.md (Keys). ADR-0003.

Key directory: PART2_KEY_DIR, default ~/.config/firm/operator-keys/ (mode 700, each file 600). Each file is
named after its environment variable; only MODEL_API_KEY and HF_TOKEN are ever read. The environment variable
of the same name is the second channel; the file wins when both exist.

The value is never logged, returned in an error, stored on a module attribute or printed. `read` is called
only inside a tracker adapter, immediately before the call that needs it.
"""
import os
import stat
from pathlib import Path

KNOWN = ("MODEL_API_KEY", "HF_TOKEN")
DEFAULT_DIR = "~/.config/firm/operator-keys"
DIR_ENV = "PART2_KEY_DIR"


class KeyMissing(RuntimeError):
    """No usable key file and no environment variable. The message never holds a value."""


def key_dir() -> Path:
    return Path(os.environ.get(DIR_ENV) or DEFAULT_DIR).expanduser()


def _known(name: str) -> None:
    if name not in KNOWN:
        raise ValueError(f"keys: {name} is not a key Part 2 reads (known: {', '.join(KNOWN)})")


def file_status(name: str) -> tuple[bool, str]:
    """(usable, reason) for the key file alone. Uses stat only; never opens the file."""
    _known(name)
    d = key_dir()
    try:
        st = (d / name).stat()
        dst = d.stat()
    except FileNotFoundError:
        return False, f"{name} not found in {d}"
    except OSError:
        return False, f"{d} is not readable"
    if not stat.S_ISREG(st.st_mode):
        return False, f"{name} is not a regular file"
    if st.st_size == 0:
        return False, f"{name} is empty"
    if st.st_mode & 0o077:
        return False, f"{name} must be mode 600"
    if dst.st_mode & 0o077:
        return False, f"{d} must be mode 700"
    return True, "file"


def check(name: str) -> tuple[bool, str]:
    """(present, where or why not): "file", "env", or the plain reason the file is unusable."""
    ok, reason = file_status(name)
    if ok:
        return True, "file"
    if os.environ.get(name, "").strip():
        return True, "env"
    return False, reason


def present(name: str) -> bool:
    return check(name)[0]


def read(name: str) -> str:
    """The key value, stripped of surrounding whitespace. File first, then the environment variable."""
    ok, reason = file_status(name)
    if ok:
        try:
            value = (key_dir() / name).read_text().strip()
        except OSError:
            value, reason = "", f"{name} is not readable"
        if value:
            return value
        reason = reason if reason != "file" else f"{name} holds only whitespace"
    value = os.environ.get(name, "").strip()
    if value:
        return value
    raise KeyMissing(f"{name}: {reason}; the {name} variable is not set either")
