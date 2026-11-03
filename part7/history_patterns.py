"""The pattern finder's deterministic side (docs/specs/history-patterns.md, TICKET-221).

`count_table` counts, with no model, how each (measure, side) shows across the takes and across reps, and how the
tempo bands fall. The model is asked for recurring patterns and states its counts as fields (`takes_with`, `takes_total`,
`from_rep`, `tempo_band`); `check` keeps a pattern only when those fields equal the table, every cite is a real take and a
second inside a span measured for that take, and the wording passes the history guard plus the extra word rules here.
`fallback` is the same table said in plain sentences, labelled as worked out without the model.
"""

from __future__ import annotations

import json
import re
from typing import Any

from part7 import history_facts, history_guard, history_prompt

FEATURE = "pattern"
PROMPT_VERSION = "pattern.v1"
SCHEMA_NAME = "simon_patterns_v1"
KINDS = ("recurs", "starts_at_rep", "rep_drift", "tempo")
BANDS = ("slow_down", "speed_up", "close")
SLOW_BELOW, FAST_ABOVE = 0.85, 1.15      # score.tempo.ratio: below means Part 5 says slow down, above says speed up
DROP_POINTS = 10.0                       # a rep whose mean score is this far under rep 1 starts the drift
MAX_PATTERNS = 5
MIN_TAKES = 3
MAX_LINE = history_guard.MAX_LINE

# Wording this feature never uses (AC-4), on top of the history guard's banned and praise lists.
_WORDS = re.compile(r"\b(?:fatigu\w*|tired\w*|exhaust\w*|stop(?:s|ped|ping)?|rest(?:s|ed|ing)?)\b", re.I)
_MORE_REPS = re.compile(r"\b(?:more|extra|another|additional|add|increase)\b[^.]{0,20}\breps?\b", re.I)

QUESTION = (
    "Task: find recurring patterns across these takes. Use the computed table below for every count. A pattern is one of:\n"
    "- recurs: one measure and side that shows in several takes (takes_with of takes_total).\n"
    "- starts_at_rep: a measure and side that shows only from one rep onward (from_rep), in every take that has it.\n"
    "- rep_drift: the score of the later reps falls under the first rep (from_rep is the first rep that falls).\n"
    "- tempo: takes with the same tempo band (tempo_band: slow_down, speed_up or close), counted as takes_with of takes_total.\n"
    "Copy takes_with, takes_total, from_rep and tempo_band from the table, or null when they do not apply. Give at least "
    "2 cites per pattern, each a take and a second (at_s) inside a span measured for that take. At most 5 patterns, "
    "strongest first. Say 'differs more from the example', never why. Do not use the words fatigue, stop or rest, and "
    "never suggest more reps."
)


def _obj(**props: Any) -> dict[str, Any]:
    return history_prompt._obj(**props)


_NULL_INT = {"type": ["integer", "null"]}
_NULL_STR = {"type": ["string", "null"]}
SCHEMA: dict[str, Any] = _obj(patterns={"type": "array", "items": _obj(
    kind={"type": "string", "enum": list(KINDS)}, measure=_NULL_STR, side=_NULL_STR, tempo_band=_NULL_STR,
    takes_with=_NULL_INT, takes_total=_NULL_INT, from_rep=_NULL_INT,
    text={"type": "string"}, cites=history_prompt._CITES)})


def band(ratio: Any) -> str | None:
    if not history_prompt._num(ratio):
        return None
    return "slow_down" if ratio < SLOW_BELOW else "speed_up" if ratio > FAST_ABOVE else "close"


