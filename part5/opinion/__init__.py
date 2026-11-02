"""Muse Spark's second opinion on a take (TICKET-045, docs/specs/second-opinion.md, contract C1).

`attach(result, expected_video, follower_video, live=...)` returns the analysis with a top-level `second_opinion`:
one Muse Spark 1.3 call that watches the teacher's recording and the student's take with the measured faults, and
says per fault whether it agrees, with a one-line note, plus at most two observations of its own labelled
`model_opinion`. Only what passes `guard.read_answer` is kept.

The block is added after the score and insights are built and nothing reads it back, so a dispute never changes a
measured field (AC-SO-05). It is absent when no clip was given; `skipped` when no call was attempted (one clip
missing, no key, live off); `fallback` when a call was prepared or made and failed (the reason says why). A failure
never stops the analysis.

`history_run(series, ...)` is the second entry point (TICKET-072, docs/specs/history-opinion.md): one text-only call
over a series of analyses (`series_from_files`, `series_from_request`), returning a `simon.history_opinion.v1`
document of grounded observations. It shares the client, the spend guard and the ledger (`meta_api.call`).
"""
import json
import tempfile
from pathlib import Path

from ..phrasing import lang as phrasing_lang
from . import guard, meta_api, prompt
from .meta_api import BACKEND, MODEL, OpinionError
from .prompt import ContractError, HistoryError, UsageError   # re-exported: the CLI and the API catch them

BOTH_CLIPS = "both clips are needed"
HISTORY_FORMAT = "simon.history_opinion.v1"
HISTORY_PURPOSE = "history_opinion"   # the ledger's `purpose`: the feature that made the call
# The API route's timeout for its one HTTP call, below `api.ANALYSIS_TIMEOUT_S`. It bounds the call, not the route: the
# route does not run under `api._run_with_timeout`, and a call that waits for the ledger lock can wait up to
# `meta_api.LOCK_WAIT_S` (330 s) while another process's call holds it.
HISTORY_TIMEOUT_S = 50
NO_CITABLE = "no fault with a second to cite"
CUT_OFF = "answer cut off at the output limit"


def _block(status, reason=None, usage=None, **found):
    block = {"status": status, "reason": reason, "backend": BACKEND, "model": MODEL if status == "ok" else None,
             "lang": "en", "verdicts": found.get("verdicts", []), "observations": found.get("observations", [])}
    if found.get("rejected"):
        block["rejected"] = found["rejected"]
    if usage:
        block["usage"] = usage
    return block


def _duration(clip, follower_video):
    """The follower clip's span in seconds: the skeleton's last time, no longer than the video and what is sent."""
    spans = [float(clip.t[-1]) if clip is not None and len(clip.t) else None, meta_api.clip_seconds(follower_video),
             float(meta_api.CLIP_MAX_S)]
    return min(s for s in spans if s is not None)


def _ask(client, faults, clips, duration_s):
    """Check the limits and the total cap, upload both clips, count, ask; (answer text, usage). Files are deleted on
    every path.

    `meta_api.call` counts, checks the budget under the locked ledger, sends and records the call: the budget check
    and the call happen under the lock, so two processes cannot both pass the cap, and a call whose cost is not known
    (no answer from the API, a 5xx, an answer with no token counts) is recorded at its pre-call estimate."""
    ids = []
    try:
        meta_api.preflight()   # a bad limit or a spent cap refuses the call before any upload
        with tempfile.TemporaryDirectory(prefix="part5-opinion-") as tmp:
            for clip in clips:
                ids.append(client.upload(meta_api.prepare(clip, tmp)))
        payload, usage = meta_api.call(client, prompt.request(ids[0], ids[1], faults, duration_s))
        return meta_api.output_text(payload), usage
    finally:
        for file_id in ids:
            client.delete(file_id)


def run(analysis, follower_clip, expected_video, follower_video, *, live=False, client=None):
    """The `second_opinion` block for `analysis` (the faults it holds) on the two videos; never raises for a call."""
    if not (expected_video and follower_video):
        return _block("skipped", BOTH_CLIPS)
    reason = meta_api.unavailable(live)
    if reason:
        return _block("skipped", reason)
    for role, path in (("expected", expected_video), ("follower", follower_video)):
        if not Path(path).is_file():
            return _block("fallback", f"{role} clip not readable")
    duration_s = _duration(follower_clip, follower_video)
    usage = None
    try:
        client = client or meta_api.HttpClient(meta_api.read_key())
        text, usage = _ask(client, analysis["faults"], (expected_video, follower_video), duration_s)
        found = guard.read_answer(text, len(analysis["faults"]), duration_s, guard.supported(follower_clip))
    except OpinionError as error:
        return _block("fallback", error.reason)
    except OSError:   # a clip or the temp directory that cannot be read or written: the analysis is still written
        return _block("fallback", "clip could not be prepared")
    except ValueError:
        return _block("fallback", "unreadable answer", usage)
    return _block("ok", usage=usage, **found)


def attach(result, expected_video, follower_video, *, live=False, client=None):
    """`result.analysis` with `second_opinion` added and validated; the analysis unchanged when no clip was given."""
    from ..output import validate_analysis   # output imports guard, so the import waits for the call

    if not (expected_video or follower_video):
        return result.analysis
    block = run(result.analysis, result.follower, expected_video, follower_video, live=live, client=client)
    return validate_analysis(dict(result.analysis, second_opinion=block), source="<built analysis>")


