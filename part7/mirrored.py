"""Mirrored uploads (TICKET-310, recorder.md "Mirrored uploads"): the person's own word that a clip is mirrored.

A selfie video may be stored mirrored, depending on the phone's camera app. Part 7 never guesses: the upload trim
step has a checkbox, the request carries `mirrored: true`, the job record keeps it, and Part 3 flips left and right
(`p3_skeleton._mirror`). Anything other than the JSON `true` means not mirrored and adds nothing to the record.
"""

from __future__ import annotations

from typing import Any

FIELD = "mirrored"


def requested(doc: dict[str, Any]) -> bool:
    """True only for `"mirrored": true` in the request body."""
    return doc.get(FIELD) is True


def take(doc: dict[str, Any], record: dict[str, Any]) -> bool:
    """Whether the take is mirrored; marks the job record with `mirrored: true` when it is (nothing otherwise)."""
    if requested(doc):
        record[FIELD] = True
        return True
    return False


def of_record(record: dict[str, Any] | None) -> bool:
    """A queued job's choice, for a job rebuilt after a restart (resume.py)."""
    return bool(record) and record.get(FIELD) is True
