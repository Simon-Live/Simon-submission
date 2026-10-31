"""Ask a pinned part's `--help` whether it offers a flag (cached per clone), so argv follows the pin."""

from __future__ import annotations

from pathlib import Path

from part7 import modules, runner

_CACHE: dict[tuple[str, tuple[str, ...], str], bool] = {}
HELP_TIMEOUT_S = 90.0


def help_text(part: int | str, argv: list[str], clone: Path, lock: modules.Modules | None = None) -> str:
    """Return the `--help` output of the command `argv` run in `clone` (empty when it fails)."""
    step = runner.run(part, [*argv, "--help"], cwd=clone, timeout_s=HELP_TIMEOUT_S, lock=lock)
    return step["stdout"] if step["exit"] == 0 else ""


def has_flag(
    part: int | str, argv: list[str], clone: Path, flag: str, lock: modules.Modules | None = None
) -> bool:
    """True when `<argv> --help` lists `flag`; the answer is cached for the clone and command."""
    key = (str(clone), tuple(argv), flag)
    if key not in _CACHE:
        _CACHE[key] = flag in help_text(part, argv, clone, lock)
    return _CACHE[key]


def clear_cache() -> None:
    _CACHE.clear()
