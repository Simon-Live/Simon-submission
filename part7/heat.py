"""Heat on your own body: per-vertex movement error on the follower's SAM 3D Body mesh (docs/specs/heat.md, TICKET-274).

For each follower mesh frame the trainer's bone directions at the DTW-aligned moment (`replay.json`) are applied to the
follower's own skeleton and bone lengths (`heat_rig.retarget`), which moves the follower's real mesh into the trainer's
pose with the follower's body shape. The distance each vertex travels is its heat. Hands and feet are masked (their
transfer drifts). The heat is smoothed over the mesh faces so the colour is continuous.

Files, written once per job beside the follower's mesh and served by `handle`. They follow contract H1 of the web lane
(format `part7.heat/1`, fixture `tests/part7/fixtures/heat`): `heat.json` = {format, vertex_count, max_m, frames: [{t_ms}],
bin, bin_bytes, masked_labels} and `heat.bin` = frames x vertex_count bytes, frame-major, byte v = v / 255 x max_m metres,
masked vertices 0. The analysis (worst moment, per-region means) goes in `heat.meta.json`, which the route does not serve.
`GET results/<job>/heat.json|heat.bin` answers a done follow job that has a follower mesh and a `replay.json`; 404 else.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
import struct
import threading
from typing import Any

from part7 import heat_rig as rig, job_lookup, jobs, mesh_files, take_rig

FORMAT = "part7.heat/1"  # contract H1, shared with web/heat/heat-data.js
MASKED_LABELS = ["left_wrist", "right_wrist", "left_ankle", "right_ankle"]
NAMES = {"json": ("heat.json", "application/json; charset=utf-8"), "bin": ("heat.bin", "application/octet-stream")}
META = "heat.meta.json"
MIN_SCALE_M = 0.02
SMOOTH_PASSES = 2
META_VERSION = 3  # 2: frames past the aligned part are `unaligned`; 3: regions from the take's motion (AC-H7); older is rebuilt
HEAD_LABELS = ("nose", "left_eye", "right_eye", "left_ear", "right_ear")
MASKED = ("left_hand", "right_hand", "left_foot", "right_foot")
REGION_JOINTS = {
    "head": list(HEAD_LABELS), "torso": ["left_shoulder", "right_shoulder", "left_hip", "right_hip"],
    **{f"{s}_{r}": j for s in rig.SIDES for r, j in (("upper_arm", [f"{s}_shoulder", f"{s}_elbow"]),
                                                      ("forearm", [f"{s}_elbow", f"{s}_wrist"]),
                                                      ("thigh", [f"{s}_hip", f"{s}_knee"]),
                                                      ("shin", [f"{s}_knee", f"{s}_ankle"]))},
}
MSG_GONE = "This result is not available."
_lock = threading.Lock()


class Mesh:
    """One person's decoded mesh: faces, per-vertex joint labels and `frames` of (frame number, t_ms, vertices or None)."""

    def __init__(self, names: list[str], labels: list[int], faces: list[tuple[int, int, int]],
                 frames: list[tuple[Any, float, Any, list[tuple[float, float, float]] | None]], sha: str) -> None:
        self.names, self.labels, self.faces, self.frames, self.sha = names, labels, faces, frames, sha


def read_mesh(header: Any, data: bytes) -> Mesh | None:
    """Decode a Part 2 `mesh3d` pair, or None when the header or bin is not what it says."""
    try:
        n, nf = int(header["vertex_count"]), int(header["face_count"])
        fmt = {"uint16": ("H", 2), "uint32": ("I", 4)}[header["faces"]["dtype"]]
        unit = float(header["vertices"]["unit_m"])
        lab_off, names = int(header["vertex_joint"]["offset"]), list(header["vertex_joint"]["names"])
        flat = struct.unpack_from(f"<{nf * 3}{fmt[0]}", data, int(header["faces"]["offset"]))
        labels = list(data[lab_off:lab_off + n])
        frames = []
        for fr in header["frames"]:
            person = (fr.get("people") or [None])[0]
            verts = None
            if person is not None:
                raw = struct.unpack_from(f"<{n * 3}h", data, int(person["offset"]))
                verts = [(raw[i] * unit, raw[i + 1] * unit, raw[i + 2] * unit) for i in range(0, n * 3, 3)]
            frames.append((fr.get("frame"), float(fr.get("t_ms", 0.0)), (person or {}).get("id"), verts))
    except (KeyError, TypeError, ValueError, IndexError, struct.error):
        return None
    if len(labels) != n or any(b >= len(names) for b in labels) or (flat and max(flat) >= n):
        return None
    return Mesh(names, labels, [tuple(flat[i:i + 3]) for i in range(0, len(flat), 3)], frames, str(header.get("bin_sha256", "")))  # type: ignore[misc]


