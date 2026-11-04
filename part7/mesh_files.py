"""Each person's SAM 3D Body mesh of a finished follow job (docs/specs/result-redesign-additions.md R3, TICKET-143).

Part 2 writes `mesh3d.json` and `mesh3d.bin` next to `pose3d.json` when it runs with `--mesh` (Part 2 CONTRACT.md).
The follower's are in the job's `work/follower/part2/`, the trainer's in the newest done trainer job of the same
catalog entry, `work/trainer/part2/` (models_used.trainer_job). Part 7 serves the files unchanged.

- `GET results/<job>/mesh.json` answers a done follow job with `{trainer, you}`: each the URL of that person's
  `mesh3d.json` (relative to the app's base path) when that person's two files are present, else null (TICKET-375: the
  Person model needs only its own person's mesh; the side-by-side mesh view needs both and checks both). Always 200 for
  such a job, so a result without meshes makes no failing request; 404 for any other id, kind or state.
- `GET results/<job>/mesh/<trainer|you>/<mesh3d.json|mesh3d.bin>` serves the file; 404 when it is absent.
- `GET results/<job>/mesh/<trainer|you>/rest.json` (docs/specs/person-skin.md) answers the person's rest joints: the
  17 pose3d keypoints of the first mesh frame that has a person and both elbows bent less than 30 degrees, so the
  browser skins the mesh around real joints instead of label centroids, plus `motion` (the joints of up to 64 frames
  of the take) and `weights` (the skin weights computed once here, part7.skin_weights). Same gate as the mesh files; 404 when
  `pose3d.json` or the mesh header is missing or holds no usable frame.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from part7 import job_lookup, jobs, models_used

INDEX = "mesh.json"
FILES = {"mesh3d.json": "application/json; charset=utf-8", "mesh3d.bin": "application/octet-stream"}
WHO = ("trainer", "you")
REST = "rest.json"
REST_SCHEMA = "simon.person-rest.v1"
JOINTS = ("nose", "left_eye", "right_eye", "left_ear", "right_ear", "left_shoulder", "right_shoulder", "left_elbow",
          "right_elbow", "left_wrist", "right_wrist", "left_hip", "right_hip", "left_knee", "right_knee", "left_ankle",
          "right_ankle")
ARMS = (("left_shoulder", "left_elbow", "left_wrist"), ("right_shoulder", "right_elbow", "right_wrist"))
MAX_BEND_DEG = 30.0
MOTION_MAX = 64  # frames of the take sent for the skin weights (about 400 bytes each); part7.take_rig weighs the same
MIN_CONF = 0.3
MSG_GONE = "This result is not available."


def _record(job_dir: Path) -> dict[str, Any] | None:
    rec = job_lookup.read_json(job_dir / "job.json")
    ok = isinstance(rec, dict) and rec.get("kind") == "follow" and rec.get("status") == "done"
    return rec if ok else None


def _folders(jobs_root: Path, job_id: str, trainer_too: bool = True) -> dict[str, Path | None] | None:
    """`{who: folder}` for done follow job `job_id` (one read of its record, one trainer lookup), or None when it is not one."""
    job_dir = jobs_root / job_id
    rec = _record(job_dir)
    if rec is None:
        return None
    trainer = models_used.trainer_job(jobs_root, rec.get("entry_id")) if trainer_too else None
    return {
        "you": job_dir / "work" / "follower" / "part2",
        "trainer": trainer / "work" / "trainer" / "part2" if trainer is not None else None,
    }


def _regular(folder: Path | None, name: str) -> Path | None:
    path = folder / name if folder is not None and name in FILES else None
    return path if path is not None and path.is_file() and not path.is_symlink() else None


def mesh_dir(jobs_root: Path, job_id: str, who: str) -> Path | None:
    """The folder holding `who`'s mesh files for done follow job `job_id`, or None when there is none."""
    folders = _folders(jobs_root, job_id, who == "trainer") if who in WHO else None
    return folders[who] if folders is not None else None