# ---- the history opinion (TICKET-072, docs/specs/history-opinion.md) ----------------------------------------------
def _read_analysis(path):
    """The parsed JSON of the analysis file `path`; HistoryError naming the file when it cannot be had."""
    try:
        size = Path(path).stat().st_size
        text = Path(path).read_text() if size <= prompt.MAX_FILE_BYTES else None
    except (OSError, ValueError):
        raise HistoryError(f"{path}: cannot be read") from None
    if text is None:
        raise HistoryError(f"{path}: larger than {prompt.MAX_FILE_BYTES // 2**20} MiB")
    try:
        return json.loads(text)
    except (ValueError, RecursionError):
        raise HistoryError(f"{path}: not JSON") from None


def series_from_files(paths, take_ids=None):
    """The `prompt.Series` of the analysis files `paths`, oldest first. The take ids are `take_ids` (one per file) or
    the file names (`prompt.take_id_from`). UsageError for take ids that are wrong, HistoryError for a file that cannot
    be had, is not an analysis, or a series of more than `prompt.MAX_TAKES`."""
    paths = list(paths)
    if len(paths) > prompt.MAX_TAKES:
        raise HistoryError(f"{len(paths)} analyses, the limit is {prompt.MAX_TAKES}")
    ids = list(take_ids) if take_ids else [prompt.take_id_from(p) for p in paths]
    prompt.check_ids(ids, len(paths))   # the ids are checked before any file is read
    return prompt.build_series([_read_analysis(p) for p in paths], ids, labels=[str(p) for p in paths])


def series_from_request(request):
    """`(series, lang, limit)` from the parsed body of `POST api/history-opinion`:
    `{"analyses": [{"take_id", "analysis"}], "lang", "max_observations"}`. HistoryError names the field at fault."""
    if not isinstance(request, dict):
        raise HistoryError("body: expected a JSON object with 'analyses'", "body")
    entries = request.get("analyses")
    if not isinstance(entries, list) or not all(isinstance(e, dict) for e in entries):
        raise HistoryError("analyses: give a list of {take_id, analysis}")
    lang = request.get("lang")
    if lang is not None and not isinstance(lang, str):
        raise HistoryError("lang: must be a language tag such as es or pt-BR", "lang")
    limit = request.get("max_observations", prompt.HISTORY_DEFAULT_N)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= prompt.HISTORY_MAX_N:
        raise HistoryError(f"max_observations: a whole number from 1 to {prompt.HISTORY_MAX_N}", "max_observations")
    series = prompt.build_series([e.get("analysis") for e in entries], [e.get("take_id") for e in entries],
                                 labels=[f"analyses[{i}].analysis" for i in range(len(entries))])
    return series, lang, limit


def _history_document(series, language, requested, status, reason=None, usage=None, found=None):
    found = found or {}
    doc = {"format": HISTORY_FORMAT, "label": guard.LABEL, "status": status, "reason": reason, "backend": BACKEND,
           "model": MODEL if status == "ok" else None, "prompt_version": prompt.PROMPT_VERSION,
           "allowlist_version": prompt.allowlist_version(), "lang": language, "takes": series.summary(),
           "observations": found.get("observations", []),
           "dropped": found.get("dropped", {"count": 0, "reasons": {}}),
           "translation_fallbacks": found.get("translation_fallbacks", 0)}
    if requested:
        doc["lang_requested"] = requested
    if usage:
        doc["usage"] = usage
    return doc


def _history_ask(client, series, language, limit):
    """Check the limits and the cap, ask, record the call; (answer text, usage)."""
    meta_api.preflight()
    payload, usage = meta_api.call(client, prompt.history_request(series, language, limit), HISTORY_PURPOSE,
                                   prompt_version=prompt.PROMPT_VERSION)
    return meta_api.output_text(payload), usage


def _unreadable(usage):
    """The reason for an answer that could not be read: `answer cut off at the output limit` when the API's own count
    says the model used the whole output allowance of a history call (the one live call of 2026-11-01 did, at the old
    allowance of 3000: 3000 of 3000 tokens, no JSON), else `unreadable answer`. An estimated usage says nothing about
    what the model wrote."""
    cut = usage and not usage.get("estimated") and usage.get("output_tokens", 0) >= prompt.HISTORY_MAX_OUTPUT_TOKENS
    return CUT_OFF if cut else "unreadable answer"


def history_run(series, *, lang=None, max_observations=prompt.HISTORY_DEFAULT_N, live=False, client=None,
                timeout_s=meta_api.TIMEOUT_S):
    """The `simon.history_opinion.v1` document for `series`; never raises for a call. `skipped` when no call was
    attempted (no fault with a second, no key, live off), `fallback` when one was prepared or made and failed."""
    language, requested = phrasing_lang.resolve(lang)

    def document(status, reason=None, usage=None, found=None):
        return _history_document(series, language, requested, status, reason, usage, found)

    if not series.citable():
        return document("skipped", NO_CITABLE)
    reason = meta_api.unavailable(live)
    if reason:
        return document("skipped", reason)
    usage = None
    try:
        client = client or meta_api.HttpClient(meta_api.read_key(), timeout_s)
        text, usage = _history_ask(client, series, language, max_observations)
        found = guard.read_history_answer(text, series, language, max_observations)
    except OpinionError as error:
        return document("fallback", error.reason)
    except (ValueError, RecursionError, OverflowError):   # OverflowError: an integer too large for a float
        return document("fallback", _unreadable(usage), usage)
    return document("ok", usage=usage, found=found)
