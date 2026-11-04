"""Ask this take's agent loop, spend and fallbacks (docs/specs/ask-this-take.md AC-ASK-05 to AC-ASK-08 and AC-ASK-10, the
hub's AC-4 and AC-5; TICKET-081).

The Meta Model API is replaced by `Scripted` (no socket): each `respond` returns the next scripted Responses body. The
ledger is a temp file (`meta` of tests/test_history_opinion.py opens the gate with a sentinel key).
"""
import json
import logging

import pytest
from test_ask_tools import golden_take, seated, seated_take  # noqa: F401  (seated is a fixture)
from test_history_opinion import KEY, ledger_lines, meta  # noqa: F401  (meta is a fixture)
from test_second_opinion import UNREADABLE_SHAPES, unreadable_outputs

from part5.ask import agent, tools
from part5.opinion import guard, meta_api, prompt
from part5.opinion.meta_api import OpinionError

QUESTION = "Why is my right elbow flagged?"
GOOD = "Your right elbow bends 36.1 degrees more than the example at 0.7 s."


class Scripted:
    """The Meta Model API stand-in for a tool-calling exchange: `respond` returns the next scripted body, or raises it
    with HTTP status `status`; every count and body is recorded."""

    def __init__(self, *payloads, count=500, status=500):
        self.payloads, self.count_tokens, self.failure_status = list(payloads), count, status
        self.counted, self.bodies, self.last_status = [], [], None

    def count(self, body):
        self.counted.append(body)
        return self.count_tokens

    def respond(self, body):
        self.bodies.append(body)
        item = self.payloads.pop(0)
        if isinstance(item, Exception):
            self.last_status = self.failure_status
            raise item
        self.last_status = 200
        return item


def usage(tokens):
    return {"input_tokens": tokens[0], "output_tokens": tokens[1]}


def calls(*items, rid="resp_1", tokens=(800, 60)):
    """A turn that calls tools: `items` are `(name, arguments)`; call ids are `<rid>_c<i>`."""
    output = [{"type": "reasoning", "summary": []}]
    output += [{"type": "function_call", "name": name, "arguments": json.dumps(args), "call_id": f"{rid}_c{i}",
                "status": "completed"} for i, (name, args) in enumerate(items)]
    return {"id": rid, "output": output, "usage": usage(tokens)}


def text(answer, rid="resp_9", tokens=(900, 80)):
    return {"id": rid, "output": [{"type": "message", "content": [{"type": "output_text", "text": answer}]}],
            "usage": usage(tokens)}


def ask(fake, question=QUESTION, take=None, **kw):
    events = []
    doc = agent.ask_run(question, take or golden_take(), live=True, client=fake,
                          on_event=lambda kind, data: events.append((kind, data)), **kw)
    return doc, events


def faults_then_answer(answer=GOOD):
    return Scripted(calls(("get_faults", {}), ("seek", {"t": 0.7}), ("spotlight", {"limb": "right_arm", "t": 0.7})),
                    text(answer))


# ---- AC-ASK-05: the loop ---------------------------------------------------------------------------------------------
def test_ac_ask_05_tool_calls_run_in_order_and_their_results_go_back_by_call_id(meta):
    fake = faults_then_answer()
    doc, events = ask(fake)
    assert (doc["source"], doc["answer"], doc["validated"], doc["fallback_reason"]) == ("model", GOOD, True, None)
    assert [c["name"] for c in doc["tool_calls"]] == ["get_faults", "seek", "spotlight"]
    assert doc["ui_actions"] == [{"type": "seek", "t": 0.7, "limb": None},
                                 {"type": "spotlight", "t": 0.7, "limb": "right_arm",
                                  "joints": ["right_shoulder", "right_elbow", "right_wrist"]}]
    first, second = fake.bodies
    assert first["model"] == "muse-wonder-1.0" and "previous_response_id" not in first
    assert [t["name"] for t in first["tools"]] == ["get_faults", "get_joint_angle", "compare_with_teacher", "seek",
                                                   "spotlight"]
    assert all(t["type"] == "function" and "function" not in t and t["parameters"]["type"] == "object"
               for t in first["tools"])
    parts = [p["text"] for p in first["input"][0]["content"]]
    assert parts[0] == prompt.ASK_INSTRUCTIONS and parts[-1] == f"Question: {QUESTION}"
    assert second["previous_response_id"] == "resp_1" and second["tools"] == first["tools"]
    assert [(i["type"], i["call_id"]) for i in second["input"]] == [("function_call_output", f"resp_1_c{i}")
                                                                    for i in range(3)]
    assert [json.loads(i["output"]) for i in second["input"]] == [c["result"] for c in doc["tool_calls"]]
    assert [k for k, _ in events] == ["tool_call", "tool_call", "ui_action", "tool_call", "ui_action"]


