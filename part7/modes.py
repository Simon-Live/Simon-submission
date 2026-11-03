"""Practice modes (practice-and-modes.md): dance, rehab, fitness.

A mode is chosen by the visitor and kept on the job record. It sets coaching and practice, and (ADR-0008)
how a take is scored: Part 5's `--profile <mode>` when its analyse help offers it, else the plain CLI. Fitness is Part 5's standard rules.
"""

from __future__ import annotations

import logging
from typing import Any

from part7 import applog

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


# TICKET-311: the entry decides. Rehab is a tag (labels.py), dance and exercise are Part 6 categories.
REHAB_TAG = "rehab"
CATEGORY_MODE = {"dance": "dance", "exercise": "fitness"}


def of_entry(manifest: dict[str, Any] | None, tags: list[str] | None) -> str | None:
    """The mode an entry's own kind names: rehab for the `rehab` tag, else its category's mode, else None."""
    if REHAB_TAG in (tags or []):
        return "rehab"
    category = (manifest or {}).get("category")
    return CATEGORY_MODE.get(category) if isinstance(category, str) else None


def decide(posted: str | None, entry_mode: str | None, entry_id: str = "") -> str | None:
    """The mode a take is scored with: the entry's when it has one and a mode was posted, else the posted one.

    No posted mode stays None (an API call or the submission profile without modes: Part 5's standard rules).
    A posted mode that differs from the entry's is logged, then replaced.
    """
    if posted is None or entry_mode is None or posted == entry_mode:
        return posted
    applog.log(f"mode {posted} posted for entry {entry_id}, whose kind is {entry_mode}: scored as {entry_mode}",
               level=logging.WARNING)
    return entry_mode