def skeleton(person: Any) -> rig.Skeleton | None:
    """`{joint: (x, y, z)}` of a pose3d person with all 17 joints seen, else None."""
    kp = mesh_files._keypoints(person)
    return {k: (v[0], v[1], v[2]) for k, v in kp.items()} if kp else None


BONE_REGION = {"hips": "torso", "spine": "torso", "chest": "torso", "neck": "head", "head": "head",
               **{f"{s}{B}": f"{s}_{r}" for s in rig.SIDES for B, r in (("UpperArm", "upper_arm"), ("LowerArm", "forearm"),
                                                                       ("UpperLeg", "thigh"), ("LowerLeg", "shin"))}}
END_LIMB = {"wrist": ("UpperArm", "LowerArm", "hand"), "ankle": ("UpperLeg", "LowerLeg", "foot")}


def assign_regions(mesh: Mesh, frames: list[tuple[list[rig.Vec], rig.Skeleton]]) -> list[str]:
    """The body region of every vertex: the bone it stays nearest over the take (`take_rig.motion_weights`, the person
    skin's rule, docs/specs/person-skin.md AC-PS17), mapped to the overlay's regions. `frames` is (vertices, skeleton)
    of the take's scored frames, in order. Part 2's nearest-joint label is not trusted for the region: with the arms
    down it names an elbow or wrist for the side of the waist. It only marks hands and feet, and only on a vertex that
    follows that same arm or leg (docs/specs/heat.md AC-H7)."""
    sample = take_rig.motion_sample(len(frames), 0)
    bones, _ = take_rig.motion_weights([(frames[k][0], take_rig.derive(frames[k][1])) for k in sample])
    out = []
    for (b0, _), label in zip(bones, mesh.labels):
        bone = take_rig.NAMES[b0]
        side, _, joint = mesh.names[label].partition("_")
        end = END_LIMB.get(joint)
        if end and side in rig.SIDES and bone in (side + end[0], side + end[1]):
            out.append(f"{side}_{end[2]}")
        else:
            out.append(BONE_REGION[bone])
    return out


def neighbours(mesh: Mesh, masked: list[bool]) -> list[list[int]]:
    """Unmasked mesh neighbours of every vertex (by shared faces)."""
    sets: list[set[int]] = [set() for _ in masked]
    for a, b, c in mesh.faces:
        for x, y in ((a, b), (b, c), (c, a)):
            if not masked[y]:
                sets[x].add(y)
            if not masked[x]:
                sets[y].add(x)
    return [sorted(s) for s in sets]


def smooth(heat: list[float], adj: list[list[int]], masked: list[bool]) -> list[float]:
    for _ in range(SMOOTH_PASSES):
        heat = [0.0 if masked[i] or not adj[i] else 0.5 * heat[i] + 0.5 * sum(heat[j] for j in adj[i]) / len(adj[i])
                for i in range(len(heat))]
    return heat


def frame_heat(verts: list[rig.Vec], regions: list[str], mine: rig.Skeleton, theirs: rig.Skeleton) -> list[float]:
    """Metres each vertex travels when the follower's body takes the trainer's bone directions (0 for masked regions)."""
    affine = {}
    for name, (pivot, rot, new) in rig.retarget(mine, theirs).items():
        t = rig.sub(new, rig.apply(rot, pivot))
        affine[name] = (rig.sub(rot[0], (1, 0, 0)), rig.sub(rot[1], (0, 1, 0)), rig.sub(rot[2], (0, 0, 1)), t)
    out = []
    for p, region in zip(verts, regions):
        m = affine.get(region)
        if m is None:
            out.append(0.0)
            continue
        x, y, z = p
        dx = m[0][0] * x + m[0][1] * y + m[0][2] * z + m[3][0]
        dy = m[1][0] * x + m[1][1] * y + m[1][2] * z + m[3][1]
        dz = m[2][0] * x + m[2][1] * y + m[2][2] * z + m[3][2]
        out.append(math.sqrt(dx * dx + dy * dy + dz * dz))
    return out