def count_table(items: list[dict[str, Any]]) -> dict[str, Any]:
    """The computed table over `items` (allowlisted evidence of the takes of one section and mode, oldest first)."""
    seen: dict[tuple[str, str], dict[str, Any]] = {}
    for it in items:
        for f in it.get("faults") or []:
            rec = seen.setdefault((f["measure"], f.get("side") or "center"), {"takes": [], "reps": {}})
            if it["take"] not in rec["takes"]:
                rec["takes"].append(it["take"])
            for rep in f.get("reps") or []:
                rec["reps"].setdefault(rep, set()).add(it["take"])
    measures = [{"measure": m, "side": s, "takes_with": len(r["takes"]), "takes_total": len(items), "takes": r["takes"],
                 "first_rep": min(r["reps"]) if r["reps"] else None,
                 "rep_takes": {str(k): len(v) for k, v in sorted(r["reps"].items())}}
                for (m, s), r in sorted(seen.items())]
    bands: dict[str, list[int]] = {}
    for it in items:
        b = band((it.get("score") or {}).get("tempo_ratio"))
        if b:
            bands.setdefault(b, []).append(it["take"])
    by_rep: dict[int, list[float]] = {}
    for it in items:
        for n, value in enumerate((it.get("score") or {}).get("per_rep") or [], 1):
            by_rep.setdefault(n, []).append(value)
    means = {n: round(sum(v) / len(v), 1) for n, v in by_rep.items() if len(v) >= 2}
    drop = next((n for n in sorted(means) if n > 1 and 1 in means and means[n] <= means[1] - DROP_POINTS), None)
    return {"takes_total": len(items), "measures": measures,
            "tempo_bands": {k: {"takes": v, "takes_with": len(v), "takes_total": len(items)} for k, v in sorted(bands.items())},
            "rep_scores": {str(n): m for n, m in sorted(means.items())}, "rep_drift_from": drop}


def question_blocks(table: dict[str, Any]) -> list[str]:
    return ["Computed table (JSON data, counts you must copy): " + json.dumps(table, sort_keys=True, separators=(",", ":")),
            QUESTION]


# ----- the check ---------------------------------------------------------------------------------------------
Problem = tuple[int, str]
NUMBER_RULE = 4


def _table_claim(item: dict[str, Any], table: dict[str, Any]) -> Problem | None:
    """Count rule: every count field equals the computed table."""
    kind = item.get("kind")
    if kind in ("recurs", "starts_at_rep"):
        row = next((m for m in table["measures"] if (m["measure"], m["side"]) == (item.get("measure"), item.get("side"))), None)
        if row is None:
            return 3, "the table has no such measure and side"
        if (item.get("takes_with"), item.get("takes_total")) != (row["takes_with"], row["takes_total"]) or row["takes_with"] < 2:
            return NUMBER_RULE, "the take count is not the table's"
        if kind == "starts_at_rep" and (item.get("from_rep") != row["first_rep"] or not row["first_rep"] or row["first_rep"] < 2):
            return NUMBER_RULE, "the rep is not the table's first rep for that fault"
        if kind == "recurs" and item.get("from_rep") is not None:
            return NUMBER_RULE, "a recurring fault has no rep"
        return None
    if kind == "rep_drift":
        if table["rep_drift_from"] is None or item.get("from_rep") != table["rep_drift_from"] or item.get("measure") or item.get("takes_with"):
            return NUMBER_RULE, "the rep is not the table's drift rep"
        return None
    if kind == "tempo":
        row = table["tempo_bands"].get(item.get("tempo_band"))
        if row is None or (item.get("takes_with"), item.get("takes_total")) != (row["takes_with"], row["takes_total"]) or row["takes_with"] < 2:
            return NUMBER_RULE, "the tempo count is not the table's"
        return None
    return 3, "not a pattern kind"


def _in_span(item: dict[str, Any], cites: list[dict[str, Any]], ctx: Any, rows: dict[int, dict[str, Any]]) -> Problem | None:
    for c in cites:
        if "at_s" not in c:
            return 1, "a cite has no time"
        if item.get("measure"):
            if not history_guard._fault_ok(ctx.takes[c["take"]], item["measure"], item["side"], c["at_s"]):
                return 2, "a time is not where the analysis measured that fault"
        elif not history_facts.covers(rows[c["take"]], c["at_s"]):
            return 2, "a time is outside the windows measured for that take"
    return None


