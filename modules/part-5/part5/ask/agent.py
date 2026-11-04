"""Ask this take: the agent (TICKET-081, docs/specs/ask-this-take.md, ADR-0022).

`ask_run(question, take, ...)` returns the `simon.ask.v1` document for one question about one take: the muse-wonder-1.0 loop
over the take's tools (`tools.run_tool`), its budget (ASM-016) through the one spend path (`meta_api.call`), and an answer
that passed `guard.check_answer`, or the measured facts (`guard.measured_facts`), or the cached demo answer. `ask_take`,
`ask_question`, `ask_request_from` and `ask_files` read what a caller sends.

Moved out of `part5/opinion/__init__.py` unchanged in the 1.14.0 round. The take and its tools came out of `part5/replay.py`
into `part5/ask/tools.py` with it, so they are imported at the top: nothing they import loads this package. The event stream
(`sse`, `ask_events`) stays in `part5/opinion/__init__.py`: the write gate refused `part5/ask/stream.py`, which no spec on
main named.
"""
import json
import logging
import math
from pathlib import Path

from ..io import JOINTS
from ..mask import validate_mask_block
from ..opinion import CUT_OFF, _read_json, guard, meta_api, prompt, unreadable_reason   # `_read_json`: the history opinion's file reader
from ..opinion.meta_api import OpinionError
from ..replay import FORMAT as REPLAY_FORMAT
from . import tools

ASK_FORMAT, ASK_SCHEMA_VERSION = "simon.ask.v1", "1.0.0"
ASK_PURPOSE = "ask"   # the ledger's `purpose`
ASK_TIMEOUT_S = 50    # the API route's timeout for each HTTP call, as for the history opinion; the command uses 300 s
MAX_TURNS, MAX_TOOL_CALLS = 4, 8
MAX_LISTED_CALLS = MAX_TOOL_CALLS + 1   # `tool_calls` in the schema: the model's 8 and Part 5's own `get_faults`
TOOL_LIMIT = "tool call limit reached"
TURN_LIMIT = "no answer within the turn limit"
CHARS_PER_TOKEN = 3   # ASM-016: what the count endpoint is not asked about is estimated at one token per 3 characters
MAX_ASK_FILE_BYTES = 32 * 1024 * 1024
ASK_EXAMPLE = Path(__file__).resolve().parents[2] / "fixtures" / "output" / "ask.example.json"   # the demo's cache
ask_log = logging.getLogger("part5.ask")   # the same logger as the event stream's (`opinion.ask_events`)


class AskError(ValueError):
    """A request or a file Ask this take cannot read. `field` names the request field at fault for the API."""

    def __init__(self, message, field="body"):
        super().__init__(message)
        self.field = field


class AskUsageError(AskError):
    """The question was asked wrongly: the CLI exits 2 for it, 1 for any other AskError."""


def ask_question(question):
    """The question without its outer blanks; AskUsageError unless it is 1 to `prompt.MAX_QUESTION_CHARS` characters."""
    text = question.strip() if isinstance(question, str) else ""
    if not text:
        raise AskUsageError("question: give the question as text", "question")
    if len(text) > prompt.MAX_QUESTION_CHARS:
        raise AskUsageError(f"question: {len(text)} characters, the limit is {prompt.MAX_QUESTION_CHARS}", "question")
    return text


def _point_ok(point):
    return point is None or (isinstance(point, list) and len(point) == 3
                             and all(prompt._number(v) is not None for v in point))


def _replay_problem(doc):
    """None when `doc` is a replay the tools can read: what `make check-5-contract` checks (`contract.replay_problems`)
    after the types it leaves to the schema, so the server needs no jsonschema."""
    from ..contract import replay_problems   # imported at the first use, as before the move
    if not isinstance(doc, dict) or doc.get("format") != REPLAY_FORMAT:
        return f"not a replay (format is not {REPLAY_FORMAT})"
    if doc.get("joints") != JOINTS:
        return "joints are not the 17 canonical joints in order"
    for key in ("expected", "follower"):
        frames = doc.get(key)
        if not (isinstance(frames, list) and frames and all(
                isinstance(f, list) and len(f) == len(JOINTS) and all(_point_ok(p) for p in f) for f in frames)):
            return f"{key} is not a list of frames of 17 points [x, y, z] or null"
    for key in ("expected_t", "follower_t"):
        if not isinstance(doc.get(key), list) or any(prompt._number(t) is None for t in doc[key]):
            return f"{key} is not a list of times"
    if not isinstance(doc.get("exp_to_fol"), list) or any(isinstance(i, bool) or not isinstance(i, int)
                                                          for i in doc["exp_to_fol"]):
        return "exp_to_fol is not a list of frame indexes"
    found = replay_problems(doc)
    return f"{found[0][0]} {found[0][1]}" if found else None


