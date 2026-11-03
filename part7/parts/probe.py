"""Ask a pinned part's `--help` whether it offers a flag (cached per clone and pin sha), so argv follows the pin."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Callable

from part7 import modules, runner

_CACHE: dict[tuple[str, str | None, tuple[str, ...], str], bool] = {}
HELP_TIMEOUT_S = 90.0


def help_text(part: int | str, argv: list[str], clone: Path, lock: modules.Modules | None = None) -> str:
    """Return the `--help` output of the command `argv` run in `clone` (empty when it fails)."""
    step = runner.run(part, [*argv, "--help"], cwd=clone, timeout_s=HELP_TIMEOUT_S, lock=lock)
    return step["stdout"] if step["exit"] == 0 else ""


def mentions(text: str, flag: str) -> bool:
    """True when `flag` appears in `text` as a whole option: `--live` does not match `--live-x` or `--no-live`."""
    return re.search(r"(?<![\w-])" + re.escape(flag) + r"(?![\w-])", text) is not None


def has_flag(
    part: int | str, argv: list[str], clone: Path, flag: str, lock: modules.Modules | None = None
) -> bool:
    """True when `<argv> --help` lists `flag`; the answer is cached for the clone, its HEAD sha and the command.

    The sha is read fresh each call, so a pin bump (a new commit checked out in the clone) asks `--help` again
    without a restart."""
    key = (str(clone), modules.head_sha(clone), tuple(argv), flag)
    if key not in _CACHE:
        _CACHE[key] = mentions(help_text(part, argv, clone, lock), flag)
    return _CACHE[key]


def cached(clone: Path, name: str, compute: Callable[[], bool]) -> bool:
    """A yes/no answer about the clone at its current HEAD sha, computed once per sha and kept until `clear_cache`."""
    key = (str(clone), modules.head_sha(clone), (name,), "")
    if key not in _CACHE:
        _CACHE[key] = bool(compute())
    return _CACHE[key]


def clear_cache() -> None:
    _CACHE.clear()
