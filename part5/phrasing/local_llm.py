"""The `local-llm` backend (Ollama on this machine), and the chat plumbing `muse_spark` reuses.

ADR-0005. Ollama serves the OpenAI-compatible chat completions API, the same protocol Baseten
speaks, so one request builder, one client contract and one failure mapping serve both backends.
The backend runs only when the `ollama` binary is on PATH and `PART5_OLLAMA_MODEL` names a model;
any failure raises `BackendError` and the registry falls back to the template line for that fault.

Two optional settings for a slow local model (Part 7 TICKET-147, Muse Glimmer 30B), both unset by default:
`PART5_LOCAL_LLM_TIMEOUT_S` is the per-call timeout of this backend in seconds (a positive number; anything else
keeps the caller's timeout and logs why), and `PART5_LOCAL_LLM_THINK` set to "0" or "false" sends both
`reasoning_effort: "none"` and `think: false` in the request body. Ollama's OpenAI-compatible endpoint ignores
`think` (measured with muse-glimmer:30b: 996 characters of reasoning and empty content) and honours
`reasoning_effort: "none"` (2.1 s on the GPU); `think: false` stays for servers that read it.
`PART5_LOCAL_LLM_MAX_TOKENS` overrides the completion allowance (default 2048, as for Muse Spark: Glimmer still reasons
about 900 tokens on the timed prompt with `reasoning_effort: "none"`, so 256 cut every answer off). An answer cut off
at the allowance with no content falls back with the reason "cut off at max_tokens". The registry starts a call only while the time spent plus the timeout fits in
`PART5_PHRASING_BUDGET_S`, so a longer timeout needs a budget at least as long.

Nothing here reads a key or logs anything but a bad setting's value. Reasons are built from status codes and
exception class names, never from an exception's text, so a secret cannot ride along in one.
"""
import json
import logging
import math
import os
import shutil
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass

from ..measures import ALL_SPECS
from .lang import EN, reply_instruction
from .prompt import timed_messages

NAME = "local-llm"
TIMEOUT_ENV, THINK_ENV, MAX_TOKENS_ENV = "PART5_LOCAL_LLM_TIMEOUT_S", "PART5_LOCAL_LLM_THINK", "PART5_LOCAL_LLM_MAX_TOKENS"
CUT_OFF = "cut off at max_tokens"
THINK_OFF = ("0", "false")
_log = logging.getLogger(__name__)
URL = "http://127.0.0.1:11434/v1/chat/completions"
MODEL_ENV = "PART5_OLLAMA_MODEL"
MAX_TOKENS = 2048   # Part 7 TICKET-147: a thinking local model needs room to reason before the line (was 256)

# The only fields of a fault a model is shown (ADR-0005): the measured record, not the template text.
RECORD_KEYS = ("measure", "joint", "side", "direction", "magnitude_deg", "threshold_deg")

SYSTEM = (
    "You write one coaching line for a person copying a movement. The user message is one measured "
    "fault as JSON. Reply with only the line: a short lower case phrase without a full stop that "
    "names the body part, the side and how the person differs from the example.\n"
    "Rules:\n"
    "- Use the side in the record. \"left\" and \"right\" are the person's own sides. For \"both\" "
    "use the plural and name no single side. For \"center\" name no side.\n"
    "- \"more\" means the person's value is larger than the example's, \"less\" means smaller. "
    "Say it as a comparison with the example, describing where the body is, not giving orders.\n"
    "- Mention only the body part of the measure. No second fault, no numbers, no units.\n"
    "- Style examples: left foot too far out; elbows wider than the example; right knee not bent enough; "
    "left foot turned out more than the example; right ankle rolling in."
)


