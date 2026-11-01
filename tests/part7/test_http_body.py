"""TICKET-194: an oversized body up to DRAIN_MAX is read before the refusal, so the client gets the answer."""
from __future__ import annotations

import io
from types import SimpleNamespace

from part7.http_body import DRAIN_MAX, drain_before_refusal


def _handler(body: bytes) -> SimpleNamespace:
    return SimpleNamespace(rfile=io.BytesIO(body), close_connection=False)


def test_a_small_oversized_body_is_read_and_the_connection_kept() -> None:
    h = _handler(b"x" * 9000 + b"NEXT")
    drain_before_refusal(h, 9000)
    assert h.close_connection is False
    assert h.rfile.read() == b"NEXT"  # the next request on the connection starts clean


def test_a_body_over_the_drain_limit_closes_the_connection_unread() -> None:
    h = _handler(b"x" * 10)
    drain_before_refusal(h, DRAIN_MAX + 1)
    assert h.close_connection is True
    assert h.rfile.read() == b"x" * 10  # nothing was read


def test_a_short_body_or_a_bad_length_closes_the_connection() -> None:
    short = _handler(b"x" * 5)
    drain_before_refusal(short, 100)  # the client sent less than it announced
    assert short.close_connection is True
    bad = _handler(b"")
    drain_before_refusal(bad, -1)
    assert bad.close_connection is True


def test_the_refusal_arrives_on_a_real_server_every_time(api) -> None:
    """The release 18 run saw ConnectionResetError here; the 413 must arrive on every try."""
    import json

    big = json.dumps({"entry_id": "lateral-raise", "title": "x" * 9000}).encode()
    for _ in range(40):
        assert api.request("POST", "api/challenges", big, {"Content-Type": "application/json"})[0] == 413
