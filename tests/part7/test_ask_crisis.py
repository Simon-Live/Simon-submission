"""Reels 3.10: "Ask my history" and "Ask this take" answer a self-harm or suicide message with a fixed crisis text and
never call a model (part7/history_ask_guard.py `crisis`, `crisis_reply`; docs/specs/history-ask.md, take-ask.md)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from history_support import USER, World, world  # noqa: F401
from part7 import history_api, history_ask, history_ask_guard, history_store, take_ask
from support import Api
from test_take_ask import FakePart5, _post, asked  # noqa: F401

CRISIS = ["I want to kill myself", "thinking about SUICIDE", "i keep self-harming", "self harm", "I want to end my life",
          "is it worth it, I want to die", "I took an overdose", "better off dead", "cut myself again", "how to  kill   myself"]
NOT_CRISIS = ["why does my squat score die off at the end?", "my left knee caves in", "which take was my best?",
              "I hurt my knee last week", "kill the lag at 2 s", "ending position looks off", "", None, 7]


@pytest.mark.parametrize("text", CRISIS)
def test_a_self_harm_or_suicide_message_is_a_crisis(text: str) -> None:
    assert history_ask_guard.crisis(text)


@pytest.mark.parametrize("text", NOT_CRISIS)
def test_ordinary_questions_are_not(text: Any) -> None:  # negative: the movement questions still reach the guard
    assert not history_ask_guard.crisis(text)


def test_the_crisis_text_is_fixed_names_the_help_lines_and_follows_the_writer_rules() -> None:
    reply = history_ask_guard.crisis_reply(claims=[])
    assert reply["status"] == "crisis" and reply["text"] is None and reply["usage"] is None and reply["claims"] == []
    assert reply["message"] == history_ask_guard.CRISIS_TEXT
    for line in ("call or text 988", "Samaritans on 116 123", "Lifeline on 13 11 14", "findahelpline.com", "emergency number"):
        assert line in reply["message"]
    assert "[" not in reply["message"]
    assert not any(ch in reply["message"] for ch in ("—", "–")) and " - " not in reply["message"]


def _never(*_a: Any, **_k: Any) -> Any:
    raise AssertionError("a model was called for a crisis message")


def test_ask_my_history_answers_a_crisis_without_a_model_or_the_opt_in(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(history_api, "ask", _never)
    monkeypatch.setattr(history_store, "retention_opt_in", lambda *_a: False)  # before the 409 a signed-out history gets
    out = history_ask.run_question(tmp_path, "u1", "I want to kill myself", lambda e: e, lambda e, j: None)
    assert out["status"] == "crisis" and out["message"] == history_ask_guard.CRISIS_TEXT and out["claims"] == []
    assert history_ask.asked_today(tmp_path, "u1") == 0


def test_ask_this_take_answers_a_crisis_before_any_other_check(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(take_ask, "ASK", _never)
    out = take_ask.run_question(tmp_path, "u1", "abc123def456", None, "thinking about suicide")  # even with no take found
    assert out["status"] == "crisis" and out["message"] == history_ask_guard.CRISIS_TEXT and out["actions"] == []
    assert take_ask.asked_today(tmp_path, "u1") == 0


def test_the_take_route_returns_the_crisis_text_and_part5_is_never_called(asked: tuple[Api, FakePart5]) -> None:
    api, fake = asked
    status, doc = _post(api, {"question": "I want to end my life"})
    assert status == 200 and doc["status"] == "crisis" and doc["message"] == history_ask_guard.CRISIS_TEXT
    assert fake.calls == [] and doc["text"] is None
    status, doc = _post(api, {"question": "when does my trunk lean show up?"})  # negative: an ordinary question still asks
    assert status == 200 and doc["status"] == "ok" and len(fake.calls) == 1
