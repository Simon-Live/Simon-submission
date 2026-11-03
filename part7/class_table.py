"""The class table of the teacher page (docs/specs/class-table.md; TICKET-226 phase 1, TICKET-273 AC-2). No model call.

`build(found, owners, now)` turns the takes `teacher_stats` already read for one movement (private takes left out, at
most `teacher_stats.TAKES_MAX`, oldest first) into four facts: the cue most followers met (counted once per follower),
the takes in the last 7 days, the follower count and, for the entry's owner only, each returning follower's
first-to-latest score change.

A follower is the signed-in account that owns a take (`identity.follow_owners`); a take made signed out cannot be tied
to anyone, so it is a follower of its own. A seeded take (`synthetic: true`, tools/seed_class.py) may name its seeded
follower instead. The key never leaves this module: a row carries `n`, the follower's 1-based position by first take,
which comes from no account or job value (the same rule as a take's `n`, teacher-dashboard.md "Privacy").
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

WINDOW_DAYS = 7
FOLLOWERS_MAX = 20  # rows of `followers`: the followers whose latest take is newest


def _when(at: Any) -> datetime | None:
    if not isinstance(at, str) or not at:
        return None
    try:
        found = datetime.fromisoformat(at.replace("Z", "+00:00"))
    except ValueError:
        return None
    return found if found.tzinfo else found.replace(tzinfo=timezone.utc)


def follower_key(take: Mapping[str, Any], owners: Mapping[str, str]) -> str:
    """Who made `take`, for grouping only: the owning account, else the seeded follower, else the take itself."""
    job = str(take.get("_folder") or "")
    if job in owners:
        return "u:" + owners[job]
    seed = take.get("_seed_follower")
    if take.get("_synthetic") is True and isinstance(seed, str) and seed:
        return "s:" + seed
    return "j:" + job


def _top_cue(groups: dict[str, list[Mapping[str, Any]]]) -> dict[str, Any] | None:
    counts: dict[str, int] = {}
    for takes in groups.values():
        for text in {c for t in takes for c in t.get("_cues") or []}:
            counts[text] = counts.get(text, 0) + 1
    if not counts:
        return None
    text = min(counts, key=lambda c: (-counts[c], c))  # ties go to the first in text order: the answer is stable
    return {"text": text, "followers": counts[text]}


def _change(n: int, takes: list[Mapping[str, Any]]) -> dict[str, Any]:
    first, latest = takes[0]["score"], takes[-1]["score"]
    return {"n": n, "takes": len(takes), "first": first, "latest": latest, "delta": round(latest - first, 1), "_at": takes[-1].get("at") or ""}


def _rows(groups: dict[str, list[Mapping[str, Any]]]) -> list[dict[str, Any]]:
    rows = [_change(n, takes) for n, takes in enumerate(groups.values(), start=1) if len(takes) >= 2]
    kept = sorted(rows, key=lambda r: r["_at"], reverse=True)[:FOLLOWERS_MAX]
    return [{k: v for k, v in r.items() if k != "_at"} for r in sorted(kept, key=lambda r: r["n"])]


def build(found: list[Mapping[str, Any]], owners: Mapping[str, str] | None = None, now: datetime | None = None,
          with_followers: bool = False) -> dict[str, Any]:
    """`{follower_count, takes_7d, window_days, top_cue, seeded}` from oldest-first takes, class-level only.

    `followers` (the per-follower rows) is added only with `with_followers`, which the route sets for the entry's owner
    alone (TICKET-273 decision 2026-11-02, TICKET-226's owner-only plan): anyone else never gets the key at all."""
    owners = owners or {}
    now = now or datetime.now(timezone.utc)
    groups: dict[str, list[Mapping[str, Any]]] = {}
    for take in found:  # dicts keep insertion order: followers come out in the order of their first take
        groups.setdefault(follower_key(take, owners), []).append(take)
    cutoff = now - timedelta(days=WINDOW_DAYS)
    recent = sum(1 for t in found if (when := _when(t.get("at"))) is not None and cutoff <= when <= now)
    table = {
        "follower_count": len(groups),
        "takes_7d": recent,
        "window_days": WINDOW_DAYS,
        "top_cue": _top_cue(groups),
        "seeded": any(t.get("_synthetic") is True for t in found),
    }
    return {**table, "followers": _rows(groups)} if with_followers else table
