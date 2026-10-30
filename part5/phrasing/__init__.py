"""Coaching phrasing registry (ADR-0005, ADR-0008): `template`, `local-llm`, `muse-spark`.

`phrase(faults, backend)` returns one display line per fault, in fault order, and the `phrasing`
record for `analysis.json`. The template backend returns each fault's template line (`text_timed`
when the fault has it, else `text`). A language-model backend is asked for one line per fault, and
that line must pass the word test (`template.line_problem`: same body part and side, the
direction's meaning, no added number, no other body part). A fault that carries `at_s` is phrased
in timed mode (ADR-0008): the line must also say the time once, may name the fault's `lateral` as
a direction and a short list of landmarks. A backend that is unavailable, fails, is rate limited,
runs out of the analysis's time budget or fails the word test falls back to the template line for
that fault alone, and the record says why.

`select_backend` is the one place that decides the default: `muse-spark` in live mode, `template`
otherwise, and an explicit choice always wins.

Reasons: when a backend cannot run at all the reason is plain ("no key", "live calls are off ...",
"ollama not found", "rate limited", "time budget spent"). When it ran and a fault failed the reason
is "<backend>: <what>". A reason never holds a key, a path's contents or a model's text.
"""
import os
import time
from concurrent.futures import ThreadPoolExecutor

from . import local_llm, muse_spark, template
from .local_llm import BackendError

TEMPLATE = template.NAME
BACKENDS = {TEMPLATE: template, local_llm.NAME: local_llm, muse_spark.NAME: muse_spark}
NO_FAULTS = "no faults to phrase"
BUDGET_ENV, BUDGET_S = "PART5_PHRASING_BUDGET_S", 20.0  # phrasing time one analysis may spend
BUDGET_SPENT = "time budget spent"
CONCURRENCY_ENV, CONCURRENCY = "PART5_PHRASING_CONCURRENCY", 4  # live calls in flight at once


def select_backend(explicit=None, live=False):
    """(backend, selected_by) for a request: `flag` for an explicit backend, `live` for the live
    default (`muse-spark`), `default` for `template` (ADR-0008)."""
    if explicit:
        return explicit, "flag"
    if muse_spark.live_on(live):
        return muse_spark.NAME, "live"
    return TEMPLATE, "default"


def _entry(backend, reason=None, model=None):
    return {"backend": backend, "model": model, "fallback_reason": reason}


def _budget_s():
    try:
        return float(os.environ.get(BUDGET_ENV, BUDGET_S))
    except ValueError:
        return BUDGET_S


def _concurrency():
    try:
        return max(1, int(os.environ.get(CONCURRENCY_ENV, CONCURRENCY)))
    except ValueError:
        return CONCURRENCY


def _one(module, fault, timeout_s, client):
    """(line, per-fault record entry) for one fault from a language-model backend."""
    fallback = template.fallback_text(fault)
    try:
        line = module.line(fault, timeout_s=timeout_s, client=client)
    except BackendError as error:
        return fallback, _entry(TEMPLATE, f"{module.NAME}: {error.reason}" if error.reason != "rate limited"
                                else error.reason)
    problem = template.line_problem(fault, line, timed=fault.get("at_s") is not None)
    if problem:
        return fallback, _entry(TEMPLATE, f"{module.NAME}: {problem}")
    return line, _entry(module.NAME, model=module.model())


def _record(requested, module, entries, reason):
    ran = any(e["backend"] == requested for e in entries)
    backend = requested if ran else TEMPLATE
    first = next((e["fallback_reason"] for e in entries if e["fallback_reason"]), None)
    return {"requested": requested, "backend": backend,
            "model": module.model() if ran and requested != TEMPLATE else None,
            "fallback_reason": reason or first, "faults": entries}


def phrase(faults, backend=TEMPLATE, *, timeout_s=10, client=None, live=False, selected_by=None,
           budget_s=None, clock=time.monotonic):
    """(lines, record) for `faults`, dicts with at least `text` and the measured fields.

    `client` is the HTTP client for the model backends, a callable taking the request dict and
    returning an `HttpResult` or raising; tests inject one, production uses stdlib `urllib`.
    `live` is the `--live` flag. A model call starts only while the time spent so far plus
    `timeout_s` fits in `budget_s` (default `PART5_PHRASING_BUDGET_S`, 20 s). Model calls run on a thread pool
    (`PART5_PHRASING_CONCURRENCY`, default 4); lines keep fault order and each fault falls back alone. `selected_by`, when
    given, is copied into the record. Raises ValueError for an unknown backend.
    """
    if backend not in BACKENDS:
        raise ValueError(f"unknown phrasing backend {backend!r}; use one of {', '.join(BACKENDS)}")
    faults = list(faults)
    module = BACKENDS[backend]
    reason = None if backend == TEMPLATE else module.unavailable(live) or (None if faults else NO_FAULTS)
    if backend == TEMPLATE or reason:
        entries = [_entry(TEMPLATE, reason) for _ in faults]
        return template.lines(faults), _with(_record(backend, module, entries, reason), selected_by)
    budget = _budget_s() if budget_s is None else budget_s
    start = clock()

    def run(fault):  # the budget is checked when the call would start, not when it was queued
        if clock() - start + timeout_s > budget:
            return template.fallback_text(fault), _entry(TEMPLATE, BUDGET_SPENT)
        return _one(module, fault, timeout_s, client)

    with ThreadPoolExecutor(max_workers=min(_concurrency(), len(faults))) as pool:
        results = list(pool.map(run, faults))  # map keeps fault order
    entries = [entry for _, entry in results]
    return [line for line, _ in results], _with(_record(backend, module, entries, None), selected_by)


def _with(record, selected_by):
    if selected_by:
        record["selected_by"] = selected_by
    return record


def phrase_fault(fault, backend=muse_spark.NAME, **options):
    """`{text, model, backend, fallback_reason}` for one fault dict (measured fields, `at_s`,
    `lateral`, `text_timed`). Takes the same options as `phrase`."""
    lines, record = phrase([fault], backend, **options)
    entry = record["faults"][0]
    return {"text": lines[0], "model": entry["model"], "backend": entry["backend"],
            "fallback_reason": entry["fallback_reason"]}
