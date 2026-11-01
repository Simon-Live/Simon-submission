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

Language and variety (TICKET-045, TICKET-046, docs/specs/second-opinion.md): `lang` is a BCP 47 tag resolved by
`lang.resolve`; for a listed language other than English a model returns an English twin and the translated line,
the twin passes the word test and the translated line `lang.check_translated`. Each fault is asked for the sentence
shape of its position, and after phrasing a model line that repeats a non-fact phrase of an earlier line falls back
to its template line (`variety.repeats`). The record carries `lang` (and `lang_requested` when the tag was not
listed as given) and, per fault, the line shown (`text`) and its language (`lang`).

`select_backend` is the one place that decides the default: `muse-spark` in live mode, `template`
otherwise, and an explicit choice always wins.

Reasons: when a backend cannot run at all the reason is plain ("no key", "live calls are off ...",
"ollama not found", "rate limited", "time budget spent"). When it ran and a fault failed the reason
is "<backend>: <what>". A reason never holds a key, a path's contents or a model's text.
"""
import os
import time
from concurrent.futures import ThreadPoolExecutor

from . import lang as languages
from . import local_llm, muse_spark, template, variety
from .lang import EN
from .local_llm import BackendError

TEMPLATE = template.NAME
BACKENDS = {TEMPLATE: template, local_llm.NAME: local_llm, muse_spark.NAME: muse_spark}
NO_FAULTS = "no faults to phrase"
BUDGET_ENV, BUDGET_S = "PART5_PHRASING_BUDGET_S", 20.0  # phrasing time one analysis may spend
BUDGET_SPENT = "time budget spent"
CONCURRENCY_ENV, CONCURRENCY = "PART5_PHRASING_CONCURRENCY", 4  # live calls in flight at once
REPEATS = "repeats a phrase of another line"
ENGLISH_ONLY = "template lines are English only"


def select_backend(explicit=None, live=False):
    """(backend, selected_by) for a request: `flag` for an explicit backend, `live` for the live
    default (`muse-spark`), `default` for `template` (ADR-0008)."""
    if explicit:
        return explicit, "flag"
    if muse_spark.live_on(live):
        return muse_spark.NAME, "live"
    return TEMPLATE, "default"


def _entry(backend, reason=None, model=None, language=EN):
    """One fault's record entry; `phrase` adds the line shown as `text`."""
    return {"backend": backend, "model": model, "fallback_reason": reason, "lang": language}


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


def _one(module, fault, timeout_s, client, shape=0, language=EN):
    """(line, per-fault record entry, English line) for one fault from a language-model backend. The English line is
    the one the word test and the variety check read: the line itself in English, its twin in another language."""
    fallback = template.fallback_text(fault)
    timed = fault.get("at_s") is not None
    try:
        reply = module.line(fault, timeout_s=timeout_s, client=client, shape=shape, language=language)
        english, line = (reply, reply) if language == EN else languages.read_pair(reply)
    except BackendError as error:
        return fallback, _entry(TEMPLATE, f"{module.NAME}: {error.reason}" if error.reason != "rate limited"
                                else error.reason), fallback
    except ValueError:   # a language pair that is not one (lang.read_pair)
        return fallback, _entry(TEMPLATE, f"{module.NAME}: unreadable answer"), fallback
    problem = template.line_problem(fault, english, timed=timed) or (
        None if language == EN else languages.check_translated(fault, line, timed))
    if problem:
        return fallback, _entry(TEMPLATE, f"{module.NAME}: {problem}"), fallback
    return line, _entry(module.NAME, model=module.model(), language=language), english


def _record(requested, module, entries, reason, lines, language, asked):
    for entry, line in zip(entries, lines):
        entry["text"] = line
    ran = any(e["backend"] == requested for e in entries)
    backend = requested if ran else TEMPLATE
    first = next((e["fallback_reason"] for e in entries if e["fallback_reason"]), None)
    record = {"requested": requested, "backend": backend,
              "model": module.model() if ran and requested != TEMPLATE else None,
              "fallback_reason": reason or first, "lang": language}
    if asked is not None:
        record["lang_requested"] = asked
    record["faults"] = entries
    return record


