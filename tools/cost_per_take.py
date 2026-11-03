"""Cost and capacity per student take (TICKET-261, docs/specs/cost-per-take.md).

    uv run python tools/cost_per_take.py <state dir> [--date YYYY-MM-DD]

Reads `jobs/*/job.json`, each job's `steps/part7.log` summary line and `history/spend.jsonl`. No GPU price is used.
"""

from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import re
import statistics
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from part7.judge_view import is_test_id  # noqa: E402  (one exclusion rule, not a copy)

RULE = "jobs whose entry id starts with verify-, check-7- or qa- are excluded (part7/judge_view.py is_test_id)"
_SUMMARY = re.compile(r"summary: kind=follow status=ok .*?\bpose=([0-9.]+)s(?:\(gpu_wait=([0-9.]+)s\))?")


def gpu_seconds(job_dir: Path) -> float | None:
    """GPU seconds of one follow job: the pose stage less its wait for the GPU lock; None when not logged."""
    try:
        text = (job_dir / "steps" / "part7.log").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    found = None
    for found in _SUMMARY.finditer(text):
        pass
    if found is None:
        return None
    return max(0.0, float(found.group(1)) - float(found.group(2) or 0.0))


def read_jobs(state: Path) -> list[tuple[str, float]]:
    """(entry id, GPU seconds) for each counted follow take."""
    rows = []
    for path in sorted((state / "jobs").glob("*/job.json")):
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(job, dict) or job.get("kind") != "follow" or job.get("status") != "done":
            continue
        entry = str(job.get("entry_id") or "")
        if not entry or is_test_id(entry):
            continue
        seconds = gpu_seconds(path.parent)
        if seconds is not None:
            rows.append((entry, seconds))
    return rows


def settled_usd(ledger: Path) -> float:
    """USD on the ledger: a settle line's cost, or the reserve estimate when none settled that call."""
    held: dict[str, float] = {}
    total = 0.0
    try:
        lines = ledger.read_text(encoding="utf-8").splitlines()
    except OSError:
        return 0.0
    for line in lines:
        try:
            row = json.loads(line)
            usd, call = float(row.get("usd") or 0.0), str(row.get("call"))
        except (ValueError, AttributeError, TypeError):
            continue
        if row.get("kind") == "settle":
            total += usd - held.pop(call, 0.0)
        else:
            held[call] = usd
            total += usd
    return total


def percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    pos = (len(ordered) - 1) * pct
    low = int(pos)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (pos - low)


def report(state: Path, today: str) -> str:
    rows = read_jobs(state)
    lines = [f"cost per student take, run {today}", f"exclusion rule: {RULE}", f"follow takes counted: {len(rows)}"]
    if not rows:
        return "\n".join(lines + ["no counted takes"])
    secs = [s for _, s in rows]
    mean = statistics.fmean(secs)
    spend = settled_usd(state / "history" / "spend.jsonl")
    per_entry: dict[str, int] = {}
    for entry, _ in rows:
        per_entry[entry] = per_entry.get(entry, 0) + 1
    counts = list(per_entry.values())
    lines += [
        f"GPU seconds per follow take (Part 2 pose stage, less GPU-lock wait): p50 {percentile(secs, 0.5):.1f}, p90 {percentile(secs, 0.9):.1f}, mean {mean:.1f}",
        f"takes per GPU-hour (derived: 3600 / mean GPU seconds): {3600 / mean:.1f}",
        f"API spend: ${spend:.4f} USD settled on the ledger; mean ${spend / len(rows):.4f} USD per take "
        "(the ledger has no job id, so test spend cannot be removed; this is an upper bound)",
        f"one recording served N takes: {len(per_entry)} trainer entries, max {max(counts)}, median {statistics.median(counts):g}",
        "GPU price: none used; figures are GPU seconds and USD of API spend only",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("state", type=Path)
    parser.add_argument("--date", default=date.today().isoformat())
    args = parser.parse_args(argv)
    if not (args.state / "jobs").is_dir():
        print(f"cost_per_take: no jobs dir under {args.state}", file=sys.stderr)
        return 2
    print(report(args.state, args.date))
    return 0


if __name__ == "__main__":
    sys.exit(main())
