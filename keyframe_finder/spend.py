"""Running cost of Meta Model API calls made from this repo.

Warn at $5, then every $5 after that ($10, $15, ...). The ledger is the sum of
calls this project records, priced from the published list rates. It is not
Meta's invoice for the whole account.
"""

import contextlib
import fcntl
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / ".meta-spend.json"
STEP_USD = 5.0

# USD. Token rates are per 1,000,000 tokens. Frame and image rates are per unit.
RATES = {
    "sam-3.1": {"frame": 0.20 / 1000, "image": 2.50 / 1000},
    "muse-spark-1.3": {
        "input_mtok": 1.25,
        "cached_input_mtok": 0.15,
        "output_mtok": 4.25,
    },
    "muse-spark-1.3-contributor": {
        "input_mtok": 0.10,
        "cached_input_mtok": 0.002,
        "output_mtok": 0.20,
    },
    "muse-wonder-1.0": {
        "input_mtok": 4.00,
        "cached_input_mtok": 0.20,
        "output_mtok": 20.00,
    },
    "muse-voice-transcribe-1.0": {"hour": 0.18},
}


def _load():
    if not LEDGER.exists():
        return {"usd": 0.0, "warned_usd": [], "entries": []}
    return json.loads(LEDGER.read_text(encoding="utf-8"))


def _save(ledger):
    """Write the ledger whole, by a rename, so a reader never sees half a file."""
    tmp = LEDGER.with_name(LEDGER.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, LEDGER)


@contextlib.contextmanager
def _locked():
    """One writer at a time (TICKET-380 review): overlapping takes share the ledger, and a read, change and write
    without a lock let one run's record overwrite another's."""
    with open(LEDGER.with_name(LEDGER.name + ".lock"), "a", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def thresholds_reached(usd):
    if usd < STEP_USD:
        return []
    last = int(usd // STEP_USD) * int(STEP_USD)
    return list(range(int(STEP_USD), last + 1, int(STEP_USD)))


def estimate(model, **units):
    """Price one call from list rates. Returns None when the model has no rate."""
    rates = RATES.get(model)
    if rates is None:
        return None
    total = 0.0
    for name, count in units.items():
        if name not in rates:
            return None
        total += float(count) * rates[name]
    return total


def token_units(input_tokens=0, cached_input_tokens=0, output_tokens=0):
    return {
        "input_mtok": input_tokens / 1_000_000,
        "cached_input_mtok": cached_input_tokens / 1_000_000,
        "output_mtok": output_tokens / 1_000_000,
    }


def price_usage(model, input_tokens=0, output_tokens=0, cached_tokens=0):
    """Bill cached tokens at the cache rate and the rest of the input at the full rate."""
    cached = min(int(cached_tokens), int(input_tokens))
    fresh = int(input_tokens) - cached
    return estimate(
        model,
        input_mtok=fresh / 1_000_000,
        cached_input_mtok=cached / 1_000_000,
        output_mtok=int(output_tokens) / 1_000_000,
    )


def would_warn(additional_usd):
    """Thresholds a new charge would cross. Does not record the charge."""
    after = float(_load()["usd"]) + float(additional_usd)
    warned = set(_load()["warned_usd"])
    return [mark for mark in thresholds_reached(after) if mark not in warned]


class SpendWarning(RuntimeError):
    """The next call would cross a $5 warning mark. It has not been sent."""

    def __init__(self, marks, projected_usd, note):
        self.marks = marks
        self.projected_usd = projected_usd
        self.note = note
        shown = ", ".join(f"${mark}" for mark in marks)
        super().__init__(
            f"Stopping before {note}: it would reach {shown}. "
            f"Projected total ${projected_usd:.2f}."
        )


def crossing(extra_usd):
    ledger = _load()
    projected = float(ledger["usd"]) + float(extra_usd)
    marks = [mark for mark in thresholds_reached(projected) if mark not in ledger["warned_usd"]]
    return marks, projected


def require_budget(extra_usd, note):
    marks, projected = crossing(extra_usd)
    if marks:
        raise SpendWarning(marks, projected, note)


def status():
    ledger = _load()
    usd = float(ledger["usd"])
    reached = thresholds_reached(usd)
    return {
        "usd": round(usd, 6),
        "next_warning_usd": (int(usd // STEP_USD) + 1) * int(STEP_USD),
        "warnings_due": [mark for mark in reached if mark not in ledger["warned_usd"]],
    }


def record(usd, note, model=None):
    """Add a charge and return warning strings for any new $5 mark."""
    if usd < 0:
        raise ValueError("cost cannot be negative")
    with _locked():
        return _record(usd, note, model)


def _record(usd, note, model):
    ledger = _load()
    before = float(ledger["usd"])
    after = before + float(usd)
    ledger["entries"].append(
        {
            "usd": round(float(usd), 6),
            "total_usd": round(after, 6),
            "model": model,
            "note": note,
        }
    )
    ledger["usd"] = round(after, 6)
    warnings = []
    for mark in thresholds_reached(after):
        if mark not in ledger["warned_usd"]:
            ledger["warned_usd"].append(mark)
            warnings.append(
                f"Meta Model API spend from this repo has reached ${mark}. "
                f"Running total is ${after:.2f}."
            )
    _save(ledger)
    return warnings


def main():
    print(json.dumps(status(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
