"""The citation guard for "Ask my history" (docs/specs/history-ask.md, TICKET-222).

`check_qa(answer, refs, entries, words)` reads the model's `simon.history.ask.v1` answer and keeps only the claims
the stored data backs. A claim is a trend, a moment, a comparison or a count; each cites takes by `ref` (the number
`history_ask.pack` gave every take of the whole history) and seconds. Rules per claim:
1. every cite is a known ref, all in one movement, with `at_s` inside that take's length; at most MAX_CITES.
2. the measure and side exist in that movement's fact table, and a cited second is where that take measured the fault.
3. by kind: a trend's `relation` is the fact table's status; a moment cites one second of one take; a comparison's
   `relation` (smaller, larger, score_up, score_down) is true of the two cited takes' measured sizes or scores;
   a count equals the number of takes the fact table lists for that measure (or all takes of the movement).
4. the text is one plain line with no banned word or praise, and its numbers are only cited seconds and scores, the
   claim's count, cited take numbers and the cited takes' day and year; its side and body-part words are the fault's.
A claim failing any rule is dropped and only counted. The lead sentence (`answer.text`) is shown only when nothing was
dropped and its numbers, sides and parts come from the kept claims. `abstain` is honoured with a checked reason.
"""

from __future__ import annotations

import math
import re
from typing import Any

from part7 import history_facts, history_guard, movement, shown_score

MAX_CLAIMS = 8
MAX_CITES = 12
LEAD_MAX = 240
KINDS = ("trend", "moment", "comparison", "count")
RELATIONS = ("smaller", "larger", "score_up", "score_down")
MSG_ABSTAIN = "Your takes do not hold enough to answer that."
MSG_UNCHECKED = "Simon could not check an answer to that against your takes."
_DATE = re.compile(r"(\d{1,2}) \w{3} (\d{4})")
_SNAKE = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b", re.I)  # a raw id such as trunk_lean_forward

Problem = str
Refs = dict[int, dict[str, Any]]


def _num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def display_name(measure: str) -> str:
    """The name a measure is shown by, the one the cites and the history page use (web/model/history.js measureLabel):
    "trunk_lean_forward" -> "Trunk lean forward"."""
    words = str(measure).replace("_", " ").strip()
    return words[:1].upper() + words[1:]


def known_measures(entries: dict[str, Any]) -> set[str]:
    """Every measure id a claim may name: Part 5's list and the measures of the movements sent."""
    found = set(movement.PART5_MEASURES)
    for entry in entries.values():
        found |= {m["measure"] for m in (entry.get("facts") or {}).get("measures") or [] if isinstance(m.get("measure"), str)}
    return found


def plain_ids(text: Any, known: set[str]) -> Any:
    """`text` with each snake_case measure id written as its display name (lower case inside a sentence); None when it
    holds a snake_case word that is no known measure, so the claim is dropped. Anything but a string is returned as is."""
    if not isinstance(text, str):
        return text
    unknown = False

    def swap(match: re.Match[str]) -> str:
        nonlocal unknown
        word = match.group(0)
        if word.lower() not in known:
            unknown = True
            return word
        name = display_name(word.lower())
        return name if match.start() == 0 or text[:match.start()].rstrip().endswith((".", "!", "?")) else name.lower()

    out = _SNAKE.sub(swap, text)
    return None if unknown else out


def _cites(claim: dict[str, Any], refs: Refs) -> tuple[list[dict[str, Any]], Problem | None]:
    raw = claim.get("cites")
    if not isinstance(raw, list) or not raw or len(raw) > MAX_CITES:
        return [], "no citation"
    out: list[dict[str, Any]] = []
    for cite in raw:
        ref = cite.get("ref") if isinstance(cite, dict) else None
        if not _int(ref) or ref not in refs:
            return [], "cites a take that was not sent"
        at_s, row = cite.get("at_s"), refs[ref]["row"]
        if at_s is not None and (not _num(at_s) or at_s < 0 or (_num(row.get("duration_s")) and at_s > row["duration_s"])):
            return [], "cites a time outside the take"
        out.append({"ref": ref, "at_s": at_s})
    if len({refs[c["ref"]]["entry"] for c in out}) != 1:
        return [], "cites more than one movement"
    return out, None


def _side(claim: dict[str, Any]) -> str:
    return claim.get("side") or "center"


def _measure(claim: dict[str, Any], entry: dict[str, Any], need: bool) -> tuple[dict[str, Any] | None, Problem | None]:
    measure, side = claim.get("measure") or None, _side(claim)
    if measure is None:
        return None, "needs a measure" if need else None
    found = next((m for m in entry["facts"]["measures"] if m["measure"] == measure and m["side"] == side), None)
    return (found, None) if found else (None, "the fact table has no such measure and side")


def _fault_at(row: dict[str, Any], claim: dict[str, Any], at_s: float) -> bool:
    return history_guard._fault_ok(row, claim.get("measure"), _side(claim), at_s)


