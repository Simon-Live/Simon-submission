"""`PART5_LOCAL_LLM_TIMEOUT_S` and `PART5_LOCAL_LLM_THINK` for a slow local model (Part 7 TICKET-147; master spec
"Coaching phrasing registry"). A fake Ollama answers on 127.0.0.1 (the conftest guard allows loopback only); the
`ollama` binary check is replaced, so the tests do not depend on Ollama being installed.
"""
import json
import logging
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from part5 import phrasing
from part5.phrasing import local_llm, muse_spark
from test_phrasing import KNEE, clean_env  # noqa: F401

LINE = "right knee not bent enough"


@pytest.fixture
def ollama(monkeypatch):
    """A fake Ollama chat completions server; `state["delay"]` slows each answer, `state["bodies"]` records them, and
    `state["answer"]`, when set, is the JSON body sent back."""
    state = {"delay": 0.0, "bodies": [], "answer": None}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            state["bodies"].append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            time.sleep(state["delay"])
            body = json.dumps(state["answer"] or {"choices": [{"message": {"role": "assistant", "content": LINE}}]}).encode()
            try:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass   # the client gave up (the timeout test)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setattr(local_llm, "URL", f"http://127.0.0.1:{server.server_address[1]}/v1/chat/completions")
    monkeypatch.setattr(local_llm.shutil, "which", lambda name: "/usr/bin/ollama")
    monkeypatch.setenv("PART5_OLLAMA_MODEL", "muse-glimmer:30b")
    monkeypatch.setenv("PART5_PHRASING_BUDGET_S", "300")
    yield state
    server.shutdown()
    server.server_close()


def phrase_one():
    lines, record = phrasing.phrase([KNEE], "local-llm")
    return lines[0], record["faults"][0]


# ---- PART5_LOCAL_LLM_TIMEOUT_S ---------------------------------------------------------------------------------
def test_unset_keeps_the_10_s_default_and_the_line_comes_back(ollama, monkeypatch):
    monkeypatch.delenv("PART5_LOCAL_LLM_TIMEOUT_S", raising=False)
    line, entry = phrase_one()
    assert line == LINE and entry["backend"] == "local-llm" and entry["model"] == "muse-glimmer:30b"
    assert local_llm.call_timeout(10) == 10


def test_a_short_timeout_falls_back_with_the_timeout_named(ollama, monkeypatch):
    ollama["delay"] = 1.0
    monkeypatch.setenv("PART5_LOCAL_LLM_TIMEOUT_S", "0.2")
    line, entry = phrase_one()
    assert line == KNEE["text"] and entry["fallback_reason"] == "local-llm: timeout after 0.2 s"


def test_a_longer_timeout_lets_a_slow_model_answer(ollama, monkeypatch):
    ollama["delay"] = 0.3
    monkeypatch.setenv("PART5_LOCAL_LLM_TIMEOUT_S", "30")
    line, entry = phrase_one()
    assert line == LINE and entry["fallback_reason"] is None


def test_the_timeout_counts_against_the_phrasing_budget(ollama, monkeypatch):
    """A call starts only while time spent plus the timeout fits in the budget: 60 s against the default 20 s."""
    monkeypatch.delenv("PART5_PHRASING_BUDGET_S")
    monkeypatch.setenv("PART5_LOCAL_LLM_TIMEOUT_S", "60")
    line, entry = phrase_one()
    assert entry["fallback_reason"] == phrasing.BUDGET_SPENT and ollama["bodies"] == []


@pytest.mark.parametrize("raw", ["abc", "0", "-5", "nan", "inf", "10s"])
def test_a_bad_value_keeps_the_default_and_logs_why(raw, monkeypatch, caplog):
    monkeypatch.setenv("PART5_LOCAL_LLM_TIMEOUT_S", raw)
    with caplog.at_level(logging.WARNING, logger="part5.phrasing.local_llm"):
        assert local_llm.call_timeout(10) == 10
    assert "PART5_LOCAL_LLM_TIMEOUT_S" in caplog.text and repr(raw) in caplog.text


def test_the_setting_never_touches_the_muse_spark_timeout(monkeypatch):
    monkeypatch.setenv("PART5_LOCAL_LLM_TIMEOUT_S", "120")
    _, record = phrasing.phrase([KNEE], "muse-spark")   # no key: falls back before any call
    assert record["faults"][0]["fallback_reason"] == "no key"


# ---- PART5_LOCAL_LLM_THINK ---------------------------------------------------------------------------------------
@pytest.mark.parametrize("raw,off", [(None, False), ("", False), ("1", False), ("true", False),
                                     ("0", True), ("false", True), (" FALSE ", True)])
def test_think_off_sends_reasoning_effort_none_and_think_false_and_anything_else_neither(ollama, monkeypatch, raw, off):
    """Ollama's /v1 endpoint ignores `think` and honours `reasoning_effort: "none"` (Part 7 TICKET-147, measured with
    muse-glimmer:30b), so off sends both; unset or true sends neither."""
    if raw is None:
        monkeypatch.delenv("PART5_LOCAL_LLM_THINK", raising=False)
    else:
        monkeypatch.setenv("PART5_LOCAL_LLM_THINK", raw)
    line, _ = phrase_one()
    body = ollama["bodies"][0]
    assert line == LINE and body["temperature"] == 0
    if off:
        assert body["reasoning_effort"] == "none" and body["think"] is False
    else:
        assert "reasoning_effort" not in body and "think" not in body


# ---- PART5_LOCAL_LLM_MAX_TOKENS and the cut-off reason ----------------------------------------------------------
def test_the_default_allowance_is_2048_like_muse_spark(ollama, monkeypatch):
    monkeypatch.delenv("PART5_LOCAL_LLM_MAX_TOKENS", raising=False)
    phrase_one()
    assert ollama["bodies"][0]["max_tokens"] == 2048 == local_llm.MAX_TOKENS == muse_spark.MAX_TOKENS


def test_a_positive_integer_overrides_the_allowance(ollama, monkeypatch):
    monkeypatch.setenv("PART5_LOCAL_LLM_MAX_TOKENS", " 1024 ")
    phrase_one()
    assert ollama["bodies"][0]["max_tokens"] == 1024


@pytest.mark.parametrize("raw", ["abc", "0", "-3", "1.5", "2e3"])
def test_a_bad_allowance_keeps_2048_and_logs_why(raw, monkeypatch, caplog):
    monkeypatch.setenv("PART5_LOCAL_LLM_MAX_TOKENS", raw)
    with caplog.at_level(logging.WARNING, logger="part5.phrasing.local_llm"):
        assert local_llm.max_tokens() == 2048
    assert "PART5_LOCAL_LLM_MAX_TOKENS" in caplog.text and repr(raw) in caplog.text


def test_an_answer_cut_off_at_the_allowance_says_so(ollama):
    """The body Ollama sent for muse-glimmer:30b at 256 tokens (Part 7 demos/rubric/147/replay_request.json)."""
    ollama["answer"] = {"choices": [{"finish_reason": "length", "message": {"role": "assistant", "content": ""}}]}
    line, entry = phrase_one()
    assert line == KNEE["text"] and entry["fallback_reason"] == "local-llm: cut off at max_tokens"


def test_empty_content_that_was_not_cut_off_keeps_its_reason(ollama):
    ollama["answer"] = {"choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": ""}}]}
    assert phrase_one()[1]["fallback_reason"] == "local-llm: empty content"
