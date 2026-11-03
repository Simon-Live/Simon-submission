"""The session cookie is read even when a gateway leaves a stray separator (staging sign-in, 2026-11-01)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from part7.auth import COOKIE, sid_from


def _h(cookie: str | None) -> SimpleNamespace:
    return SimpleNamespace(headers={} if cookie is None else {"Cookie": cookie})


@pytest.mark.parametrize("raw", [f"{COOKIE}=abc", f"; {COOKIE}=abc", f"a=1; {COOKIE}=abc;", f" ;; {COOKIE}=abc ; b=2"])
def test_the_session_id_survives_stray_separators(raw: str) -> None:
    assert sid_from(_h(raw)) == "abc"


@pytest.mark.parametrize("raw", [None, "", "a=1", f"{COOKIE}=", f"x{COOKIE}=abc", f"{COOKIE}x=abc"])
def test_no_session_id_without_the_exact_cookie(raw: str | None) -> None:
    assert sid_from(_h(raw)) is None  # negative: a lookalike name or an empty value is not a session