def _timed_at_fault(claim: dict[str, Any], cites: list[dict[str, Any]], refs: Refs) -> Problem | None:
    for cite in cites:
        if cite["at_s"] is not None and not _fault_at(refs[cite["ref"]]["row"], claim, cite["at_s"]):
            return "a time is not where the analysis measured that fault"
    return None


def _trend(claim: dict[str, Any], cites: list[dict[str, Any]], refs: Refs, entry: dict[str, Any]) -> Problem | None:
    found, problem = _measure(claim, entry, True)
    if problem or found is None:
        return problem
    if claim.get("relation") not in history_guard.KINDS or claim["relation"] != found.get("status"):
        return "the relation does not agree with the fact table"
    if not all(refs[c["ref"]]["row"].get("in_group") for c in cites) or not any(c["at_s"] is not None for c in cites):
        return "a trend cites takes of its group and at least one second"
    return _timed_at_fault(claim, cites, refs)


def _moment(claim: dict[str, Any], cites: list[dict[str, Any]], refs: Refs, entry: dict[str, Any]) -> Problem | None:
    if len(cites) != 1 or cites[0]["at_s"] is None:
        return "a moment cites one second of one take"
    if not claim.get("measure"):
        return "needs a measure"
    return None if _fault_at(refs[cites[0]["ref"]]["row"], claim, cites[0]["at_s"]) else "no such fault at that second"


def _score_moved(a: dict[str, Any], b: dict[str, Any]) -> str | None:
    """"up" or "down" from take `a` to take `b` by the shown measure (one-letter.md L3), None when the same."""
    ra, rb = shown_score.rank_of(a), shown_score.rank_of(b)
    return None if ra is None or rb is None or ra == rb else "up" if rb > ra else "down"


def _comparison(claim: dict[str, Any], cites: list[dict[str, Any]], refs: Refs, entry: dict[str, Any]) -> Problem | None:
    relation = claim.get("relation")
    if len(cites) != 2 or cites[0]["ref"] == cites[1]["ref"] or relation not in RELATIONS:
        return "a comparison cites two takes and says smaller, larger, score_up or score_down"
    a, b = refs[cites[0]["ref"]]["row"], refs[cites[1]["ref"]]["row"]
    if relation.startswith("score"):
        if claim.get("measure") or not history_facts.same_scale(a, b) or not (_num(a.get("score")) and _num(b.get("score"))):
            return "scores are comparable only for one section, mode and score version"
        moved = _score_moved(a, b)
        return None if moved is not None and (moved == "up") == (relation == "score_up") else "the scores do not say that"
    found, problem = _measure(claim, entry, True)
    if problem or found is None or not history_facts.same_group(a, b):
        return problem or "the takes are not of one section and mode"
    sizes = [(history_facts.fault_of(r, claim["measure"], _side(claim)) or {}).get("magnitude") for r in (a, b)]
    if not all(_num(s) for s in sizes):
        return "that fault has no measured size in both takes"
    sizes = [abs(s) for s in sizes]  # Part 5's magnitude_deg is signed (follower minus example): size is its absolute value
    return None if sizes[1] != sizes[0] and (sizes[1] < sizes[0]) == (relation == "smaller") else "the sizes do not say that"


def _count(claim: dict[str, Any], cites: list[dict[str, Any]], refs: Refs, entry: dict[str, Any]) -> Problem | None:
    found, problem = _measure(claim, entry, False)
    if problem:
        return problem
    cited = {refs[c["ref"]]["row"]["take"] for c in cites}
    owners = set(found["present_in"]) if found is not None else {r["take"] for r in entry["rows"]}
    return None if claim.get("count") == len(owners) and cited <= owners else "the count is not the fact table's"


JUDGES = {"trend": _trend, "moment": _moment, "comparison": _comparison, "count": _count}


def _allowed_numbers(claim: dict[str, Any], cites: list[dict[str, Any]], refs: Refs) -> set[float]:
    allowed: set[float] = {round(float(c["at_s"]), 3) for c in cites if c["at_s"] is not None}
    if _int(claim.get("count")):
        allowed.add(float(claim["count"]))
    for cite in cites:
        row = refs[cite["ref"]]["row"]
        allowed.add(float(row["take"]))
        if _num(row.get("score")):
            allowed.add(round(float(row["score"]), 3))
        allowed |= shown_score.numbers_in(row.get("shown"))  # one-letter.md L7: the figures the page shows
        date = _DATE.search(refs[cite["ref"]].get("date") or "")
        allowed |= {float(g) for g in date.groups()} if date else set()
    return allowed


def _numbers_ok(text: str, allowed: set[float]) -> bool:
    bare = history_guard._GROUPED.sub(r"\1\2", history_guard._outside_quotes(text))
    return all(round(float(t), 3) in allowed for t in history_guard._NUMBER.findall(bare))


def _words_ok(text: str, sides: set[str], parts: set[str]) -> bool:
    if any(w.lower() not in sides for w in history_guard._SIDE_WORD.findall(text)):
        return False
    return all(history_guard.PARTS[w.lower()] in parts for w in history_guard._PART_WORD.findall(text))


