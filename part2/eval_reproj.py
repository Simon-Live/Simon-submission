"""One-person done criterion: 3D joints reproject within 5% of body height on hand-clicked frames.

labels_2d.json (from the #6 tool):
  {frames: [{frame, view?: "front"|"side"|"back"|..., id?, joints: {<joint>: [u, v] | null}}]}
null = not visible / not clicked; such joints are not scored.

Per labelled frame: error = mean pixel distance over clicked joints between the click and the
reprojected 3D joint (pose3d.json + camera.json), divided by body height in pixels. Body height
is the clicked nose -> ankle-midpoint distance (nose -> the one clicked ankle if only one is),
which is shorter than full stature, so the threshold is stricter than "5% of height".
A labelled frame with no prediction scores as a failure.
"""
import json
from pathlib import Path

import numpy as np

from part2.canonical import project_pose3d

THRESHOLD = 0.05
MIN_FRAMES = 20


def evaluate(pose3d: dict, camera: dict, labels: dict, threshold=THRESHOLD, rule="every_frame",
             min_frames=MIN_FRAMES) -> dict:
    proj = project_pose3d(pose3d, camera)
    ids_by_frame = {}
    for (frame, pid) in proj:
        ids_by_frame.setdefault(frame, []).append(pid)

    per_frame = []
    for lf in labels["frames"]:
        clicked = {j: np.asarray(uv, float) for j, uv in lf["joints"].items() if uv is not None}
        height = body_height_px(clicked)
        row = {"frame": lf["frame"], "view": lf.get("view"), "n_joints": len(clicked),
               "height_px": None if height is None else round(height, 1)}
        pid = lf.get("id")
        if pid is None:
            ids = ids_by_frame.get(lf["frame"], [])
            pid = ids[0] if len(ids) == 1 else None
            if len(ids) > 1:
                row["note"] = f"{len(ids)} people predicted; label has no id"
        pred = proj.get((lf["frame"], pid))
        if height is None:
            row.update(error_pct=None, ok=False, note="nose and an ankle must be clicked to measure height")
        elif pred is None:
            row.update(error_pct=None, ok=False, note=row.get("note", "no prediction for this frame"))
        else:
            dists = [float(np.linalg.norm(np.asarray(pred[j]) - uv)) for j, uv in clicked.items()]
            pct = float(np.mean(dists)) / height
            row.update(error_px=round(float(np.mean(dists)), 2), error_pct=round(pct * 100, 3),
                       worst_joint=max(zip(dists, clicked))[1], ok=pct <= threshold)
        per_frame.append(row)

    scored = [r["error_pct"] for r in per_frame if r["error_pct"] is not None]
    n_side = sum(1 for r in per_frame if r["view"] == "side")
    if rule == "every_frame":
        within = all(r["ok"] for r in per_frame)
    elif rule == "mean":
        within = bool(scored) and len(scored) == len(per_frame) and np.mean(scored) <= threshold * 100
    else:
        raise ValueError(f"unknown rule {rule!r}")
    checks = {"enough_frames": len(per_frame) >= min_frames, "has_side_views": n_side > 0, "within_threshold": within}
    worst = max((r for r in per_frame if r["error_pct"] is not None), key=lambda r: r["error_pct"], default=None)
    return {
        "metric": "reprojection_error_pct_of_body_height", "threshold_pct": threshold * 100, "rule": rule,
        "n_frames": len(per_frame), "n_side_frames": n_side, "n_failed_frames": sum(not r["ok"] for r in per_frame),
        "mean_pct": _r(np.mean(scored)) if scored else None,
        "p95_pct": _r(np.percentile(scored, 95)) if scored else None,
        "max_pct": _r(max(scored)) if scored else None,
        "worst_frame": worst["frame"] if worst else None,
        "checks": checks, "pass": all(checks.values()),
        "per_frame": per_frame,
    }


def body_height_px(clicked: dict) -> float | None:
    if "nose" not in clicked:
        return None
    ankles = [clicked[a] for a in ("left_ankle", "right_ankle") if a in clicked]
    if not ankles:
        return None
    h = float(np.linalg.norm(clicked["nose"] - np.mean(ankles, axis=0)))
    return h if h > 0 else None


def evaluate_files(pose3d_path, camera_path, labels_path, **kw) -> dict:
    load = lambda p: json.loads(Path(p).read_text())  # noqa: E731
    return evaluate(load(pose3d_path), load(camera_path), load(labels_path), **kw)


def _r(x) -> float:
    return round(float(x), 3)
