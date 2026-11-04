"""`part5 ask` and `POST api/ask` (docs/specs/ask-this-take.md AC-ASK-09, AC-ASK-11 to AC-ASK-13, the hub's AC-3 witness
and AC-5; TICKET-081). Every document here is also checked against `contracts/ask.schema.json`.

The production client is replaced by the scripted fake of tests/test_ask_agent.py (no socket); the stream is read
through `api.handle` and once through the real server on the loopback.
"""
import copy
import json
import shutil
import subprocess
import threading
import time
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import jsonschema
import pytest
from test_ask_agent import GOOD, QUESTION, Scripted, calls, faults_then_answer, text
from test_ask_tools import ANALYSIS, REPLAY, cut, golden_take
from test_history_opinion import KEY, ledger_lines, meta  # noqa: F401  (a fixture)

from part5 import api, cli, contract, opinion, server
from part5 import replay as replay_module
from part5.ask import agent, tools
from part5.opinion import meta_api

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = jsonschema.Draft202012Validator(contract.load_schema("ask"))
REQUEST = jsonschema.Draft202012Validator({**contract.load_schema("ask")["$defs"]["request"]})


def valid(doc):
    problems = [f"{'/'.join(map(str, e.absolute_path))}: {e.message[:120]}" for e in VALIDATOR.iter_errors(doc)]
    assert problems == []
    return doc


def events_of(raw):
    """`[(event, data)]` of a text/event-stream body."""
    out = []
    for block in raw.decode().split("\n\n"):
        if block.strip():
            name, data = block.split("\n")
            out.append((name.removeprefix("event: "), json.loads(data.removeprefix("data: "))))
    return out


@pytest.fixture(autouse=True)
def fresh_limits(monkeypatch):
    """Each test starts with no request counted against either per-client limit of api/ask; a test that needs a smaller
    limit sets its own after this."""
    monkeypatch.setattr(api, "_MUSE_LIMIT", api.ClientLimit())
    monkeypatch.setattr(api, "_ASK_FREE_LIMIT", api.ClientLimit(per_minute=api.ASK_FREE_PER_MINUTE))


@pytest.fixture
def files(tmp_path):
    a, r = tmp_path / "in" / "analysis.json", tmp_path / "in" / "replay.json"
    a.parent.mkdir()
    a.write_text(json.dumps(ANALYSIS))
    r.write_text(json.dumps(REPLAY))
    return SimpleNamespace(analysis=a, replay=r)


@pytest.fixture
def served(monkeypatch):
    """The production client replaced: each build takes the next scripted fake of `served.fakes`."""
    holder = SimpleNamespace(fakes=[], made=[])

    def build(key, timeout_s=None):
        holder.made.append((key, timeout_s))
        return holder.fakes.pop(0)
    monkeypatch.setattr(meta_api, "HttpClient", build)
    return holder


def ask_cli(files, *extra, question=QUESTION):
    return cli.main(["ask", str(files.analysis), str(files.replay), question, *map(str, extra)])


# ---- AC-ASK-12: the command -------------------------------------------------------------------------------------------
def test_ac_ask_12_without_out_the_document_is_all_of_stdout(files, capsys):
    assert ask_cli(files) == 0
    shown = capsys.readouterr()
    doc = valid(json.loads(shown.out))
    assert (doc["source"], doc["question"]) == ("measured_facts", QUESTION)
    assert shown.err == f"ask: measured_facts ({doc['fallback_reason']}), 1 tool call, $0.0000\n"


def test_ac_ask_12_with_out_the_document_is_written_and_the_summary_goes_to_stdout(files, tmp_path, capsys):
    out = tmp_path / "out" / "ask.json"
    assert ask_cli(files, "--out", out) == 0
    shown = capsys.readouterr()
    assert valid(json.loads(out.read_text()))["format"] == "simon.ask.v1"
    assert shown.out.startswith(f"{out}: ask: measured_facts (") and shown.err == ""


def test_ac_ask_12_live_with_the_key_answers_through_the_model_and_never_prints_the_key(meta, served, files, capsys):
    served.fakes.append(faults_then_answer())
    assert ask_cli(files, "--live") == 0
    shown = capsys.readouterr()
    doc = valid(json.loads(shown.out))
    assert (doc["source"], doc["answer"], doc["live"]) == ("model", GOOD, True)
    assert served.made == [(KEY, meta_api.TIMEOUT_S)] and KEY not in shown.out + shown.err


