"""TICKET-102 (docs/specs/second-opinion.md AC-SO-06): a per-take second opinion that used the whole output allowance and
left a half-written JSON says `answer cut off at the output limit`, not `unreadable answer`; the allowance is 8000 as the
history opinion's is, and the estimate and the cap check follow the request's own allowance. No retry.

The live case was job 23d13c0b27e7 (Part 7's staging): HTTP 200, 7071 input tokens, 3000 of 3000 output tokens, no JSON.
The Meta Model API is the fake client of tests/test_second_opinion.py; no socket is opened.
"""
import json

import pytest

from part5 import opinion
from part5.opinion import meta_api, prompt
from part5.opinion.meta_api import OpinionError
from test_second_opinion import Fake, answer, attach, meta, take  # noqa: F401  (the fixtures are used by name)

CUT = "answer cut off at the output limit"
HALF = '{"verdicts": [{"fault_index": 0, "agrees": tr'   # what a reply cut at the allowance looks like


def truncated(tokens):
    """A reply whose text is a half-written JSON and whose usage is `tokens` (input, output)."""
    return {"output": [{"type": "reasoning", "summary": []},
                       {"type": "message", "content": [{"type": "output_text", "text": HALF}]}],
            "usage": {"input_tokens": tokens[0], "output_tokens": tokens[1]}}


def ledger_of(meta):
    return [json.loads(line) for line in meta.ledger.read_text().splitlines()]


def test_ticket_102_the_per_take_request_asks_for_the_history_allowance():
    body = prompt.request("exp-id", "fol-id", [], 4.0)
    assert body["max_output_tokens"] == prompt.SECOND_MAX_OUTPUT_TOKENS == prompt.HISTORY_MAX_OUTPUT_TOKENS == 8000
    assert meta_api.price(0, 8000) == 0.034 < meta_api.CALL_MAX_USD / 10   # the worst case stays far under the ceiling


def test_ticket_102_an_answer_cut_at_the_allowance_says_so_and_is_asked_once(take, meta):
    fake = Fake(truncated((7071, prompt.SECOND_MAX_OUTPUT_TOKENS)))
    block = attach(take, meta, fake)["second_opinion"]
    assert (block["status"], block["reason"]) == ("fallback", CUT)
    assert block["verdicts"] == [] and block["observations"] == [] and block["model"] is None
    assert block["usage"]["output_tokens"] == 8000 and block["usage"]["input_tokens"] == 7071
    assert len(fake.bodies) == 1 and fake.bodies[0]["max_output_tokens"] == 8000   # no retry: it would double the spend
    [line] = ledger_of(meta)
    assert (line["http_status"], line["output_tokens"], line["usd"]) == (200, 8000, block["usage"]["usd"])
    assert "estimated" not in line


@pytest.mark.parametrize("output_tokens", [7999, 3000, 400, 0])
def test_ticket_102_an_unreadable_answer_below_the_allowance_stays_unreadable(take, meta, output_tokens):
    """3000 of 3000 was the cut at the old allowance; under 8000 it is a model that stopped on its own."""
    block = attach(take, meta, Fake(truncated((7071, output_tokens))))["second_opinion"]
    assert (block["status"], block["reason"]) == ("fallback", "unreadable answer")
    assert block["usage"]["output_tokens"] == output_tokens


def test_ticket_102_an_answer_over_the_allowance_count_is_cut_too(take, meta):
    block = attach(take, meta, Fake(truncated((7071, 8001))))["second_opinion"]
    assert (block["status"], block["reason"]) == ("fallback", CUT)


def test_ticket_102_an_estimated_usage_says_nothing_about_what_the_model_wrote(take, meta):
    """No token counts in the body: the ledger line is the pre-call estimate at the full allowance, flagged estimated,
    and that is not the API's own count of what was used."""
    payload = {"output": [{"type": "message", "content": [{"type": "output_text", "text": HALF}]}]}
    block = attach(take, meta, Fake(payload))["second_opinion"]
    assert (block["status"], block["reason"]) == ("fallback", "unreadable answer")
    assert block["usage"]["estimated"] is True and block["usage"]["output_tokens"] == 8000


def test_ticket_102_a_readable_answer_at_the_allowance_is_still_shown(take, meta):
    """The reason only changes an answer that could not be read."""
    block = attach(take, meta, Fake(answer(tokens=(9000, 8000))))["second_opinion"]
    assert block["status"] == "ok" and block["reason"] is None


def test_ticket_102_the_estimate_and_the_ceiling_follow_the_requests_allowance(take, meta):
    """380000 input tokens at the old allowance of 3000 estimate USD 0.4878 and pass the ceiling of 0.50; at 8000 they
    estimate 0.509 and are refused before the call."""
    assert meta_api.price(380_000, 3000) < meta_api.CALL_MAX_USD < meta_api.price(380_000, 8000)
    fake = Fake(answer(), count=380_000)
    block = attach(take, meta, fake)["second_opinion"]
    assert (block["status"], block["reason"]) == ("fallback", "estimated $0.51 over the per-call limit of $0.50")
    assert fake.bodies == []


def test_ticket_102_an_estimated_ledger_line_and_the_cap_check_use_the_allowance(take, meta, monkeypatch):
    fake = Fake(OpinionError("timeout on responses"), count=1000)
    attach(take, meta, fake)
    [line] = ledger_of(meta)
    assert (line["output_tokens"], line["usd"], line["estimated"]) == (8000, 0.03525, True)
    monkeypatch.setenv("PART5_META_SPEND_CAP_USD", "0.05")   # spent 0.03525, and the next call is estimated at 0.03525 too
    again = Fake(answer(), count=1000)
    block = attach(take, meta, again)["second_opinion"]
    assert (block["status"], block["reason"]) == ("fallback", "spend cap reached") and again.bodies == []


@pytest.mark.parametrize("usage, allowance, reason", [
    ({"output_tokens": 8000}, 8000, CUT), ({"output_tokens": 8001}, 8000, CUT), ({"output_tokens": 7999}, 8000, "unreadable answer"),
    ({"output_tokens": 3000}, 3000, CUT), ({"output_tokens": 3000}, 8000, "unreadable answer"),
    ({"output_tokens": 8000, "estimated": True}, 8000, "unreadable answer"),
    ({}, 8000, "unreadable answer"), (None, 8000, "unreadable answer"),
])
def test_ticket_102_one_helper_decides_for_the_per_take_and_the_history_opinion(usage, allowance, reason):
    assert opinion.unreadable_reason(usage, allowance) == reason
    history = opinion._unreadable(usage)
    assert history == opinion.unreadable_reason(usage, prompt.HISTORY_MAX_OUTPUT_TOKENS)
