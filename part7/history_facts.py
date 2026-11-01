"""The fact table of a student's takes of one movement, computed with no model (docs/specs/history.md "Facts").

`build(takes)` reads each take's stored `analysis.json` (Part 5's published contract: `faults[].measure`, `side`,
`at_s`, `follower_t_s`, `text_timed`, `cue`, `magnitude_deg`; `score.timeline[].misses[].cue`) and answers
`simon.history.facts.v1`. The same table backs the guard's checks and the fallback report.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from part7 import history_store

FORMAT = "simon.history.facts.v1"
IMPROVED_BELOW = 0.8  # a measure whose size fell to this share of its first size, or less, is "improved"
SUMMARY_LABEL = "Worked out from your stored takes, without the model."
MAX_TRENDS = 5


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _read(path: Path) -> dict[str, Any]:
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _faults(analysis: dict[str, Any]) -> list[dict[str, Any]]:
    """One fault per (measure, side): the largest, in the order Part 5 listed them."""
    best: dict[tuple[str, str], dict[str, Any]] = {}
    for raw in analysis.get("faults") or []:
        if not isinstance(raw, dict) or not isinstance(raw.get("measure"), str):
            continue
        side = raw.get("side") if isinstance(raw.get("side"), str) else "center"
        item = {
            "measure": raw["measure"], "side": side, "at_s": _number(raw.get("at_s")),
            "span": [x for x in (raw.get("follower_t_s") or []) if _number(x) is not None] or None,
            "text_timed": raw.get("text_timed") if isinstance(raw.get("text_timed"), str) else None,
            "cue": raw.get("cue") if isinstance(raw.get("cue"), str) else None,
            "magnitude": _number(raw.get("magnitude_deg")),
        }
        key = (item["measure"], side)
        if key not in best or (item["magnitude"] or 0) > (best[key]["magnitude"] or 0):
            best[key] = item
    return list(best.values())


def _cues(analysis: dict[str, Any]) -> list[str]:
    score = analysis.get("score") if isinstance(analysis.get("score"), dict) else {}
    seen: list[str] = []
    for window in score.get("timeline") or []:
        for miss in (window.get("misses") or []) if isinstance(window, dict) else []:
            cue = miss.get("cue") if isinstance(miss, dict) else None
            if isinstance(cue, str) and cue and cue not in seen:
                seen.append(cue)
    return seen


def _take_row(take: dict[str, Any], analysis: dict[str, Any]) -> dict[str, Any]:
    return {
        "take": take["take"], "at": take.get("at"), "score": take.get("score"), "grade": take.get("grade"),
        "duration_s": take.get("duration_s") if history_store.positive(take.get("duration_s")) else history_store.timeline_end(analysis),
        "faults": _faults(analysis), "cues": _cues(analysis),
    }


def _status(seen: list[dict[str, Any]], latest: int) -> str:
    """`new`, `persistent`, `improved` or `fixed` for one measure given where it showed up."""
    last = seen[-1]
    if last["take"] != latest:
        return "fixed"
    if len(seen) == 1:
        return "new"
    first_size, last_size = seen[0]["magnitude"], last["magnitude"]
    if first_size and last_size is not None and last_size <= first_size * IMPROVED_BELOW:
        return "improved"
    return "persistent"


def _measures(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest = rows[-1]["take"]
    seen: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        for fault in row["faults"]:
            seen.setdefault((fault["measure"], fault["side"]), []).append(
                {"take": row["take"], "at_s": fault["at_s"], "magnitude": fault["magnitude"]})
    return [
        {"measure": measure, "side": side, "present_in": [s["take"] for s in found],
         "status": _status(found, latest), "first": found[0], "last": found[-1]}
        for (measure, side), found in seen.items()
    ]


def build(takes: list[dict[str, Any]], entry_id: str | None = None) -> dict[str, Any]:
    """The fact table for `takes` (oldest first, as `history_store.takes` returns them)."""
    rows = [_take_row(t, _read(t["analysis"])) for t in takes]
    scored = [r for r in rows if _number(r["score"]) is not None]
    best = max(scored, key=lambda r: (r["score"], -r["take"]), default=None)
    entry = entry_id if entry_id is not None else (takes[0].get("entry_id") if takes else None)
    return {
        "format": FORMAT, "entry_id": entry, "takes": rows, "measures": _measures(rows) if rows else [],
        "best": best["take"] if best else None,  # take numbers, as lc-history-meta's guard reads `latest`
        "latest": rows[-1]["take"] if rows else None,
    }


# ----- the summary and trends the fallback report shows ---------------------------------------------------
def _name(measure: str, side: str) -> str:
    words = measure.replace("_", " ")
    return words if side in ("center", "") else f"{side} {words}"


def _trend_text(item: dict[str, Any]) -> str:
    name, first, last = _name(item["measure"], item["side"]), item["first"], item["last"]
    at = f" at {last['at_s']:g} s" if last["at_s"] is not None else ""
    if item["status"] == "new":
        return f"{name} shows in take {last['take']}{at}, not before."
    if item["status"] == "fixed":
        return f"{name} showed in take {last['take']} and is not in the latest take."
    word = "is smaller in" if item["status"] == "improved" else "is still in"
    return f"{name} {word} take {last['take']}{at}; it first showed in take {first['take']}."


def fallback_summary(facts: dict[str, Any]) -> dict[str, Any]:
    """The labelled fact-table summary: first and latest score, the best take."""
    rows = facts["takes"]
    first, last = rows[0], rows[-1]
    best = next((r for r in rows if r["take"] == facts["best"]), None)
    text = f"Take {first['take']} scored {first['score']} and take {last['take']} scored {last['score']}."
    if best and best["take"] not in (first["take"], last["take"]):
        text += f" The best was take {best['take']}, {best['score']}."
    return {"text": text, "cites": [{"take": first["take"]}, {"take": last["take"]}], "source": "fact_table",
            "label": SUMMARY_LABEL}


def fallback_trends(facts: dict[str, Any]) -> list[dict[str, Any]]:
    """Up to five trends straight from the table, persistent first, then new, improved and fixed."""
    order = {"persistent": 0, "new": 1, "improved": 2, "fixed": 3}
    items = sorted(facts["measures"], key=lambda m: order[m["status"]])[:MAX_TRENDS]
    trends = []
    for item in items:
        cite: dict[str, Any] = {"take": item["last"]["take"]}
        if item["last"]["at_s"] is not None:
            cite["at_s"] = item["last"]["at_s"]
        trends.append({"kind": item["status"], "measure": item["measure"], "side": item["side"],
                       "text": _trend_text(item), "cites": [cite], "source": "fact_table"})
    return trends
