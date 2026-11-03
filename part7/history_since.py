"""Since last time: one take against the student's previous take of the same movement, section and mode
(docs/specs/history.md "Since last time", TICKET-207). No model; every fact comes from the fact table with its
like-with-like rule (`history_facts`): a cue is "gone" or "new" only where the other take compared that moment, and a
score is compared only on one score version. Anything the table cannot back is left out, a private take is neither shown nor counted, and with nothing to say the
answer is None, so the result page shows nothing.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from part7 import history_facts, shown_score

FORMAT = "simon.history.since.v1"
MAX_PER_KIND = 2
_JOINT_SIDES = ("left", "right")


def _label(fault: dict[str, Any]) -> str:
    """The plain name of what a cue is about: the joint (left knee), else the measure's words."""
    joint = fault.get("joint")
    words = joint.replace("_", " ").strip() if isinstance(joint, str) and joint else str(fault["measure"]).replace("_", " ")
    side = fault.get("side")
    if side in _JOINT_SIDES and side not in words.split():
        words = f"{side} {words}"
    return words


def _date(stamp: Any) -> str:
    """A date such as 28 Oct from a recorded time, or an empty string when it does not parse."""
    try:
        when = datetime.strptime(str(stamp), "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return ""
    return f"{when.day} {when:%b}"


def _link(row: dict[str, Any], at_s: float | None = None) -> dict[str, Any]:
    inside = at_s is not None and (row.get("duration_s") is None or at_s <= row["duration_s"])
    return {"take": row["take"], "job_id": row.get("job_id"), "at_s": at_s if inside else None}


def _figures(row: dict[str, Any]) -> str:
    """A take's score as its page shows it: the `shown` figures, else Part 5's score."""
    shown = row.get("shown")
    return shown["figures"] if isinstance(shown, dict) and isinstance(shown.get("figures"), str) else str(row["score"])


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _changes(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Facts about the last take against the one before it (`rows` is one group, oldest first)."""
    take, prev, earlier = rows[-1], rows[-2], rows[:-2]
    out = []
    if history_facts.same_scale(take, prev) and _number(take["score"]) and _number(prev["score"]):
        # one-letter.md L3: compared by the shown measure and worded with the shown figures (16,239, 73%, or the score)
        same = shown_score.rank_of(take) == shown_score.rank_of(prev)
        text = f"score {_figures(take)}, the same" if same else f"score {_figures(prev)} to {_figures(take)}"
        out.append({"kind": "score", "text": text, "link": _link(prev)})
    gone, back = [], []
    for fault in prev["faults"]:
        if history_facts.fault_of(take, fault["measure"], fault["side"]) is None and history_facts.covers(take, fault["at_s"], fault["measure"], fault["side"]):
            gone.append({"kind": "gone", "text": f"the {_label(fault)} cue is gone", "link": _link(prev, fault["at_s"])})
    for fault in take["faults"]:
        if history_facts.fault_of(prev, fault["measure"], fault["side"]) is not None or not history_facts.covers(prev, fault["at_s"], fault["measure"], fault["side"]):
            continue
        before = any(history_facts.fault_of(r, fault["measure"], fault["side"]) for r in earlier)
        word = "back" if before else "new"
        back.append({"kind": word, "text": f"the {_label(fault)} cue is {word}", "link": _link(prev, fault["at_s"])})
    return out + _unique(gone) + _unique(back)


def _unique(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen, kept = set(), []
    for item in items:
        if item["text"] not in seen and len(kept) < MAX_PER_KIND:
            seen.add(item["text"])
            kept.append(item)
    return kept


def _bests(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Personal bests and firsts of the last take against every earlier take of its group."""
    take, earlier = rows[-1], rows[:-1]
    out = []
    scored = [r for r in earlier if history_facts.same_scale(take, r) and _number(r["score"])]
    if _number(take["score"]) and scored:
        top = max(scored, key=lambda r: (shown_score.rank_of(r), -r["take"]))
        if shown_score.rank_of(take) > shown_score.rank_of(top):
            out.append({"kind": "best", "text": f"New best: {_figures(take)}", "link": _link(top)})
    firsts = []
    for measure, side in dict.fromkeys((f["measure"], f["side"]) for r in earlier for f in r["faults"]):
        marks = history_facts.states(rows, measure, side)
        if not marks or marks[-1][0] is not take or marks[-1][1] != "a" or any(m == "a" for _, m in marks[:-1]):
            continue  # this take did not compare the moment, or an earlier take was already without it
        last = next(r for r, m in reversed(marks[:-1]) if m == "p")
        fault = history_facts.fault_of(last, measure, side)
        firsts.append({"kind": "first_without", "text": f"First take without the {_label(fault)} cue",
                       "link": _link(last, fault["at_s"])})
    return out + _unique(firsts)


def since_last_time(facts: dict[str, Any], job_id: str) -> dict[str, Any] | None:
    """The comparison for the take recorded by `job_id`, or None: not in the table, a first take of its group, an
    unknown section or mode, or nothing the table can back. Later takes are ignored, so an old result reads as it did."""
    row = next((r for r in facts.get("takes") or [] if r.get("job_id") == job_id), None)
    if row is None:
        return None
    if row.get("private"):
        return None
    rows = [r for r in facts["takes"] if r["take"] <= row["take"] and not r.get("private") and history_facts.same_group(r, row)]
    if len(rows) < 2:
        return None
    changes, bests = _changes(rows), _bests(rows)
    if row.get("mode") == "rehab":  # rehab shows what changed in the cues, never a score or a record
        changes = [c for c in changes if c["kind"] != "score"]
        bests = [b for b in bests if b["kind"] != "best"]
    if not changes and not bests:
        return None
    prev = rows[-2]
    date = _date(prev.get("at"))
    head = f"Since last time ({date})" if date else "Since last time"
    line = f"{head}: " + "; ".join(c["text"] for c in changes) if changes else ""
    return {"format": FORMAT, "job_id": job_id, "take": row["take"], "previous": {"take": prev["take"], "job_id": prev.get("job_id"), "at": prev.get("at")},
            "line": line, "facts": changes, "bests": bests}
