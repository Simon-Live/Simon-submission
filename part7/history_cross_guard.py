"""The citation guard of the across-my-movements report and the monthly recap (docs/specs/history-all.md, TICKET-224 AC-3, AC-7).

`check(answer, bundles, words)` keeps only what the stored data backs. `bundles` maps each movement the call read to its fact
table (the readable takes only, so a private or rehab take is not in it and cannot be cited). An observation is kept
when all of these hold, else it moves to `rejected` with a plain reason; nothing is repaired.
1. It cites takes of two or more different movements, each `{entry, take, at_s}` with the movement in the call, the take
   in that movement's table and `at_s` inside the take.
2. Every cited moment is inside the measured span (or near the measured time) of the same measure and side in that take.
3. Its text is one line without a banned or praise word (the same word lists as the single-movement guard) and without
   a weakness word ("weak", "tight"): the copy says what came up, never what a person has.
4. The only numbers in the text are cited times; movement names are data and are ignored when the text is read.
5. A side or body-part word matches the cited fault's measure, side and joint.
`next_focus` follows the same rules with one cite or more, and its measure and side must be one the tables show as not gone
(`persistent`, `came_back`, `new` or `improved`: still there) in a cited movement.
At most MAX_OBSERVATIONS observations are kept.
"""

from __future__ import annotations

import re
from types import SimpleNamespace
from typing import Any

from part7 import history_guard

MAX_OBSERVATIONS = 3
LABEL = "model_opinion"
LIVE_STATUS = ("persistent", "came_back", "new", "improved")
_WEAKNESS = re.compile(r"\b(?:weak\w*|tight\w*|stiff\w*|imbalance\w*|deficien\w*|lacks?|tendenc\w*|flaw\w*)\b", re.I)
_NUMBER = re.compile(r"(?<![\w.])\d+(?:\.\d+)?")
Problem = tuple[int, str]


def _strip_names(text: str, names: list[str]) -> str:
    for name in sorted({n for n in names if n}, key=len, reverse=True):
        text = re.sub(re.escape(name), " ", text, flags=re.I)
    return text


def _cite(raw: Any, bundles: dict[str, dict[str, Any]], item: dict[str, Any]) -> tuple[dict[str, Any] | None, Problem | None]:
    entry = raw.get("entry") if isinstance(raw, dict) else None
    facts = bundles.get(entry) if isinstance(entry, str) else None
    if facts is None:
        return None, (1, "cites a movement that was not in the input")
    take = raw.get("take")
    row = next((t for t in facts["takes"] if t["take"] == take), None) if isinstance(take, int) and not isinstance(take, bool) else None
    if row is None:
        return None, (1, "cites a take that was not in the input")
    at_s = raw.get("at_s")
    if not history_guard._num(at_s) or at_s < 0 or (history_guard._num(row.get("duration_s")) and at_s > row["duration_s"]):
        return None, (1, "cites a time outside the take")
    if not history_guard._fault_ok(row, item.get("measure"), item.get("side"), at_s):
        return None, (2, "a cited time is not where the analysis measured that fault")
    return {"entry": entry, "take": take, "at_s": at_s}, None


def _reference_fault(item: dict[str, Any], cites: list[dict[str, Any]], bundles: dict[str, dict[str, Any]]) -> dict[str, Any]:
    row = next(t for t in bundles[cites[0]["entry"]]["takes"] if t["take"] == cites[0]["take"])
    found = next((f for f in row["faults"] if f["measure"] == item.get("measure") and f["side"] == item.get("side")), None)
    return found or {"measure": item.get("measure"), "side": item.get("side")}


def _words(text: Any, cites: list[dict[str, Any]], item: dict[str, Any], bundles: dict[str, dict[str, Any]],
           names: dict[str, str], words: Any) -> Problem | None:
    if not isinstance(text, str):
        return 6, "empty text"
    ctx = SimpleNamespace(words=words)
    problem = history_guard._rule6(text, ctx)
    if problem:
        return problem
    bare = _strip_names(history_guard._outside_quotes(text), [names.get(c["entry"], "") for c in cites])
    if _WEAKNESS.search(bare):
        return 6, "says what a person has, not what came up"
    times = {round(float(c["at_s"]), 3) for c in cites}
    if any(round(float(token), 3) not in times for token in _NUMBER.findall(bare)):
        return 4, "a number that is not a cited time"
    if not history_guard._named_matches(bare, _reference_fault(item, cites, bundles)):
        return 9, "names a side or body part that is not the cited fault's"
    return None


def _judge(item: Any, kind: str, bundles: dict[str, dict[str, Any]], names: dict[str, str],
           words: Any) -> tuple[dict[str, Any] | None, Problem | None]:
    if not isinstance(item, dict) or not isinstance(item.get("cites"), list) or not item["cites"]:
        return None, (1, "no citation")
    cites = []
    for raw in item["cites"]:
        cite, problem = _cite(raw, bundles, item)
        if problem:
            return None, problem
        cites.append(cite)
    entries = {c["entry"] for c in cites}
    if kind == "observation" and len(entries) < 2:
        return None, (1, "a cross-movement claim cites fewer than two movements")
    if kind == "next_focus":
        statuses = {m["status"] for e in entries for m in bundles[e]["measures"]
                    if m["measure"] == item.get("measure") and m["side"] == item.get("side")}
        if not statuses & set(LIVE_STATUS):
            return None, (3, "the tables do not show that measure as still there")
    problem = _words(item.get("text"), cites, item, bundles, names, words)
    if problem:
        return None, problem
    return {"text": item["text"], "measure": item["measure"], "side": item["side"], "cites": cites, "label": LABEL}, None


def check(answer: Any, bundles: dict[str, dict[str, Any]], names: dict[str, str],
          words: dict[str, Any] | None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """`(kept, rejected)`: `kept` is `{observations, next_focus}`. `names` maps movement id to its name."""
    shared = history_guard._Words(words)
    doc = history_guard.parse_answer(answer)
    rejected: list[dict[str, Any]] = []
    if doc is None:
        return {"observations": [], "next_focus": None}, [{"item": "answer", "rule": None, "reason": "the answer was not a JSON object"}]
    kept: list[dict[str, Any]] = []
    items = doc.get("observations")
    for i, item in enumerate(items if isinstance(items, list) else []):
        clean, problem = _judge(item, "observation", bundles, names, shared) if len(kept) < MAX_OBSERVATIONS else (None, (0, f"more than {MAX_OBSERVATIONS} items"))
        if clean is not None:
            kept.append(clean)
        else:
            rejected.append({"item": f"observations[{i}]", "rule": problem[0] or None, "reason": problem[1]})
    focus = None
    if doc.get("next_focus") is not None:
        focus, problem = _judge(doc["next_focus"], "next_focus", bundles, names, shared)
        if focus is None:
            rejected.append({"item": "next_focus", "rule": problem[0], "reason": problem[1]})
    return {"observations": kept, "next_focus": focus}, rejected