def _refuse_analysis(message):
    raise AskError(f"analysis: {message}", "analysis")


def ask_take(analysis, replay):
    """The `tools.Take` of an analysis and the replay written with it; AskError naming the document at fault. A declared
    body mask (`body_mask`, ADR-0023) must pass the analysis's own check, since the tools refuse what it lists."""
    problem = prompt.analysis_problem(analysis)
    if problem or not all(isinstance(f, dict) for f in analysis["faults"]):
        _refuse_analysis(problem or "a fault is not an object")
    if analysis.get("body_mask") is not None:
        validate_mask_block(analysis, _refuse_analysis)
    problem = _replay_problem(replay)
    if problem:
        raise AskError(f"replay: {problem}", "replay")
    size = len(replay["follower"])
    for fault in analysis["faults"]:
        frames = fault.get("follower_frames")
        if isinstance(frames, list) and any(isinstance(i, bool) or not isinstance(i, int) or not 0 <= i < size
                                            for i in frames):
            raise AskError("replay: not the replay of this analysis (a fault's follower frames lie outside it)",
                           "replay")
    return tools.Take(analysis, replay)


def ask_request_from(body):
    """`(question, take, stream)` from the bytes of a `POST api/ask` body; AskError names the field at fault."""
    try:
        request = tools.strict_json(body)
    except (ValueError, RecursionError):
        raise AskError("body: not JSON") from None
    if not isinstance(request, dict):
        raise AskError("body: expected a JSON object with 'question', 'analysis' and 'replay'")
    stream = request.get("stream", False)
    if not isinstance(stream, bool):
        raise AskError("stream: must be true or false", "stream")
    question = ask_question(request.get("question"))
    return question, ask_take(request.get("analysis"), request.get("replay")), stream


def ask_files(analysis_path, replay_path):
    """The take of the two files; AskError naming the file at fault."""
    def read(path):
        return _read_json(path, AskError, MAX_ASK_FILE_BYTES, tools.strict_json)

    analysis, replay = read(analysis_path), read(replay_path)
    try:
        return ask_take(analysis, replay)
    except AskError as error:
        path = analysis_path if error.field == "analysis" else replay_path
        raise AskError(f"{path}: {str(error).partition(': ')[2]}", error.field) from None


class _Exchange:
    """What one question has done so far: its tool calls and UI actions (each sent to `emit` as it happens), the usage
    of each answered model call, and the number of calls sent."""

    def __init__(self, emit):
        self.emit, self.tool_calls, self.ui_actions, self.usages, self.sent = emit, [], [], [], 0

    def record(self, record, action=None):
        self.tool_calls.append(record)
        self.emit("tool_call", record)
        if action:
            self.ui_actions.append(action)
            self.emit("ui_action", action)


def _tokens(value):
    return math.ceil(len(json.dumps(value, separators=(",", ":"))) / CHARS_PER_TOKEN)


class _Budget:
    """The client as `meta_api.call` sees it for one question (ASM-016). The first turn's input is counted by the API;
    a later turn's is estimated (its input answers calls the count endpoint has not seen) and adds the context it
    carries, the previous turn's input and output. Both add the tool declarations. A later turn that would take what
    the question has spent past the per-call ceiling is refused before it is sent; `meta_api.call` refuses a single
    turn over it, and the cap."""

    def __init__(self, client, exchange):
        self.client, self.exchange, self.carried = client, exchange, 0

    @property
    def last_status(self):
        return getattr(self.client, "last_status", None)

    def count(self, body):
        tokens = self.carried + _tokens(body["input"]) if "previous_response_id" in body else self.client.count(body)
        tokens += _tokens(body["tools"]) if body.get("tools") else 0
        spent, ceiling = sum(usage["usd"] for usage in self.exchange.usages), meta_api.call_ceiling()
        estimate = meta_api.price(tokens, body["max_output_tokens"], rates=prompt.ASK_RATES)
        if spent and spent + estimate > ceiling:
            raise OpinionError(f"estimated ${spent + estimate:.2f} for this question over the per-call limit of "
                               f"${ceiling:.2f}")
        return tokens

    def respond(self, body):
        self.exchange.sent += 1
        return self.client.respond(body)