def _vary(faults, results, module):
    """Send every model line that repeats a non-fact phrase of an earlier line back to its template line (AC-VA-02)."""
    english = [e for _, _, e in results]
    replaceable = {i for i, (_, entry, _) in enumerate(results) if entry["backend"] != TEMPLATE}
    fallbacks = [template.fallback_text(f) for f in faults]
    for i in variety.repeats(english, faults, replaceable, fallbacks):
        results[i] = (fallbacks[i], _entry(TEMPLATE, f"{module.NAME}: {REPEATS}"), fallbacks[i])
    return results


def phrase(faults, backend=TEMPLATE, *, timeout_s=10, client=None, live=False, selected_by=None,
           budget_s=None, clock=time.monotonic, lang=None):
    """(lines, record) for `faults`, dicts with at least `text` and the measured fields.

    `client` is the HTTP client for the model backends, a callable taking the request dict and
    returning an `HttpResult` or raising; tests inject one, production uses stdlib `urllib`.
    `live` is the `--live` flag. A model call starts only while the time spent so far plus
    `timeout_s` fits in `budget_s` (default `PART5_PHRASING_BUDGET_S`, 20 s). Model calls run on a thread pool
    (`PART5_PHRASING_CONCURRENCY`, default 4); lines keep fault order and each fault falls back alone. `selected_by`, when
    given, is copied into the record. `lang` is the follower's BCP 47 tag (None: English). Raises ValueError for an
    unknown backend.
    """
    if backend not in BACKENDS:
        raise ValueError(f"unknown phrasing backend {backend!r}; use one of {', '.join(BACKENDS)}")
    faults = list(faults)
    module = BACKENDS[backend]
    if backend == local_llm.NAME:   # PART5_LOCAL_LLM_TIMEOUT_S, for a slow local model (Part 7 TICKET-147)
        timeout_s = local_llm.call_timeout(timeout_s)
    language, asked = languages.resolve(lang)
    reason = None if backend == TEMPLATE else module.unavailable(live) or (None if faults else NO_FAULTS)
    if backend == TEMPLATE or reason:
        per_fault = reason or (ENGLISH_ONLY if language != EN else None)
        entries = [_entry(TEMPLATE, per_fault) for _ in faults]
        lines = template.lines(faults)
        return lines, _with(_record(backend, module, entries, reason, lines, language, asked), selected_by)
    budget = _budget_s() if budget_s is None else budget_s
    start = clock()

    def run(indexed):  # the budget is checked when the call would start, not when it was queued
        index, fault = indexed
        if clock() - start + timeout_s > budget:
            fallback = template.fallback_text(fault)
            return fallback, _entry(TEMPLATE, BUDGET_SPENT), fallback
        return _one(module, fault, timeout_s, client, shape=index, language=language)

    with ThreadPoolExecutor(max_workers=min(_concurrency(), len(faults))) as pool:
        results = list(pool.map(run, enumerate(faults)))  # map keeps fault order
    results = _vary(faults, results, module)
    lines = [line for line, _, _ in results]
    entries = [entry for _, entry, _ in results]
    return lines, _with(_record(backend, module, entries, None, lines, language, asked), selected_by)


def _with(record, selected_by):
    if selected_by:
        record["selected_by"] = selected_by
    return record


def phrase_fault(fault, backend=muse_spark.NAME, **options):
    """`{text, model, backend, fallback_reason, lang}` for one fault dict (measured fields, `at_s`,
    `lateral`, `text_timed`). Takes the same options as `phrase`."""
    lines, record = phrase([fault], backend, **options)
    entry = record["faults"][0]
    return {"text": lines[0], "model": entry["model"], "backend": entry["backend"],
            "fallback_reason": entry["fallback_reason"], "lang": entry["lang"]}