def test_ac_ask_05_plain_text_on_the_first_turn_is_an_answer(meta):
    fake = Scripted(text("The take shows a bent right elbow."))
    doc, events = ask(fake)
    assert (doc["source"], doc["tool_calls"], events, len(fake.bodies)) == ("model", [], [], 1)


def test_ac_ask_05_the_turn_limit_holds_and_the_last_turn_has_no_tools(meta):
    fake = Scripted(*[calls(("get_faults", {}), rid=f"resp_{i}") for i in range(agent.MAX_TURNS)])
    doc, _ = ask(fake)
    assert len(fake.bodies) == agent.MAX_TURNS and "tools" not in fake.bodies[-1]
    assert all("tools" in body for body in fake.bodies[:-1])
    assert (doc["source"], doc["fallback_reason"]) == ("measured_facts", agent.TURN_LIMIT)
    assert doc["answer"].startswith("The measurement found 2 differences from the example.")


LAST_TURN = {"type": "message", "role": "user", "content": [{"type": "input_text", "text": prompt.ASK_LAST_TURN}]}


def test_n4_the_last_turn_says_no_tool_is_left_and_carries_none_so_the_model_answers(meta):
    """N4 of the 1.14.0 recheck: live Ask asked for tools on the last turn, sent without them, and fell back."""
    turns = [calls(("get_faults", {}), rid=f"resp_{i}") for i in range(1, agent.MAX_TURNS)]
    fake = Scripted(*turns, text(GOOD))
    doc, _ = ask(fake)
    last = fake.bodies[-1]
    assert len(fake.bodies) == agent.MAX_TURNS and "tools" not in last and "tool_choice" not in last
    assert last["previous_response_id"] == f"resp_{agent.MAX_TURNS - 1}" and last["input"][-1] == LAST_TURN
    assert [item["type"] for item in last["input"][:-1]] == ["function_call_output"]   # the results come first
    assert "No more tools are available" in prompt.ASK_LAST_TURN and "from the tool results you already have" in \
        prompt.ASK_LAST_TURN
    assert all("tools" in body and LAST_TURN not in body["input"] for body in fake.bodies[:-1])
    assert (doc["source"], doc["answer"], doc["validated"], doc["fallback_reason"]) == ("model", GOOD, True, None)
    assert [line["prompt_version"] for line in ledger_lines(meta)] == [prompt.ASK_PROMPT_VERSION] * agent.MAX_TURNS


def test_n4_a_tool_call_on_the_last_turn_still_ends_in_the_measured_facts(meta):
    fake = Scripted(*[calls(("get_faults", {}), rid=f"resp_{i}") for i in range(1, agent.MAX_TURNS + 1)])
    doc, _ = ask(fake)
    assert fake.bodies[-1]["input"][-1] == LAST_TURN and "tools" not in fake.bodies[-1]
    assert (doc["source"], doc["fallback_reason"], doc["validated"]) == ("measured_facts", agent.TURN_LIMIT, False)
    assert len(doc["tool_calls"]) == agent.MAX_TURNS - 1   # the last turn's call was not run
    assert len(ledger_lines(meta)) == agent.MAX_TURNS == doc["spend"]["calls"]


