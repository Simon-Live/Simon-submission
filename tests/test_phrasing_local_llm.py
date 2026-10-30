"""The local-llm backend: Ollama on 127.0.0.1, falling back to template when it is absent (ASM-007)."""
import pytest

from part5 import phrasing
from part5.phrasing import local_llm
from part5.phrasing.local_llm import HttpResult
from test_phrasing import FAULTS, FOOT, KNEE, clean_env, no_network  # noqa: F401
from test_phrasing_muse_spark import Client, reply

GOOD = ["left foot sticking out too far", "right knee not bent enough", "leaning forward more than the example"]


@pytest.fixture
def ollama(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/ollama" if name == "ollama" else None)
    monkeypatch.setenv("PART5_OLLAMA_MODEL", "tiny-coach")


def test_no_ollama_binary_falls_back_to_template_with_a_reason(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.setenv("PART5_OLLAMA_MODEL", "tiny-coach")
    client = Client()
    lines, record = phrasing.phrase(FAULTS, "local-llm", client=client)
    assert lines == [f["text"] for f in FAULTS] and client.requests == []
    assert record["requested"] == "local-llm" and record["backend"] == "template"
    assert record["fallback_reason"] == "ollama not found" and record["model"] is None
    assert record["faults"] == [{"backend": "template", "model": None, "fallback_reason": "ollama not found"}] * 3


def test_this_host_has_no_ollama_so_the_real_lookup_falls_back_too():
    # ASM-007: on a host without Ollama no patching is needed; with it, the model variable still gates.
    lines, record = phrasing.phrase(FAULTS, "local-llm")
    assert lines == [f["text"] for f in FAULTS] and record["backend"] == "template"


def test_a_binary_without_a_model_falls_back(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/ollama")
    _, record = phrasing.phrase(FAULTS, "local-llm", client=Client())
    assert record["backend"] == "template" and "PART5_OLLAMA_MODEL" in record["fallback_reason"]


def test_a_blank_model_name_counts_as_none(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/ollama")
    monkeypatch.setenv("PART5_OLLAMA_MODEL", "   ")
    assert local_llm.unavailable() is not None and local_llm.model() is None


def test_with_ollama_and_a_model_each_fault_is_phrased(ollama):
    client = Client(*(reply(line) for line in GOOD))
    lines, record = phrasing.phrase(FAULTS, "local-llm", client=client)
    assert lines == GOOD
    assert record["backend"] == "local-llm" and record["model"] == "tiny-coach"
    assert record["fallback_reason"] is None
    request = client.requests[0]
    assert request["url"] == "http://127.0.0.1:11434/v1/chat/completions"
    assert request["body"]["model"] == "tiny-coach" and request["timeout_s"] == 10
    assert "Authorization" not in request["headers"]


def test_the_local_request_carries_only_the_measured_record(ollama):
    import json
    client = Client(reply(GOOD[0]))
    phrasing.phrase([FOOT], "local-llm", client=client)
    user = client.requests[0]["body"]["messages"][1]["content"]
    assert set(json.loads(user)) == {"measure", "joint", "side", "direction", "magnitude_deg",
                                     "threshold_deg", "frames"}


@pytest.mark.parametrize("bad,reason", [
    (TimeoutError(), "local-llm: timeout after 10 s"),
    (ConnectionRefusedError(), "local-llm: request failed (ConnectionRefusedError)"),
    (reply(""), "local-llm: empty content"),
    (HttpResult(404, {"error": "model not found"}), "local-llm: HTTP 404"),
    (reply("left knee not bent enough"), "local-llm: wrong side"),
])
def test_one_failing_fault_alone_falls_back(ollama, bad, reason):
    lines, record = phrasing.phrase(FAULTS, "local-llm", client=Client(reply(GOOD[0]), bad, reply(GOOD[2])))
    assert lines == [GOOD[0], KNEE["text"], GOOD[2]]
    assert record["faults"][1] == {"backend": "template", "model": None, "fallback_reason": reason}
    assert record["backend"] == "local-llm"


def test_local_calls_write_no_usage_ledger(ollama, tmp_path):
    phrasing.phrase([FOOT], "local-llm", client=Client(reply(GOOD[0])))
    assert not (tmp_path / "usage.jsonl").exists()
