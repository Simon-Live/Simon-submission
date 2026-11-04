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

Cues (TICKET-080, docs/specs/language-cues.md): for a listed language other than English `phrase_cues` asks the same
backend, in one more batched call once the insights are final, to write every cue and "why" of the document in that
language. Each is held to `lang.check_cue` and keeps its English text, with the reason, when it fails. The English fields
do not change: the result is the additive record `phrasing.cues[]` ({path, text, lang, backend, model, fallback_reason})
and `phrasing.native_review` (false until a native reader has checked the language, `lang.NATIVE_REVIEWED`).

`select_backend` is the one place that decides the default: `muse-spark` in live mode, `template`
otherwise, and an explicit choice always wins.

Reasons: when a backend cannot run at all the reason is plain ("no key", "live calls are off ...",
"ollama not found", "rate limited", "time budget spent"). When it ran and a fault failed the reason
is "<backend>: <what>". A reason never holds a key, a path's contents or a model's text.
"""
import os
import time
from concurrent.futures import ThreadPoolExecutor

from ..cues import cue_fields
from . import lang as languages
from . import local_llm, muse_spark, prompt, template, variety
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
CUES_TIMEOUT_S = 20.0   # the cue call's own timeout, on top of the fault lines' budget (the API allows an analysis 60 s)
NO_TRANSLATION = "no translation returned"


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


def _kept(field, reason):
    """The `phrasing.cues[]` entry of a field that keeps its English text, with the `reason` it does."""
    return {"path": field.path, "text": field.text, "lang": EN, "backend": TEMPLATE, "model": None,
            "fallback_reason": reason}


def _translated(module, fields, language, timeout_s, client):
    """The entries for `fields` from one batched call to `module`. A failed call or an unreadable answer keeps every
    field in English with the reason (`rate limited` plain, as for a fault); otherwise each distinct English text is
    held to `lang.check_cue` on its own, and a text shared by several paths is written to each."""
    texts = list(dict.fromkeys((f.role, f.text) for f in fields))
    try:
        reply = module.complete(prompt.cue_messages(texts, language), timeout_s=timeout_s, client=client)
        found = languages.read_items(reply, len(texts))
    except BackendError as error:
        reason = error.reason if error.reason == "rate limited" else f"{module.NAME}: {error.reason}"
        return [_kept(f, reason) for f in fields]
    except ValueError as error:   # `lang.read_items`: not the JSON asked for
        return [_kept(f, f"{module.NAME}: {error}") for f in fields]
    verdict = {}   # (role, English text) -> (the model's text, None) or (None, why it was not taken)
    for number, (role, source) in enumerate(texts):
        said = found.get(number)
        problem = NO_TRANSLATION if said is None else languages.check_cue(role, source, said, language)
        verdict[(role, source)] = (None, f"{module.NAME}: {problem}") if problem else (said, None)
    out = []
    for f in fields:
        said, reason = verdict[(f.role, f.text)]
        out.append(_kept(f, reason) if reason else
                   {"path": f.path, "text": said, "lang": language, "backend": module.NAME, "model": module.model(),
                    "fallback_reason": None})
    return out


def phrase_cues(analysis, backend=TEMPLATE, *, timeout_s=CUES_TIMEOUT_S, client=None, live=False, lang=None):
    """`analysis` with `phrasing.cues` and `phrasing.native_review` set, for a listed language other than English; an
    English request (or an unlisted tag) returns it untouched.

    Call it last, when the insights are final: one entry for each field of `cues.cue_fields(analysis)`. A backend that
    cannot run (the template, no key, live calls off) makes no call and keeps every field in English with its reason; a
    document with no cue field makes none either (`cues` is `[]`). Takes the options of `phrase`; raises ValueError for an
    unknown backend."""
    if backend not in BACKENDS:
        raise ValueError(f"unknown phrasing backend {backend!r}; use one of {', '.join(BACKENDS)}")
    language, _ = languages.resolve(lang)
    if language == EN:
        return analysis
    module = BACKENDS[backend]
    fields = cue_fields(analysis)
    reason = None if backend == TEMPLATE else module.unavailable(live)
    if backend == TEMPLATE or reason:
        entries = [_kept(f, reason or ENGLISH_ONLY) for f in fields]
    elif not fields:
        entries = []
    else:
        timeout_s = local_llm.call_timeout(timeout_s) if backend == local_llm.NAME else timeout_s
        entries = _translated(module, fields, language, timeout_s, client)
    analysis["phrasing"]["cues"] = entries
    analysis["phrasing"]["native_review"] = languages.native_review(language)
    return analysis


def phrase_fault(fault, backend=muse_spark.NAME, **options):
    """`{text, model, backend, fallback_reason, lang}` for one fault dict (measured fields, `at_s`,
    `lateral`, `text_timed`). Takes the same options as `phrase`."""
    lines, record = phrase([fault], backend, **options)
    entry = record["faults"][0]
    return {"text": lines[0], "model": entry["model"], "backend": entry["backend"],
            "fallback_reason": entry["fallback_reason"], "lang": entry["lang"]}
