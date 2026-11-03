"""The next-session plan (docs/specs/history-all.md "Next session plan", TICKET-223).

A plan is chosen only from things Simon already has: a cue the student's own takes carry, a learn-in-sections step, a
playback speed of the section ladder, a number of takes. Each item is tied to cited takes and moments, so
`check` can test every one of them against the fact table before anything is shown:

- `cue`: the cue is word for word one of the cited take's cues, and the cited moment is where that take's analysis measured the fault.
- `section`: the section key is one a take of this movement was recorded in (never the whole movement), `step` is the ladder
  key it names, and the cited take was recorded in that section.
- `speed`: one of SPEEDS, below full speed (the ladder's slow step).
- `takes`: a whole number from 1 to MAX_TAKES.
- every text is one line with no banned or praise word (the single-movement guard's word lists, which hold the health words),
  and its only numbers are cited times, take numbers it cites and the item's own section, speed or take count.
`build` never reads a private take, and returns None for a rehab group: a plan there would add load, range or reps, which only
the teacher decides. No model is called, so a plan costs nothing; `check` accepts a plan from any source.
"""

from __future__ import annotations

import re
from types import SimpleNamespace
from typing import Any

from part7 import history_guard, history_since

FORMAT = "simon.history.plan.v1"
SPEEDS = (0.5, 0.75, 1.0)   # the learn speeds of the section ladder (web/modes.js): rehab 0.5, dance 0.75, fitness 1
LEARN_SPEED = {"dance": 0.75}   # the modes whose ladder has a slow step the plan may name (rehab is never planned)
MAX_TAKES = 5
KINDS = ("cue", "section", "speed", "takes")
SPACING = "Come back tomorrow for the next session. Spreading practice over days helps it stick."
LABEL = "Worked out from your stored takes, without the model."
_PRIORITY = {"persistent": 0, "came_back": 1, "new": 2, "improved": 3}
_SECTION = re.compile(r"^s(?:(\d+)-)?(\d+)of(\d+)(?:@([0-9.]+))?$")
_NUMBER = re.compile(r"(?<![\w.])\d+(?:\.\d+)?")
_TAKE_LABEL = re.compile(r"\btake\s+(\d+)", re.I)


def step_of(section_key: Any) -> str | None:
    """The ladder step (web/practice.js `buildLadder` key) a take's section key names, or None for the whole movement."""
    found = _SECTION.match(section_key) if isinstance(section_key, str) else None
    if not found:
        return None
    first, index, _count, speed = found.groups()
    if first:
        return f"j{first}-{index}"
    return f"s{index}@slow" if speed else f"s{index}@full"


def _focus(facts: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]] | None:
    """`(measure row, latest take, its fault)` for the measure most worth another go: still in the latest take, with a cue."""
    latest = next((t for t in facts["takes"] if t["take"] == facts.get("latest")), None)
    if latest is None or not latest.get("in_group") or latest.get("mode") == "rehab" or latest.get("private"):
        return None
    options = []
    for measure in facts["measures"]:
        fault = next((f for f in latest["faults"] if f["measure"] == measure["measure"] and f["side"] == measure["side"]), None)
        if fault and measure["status"] in _PRIORITY and isinstance(fault.get("cue"), str) and fault["cue"].strip() and fault.get("at_s") is not None:
            options.append(((_PRIORITY[measure["status"]], -abs(fault["magnitude"] or 0), measure["measure"], measure["side"]), measure, fault))
    if not options:
        return None
    _, measure, fault = min(options, key=lambda o: o[0])
    return measure, latest, fault


def focus_fault(facts: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]] | None:
    """`(measure row, latest take, its fault)` the plan and the focus line both start from (TICKET-223 AC-1)."""
    return _focus(facts)


def _takes_to_record(status: str) -> int:
    return {"persistent": 3, "came_back": 3, "new": 2, "improved": 2}.get(status, 2)


def _candidate(facts: dict[str, Any]) -> dict[str, Any] | None:
    picked = _focus(facts)
    if picked is None:
        return None
    measure, latest, fault = picked
    cite = [{"take": latest["take"], "at_s": fault["at_s"]}]
    label = history_since._label(fault)
    items: list[dict[str, Any]] = [{
        "kind": "cue", "cue": fault["cue"], "measure": fault["measure"], "side": fault["side"], "cites": cite,
        "text": f"Work on the {label} cue: “{fault['cue']}” (take {latest['take']}, {fault['at_s']:g} s)."}]
    step = step_of(latest.get("section_key"))
    if step:
        found = _SECTION.match(latest["section_key"])
        index, count = int(found.group(2)), int(found.group(3))
        items.append({"kind": "section", "section_key": latest["section_key"], "step": step, "cites": cite,
                      "text": f"Practise section {index} of {count}, where it showed in take {latest['take']}."})
        speed = LEARN_SPEED.get(latest.get("mode"))
        if speed:
            items.append({"kind": "speed", "speed": speed, "cites": cite, "text": f"Start the slow step at {speed:g} speed."})
    n = _takes_to_record(measure["status"])
    items.append({"kind": "takes", "takes": n, "cites": cite, "text": f"Record {n} takes, then see if the cue came up again."})
    return {"format": FORMAT, "entry_id": facts.get("entry_id"), "items": items, "spacing": SPACING, "label": LABEL,
            "based_on": {"take": latest["take"], "at": latest.get("at")}, "focus": {"measure": fault["measure"], "side": fault["side"]}}


