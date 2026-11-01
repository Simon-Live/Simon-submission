"""Practice modes (practice-and-modes.md): dance, rehab, fitness.

A mode is chosen by the visitor and kept on the job record. It sets coaching and practice, and (ADR-0008)
how a take is scored: Part 5's `--profile <mode>` when its analyse help offers it, else the plain CLI. Fitness is Part 5's standard rules.
"""

from __future__ import annotations

from typing import Any

MODES = ("dance", "rehab", "fitness")
MSG_MODE = "Pick dance, rehab or fitness as the mode."


class ModeError(ValueError):
    """The mode is not acceptable; the message is plain words for the person."""


def parse(value: Any) -> str | None:
    """None when absent, the mode when valid, else `ModeError`."""
    if value is None:
        return None
    if not isinstance(value, str) or value not in MODES:
        raise ModeError(MSG_MODE)
    return value
