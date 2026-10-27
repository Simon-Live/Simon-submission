"""Multi-person 3D (#11): tracks.json boxes -> per-person pose3d streams.

Runs SAM 3D Body (part2.body3d) once per frame on every tracked person's box
(the estimator batches the boxes of a frame together), converts to the
canonical frame (part2.canonical), and writes:
  pose3d.json / camera.json     combined, ids matching tracks.json
  pose3d_person_<id>.json       one stream per tracked person (same shape)
"""
import json
from pathlib import Path

from part2.canonical import convert
from part2.schema import validate_pose3d


def tracks_to_boxes(tracks: dict) -> dict:
    """{frame: {id: [x, y, w, h]}} from a tracks.json document, for body3d.estimate(boxes=…)."""
    return {f["frame"]: {p["id"]: [float(v) for v in p["bbox"]] for p in f.get("people", [])}
            for f in tracks.get("frames", [])}


def split_people(pose3d: dict) -> dict:
    """{id: pose3d doc with only that person's stream}."""
    ids = sorted({p["id"] for f in pose3d["frames"] for p in f["people"]}, key=str)
    return {pid: {"frames": [
        {"frame": f["frame"], "t_ms": f["t_ms"],
         "people": [p for p in f["people"] if p["id"] == pid]}
        for f in pose3d["frames"]]} for pid in ids}


def write_pose_streams(body3d_doc: dict, out_dir, smooth: bool = False) -> dict:
    """Canonical-convert a body3d doc and write combined + per-person pose3d files."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    pose3d, camera = convert(body3d_doc, smooth=smooth)
    validate_pose3d(pose3d)
    (out_dir / "pose3d.json").write_text(json.dumps(pose3d))
    (out_dir / "camera.json").write_text(json.dumps(camera))
    per_person = split_people(pose3d)
    for stale in out_dir.glob("pose3d_person_*.json"):  # ids from an earlier run into this dir
        stale.unlink()
    for pid, doc in per_person.items():
        (out_dir / f"pose3d_person_{pid}.json").write_text(json.dumps(doc))
    return {"pose3d": pose3d, "camera": camera, "people": sorted(per_person, key=str)}


def run(frames_dir, out_dir, estimator=None, smooth: bool = False) -> dict:
    """Full #11 step on an out dir that already has frames/ and tracks.json."""
    from part2 import body3d

    out_dir = Path(out_dir)
    tracks = json.loads((out_dir / "tracks.json").read_text())
    body3d_doc = body3d.estimate(frames_dir, out_dir / "body3d.json",
                                 boxes=tracks_to_boxes(tracks), estimator=estimator)
    return write_pose_streams(body3d_doc, out_dir, smooth=smooth)
