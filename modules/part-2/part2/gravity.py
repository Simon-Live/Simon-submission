"""The phone's gravity as the true up (TICKET-055; spec docs/specs/gravity-up.md).

`part2 run --gravity <gravity.json>` reads one measured up direction for the take, validates it before any work, and
after pose3d.json is written adds it to the pose3d files this run wrote (pose3d.json, and in multi mode each
pose3d_person_<id>.json of the run's people):

- top level `gravity`: {up_camera: [x, y, z], camera_frame: "opencv", source, t_ms: [start, end], samples,
  tilt_deg}. `up_camera` is the unit up direction (opposite to gravity) in OpenCV camera axes of the saved video's
  image: x to the image right, y to the image bottom, z out of the lens into the scene. `tilt_deg` is its angle from
  the camera up Part 2 otherwise assumes (-y), the phone's pitch and roll together.
- per person and frame `up`: [x, y, z], the same direction in that person's canonical axes of that frame
  (up = R^T up_camera, with R from camera.json, p_cam = R p_canonical + t). Its y part is the cosine of tilt_deg.

Without `--gravity` nothing here runs and every file is byte-identical to a run before this module existed. The module
only reads camera.json and rewrites pose3d files; it never changes a joint, a confidence or a scored number.
"""
import json
from pathlib import Path

import numpy as np

from part2 import contract
from part2.schema import ContractError, check_gravity_fields, is_number, tilt_deg, vector_length, write_json

SCHEMA_ID = "simon.gravity/1"
CAMERA_FRAME = "opencv"
MIN_NORM = 1e-6
CLIP_SLACK_MS = 1000.0  # a window may end this long after the last frame (its own duration, sensor lag)


def load(path) -> dict | None:
    """The validated gravity input of `path` (None when no path). Raises ContractError (a ValueError) when the file is
    not a valid simon.gravity/1 document."""
    if path is None:
        return None
    try:
        doc = json.loads(Path(path).read_text())
    except (OSError, ValueError) as e:
        raise ContractError("gravity", f"cannot read {path}: {e}") from None
    return parse(doc)


def parse(doc) -> dict:
    """Check a gravity document and return {up_camera (unit), source, t_ms, samples}."""
    if not isinstance(doc, dict):
        raise ContractError("gravity", "expected an object")
    if doc.get("schema") != SCHEMA_ID:
        raise ContractError("gravity.schema", f"expected {SCHEMA_ID!r}, got {doc.get('schema')!r}")
    if doc.get("frame") != CAMERA_FRAME:
        raise ContractError("gravity.frame", f"expected {CAMERA_FRAME!r} (x image right, y image down, z into the scene)")
    up = doc.get("up")
    if not (isinstance(up, list) and len(up) == 3 and all(is_number(v) for v in up)):
        raise ContractError("gravity.up", "expected three finite numbers")
    norm = vector_length(up)
    if norm < MIN_NORM:
        raise ContractError("gravity.up", "the vector has no length")
    check_gravity_fields(doc.get("source"), doc.get("samples"), doc.get("t_ms"), "gravity")
    t_ms = doc["t_ms"]
    return {"up_camera": [float(v) / norm for v in up], "source": doc["source"],
            "t_ms": [float(t_ms[0]), float(t_ms[1])], "samples": doc["samples"]}


def check_clip(gravity: dict | None, recs: list[dict]) -> None:
    """Refuse a window that ends more than CLIP_SLACK_MS after the last frame of `recs` (the run's frame records): the
    file then belongs to a longer take. Nothing to check without gravity or frames."""
    if gravity is None or not recs:
        return
    end = max(r["t_ms"] for r in recs)
    if gravity["t_ms"][1] > end + CLIP_SLACK_MS:
        raise ContractError("gravity.t_ms", f"the window ends at {gravity['t_ms'][1]:g} ms but the clip's last frame is at "
                            f"{end:g} ms (more than {CLIP_SLACK_MS:g} ms of slack): is this file from another take?")


def apply(out_dir, gravity: dict | None, people=()) -> list[Path]:
    """Add `gravity` to out_dir/pose3d.json and to pose3d_person_<id>.json for each id in `people`: the files this run
    wrote. Other pose3d files in the directory belong to an earlier run and stay as they are. Every document is built and
    validated before any is written. Returns the files written; [] when `gravity` is None."""
    if gravity is None:
        return []
    out_dir = Path(out_dir)
    rotations = _rotations(json.loads((out_dir / "camera.json").read_text()))
    up_cam = np.asarray(gravity["up_camera"], dtype=float)
    block = {"up_camera": [_r(v) for v in up_cam], "camera_frame": CAMERA_FRAME, "source": gravity["source"],
             "t_ms": gravity["t_ms"], "samples": gravity["samples"], "tilt_deg": _r(tilt_deg(up_cam), 3)}
    paths = [out_dir / "pose3d.json", *(out_dir / f"pose3d_person_{pid}.json" for pid in people)]
    docs = [add(json.loads(p.read_text()), block, rotations) for p in paths]
    for doc in docs:
        contract.validate(doc, "pose3d")
    return [write_json(p, d) for p, d in zip(paths, docs)]


def add(doc: dict, block: dict, rotations: dict) -> dict:
    """Put `block` at the top of `doc` and each person's `up` in its own canonical axes (in place)."""
    up_cam = np.asarray(block["up_camera"], dtype=float)
    doc["gravity"] = block
    for frame in doc["frames"]:
        for person in frame["people"]:
            R = rotations.get((frame["frame"], person["id"]))
            if R is None:
                raise ContractError(f"pose3d.frames[frame={frame['frame']}]", f"camera.json has no R for person {person['id']!r}")
            person["up"] = [_r(v) for v in R.T @ up_cam]
    return doc


def _rotations(camera: dict) -> dict:
    """{(frame, id): R}. The id keeps its JSON type, as canonical.project_pose3d and contract.check_sequence do, so 3 and
    "3" are two people."""
    out = {}
    for frame in camera.get("frames", []):
        for person in frame.get("people", []):
            out[(frame["frame"], person["id"])] = np.asarray(person["R"], dtype=float)
    return out


def _r(v, digits: int = 6) -> float:
    return round(float(v), digits)