def test_n4_only_the_last_turn_carries_the_message():
    outputs = [{"type": "function_call_output", "call_id": "c1", "output": "{}"}]
    tools = prompt.ask_tools(("left_elbow",), ("left_arm",))
    middle = prompt.ask_request(outputs, tools, "resp_1")
    assert middle["input"] == outputs and middle["tools"] == tools
    final = prompt.ask_request(outputs, tools, "resp_1", last=True)
    assert final["input"] == [*outputs, LAST_TURN] and "tools" not in final and outputs == middle["input"]


SEEK_TURN = {"type": "message", "role": "user", "content": [{"type": "input_text", "text": prompt.ASK_SEEK_TURN}]}


def test_askseek_the_turn_before_the_last_asks_for_the_seek_and_the_spotlight_and_keeps_its_tools(meta):
    """The two live answers of N4 read through every tool turn and never moved the page's replay: the turn before the
    last, the last one with tools, now says to call seek and spotlight, beside any read still needed."""
    turns = [calls(("get_faults", {}), rid=f"resp_{i}") for i in range(1, agent.MAX_TURNS)]
    fake = Scripted(*turns, text(GOOD))
    doc, _ = ask(fake)
    before_last, last = fake.bodies[-2], fake.bodies[-1]
    assert len(fake.bodies) == agent.MAX_TURNS and before_last["input"][-1] == SEEK_TURN
    assert [item["type"] for item in before_last["input"][:-1]] == ["function_call_output"]   # the results come first
    assert before_last["tools"] == fake.bodies[0]["tools"] and before_last["previous_response_id"] == "resp_2"
    assert "tools" not in last and last["input"][-1] == LAST_TURN and SEEK_TURN not in last["input"]   # N4, unchanged
    assert all(SEEK_TURN not in body["input"] for body in fake.bodies if body is not before_last)
    assert (doc["source"], doc["validated"]) == ("model", True)
    message = prompt.ASK_SEEK_TURN
    assert all(part in message for part in ("last turn with tools", "next turn has none", "seek", "spotlight",
                                            "reads you still need")) and not any(ch.isdigit() for ch in message)
    assert [line["prompt_version"] for line in ledger_lines(meta)] == ["ask-4"] * agent.MAX_TURNS


def test_askseek_a_model_that_calls_seek_and_spotlight_on_that_turn_ends_with_those_ui_actions(meta):
    fake = Scripted(calls(("get_faults", {}), rid="resp_1"),
                    calls(("get_joint_angle", {"joint": "right_elbow", "t0": 0.0, "t1": 1.0}), rid="resp_2"),
                    calls(("seek", {"t": 0.7}), ("spotlight", {"limb": "right_arm", "t": 0.7}), rid="resp_3"),
                    text(GOOD))
    doc, events = ask(fake)
    assert fake.bodies[2]["input"][-1] == SEEK_TURN and fake.bodies[3]["input"][-1] == LAST_TURN
    assert (doc["source"], doc["answer"], doc["validated"], doc["fallback_reason"]) == ("model", GOOD, True, None)
    assert [c["name"] for c in doc["tool_calls"]] == ["get_faults", "get_joint_angle", "seek", "spotlight"]
    assert doc["ui_actions"] == [{"type": "seek", "t": 0.7, "limb": None},
                                 {"type": "spotlight", "t": 0.7, "limb": "right_arm",
                                  "joints": ["right_shoulder", "right_elbow", "right_wrist"]}]
    assert [k for k, _ in events][-4:] == ["tool_call", "ui_action", "tool_call", "ui_action"]
    results = [json.loads(i["output"]) for i in fake.bodies[3]["input"][:-1]]
    assert results == [c["result"] for c in doc["tool_calls"][2:]]