@pytest.mark.parametrize("question", ["", "   ", "x" * 501])
def test_ac_ask_12_a_wrong_question_is_a_usage_error_before_any_file_is_read(tmp_path, capsys, question):
    missing = SimpleNamespace(analysis=tmp_path / "nope.json", replay=tmp_path / "nope2.json")
    assert ask_cli(missing, question=question) == 2
    assert capsys.readouterr().err.startswith("part5 ask: question: ")


@pytest.mark.parametrize("break_it, says", [
    (lambda f: f.analysis.unlink(), "analysis.json: cannot be read"),
    (lambda f: f.replay.write_text("{not json"), "replay.json: not JSON"),
    (lambda f: f.analysis.write_text('{"format": "simon.analysis.v1", "faults": [], "x": NaN}'), "analysis.json: not JSON"),
    (lambda f: f.analysis.write_text('{"format": "other", "faults": []}'), "analysis.json: not an analysis"),
    (lambda f: f.replay.write_text(json.dumps(dict(REPLAY, **cut(REPLAY, 5)))), "replay.json: not the replay of this analysis"),
])
def test_ac_ask_12_an_input_problem_is_exit_1_naming_the_file(files, capsys, break_it, says):
    break_it(files)
    assert ask_cli(files) == 1
    err = capsys.readouterr().err
    assert err.startswith("part5 ask: ") and says in err


def test_ac_ask_12_an_out_that_cannot_be_written_is_exit_1(files, tmp_path, capsys):
    assert ask_cli(files, "--out", tmp_path) == 1
    assert "part5 ask: cannot write" in capsys.readouterr().err


def test_ac_ask_13_the_input_files_are_never_written(files):
    before = files.analysis.read_bytes(), files.replay.read_bytes()
    ask_cli(files)
    assert (files.analysis.read_bytes(), files.replay.read_bytes()) == before


# ---- AC-ASK-11: the stream ------------------------------------------------------------------------------------------
def test_ac_ask_11_the_command_streams_the_events_and_ends_with_the_document(meta, served, files, tmp_path, capsys):
    served.fakes.append(faults_then_answer())
    out = tmp_path / "ask.json"
    assert ask_cli(files, "--live", "--stream", "--out", out) == 0
    shown = capsys.readouterr()
    events = events_of(shown.out.encode())
    assert [e for e, _ in events] == ["tool_call", "tool_call", "ui_action", "tool_call", "ui_action", "answer"]
    assert events[-1][1] == json.loads(out.read_text()) and shown.err.startswith("ask: model, 3 tool calls, $")


def post(body, client="203.0.113.7"):
    raw = body if isinstance(body, bytes) else json.dumps(body).encode()
    return api.handle("POST", "/api/ask", raw, base_path="/", client=client)


def request(**extra):
    return {"question": QUESTION, "analysis": ANALYSIS, "replay": REPLAY, **extra}


def test_ac_ask_11_the_route_streams_tool_calls_before_their_actions_and_the_document_last(meta, served):
    served.fakes += [faults_then_answer(), faults_then_answer()]
    status, headers, body = post(request(stream=True))
    assert status == 200 and headers["Content-Type"] == "text/event-stream; charset=utf-8"
    assert not isinstance(body, bytes)
    events = events_of(b"".join(body))
    assert [e for e, _ in events] == ["tool_call", "tool_call", "ui_action", "tool_call", "ui_action", "answer"]
    doc = valid(events[-1][1])
    assert [d for e, d in events if e == "tool_call"] == doc["tool_calls"]
    assert [d for e, d in events if e == "ui_action"] == doc["ui_actions"]
    status, _, plain = post(request())
    assert json.loads(plain) == doc   # the same exchange through the JSON route