def _numbers_ok(text: str, allowed: set[float], takes: set[int]) -> bool:
    """Numbers in the text (outside quotes) must be allowed; "take n" is a label only for a take the item cites."""
    bare = _TAKE_LABEL.sub(lambda m: " " if int(m.group(1)) in takes else m.group(0), history_guard._outside_quotes(text))
    return all(round(float(n), 3) in allowed for n in _NUMBER.findall(bare))


def _item_problem(item: Any, facts: dict[str, Any], words: Any) -> str | None:
    """The reason one plan item fails the check, or None."""
    if not isinstance(item, dict) or item.get("kind") not in KINDS:
        return "not a plan item Simon has"
    takes = {t["take"]: t for t in facts["takes"] if not t.get("private")}
    cites = item.get("cites")
    if not isinstance(cites, list) or not cites:
        return "no citation"
    allowed: set[float] = set()
    for cite in cites:
        take = takes.get(cite.get("take")) if isinstance(cite, dict) else None
        at_s = cite.get("at_s") if isinstance(cite, dict) else None
        if take is None:
            return "cites a take that was not in the input"
        if not history_guard._num(at_s) or at_s < 0 or (history_guard._num(take.get("duration_s")) and at_s > take["duration_s"]):
            return "cites a time outside the take"
        allowed |= {round(float(at_s), 3), float(take["take"])}
    kind = item["kind"]
    first = takes[cites[0]["take"]]
    if kind == "cue":
        if item.get("cue") not in set(first.get("cues") or []) | {f.get("cue") for f in first["faults"]}:
            return "the cue is not one of the cited take's cues"
        if not history_guard._fault_ok(first, item.get("measure"), item.get("side"), cites[0]["at_s"]):
            return "the cited time is not where that fault was measured"
    elif kind == "section":
        seen = {t.get("section_key") for t in takes.values() if step_of(t.get("section_key"))}
        found = _SECTION.match(item.get("section_key") or "")
        if item.get("section_key") not in seen or not found or item.get("step") != step_of(item["section_key"]) or first.get("section_key") != item["section_key"]:
            return "not a section this movement was practised in"
        allowed |= {float(found.group(2)), float(found.group(3))}
    elif kind == "speed":
        if not isinstance(item.get("speed"), (int, float)) or isinstance(item.get("speed"), bool) or item["speed"] not in SPEEDS or item["speed"] >= 1:
            return "not a slow step speed the ladder has"
        allowed.add(float(item["speed"]))
    else:
        count = item.get("takes")
        if not isinstance(count, int) or isinstance(count, bool) or not 1 <= count <= MAX_TAKES:
            return f"takes must be a whole number from 1 to {MAX_TAKES}"
        allowed.add(float(count))
    text = item.get("text")
    problem = history_guard._rule6(text, SimpleNamespace(words=words)) if isinstance(text, str) else (6, "empty text")
    if problem:
        return problem[1]
    bare = history_guard._outside_quotes(text)
    if kind == "cue" and (history_guard._SIDE_WORD.search(bare) or history_guard._PART_WORD.search(bare)) \
            and not history_guard._named_matches(bare, next(f for f in first["faults"] if f["measure"] == item["measure"] and f["side"] == item["side"])):
        return "names a side or body part that is not the cited fault's"
    return None if _numbers_ok(text, allowed, {c['take'] for c in cites}) else "a number that is not a cited time, take, section, speed or count"


def check(plan: Any, facts: dict[str, Any], words: dict[str, Any] | None = None) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """`(plan with only the items that pass, rejected)`; the plan is None when its cue item does not pass or no item does."""
    shared = history_guard._Words(words)
    rejected: list[dict[str, Any]] = []
    kept = []
    for i, item in enumerate(plan.get("items") if isinstance(plan, dict) and isinstance(plan.get("items"), list) else []):
        problem = _item_problem(item, facts, shared)
        if problem:
            rejected.append({"item": f"items[{i}]", "reason": problem})
        else:
            kept.append(item)
    spacing = plan.get("spacing") if isinstance(plan, dict) else None
    spacing_ok = spacing == SPACING or (isinstance(spacing, str) and history_guard._rule6(spacing, SimpleNamespace(words=shared)) is None
                                        and "streak" not in spacing.lower() and "ready" not in spacing.lower())
    if not any(i["kind"] == "cue" for i in kept):
        return None, rejected
    return {**plan, "items": kept, "spacing": spacing if spacing_ok else SPACING}, rejected


def build(facts: dict[str, Any], words: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """The plan for the latest take's group, every item through `check`; None when there is nothing to plan.

    `facts` is `history_facts.build` over the takes a report may read (private takes left out)."""
    candidate = _candidate(facts)
    if candidate is None:
        return None
    plan, _ = check(candidate, facts, words)
    return plan
