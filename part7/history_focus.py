"""The focus of the next take and what came of it (docs/specs/history-all.md "Focus", TICKET-223 AC-1, AC-2).

`focus` is what the student worked on last time: the cached report's focus (measure, side, cue, cites) when a report
exists and still stands on the readable takes, else the fact table's most persistent measure that carries a cue, labelled
"worked out from your stored takes". It names the take it comes from and the date of that take, so a movement
re-recorded since shows its age. `after` answers, for a take just made (`job`), whether that cue came up again, at what
second and whether the fault is larger or smaller, using `history_facts.NOISE_BAND` (TICKET-214): a change inside the band
is "not_enough", never "larger" or "smaller". Both read only readable takes (never private, never rehab) and no model is called.
"""

from __future__ import annotations

from typing import Any

from part7 import history_facts, history_plan, history_since

FORMAT = "simon.history.focus.v1"
LABEL = "Worked out from your stored takes."
CHANGES = ("larger", "smaller", "not_enough")


def _focus_doc(facts: dict[str, Any], source: str, take: dict[str, Any], fault: dict[str, Any], cue: str, at_s: float) -> dict[str, Any]:
    return {"format": FORMAT, "entry_id": facts.get("entry_id"), "source": source, "label": LABEL if source == "fact_table" else "",
            "measure": fault["measure"], "side": fault["side"], "cue": cue, "cites": [{"take": take["take"], "at_s": at_s}],
            "take": take["take"], "at_s": at_s, "at": take.get("at"), "date": history_since._date(take.get("at"))}


def _from_report(report: Any, facts: dict[str, Any]) -> dict[str, Any] | None:
    """The cached report's focus, only when its cited take is a readable take that carries that very cue and fault."""
    item = report.get("focus") if isinstance(report, dict) else None
    cites = item.get("cites") if isinstance(item, dict) else None
    if not isinstance(item, dict) or not isinstance(item.get("cue"), str) or not isinstance(cites, list) or not cites or not isinstance(cites[0], dict):
        return None
    at_s = cites[0].get("at_s")
    take = next((t for t in facts["takes"] if t["take"] == cites[0].get("take")), None)
    if take is None or take.get("private") or take.get("mode") == "rehab" or history_facts._number(at_s) is None:
        return None
    fault = history_facts.fault_of(take, str(item.get("measure")), str(item.get("side")))
    if fault is None or item["cue"] not in set(take.get("cues") or []) | {fault.get("cue")}:
        return None
    return _focus_doc(facts, "report", take, fault, item["cue"], at_s)


def _from_table(facts: dict[str, Any]) -> dict[str, Any] | None:
    picked = history_plan.focus_fault(facts)
    if picked is None:
        return None
    _, take, fault = picked
    return _focus_doc(facts, "fact_table", take, fault, fault["cue"], fault["at_s"])


def focus(facts: dict[str, Any], report: Any = None) -> dict[str, Any] | None:
    """The focus of `facts` (readable takes only): the report's when it stands, else the table's; None with nothing to carry."""
    latest = next((t for t in facts["takes"] if t["take"] == facts.get("latest")), None)
    if latest is None or latest.get("private") or latest.get("mode") == "rehab":
        return None
    return _from_report(report, facts) or _from_table(facts)


def _change(then: dict[str, Any], now: dict[str, Any]) -> str:
    """`larger`, `smaller` or `not_enough` (inside the noise band, a different unit, or no size to compare)."""
    unit = now.get("unit")
    if unit is None or unit != then.get("unit") or then.get("size") is None or now.get("size") is None:
        return "not_enough"
    delta = now["size"] - then["size"]
    if abs(delta) <= history_facts.NOISE_BAND[unit]:
        return "not_enough"
    return "larger" if delta > 0 else "smaller"


def after(facts: dict[str, Any], seen: dict[str, Any], job: str) -> dict[str, Any] | None:
    """What the take `job` says about `seen`, the focus from the takes before it; `facts` holds the readable takes up to `job`.

    None when the take is not like the focused one (another section or mode), has no person, or is not a readable take.
    `came_up` is None when the take did not compare that moment, so nothing can be said."""
    row = next((t for t in facts["takes"] if t.get("job_id") == job), None)
    then_take = next((t for t in facts["takes"] if t["take"] == seen["take"]), None)
    if row is None or then_take is None or not row.get("in_group") or not then_take.get("in_group") or row["take"] == then_take["take"]:
        return None
    then = history_facts.fault_of(then_take, seen["measure"], seen["side"])
    now = history_facts.fault_of(row, seen["measure"], seen["side"])
    unit = then["unit"] if then else None
    out: dict[str, Any] = {"job_id": job, "take": row["take"], "came_up": None, "at_s": None, "change": None,
                           "band": {"unit": unit, "value": history_facts.NOISE_BAND[unit]} if unit else None}
    if now is not None:
        out.update(came_up=True, at_s=now["at_s"], change=_change(then or {}, now))
    elif history_facts.covers(row, seen["at_s"], seen["measure"], seen["side"]):
        out["came_up"] = False
    return out
