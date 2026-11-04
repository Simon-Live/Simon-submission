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

Every word is template text (part5.cues, part5.words) except the one case below, and the insights are a function of
the document alone: the same document always gets the same insights.

An insight that points at a reported fault says it in that fault's own words, so the insight and the fault row never
describe the same fault in two vocabularies (ADR-0014, amendments of 2026-10-31 and 2026-11-01). Those are the fault's
timed words (its `text_timed`, "Right foot too far right at 1.9 s"). When the fault's line was written by a live model
and passed the word test (its `phrasing.faults[i]` has a backend other than the template, no fallback reason and
language en or none), they are the observation clause of that line instead: its `coaching` before the first ";", any
closing run of "." "!" and "?" dropped, "Your right foot drifts too far to the right at 1.9 s", which must pass the timed word test
again and has its time set to the insight's own. A clause that fails the test, a template or fallback line and a
translated line keep the timed words. A miss no reported fault matches (a rep's own miss the take does not report) and
a tempo item keep the plain-words templates below.
"""
import re

from .cues import REASSURANCE_CUES
from .phrasing.lang import EN
from .phrasing.template import NAME as TEMPLATE
from .phrasing.template import TIME, line_problem
from .words import phrase

MAX_INSIGHTS = 5
_TIME_TAIL = re.compile(r" at \d+(?:\.\d+)? s$")
_LINE_TIME = re.compile(TIME.pattern, re.I)   # the word test's time phrase, whatever the letter case
CLOSING_MARKS = ".!?"   # a live clause loses any closing run of these, so "..." and "?" leave nothing before the count


def insights_of(analysis):
    score = analysis.get("score") or {}
    faults = analysis.get("faults", [])
    phrased = (analysis.get("phrasing") or {}).get("faults") or []
    timeline = score.get("timeline")
    items = _from_timeline(timeline, score.get("basis"), faults, phrased) if timeline else _from_faults(faults, phrased)
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


def _fault_index(faults, miss):
    """The index of the reported fault a miss repeats (same measure, side and direction), or None."""
    key = (miss.get("measure"), miss.get("side"), miss.get("direction"))
    return next((i for i, f in enumerate(faults) if (f.get("measure"), f.get("side"), f.get("direction")) == key), None)


def _entry(phrased, index):
    """`phrasing.faults[index]`, or None without an index or when the record is shorter."""
    return phrased[index] if index is not None and index < len(phrased) else None


def _is_live(entry):
    """True when a `phrasing.faults[i]` entry records a line a live model wrote and the word test passed: a backend
    other than the template, no fallback reason, and English (`lang` en or absent)."""
    return (isinstance(entry, dict) and bool(entry.get("backend")) and entry["backend"] != TEMPLATE
            and entry.get("fallback_reason") is None and entry.get("lang", EN) == EN)


def _live_clause(fault, entry, at):
    """The observation clause of the fault's live English line at the insight's time `at`, or None.

    Steps (ADR-0014, Amendment 2): keep the `coaching` before its first ";", drop any closing run of "." "!" and "?"
    ("...", "?!" too), and run the timed word test on what is left (None if it fails); then replace the one time number (the fault's `at_s` to 0.1 s)
    with `at` to 0.1 s, keeping the unit as written, and capitalise the first letter. "At 1.4 s, your knees are not
    bent enough." gives "At 1.4 s, your knees are not bent enough". "Your right foot drifts too far to the right at
    1.9 s; keep it under your hip", for an insight at 1.7 s, gives "Your right foot drifts too far to the right at
    1.7 s"."""
    line = (fault or {}).get("coaching")
    if at is None or not _is_live(entry) or not isinstance(line, str):
        return None
    clause = line.partition(";")[0].strip().rstrip(CLOSING_MARKS).rstrip()
    if line_problem(fault, clause, timed=True):
        return None
    found = list(_LINE_TIME.finditer(clause))
    if len(found) != 1:
        return None
    start, end = found[0].span(1)
    return _sentence(f"{clause[:start]}{at:.1f}{clause[end:]}")


def _item(source, why, at_s, window, points):
    return {"cue": source["cue"], "why": why, "kind": source["cue_kind"], "at_s": at_s, "window": window,
            "points": points, "measure": source.get("measure"), "side": source.get("side"),
            "joint": source.get("joint")}


def _from_faults(faults, phrased=()):
    out, seen = [], set()
    for i, f in enumerate(faults):
        if not f.get("cue") or f["cue"] in seen:
            continue
        seen.add(f["cue"])
        at = f.get("at_s")
        observed = _live_clause(f, _entry(phrased, i), at) or (
            _observation(_timed_words(f) or f["text"]) + (f" at {at:.1f} s" if at is not None else ""))
        out.append(_item(f, observed, at, None, None))
    return out


def _from_timeline(timeline, basis, faults=(), phrased=()):
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
        i = _fault_index(faults, m)
        fault = faults[i] if i is not None else None
        out.append(_item(m, _why(m, len(g["windows"]), len(compared), basis, fault, _entry(phrased, i)), m.get("at_s"),
                         k, round(g["points"] / len(compared), 1)))
    return sorted(out, key=lambda x: (-x["points"], x["at_s"] is None, x["at_s"] or 0.0, x["cue"]))


def _why(miss, n_windows, n_compared, basis, fault=None, entry=None):
    """What was seen and where. A miss that repeats a reported `fault` says the fault's own words and the
    time, then how often: "Right foot too far right at 1.9 s (3 of 8 reps)", "... at 1.9 s (2 times)". Those words
    are the fault's `text_timed`, or, when `entry` (its `phrasing.faults[i]`) records a validated live English line,
    that line's observation clause (`_live_clause`): "Your right foot drifts too far to the right at 1.7 s
    (3 of 8 reps)". Any other miss says it in plain words: "Left knee not bent enough (3 of 8 reps)",
    "... (2 times, first at 4.1 s)"."""
    at = miss.get("at_s")
    live = _live_clause(fault, entry, at)
    words = _timed_words(fault)
    seen = _observation(words or phrase(miss["measure"], miss["direction"], miss["side"]))
    when = f" at {at:.1f} s" if at is not None else ""
    says_time = bool(live or words)
    lead = live or (seen + when if words else seen)   # the insight's own time, which is the fault's when they agree
    if basis == "reps" and n_compared > 1:
        return f"{lead} ({n_windows} of {n_compared} reps)"
    if n_windows > 1:
        first = f", first at {at:.1f} s" if at is not None and not says_time else ""
        return f"{lead} ({n_windows} times{first})"
    return lead if says_time else seen + when


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