# Grammar rules for this backend only (Part 7, Muse Glimmer 30B): the local model wrote "Arms elbows wider than the
# example at 0.4 s", the record's `body_part` (arms) laid in front of the part `text_timed` names (elbows), with no verb.
# Muse Spark's prompt is unchanged; `template.line_problem` also rejects a line with two body-part nouns side by side.
# A rule here is a constraint, not a phrase to copy; the one example uses a record that is not the failing one.
GRAMMAR_PART_ONCE = "- Name the body part once. Two body-part nouns never stand side by side."
GRAMMAR_PART_ONCE_TIMED = (
    "- Name the body part once. `body_part` is only the group (for example arms or legs) and `text_timed` names the "
    "part itself (for example elbows or knees): write the part from `text_timed`, leave the group word out, so two "
    "body-part nouns never stand side by side.\n"
    "- Write a sentence with a verb: \"is\" after one part, \"are\" after two or more. Grammar example for another "
    "record: Your knees are not bent enough at <at_s> s.")


def grammar(fault):
    """The extra grammar rules this backend appends to its system text, for a timed fault or a plain one."""
    return "\n" + (GRAMMAR_PART_ONCE_TIMED if fault.get("at_s") is not None else GRAMMAR_PART_ONCE)


class BackendError(Exception):
    """A backend could not give a line. `reason` is short and never holds a secret."""

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class HttpResult:
    """What a client returns for a 2xx answer: the status and the decoded JSON body."""
    status: int
    body: dict


@dataclass(frozen=True)
class Outcome:
    """One request's result for its caller: a status if one came back, the body, or the failure."""
    status: "int | None"
    body: "dict | None"
    error: "BackendError | None"


def fault_record(fault):
    """The measured record sent to a model: the fields in RECORD_KEYS plus the frames."""
    record = {k: fault[k] for k in RECORD_KEYS}
    record["frames"] = list(fault["expected_frames"])
    return record


def _measure_meaning(measure):
    spec = ALL_SPECS.get(f"left_{measure}") or ALL_SPECS.get(measure)
    return f" The measure is: {spec.description}." if spec else ""


def messages(fault, shape=0, language=EN, extra_rules=""):
    """The chat messages for one fault: the timed prompt when it has `at_s` (ADR-0008), else the plain one. `shape`
    is the fault's position in its result and `language` the follower's (TICKET-045, TICKET-046); `extra_rules` is
    text appended to the system message (this backend's `grammar`; Muse Spark passes none)."""
    if fault.get("at_s") is not None:  # a timed fault, ADR-0008
        chat = timed_messages(fault, shape, language)
        chat[0]["content"] += extra_rules
        return chat
    reply = "" if language == EN else "\n" + reply_instruction(language)
    return [{"role": "system", "content": SYSTEM + _measure_meaning(fault["measure"]) + reply + extra_rules},
            {"role": "user", "content": json.dumps(fault_record(fault), sort_keys=True)}]


def chat_request(url, model, fault, *, headers, max_tokens, timeout_s, options=None, shape=0, language=EN,
                 extra_rules=""):
    """A chat completions request for one fault, as a plain dict a client turns into an HTTP call."""
    body = {"model": model, "max_tokens": max_tokens, "messages": messages(fault, shape, language, extra_rules)}
    body.update(options or {})
    return {"url": url, "headers": {"Content-Type": "application/json", **headers},
            "body": body, "timeout_s": timeout_s}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow a redirect: a request that carries an Authorization header goes to the one URL
    chosen for it and nowhere else. The 3xx answer surfaces as an `HTTPError`, reported as "HTTP 3xx"."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def no_redirect_opener(*handlers):
    return urllib.request.build_opener(NoRedirect, *handlers)


_OPENER = no_redirect_opener()


def urllib_client(request):
    """The production client: one POST with a timeout, no redirect followed. A non-2xx answer
    (a 3xx included) raises `HTTPError`."""
    http = urllib.request.Request(
        request["url"], data=json.dumps(request["body"]).encode(), method="POST",
        headers={"User-Agent": "part5-phrasing", **request["headers"]})
    with _OPENER.open(http, timeout=request["timeout_s"]) as response:
        return HttpResult(response.status, json.loads(response.read()))


