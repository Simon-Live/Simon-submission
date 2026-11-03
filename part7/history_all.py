"""Across my movements: the part that needs no model (docs/specs/history-all.md, TICKET-224 AC-1, AC-2, AC-6).

`gather` reads one user's takes of every movement they keep and builds each movement's fact table from the takes a
report may read: a private take is never read, and a rehab-mode take is only counted (it enters no table, so no fault
language can come from it). `cross_table` joins those tables by (measure, side). Facts are computed per movement and
within the movement's own group (section and mode), so nothing is merged across groups or across people. The movements
the user left out are kept in `cross_prefs.json` and are not read.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from part7 import history_facts, history_store, labels

MIN_ENTRIES = 2  # a cross-movement claim needs at least two movements
MSG_NO_OVERLAP = "Nothing has come up in two movements yet, so there is nothing to read across."
READABLE_STATUS = ("persistent", "came_back", "new", "improved", "fixed")


def left_out(state: Path | str, user_id: str) -> list[str]:
    doc = history_store.read_json(history_store.user_dir(state, user_id) / history_store.CROSS_PREFS)
    found = doc.get("left_out") if isinstance(doc, dict) else None
    return sorted({e for e in found or [] if isinstance(e, str) and labels.ENTRY_ID_RE.match(e)})


def set_left_out(state: Path | str, user_id: str, entries: Any) -> list[str]:
    """Save the movements to leave out (ValueError for a bad list) and void the user's cross reports, which read the old set."""
    if not history_store.valid_ids(user_id) or not isinstance(entries, list) or len(entries) > 200 \
            or not all(isinstance(e, str) and labels.ENTRY_ID_RE.match(e) for e in entries):
        raise ValueError("left_out must be a list of movement ids")
    kept = sorted(set(entries))
    with history_store.locked(state):
        if kept == left_out(state, user_id):
            return kept
        history_store.write_json(history_store.user_dir(state, user_id) / history_store.CROSS_PREFS, {"left_out": kept})
        for path in history_store.cross_dir(state, user_id).glob("*.json"):
            path.unlink(missing_ok=True)
    return kept


def readable(takes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The takes a cross report may read: not private, not rehab. An unknown mode counts as readable (it is not rehab)."""
    return [t for t in takes if not t["private"] and t.get("mode") != "rehab"]


def gather(state: Path | str, user_id: str, name_of: Callable[[str], str], *, month: str | None = None) -> list[dict[str, Any]]:
    """One row per movement the user has readable takes of, oldest movement first.

    `{entry_id, name, left_out, takes (readable rows), facts, rehab_takes, taken}`; `taken` is the count of readable
    takes. With `month` ("2026-10") the takes are limited to those recorded in that UTC month. A movement with no readable take is absent."""
    out = []
    skipped = set(left_out(state, user_id))
    for entry in history_store.entries(state, user_id):
        every = history_store.takes(state, user_id, entry)
        if month is not None:
            every = [t for t in every if str(t.get("at") or "").startswith(month)]
        rows = readable(every)
        rehab = [t["at"] for t in every if not t["private"] and t.get("mode") == "rehab"]
        if not rows:
            continue
        out.append({"entry_id": entry, "name": name_of(entry), "left_out": entry in skipped, "takes": rows,
                    "facts": history_facts.build(rows, entry), "taken": len(rows), "rehab_at": rehab,
                    "rehab_takes": len(rehab)})
    out.sort(key=lambda e: (str(e["takes"][0]["at"] or ""), e["entry_id"]))  # first take date: new takes mostly append to a prompt
    return out


def included(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [e for e in entries if not e["left_out"]]


def _cell(entry: dict[str, Any], measure: dict[str, Any]) -> dict[str, Any]:
    return {"entry_id": entry["entry_id"], "name": entry["name"], "status": measure["status"], "takes": measure["present_in"],
            "first": measure["first"], "last": measure["last"]}


def cross_table(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rows by (measure, side) over the given movements. `across` is how many movements show the measure; rows seen in
    more movements come first, then by name. `unverified` measures stay (nobody says they are gone)."""
    cells: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for entry in entries:
        for measure in entry["facts"]["measures"]:
            cells.setdefault((measure["measure"], measure["side"]), []).append(_cell(entry, measure))
    rows = [{"measure": m, "side": s, "across": len(found), "entries": found} for (m, s), found in cells.items()]
    rows.sort(key=lambda r: (-r["across"], r["measure"], r["side"]))
    return rows


def across(table: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The rows that show in two or more movements: the ones a cross-movement claim may be about."""
    return [r for r in table if r["across"] >= MIN_ENTRIES]


def public_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """What the page shows of a movement a report reads (or could read): never a take or a fault."""
    return {"entry_id": entry["entry_id"], "name": entry["name"], "takes": entry["taken"], "rehab_takes": entry["rehab_takes"],
            "left_out": entry["left_out"]}


def blocker(read: list[dict[str, Any]]) -> str | None:
    """Why a cross report cannot run over these (included) movements, or None: fewer than 2, or no measure shared by 2 or more.
    The one rule the page, the table route and the cross job all use."""
    if len(read) < MIN_ENTRIES:
        return "Reading across needs at least 2 movements that are not left out."
    return None if across(cross_table(read)) else MSG_NO_OVERLAP