def _limbs():
    return (*tools.LIMBS, *JOINTS)


def _answer_call(take, call, exchange):
    """Run one of the model's tool calls (`meta_api.function_calls`) and return its `function_call_output` item. A call
    of no tool, or past `MAX_TOOL_CALLS`, is answered with an error and not listed."""
    if call["name"] not in tools.TOOLS:
        result = {"error": f"no tool of that name; the tools are {', '.join(tools.TOOLS)}"}
    elif len(exchange.tool_calls) >= MAX_TOOL_CALLS:
        result = {"error": TOOL_LIMIT}
    else:
        record, action = tools.run_tool(take, call["name"], call["arguments"])
        exchange.record(record, action)
        result = record["result"]
    return {"type": "function_call_output", "call_id": call["call_id"], "output": json.dumps(result, allow_nan=False)}


def _converse(client, take, question, exchange):
    """`(text, usage)` of the model's final turn, `(None, None)` when the turn limit came first; OpinionError for a
    call that failed or was refused. The last allowed turn is sent without tools and says so (`prompt.ASK_LAST_TURN`,
    N4 of the 1.14.0 recheck), so the model must answer; a tool call on it still ends in the measured facts. The turn
    before it keeps its tools and asks for the seek and the spotlight (`prompt.ASK_SEEK_TURN`), since the last turn has
    no tool to move the page's replay with."""
    budget, joints, limbs = _Budget(client, exchange), tools.JOINTS_WITH_MEASURES, _limbs()
    declared = prompt.ask_tools(joints, limbs)
    body = prompt.ask_request(prompt.ask_opening(question, *take.span, joints, limbs), declared)
    for turn in range(1, MAX_TURNS + 1):
        payload, usage = meta_api.call(budget, body, ASK_PURPOSE, prompt.ASK_RATES,
                                       prompt_version=prompt.ASK_PROMPT_VERSION, turn=turn)
        exchange.usages.append(usage)
        budget.carried = usage["input_tokens"] + usage["output_tokens"]
        calls = meta_api.function_calls(payload)
        if not calls:
            return meta_api.output_text(payload), usage
        if turn == MAX_TURNS:
            break
        previous = meta_api.response_id(payload)
        outputs = [_answer_call(take, call, exchange) for call in calls]
        body = prompt.ask_request(outputs, declared, previous, last=turn + 1 == MAX_TURNS,
                                  seek=turn + 2 == MAX_TURNS)
    return None, None


def _same_question(cached, question):
    return isinstance(cached, str) and " ".join(cached.split()).casefold() == " ".join(question.split()).casefold()


def _cached(question, take):
    """The cached demo document (`ASK_EXAMPLE`) when `question` and `take` are its own and its answer still passes the
    validator against its own tool results, else None."""
    try:
        doc = json.loads(ASK_EXAMPLE.read_text())
    except (OSError, ValueError):
        return None
    if not (isinstance(doc, dict) and doc.get("format") == ASK_FORMAT and _same_question(doc.get("question"), question)
            and isinstance(doc.get("tool_calls"), list) and doc.get("take_sha256") == take.sha256()):
        return None
    if not all(isinstance(c, dict) and tools.arguments_shown(c.get("arguments")) for c in doc["tool_calls"]):
        return None   # the cache's arguments are held to the word guard as a live call's are (R1 of the 1.14.0 review)
    return doc if guard.check_answer(doc.get("answer"), doc["tool_calls"])[1] is None else None