def test_askseek_an_exchange_that_answers_before_that_turn_never_sees_the_message(meta):
    fake = faults_then_answer()
    ask(fake)
    assert all(SEEK_TURN not in body["input"] for body in fake.bodies)


def test_askseek_the_request_puts_the_message_after_the_results_and_the_last_turn_wins():
    outputs = [{"type": "function_call_output", "call_id": "c1", "output": "{}"}]
    declared = prompt.ask_tools(("left_elbow",), ("left_arm",))
    seek = prompt.ask_request(outputs, declared, "resp_1", seek=True)
    assert seek["input"] == [*outputs, SEEK_TURN] and seek["tools"] == declared and outputs == [seek["input"][0]]
    assert seek["previous_response_id"] == "resp_1"
    both = prompt.ask_request(outputs, declared, "resp_1", last=True, seek=True)
    assert both == prompt.ask_request(outputs, declared, "resp_1", last=True) and "tools" not in both


def test_ac_ask_05_calls_past_the_tool_limit_get_an_error_and_are_not_listed(meta):
    many = [("seek", {"t": 0.1 * i}) for i in range(agent.MAX_TOOL_CALLS + 2)]
    fake = Scripted(calls(*many), text("Done."))
    doc, _ = ask(fake)
    assert len(doc["tool_calls"]) == agent.MAX_TOOL_CALLS == len(doc["ui_actions"])
    outputs = [json.loads(i["output"]) for i in fake.bodies[1]["input"]]
    assert outputs[-2:] == [{"error": agent.TOOL_LIMIT}] * 2


def test_ac_ask_05_a_call_of_no_tool_is_answered_with_an_error_and_not_listed(meta):
    fake = Scripted(calls(("read_file", {"path": "/etc/passwd"})), text("I can only answer about this take."))
    doc, _ = ask(fake)
    assert doc["tool_calls"] == [] and "no tool of that name" in json.loads(fake.bodies[1]["input"][0]["output"])["error"]


# ---- AC-ASK-06: spend through the one ledger (hub AC-4) --------------------------------------------------------------
def test_ac_ask_06_every_call_is_one_ledger_line_at_the_wonder_rates(meta):
    doc, _ = ask(faults_then_answer())
    lines = ledger_lines(meta)
    assert [(x["model"], x["purpose"], x["turn"], x["prompt_version"], x["http_status"]) for x in lines] == [
        ("muse-wonder-1.0", "ask", 1, prompt.ASK_PROMPT_VERSION, 200), ("muse-wonder-1.0", "ask", 2, "ask-4", 200)]
    assert lines[0]["usd"] == round((800 * 4.00 + 60 * 20.00) / 1e6, 6) == 0.0044
    assert lines[1]["usd"] == round((900 * 4.00 + 80 * 20.00) / 1e6, 6)
    assert doc["spend"] == {"usd": round(lines[0]["usd"] + lines[1]["usd"], 6), "ledger_purpose": "ask", "calls": 2,
                            "input_tokens": 1700, "output_tokens": 140, "cached_tokens": 0, "estimated": False}
    assert all(KEY not in json.dumps(x) and GOOD not in json.dumps(x) for x in lines)


def test_ac_ask_06_the_muse_spark_lines_and_prices_are_unchanged():
    assert meta_api.price(1000, 1000) == round((1000 * 1.25 + 1000 * 4.25) / 1e6, 6)
    assert meta_api.ledger_line(200, {"usd": 0})["model"] == "muse-spark-1.3"


def test_ac_ask_06_an_oversize_request_is_refused_before_any_call(meta):
    fake = Scripted(text(GOOD), count=200_000)   # 200k tokens at $4 a million is $0.80, over the $0.50 ceiling
    doc, _ = ask(fake)
    assert fake.bodies == [] and ledger_lines(meta) == []   # the ledger is opened, the call refused, nothing written
    assert doc["fallback_reason"] == "estimated $0.86 over the per-call limit of $0.50"
    assert (doc["source"], doc["live"], doc["model"], doc["spend"]["calls"]) == ("measured_facts", False, None, 0)


