"""Muse Spark's second opinion on a take (TICKET-045, docs/specs/second-opinion.md, contract C1).

`attach(result, expected_video, follower_video, live=...)` returns the analysis with a top-level `second_opinion`:
one Muse Spark 1.3 call that watches the teacher's recording and the student's take with the measured faults, and
says per fault whether it agrees, with a one-line note, plus at most two observations of its own labelled
`model_opinion`. Only what passes `guard.read_answer` is kept.

The block is added after the score and insights are built and nothing reads it back, so a dispute never changes a
measured field (AC-SO-05). It is absent when no clip was given; `skipped` when no call was attempted (one clip
missing, no key, live off); `fallback` when a call was prepared or made and failed (the reason says why). A failure
never stops the analysis.
"""
import tempfile
from pathlib import Path

from . import guard, meta_api, prompt
from .meta_api import BACKEND, MODEL, OpinionError

BOTH_CLIPS = "both clips are needed"


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
    """Check the total cap, upload both clips, count, ask; (answer text, usage). Files are deleted on every path.

    The ledger is opened and locked after the count and held until the call is recorded: the budget check and the
    call happen under the lock, so two processes cannot both pass the cap. A call whose cost is not known (no answer
    from the API, a 5xx, an answer with no token counts) is recorded at its pre-call estimate
    (`meta_api.failed_usage`, `meta_api.answered_usage`)."""
    ids = []
    try:
        meta_api.check_settings()   # a limit set to something that is not an amount refuses the call before any upload
        meta_api.check_cap()   # nothing is uploaded when the total cap is already spent
        with tempfile.TemporaryDirectory(prefix="part5-opinion-") as tmp:
            for clip in clips:
                ids.append(client.upload(meta_api.prepare(clip, tmp)))
        body = prompt.request(ids[0], ids[1], faults, duration_s)
        counted = client.count(body)
        estimate = meta_api.price(counted, meta_api.MAX_OUTPUT_TOKENS)
        with meta_api.open_ledger() as ledger:
            meta_api.check_budget(estimate)
            try:
                payload = client.respond(body)
            except OpinionError:
                status = getattr(client, "last_status", None)
                meta_api.write_ledger(ledger, status, meta_api.failed_usage(status, counted, estimate))
                raise
            usage = meta_api.answered_usage(payload, counted, estimate)
            meta_api.write_ledger(ledger, getattr(client, "last_status", 200), usage)
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