def aligned_until(replay: Any) -> float | None:
    """Follower time (s) where the DTW-aligned part ends: `aligned_until_s` (Part 5 1.14.0, TICKET-085) when present,
    else the follower time of the last follower frame in `exp_to_fol`. None when neither can be read."""
    try:
        if isinstance(replay.get("aligned_until_s"), (int, float)):
            return float(replay["aligned_until_s"])
        return float(replay["follower_t"][max(int(i) for i in replay["exp_to_fol"])])
    except (AttributeError, KeyError, TypeError, ValueError, IndexError):
        return None


def trainer_pick(replay: Any, t_s: float) -> rig.Skeleton | None:
    """The trainer's skeleton aligned (DTW, `exp_to_fol`) with the follower's moment `t_s`, or None."""
    try:
        times, e2f, joints = replay["follower_t"], replay["exp_to_fol"], replay["joints"]
        idx = min(range(len(times)), key=lambda i: abs(times[i] - t_s)) if times else 0
        e = min(range(len(e2f)), key=lambda i: abs(e2f[i] - idx))
        return {n: (float(c[0]), float(c[1]), float(c[2])) for n, c in zip(joints, replay["expected"][e])}
    except (KeyError, TypeError, ValueError, IndexError):
        return None


def build(mesh: Mesh, pose3d: Any, replay: Any) -> dict[str, Any] | None:
    """`{doc, bin}` for a follower mesh, its pose3d and replay.json; None when no frame can be scored."""
    by_frame = {f.get("frame"): f for f in (pose3d.get("frames") or []) if isinstance(f, dict)} if isinstance(pose3d, dict) else {}
    rows: list[tuple[Any, list[float] | None, dict[str, Any] | None]] = []
    until = aligned_until(replay)
    fps = replay.get("fps") if isinstance(replay, dict) else None
    slack = 0.5 / float(fps) if isinstance(fps, (int, float)) and fps > 0 else 0.0  # mesh and pose clocks differ by under a frame
    scored: list[tuple[Any, list[rig.Vec], rig.Skeleton, rig.Skeleton] | tuple[Any, None, Any, None]] = []
    for number, t_ms, pid, verts in mesh.frames:
        if until is not None and t_ms / 1000.0 > until + slack:
            scored.append((number, None, {"unaligned": True}, None))  # past the aligned part: the trainer is not at this moment
            continue
        match = [p for p in ((by_frame.get(number) or {}).get("people") or []) if isinstance(p, dict) and p.get("id") == pid]
        mine, theirs = (skeleton(match[0]) if match else None), trainer_pick(replay, t_ms / 1000.0)
        if verts is None or mine is None or theirs is None or any(j not in theirs for j in mine):
            scored.append((number, None, None, None))
            continue
        scored.append((number, verts, mine, theirs))
    usable = [(verts, mine) for _, verts, mine, theirs in scored if theirs is not None]
    if not usable:
        return None
    regions = assign_regions(mesh, usable)
    for number, verts, mine, theirs in scored:
        rows.append((number, None, mine) if theirs is None else (number, frame_heat(verts, regions, mine, theirs), {}))
    masked = [r in MASKED for r in regions]
    adj = neighbours(mesh, masked)
    rows = [(n, smooth(h, adj, masked) if h is not None else None, m) for n, h, m in rows]
    return _pack(mesh, regions, masked, rows, until)


