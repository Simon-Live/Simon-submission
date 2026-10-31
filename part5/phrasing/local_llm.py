"""The `local-llm` backend (Ollama on this machine), and the chat plumbing `muse_spark` reuses.

ADR-0005. Ollama serves the OpenAI-compatible chat completions API, the same protocol Baseten
speaks, so one request builder, one client contract and one failure mapping serve both backends.
The backend runs only when the `ollama` binary is on PATH and `PART5_OLLAMA_MODEL` names a model;
any failure raises `BackendError` and the registry falls back to the template line for that fault.

Nothing here reads a key or logs anything. Reasons are built from status codes and exception class
names, never from an exception's text, so a secret cannot ride along in one.
"""
import json
import os
import shutil
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass

from ..measures import ALL_SPECS
from .prompt import timed_messages

NAME = "local-llm"
URL = "http://127.0.0.1:11434/v1/chat/completions"
MODEL_ENV = "PART5_OLLAMA_MODEL"
MAX_TOKENS = 256

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


def messages(fault):
    if fault.get("at_s") is not None:  # a timed fault, ADR-0008
        return timed_messages(fault)
    return [{"role": "system", "content": SYSTEM + _measure_meaning(fault["measure"])},
            {"role": "user", "content": json.dumps(fault_record(fault), sort_keys=True)}]


def chat_request(url, model, fault, *, headers, max_tokens, timeout_s, options=None):
    """A chat completions request for one fault, as a plain dict a client turns into an HTTP call."""
    body = {"model": model, "max_tokens": max_tokens, "messages": messages(fault)}
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


def line(fault, *, timeout_s, client):
    """One line for one fault from the local model; raises BackendError on any failure."""
    request = chat_request(URL, model(), fault, headers={}, max_tokens=MAX_TOKENS,
                           timeout_s=timeout_s, options={"temperature": 0})
    outcome = send(client or urllib_client, request)
    if outcome.error:
        raise outcome.error
    return content(outcome.body)
