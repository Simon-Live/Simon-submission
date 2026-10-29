"""Coaching phrasing registry (ADR-0005): `template`, `local-llm`, `muse-spark`.

`phrase(faults, backend)` returns one display line per fault, in fault order, and the `phrasing`
record for `analysis.json`. The template backend returns each fault's `text`. A language-model
backend is asked for one line per fault, and that line must pass the word test
(`template.line_problem`: same body part and side, the direction's meaning, no added number, no
other body part). A backend that is unavailable, fails or fails the word test falls back to the
fault's `text`, for that fault alone, and the record says why.

Reasons: when a backend cannot run at all the reason is plain ("no key", "live calls are off ...",
"ollama not found"). When it ran and a fault failed the reason is "<backend>: <what>". A reason
never holds a key, a path's contents or a model's text.
"""
from . import local_llm, muse_spark, template
from .local_llm import BackendError

TEMPLATE = template.NAME
BACKENDS = {TEMPLATE: template, local_llm.NAME: local_llm, muse_spark.NAME: muse_spark}
NO_FAULTS = "no faults to phrase"


def _entry(backend, reason=None):
    return {"backend": backend, "fallback_reason": reason}


def _one(module, fault, timeout_s, client):
    """(line, per-fault record entry) for one fault from a language-model backend."""
    try:
        line = module.line(fault, timeout_s=timeout_s, client=client)
    except BackendError as error:
        return fault["text"], _entry(TEMPLATE, f"{module.NAME}: {error.reason}")
    problem = template.line_problem(fault, line)
    if problem:
        return fault["text"], _entry(TEMPLATE, f"{module.NAME}: {problem}")
    return line, _entry(module.NAME)


def _record(requested, module, entries, reason):
    ran = any(e["backend"] == requested for e in entries)
    backend = requested if ran else TEMPLATE
    first = next((e["fallback_reason"] for e in entries if e["fallback_reason"]), None)
    return {"requested": requested, "backend": backend,
            "model": module.model() if ran and requested != TEMPLATE else None,
            "fallback_reason": reason or first, "faults": entries}


def phrase(faults, backend=TEMPLATE, *, timeout_s=10, client=None):
    """(lines, record) for `faults`, dicts with at least `text` and the measured fields.

    `client` is the HTTP client for the model backends, a callable taking the request dict and
    returning an `HttpResult` or raising; tests inject one, production uses stdlib `urllib`.
    Raises ValueError for an unknown backend.
    """
    if backend not in BACKENDS:
        raise ValueError(f"unknown phrasing backend {backend!r}; use one of {', '.join(BACKENDS)}")
    faults = list(faults)
    module = BACKENDS[backend]
    reason = None if backend == TEMPLATE else module.unavailable() or (None if faults else NO_FAULTS)
    if backend == TEMPLATE or reason:
        lines = template.lines(faults)
        entries = [_entry(TEMPLATE, reason) for _ in faults]
        return lines, _record(backend, module, entries, reason)
    results = [_one(module, fault, timeout_s, client) for fault in faults]
    entries = [entry for _, entry in results]
    return [line for line, _ in results], _record(backend, module, entries, None)
