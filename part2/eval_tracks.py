"""Multi-person done criterion (#13): tracking coverage + ID swaps vs hand-labelled keyframes.

gt_tracks.json (from the #6 tool): {keyframes_only: true,
  frames: [{frame, people: [{id, bbox: [x, y, w, h]}]}]} — keyframes only (~1 s apart).
A keyframe with no people counts as unlabelled and is excluded everywhere.

Per labelled keyframe, GT boxes are matched to predicted tracks.json boxes in the
same frame by IoU (>= 0.5), greedily by descending IoU, one-to-one. For each GT
person, over the keyframes where they are labelled:
  coverage      = matched keyframes / labelled keyframes        (pass: >= 0.95 each)
  id swaps      = times the matched track id changes between consecutive
                  matched appearances; swaps/min uses the person's labelled
                  time span from pose3d.json timestamps          (pass: <= 1 each)
The clip passes when it has >= 5 GT people, every GT person meets both limits,
and every matched track id has a pose3d stream (appears in pose3d.json).
"""
import json
from pathlib import Path

IOU_THRESHOLD = 0.5
MIN_COVERAGE = 0.95
MAX_SWAPS_PER_MIN = 1.0
MIN_PEOPLE = 5


def iou(a, b) -> float:
    """IoU of two [x, y, w, h] boxes."""
    ax, ay, aw, ah = (float(v) for v in a)
    bx, by, bw, bh = (float(v) for v in b)
    ix = max(0.0, min(ax + aw, bx + bw) - max(ax, bx))
    iy = max(0.0, min(ay + ah, by + bh) - max(ay, by))
    inter = ix * iy
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


def _match(gt_people, pred_people):
    """Greedy one-to-one matching by descending IoU. Returns {gt_id: pred_id}."""
    pairs = sorted(
        ((iou(g["bbox"], p["bbox"]), g["id"], p["id"]) for g in gt_people for p in pred_people),
        reverse=True,
    )
    used_g, used_p, out = set(), set(), {}
    for score, gid, pid in pairs:
        if score < IOU_THRESHOLD or gid in used_g or pid in used_p:
            continue
        used_g.add(gid)
        used_p.add(pid)
        out[gid] = pid
    return out


def evaluate(tracks: dict, gt: dict, pose3d: dict) -> dict:
    from part2.schema import validate_tracks

    validate_tracks(tracks)
    _validate_gt(gt)
    pred_by_frame = {f["frame"]: f.get("people", []) for f in tracks.get("frames", [])}
    t_by_frame = {f["frame"]: f["t_ms"] for f in pose3d.get("frames", []) if "t_ms" in f}
    pose_by_frame = {f["frame"]: {p["id"] for p in f.get("people", [])}
                     for f in pose3d.get("frames", [])}

    appearances = {}  # gt id -> [(frame, matched pred id | None)]
    for f in gt.get("frames", []):
        people = f.get("people", [])
        if not people:
            continue  # unlabelled keyframe
        matched = _match(people, pred_by_frame.get(f["frame"], []))
        for g in people:
            appearances.setdefault(g["id"], []).append((f["frame"], matched.get(g["id"])))

    per_person = []
    for gid in sorted(appearances):
        apps = sorted(appearances[gid])
        n = len(apps)
        hits = [(fr, pid) for fr, pid in apps if pid is not None]
        swaps, prev = 0, None
        for _, pid in hits:
            if prev is not None and pid != prev:
                swaps += 1
            prev = pid
        times = [t_by_frame[fr] for fr, _ in apps if fr in t_by_frame]
        span_min = (max(times) - min(times)) / 60000.0 if len(times) >= 2 else 0.0
        swaps_per_min = swaps / span_min if span_min > 0 else (float("inf") if swaps else 0.0)
        matched_ids = sorted({pid for _, pid in hits})
        n_pose = sum(1 for fr, pid in hits if pid in pose_by_frame.get(fr, set()))
        per_person.append({
            "gt_id": gid, "n_keyframes": n, "n_matched": len(hits),
            "coverage": round(len(hits) / n, 4) if n else 0.0,
            "id_swaps": swaps, "span_min": round(span_min, 3),
            "swaps_per_min": None if swaps_per_min == float("inf") else round(swaps_per_min, 3),
            "track_ids": matched_ids,
            "pose3d_coverage": round(n_pose / len(hits), 4) if hits else 0.0,
            "has_pose3d": bool(hits) and n_pose / len(hits) >= MIN_COVERAGE,
        })

    checks = {
        "enough_people": len(per_person) >= MIN_PEOPLE,
        "coverage_ge_95pct": all(p["coverage"] >= MIN_COVERAGE for p in per_person),
        "swaps_le_1_per_min": all(
            (p["swaps_per_min"] is not None and p["swaps_per_min"] <= MAX_SWAPS_PER_MIN)
            for p in per_person),
        "pose3d_per_person": all(p["has_pose3d"] for p in per_person) and bool(per_person),
    }
    n_missing_t = sum(1 for apps in appearances.values() for fr, _ in apps if fr not in t_by_frame)
    return {
        "metric": "tracking_coverage_and_id_swaps",
        "swap_rate_basis": "person_span (decision pending: #18 open decision 4)",
        "n_appearances_missing_timestamps": n_missing_t,
        "iou_threshold": IOU_THRESHOLD, "min_people": MIN_PEOPLE,
        "n_gt_people": len(per_person),
        "n_keyframes": sum(p["n_keyframes"] for p in per_person),
        "mean_coverage": round(sum(p["coverage"] for p in per_person) / len(per_person), 4)
        if per_person else 0.0,
        "total_id_swaps": sum(p["id_swaps"] for p in per_person),
        "checks": checks, "pass": all(checks.values()),
        "per_person": per_person,
    }


def _validate_gt(gt: dict) -> None:
    frames = gt.get("frames") if isinstance(gt, dict) else None
    if not isinstance(frames, list):
        raise ValueError("gt_tracks: expected {frames: [...]}")
    for i, f in enumerate(frames):
        ids = [p.get("id") for p in f.get("people", [])]
        if len(set(ids)) != len(ids):
            raise ValueError(f"gt_tracks.frames[{i}]: duplicate GT ids {ids}")
        for p in f.get("people", []):
            bbox = p.get("bbox")
            if not (isinstance(bbox, list) and len(bbox) == 4):
                raise ValueError(f"gt_tracks.frames[{i}]: bbox must be [x, y, w, h]")


def evaluate_files(tracks_path, gt_path, pose3d_path) -> dict:
    load = lambda p: json.loads(Path(p).read_text())  # noqa: E731
    return evaluate(load(tracks_path), load(gt_path), load(pose3d_path))
