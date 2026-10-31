"""The take's top-level `insights`: what to work on first (ADR-0014).

    insights_of(analysis) -> [{cue, why, kind, at_s, window, points, measure, side, joint}]   at most MAX_INSIGHTS

A scored take (ADR-0013 timeline) has one insight per distinct cue among its misses, ranked by the points
the cue cost the score: the sum of its misses' points over the compared windows, divided by their number,
because the score is the mean of the windows. `at_s` and `window` are the cue's first miss, so a viewer
can seek there. When the take as a whole was more than 15% faster or slower than the example, a tempo
insight is added last and always kept (`score.tempo`), except when its cue is a reassurance (`cues.REASSURANCE_CUES`:
"Slower is fine", which `rehab` writes in place of the speed-up nudge): that cue is not an action, so it stays in
`tempo.cue` and is no item. A take without a timeline has one insight per distinct fault cue in the order of `faults`
(largest first) with `points` null.

Every word is template text (part5.cues, part5.words), so the same take always gets the same insights.

An insight that points at a reported fault says it in that fault's own timed words (its `text_timed`, "Right foot
too far right at 1.9 s"), so the insight and the fault row never describe the same fault in two vocabularies
(ADR-0014, amendment of 2026-10-31). A miss no reported fault matches (a rep's own miss the take does not report)
and a tempo item keep the plain-words templates below.
"""
import re

from .cues import REASSURANCE_CUES
from .words import phrase

MAX_INSIGHTS = 5
_TIME_TAIL = re.compile(r" at \d+(?:\.\d+)? s$")


def insights_of(analysis):
    score = analysis.get("score") or {}
    faults = analysis.get("faults", [])
    timeline = score.get("timeline")
    items = _from_timeline(timeline, score.get("basis"), faults) if timeline else _from_faults(faults)
    tempo = _tempo_insight(score)
    room = MAX_INSIGHTS - (1 if tempo else 0)
    return items[:room] + ([tempo] if tempo else [])


def _sentence(text):
    return text[:1].upper() + text[1:]


def _timed_words(fault):
    """The fault's timed words, `text_timed` without its time ("right foot too far right"), or None without them."""
    timed = (fault or {}).get("text_timed")
    return _TIME_TAIL.sub("", timed) if timed else None


def _observation(words):
    """The words as one sentence: a phrase that ends in advice ("more upright than the example, lean forward
    more") keeps its first clause, since the cue already says what to do."""
    return _sentence(words.split(", ")[0])


def _fault_of(faults, miss):
    """The reported fault a miss repeats (same measure, side and direction), or None."""
    key = (miss.get("measure"), miss.get("side"), miss.get("direction"))
    return next((f for f in faults if (f.get("measure"), f.get("side"), f.get("direction")) == key), None)


def _item(source, why, at_s, window, points):
    return {"cue": source["cue"], "why": why, "kind": source["cue_kind"], "at_s": at_s, "window": window,
            "points": points, "measure": source.get("measure"), "side": source.get("side"),
            "joint": source.get("joint")}


def _from_faults(faults):
    out, seen = [], set()
    for f in faults:
        if not f.get("cue") or f["cue"] in seen:
            continue
        seen.add(f["cue"])
        at = f.get("at_s")
        observed = _observation(_timed_words(f) or f["text"])
        out.append(_item(f, observed + (f" at {at:.1f} s" if at is not None else ""), at, None, None))
    return out


def _from_timeline(timeline, basis, faults=()):
    compared = [k for k, w in enumerate(timeline) if w.get("compared", True)]
    groups = {}   # cue -> {"first": (window, miss), "points": float, "windows": set}
    for k in compared:
        for m in timeline[k].get("misses", []):
            if not m.get("cue"):
                continue   # a miss written before 1.5.0
            g = groups.setdefault(m["cue"], {"first": (k, m), "points": 0.0, "windows": set()})
            g["points"] += m["points"]
            g["windows"].add(k)
    out = []
    for g in groups.values():
        k, m = g["first"]
        out.append(_item(m, _why(m, len(g["windows"]), len(compared), basis, _fault_of(faults, m)), m.get("at_s"), k,
                         round(g["points"] / len(compared), 1)))
    return sorted(out, key=lambda x: (-x["points"], x["at_s"] is None, x["at_s"] or 0.0, x["cue"]))


def _why(miss, n_windows, n_compared, basis, fault=None):
    """What was seen and where. A miss that repeats a reported `fault` says the fault's timed words and the
    time, then how often: "Right foot too far right at 1.9 s (3 of 8 reps)", "... at 1.9 s (2 times)". Any
    other miss says it in plain words: "Left knee not bent enough (3 of 8 reps)", "... (2 times, first at 4.1 s)"."""
    words = _timed_words(fault)
    seen = _observation(words or phrase(miss["measure"], miss["direction"], miss["side"]))
    at = miss.get("at_s")
    when = f" at {at:.1f} s" if at is not None else ""
    lead = seen + when if words else seen   # the insight's own time, which is the fault's when they agree
    if basis == "reps" and n_compared > 1:
        return f"{lead} ({n_windows} of {n_compared} reps)"
    if n_windows > 1:
        first = f", first at {at:.1f} s" if at is not None and not words else ""
        return f"{lead} ({n_windows} times{first})"
    return seen + when


def _reassures(tempo):
    """True when the take's tempo cue is a reassurance, one of `cues.REASSURANCE_CUES` (`rehab`: "Slower is fine"). That
    is not an action and "what to work on first" lists actions, so the cue stays in `tempo.cue` and `score.tempo.cue`
    but is no item here (Writer ruling of 2026-10-31, AC-PROF-07). Any other cue is an item, including one a profile
    wrote in place of the speed-up nudge."""
    return tempo["cue"] in REASSURANCE_CUES


def _tempo_insight(score):
    tempo = score.get("tempo") or {}
    if not tempo.get("cue") or _reassures(tempo):
        return None
    timeline = score.get("timeline") or []
    same = [(abs(w["tempo"]["ratio"] - 1), k) for k, w in enumerate(timeline)
            if (w.get("tempo") or {}).get("cue") == tempo["cue"]]
    window = max(same)[1] if same else None
    at_s = timeline[window]["t_s"][0] if window is not None else None
    whose = "Your reps took" if score.get("basis") == "reps" else "You took"
    r = tempo["ratio"]
    share = f"{r:.1f} times" if r >= 1 else f"{round(r * 100)}% of"
    why = f"{whose} {share} the trainer's time"
    # ADR-0016: under the dance profile tempo costs points, and the item says how many; null as in ADR-0014 otherwise.
    points = (score.get("components") or {}).get("tempo")
    return {"cue": tempo["cue"], "why": why, "kind": "tempo", "at_s": at_s, "window": window, "points": points,
            "measure": None, "side": None, "joint": None}