def mesh_file(jobs_root: Path, job_id: str, who: str, name: str) -> Path | None:
    """The mesh file `name` of `who`, when it is a regular file (never a symlink), else None."""
    return _regular(mesh_dir(jobs_root, job_id, who) if name in FILES else None, name)


def index(jobs_root: Path, job_id: str) -> dict[str, Any] | None:
    """`{trainer, you}` mesh URLs (null when absent) for a done follow job, or None when it is not one.

    The job record and the trainer lookup are read once per request, not once per file.
    """
    folders = _folders(jobs_root, job_id)
    if folders is None:
        return None
    url = lambda who: f"api/results/{job_id}/mesh/{who}/mesh3d.json"  # noqa: E731
    has = {who: all(_regular(folders[who], n) for n in FILES) for who in WHO}
    both = all(has.values())
    # TICKET-375: each person on their own, so the Person model shows the follower's body when the trainer was recorded
    # before --mesh; the side-by-side mesh view needs both URLs and checks that itself (result-wiring.js mountMesh)
    doc: dict[str, Any] = {who: (url(who) if has[who] else None) for who in WHO}
    from part7 import take_ar  # TICKET-282: AR file link requests, present only for a person who has them (take-ar.md)

    ar = take_ar.from_folders(folders, job_id) or {}
    for kind in take_ar.KINDS:
        asks = {who: f"api/results/{job_id}/take-ar-url?who={who}&kind={kind}" if ar.get(who) else None for who in WHO}
        if any(asks.values()):
            doc[kind] = asks
    from part7 import heat  # TICKET-274: optional `heat` field (contract H1); imported here because heat imports this module

    if both and heat.eligible(folders["you"]):
        doc["heat"] = f"api/results/{job_id}/heat.json"
    return doc


def _keypoints(person: Any) -> dict[str, list[float]] | None:
    """`{joint: [x, y, z]}` for all 17 joints of a pose3d person, each seen (conf >= MIN_CONF), else None."""
    joints = person.get("joints") if isinstance(person, dict) else None
    if not isinstance(joints, dict):
        return None
    out: dict[str, list[float]] = {}
    for name in JOINTS:
        j = joints.get(name)
        xyz = [j.get(k) for k in "xyz"] if isinstance(j, dict) else []
        conf = j.get("conf", 1.0) if isinstance(j, dict) else 0
        ok = len(xyz) == 3 and all(isinstance(v, (int, float)) and math.isfinite(v) for v in xyz)
        if not ok or not isinstance(conf, (int, float)) or conf < MIN_CONF:
            return None
        out[name] = [float(v) for v in xyz]
    return out


def _bend_deg(a: list[float], b: list[float], c: list[float]) -> float:
    """The angle between a->b and b->c: 0 for a straight limb."""
    u = [b[i] - a[i] for i in range(3)]
    v = [c[i] - b[i] for i in range(3)]
    nu, nv = math.hypot(*u), math.hypot(*v)
    if nu == 0 or nv == 0:
        return 180.0
    cos = sum(u[i] * v[i] for i in range(3)) / (nu * nv)
    return math.degrees(math.acos(max(-1.0, min(1.0, cos))))


