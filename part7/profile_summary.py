"""What the profile page lists beside the form (TICKET-231 AC-5 and AC-6; docs/specs/profile.md).

`entries`: the trainer entries the caller owns, each with the count and date of the last follower take (the same takes
the teacher page counts, so a private-mode take is counted nowhere). `movements`: the movements the caller kept takes
of, with the count and the date of the last one, private takes left out. `summary`: built only from the fact table
(`history_facts`), grouped like with like (section, mode, score version): takes kept, movements, first and latest score
and how many measures came back. No model call, no readiness or symmetry figure. Retention off: `kept` is false and
there are no groups, so the page says nothing was kept rather than showing zeros.
"""

from __future__ import annotations

from typing import Any, Callable

from part7 import history_facts, history_store, teacher_stats


def _score(value: Any) -> float | int | None:
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def groups(by_entry: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """The like-with-like groups of the caller's takes. `by_entry` maps an entry id to its takes, oldest first, as
    `history_store.takes` returns them. A private take, a take with no person found and a take whose section, mode or
    score version is unknown are in no group."""
    found: dict[tuple[str, str, str], dict[str, Any]] = {}
    for entry, takes in by_entry.items():
        kept = [t for t in takes if not t.get("private")]
        rows = history_facts.table(kept, entry)["takes"] if kept else []
        per_group: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
        for row in rows:
            key = (row.get("section_key"), row.get("mode"), row.get("score_version"))
            if row["no_person"] or row.get("reference", "teacher") != "teacher" or not all(isinstance(part, str) and part for part in key):
                continue
            per_group.setdefault(key, []).append(row)
        for key, members in per_group.items():
            group = found.setdefault(key, {"section": key[0], "mode": key[1], "score_version": key[2], "takes": 0, "entries": set(),
                                           "scored": [], "came_back": 0})
            group["takes"] += len(members)
            group["entries"].add(entry)
            group["scored"] += [(str(r.get("at") or ""), entry, r["take"], _score(r.get("score"))) for r in members]
            group["came_back"] += sum(1 for m in history_facts.measures(members) if m["status"] == "came_back")
    out = []
    for group in found.values():
        scores = [s for *_, s in sorted(group.pop("scored"), key=lambda x: x[:3]) if s is not None]
        movement_count = len(group.pop("entries"))  # popped before the copy below: a set is not JSON
        out.append({**group, "movements": movement_count, "first_score": scores[0] if scores else None,
                    "latest_score": scores[-1] if scores else None})
    return sorted(out, key=lambda g: (-g["takes"], g["section"], g["mode"], g["score_version"]))


def movements(state: Any, user: str, name_of: Callable[[str], str]) -> list[dict[str, Any]]:
    """The movements the caller kept takes of: id, name, count and the date of the last take (private takes not counted)."""
    out = []
    for entry in history_store.entries(state, user):
        found = [t for t in history_store.takes(state, user, entry) if not t["private"]]
        if found:
            out.append({"entry_id": entry, "name": name_of(entry), "count": len(found), "last_at": found[-1]["at"]})
    return out


def entries(jobs_root: Any, owned: list[dict[str, Any]], name_of: Callable[[str], str]) -> list[dict[str, Any]]:
    """The caller's trainer entries (`owned`, from the identity store) with the count and date of follower takes."""
    out = []
    for entry in owned:
        takes = teacher_stats.collect(jobs_root, entry["entry_id"])["takes"]
        out.append({"entry_id": entry["entry_id"], "name": name_of(entry["entry_id"]), "count": len(takes),
                    "last_at": takes[-1]["at"] if takes else None})
    return out


def capped(rows: list[dict[str, Any]]) -> bool:
    """True when an entry's count reached the newest-takes cap of the teacher page, so the page says the counts are partial."""
    return any(r["count"] >= teacher_stats.TAKES_MAX for r in rows)


def summary(state: Any, user: str, is_capped: bool = False) -> dict[str, Any]:
    """`{kept, groups, capped}`; nothing is read when the caller did not opt in to keeping takes. `capped` is `capped(entries)`."""
    if not history_store.retention_opt_in(state, user):
        return {"kept": False, "groups": [], "capped": is_capped}
    by_entry = {e: history_store.takes(state, user, e) for e in history_store.entries(state, user)}
    return {"kept": True, "groups": groups(by_entry), "capped": is_capped}
