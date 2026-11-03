"""Routes for the life-size AR take: a rigged, animated GLB and USDZ of one person (docs/specs/take-ar.md, TICKET-282).

- `GET results/<job>/take-ar.json` answers a done follow job with, per person (`trainer`, `you`), the file URLs (relative
  to the app's base path) and the animation length, or null when that person has no mesh pair and pose3d file. The page
  shows its "See it in your room" button only for a person whose entry is not null. Always 200 for such a job, so a result
  without a mesh makes no failing request; 404 for any other id, kind or state.
- `GET results/<job>/take/<trainer|you>.glb` and `.usdz`, with `?ghost=1` to add the other person as a see-through ghost
  on the same spot. 404 when the person's files are absent or unreadable, or a ghost is asked for and the other person
  has none.
The files are made from the Part 2 measurement on request and kept in a small memory cache. Same gate as mesh_files.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from part7 import auth, identity as ident, job_lookup, jobs, mesh_files, take_glb, take_load, take_rig, take_usdz

SCHEMA = "simon.take-ar.v1"
WHO = mesh_files.WHO
KINDS = {"glb": "model/gltf-binary", "usdz": "model/vnd.usdz+zip"}
MAX_BYTES = 15 * 1024 * 1024  # a venue network carries this in a few seconds; longer takes lose frames, see `thinned`
CACHE_MAX = 6
MSG_GONE = "This result is not available."
_FILES = ("mesh3d.json", "mesh3d.bin", "pose3d.json")
_cache: OrderedDict[tuple[Any, ...], bytes] = OrderedDict()
_lock = threading.Lock()


def may_view(h: Any, job_id: str) -> bool:
    """A take with an owner (it was made signed in) is for that person only; an anonymous take is open to whoever holds its id,
    as every other result route is."""
    owner = ident.owner_of_job(h.app.state, job_id)
    return owner is None or auth.current_user(h) == owner


def _ready(folder: Path | None) -> bool:
    return folder is not None and all((folder / n).is_file() and not (folder / n).is_symlink() for n in _FILES)


def _duration_s(folder: Path) -> float | None:
    header = job_lookup.read_json(folder / "mesh3d.json")
    frames = header.get("frames") if isinstance(header, dict) else None
    try:
        return round((float(frames[-1]["t_ms"]) - float(frames[0]["t_ms"])) / 1000.0, 3)
    except (TypeError, KeyError, IndexError, ValueError):
        return None


def index(jobs_root: Path, job_id: str) -> dict[str, Any] | None:
    """The take-ar document for done follow job `job_id`, or None when it is not one."""
    return from_folders(mesh_files._folders(jobs_root, job_id), job_id)


def from_folders(folders: dict[str, Path | None] | None, job_id: str) -> dict[str, Any] | None:
    """`index` for folders already looked up (mesh_files.index reads the job record once)."""
    if folders is None:
        return None
    ready = {who: _ready(folders[who]) for who in WHO}
    doc: dict[str, Any] = {"schema": SCHEMA}
    for who in WHO:
        if not ready[who]:
            doc[who] = None
            continue
        base = f"api/results/{job_id}/take/{who}"
        other = WHO[1 - WHO.index(who)]
        entry: dict[str, Any] = {"glb": f"{base}.glb", "usdz": f"{base}.usdz", "duration_s": _duration_s(folders[who])}
        if ready[other]:
            entry.update({"glb_ghost": f"{base}.glb?ghost=1", "usdz_ghost": f"{base}.usdz?ghost=1"})
        doc[who] = entry
    return doc


def thinned(fig: take_rig.Figure, stride: int) -> take_rig.Figure:
    """The figure with every `stride`-th frame (and always the last), for a file that would be too large."""
    keep = sorted(set(range(0, len(fig.times), stride)) | {len(fig.times) - 1})
    copy = take_rig.Figure(fig.name, fig.rest_joints, fig.bone_head, fig.positions, fig.faces, fig.bones, fig.weights)
    copy.times = [fig.times[k] for k in keep]
    copy.rotations = [fig.rotations[k] for k in keep]
    copy.hips = [fig.hips[k] for k in keep]
    copy.measured = [fig.measured[k] for k in keep]
    copy.ground = [fig.ground[k] for k in keep]
    return copy


def make(kind: str, figures: list[take_rig.Figure], extras: dict[str, Any], max_bytes: int = MAX_BYTES) -> bytes:
    """The file of `kind` (glb or usdz) for `figures`; frames are dropped, evenly, until it is under `max_bytes`."""
    stride = 1
    while True:
        use = figures if stride == 1 else [thinned(f, stride) for f in figures]
        data = take_glb.build_glb(use, extras) if kind == "glb" else take_usdz.build_usdz(use)
        if len(data) <= max_bytes or stride >= 64:
            return data
        stride *= 2


def _signature(folder: Path) -> tuple[int, ...]:
    sig: list[int] = []
    for n in _FILES:
        st = (folder / n).stat()
        sig += [st.st_mtime_ns, st.st_size]
    return tuple(sig)


def render(jobs_root: Path, job_id: str, who: str, kind: str, ghost: bool) -> bytes | None:
    """The take file, or None when the gate, a file or a usable frame is missing."""
    if who not in WHO or kind not in KINDS:
        return None
    folders = mesh_files._folders(jobs_root, job_id, trainer_too=who == "trainer" or ghost)
    if folders is None or not _ready(folders[who]):
        return None
    other = WHO[1 - WHO.index(who)]
    if ghost and not _ready(folders[other]):
        return None
    used = [who] + ([other] if ghost else [])
    try:
        key = (job_id, kind, tuple(used), tuple(_signature(folders[w]) for w in used))  # type: ignore[arg-type]
    except OSError:
        return None
    with _lock:
        hit = _cache.get(key)
        if hit is not None:
            _cache.move_to_end(key)
            return hit
    figures = [take_load.load_figure(folders[w], w) for w in used]  # type: ignore[arg-type]
    if any(f is None for f in figures):
        return None
    extras = {"job": job_id, "person": who, "ghost": ghost, "source": "SAM 3D Body mesh and pose, no video frames or textures"}
    data = make(kind, [f for f in figures if f is not None], extras)
    with _lock:
        _cache[key] = data
        while len(_cache) > CACHE_MAX:
            _cache.popitem(last=False)
    return data


def handle(h: Any, method: str, route: str) -> bool:
    """Answer the take-ar index and the take files; False for any other route."""
    parts = route.split("/")
    if method not in ("GET", "HEAD") or len(parts) < 3 or parts[0] != "results":
        return False
    is_index = len(parts) == 3 and parts[2] == "take-ar.json"
    is_file = len(parts) == 4 and parts[2] == "take" and "." in parts[3]
    if not (is_index or is_file):
        return False
    if not jobs.JOB_ID_RE.match(parts[1]):
        h._error(404, MSG_GONE)
        return True
    if not may_view(h, parts[1]):
        h._error(404, MSG_GONE)
        return True
    root = h.app.queue.job_dir(parts[1]).parent
    if is_index:
        doc = index(root, parts[1])
        h._json(200, doc) if doc is not None else h._error(404, MSG_GONE)
        return True
    who, _, kind = parts[3].rpartition(".")
    ghost = parse_qs(urlsplit(h.path).query).get("ghost", [""])[0] == "1"
    data = render(root, parts[1], who, kind, ghost)
    if data is None:
        h._error(404, MSG_GONE)
        return True
    name = f"simon-{who}-{parts[1]}{'-ghost' if ghost else ''}.{kind}"
    send_file(h, data, kind, name)
    return True


def send_file(h: Any, data: bytes, kind: str, name: str) -> None:
    h._send(200, data, KINDS[kind], {"Content-Disposition": f'inline; filename="{name}"', "X-Content-Type-Options": "nosniff"})