def _pack(mesh: Mesh, regions: list[str], masked: list[bool], rows: list[tuple[Any, list[float] | None, Any]],
          until: float | None = None) -> dict[str, Any]:
    peak = max((max(h) for _, h, _ in rows if h), default=0.0)
    scale = max(MIN_SCALE_M, round(peak + 0.0005, 3))  # max_m
    names = sorted(set(regions))
    members = {r: [i for i, x in enumerate(regions) if x == r] for r in names}
    means: dict[str, list[float | None]] = {r: [] for r in names if r not in MASKED}
    frames_doc, body = [], bytearray()
    for (number, heat, flags), (_, t_ms, _, _) in zip(rows, mesh.frames):
        if heat is None:
            body += bytes(len(masked))
            frames_doc.append({"frame": number, "t_ms": t_ms, "valid": False, **({"unaligned": True} if (flags or {}).get("unaligned") else {})})
            for r in means:
                means[r].append(None)
            continue
        body += bytes(min(255, int(round(h / scale * 255))) for h in heat)
        per = {r: sum(heat[i] for i in members[r]) / len(members[r]) for r in means}
        for r, v in per.items():
            means[r].append(round(v, 5))
        hot = max(per, key=lambda r: per[r])
        frames_doc.append({"frame": number, "t_ms": t_ms, "valid": True, "peak_m": round(max(heat), 5),
                           "region": hot, "region_mean_m": round(per[hot], 5), "joints": REGION_JOINTS[hot]})
    valid = [i for i, f in enumerate(frames_doc) if f["valid"]]
    worst = max(valid, key=lambda i: frames_doc[i]["region_mean_m"]) if valid else 0
    contract = {"format": FORMAT, "vertex_count": len(masked), "max_m": scale, "frames": [{"t_ms": t} for _, t, _, _ in mesh.frames],
                "bin": "heat.bin", "bin_bytes": len(body), "masked_labels": MASKED_LABELS}
    meta = {"format": FORMAT, "meta_version": META_VERSION, "aligned_until_s": until, "mesh_sha256": mesh.sha, "masked_regions": list(MASKED), "smooth_passes": SMOOTH_PASSES,
            "regions": {r: {"vertices": len(members[r]), "masked": r in MASKED, "joints": REGION_JOINTS.get(r, [])} for r in names},
            "worst": {"index": worst, **{k: frames_doc[worst][k] for k in ("frame", "t_ms")}, **({k: frames_doc[worst][k]
                      for k in ("region", "region_mean_m", "peak_m", "joints")} if valid else {})},
            "frames": frames_doc, "mean_by_region_m": means,
            "method": "trainer bone directions on the follower's own skeleton and mesh; body shape removed; hands and feet masked"}
    return {"doc": contract, "meta": meta, "bin": bytes(body), "mask": masked}


NEAREST_S = 0.25  # a fault time further than this from every valid heat frame has no heat


def nearest_valid(meta: dict[str, Any], t_s: float) -> int | None:
    """Index of the valid heat frame nearest `t_s` seconds, or None when none is within NEAREST_S. Unaligned frames are
    not valid, so they are never returned."""
    best = min((i for i, f in enumerate(meta.get("frames") or []) if f.get("valid")),
               key=lambda i: abs(meta["frames"][i]["t_ms"] / 1000.0 - t_s), default=None)
    return best if best is not None and abs(meta["frames"][best]["t_ms"] / 1000.0 - t_s) <= NEAREST_S else None


def open_moment(meta: dict[str, Any], analysis: Any) -> dict[str, Any] | None:
    """Where the Heat view opens (AC-H4): Part 5's lead fault (`faults[0]`, the first row of Mistakes you repeated) on the
    nearest valid frame; with no fault, the hottest valid frame. Unaligned frames are never chosen. None when no frame is valid."""
    frames = meta.get("frames") or []
    faults = [f for f in ((analysis or {}).get("faults") or []) if isinstance(f, dict) and isinstance(f.get("at_s"), (int, float))]
    pick: dict[str, Any] | None = None
    if faults:
        i = nearest_valid(meta, float(faults[0]["at_s"]))
        if i is not None:
            pick = {"index": i, "source": "fault", "fault": {k: faults[0].get(k) for k in ("measure", "at_s", "joints")}}
    if pick is None:
        keep = [i for i, f in enumerate(frames) if f.get("valid")]
        if not keep:
            return None
        pick = {"index": max(keep, key=lambda i: frames[i]["region_mean_m"]), "source": "heat", "fault": None}
    f = frames[pick["index"]]
    return {**pick, "frame": f["frame"], "t_ms": f["t_ms"], "region": f["region"]}