def _failure(exc, timeout_s):
    """(status, reason) for an exception from a client, from its class and code only."""
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code, f"HTTP {exc.code}"
    reason = getattr(exc, "reason", None)
    if isinstance(exc, (TimeoutError, socket.timeout)) or isinstance(reason, (TimeoutError, socket.timeout)):
        return None, f"timeout after {timeout_s:g} s"
    if isinstance(exc, ValueError):
        return None, "unreadable response"
    return None, f"request failed ({type(exc).__name__})"


def send(client, request):
    """Call `client(request)` and never raise: the result is an `Outcome`."""
    try:
        result = client(request)
    except Exception as exc:  # any client failure becomes a reason, never a traceback
        status, reason = _failure(exc, request["timeout_s"])
        return Outcome(status, None, BackendError(reason))
    status, body = getattr(result, "status", None), getattr(result, "body", None)
    if not isinstance(status, int) or not isinstance(body, dict):
        return Outcome(None, None, BackendError("unreadable response"))
    if not 200 <= status < 300:
        return Outcome(status, body, BackendError(f"HTTP {status}"))
    return Outcome(status, body, None)


def content(body):
    """The reply text of a chat completions body, trimmed; empty content is a failure."""
    try:
        text = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise BackendError("unexpected response shape") from None
    if not isinstance(text, str) or not text.strip():
        raise BackendError("empty content")
    return text.strip().strip("\"'`").strip()


def model():
    return os.environ.get(MODEL_ENV, "").strip() or None


def unavailable(live=False):
    """None when Ollama can be tried, else the reason it cannot. `live` is ignored: it is local."""
    if shutil.which("ollama") is None:
        return "ollama not found"
    if model() is None:
        return f"no model ({MODEL_ENV} is not set)"
    return None


def call_timeout(default):
    """The per-call timeout in seconds: `PART5_LOCAL_LLM_TIMEOUT_S` when it is a positive finite number, else
    `default` (an unset variable silently, a bad value with a logged warning naming it)."""
    raw = os.environ.get(TIMEOUT_ENV)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError:
        value = None
    if value is None or not math.isfinite(value) or value <= 0:
        _log.warning("%s=%r is not a positive number of seconds; using the default %g s", TIMEOUT_ENV, raw, default)
        return default
    return value


def max_tokens():
    """The completion allowance: `PART5_LOCAL_LLM_MAX_TOKENS` when it is a positive integer, else MAX_TOKENS (an
    unset variable silently, a bad value with a logged warning naming it)."""
    raw = os.environ.get(MAX_TOKENS_ENV)
    if raw is None or not raw.strip():
        return MAX_TOKENS
    try:
        value = int(raw.strip())
    except ValueError:
        value = 0
    if value <= 0:
        _log.warning("%s=%r is not a positive whole number; using the default %d", MAX_TOKENS_ENV, raw, MAX_TOKENS)
        return MAX_TOKENS
    return value


def _cut_off(body):
    """True when the answer stopped at the allowance with no content (a reasoning model out of room)."""
    try:
        choice = body["choices"][0]
        text = choice["message"].get("content")
    except (KeyError, IndexError, TypeError, AttributeError):
        return False
    return choice.get("finish_reason") == "length" and not (isinstance(text, str) and text.strip())


def request_options():
    """The extra body fields: `temperature` 0, plus `reasoning_effort: "none"` and `think: false` when
    `PART5_LOCAL_LLM_THINK` is "0" or "false" (the first is the one Ollama's /v1 endpoint honours)."""
    options = {"temperature": 0}
    if os.environ.get(THINK_ENV, "").strip().lower() in THINK_OFF:
        options.update({"reasoning_effort": "none", "think": False})
    return options


def line(fault, *, timeout_s, client, shape=0, language=EN):
    """One reply for one fault from the local model; raises BackendError on any failure."""
    request = chat_request(URL, model(), fault, headers={}, max_tokens=max_tokens(), timeout_s=timeout_s,
                           options=request_options(), shape=shape, language=language, extra_rules=grammar(fault))
    outcome = send(client or urllib_client, request)
    if outcome.error:
        raise outcome.error
    if _cut_off(outcome.body):
        raise BackendError(CUT_OFF)
    return content(outcome.body)