def _numbers_ok(text: str, item: dict[str, Any], cites: list[dict[str, Any]], ctx: Any) -> bool:
    cited = {c["take"] for c in cites}
    allowed = {round(float(c["at_s"]), 3) for c in cites if "at_s" in c}
    allowed |= {float(item[k]) for k in ("takes_with", "takes_total", "from_rep") if isinstance(item.get(k), int)}
    allowed |= {round(float(ctx.takes[t]["score"]), 3) for t in cited if history_prompt._num(ctx.takes[t].get("score"))}

    def labels(match: re.Match[str]) -> str:
        nums = [int(n) for n in re.findall(r"\d+", match.group(1))]
        return "take" if all(n in cited for n in nums) else match.group(0)

    bare = history_guard._TAKES.sub(labels, history_guard._outside_quotes(text))
    return all(round(float(t), 3) in allowed for t in history_guard._NUMBER.findall(bare))


def _text_problem(item: dict[str, Any], cites: list[dict[str, Any]], ctx: Any) -> Problem | None:
    text = item.get("text")
    found = history_guard._rule6(text, ctx)
    if found:
        return found
    if _WORDS.search(text) or _MORE_REPS.search(text):
        return 6, "uses a word or advice this feature does not use"
    if not _numbers_ok(text, item, cites, ctx):
        return NUMBER_RULE, "a number that is not a cited time, a cited score or a count from the table"
    named = {"measure": item.get("measure"), "side": item.get("side"), "text": text}
    return history_guard._rule9("trend", named, cites, ctx)


def _judge(item: Any, ctx: Any, table: dict[str, Any], rows: dict[int, dict[str, Any]]) -> tuple[dict[str, Any] | None, Problem | None]:
    if not isinstance(item, dict):
        return None, (1, "not an object")
    cites, problem = history_guard._cites(item.get("cites"), ctx)
    if not problem and len({(c["take"], c.get("at_s")) for c in cites}) < 2:
        problem = (1, "fewer than 2 distinct cites")
    problem = problem or _table_claim(item, table) or _in_span(item, cites, ctx, rows) or _text_problem(item, cites, ctx)
    if problem:
        return None, problem
    out = {k: item.get(k) for k in ("kind", "measure", "side", "tempo_band", "takes_with", "takes_total", "from_rep", "text")}
    return {**out, "cites": cites, "source": "model"}, None


def check(answer: Any, facts: dict[str, Any], table: dict[str, Any], words: dict[str, Any] | None = None,
          ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """`(kept, rejected)` for the model's `{patterns: [...]}`. `facts` is the fact table of the takes sent."""
    ctx = history_guard._Context(facts, None, words)
    rows = {r["take"]: r for r in facts.get("takes") or []}
    doc = history_guard.parse_answer(answer) or {}
    kept: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for i, item in enumerate(doc.get("patterns") if isinstance(doc.get("patterns"), list) else []):
        clean, problem = _judge(item, ctx, table, rows) if len(kept) < MAX_PATTERNS else (None, (0, f"more than {MAX_PATTERNS} items"))
        if clean:
            kept.append(clean)
        else:
            rejected.append({"item": f"patterns[{i}]", "rule": problem[0] or None, "reason": problem[1]})
    return kept, rejected


# ----- no model ---------------------------------------------------------------------------------------------
def _name(measure: str, side: str) -> str:
    return history_facts._name(measure, side)


def fallback(table: dict[str, Any], facts: dict[str, Any]) -> list[dict[str, Any]]:
    """The table as patterns: a measure that shows in 2 or more takes, with the first two takes it shows in cited."""
    rows = {r["take"]: r for r in facts.get("takes") or []}
    out = []
    for m in sorted(table["measures"], key=lambda m: -m["takes_with"]):
        if m["takes_with"] < 2:
            continue
        cites = []
        for n in m["takes"][:2]:
            fault = history_facts.fault_of(rows[n], m["measure"], m["side"]) if n in rows else None
            if fault and fault["at_s"] is not None:
                cites.append({"take": n, "at_s": fault["at_s"]})
        if len(cites) < 2:
            continue
        out.append({"kind": "recurs", "measure": m["measure"], "side": m["side"], "tempo_band": None, "takes_with": m["takes_with"],
                    "takes_total": m["takes_total"], "from_rep": None, "cites": cites, "source": "fact_table",
                    "text": f"{_name(m['measure'], m['side'])} shows in {m['takes_with']} of {m['takes_total']} takes."})
        if len(out) == MAX_PATTERNS:
            break
    return out
