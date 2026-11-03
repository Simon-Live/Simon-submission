"""The blind referee (docs/specs/muse-fix.md, TICKET-280 AC-4): which render moves more like the reference?

The trainer render goes up with the original and the corrected render in a seeded random order, labelled A and B. The
key (which letter holds the corrected render) comes from the stored seed, is kept in the record and is never sent: the
request holds the letters and the images only. k is how many times the model picked the corrected render in n trials;
p is the one-sided binomial tail P(X >= k) at chance 0.5, and the badge shows only when p < 0.05.
"""

from __future__ import annotations

import math
import random
import secrets
from typing import Any

from part7 import muse_fix_api

BADGE_P = 0.05


def corrected_letter(seed: int) -> str:
    """The letter ("A" or "B") that holds the corrected render for `seed`; a pure function of the stored seed."""
    return "A" if random.Random(int(seed)).random() < 0.5 else "B"


def new_seed() -> int:
    return secrets.randbits(53)


def binomial_p(k: int, n: int) -> float:
    """P(X >= k) for X ~ Binomial(n, 0.5)."""
    if n <= 0 or k <= 0:
        return 1.0
    if k > n:
        return 0.0
    return min(1.0, sum(math.comb(n, i) for i in range(k, n + 1)) / 2 ** n)


def trial(reference: bytes, original: bytes, corrected: bytes, *, seed: int | None = None, **api: Any) -> dict[str, Any]:
    """One blind comparison. `api` goes to `muse_fix_api.referee` (transport, state, keys_dir, clock).

    Returns the record: `{seed, key, choice, picked_corrected, model, cost_usd, call}`."""
    seed = new_seed() if seed is None else int(seed)
    key = corrected_letter(seed)
    a, b = (corrected, original) if key == "A" else (original, corrected)
    out = muse_fix_api.referee(reference, a, b, **api)
    return {"seed": seed, "key": key, "choice": out["choice"], "picked_corrected": out["choice"] == key,
            "model": out["model"], "cost_usd": out["cost_usd"], "call": out["call"]}


def summary(trials: list[dict[str, Any]]) -> dict[str, Any]:
    """`{n, k, p, badge}` over trial records; the badge is true only when p < 0.05."""
    n = len(trials)
    k = sum(1 for t in trials if t.get("picked_corrected") is True)
    p = binomial_p(k, n)
    return {"n": n, "k": k, "p": round(p, 6), "badge": n > 0 and p < BADGE_P}