def test_ac_ask_11_the_real_server_writes_the_stream_as_it_comes(meta, served):
    served.fakes.append(faults_then_answer())
    httpd = server.make_server(port=0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        host, port = httpd.server_address
        req = urllib.request.Request(f"http://{host}:{port}/api/ask", data=json.dumps(request(stream=True)).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=60) as answer:
            kind, raw = answer.headers["Content-Type"], answer.read()
    finally:
        httpd.shutdown()
        httpd.server_close()
    assert kind.startswith("text/event-stream") and events_of(raw)[-1][1]["source"] == "model"


def test_ac_ask_11_a_failure_after_the_stream_began_is_an_error_event(monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("a bug")
    monkeypatch.setattr(api, "ask_run", broken)
    status, _, body = post(request(stream=True))
    assert status == 200 and events_of(b"".join(body)) == [("error", opinion.STREAM_FAILED)]


# ---- AC-ASK-12: the route -------------------------------------------------------------------------------------------
def test_ac_ask_12_the_route_answers_the_document(meta, served):
    served.fakes.append(faults_then_answer())
    status, headers, body = post(request())
    doc = valid(json.loads(body))
    assert status == 200 and headers["Content-Type"].startswith("application/json") and doc["source"] == "model"
    assert served.made == [(KEY, agent.ASK_TIMEOUT_S)]
    assert api.ROUTES["api/ask"][0] == "POST"


def test_r5_a_malformed_model_reply_is_a_document_on_the_route_not_a_500(meta, served):
    served.fakes.append(Scripted({"id": "resp_1", "output": 5, "usage": {"input_tokens": 9, "output_tokens": 9}}))
    status, _, body = post(request())
    doc = valid(json.loads(body))
    assert status == 200 and (doc["source"], doc["fallback_reason"]) == ("measured_facts", "unreadable answer")


@pytest.mark.parametrize("body, field, says", [
    (b"{oops", "body", "body: not JSON"),
    (b'{"question": "x", "analysis": {}, "replay": {}, "n": NaN}', "body", "body: not JSON"),
    ([1], "body", "body: expected a JSON object"),
    (request(question=""), "question", "question: give the question as text"),
    (request(question=7), "question", "question: give the question as text"),
    (request(question="y" * 501), "question", "question: 501 characters, the limit is 500"),
    (request(analysis="x"), "analysis", "analysis: not an analysis"),
    (request(replay={"format": "simon.replay.v1"}), "replay", "replay: joints are not the 17"),
    (request(stream="yes"), "stream", "stream: must be true or false"),
])
def test_ac_ask_12_a_wrong_request_is_400_naming_the_field(body, field, says):
    status, _, answer = post(body)
    error = json.loads(answer)["error"]
    assert (status, error["field"]) == (400, field) and error["message"].startswith(says)


def test_ac_ask_12_a_body_over_the_limit_is_413_and_a_get_405():
    status, _, answer = post(b"x" * (api.MAX_BODY_BYTES + 1))
    assert status == 413 and json.loads(answer)["error"]["field"] == "upload"
    status, headers, _ = api.handle("GET", "/api/ask", b"", base_path="/")
    assert status == 405 and headers["Allow"] == "POST"


def test_ac_ask_12_only_a_request_that_will_pay_counts_against_the_client_limit(meta, served, monkeypatch):
    monkeypatch.setattr(api, "_MUSE_LIMIT", api.ClientLimit(per_minute=1))
    served.fakes += [faults_then_answer()]
    assert post(request())[0] == 200
    status, headers, answer = post(request())
    assert status == 429 and "Retry-After" in headers and served.fakes == []
    monkeypatch.delenv("META_LIVE")
    for _ in range(3):   # no call can be made: no Muse slot is taken (the route's own limit counts them, R12)
        assert post(request())[0] == 200
    assert len(api._MUSE_LIMIT._starts["203.0.113.7"]) == 1 and len(api._ASK_FREE_LIMIT._starts["203.0.113.7"]) == 3


def test_r6_the_429_of_api_ask_has_its_own_field_and_words(meta, served, monkeypatch):
    """R6 of the 1.14.0 review: the Ask box showed "Too many Muse Spark requests. Wait a minute or pick template.", field
    `phrasing`, which names a control the box does not have."""
    monkeypatch.setattr(api, "_MUSE_LIMIT", api.ClientLimit(per_minute=1))
    served.fakes += [faults_then_answer()]
    assert post(request())[0] == 200
    status, headers, answer = post(request())
    assert status == 429 and json.loads(answer)["error"] == {"field": api.ASK_LIMIT_FIELD,
                                                             "message": api.ASK_LIMIT_MESSAGE}
    assert api.ASK_LIMIT_FIELD == "question" and "Muse Spark" not in api.ASK_LIMIT_MESSAGE
    assert "template" not in api.ASK_LIMIT_MESSAGE and int(headers["Retry-After"]) >= 1


def test_r6_the_paid_phrasing_routes_keep_their_429():
    limit = api.ClientLimit(per_minute=1)
    limit.start("10.0.0.9")
    limit.finish("10.0.0.9")
    with pytest.raises(api.ApiError) as caught:
        limit.start("10.0.0.9")
    assert (caught.value.status, caught.value.field, caught.value.message) == (429, "phrasing", api.MUSE_LIMIT_MESSAGE)


def test_r12_a_request_that_makes_no_model_call_is_rate_limited_per_client(monkeypatch):
    monkeypatch.setattr(api, "_ASK_FREE_LIMIT", api.ClientLimit(per_minute=2))
    assert [post(request())[0] for _ in range(2)] == [200, 200]
    status, headers, answer = post(request())
    assert status == 429 and json.loads(answer)["error"]["field"] == "question" and "Retry-After" in headers
    assert post(request(), client="198.51.100.4")[0] == 200   # another client has its own count
    assert api.ASK_FREE_PER_MINUTE == 30 and api._MUSE_LIMIT._starts == {}


def test_r12_a_free_request_is_one_at_a_time_and_a_stream_frees_its_slot(monkeypatch):
    limit = api.ClientLimit(per_minute=5)
    monkeypatch.setattr(api, "_ASK_FREE_LIMIT", limit)
    _, _, body = post(request(stream=True))
    b"".join(body)
    deadline = time.monotonic() + 60
    while limit._running and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not limit._running and post(request())[0] == 200
    limit.start("203.0.113.7")   # one still running for this client
    assert post(request())[0] == 429


def test_r12_a_refused_request_takes_no_slot(monkeypatch):
    monkeypatch.setattr(api, "_ASK_FREE_LIMIT", api.ClientLimit(per_minute=1))
    assert post(request(question=""))[0] == 400 and post(b"x" * (api.MAX_BODY_BYTES + 1))[0] == 413
    assert post(request())[0] == 200


def stretched(n):
    """The golden replay with its example and its take each stretched to `n` frames: a sound replay of a long take."""
    doc = copy.deepcopy(REPLAY)
    for key, times in (("follower", "follower_t"), ("expected", "expected_t")):
        doc[key] = [doc[key][i % len(doc[key])] for i in range(n)]
        doc[times] = [round(i / 30, 6) for i in range(n)]
    doc["exp_to_fol"] = list(range(n))
    doc.update(replay_module.aligned_until(doc["exp_to_fol"], doc["follower_t"]))
    return doc


def test_r12_the_replay_frames_are_capped_as_api_analyse_caps_an_upload():
    over = api.MAX_ASK_FRAMES // 2 + 1
    status, _, answer = post(request(replay=stretched(over)))
    error = json.loads(answer)["error"]
    assert (status, error["field"]) == (400, "replay")
    assert error["message"] == f"replay: {2 * over} frames in the example and the take together, the limit is 12000"
    assert api.MAX_ASK_FRAMES == 2 * api.MAX_FRAMES == 12000 and api._ASK_FREE_LIMIT._starts == {}
    assert post(request(replay=stretched(api.MAX_ASK_FRAMES // 2)))[0] == 200


def test_ac_ask_12_a_stream_releases_the_slot_when_the_exchange_ends(meta, served, monkeypatch):
    monkeypatch.setattr(api, "_MUSE_LIMIT", api.ClientLimit(per_minute=5))
    served.fakes += [faults_then_answer(), faults_then_answer()]
    _, _, body = post(request(stream=True))
    b"".join(body)
    assert post(request())[0] == 200   # one at a time: the first one's slot is free again


def test_ac_ask_12_a_stream_dropped_before_it_is_read_still_frees_the_slot(meta, served, monkeypatch):
    limit = api.ClientLimit(per_minute=5)
    monkeypatch.setattr(api, "_MUSE_LIMIT", limit)
    served.fakes += [faults_then_answer(), faults_then_answer()]
    post(request(stream=True))   # the page went away before the server wrote a byte: the body is never iterated
    deadline = time.monotonic() + 60
    while limit._running and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not limit._running and post(request())[0] == 200


def test_the_request_schema_accepts_what_the_route_accepts():
    assert list(REQUEST.iter_errors(request(stream=True))) == []
    assert list(REQUEST.iter_errors({"question": QUESTION})) != []


# ---- AC-ASK-09: the cache -----------------------------------------------------------------------------------------
@pytest.fixture
def cache(meta, served, tmp_path, monkeypatch):
    """A cached document made by one scripted live exchange on the golden take, then live mode off."""
    served.fakes.append(faults_then_answer())
    doc = agent.ask_run(QUESTION, golden_take(), live=True)
    path = tmp_path / "ask.example.json"
    path.write_text(json.dumps(doc))
    monkeypatch.setattr(agent, "ASK_EXAMPLE", path)
    monkeypatch.delenv("META_LIVE")
    return SimpleNamespace(doc=doc, path=path)


def test_ac_ask_09_the_demo_question_on_the_demo_take_gives_the_cached_answer(cache):
    events = []
    doc = valid(agent.ask_run(f"  {QUESTION.upper()} ", golden_take(), on_event=lambda k, d: events.append((k, d))))
    assert (doc["source"], doc["answer"], doc["model"], doc["live"], doc["validated"]) == (
        "cache", GOOD, "muse-wonder-1.0", False, True)
    assert doc["fallback_reason"].startswith("live calls are off") and doc["spend"]["usd"] == 0
    assert doc["tool_calls"] == cache.doc["tool_calls"] and doc["ui_actions"] == cache.doc["ui_actions"]
    assert [k for k, _ in events] == ["tool_call", "tool_call", "ui_action", "tool_call", "ui_action"]


def test_r13_a_take_with_many_faults_gives_a_document_the_schema_takes():
    from test_ask_validator import many_faults
    doc = valid(agent.ask_run("What went wrong?", many_faults(120)))
    assert doc["source"] == "measured_facts" and len(doc["answer"]) <= 4000 and doc["tool_calls"][0]["by"] == "part5"


def test_ac_ask_09_another_question_or_another_take_gets_the_measured_facts(cache):
    assert agent.ask_run("What is my score?", golden_take())["source"] == "measured_facts"
    other = agent.ask_take(dict(ANALYSIS, faults=ANALYSIS["faults"][:1]), copy.deepcopy(REPLAY))
    assert agent.ask_run(QUESTION, other)["source"] == "measured_facts"


def test_ac_ask_09_a_cached_answer_that_no_longer_passes_the_validator_is_not_used(cache):
    cache.path.write_text(json.dumps(dict(cache.doc, answer="It is 99.9 degrees.")))
    assert agent.ask_run(QUESTION, golden_take())["source"] == "measured_facts"


def test_r1_a_cached_answer_whose_arguments_fail_the_word_guard_is_not_used(cache):
    calls_ = copy.deepcopy(cache.doc["tool_calls"])
    calls_[1]["arguments"]["note"] = "see www.example.com"
    cache.path.write_text(json.dumps(dict(cache.doc, tool_calls=calls_)))
    assert agent.ask_run(QUESTION, golden_take())["source"] == "measured_facts"


def test_ac_ask_09_a_failed_live_call_on_the_demo_question_gives_the_cache_too(cache, served, monkeypatch):
    monkeypatch.setenv("META_LIVE", "1")
    served.fakes.append(Scripted(meta_api.OpinionError("HTTP 503 on responses"), status=503))
    doc = valid(agent.ask_run(QUESTION, golden_take()))
    assert (doc["source"], doc["fallback_reason"], doc["live"]) == ("cache", "HTTP 503 on responses", True)
    assert doc["tool_calls"] == cache.doc["tool_calls"] and doc["spend"]["calls"] == 0   # the failed call is no spend


def test_r4_a_call_that_fails_after_tool_calls_keeps_them_before_the_cache_and_the_stream_agrees(cache, served, meta,
                                                                                               monkeypatch):
    """R4 of the 1.14.0 review: one rule. The calls already made are kept, the cache's follow; live and spend are what
    this exchange did; the stream's events are the document's lists."""
    monkeypatch.setenv("META_LIVE", "1")
    served.fakes.append(Scripted(calls(("get_faults", {}), ("seek", {"t": 0.5})),
                                 meta_api.OpinionError("timeout on responses"), status=None))
    events = []
    doc = valid(agent.ask_run(QUESTION, golden_take(), on_event=lambda k, d: events.append((k, d))))
    assert (doc["source"], doc["answer"], doc["validated"], doc["fallback_reason"]) == (
        "cache", GOOD, True, "timeout on responses")
    assert doc["tool_calls"][:2] == [
        {"name": "get_faults", "arguments": {}, "ok": True, "result": doc["tool_calls"][0]["result"]},
        {"name": "seek", "arguments": {"t": 0.5}, "ok": True, "result": {"type": "seek", "t": 0.5, "limb": None}}]
    assert doc["tool_calls"][2:] == cache.doc["tool_calls"]
    assert doc["ui_actions"] == [{"type": "seek", "t": 0.5, "limb": None}, *cache.doc["ui_actions"]]
    assert [d for k, d in events if k == "tool_call"] == doc["tool_calls"]
    assert [d for k, d in events if k == "ui_action"] == doc["ui_actions"]
    assert (doc["live"], doc["model"], doc["spend"]["calls"]) == (True, "muse-wonder-1.0", 1)
    assert doc["spend"]["usd"] == ledger_lines(meta)[0]["usd"] > 0   # the answered call as the ledger recorded it


def test_r4_calls_that_would_not_fit_beside_the_cache_give_the_measured_facts(cache, served, monkeypatch):
    monkeypatch.setenv("META_LIVE", "1")
    many = [("seek", {"t": 0.1 * i}) for i in range(agent.MAX_LISTED_CALLS - len(cache.doc["tool_calls"]) + 1)]
    served.fakes.append(Scripted(calls(*many), meta_api.OpinionError("HTTP 503 on responses"), status=503))
    doc = valid(agent.ask_run(QUESTION, golden_take()))
    assert (doc["source"], doc["fallback_reason"]) == ("measured_facts", "HTTP 503 on responses")
    assert [c["name"] for c in doc["tool_calls"]] == ["seek"] * len(many) + ["get_faults"]
    assert len(doc["tool_calls"]) <= agent.MAX_LISTED_CALLS


def test_ac_ask_09_a_replaced_live_answer_never_turns_into_the_cache(cache, served, monkeypatch):
    monkeypatch.setenv("META_LIVE", "1")
    served.fakes.append(Scripted(calls(("get_faults", {})), text("It is 99.9 degrees.")))
    assert agent.ask_run(QUESTION, golden_take())["source"] == "measured_facts"


# ---- the shipped demo answer: one live exchange on the seed 5 Take 03 -----------------------------------------------
EXAMPLE = json.loads(agent.ASK_EXAMPLE.read_text())
TAKE_03 = {"expected": {"sample": "exercise"}, "follower": {"sample": "exercise_front_good_03_foot_out-right"}}


@pytest.fixture(scope="module")
def take_03():
    """Take 03's analysis and replay as Part 5's page gets them (`POST api/analyse` with the two samples)."""
    status, _, body = api.handle("POST", "/api/analyse", json.dumps(TAKE_03).encode(), base_path="/")
    assert status == 200
    doc = json.loads(body)
    return doc["analysis"], doc["replay"]


def test_the_shipped_example_is_a_validated_live_answer_through_the_product_path():
    doc = valid(EXAMPLE)
    assert (doc["source"], doc["model"], doc["live"], doc["validated"], doc["fallback_reason"]) == (
        "model", "muse-wonder-1.0", True, True, None)
    assert doc["spend"]["ledger_purpose"] == "ask" and doc["spend"]["calls"] >= 2 and not doc["spend"]["estimated"]
    assert all(c["ok"] and "by" not in c for c in doc["tool_calls"]) and doc["ui_actions"]


def test_ac_ask_01_the_example_tool_results_equal_the_tools_run_again_on_take_03(take_03):
    take = agent.ask_take(*copy.deepcopy(take_03))
    assert take.sha256() == EXAMPLE["take_sha256"]
    for record in EXAMPLE["tool_calls"]:
        again, _ = tools.run_tool(take, record["name"], json.dumps(record["arguments"]))
        assert again == record


def test_ac_ask_09_the_demo_question_on_take_03_gives_the_shipped_answer_with_no_call(take_03):
    doc = valid(agent.ask_run(EXAMPLE["question"], agent.ask_take(*copy.deepcopy(take_03))))
    assert (doc["source"], doc["answer"], doc["ui_actions"]) == ("cache", EXAMPLE["answer"], EXAMPLE["ui_actions"])
    assert (doc["live"], doc["spend"]["usd"]) == (False, 0)


# ---- TICKET-100: the page's own copy of the take reaches the cache ------------------------------------------------------
def as_json_stringify(value):
    """`value` as the page's JSON.stringify writes it: a float with no fraction as an integer (`6` for `6.0`), `-0.0` as
    `0`. Every other number, text and null is written as it was."""
    if isinstance(value, dict):
        return {key: as_json_stringify(item) for key, item in value.items()}
    if isinstance(value, list):
        return [as_json_stringify(item) for item in value]
    return int(value) if isinstance(value, float) and value.is_integer() else value


def page_body(analysis, replay_doc):
    return {"question": EXAMPLE["question"], "analysis": analysis, "replay": replay_doc, "stream": False}


@pytest.fixture
def offline(monkeypatch):
    for name in ("META_LIVE", "SIMON5_LIVE"):
        monkeypatch.delenv(name, raising=False)


def test_ticket_100_a_page_written_copy_of_take_03_digests_as_the_python_written_one(take_03):
    analysis, replay_doc = take_03
    page = (as_json_stringify(analysis), as_json_stringify(replay_doc))
    assert json.dumps(page[0]) != json.dumps(analysis) and json.dumps(page[1]) != json.dumps(replay_doc)   # it differs
    assert agent.ask_take(*copy.deepcopy(page)).sha256() == agent.ask_take(*copy.deepcopy(take_03)).sha256()
    assert agent.ask_take(*copy.deepcopy(page)).sha256() == EXAMPLE["take_sha256"]


def test_ticket_100_the_demo_question_posted_as_the_page_writes_it_gets_the_cached_answer(take_03, offline):
    status, _, raw = post(page_body(*map(as_json_stringify, take_03)))
    doc = valid(json.loads(raw))
    assert status == 200 and (doc["source"], doc["answer"], doc["model"]) == ("cache", EXAMPLE["answer"], "muse-wonder-1.0")
    assert (doc["live"], doc["spend"]["usd"], doc["take_sha256"]) == (False, 0, EXAMPLE["take_sha256"])
    assert doc["ui_actions"] == EXAMPLE["ui_actions"]
    assert doc["fallback_reason"] == meta_api.unavailable(False)   # "no key" or "live calls are off", by the key file


def test_ticket_100_another_question_on_the_page_written_copy_still_gets_the_measured_facts(take_03, offline):
    body = page_body(*map(as_json_stringify, take_03))
    status, _, raw = post({**body, "question": "Is my left elbow too high?"})
    assert status == 200 and valid(json.loads(raw))["source"] == "measured_facts"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_ticket_100_a_real_javascript_round_trip_of_take_03_reaches_the_cache(take_03, offline):
    """The page's own serialiser: Node's JSON.parse then JSON.stringify over the Python-written files."""
    script = "let s='';process.stdin.on('data',d=>{s+=d}).on('end',()=>process.stdout.write(JSON.stringify(JSON.parse(s))))"
    sent = json.dumps(page_body(*take_03))
    done = subprocess.run(["node", "-e", script], input=sent, capture_output=True, text=True, check=True, timeout=60)
    assert done.stdout != sent and json.loads(done.stdout) == json.loads(sent)   # other text, the same values
    status, _, raw = post(done.stdout.encode())
    doc = valid(json.loads(raw))
    assert status == 200 and (doc["source"], doc["take_sha256"]) == ("cache", EXAMPLE["take_sha256"])


@pytest.mark.parametrize("field", ["magnitude_deg", "peak_deg", "threshold_deg", "at_s"])
def test_r1_an_int_too_large_for_a_double_is_a_200_not_a_500(monkeypatch, field):
    """R1 of the 1.14.1 review: `canonical` took `float()` of every number, which raises OverflowError for an int of 309
    or more digits, so a 401-digit magnitude answered 500 where 8aac47e answered 200 measured_facts."""
    monkeypatch.delenv("META_LIVE", raising=False)   # no model call can be made: the answer is the measured facts
    analysis = copy.deepcopy(ANALYSIS)
    analysis["faults"][0][field] = 10 ** 400
    assert len(str(analysis["faults"][0][field])) == 401
    status, _, body = post(request(analysis=analysis))
    assert status == 200 and json.loads(body)["source"] == "measured_facts"
    assert tools.canonical({"n": 10 ** 400, "m": 3}) == {"n": 10 ** 400, "m": 3.0}