def test_ac_ask_06_a_later_turn_the_question_cannot_afford_is_refused_before_it_is_sent(meta, monkeypatch):
    monkeypatch.setenv("PART5_META_CALL_MAX_USD", "0.07")   # the first turn's $0.062 estimate fits; two turns do not
    fake = faults_then_answer()
    doc, _ = ask(fake)
    assert len(fake.bodies) == 1 and len(ledger_lines(meta)) == 1
    assert doc["fallback_reason"].endswith("for this question over the per-call limit of $0.07")
    assert [c["name"] for c in doc["tool_calls"]] == ["get_faults", "seek", "spotlight"]   # kept, and the facts use them
    assert doc["spend"]["calls"] == 1 and doc["live"] is True and doc["model"] == "muse-wonder-1.0"


def test_ac_ask_06_a_later_turn_is_estimated_with_the_context_it_carries(meta):
    fake = faults_then_answer()
    ask(fake)
    assert len(fake.counted) == 1   # only the first turn's input is counted by the API


def test_ac_ask_06_the_cap_and_an_unreadable_ledger_refuse_as_elsewhere(meta, monkeypatch):
    monkeypatch.setenv("PART5_META_SPEND_CAP_USD", "0")
    doc, _ = ask(faults_then_answer())
    assert doc["fallback_reason"] == "spend cap reached"
    monkeypatch.delenv("PART5_META_SPEND_CAP_USD")
    meta.ledger.parent.mkdir(parents=True, exist_ok=True)
    meta.ledger.write_text('{"usd": NaN}\n')
    doc, _ = ask(faults_then_answer())
    assert doc["fallback_reason"] == "usage ledger not readable"


# ---- AC-ASK-07: the live switch and the key ----------------------------------------------------------------------
def test_ac_ask_07_no_key_makes_no_call(monkeypatch, tmp_path):
    monkeypatch.setenv("META_LIVE", "1")
    fake = Scripted(text(GOOD))
    doc = agent.ask_run(QUESTION, golden_take(), live=True, client=fake)
    assert fake.bodies == [] and doc["fallback_reason"] == "no key" and doc["source"] == "measured_facts"
    assert [c.get("by") for c in doc["tool_calls"]] == ["part5"]


def test_ac_ask_07_live_mode_off_makes_no_call(meta, monkeypatch):
    monkeypatch.delenv("META_LIVE")
    fake = Scripted(text(GOOD))
    doc = agent.ask_run(QUESTION, golden_take(), client=fake)
    assert fake.bodies == [] and doc["fallback_reason"].startswith("live calls are off") and not meta.ledger.exists()


def test_ac_ask_07_the_key_is_read_for_the_client_and_never_shown(meta, monkeypatch, caplog):
    made = []

    def build(key, timeout_s=None):
        made.append((key, timeout_s))
        return Scripted(text("A bent elbow at 99 s."))   # forged: the replacement is logged
    monkeypatch.setattr(meta_api, "HttpClient", build)
    doc = agent.ask_run(QUESTION, golden_take(), timeout_s=agent.ASK_TIMEOUT_S)
    assert made == [(KEY, agent.ASK_TIMEOUT_S)]
    assert KEY not in json.dumps(doc) + caplog.text


# ---- AC-ASK-08: a failed call ------------------------------------------------------------------------------------
@pytest.mark.parametrize("failure, reason", [(OpinionError("HTTP 429 on responses"), "HTTP 429 on responses"),
                                             (OpinionError("timeout on responses"), "timeout on responses")])
