"""Turning away an oversized request body without resetting the connection (TICKET-194).

A handler that answers 413 and closes without reading the body leaves unread bytes in the socket; the kernel then
sends a reset, and the client sees "connection reset" instead of the 413 (seen in the release 18 suite run). A body
up to `DRAIN_MAX` bytes is read and dropped first, so the answer arrives; a larger one is not worth reading and the
connection still closes.
"""
from __future__ import annotations

from typing import Any

DRAIN_MAX = 64 * 1024  # bytes read and dropped before a 413; larger bodies close the connection unread
_CHUNK = 16 * 1024


def drain_before_refusal(h: Any, length: int, limit: int = DRAIN_MAX) -> None:
    """Read and drop `length` body bytes when that is within `limit`; otherwise mark the connection to close."""
    if 0 < length <= limit:
        left = length
        while left > 0:
            got = h.rfile.read(min(_CHUNK, left))
            if not got:
                break
            left -= len(got)
        if left == 0:
            return
    h.close_connection = True
