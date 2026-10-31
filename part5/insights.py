"""The take's top-level `insights`: what to work on first (ADR-0014).

    insights_of(analysis) -> [{cue, why, kind, at_s, window, points, measure, side, joint}]   at most MAX_INSIGHTS

A scored take (ADR-0013 timeline) has one insight per distinct cue among its misses, ranked by the points
the cue cost the score: the sum of its misses' points over the compared windows, divided by their number,
because the score is the mean of the windows. `at_s` and `window` are the cue's first miss, so a viewer
can seek there. When the take as a whole was more than 15% faster or slower than the example, a tempo
insight is added last and always kept (`score.tempo`). A take without a timeline has one insight per
distinct fault cue in the order of `faults` (largest first) with `points` null.

Every word is template text (part5.cues, part5.words), so the same take always gets the same insights.
"""
from .words import phrase

MAX_INSIGHTS = 5


def insights_of(analysis):
    score = analysis.get("score") or {}
    timeline = score.get("timeline")
    items = _from_timeline(timeline, score.get("basis")) if timeline else _from_faults(analysis.get("faults", []))
    tempo = _tempo_insight(score)
    room = MAX_INSIGHTS - (1 if tempo else 0)
    return items[:room] + ([tempo] if tempo else [])


def _sentence(text):
    return text[:1].upper() + text[1:]


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
        out.append(_item(f, _sentence(f.get("text_timed") or f["text"]), f.get("at_s"), None, None))
    return out


def _from_timeline(timeline, basis):
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
        out.append(_item(m, _why(m, len(g["windows"]), len(compared), basis), m.get("at_s"), k,
                         round(g["points"] / len(compared), 1)))
    return sorted(out, key=lambda x: (-x["points"], x["at_s"] is None, x["at_s"] or 0.0, x["cue"]))


def _why(miss, n_windows, n_compared, basis):
    """What was seen and where: "Left knee not bent enough (3 of 8 reps)", "... (2 times, first at 4.1 s)"."""
    seen = _sentence(phrase(miss["measure"], miss["direction"], miss["side"]))
    at = miss.get("at_s")
    if basis == "reps" and n_compared > 1:
        return f"{seen} ({n_windows} of {n_compared} reps)"
    if n_windows > 1:
        return f"{seen} ({n_windows} times" + (f", first at {at:.1f} s)" if at is not None else ")")
    return seen + (f" at {at:.1f} s" if at is not None else "")


def _tempo_insight(score):
    tempo = score.get("tempo") or {}
    if not tempo.get("cue"):
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
    return {"cue": tempo["cue"], "why": why, "kind": "tempo", "at_s": at_s, "window": window, "points": None,
            "measure": None, "side": None, "joint": None}