def test_ac_ask_08_a_failed_call_keeps_the_tool_calls_and_gives_the_facts(meta, failure, reason):
    fake = Scripted(calls(("get_faults", {}), ("seek", {"t": 0.7})), failure, status=429)
    doc, _ = ask(fake)
    assert (doc["source"], doc["fallback_reason"], doc["validated"]) == ("measured_facts", reason, False)
    assert [c["name"] for c in doc["tool_calls"]] == ["get_faults", "seek"] and len(doc["ui_actions"]) == 1
    assert doc["live"] is True and doc["model"] == "muse-wonder-1.0" and doc["spend"]["calls"] == 1
    assert [x["http_status"] for x in ledger_lines(meta)] == [200, 429]


def test_ac_ask_08_an_answer_with_no_response_id_cannot_be_followed(meta):
    turn = calls(("get_faults", {}))
    del turn["id"]
    doc, _ = ask(Scripted(turn))
    assert doc["fallback_reason"] == "answer has no response id"
    assert [c.get("by") for c in doc["tool_calls"]] == ["part5"]   # the model's call was not run; the facts made one


def test_ac_ask_08_a_body_that_is_not_an_object_is_unreadable(meta):
    doc, _ = ask(Scripted(["not", "a", "body"]))
    assert doc["fallback_reason"] == "unreadable answer"


@pytest.mark.parametrize("output", [5, "abc", {"type": "function_call"}, True, 1.5, ""])
def test_r5_an_output_that_is_not_a_list_is_an_unreadable_answer(meta, output):
    """R5 of the 1.14.0 review: `{"output": 5}` raised TypeError out of `ask_run` after the ledger line was written."""
    doc, _ = ask(Scripted({"id": "resp_1", "output": output, "usage": usage((800, 60))}))
    assert (doc["source"], doc["fallback_reason"]) == ("measured_facts", "unreadable answer")
    assert [x["http_status"] for x in ledger_lines(meta)] == [200]
    for read in (meta_api.function_calls, meta_api.output_text):
        with pytest.raises(OpinionError, match="unreadable answer"):
            read({"output": output})


@pytest.mark.parametrize("shape", UNREADABLE_SHAPES)
def test_n1_a_reply_of_the_wrong_shape_is_an_unreadable_answer(meta, shape):
    """N1 of the 1.14.0 recheck: `{"output": [{"type": "message", "content": 5}]}` raised TypeError out of `ask_run`."""
    output = unreadable_outputs(GOOD)[shape]
    doc, _ = ask(Scripted({"id": "resp_1", "output": output, "usage": usage((800, 60))}))
    assert (doc["source"], doc["fallback_reason"], doc["validated"]) == ("measured_facts", "unreadable answer", False)
    assert [x["http_status"] for x in ledger_lines(meta)] == [200] and doc["spend"]["calls"] == 1


def test_n1_a_tool_call_beside_an_item_of_the_wrong_shape_is_not_run(meta):
    turn = calls(("seek", {"t": 0.7}))
    turn["output"].append(5)
    doc, _ = ask(Scripted(turn))
    assert (doc["source"], doc["fallback_reason"]) == ("measured_facts", "unreadable answer")
    assert [c.get("by") for c in doc["tool_calls"]] == ["part5"] and doc["ui_actions"] == []


def test_r5_no_output_and_a_null_one_are_no_items():
    assert meta_api.function_calls({}) == meta_api.function_calls({"output": None}) == []
    assert meta_api.output_text({"output_text": "plain"}) == "plain"


def test_ac_ask_08_an_empty_answer_at_the_output_limit_is_cut_off(meta):
    doc, _ = ask(Scripted(text("", tokens=(900, prompt.ASK_MAX_OUTPUT_TOKENS))))
    assert doc["fallback_reason"] == agent.CUT_OFF
    doc, _ = ask(Scripted(text("  \n ", tokens=(900, 20))))
    assert doc["fallback_reason"] == "no answer"