def rest_frame(header: Any, pose3d: Any) -> dict[str, Any] | None:
    """The rest document for a mesh header and a pose3d file, or None when no mesh frame has a usable person.

    Walks the mesh header's frames in order. A frame counts when it has a person and pose3d has the same frame number
    and person id with all 17 joints seen. The first one with both elbows bent under MAX_BEND_DEG wins; when none
    is that straight, the one with the smallest larger-elbow bend wins and `straight` is false. `motion` lists the
    usable frames (up to MOTION_MAX, evenly spread) with their joints, so the skin's weights see the whole take.
    """
    mesh_frames = header.get("frames") if isinstance(header, dict) else None
    pose_frames = pose3d.get("frames") if isinstance(pose3d, dict) else None
    if not isinstance(mesh_frames, list) or not isinstance(pose_frames, list):
        return None
    by_frame = {f.get("frame"): f for f in pose_frames if isinstance(f, dict)}
    best: tuple[float, int, dict[str, Any]] | None = None
    usable: list[tuple[int, dict[str, list[float]]]] = []
    for index, mf in enumerate(mesh_frames):
        people = mf.get("people") if isinstance(mf, dict) else None
        if not people or not isinstance(people[0], dict):
            continue
        pf = by_frame.get(mf.get("frame"))
        match = [p for p in (pf.get("people") or []) if isinstance(p, dict) and p.get("id") == people[0].get("id")] if pf else []
        joints = _keypoints(match[0]) if match else None
        if joints is None:
            continue
        usable.append((index, joints))
        bend = max(_bend_deg(*(joints[n] for n in arm)) for arm in ARMS)
        if (best is None or bend < best[0]) and (best is None or best[0] >= MAX_BEND_DEG):
            best = (bend, index, {"frame": mf.get("frame"), "joints": joints})
    if best is None:
        return None
    bend, index, found = best
    return {"schema": REST_SCHEMA, "frame": found["frame"], "index": index, "bend_deg": round(bend, 1),
            "straight": bend < MAX_BEND_DEG, "joints": {n: [round(v, 4) for v in xyz] for n, xyz in found["joints"].items()},
            "motion": _motion(usable)}


def _motion(usable: list[tuple[int, dict[str, list[float]]]]) -> list[dict[str, Any]]:
    """Up to MOTION_MAX usable frames spread evenly over the take, each `{index, joints}` with the 17 joints in JOINTS
    order (4 decimals): what the browser weighs the skin over (docs/specs/person-skin.md AC-PS17)."""
    step = max(1, math.ceil(len(usable) / MOTION_MAX))
    return [{"index": i, "joints": [[round(v, 4) for v in j[n]] for n in JOINTS]} for i, j in usable[::step]]


def rest(jobs_root: Path, job_id: str, who: str) -> dict[str, Any] | None:
    """The rest document of `who` for done follow job `job_id`; None when the gate, a file or a usable frame is missing."""
    folder = mesh_dir(jobs_root, job_id, who)
    header_path, pose_path = _regular(folder, "mesh3d.json"), (folder / "pose3d.json") if folder is not None else None
    if header_path is None or pose_path is None or not pose_path.is_file() or pose_path.is_symlink():
        return None
    from part7 import skin_weights  # imported here: skin_weights reads the bin through take_load, which imports this module

    taken = skin_weights.stamp(folder)  # before the reads, so the cache key never outdates what was read
    header = job_lookup.read_json(header_path)
    doc = rest_frame(header, job_lookup.read_json(pose_path))
    if doc is not None:
        shipped = skin_weights.weights(folder, header, doc, taken)
        if shipped is not None:
            doc["weights"] = shipped
    return doc


def handle(h: Any, method: str, route: str) -> bool:
    """Answer the mesh index and the mesh files; False for any other route."""
    parts = route.split("/")
    if method not in ("GET", "HEAD") or len(parts) < 3 or parts[0] != "results":
        return False
    is_index = len(parts) == 3 and parts[2] == INDEX
    is_file = len(parts) == 5 and parts[2] == "mesh"
    if not (is_index or is_file):
        return False
    job_id = parts[1]
    if not jobs.JOB_ID_RE.match(job_id):
        h._error(404, MSG_GONE)
        return True
    root = h.app.queue.job_dir(job_id).parent
    if is_index:
        doc = index(root, job_id)
        h._json(200, doc) if doc is not None else h._error(404, MSG_GONE)
        return True
    if parts[4] == REST:
        doc = rest(root, job_id, parts[3])
        h._json(200, doc) if doc is not None else h._error(404, MSG_GONE)
        return True
    path = mesh_file(root, job_id, parts[3], parts[4])
    if path is None:
        h._error(404, MSG_GONE)
        return True
    h._send(200, path.read_bytes(), FILES[parts[4]])
    return True
