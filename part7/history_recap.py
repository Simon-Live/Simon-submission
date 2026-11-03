"""The deterministic part of the monthly recap (docs/specs/history-all.md "Monthly recap", TICKET-224 AC-5, AC-6).

`build(entries, month)` counts what the stored takes show for one UTC month ("2026-10"): days practised, takes, movements,
records and the faults that went (gone in a take of the month that compared the moment), plus a table-backed `next_focus`.
No model. Rehab-mode takes appear only as a count, private takes are not here at all (`history_all.gather` never returns
them). `offer(...)` is the start-of-month offer: in the first days of a month, last month's recap if it has takes.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from part7 import history_all, history_facts, shown_score

FORMAT = "simon.history.recap.v1"
OFFER_DAYS = 7  # the recap of last month is offered on days 1 to 7 (UTC)
MONTH_LEN = 7   # "2026-10"
_FOCUS_ORDER = {"persistent": 0, "came_back": 1, "new": 2, "improved": 3}


def utc_now() -> datetime:
    """Now in UTC; tests replace this to pin a month boundary."""
    return datetime.now(timezone.utc)


def month_of(stamp: Any) -> str | None:
    text = stamp if isinstance(stamp, str) else ""
    return text[:MONTH_LEN] if len(text) >= 10 and text[4] == "-" and text[:4].isdigit() and text[5:7].isdigit() else None


def valid_month(value: Any) -> bool:
    return isinstance(value, str) and len(value) == MONTH_LEN and value[4] == "-" and value[:4].isdigit() and value[5:].isdigit() and 1 <= int(value[5:]) <= 12


def previous_month(month: str) -> str:
    year, number = int(month[:4]), int(month[5:])
    return f"{year - 1}-12" if number == 1 else f"{year}-{number - 1:02d}"


def this_month(now: datetime) -> str:
    return f"{now.year:04d}-{now.month:02d}"


def label(month: str) -> str:
    return datetime(int(month[:4]), int(month[5:]), 1, tzinfo=timezone.utc).strftime("%B %Y")


def offer(entries: list[dict[str, Any]], now: datetime) -> dict[str, Any] | None:
    """`{month, label, takes}` for last month on days 1 to 7 when it has readable takes, else None."""
    if now.day > OFFER_DAYS:
        return None
    last = previous_month(this_month(now))
    count = sum(1 for e in entries for t in e["takes"] if month_of(t.get("at")) == last)
    return {"month": last, "label": label(last), "takes": count} if count else None


def default_month(entries: list[dict[str, Any]], now: datetime) -> str:
    found = offer(entries, now)
    return found["month"] if found else this_month(now)


def _records(entry: dict[str, Any], month: str) -> list[dict[str, Any]]:
    """A take of the month whose shown measure (one-letter.md L3) is strictly above every earlier take of its group on
    the same scale; the record carries the shown score the page words it with."""
    rows = [r for r in entry["facts"]["takes"] if history_facts.group_of(r) and isinstance(r.get("score"), (int, float))]
    out = []
    for i, row in enumerate(rows):
        earlier = [r for r in rows[:i] if history_facts.same_scale(row, r)]
        if month_of(row.get("at")) == month and earlier and shown_score.rank_of(row) > max(shown_score.rank_of(r) for r in earlier):
            out.append({"entry_id": entry["entry_id"], "name": entry["name"], "take": row["take"], "score": row["score"], "shown": row.get("shown")})
    return out


def _gone(entry: dict[str, Any], month: str) -> list[dict[str, Any]]:
    """Faults whose absence a take of this month proved: the status is `fixed` and the proving take is in the month."""
    facts, out = entry["facts"], []
    group = [r for r in facts["takes"] if r.get("in_group")]
    for measure in facts["measures"]:
        if measure["status"] != "fixed":
            continue
        trail = history_facts.states(group, measure["measure"], measure["side"])
        last_seen = max(i for i, (_, mark) in enumerate(trail) if mark == "p")
        proof = next((r for r, mark in trail[last_seen:] if mark == "a"), None)
        if proof is not None and month_of(proof.get("at")) == month:
            out.append({"entry_id": entry["entry_id"], "name": entry["name"], "measure": measure["measure"], "side": measure["side"],
                        "take": proof["take"]})
    return out


def _next_focus(entries: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The measure still there in the most movements (then the most persistent kind), from the tables."""
    best: tuple[Any, ...] | None = None
    pick: dict[str, Any] | None = None
    for row in history_all.cross_table(entries):
        live = [c for c in row["entries"] if c["status"] in _FOCUS_ORDER]
        if not live:
            continue
        rank = (-len(live), min(_FOCUS_ORDER[c["status"]] for c in live), row["measure"], row["side"])
        if best is None or rank < best:
            best = rank
            pick = {"measure": row["measure"], "side": row["side"], "movements": len(live), "source": "fact_table",
                    "cites": [{"entry": c["entry_id"], "take": c["last"]["take"], "at_s": c["last"]["at_s"]} for c in live]}
    return pick


def build(entries: list[dict[str, Any]], month: str) -> dict[str, Any]:
    """`entries` are all the movements `history_all.gather` found (the person's full history, left-out ones flagged).

    The counts read the movements not left out, takes recorded in `month` only."""
    shown = history_all.included(entries)
    inside = [(e, t) for e in shown for t in e["takes"] if month_of(t.get("at")) == month]
    days = {str(t["at"])[:10] for _, t in inside}
    names = {e["entry_id"]: e["name"] for e, _ in inside}
    return {
        "format": FORMAT, "month": month, "label": label(month),
        "days": len(days), "takes": len(inside), "movements": [{"entry_id": k, "name": v} for k, v in sorted(names.items())],
        "rehab_takes": sum(1 for e in shown for at in e["rehab_at"] if month_of(at) == month),
        "records": [r for e in shown for r in _records(e, month)],
        "faults_gone": [g for e in shown for g in _gone(e, month)],
        "next_focus": _next_focus(shown) if inside else None,
        "entries": [history_all.public_entry(e) for e in entries],
    }
