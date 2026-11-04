"""Second one-person block (TICKET-037): the COCO photo runs scored by the unchanged eval_reproj rules.

Spec: docs/specs/check-2.md ("Scoring rules", AC-K13); ADR-0004. Labels: fixtures/input/coco/labels_2d.json
(part2.coco_set). Outputs, one photo run per labelled image:

    <scored_dir>/<image_id>/pose3d.json + camera.json     (scored_dir default fixtures/output/scored/coco-single)

Each image is its own one-frame clip, scored by `eval_reproj.evaluate` on that run alone, so its body height is
that image's nose to ankle-midpoint distance. The label is matched to the run's single frame whatever its number
(coco_set.stage_photo numbers it by image id); a run with no frame is a missing prediction and one with more
frames is refused. Threshold (5%), the per-frame error and the every-frame pass rule are eval_reproj's. Checks:
at least eval_reproj.MIN_FRAMES images and every image within the threshold. No side-view check: camera angle
must not matter (operator ruling on #337) and COCO records no view.

    uv run python -m part2.eval_coco [--scored DIR] [--labels PATH] [--per-frame]   # exit 0 only on pass
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np

from part2 import eval_reproj

ROOT = Path(__file__).resolve().parent.parent
LABELS = ROOT / "fixtures" / "input" / "coco" / "labels_2d.json"
SCORED = ROOT / "fixtures" / "output" / "scored" / "coco-single"
BODY_HEIGHT = "per image nose to ankle-midpoint distance in px (each image its own clip)"


def score_image(run_dir: Path, label: dict, threshold: float = eval_reproj.THRESHOLD) -> dict:
    """One per-frame row (eval_reproj's shape) for one labelled image; `frame` is the image id."""
    image_id = label["frame"]
    missing = [n for n in ("pose3d.json", "camera.json") if not (run_dir / n).is_file()]
    if missing:
        return _failed(image_id, f"missing output {run_dir / missing[0]}; run make outputs")
    pose3d, camera = (json.loads((run_dir / n).read_text()) for n in ("pose3d.json", "camera.json"))
    frames = pose3d.get("frames", [])
    if len(frames) > 1:
        return _failed(image_id, f"not a photo run: {len(frames)} frames in {run_dir / 'pose3d.json'}")
    frame = frames[0]["frame"] if frames else image_id
    one = {"frames": [{**label, "frame": frame}]}
    row = eval_reproj.evaluate(pose3d, camera, one, threshold=threshold, min_frames=1)["per_frame"][0]
    return {**row, "frame": image_id}


def evaluate(scored_dir, labels: dict, threshold: float = eval_reproj.THRESHOLD, rule: str = "every_frame",
             min_frames: int = eval_reproj.MIN_FRAMES) -> dict:
    eval_reproj.validate_labels(labels)
    rows = [score_image(Path(scored_dir) / str(lf["frame"]), lf, threshold) for lf in labels["frames"]]
    scored = [r["error_pct"] for r in rows if r["error_pct"] is not None]
    if rule == "every_frame":
        within = bool(rows) and all(r["ok"] for r in rows)
    elif rule == "mean":
        within = bool(scored) and len(scored) == len(rows) and float(np.mean(scored)) <= threshold * 100
    else:
        raise ValueError(f"unknown rule {rule!r}")
    checks = {"enough_frames": len(rows) >= min_frames, "within_threshold": within}
    worst = max((r for r in rows if r["error_pct"] is not None), key=lambda r: r["error_pct"], default=None)
    return {
        "metric": "reprojection_error_pct_of_body_height", "threshold_pct": threshold * 100, "rule": rule,
        "body_height": BODY_HEIGHT, "n_frames": len(rows), "n_failed_frames": sum(not r["ok"] for r in rows),
        "mean_pct": _r(np.mean(scored)) if scored else None,
        "p95_pct": _r(np.percentile(scored, 95)) if scored else None,
        "max_pct": _r(max(scored)) if scored else None,
        "worst_frame": worst["frame"] if worst else None,
        "checks": checks, "pass": all(checks.values()), "per_frame": rows,
    }


def block(scored_dir=SCORED, labels_path=LABELS) -> dict:
    """check-2's `one_person_coco` block without per-frame rows; a missing scored dir is a failed block."""
    scored_dir = Path(scored_dir)
    if not scored_dir.is_dir():
        return {"pass": False, "status": f"missing output {scored_dir}; run make outputs"}
    m = evaluate(scored_dir, json.loads(Path(labels_path).read_text()))
    m.pop("per_frame")
    return m


def _failed(image_id: int, note: str) -> dict:
    return {"frame": image_id, "view": None, "n_joints": 0, "height_px": None, "frame_height_px": None,
            "error_pct": None, "ok": False, "note": note}


def _r(x) -> float:
    return round(float(x), 3)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m part2.eval_coco", description=__doc__.split("\n")[0])
    ap.add_argument("--scored", type=Path, default=SCORED, help="dir of <image_id>/{pose3d,camera}.json")
    ap.add_argument("--labels", type=Path, default=LABELS)
    ap.add_argument("--per-frame", action="store_true", help="include one row per image")
    args = ap.parse_args(argv)
    if not args.scored.is_dir():
        m = block(args.scored, args.labels)
    else:
        m = evaluate(args.scored, json.loads(args.labels.read_text()))
        if not args.per_frame:
            m.pop("per_frame")
    print(json.dumps(m, indent=2))
    return 0 if m["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