def decode_bin(doc: dict[str, Any], data: bytes) -> list[list[int]]:
    """Rows of uint8 heat of a heat.json and heat.bin pair; ValueError when they disagree."""
    n, nf = int(doc["vertex_count"]), len(doc["frames"])
    if len(data) != n * nf or len(data) != doc["bin_bytes"]:
        raise ValueError("heat.bin size does not match heat.json")
    return [list(data[i * n:(i + 1) * n]) for i in range(nf)]


def eligible(folder: Path | None) -> bool:
    """Cheap check (no build) that the follower's part2 `folder` has what heat needs; `mesh.json` uses it for its optional `heat` field."""
    if folder is None or mesh_files._regular(folder, "mesh3d.json") is None or mesh_files._regular(folder, "mesh3d.bin") is None:
        return False
    replay = folder.parent / "replay.json"
    mirror = job_lookup.read_json(folder.parent / "follower.json")
    return replay.is_file() and not replay.is_symlink() and not (isinstance(mirror, dict) and (mirror.get("mirror") or {}).get("applied"))


def files(jobs_root: Path, job_id: str) -> tuple[Path, Path] | None:
    """Paths of the cached (heat.json, heat.bin), made first when absent; None when the job cannot show heat."""
    folder = mesh_files.mesh_dir(jobs_root, job_id, "you")
    if folder is None:
        return None
    header_p, bin_p = mesh_files._regular(folder, "mesh3d.json"), mesh_files._regular(folder, "mesh3d.bin")
    follower = folder.parent
    replay_p, out = follower / "replay.json", follower / "heat"
    if header_p is None or bin_p is None or not replay_p.is_file() or replay_p.is_symlink():
        return None
    header, replay = job_lookup.read_json(header_p), job_lookup.read_json(replay_p)
    mirror = job_lookup.read_json(follower / "follower.json")
    if (isinstance(mirror, dict) and (mirror.get("mirror") or {}).get("applied")) or not isinstance(replay, dict):
        return None  # a mirrored follower is not in the mesh's frame: no heat rather than a wrong one
    jp, bp, mp = out / NAMES["json"][0], out / NAMES["bin"][0], out / META
    with _lock:
        cached = job_lookup.read_json(mp) if jp.is_file() and bp.is_file() else None
        if isinstance(cached, dict) and cached.get("format") == FORMAT and cached.get("meta_version") == META_VERSION and cached.get("mesh_sha256") == str((header or {}).get("bin_sha256", "")):
            return jp, bp
        mesh = read_mesh(header, bin_p.read_bytes())
        built = build(mesh, job_lookup.read_json(folder / "pose3d.json"), replay) if mesh is not None else None
        if built is None:
            return None
        out.mkdir(parents=True, exist_ok=True)
        for path, payload in ((bp, built["bin"]), (mp, json.dumps(built["meta"]).encode("utf-8")), (jp, json.dumps(built["doc"]).encode("utf-8"))):
            tmp = path.with_name(path.name + ".tmp")
            tmp.write_bytes(payload)
            os.replace(tmp, path)
    return jp, bp


def handle(h: Any, method: str, route: str) -> bool:
    """Answer `results/<job>/heat.json` and `heat.bin`; False for any other route."""
    parts = route.split("/")
    if method not in ("GET", "HEAD") or len(parts) != 3 or parts[0] != "results" or parts[2] not in ("heat.json", "heat.bin"):
        return False
    if not jobs.JOB_ID_RE.match(parts[1]):
        h._error(404, MSG_GONE)
        return True
    found = files(h.app.queue.job_dir(parts[1]).parent, parts[1])
    if found is None:
        h._error(404, MSG_GONE)
        return True
    which = "json" if parts[2] == "heat.json" else "bin"
    h._send(200, found[0 if which == "json" else 1].read_bytes(), NAMES[which][1])
    return True