# ---- AC-ASK-10: the model is named --------------------------------------------------------------------------------
def test_ac_ask_10_the_document_names_the_model_and_whether_it_was_called_now(meta):
    doc, _ = ask(faults_then_answer())
    assert (doc["model"], doc["live"], doc["format"], doc["schema_version"]) == ("muse-wonder-1.0", True,
                                                                                 "simon.ask.v1", "1.0.0")


def test_ac_ask_10_no_call_names_no_model(monkeypatch):
    doc = agent.ask_run("What is my score?", golden_take())
    assert (doc["model"], doc["live"], doc["spend"]["usd"]) == (None, False, 0)


# ---- AC-ASK-03 and AC-ASK-04 through the loop: a forged answer is replaced and logged (hub AC-2) --------------------
def test_ac_ask_03_a_forged_number_is_replaced_by_the_measured_facts_and_logged(meta, caplog):
    forged = "Your right elbow bends 42.5 degrees more than the example at 0.7 s, twice the limit of 20."
    caplog.set_level(logging.WARNING, logger="part5.ask")
    doc, _ = ask(faults_then_answer(forged))
    assert (doc["source"], doc["validated"], doc["model"], doc["live"]) == ("measured_facts", False, "muse-wonder-1.0",
                                                                           True)
    assert doc["replaced_numbers"] == ["42.5"]   # 0.7 and 20 (the threshold) are in get_faults; numbers before "twice"
    assert doc["fallback_reason"] == guard.NUMBER_NOT_FOUND
    assert doc["answer"] == guard.measured_facts(doc["tool_calls"]) and "42.5" not in doc["answer"]
    assert doc["answer"].startswith("The measurement found 2 differences from the example. Right elbow bent more")
    logged = [r.getMessage() for r in caplog.records if r.name == "part5.ask"]
    assert logged == ["ask: the model's answer was replaced by the measured facts (a number in the answer is not in "
                      "any tool result); numbers in no tool result: 42.5"]
    assert forged not in caplog.text   # the model's text is never logged


def test_ac_ask_03_part7_reads_the_replaced_numbers_on_every_answer_replaced_for_them(meta):
    """Part 7's one request on the contract: a `validated: false` answer replaced for its numbers carries them all."""
    doc, _ = ask(faults_then_answer("At 3.2 s and at 4 s the elbow is off by 77 degrees."))
    assert doc["validated"] is False and doc["replaced_numbers"] == ["3.2", "4", "77"]


def test_ac_ask_03_an_answer_whose_numbers_are_all_found_is_kept(meta):
    kept = "Your right elbow bends 36 degrees more than the example at 0.7 s; the limit is 20 degrees, two faults."
    doc, _ = ask(faults_then_answer(kept))
    assert (doc["source"], doc["validated"], doc["replaced_numbers"], doc["answer"]) == ("model", True, [], kept)


def test_ac_ask_03_a_number_with_no_tool_call_at_all_is_replaced_and_part5_reads_the_faults(meta):
    doc, _ = ask(Scripted(text("Your elbow is 30 degrees off.")))
    assert doc["replaced_numbers"] == ["30"] and [c.get("by") for c in doc["tool_calls"]] == ["part5"]
    assert doc["answer"] == guard.measured_facts(doc["tool_calls"])


@pytest.mark.parametrize("answer, reason", [
    ("See https://example.com for more.", "has a link"),
    ("Your knee pain shows at the bottom.", "uses a word this product does not use"),
    ("Great job on the squat!", "adds praise"),
    ("Bend more\u200b at the knee.", "has a control character"),
    ("x" * (guard.MAX_ANSWER_CHARS + 1), "answer too long"),
    ("   ", guard.NO_ANSWER),
])
def test_ac_ask_04_an_answer_the_word_guard_refuses_is_replaced_with_its_reason(meta, answer, reason):
    doc, _ = ask(faults_then_answer(answer))
    assert (doc["source"], doc["fallback_reason"], doc["replaced_numbers"]) == ("measured_facts", reason, [])


