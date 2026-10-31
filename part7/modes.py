"""Practice modes (practice-and-modes.md): dance, rehab, fitness.

A mode is chosen by the visitor and kept on the job record. Part 7 uses it for coaching and practice only.
Part 5 scores with its own rules; `--profile <mode>` is passed only when Part 5's analyse help offers it.
"""

from __future__ import annotations

from typing import Any

MODES = ("dance", "rehab", "fitness")
MSG_MODE = "Pick dance, rehab or fitness as the mode."
NOTE_NO_PROFILE = "Part 5 has no scoring profile; mode changes coaching and practice only"


class ModeError(ValueError):
    """The mode is not acceptable; the message is plain words for the person."""


def parse(value: Any) -> str | None:
    """None when absent, the mode when valid, else `ModeError`."""
    if value is None:
        return None
    if not isinstance(value, str) or value not in MODES:
        raise ModeError(MSG_MODE)
    return value
