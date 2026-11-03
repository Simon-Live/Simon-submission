"""Model import stage times (TICKET-363, docs/specs/model-import.md AC-T4 to AC-T6).

    uv run python tools/model_import_times.py <state dir>

Reads `<state>/models/*/character.json` (else `status.json`) and prints one row per stage: count, median and p90
seconds. The serverless column holds measured Modal seconds only, from records marked `route: modal`; with none it says
"not measured". No Modal time or price is ever estimated.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
import statistics
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from part7.import_timings import STAGES  # noqa: E402

NOT_MEASURED = "not measured"


def p90(values: list[float]) -> float:
    """Nearest-rank 90th percentile."""
    ordered = sorted(values)
    return ordered[max(0, math.ceil(0.9 * len(ordered)) - 1)]


def _load(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def read_records(state: Path) -> list[tuple[str, dict[str, float]]]:
    """(route, {stage: seconds}) per model with timings; the route is `modal` only when the record says so."""
    rows = []
    for folder in sorted((state / "models").glob("*")):
        rec = _load(folder / "character.json") or _load(folder / "status.json")
        timings = rec.get("timings") if rec else None
        if not isinstance(timings, dict):
            continue
        good = {k: float(v) for k, v in timings.items() if isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0}
        if good:
            rows.append(("modal" if rec.get("route") == "modal" else "local", good))
    return rows


def _cell(values: list[float]) -> str:
    return f"median {statistics.median(values):.1f}, p90 {p90(values):.1f} (n={len(values)})" if values else NOT_MEASURED


def report(state: Path) -> str:
    records = read_records(state)
    stages = [s for s in STAGES if any(s in t for _, t in records)] + sorted({k for _, t in records for k in t} - set(STAGES))
    head = ("stage", "count", "median s", "p90 s", "serverless (Modal)")
    rows = [head]
    for stage in stages:
        local = [t[stage] for route, t in records if route == "local" and stage in t]
        modal = [t[stage] for route, t in records if route == "modal" and stage in t]
        rows.append((stage, str(len(local)), f"{statistics.median(local):.1f}" if local else "-",
                     f"{p90(local):.1f}" if local else "-", _cell(modal)))
    if len(rows) == 1:
        return "no model import timings found\n"
    widths = [max(len(r[i]) for r in rows) for i in range(len(head))]
    return "\n".join("  ".join(c.ljust(w) for c, w in zip(r, widths)).rstrip() for r in rows) + "\n"


def main(argv: list[str]) -> int:
    if len(argv) != 2 or not (Path(argv[1]) / "models").is_dir():
        print("usage: model_import_times.py <state dir with models/>", file=sys.stderr)
        return 2
    sys.stdout.write(report(Path(argv[1])))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
