"""AC-5 of TICKET-274: the heat drop per region from take 1 to take 2 of the same movement, from two job ids.

Usage: uv run python tools/heat_drop.py <jobs_root> <take1_job> <take2_job>   (prints one JSON document)

Per region the mean heat over the take's valid frames is compared. Nothing is picked: every region is listed, and
`improved` is true only when the whole-body mean (hands and feet excluded) fell. When it did not, the heat-cools
motif is not used (exit 3), as the ticket requires.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from part7 import heat  # noqa: E402


def region_means(jobs_root: Path, job_id: str) -> dict[str, float] | None:
    found = heat.files(jobs_root, job_id)
    if found is None:
        return None
    by = json.loads(found[0].with_name(heat.META).read_text())["mean_by_region_m"]
    return {r: sum(v for v in vals if v is not None) / max(1, sum(v is not None for v in vals)) for r, vals in by.items()}


def compare(one: dict[str, float], two: dict[str, float]) -> dict:
    regions = {r: {"take1_m": round(one[r], 5), "take2_m": round(two[r], 5), "drop_m": round(one[r] - two[r], 5)} for r in sorted(one) if r in two}
    mean = lambda d: sum(d.values()) / len(d)  # noqa: E731
    total = {"take1_m": round(mean(one), 5), "take2_m": round(mean(two), 5), "drop_m": round(mean(one) - mean(two), 5)}
    return {"regions": regions, "whole_body": total, "improved": total["drop_m"] > 0}


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2
    one, two = region_means(Path(argv[0]), argv[1]), region_means(Path(argv[0]), argv[2])
    if one is None or two is None:
        print(json.dumps({"error": "a job has no heat (no follower mesh or replay)"}))
        return 1
    out = compare(one, two)
    print(json.dumps({"take1": argv[1], "take2": argv[2], **out}, indent=1))
    return 0 if out["improved"] else 3


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
