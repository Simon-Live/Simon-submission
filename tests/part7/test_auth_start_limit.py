"""The per-client sign-in start limit is higher only with the staging test mailbox (no real mail leaves)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from part7 import auth


def _state(monkeypatch: pytest.MonkeyPatch, tmp_path, transport: str) -> auth.AuthState:
    monkeypatch.setattr(auth.mail.Mailer, "__init__", lambda self, state, *a, **k: setattr(self, "transport", transport))
    monkeypatch.setattr(auth.mail, "file_refused_on_staging", lambda *a, **k: False)
    return auth.AuthState(SimpleNamespace(state=tmp_path))


def _allowed(limit: auth.Limiter) -> int:
    return sum(limit.hit("203.0.113.9") for _ in range(100))


def test_the_outbox_allows_more_starts_per_client(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    assert _allowed(_state(monkeypatch, tmp_path, "outbox").start_limit) == auth.START_PER_IP_OUTBOX[0]


@pytest.mark.parametrize("transport", ["smtp", "api", "file", "off"])
def test_real_mail_keeps_the_strict_limit(monkeypatch: pytest.MonkeyPatch, tmp_path, transport: str) -> None:
    assert _allowed(_state(monkeypatch, tmp_path, transport).start_limit) == auth.START_PER_IP[0]  # negative