def _ask_document(question, take, exchange, answer, source, reason, *, validated, replaced=()):
    """The document of the exchange. `spend` is what its answered calls cost as the ledger recorded them; `tool_calls`
    and `ui_actions` are the exchange's own, which are also the events the stream sent."""
    usages = exchange.usages
    spend = {"usd": round(sum(u["usd"] for u in usages), 6), "ledger_purpose": ASK_PURPOSE, "calls": len(usages),
             **{key: sum(u.get(key, 0) for u in usages) for key in ("input_tokens", "output_tokens", "cached_tokens")},
             "estimated": any(u.get("estimated", False) for u in usages)}
    return {"format": ASK_FORMAT, "schema_version": ASK_SCHEMA_VERSION, "question": question, "answer": answer,
            "source": source, "model": prompt.ASK_MODEL if exchange.sent or source == "cache" else None,
            "live": exchange.sent > 0, "validated": validated, "replaced_numbers": list(replaced),
            "fallback_reason": reason, "take_sha256": take.sha256(), "tool_calls": exchange.tool_calls,
            "ui_actions": exchange.ui_actions, "spend": spend}


def _fallback(question, take, exchange, reason, *, cache=False, replaced=()):
    """The cached demo answer (when `cache` and it fits) or the measured facts, with `reason`. With no fact among the
    exchange's results, Part 5 calls `get_faults` itself (`by: "part5"`).

    R4 of the 1.14.0 review, one rule for the cache: the tool calls and UI actions the exchange already made are kept, and
    the cache's own follow them, recorded and sent as events like any call, so the stream's events are the document's
    lists. `live` and `spend` stay what this exchange did. The cache is used only when both lists together fit
    `MAX_LISTED_CALLS`; otherwise the measured facts of the calls already made."""
    cached = _cached(question, take) if cache else None
    if cached is not None and len(exchange.tool_calls) + len(cached["tool_calls"]) <= MAX_LISTED_CALLS:
        for record in cached["tool_calls"]:   # replayed as calls, so a streaming page moves as it would have
            ui = record.get("ok") is True and record.get("name") in tools.UI_TOOLS
            exchange.record(record, dict(record["result"]) if ui else None)
        return _ask_document(question, take, exchange, cached["answer"], "cache", reason, validated=True)
    answer = guard.measured_facts(exchange.tool_calls)
    if answer is None:
        record, _ = tools.run_tool(take, "get_faults", "")
        exchange.record({**record, "by": "part5"})
        answer = guard.measured_facts(exchange.tool_calls)
    return _ask_document(question, take, exchange, answer, "measured_facts", reason, validated=False,
                         replaced=replaced)


def ask_run(question, take, *, live=False, client=None, timeout_s=meta_api.TIMEOUT_S, on_event=None):
    """The `simon.ask.v1` document for `question` about `take`; never raises for a call. `on_event(kind, data)` gets
    each tool call (`tool_call`) and UI action (`ui_action`) as it happens. No key, live mode off and a failed call
    give the cached demo answer when it fits, else the measured facts; an answer that fails `guard.check_answer` is
    replaced by the measured facts and the replacement is logged (numbers and reason only, never the model's text)."""
    exchange = _Exchange(on_event or (lambda kind, data: None))
    reason = meta_api.unavailable(live)
    if reason:
        return _fallback(question, take, exchange, reason, cache=True)
    try:
        client = client or meta_api.HttpClient(meta_api.read_key(), timeout_s)
        meta_api.preflight()
        text, usage = _converse(client, take, question, exchange)
    except OpinionError as error:
        return _fallback(question, take, exchange, error.reason, cache=True)
    if text is None:
        return _fallback(question, take, exchange, TURN_LIMIT)
    answer, problem, missing = guard.check_answer(text, exchange.tool_calls)
    if problem == guard.NO_ANSWER and unreadable_reason(usage, prompt.ASK_MAX_OUTPUT_TOKENS) == CUT_OFF:
        problem = CUT_OFF
    if problem:
        ask_log.warning("ask: the model's answer was replaced by the measured facts (%s)%s", problem,
                        f"; numbers in no tool result: {', '.join(missing)}" if missing else "")
        return _fallback(question, take, exchange, problem, replaced=missing)
    return _ask_document(question, take, exchange, answer, "model", None, validated=True)