def test_r2_a_count_in_words_is_replaced_through_the_loop(meta):
    doc, _ = ask(faults_then_answer("Your right elbow bends twice as far as the example at 0.7 s."))
    assert (doc["source"], doc["fallback_reason"], doc["replaced_numbers"]) == ("measured_facts", guard.COUNT_IN_WORDS,
                                                                                [])


def test_ac_ask_04_line_breaks_and_runs_of_blanks_become_one_space(meta):
    doc, _ = ask(faults_then_answer("Your right elbow\n\nbends   more than the example."))
    assert doc["answer"] == "Your right elbow bends more than the example." and doc["source"] == "model"


def test_ac_ask_04_the_question_is_never_a_source_of_numbers(meta):
    doc, _ = ask(faults_then_answer("At 5 s, as you asked."), question=f"{QUESTION} What about 5 s?")
    assert doc["replaced_numbers"] == ["5"]


def test_r3_on_a_seated_take_a_leg_angle_is_never_a_measurement(meta, seated):
    """R3 of the 1.14.0 review: the follower marked the legs not scored, so the model gets no leg angle to report, and
    an answer that says one anyway is replaced by the measured facts, which hold none either."""
    fake = Scripted(calls(("get_joint_angle", {"joint": "left_knee", "t0": 0, "t1": 1}),
                          ("spotlight", {"limb": "left_leg", "t": 1})), text("Your left knee bends 87.4 degrees."))
    doc, events = ask(fake, take=seated_take(seated))
    assert [c["result"] for c in doc["tool_calls"][:2]] == [{"error": tools.JOINT_NOT_SCORED},
                                                            {"error": tools.LIMB_NOT_SCORED}]
    assert (doc["source"], doc["replaced_numbers"], doc["ui_actions"]) == ("measured_facts", ["87.4"], [])
    assert doc["tool_calls"][2]["by"] == "part5"   # no fact among the model's results: Part 5 read the faults
    assert doc["answer"] == "The measurement found no difference from the example."
    assert [k for k, _ in events] == ["tool_call", "tool_call", "tool_call"]


def test_r1_a_number_laundered_through_a_refused_call_is_replaced(meta):
    """R1 of the 1.14.0 review, through the loop: the model sends `seek({"87.5": 1})`, then says 87.5 degrees."""
    doc, events = ask(Scripted(calls(("seek", {"87.5": 1})), text("Your knee bends 87.5 degrees.")))
    assert (doc["source"], doc["validated"], doc["replaced_numbers"]) == ("measured_facts", False, ["87.5"])
    assert doc["tool_calls"][0]["ok"] is False and "87.5" not in doc["tool_calls"][0]["result"]["error"]


def test_r1_a_call_whose_arguments_fail_the_word_guard_is_redacted_in_the_document_and_the_stream(meta):
    fake = Scripted(calls(("spotlight", {"limb": "see www.example.com now", "t": 0.7}), ("get_faults", {})),
                    text(GOOD))
    doc, events = ask(fake)
    assert doc["source"] == "model" and doc["tool_calls"][0] == {
        "name": "spotlight", "arguments": {}, "ok": False, "result": {"error": tools.ARGUMENTS_NOT_SHOWN}}
    assert [d for k, d in events if k == "tool_call"] == doc["tool_calls"]
    assert "example.com" not in json.dumps(doc) + json.dumps(events)
    assert json.loads(fake.bodies[1]["input"][0]["output"]) == {"error": tools.ARGUMENTS_NOT_SHOWN}


def test_ac_ask_04_tool_calls_with_their_results_ship_beside_a_replaced_answer(meta):
    doc, _ = ask(Scripted(calls(("compare_with_teacher", {"joint": "right_elbow", "t": 0.7})), text("Off by 99.")))
    assert [c["name"] for c in doc["tool_calls"]] == ["compare_with_teacher"]
    assert doc["answer"].startswith("At 0.7 s, right elbow bend: 35 degrees in the take and 8.3 in the example")
