"""Label-free comparison of two tracks.json files (the local-sam31 parity check, AC-R10).

Spec: docs/specs/tracker-registry.md (Parity check). ADR-0003. TICKET-038.

Ids of the two files are matched one to one by mean mask IoU over the frames where both are present (greedy,
highest first, at least MIN_MATCH_IOU). Coverage of an id is the share of frames where it is present. Pass:
the same id count, every id matched, and each matched pair's coverage within 1 percentage point. It compares
two tracker outputs only; it never reads ground-truth labels.

    python -m part2.trackers.parity a/tracks.json b/tracks.json [--out result.json]   # exit 0 pass, 1 fail
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np

TOLERANCE_PP = 1.0
MIN_MATCH_IOU = 0.5


def _flat_mask(rle: dict) -> np.ndarray:
    """Column-major flat boolean mask of a COCO RLE (the order of the counts)."""
    from part2.track import rle_counts

    counts = rle_counts(rle)
    values = np.arange(len(counts)) % 2 == 1
    return np.repeat(values, counts)


def coverage(doc: dict) -> dict:
    n = len(doc["frames"])
    seen = {}
    for f in doc["frames"]:
        for p in f["people"]:
            seen[p["id"]] = seen.get(p["id"], 0) + 1
    return {i: c / n for i, c in seen.items()} if n else {}


def mean_mask_iou(a: dict, b: dict) -> dict:
    """{(id_a, id_b): mean mask IoU over frames where both are present}."""
    frames_b = {f["frame"]: f["people"] for f in b["frames"]}
    sums, counts = {}, {}
    for f in a["frames"]:
        pb = frames_b.get(f["frame"], [])
        if not f["people"] or not pb:
            continue
        ma = {p["id"]: _flat_mask(p["mask_rle"]) for p in f["people"]}
        mb = {p["id"]: _flat_mask(p["mask_rle"]) for p in pb}
        for ia, xa in ma.items():
            for ib, xb in mb.items():
                if xa.size != xb.size:
                    raise ValueError(f"frame {f['frame']}: mask sizes differ between the two files")
                union = np.count_nonzero(xa | xb)
                iou = float(np.count_nonzero(xa & xb)) / union if union else 0.0
                sums[(ia, ib)] = sums.get((ia, ib), 0.0) + iou
                counts[(ia, ib)] = counts.get((ia, ib), 0) + 1
    return {k: float(sums[k] / counts[k]) for k in sums}


def compare(a: dict, b: dict, tolerance_pp: float = TOLERANCE_PP) -> dict:
    frames_a, frames_b = [f["frame"] for f in a["frames"]], [f["frame"] for f in b["frames"]]
    cov_a, cov_b = coverage(a), coverage(b)
    reasons = []
    if frames_a != frames_b:
        reasons.append("the two files cover different frames")
    ious = mean_mask_iou(a, b) if not reasons else {}
    pairs, used_a, used_b = [], set(), set()
    for (ia, ib), iou in sorted(ious.items(), key=lambda kv: (-kv[1], str(kv[0]))):
        if iou < MIN_MATCH_IOU or ia in used_a or ib in used_b:
            continue
        used_a.add(ia)
        used_b.add(ib)
        diff = abs(cov_a[ia] - cov_b[ib]) * 100
        pairs.append({"a": ia, "b": ib, "mean_mask_iou": round(iou, 4), "coverage_a": round(cov_a[ia], 4),
                      "coverage_b": round(cov_b[ib], 4), "diff_pp": round(diff, 3),
                      "within": diff <= tolerance_pp + 1e-9})
    unmatched_a = sorted(set(cov_a) - used_a, key=str)
    unmatched_b = sorted(set(cov_b) - used_b, key=str)
    if len(cov_a) != len(cov_b):
        reasons.append(f"id counts differ: {len(cov_a)} against {len(cov_b)}")
    if unmatched_a or unmatched_b:
        reasons.append(f"unmatched ids: a {unmatched_a}, b {unmatched_b}")
    over = [p for p in pairs if not p["within"]]
    if over:
        reasons.append(f"{len(over)} matched ids differ in coverage by more than {tolerance_pp} points")
    return {"pass": not reasons, "reasons": reasons, "tolerance_pp": tolerance_pp,
            "min_match_iou": MIN_MATCH_IOU, "n_frames": len(frames_a), "ids_a": len(cov_a), "ids_b": len(cov_b),
            "max_diff_pp": max((p["diff_pp"] for p in pairs), default=None), "pairs": pairs,
            "unmatched_a": unmatched_a, "unmatched_b": unmatched_b}


def compare_files(path_a, path_b, tolerance_pp: float = TOLERANCE_PP) -> dict:
    load = lambda p: json.loads(Path(p).read_text())  # noqa: E731
    return compare(load(path_a), load(path_b), tolerance_pp)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m part2.trackers.parity", description=__doc__.splitlines()[0])
    ap.add_argument("a", type=Path)
    ap.add_argument("b", type=Path)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args(argv)
    result = compare_files(args.a, args.b)
    text = json.dumps(result, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n")
    print(text)
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