def _fault_words(claim: dict[str, Any], entry: dict[str, Any]) -> tuple[set[str], set[str]]:
    """The sides and body parts a claim may name: those of its measure's faults in the movement (`both` allows either)."""
    if not claim.get("measure"):
        return set(), set()
    sides: set[str] = set()
    parts: set[str] = set()
    for row in entry["rows"]:
        for fault in row["faults"]:
            if fault["measure"] == claim["measure"] and fault["side"] == _side(claim):
                sides |= {"left", "right"} if fault["side"] == "both" else {fault["side"]}
                parts |= history_guard._parts_of(fault["measure"], fault.get("joint"), fault.get("body_part"))
    return sides, parts


def _judge(claim: Any, refs: Refs, entries: dict[str, Any], words: Any) -> tuple[dict[str, Any] | None, Problem | None]:
    if not isinstance(claim, dict) or claim.get("kind") not in KINDS:
        return None, "not a claim of a known kind"
    cites, problem = _cites(claim, refs)
    if problem:
        return None, problem
    entry_id = refs[cites[0]["ref"]]["entry"]
    entry = entries[entry_id]
    text = plain_ids(claim.get("text"), known_measures(entries))  # a raw measure id is shown by its name, or the claim goes
    if text is None:
        return None, "a raw id that is no known measure"
    problem = JUDGES[claim["kind"]](claim, cites, refs, entry) or history_guard.text_problem(text, words)
    if not problem and not _numbers_ok(text, _allowed_numbers(claim, cites, refs)):
        problem = "a number that is not a cited time, score, count or take"
    sides, parts = _fault_words(claim, entry)
    if not problem and not _words_ok(history_guard._outside_quotes(text), sides, parts):
        problem = "names a side or body part that is not the claim's"
    if problem:
        return None, problem
    out_cites = [{"ref": c["ref"], "entry_id": entry_id, "take": refs[c["ref"]]["row"]["take"],
                  "movement": entry.get("name"), "job_id": refs[c["ref"]]["row"]["job_id"], "at_s": c["at_s"]} for c in cites]
    return {"kind": claim["kind"], "text": text, "measure": claim.get("measure") or None, "side": _side(claim) if claim.get("measure") else None,
            "relation": claim.get("relation") or None, "count": claim.get("count") if _int(claim.get("count")) else None,
            "cites": out_cites}, None


def _lead_ok(text: Any, kept: list[dict[str, Any]], refs: Refs, entries: dict[str, Any], words: Any) -> bool:
    """The lead sentence is shown only when it is plain and says nothing the kept claims do not."""
    if history_guard.text_problem(text, words, LEAD_MAX):
        return False
    allowed: set[float] = set()
    sides: set[str] = set()
    parts: set[str] = set()
    for claim in kept:
        cites = [{"ref": c["ref"], "at_s": c["at_s"]} for c in claim["cites"]]
        allowed |= _allowed_numbers(claim, cites, refs)
        s, p = _fault_words(claim, entries[claim["cites"][0]["entry_id"]])
        sides |= s
        parts |= p
    return _numbers_ok(text, allowed) and _words_ok(history_guard._outside_quotes(text), sides, parts)


def _abstain_text(reason: Any, words: Any) -> str:
    plain = isinstance(reason, str) and not history_guard.text_problem(reason, words)
    bare = plain and not (history_guard._NUMBER.search(reason) or history_guard._SIDE_WORD.search(reason)
                          or history_guard._PART_WORD.search(reason))
    return reason if bare else MSG_ABSTAIN


def check_qa(answer: Any, refs: Refs, entries: dict[str, Any], words: dict[str, Any] | None = None) -> dict[str, Any]:
    """`{status, text, claims, dropped, message}`; status is ok, abstain or unverified. Nothing here is the model's raw text
    unless it passed the rules above."""
    checker = history_guard.Words(words)
    doc = history_guard.parse_answer(answer)
    if doc is None:
        return {"status": "unverified", "text": None, "claims": [], "dropped": 0, "message": MSG_UNCHECKED}
    if doc.get("abstain") is True:
        return {"status": "abstain", "text": None, "claims": [], "dropped": 0,
                "message": _abstain_text(doc.get("abstain_reason"), checker)}
    raw = doc.get("claims") if isinstance(doc.get("claims"), list) else []
    kept: list[dict[str, Any]] = []
    dropped = 0
    for item in raw:
        clean, _ = _judge(item, refs, entries, checker) if len(kept) < MAX_CLAIMS else (None, "more claims than allowed")
        if clean is None:
            dropped += 1
        else:
            kept.append(clean)
    if not kept:
        return {"status": "unverified", "text": None, "claims": [], "dropped": dropped, "message": MSG_UNCHECKED}
    lead = plain_ids(doc["answer"].get("text"), known_measures(entries)) if isinstance(doc.get("answer"), dict) else None
    shown = lead if not dropped and _lead_ok(lead, kept, refs, entries, checker) else None
    return {"status": "ok", "text": shown, "claims": kept, "dropped": dropped, "message": ""}
